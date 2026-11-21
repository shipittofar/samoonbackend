from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated

from tenants.models import Tenant, Branch, WorkingHour, TenantStatus
from tenants.service_area import resolve_location_verified_at
from tenants.services.tenant_activation import (
    enforce_tenant_activation_status,
    initial_tenant_status,
    lifecycle_branches_exist,
)
from tenants.checkout_config import (
    BRANCH_CHECKOUT_MODEL_FIELDS,
    strip_operational_settings_keys,
)
from tenants.selectors import (
    TenantDataAccessLayer,
    BranchDataAccessLayer,
    OwnerDataAccessLayer,
)
from tenants.selectors.tenant_availability import PUBLIC_TENANT_FILTER
from accounts.selectors import UserDataAccessLayer
from access.authorization.platform import is_platform_superuser
from access.constants.tenant_eligibility import is_owner_suspended
from accounts.services.workspace_bll import workspace_bll
from core.exceptions import (
    TenantNotFoundException,
    BranchNotFoundException,
    TenantPermissionDeniedException,
    BranchPermissionDeniedException,
    DuplicateTenantException,
    DuplicateBranchException,
    ManagerNotFoundException
)


from uploads.services.compat import apply_image_input

TENANT_MEDIA = (
    ("image", "image_asset", "tenant_logo", "image_asset_id"),
    ("discover_avatar", "discover_avatar_asset", "tenant_discover_avatar", "discover_avatar_asset_id"),
    ("discover_cover", "discover_cover_asset", "tenant_discover_cover", "discover_cover_asset_id"),
    ("hero_image", "hero_image_asset", "tenant_hero", "hero_image_asset_id"),
)

BRANCH_MEDIA = (
    ("image", "image_asset", "branch_logo", "image_asset_id"),
    ("cover_image", "cover_image_asset", "branch_cover", "cover_image_asset_id"),
    ("hero_image", "hero_image_asset", "branch_hero", "hero_image_asset_id"),
)


def _extract_media(data: dict, bindings):
    extracted = []
    for file_key, fk, purpose, asset_key in bindings:
        has_file = file_key in data
        has_asset = asset_key in data
        file = data.pop(file_key) if has_file else None
        asset_id = data.pop(asset_key) if has_asset else None
        # ImageField(allow_null=True) may appear as None alongside an asset id;
        # treat that as asset-id-only rather than a conflicting dual input.
        if has_file and has_asset and file is None:
            has_file = False
        extracted.append({
            "file_key": file_key,
            "fk": fk,
            "purpose": purpose,
            "file_provided": has_file,
            "file": file,
            "asset_id_provided": has_asset,
            "asset_id": asset_id,
        })
    return extracted


def _apply_extracted_media(instance, user, tenant_id, extracted, *, ingest_legacy: bool, entity_type: str, branch_id=None):
    changed = []
    for item in extracted:
        if not item["file_provided"] and not item["asset_id_provided"]:
            continue
        changed.extend(
            apply_image_input(
                instance=instance,
                user=user,
                image_field=item["file_key"],
                asset_fk=item["fk"],
                purpose=item["purpose"],
                tenant_id=tenant_id,
                file=item["file"],
                file_provided=item["file_provided"],
                asset_id=item["asset_id"],
                asset_id_provided=item["asset_id_provided"],
                entity_type=entity_type,
                entity_id=str(getattr(instance, "pk", "") or ""),
                branch_id=branch_id,
                ingest_legacy=ingest_legacy,
            )
        )
    return changed


tenant_dal = TenantDataAccessLayer()
branch_dal = BranchDataAccessLayer()
owner_dal = OwnerDataAccessLayer()
user_dal = UserDataAccessLayer()


def _assert_owns_tenant(user, tenant) -> None:
    """Ownership via flat ``owner_user_id`` only — no nested ORM relations."""
    if is_platform_superuser(user):
        return
    owner_user_id = getattr(tenant, "owner_user_id", None)
    if owner_user_id is None or owner_user_id != user.id:
        raise TenantPermissionDeniedException()
    if is_owner_suspended(user.id):
        raise TenantPermissionDeniedException()


class TenantBusinessLogicLayer:

    @staticmethod
    @transaction.atomic
    def create_tenant(user, **data) -> Tenant:
        if is_owner_suspended(user.id):
            raise TenantPermissionDeniedException()
        owner = owner_dal.get_or_create_by_user_id(user.id)

        if tenant_dal.exists_by_name_for_owner(owner.id, data["name"]):
            raise DuplicateTenantException()

        data["owner"] = owner
        # Branch lifecycle: new tenants start inactive until the first branch exists.
        data["status"] = initial_tenant_status()
        media = _extract_media(data, TENANT_MEDIA)

        try:
            tenant = Tenant.objects.create(**data)
        except IntegrityError:
            raise DuplicateTenantException()

        media_fields = _apply_extracted_media(
            tenant, user, tenant.id, media, ingest_legacy=True, entity_type="tenant",
        )
        if media_fields:
            tenant.save(update_fields=list(dict.fromkeys(media_fields + ["updated_at"])))

        transaction.on_commit(
            lambda: tenant_dal.invalidate_tenant_cache(
                tenant.id, owner.user_id)
        )
        return tenant

    @staticmethod
    @transaction.atomic
    def patch_tenant_settings(user, tenant_id, patch: dict) -> Tenant:
        from tenants.settings_cleanup import (
            TenantSettingsContractError,
            merge_settings_patch,
        )
        from rest_framework.exceptions import ValidationError

        tenant = tenant_dal.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        _assert_owns_tenant(user, tenant)
        try:
            tenant.settings = merge_settings_patch(tenant.settings, patch)
        except TenantSettingsContractError as exc:
            raise ValidationError({"settings": str(exc)}) from exc
        tenant.save(update_fields=["settings", "updated_at"])
        owner_user_id = tenant.owner_user_id
        transaction.on_commit(
            lambda: tenant_dal.invalidate_tenant_cache(tenant.id, owner_user_id)
        )
        return tenant

    @staticmethod
    @transaction.atomic
    def update_tenant(user, tenant_id: int, **data) -> Tenant:
        tenant = tenant_dal.get_tenant_for_update(tenant_id)

        if not tenant:
            raise TenantNotFoundException()

        _assert_owns_tenant(user, tenant)

        if tenant_dal.exists_by_name_for_owner(
            tenant.owner_id, data["name"], exclude_id=tenant.id
        ):
            raise DuplicateTenantException()

        tenant.name = data["name"]
        if "description" in data:
            tenant.description = data["description"]
        tenant.tax_percentage = data.get(
            "tax_percentage", tenant.tax_percentage)
        tenant.service_charge_percentage = data.get(
            "service_charge_percentage", tenant.service_charge_percentage)
        tenant.business_types = data.get("business_types", tenant.business_types)
        tenant.status = data["status"]
        tenant.settings = data.get("settings", tenant.settings)

        update_fields = [
            "name", "tax_percentage", "service_charge_percentage",
            "business_types", "status", "settings", "updated_at",
        ]
        if "description" in data:
            update_fields.append("description")

        media = _extract_media(data, TENANT_MEDIA)
        media_fields = _apply_extracted_media(
            tenant, user, tenant.id, media, ingest_legacy=True, entity_type="tenant",
        )
        update_fields.extend(media_fields)

        try:
            tenant.save(update_fields=list(dict.fromkeys(update_fields)))
        except IntegrityError:
            raise DuplicateTenantException()

        owner_user_id = tenant.owner_user_id
        transaction.on_commit(
            lambda: tenant_dal.invalidate_tenant_cache(
                tenant.id, owner_user_id)
        )
        return tenant

    @staticmethod
    def get_tenant(tenant_id: int):
        tenant = tenant_dal.get_tenant_by_id(tenant_id)

        if not tenant:
            raise TenantNotFoundException()

        return tenant

    @staticmethod
    def get_public_tenant(tenant_id: int):
        """Public catalog retrieve — same eligibility rules as GET /api/tenants/."""
        if not Tenant.objects.filter(id=tenant_id, **PUBLIC_TENANT_FILTER).exists():
            raise TenantNotFoundException()

        tenant = tenant_dal.get_tenant_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundException()

        return tenant

    @staticmethod
    def get_tenants():
        return tenant_dal.get_tenants()

    @staticmethod
    def get_discover_tenants():
        return tenant_dal.get_discover_tenants()

    @staticmethod
    def get_public_tenants():
        return tenant_dal.get_public_tenants()

    @staticmethod
    def get_console_tenants(user):
        return tenant_dal.get_console_tenants(user)

    @staticmethod
    @transaction.atomic
    def delete_tenant(user, tenant_id: int) -> Tenant:
        tenant = tenant_dal.get_tenant_for_update(tenant_id, lock=True)

        if tenant is None:
            raise TenantNotFoundException()

        _assert_owns_tenant(user, tenant)

        return TenantBusinessLogicLayer.deactivate_tenant_record(
            tenant, actor_id=getattr(user, "id", None)
        )

    @staticmethod
    @transaction.atomic
    def deactivate_tenant_record(tenant: Tenant, actor_id=None) -> Tenant:
        """Canonical tenant deactivation. Does not physically delete rows.

        Lock ordering: tenant row (caller) → memberships → assignments.
        """
        from access.services.permission_audit_bll import permission_audit_bll

        previous_status = tenant.status
        previous_is_active = tenant.is_active
        already_inactive = (
            tenant.status == TenantStatus.INACTIVE and tenant.is_active is False
        )
        tenant = tenant_dal.inactive_tenant(tenant)
        if not already_inactive:
            permission_audit_bll.record_tenant_deactivated(
                tenant=tenant,
                actor_id=actor_id,
                previous_status=previous_status,
                previous_is_active=previous_is_active,
            )
        TenantBusinessLogicLayer._remove_staff_memberships_for_tenant(
            tenant, actor_id=actor_id
        )
        return tenant

    @staticmethod
    def _remove_staff_memberships_for_tenant(tenant: Tenant, actor_id=None) -> None:
        """Soft-remove memberships; StaffAssignment rows stay as grant/revoke history."""
        from access.models import StaffMembership, StaffMembershipStatus
        from access.services.membership_bll import membership_service

        memberships = StaffMembership.objects.filter(tenant_id=tenant.id).exclude(
            status=StaffMembershipStatus.REMOVED
        )
        for membership in memberships:
            membership_service.remove_membership(
                tenant_id=tenant.id,
                membership_id=membership.id,
                actor_id=actor_id,
            )

    @staticmethod
    def get_my_tenants(user):
        if not user.is_authenticated:
            raise NotAuthenticated()
        return tenant_dal.get_tenants_for_owner(user.id)


def _assert_owns_branch(user, branch) -> None:
    """Branch ownership via flat ``owner_user_id`` / ``tenant_id`` only."""
    if is_platform_superuser(user):
        return
    if is_owner_suspended(user.id):
        raise BranchPermissionDeniedException()
    owner_user_id = getattr(branch, "owner_user_id", None)
    if owner_user_id is not None:
        if owner_user_id != user.id:
            raise BranchPermissionDeniedException()
        return
    tenant_id = getattr(branch, "tenant_id", None)
    if tenant_id is None:
        raise BranchPermissionDeniedException()
    tenant = tenant_dal.get_tenant_by_id(tenant_id)
    if tenant is None or tenant.owner_user_id != user.id:
        raise BranchPermissionDeniedException()


def _apply_branch_checkout_fields(branch: Branch, data: dict) -> list[str]:
    """Apply checkout columns from validated serializer data."""
    update_fields = []
    for field in BRANCH_CHECKOUT_MODEL_FIELDS:
        if field in data:
            setattr(branch, field, data[field])
            update_fields.append(field)
    return update_fields


def _merge_extension_settings(existing: dict | None, incoming: dict | None) -> dict:
    merged = strip_operational_settings_keys(existing or {})
    incoming = strip_operational_settings_keys(incoming or {})
    merged.update(incoming)
    return merged


def _pin_moved(branch, data: dict) -> bool:
    """True when this write changes the branch coordinates (a stored pin is only
    meaningful for the position it was confirmed at)."""
    for key in ("latitude", "longitude"):
        if key in data and data[key] != getattr(branch, key):
            return True
    return False


class BranchBusinessLogicLayer:

    @staticmethod
    def _sync_working_hours(branch: Branch, working_hours_data: list[dict]) -> None:
        branch.working_hours.all().delete()
        if not working_hours_data:
            return
        WorkingHour.objects.bulk_create(
            [WorkingHour(branch=branch, **wh) for wh in working_hours_data]
        )

    @staticmethod
    def _resolve_manager(manager_id) -> "User | None":
        if manager_id is None:
            return None
        manager = user_dal.get_by_id(manager_id)
        if manager is None:
            raise ManagerNotFoundException()
        return manager

    @staticmethod
    @transaction.atomic
    def create_branch(user, tenant_id: int, **data) -> Branch:
        tenant = tenant_dal.get_tenant_for_update(tenant_id, lock=True)

        if not tenant:
            raise TenantNotFoundException()

        _assert_owns_tenant(user, tenant)

        name = data.get("name", "")
        if branch_dal.exists_by_name_for_tenant(tenant.id, name):
            raise DuplicateBranchException()

        working_hours_data = data.pop("working_hours", [])
        settings_data = data.pop("settings", None)
        data["settings"] = _merge_extension_settings(None, settings_data)
        if "location_verified_at" in data:
            # Never trust a client clock: a confirmation is stamped with server time.
            data["location_verified_at"] = resolve_location_verified_at(
                stored=None,
                provided=True,
                incoming=data["location_verified_at"],
                coordinates_changed=False,
                now=timezone.now(),
            )
        media = _extract_media(data, BRANCH_MEDIA)

        had_lifecycle_branches = lifecycle_branches_exist(tenant.id)
        branch = Branch.objects.create(tenant_id=tenant.id, **data)
        media_fields = _apply_extracted_media(
            branch,
            user,
            tenant.id,
            media,
            ingest_legacy=False,
            entity_type="branch",
            branch_id=branch.id,
        )
        if media_fields:
            branch.save(update_fields=list(dict.fromkeys(media_fields + ["updated_at"])))
        BranchBusinessLogicLayer._sync_working_hours(
            branch, working_hours_data)

        if not had_lifecycle_branches:
            workspace_bll.assign_active_branch_for_first_tenant_branch(tenant, branch)

        enforce_tenant_activation_status(tenant)

        transaction.on_commit(
            lambda: branch_dal.invalidate_branch_cache(tenant.id, branch.id)
        )
        return branch

    @staticmethod
    @transaction.atomic
    def update_branch(user, tenant_id: int, branch_id: int, **data) -> Branch:
        branch = branch_dal.get_branch_for_update(branch_id, tenant_id=tenant_id)

        if not branch:
            raise BranchNotFoundException()

        _assert_owns_branch(user, branch)

        name = data.get("name", "")
        if branch_dal.exists_by_name_for_tenant(
            branch.tenant_id, name, exclude_id=branch.id
        ):
            raise DuplicateBranchException()

        working_hours_data = data.pop("working_hours", None)
        settings_data = data.pop("settings", None)
        media = _extract_media(data, BRANCH_MEDIA)

        branch.name = name
        branch.type = data.get("type", branch.type)
        branch.manager = data.get("manager", branch.manager)

        branch.phone = data.get("phone", "")
        branch.email = data.get("email", "")
        branch.website = data.get("website", "")

        branch.address = data.get("address", "")
        branch.city = data.get("city", "")
        branch.country = data.get("country", "")
        branch.postal_code = data.get("postal_code", "")
        # Full-replace semantics: omitted coordinates become None, which is a move.
        moved = (
            data.get("latitude") != branch.latitude
            or data.get("longitude") != branch.longitude
        )
        branch.latitude = data.get("latitude")
        branch.longitude = data.get("longitude")
        branch.location_verified_at = resolve_location_verified_at(
            stored=branch.location_verified_at,
            provided="location_verified_at" in data,
            incoming=data.get("location_verified_at"),
            coordinates_changed=moved,
            now=timezone.now(),
        )
        if "service_area" in data:
            branch.service_area = data["service_area"]

        media_fields = _apply_extracted_media(
            branch,
            user,
            branch.tenant_id,
            media,
            ingest_legacy=False,
            entity_type="branch",
            branch_id=branch.id,
        )

        branch.time_zone = data.get("time_zone", "UTC")
        branch.currency = data.get("currency", "USD")
        branch.language = data.get("language", "en")

        checkout_updates = _apply_branch_checkout_fields(branch, data)

        if settings_data is not None:
            branch.settings = _merge_extension_settings(branch.settings, settings_data)
        branch.metadata = data.get("metadata", branch.metadata)

        branch.status = data.get("status", branch.status)
        branch.is_active = data.get("is_active", branch.is_active)
        branch.is_default = data.get("is_default", branch.is_default)
        branch.cuisines = data.get("cuisines", branch.cuisines)
        branch.amenities = data.get("amenities", branch.amenities)

        update_fields = [
            "name", "type", "manager",
            "phone", "email", "website",
            "address", "city", "country", "postal_code", "latitude", "longitude",
            "service_area", "location_verified_at",
            "image", "cover_image", "hero_image",
            "time_zone", "currency", "language",
            "settings", "metadata",
            "status", "is_active", "is_default",
            "cuisines", "amenities",
            "updated_at",
        ] + checkout_updates + media_fields

        branch.save(update_fields=list(dict.fromkeys(update_fields)))

        if working_hours_data is not None:
            BranchBusinessLogicLayer._sync_working_hours(
                branch, working_hours_data)

        transaction.on_commit(
            lambda: branch_dal.invalidate_branch_cache(tenant_id, branch.id)
        )
        return branch

    @staticmethod
    @transaction.atomic
    def update_console_branch(
        user,
        branch_id,
        *,
        image_provided: bool = False,
        cover_image_provided: bool = False,
        hero_image_provided: bool = False,
        **data,
    ) -> Branch:
        branch = branch_dal.get_branch_for_update(branch_id)
        if not branch:
            raise BranchNotFoundException()

        _assert_owns_branch(user, branch)
        tenant_id = branch.tenant_id

        update_fields: list[str] = ["updated_at"]

        if "name" in data:
            name = data["name"]
            if branch_dal.exists_by_name_for_tenant(
                tenant_id, name, exclude_id=branch.id
            ):
                raise DuplicateBranchException()
            branch.name = name
            update_fields.append("name")

        scalar_fields = {
            "description": "description",
            "type": "type",
            "manager": "manager",
            "phone": "phone",
            "email": "email",
            "website": "website",
            "address": "address",
            "city": "city",
            "country": "country",
            "postal_code": "postal_code",
            "latitude": "latitude",
            "longitude": "longitude",
            "time_zone": "time_zone",
            "currency": "currency",
            "language": "language",
            "status": "status",
            "is_active": "is_active",
            "is_default": "is_default",
            "cuisines": "cuisines",
            "amenities": "amenities",
        }
        # Decide before the coordinates are overwritten below.
        pin_moved = _pin_moved(branch, data)

        for data_key, model_field in scalar_fields.items():
            if data_key in data:
                setattr(branch, model_field, data[data_key])
                update_fields.append(model_field)

        if "service_area" in data:
            branch.service_area = data["service_area"]
            update_fields.append("service_area")

        verified_at = resolve_location_verified_at(
            stored=branch.location_verified_at,
            provided="location_verified_at" in data,
            incoming=data.get("location_verified_at"),
            coordinates_changed=pin_moved,
            now=timezone.now(),
        )
        if verified_at != branch.location_verified_at:
            branch.location_verified_at = verified_at
            update_fields.append("location_verified_at")

        checkout_updates = _apply_branch_checkout_fields(branch, data)
        update_fields.extend(checkout_updates)

        provided_flags = {
            "image": image_provided,
            "cover_image": cover_image_provided,
            "hero_image": hero_image_provided,
        }
        media = _extract_media(data, BRANCH_MEDIA)
        for item in media:
            if provided_flags.get(item["file_key"]):
                item["file_provided"] = True
                if item["file"] is None:
                    item["file"] = None
        media_fields = _apply_extracted_media(
            branch,
            user,
            tenant_id,
            media,
            ingest_legacy=False,
            entity_type="branch",
            branch_id=branch.id,
        )
        update_fields.extend(media_fields)

        if "settings" in data:
            branch.settings = _merge_extension_settings(
                branch.settings, data["settings"]
            )
            update_fields.append("settings")

        if "metadata" in data:
            branch.metadata = data["metadata"]
            update_fields.append("metadata")

        branch.save(update_fields=list(dict.fromkeys(update_fields)))

        if "working_hours" in data:
            BranchBusinessLogicLayer._sync_working_hours(
                branch, data["working_hours"]
            )

        transaction.on_commit(
            lambda: branch_dal.invalidate_branch_cache(tenant_id, branch.id)
        )
        # Respond from the database, not the read cache: the cache is only
        # refreshed after this transaction commits, so a cached read here would
        # return the branch as it was BEFORE this PATCH (e.g. a pin the owner
        # just confirmed would still read as unverified).
        return branch_dal.get_branch_by_id(branch_id)

    @staticmethod
    def get_branch(tenant_id: int, branch_id: int):
        branch = branch_dal.get_branch_by_id(branch_id, tenant_id=tenant_id)
        if not branch:
            raise BranchNotFoundException()
        return branch

    @staticmethod
    def get_branches(tenant_id: int):
        return branch_dal.get_branches_for_tenant(tenant_id)

    @staticmethod
    @transaction.atomic
    def delete_branch(user, tenant_id: int, branch_id: int) -> Branch:
        branch = branch_dal.get_branch_for_update(branch_id, tenant_id=tenant_id)
        if not branch:
            raise BranchNotFoundException()
        _assert_owns_branch(user, branch)
        branch = branch_dal.inactive_branch(branch)
        workspace_bll.reassign_active_branch_after_deletion(branch)
        tenant = tenant_dal.get_tenant_for_update(tenant_id, lock=True)
        if tenant:
            enforce_tenant_activation_status(tenant)
        return branch

    @staticmethod
    @transaction.atomic
    def delete_console_branch(user, branch_id: int) -> Branch:
        branch = branch_dal.get_branch_for_update(branch_id)
        if not branch:
            raise BranchNotFoundException()
        _assert_owns_branch(user, branch)
        tenant_id = branch.tenant_id
        branch = branch_dal.inactive_branch(branch)
        workspace_bll.reassign_active_branch_after_deletion(branch)
        tenant = tenant_dal.get_tenant_for_update(tenant_id, lock=True)
        if tenant:
            enforce_tenant_activation_status(tenant)
        return branch

    @staticmethod
    def get_branch_public(branch_id):
        branch = branch_dal.get_branch_by_id_global(branch_id)
        if not branch:
            raise BranchNotFoundException()
        return branch

    @staticmethod
    def get_all_branches():
        return branch_dal.get_all_branches()
