from __future__ import annotations

from collections import defaultdict

from access.authorization.admin_role_protection import (
    PROTECTED_ADMIN_SLUG,
    viewer_may_see_admin_role,
)
from access.authorization.platform import is_platform_superuser
from access.constants import MembershipStatus, SystemRoleSlug
from access.constants.rbac_cache import (
    PERMISSIONS_CATALOG_CACHE_KEY,
    ROLES_CATALOG_CACHE_KEY,
)
from access.services.cache_utils import safe_cache_delete, safe_cache_get, safe_cache_set
from access.constants.tenant_eligibility import is_tenant_rbac_eligible
from access.models import (
    Permission,
    PermissionOverride,
    Role,
    RolePermission,
    StaffAssignment,
    StaffMembership,
)
from access.selectors import membership_selector, permission_selector, role_selector
from access.services.assignment_scope import (
    filter_assignments_for_authorization,
    filter_assignments_in_scope,
    resolve_assignment_branch_ids,
)
from core.exceptions import (
    AmbiguousTenantException,
    NoTenantContextException,
    TenantAccessDeniedException,
    TenantContextMismatchException,
)
from core.exceptions.tenant import TenantNotFoundException
from tenants.models import Tenant

EFFECTIVE_PERMISSIONS_CACHE_KEY = "rbac:effective_permissions:v1:{user_id}:{tenant_id}"
PERMISSIONS_CATALOG_TTL = 60 * 60
ROLES_CATALOG_TTL = 60 * 30
EFFECTIVE_PERMISSIONS_TTL = 60 * 5


class RbacBusinessLogicLayer:
    selector = permission_selector
    membership_selector = membership_selector

    @staticmethod
    def is_tenant_rbac_eligible(tenant: Tenant) -> bool:
        return is_tenant_rbac_eligible(tenant)

    def get_effective_permissions(self, *, user, tenant, use_cache: bool = True) -> list[str]:
        breakdown = self.get_effective_permissions_breakdown(
            user=user, tenant=tenant, use_cache=use_cache
        )
        return breakdown["permissions"]

    def get_effective_permissions_breakdown(
        self,
        *,
        user,
        tenant,
        branch_id=None,
        use_cache: bool = True,
    ) -> dict:
        if is_platform_superuser(user):
            # Platform superusers hold every permission in every tenant.
            every = sorted(Permission.objects.values_list("slug", flat=True))
            return {
                "permissions": every,
                "inherited_permissions": every,
                "overrides": [],
            }

        tenant = self._ensure_tenant_with_owner(tenant)
        if not self.is_tenant_rbac_eligible(tenant):
            return {
                "permissions": [],
                "inherited_permissions": [],
                "overrides": [],
            }

        cache_key = self._effective_permissions_cache_key(user.id, tenant.id)
        if use_cache and branch_id is None:
            cached = self._coerce_effective_permissions_cache(
                safe_cache_get(cache_key)
            )
            if cached is not None:
                return cached

        inherited, overrides = self._resolve_inherited_and_overrides(
            user=user, tenant=tenant, branch_id=branch_id
        )
        effective = self._apply_permission_overrides(inherited, overrides)
        effective = self._apply_feature_flags(tenant=tenant, permissions=effective)
        effective = self._apply_read_manage_filter(
            user=user, tenant=tenant, permissions=effective
        )

        payload = {
            "permissions": sorted(effective),
            "inherited_permissions": sorted(inherited),
            "overrides": [
                {
                    "permission": slug,
                    "effect": override.effect,
                }
                for override in overrides
                if (slug := self._permission_slug_from_override(override))
            ],
        }

        if branch_id is None:
            safe_cache_set(cache_key, payload, EFFECTIVE_PERMISSIONS_TTL)
        return payload

    def resolve_effective_permission_slugs(
        self,
        *,
        user,
        tenant,
        branch_id=None,
    ) -> set[str]:
        breakdown = self.get_effective_permissions_breakdown(
            user=user,
            tenant=tenant,
            branch_id=branch_id,
            use_cache=branch_id is None,
        )
        return set(breakdown["permissions"])

    def _resolve_inherited_and_overrides(self, *, user, tenant, branch_id=None):
        role_slugs = self._gather_role_slugs(
            user=user, tenant=tenant, branch_id=branch_id
        )
        inherited = self._resolve_role_permissions(role_slugs)
        overrides = self._get_membership_overrides(user=user, tenant=tenant)
        return inherited, overrides

    def _gather_role_slugs(
        self, *, user, tenant, branch_id=None
    ) -> set[str]:
        slugs: set[str] = set()

        if not self.is_tenant_rbac_eligible(tenant):
            return slugs

        if self._is_owner(user=user, tenant=tenant):
            slugs.add(SystemRoleSlug.OWNER)

        membership = self.selector.get_active_membership(
            user_id=user.id, tenant_id=tenant.id
        )
        if membership is not None:
            assignments = filter_assignments_for_authorization(
                StaffAssignment.objects.filter(membership_id=membership.id)
            )
            if branch_id is not None:
                assignments = filter_assignments_in_scope(
                    assignments, branch_id=branch_id
                )
            assignment_roles = assignments.values_list("role__slug", flat=True).distinct()
            slugs.update(assignment_roles)

        return slugs

    def _resolve_role_permissions(self, role_slugs: set[str]) -> set[str]:
        if not role_slugs:
            return set()

        role_ids = Role.objects.filter(slug__in=role_slugs).values_list("id", flat=True)
        return self.selector.get_permission_slugs_for_roles(role_ids=role_ids)

    def _get_membership_overrides(self, *, user, tenant):
        membership = self.selector.get_active_membership(
            user_id=user.id, tenant_id=tenant.id
        )
        if membership is None:
            return []
        return list(
            PermissionOverride.objects.filter(membership_id=membership.id)
            .select_related("permission")
            .order_by("permission__slug")
        )

    @staticmethod
    def _permission_slug_from_override(override) -> str | None:
        permission = getattr(override, "permission", None)
        slug = getattr(permission, "slug", None)
        return slug or None

    @staticmethod
    def _apply_permission_overrides(
        inherited: set[str],
        overrides,
    ) -> set[str]:
        effective = set(inherited)
        for override in overrides:
            slug = RbacBusinessLogicLayer._permission_slug_from_override(override)
            if slug is None:
                continue
            if override.effect == "allow":
                effective.add(slug)
            elif override.effect == "deny":
                effective.discard(slug)

        deny_slugs = {
            slug
            for override in overrides
            if override.effect == "deny"
            and (slug := RbacBusinessLogicLayer._permission_slug_from_override(override))
        }
        allow_slugs = {
            slug
            for override in overrides
            if override.effect == "allow"
            and (slug := RbacBusinessLogicLayer._permission_slug_from_override(override))
        }
        return (effective | allow_slugs) - deny_slugs

    def _get_permissions_by_role_slugs(self, role_slugs: set[str]) -> dict[str, list[str]]:
        """Batch-load role→permission slugs in a single query."""
        if not role_slugs:
            return {}

        grouped: dict[str, list[str]] = defaultdict(list)
        for role_slug, permission_slug in (
            RolePermission.objects.filter(role__slug__in=role_slugs)
            .values_list("role__slug", "permission__slug")
        ):
            grouped[role_slug].append(permission_slug)

        return {slug: sorted(grouped.get(slug, [])) for slug in role_slugs}

    def _apply_overrides(self, *, user, tenant, permissions: set[str]) -> set[str]:
        _, overrides = self._resolve_inherited_and_overrides(user=user, tenant=tenant)
        return self._apply_permission_overrides(permissions, overrides)

    def _apply_feature_flags(self, *, tenant, permissions: set[str]) -> set[str]:
        """Identity. Feature flags are not backend authorization.

        ``Tenant.settings.featureFlags`` are tenant-level UI/rollout
        overrides consumed by the frontend (discover, navigation, console
        ``hasPermission``). Backend RBAC stays independent. Do not filter
        ``permissions`` here unless a later product decision plus tests
        define exact behavior for owner, admin, staff, branch scope,
        overrides, missing flags, and unknown flags.
        """
        return permissions

    def _apply_read_manage_filter(self, *, user, tenant, permissions: set[str]) -> set[str]:
        return permissions

    def get_permissions_for_role_slug(self, role_slug: str) -> list[str]:
        return self._get_permissions_by_role_slugs({role_slug}).get(role_slug, [])

    def resolve_tenant_context(self, *, user, request) -> Tenant:
        slug_header = request.META.get("HTTP_X_TENANT_SLUG", "").strip()
        id_header = request.META.get("HTTP_X_TENANT_ID", "").strip()

        tenant_from_slug = None
        tenant_from_id = None

        if slug_header:
            tenant_from_slug = (
                Tenant.objects.select_related("owner").filter(slug=slug_header).first()
            )
            if tenant_from_slug is None:
                raise TenantNotFoundException(detail=f"No tenant with slug '{slug_header}'.")

        if id_header:
            tenant_from_id = (
                Tenant.objects.select_related("owner").filter(id=id_header).first()
            )
            if tenant_from_id is None:
                raise TenantNotFoundException(detail=f"No tenant with id '{id_header}'.")

        if tenant_from_slug and tenant_from_id and tenant_from_slug.id != tenant_from_id:
            raise TenantContextMismatchException(
                detail="X-Tenant-Slug and X-Tenant-Id refer to different tenants."
            )

        if tenant_from_slug:
            tenant = tenant_from_slug
        elif tenant_from_id:
            tenant = tenant_from_id
        elif user.active_tenant_id:
            tenant = (
                Tenant.objects.select_related("owner")
                .filter(id=user.active_tenant_id)
                .first()
            )
            if tenant is None:
                raise TenantNotFoundException(detail="Active tenant not found.")
        else:
            tenant_ids = self._get_user_tenant_ids(user)
            if len(tenant_ids) == 1:
                tenant = Tenant.objects.select_related("owner").get(
                    id=next(iter(tenant_ids))
                )
            elif len(tenant_ids) == 0:
                raise NoTenantContextException()
            else:
                raise AmbiguousTenantException(
                    detail="User belongs to multiple tenants; specify X-Tenant-Slug."
                )

        self.assert_tenant_member(user=user, tenant=tenant)
        return tenant

    def assert_tenant_member(self, *, user, tenant) -> None:
        if is_platform_superuser(user):
            return
        tenant = self._ensure_tenant_with_owner(tenant)
        if not self.is_tenant_rbac_eligible(tenant):
            raise TenantAccessDeniedException(
                detail="Tenant is not eligible for RBAC access."
            )

        if self._is_owner(user=user, tenant=tenant):
            return

        membership = self.selector.get_active_membership(
            user_id=user.id, tenant_id=tenant.id
        )
        if membership is None:
            raise TenantAccessDeniedException(
                detail="Caller is not a member of this tenant."
            )

    def get_permissions_catalog(self) -> list[dict]:
        cached = safe_cache_get(PERMISSIONS_CATALOG_CACHE_KEY)
        if cached is not None:
            return cached

        catalog = [
            {
                "id": str(permission.id),
                "key": permission.slug,
                "resource": permission.resource,
                "action": permission.action,
                "description": permission.description,
            }
            for permission in role_selector.get_permission_queryset()
        ]
        safe_cache_set(PERMISSIONS_CATALOG_CACHE_KEY, catalog, PERMISSIONS_CATALOG_TTL)
        return catalog

    def get_roles_with_permissions(self, *, viewer=None) -> list[dict]:
        cached = safe_cache_get(ROLES_CATALOG_CACHE_KEY)
        if cached is None:
            roles = list(
                Role.objects.filter(system_role=True)
                .exclude(slug=PROTECTED_ADMIN_SLUG)
                .order_by("slug")
            )
            role_ids = [role.id for role in roles]
            permissions_by_role_id: dict = defaultdict(list)
            for role_id, permission_slug in (
                RolePermission.objects.filter(role_id__in=role_ids)
                .values_list("role_id", "permission__slug")
            ):
                permissions_by_role_id[role_id].append(permission_slug)

            cached = [
                {
                    "id": str(role.id),
                    "name": role.name,
                    "slug": role.slug,
                    "is_system_role": role.system_role,
                    "editable": False,
                    "permissions": sorted(permissions_by_role_id.get(role.id, [])),
                }
                for role in roles
            ]
            safe_cache_set(ROLES_CATALOG_CACHE_KEY, cached, ROLES_CATALOG_TTL)

        visible = [
            role for role in cached if role.get("slug") != PROTECTED_ADMIN_SLUG
        ]
        if not viewer_may_see_admin_role(viewer):
            return visible

        admin_role = Role.objects.filter(
            slug=PROTECTED_ADMIN_SLUG,
            system_role=True,
        ).first()
        if admin_role is None:
            return visible

        admin_permissions = sorted(
            RolePermission.objects.filter(role_id=admin_role.id).values_list(
                "permission__slug", flat=True
            )
        )
        admin_payload = {
            "id": str(admin_role.id),
            "name": admin_role.name,
            "slug": admin_role.slug,
            "is_system_role": admin_role.system_role,
            "editable": False,
            "permissions": admin_permissions,
        }
        return sorted([*visible, admin_payload], key=lambda item: item["slug"])

    def build_ownership_records(self, user) -> list[dict]:
        owner_profile = getattr(user, "owner_profile", None)
        if owner_profile is None:
            return []

        return [
            {
                "ownerId": str(owner_profile.id),
                "userId": str(user.id),
                "status": owner_profile.status,
                "plan": owner_profile.plan,
                "maxTenants": owner_profile.max_tenants,
                "billing": {
                    "customerId": owner_profile.billing_customer_id,
                    "billingEmail": owner_profile.billing_email,
                },
                "createdAt": owner_profile.created_at,
                "verifiedAt": owner_profile.verified_at,
            }
        ]

    def build_staff_assignment_records(self, user, *, viewer=None) -> list[dict]:
        viewer = viewer if viewer is not None else user
        records: list[dict] = []

        for membership in self.membership_selector.get_active_staff_memberships(user=user):
            for assignment in membership.assignments.all():
                if (
                    assignment.role.slug == PROTECTED_ADMIN_SLUG
                    and not viewer_may_see_admin_role(viewer)
                ):
                    continue
                records.append(
                    {
                        "assignmentId": str(assignment.id),
                        "staffId": str(membership.user_id),
                        "tenantId": str(membership.tenant_id),
                        "tenantIsActive": membership.tenant.is_active,
                        "tenantStatus": membership.tenant.status,
                        "branchIds": resolve_assignment_branch_ids(assignment),
                        "role": assignment.role.slug,
                        "mode": assignment.mode,
                        "status": assignment.status,
                        "validFrom": assignment.valid_from,
                        "validUntil": assignment.valid_until,
                        "grantedBy": (
                            str(assignment.granted_by_id)
                            if assignment.granted_by_id
                            else None
                        ),
                        "grantedAt": assignment.granted_at or assignment.created_at,
                    }
                )

        return records

    def build_tenant_role_records(self, user, *, viewer=None) -> list[dict]:
        viewer = viewer if viewer is not None else user
        seen: set[tuple[str, str]] = set()
        records: list[dict] = []
        needed_role_slugs: set[str] = set()

        owner_profile = getattr(user, "owner_profile", None)
        owned_tenants = []
        if owner_profile:
            owned_tenants = list(owner_profile.tenants.all())
            for tenant in owned_tenants:
                key = (str(tenant.id), SystemRoleSlug.OWNER)
                if key not in seen:
                    seen.add(key)
                    needed_role_slugs.add(SystemRoleSlug.OWNER)
                    records.append(
                        {
                            "tenant_id": str(tenant.id),
                            "tenant_slug": tenant.slug,
                            "is_active": tenant.is_active,
                            "status": tenant.status,
                            "role": SystemRoleSlug.OWNER,
                            "permissions": [],
                        }
                    )

        staff_memberships = list(
            self.membership_selector.get_active_staff_memberships(user=user)
        )
        for membership in staff_memberships:
            for assignment in membership.assignments.all():
                role_slug = assignment.role.slug
                if (
                    role_slug == PROTECTED_ADMIN_SLUG
                    and not viewer_may_see_admin_role(viewer)
                ):
                    continue
                key = (str(membership.tenant_id), role_slug)
                if key in seen:
                    continue
                seen.add(key)
                needed_role_slugs.add(role_slug)
                records.append(
                    {
                        "tenant_id": str(membership.tenant_id),
                        "tenant_slug": membership.tenant.slug,
                        "is_active": membership.tenant.is_active,
                        "status": membership.tenant.status,
                        "role": role_slug,
                        "permissions": [],
                    }
                )

        permissions_by_role = self._get_permissions_by_role_slugs(needed_role_slugs)
        for record in records:
            record["permissions"] = permissions_by_role.get(record["role"], [])

        return records

    @staticmethod
    def _effective_permissions_cache_key(user_id, tenant_id) -> str:
        return EFFECTIVE_PERMISSIONS_CACHE_KEY.format(
            user_id=user_id,
            tenant_id=tenant_id,
        )

    def invalidate_effective_permissions_cache(
        self, *, user_id=None, tenant_id=None
    ) -> None:
        if user_id and tenant_id:
            safe_cache_delete(self._effective_permissions_cache_key(user_id, tenant_id))

    def invalidate_effective_permissions_for_membership(self, membership) -> None:
        self.invalidate_effective_permissions_cache(
            user_id=membership.user_id,
            tenant_id=membership.tenant_id,
        )

    def invalidate_effective_permissions_for_role(self, role: Role) -> None:
        pairs = (
            filter_assignments_for_authorization(
                StaffAssignment.objects.filter(role_id=role.id)
            )
            .values_list("membership__user_id", "membership__tenant_id")
            .distinct()
        )
        for user_id, tenant_id in pairs:
            self.invalidate_effective_permissions_cache(
                user_id=user_id, tenant_id=tenant_id
            )

        if role.slug == SystemRoleSlug.OWNER:
            for owner_user_id, tenant_id in (
                Tenant.objects.filter(owner__isnull=False)
                .values_list("owner__user_id", "id")
                .distinct()
            ):
                self.invalidate_effective_permissions_cache(
                    user_id=owner_user_id,
                    tenant_id=tenant_id,
                )

    def invalidate_reference_caches(self) -> None:
        safe_cache_delete(PERMISSIONS_CATALOG_CACHE_KEY)
        safe_cache_delete(ROLES_CATALOG_CACHE_KEY)

    def _get_user_tenant_ids(self, user) -> set:
        tenant_ids: set = set()

        owner_profile = getattr(user, "owner_profile", None)
        if owner_profile:
            tenant_ids.update(
                owner_profile.tenants.values_list("id", flat=True)
            )

        tenant_ids.update(
            StaffMembership.objects.filter(
                user_id=user.id,
                status=MembershipStatus.ACTIVE,
            ).values_list("tenant_id", flat=True)
        )

        return tenant_ids

    @staticmethod
    def _ensure_tenant_with_owner(tenant: Tenant) -> Tenant:
        if "owner" in tenant._state.fields_cache:
            return tenant
        return Tenant.objects.select_related("owner").get(pk=tenant.pk)

    @staticmethod
    def _coerce_effective_permissions_cache(cached) -> dict | None:
        if not isinstance(cached, dict):
            return None

        permissions = cached.get("permissions")
        inherited_permissions = cached.get("inherited_permissions")
        overrides = cached.get("overrides")
        if not isinstance(permissions, list) or not isinstance(inherited_permissions, list):
            return None
        if not isinstance(overrides, list):
            return None

        return {
            "permissions": permissions,
            "inherited_permissions": inherited_permissions,
            "overrides": overrides,
        }

    @staticmethod
    def _is_owner(*, user, tenant) -> bool:
        owner = getattr(tenant, "owner", None)
        if owner is None:
            return False
        return owner.user_id == user.id


rbac_bll = RbacBusinessLogicLayer()
