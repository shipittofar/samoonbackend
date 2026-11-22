from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch

from core.cache import cache_get, cache_set, cache_delete, CacheKeys, CacheTTL
from tenants.dto import BranchDTO, TenantDiscoverDTO, TenantDTO
from tenants.models import Tenant, TenantStatus, Owner, Branch, BranchStatus
from tenants.models.qr_code import QrEntityType
from tenants.selectors.qr_dal import annotate_qr_code
from tenants.selectors.tenant_availability import (
    PUBLIC_TENANT_FILTER,
    PUBLIC_TENANT_LOOKUP,
)

TENANT_TTL = CacheTTL.TENANT
BRANCH_TTL = CacheTTL.BRANCH


def _publicly_listable_tenant_ids() -> set:
    """Authoritative tenant ids eligible for public catalog surfaces."""
    return set(Tenant.objects.filter(**PUBLIC_TENANT_FILTER).values_list("id", flat=True))


def _coerce_tenant_dto(cached) -> TenantDTO | None:
    if cached is None:
        return None
    if isinstance(cached, TenantDTO):
        return cached
    if isinstance(cached, dict):
        return TenantDTO.from_cache_dict(cached)
    # Legacy pickled model — treat as miss so we rebuild a DTO.
    return None


def _coerce_branch_dto(cached) -> BranchDTO | None:
    if cached is None:
        return None
    if isinstance(cached, BranchDTO):
        return cached
    if isinstance(cached, dict):
        return BranchDTO.from_cache_dict(cached)
    return None


def _coerce_discover_list(cached) -> list[TenantDiscoverDTO] | None:
    if cached is None:
        return None
    if not isinstance(cached, list):
        return None
    out: list[TenantDiscoverDTO] = []
    for item in cached:
        if isinstance(item, TenantDiscoverDTO):
            out.append(item)
        elif isinstance(item, dict):
            out.append(TenantDiscoverDTO.from_cache_dict(item))
        else:
            return None
    return out


class OwnerDataAccessLayer:
    # Not cached: this is a tiny get_or_create lookup called once per
    # tenant-create flow, not a hot read path.

    @staticmethod
    def get_or_create_by_user_id(user_id) -> Owner:
        owner, _ = Owner.objects.get_or_create(user_id=user_id)
        return owner

    @staticmethod
    def user_exists(user_id) -> bool:
        return get_user_model().objects.filter(id=user_id).exists()


class TenantDataAccessLayer:

    # ---------- cache helpers (DTO payloads only) ----------

    @staticmethod
    def _tenant_detail_queryset():
        return annotate_qr_code(
            Tenant.objects.select_related("owner", "owner__user"),
            QrEntityType.TENANT,
        )

    @staticmethod
    def _refresh_tenant_detail_cache(tenant_id) -> TenantDTO | None:
        instance = (
            TenantDataAccessLayer._tenant_detail_queryset()
            .filter(id=tenant_id)
            .first()
        )
        key = CacheKeys.TENANT_DETAIL.format(tenant_id=tenant_id)
        if instance is not None:
            dto = TenantDTO.from_model(instance)
            cache_set(key, dto.to_cache_dict(), TENANT_TTL)
            return dto
        cache_delete(key)
        return None

    @staticmethod
    def _refresh_tenant_owner_list_cache(user_id) -> list[TenantDTO]:
        rows = list(
            TenantDataAccessLayer._tenant_detail_queryset()
            .filter(owner__user_id=user_id)
            .order_by("-created_at")
        )
        data = [TenantDTO.from_model(t) for t in rows]
        key = CacheKeys.TENANT_LIST_BY_OWNER.format(user_id=user_id)
        cache_set(key, [d.to_cache_dict() for d in data], TENANT_TTL)
        return data

    @staticmethod
    def _refresh_tenant_list_all_cache() -> list[TenantDTO]:
        rows = list(
            TenantDataAccessLayer._tenant_detail_queryset()
            .all()
            .order_by("-created_at")
        )
        data = [TenantDTO.from_model(t) for t in rows]
        cache_set(
            CacheKeys.TENANT_LIST_ALL,
            [d.to_cache_dict() for d in data],
            TENANT_TTL,
        )
        return data

    @staticmethod
    def invalidate_tenant_cache(tenant_id, owner_user_id=None) -> None:
        """
        Called from the service layer (via transaction.on_commit) after any
        tenant create/update/status-change. Refreshes the detail cache,
        the admin-wide list cache, and the owner's tenant-list cache
        if the owner's user_id is known.
        """
        TenantDataAccessLayer._refresh_tenant_detail_cache(tenant_id)
        TenantDataAccessLayer._refresh_tenant_list_all_cache()
        TenantDataAccessLayer._refresh_discover_list_cache()
        if owner_user_id is not None:
            TenantDataAccessLayer._refresh_tenant_owner_list_cache(
                owner_user_id)

    # ---------- reads (cached DTOs) ----------

    @staticmethod
    def get_tenant_by_id(tenant_id) -> TenantDTO | None:
        key = CacheKeys.TENANT_DETAIL.format(tenant_id=tenant_id)
        cached = _coerce_tenant_dto(cache_get(key))
        if cached is not None:
            return cached
        return TenantDataAccessLayer._refresh_tenant_detail_cache(tenant_id)

    @staticmethod
    def get_tenants_for_owner(user_id) -> list[TenantDTO]:
        key = CacheKeys.TENANT_LIST_BY_OWNER.format(user_id=user_id)
        raw = cache_get(key)
        if isinstance(raw, list):
            coerced = [_coerce_tenant_dto(item) for item in raw]
            if all(item is not None for item in coerced):
                return coerced  # type: ignore[return-value]
        return TenantDataAccessLayer._refresh_tenant_owner_list_cache(user_id)

    @staticmethod
    def get_tenants() -> list[TenantDTO]:
        raw = cache_get(CacheKeys.TENANT_LIST_ALL)
        if isinstance(raw, list):
            coerced = [_coerce_tenant_dto(item) for item in raw]
            if all(item is not None for item in coerced):
                return coerced  # type: ignore[return-value]
        return TenantDataAccessLayer._refresh_tenant_list_all_cache()

    @staticmethod
    def _refresh_discover_list_cache() -> list[TenantDiscoverDTO]:
        # Imported here: menu depends on tenants models, not the other way round.
        from menu.models import MenuCategory, MenuItem

        public_branches_qs = (
            BranchDataAccessLayer.public_visible_branches_queryset()
            .prefetch_related(
                "working_hours",
                # Published AND orderable items only, popular first (the DTO
                # dedupes and caps them). `objects` already hides soft-deleted rows.
                Prefetch(
                    "items",
                    queryset=MenuItem.objects.filter(is_active=True, available=True)
                    .order_by("-is_popular", "name")
                    .only("id", "branch_id", "name", "is_popular"),
                    to_attr="discover_items",
                ),
                Prefetch(
                    "categories",
                    queryset=MenuCategory.objects.order_by("name").only(
                        "id", "branch_id", "name"
                    ),
                    to_attr="discover_categories",
                ),
            )
        )
        rows = list(
            annotate_qr_code(
                Tenant.objects.filter(**PUBLIC_TENANT_FILTER),
                QrEntityType.TENANT,
            )
            .prefetch_related(Prefetch("branches", queryset=public_branches_qs))
            .order_by("-created_at")
        )
        data = [TenantDiscoverDTO.from_model(t) for t in rows]
        cache_set(
            CacheKeys.DISCOVER_LIST,
            [d.to_cache_dict() for d in data],
            TENANT_TTL,
        )
        return data

    @staticmethod
    def get_discover_tenants() -> list[TenantDiscoverDTO]:
        cached = _coerce_discover_list(cache_get(CacheKeys.DISCOVER_LIST))
        if cached is not None:
            listable_ids = _publicly_listable_tenant_ids()
            return [row for row in cached if row.id in listable_ids]
        return TenantDataAccessLayer._refresh_discover_list_cache()

    # ---------- write-path loads (always DB, never cache) ----------

    @staticmethod
    def get_tenant_for_update(tenant_id, *, lock: bool = False) -> Tenant | None:
        """
        Authoritative ORM tenant for mutation paths. Bypasses read cache.

        Attaches a flat ``owner_user_id`` attribute for ownership helpers so
        callers never need ``tenant.owner.user_id`` nesting.
        """
        qs = TenantDataAccessLayer._tenant_detail_queryset()
        if lock:
            qs = qs.select_for_update()
        tenant = qs.filter(id=tenant_id).first()
        if tenant is not None:
            tenant.owner_user_id = tenant.owner.user_id  # type: ignore[attr-defined]
        return tenant

    # ---------- reads (not cached — validation / admin) ----------

    @staticmethod
    def exists_by_slug(slug: str) -> bool:
        return Tenant.objects.filter(slug=slug).exists()

    @staticmethod
    def get_by_slug(slug: str) -> Tenant:
        return Tenant.objects.get(slug=slug)

    @staticmethod
    def is_slug_exists(slug: str, exclude_id=None) -> bool:
        queryset = Tenant.objects.filter(slug=slug)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def exists_by_name_for_owner(owner_id, name: str, exclude_id=None) -> bool:
        """Used for the pre-check; the DB UniqueConstraint is the final guard
        against race conditions under concurrent requests."""
        queryset = Tenant.objects.filter(owner_id=owner_id, name__iexact=name)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def get_public_tenants():
        return annotate_qr_code(
            Tenant.objects.filter(**PUBLIC_TENANT_FILTER),
            QrEntityType.TENANT,
        ).order_by("-created_at")

    @staticmethod
    def get_console_tenants(user):
        return annotate_qr_code(
            Tenant.objects.filter(
                status=TenantStatus.ACTIVE,
                owner__user=user,
            ).select_related("owner", "owner__user"),
            QrEntityType.TENANT,
        ).order_by("-created_at")

    # ---------- writes ----------

    @staticmethod
    def activate_tenant(tenant: Tenant) -> Tenant:
        # Mirror of inactive_tenant(), which also clears is_active: without
        # restoring it, a tenant whose last branch was deleted and then re-added
        # stayed is_active=False, so RBAC gave its owner no permissions at all
        # (console menu empty) and it never reappeared in public listings.
        tenant.status = TenantStatus.ACTIVE
        tenant.is_active = True
        tenant.save(update_fields=["status", "is_active", "updated_at"])

        owner_user_id = getattr(tenant, "owner_user_id", None) or tenant.owner.user_id
        transaction.on_commit(
            lambda: TenantDataAccessLayer.invalidate_tenant_cache(
                tenant.id, owner_user_id)
        )
        return tenant

    @staticmethod
    def inactive_tenant(tenant: Tenant) -> Tenant:
        tenant.status = TenantStatus.INACTIVE
        tenant.is_active = False
        tenant.save(update_fields=["status", "is_active", "updated_at"])

        owner_user_id = getattr(tenant, "owner_user_id", None) or tenant.owner.user_id
        transaction.on_commit(
            lambda: TenantDataAccessLayer.invalidate_tenant_cache(
                tenant.id, owner_user_id)
        )
        return tenant


class BranchDataAccessLayer:

    @staticmethod
    def public_visible_branches_queryset():
        """Branches eligible for public marketplace/discover surfaces.

        Mirrors the active-branch rules used by the global branch list and
        additionally excludes branches explicitly hidden from the marketplace.
        """
        return annotate_qr_code(
            Branch.objects.filter(
                status=BranchStatus.ACTIVE,
                is_active=True,
                marketplace_visible=True,
            ).order_by("name"),
            QrEntityType.BRANCH,
        )

    @staticmethod
    def _branch_detail_queryset():
        return annotate_qr_code(
            Branch.objects
            .select_related("tenant", "tenant__owner", "tenant__owner__user")
            .prefetch_related("working_hours"),
            QrEntityType.BRANCH,
        )

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_branch_detail_cache(branch_id, tenant_id) -> BranchDTO | None:
        instance = (
            BranchDataAccessLayer._branch_detail_queryset()
            .filter(id=branch_id, tenant_id=tenant_id)
            .first()
        )
        key = CacheKeys.BRANCH_DETAIL.format(
            tenant_id=tenant_id, branch_id=branch_id)
        if instance is not None:
            dto = BranchDTO.from_model(instance)
            cache_set(key, dto.to_cache_dict(), BRANCH_TTL)
            return dto
        cache_delete(key)
        return None

    @staticmethod
    def _refresh_branch_list_cache(tenant_id) -> list[BranchDTO]:
        rows = list(
            BranchDataAccessLayer._branch_detail_queryset()
            .filter(tenant_id=tenant_id)
            .order_by("name")
        )
        data = [BranchDTO.from_model(b) for b in rows]
        key = CacheKeys.BRANCH_LIST.format(tenant_id=tenant_id)
        cache_set(key, [d.to_cache_dict() for d in data], BRANCH_TTL)
        return data

    @staticmethod
    def publicly_listable_branches_queryset():
        """Branches eligible for GET /api/tenants/branches/ (public directory)."""
        return (
            BranchDataAccessLayer._branch_detail_queryset()
            .filter(
                status=BranchStatus.ACTIVE,
                is_active=True,
                **PUBLIC_TENANT_LOOKUP,
            )
        )

    @staticmethod
    def _refresh_branch_detail_global_cache(branch_id) -> BranchDTO | None:
        instance = (
            BranchDataAccessLayer.publicly_listable_branches_queryset()
            .filter(id=branch_id)
            .first()
        )
        key = CacheKeys.BRANCH_DETAIL_GLOBAL.format(branch_id=branch_id)
        if instance is not None:
            dto = BranchDTO.from_model(instance)
            cache_set(key, dto.to_cache_dict(), BRANCH_TTL)
            return dto
        cache_delete(key)
        return None

    @staticmethod
    def _refresh_branch_list_all_cache() -> list[BranchDTO]:
        rows = list(
            BranchDataAccessLayer.publicly_listable_branches_queryset()
            .order_by("name")
        )
        data = [BranchDTO.from_model(b) for b in rows]
        cache_set(
            CacheKeys.BRANCH_LIST_ALL,
            [d.to_cache_dict() for d in data],
            BRANCH_TTL,
        )
        return data

    @staticmethod
    def invalidate_branch_cache(tenant_id, branch_id=None) -> None:
        """
        Called from the service layer (via transaction.on_commit) after any
        branch create/update/status-change, including working-hours sync.
        """
        BranchDataAccessLayer._refresh_branch_list_cache(tenant_id)
        BranchDataAccessLayer._refresh_branch_list_all_cache()
        TenantDataAccessLayer._refresh_discover_list_cache()
        if branch_id is not None:
            BranchDataAccessLayer._refresh_branch_detail_cache(
                branch_id, tenant_id)
            BranchDataAccessLayer._refresh_branch_detail_global_cache(
                branch_id)

    # ---------- reads (cached DTOs) ----------

    @staticmethod
    def get_branch_by_id(branch_id, tenant_id=None) -> BranchDTO | None:
        """
        Cached branch read. When ``tenant_id`` is omitted, still returns a DTO
        built from a one-shot DB load (not stored under the tenant-scoped key).
        """
        if tenant_id is None:
            instance = (
                BranchDataAccessLayer._branch_detail_queryset()
                .filter(id=branch_id)
                .first()
            )
            return BranchDTO.from_model(instance) if instance else None

        key = CacheKeys.BRANCH_DETAIL.format(
            tenant_id=tenant_id, branch_id=branch_id)
        cached = _coerce_branch_dto(cache_get(key))
        if cached is not None:
            return cached
        return BranchDataAccessLayer._refresh_branch_detail_cache(
            branch_id, tenant_id)

    @staticmethod
    def get_branches_for_tenant(tenant_id) -> list[BranchDTO]:
        key = CacheKeys.BRANCH_LIST.format(tenant_id=tenant_id)
        raw = cache_get(key)
        if isinstance(raw, list):
            coerced = [_coerce_branch_dto(item) for item in raw]
            if all(item is not None for item in coerced):
                return coerced  # type: ignore[return-value]
        return BranchDataAccessLayer._refresh_branch_list_cache(tenant_id)

    @staticmethod
    def get_branch_by_id_global(branch_id) -> BranchDTO | None:
        key = CacheKeys.BRANCH_DETAIL_GLOBAL.format(branch_id=branch_id)
        cached = _coerce_branch_dto(cache_get(key))
        if cached is not None:
            if cached.tenant_id in _publicly_listable_tenant_ids():
                return cached
            cache_delete(key)
            return None
        return BranchDataAccessLayer._refresh_branch_detail_global_cache(branch_id)

    @staticmethod
    def get_all_branches() -> list[BranchDTO]:
        raw = cache_get(CacheKeys.BRANCH_LIST_ALL)
        if isinstance(raw, list):
            coerced = [_coerce_branch_dto(item) for item in raw]
            if all(item is not None for item in coerced):
                listable_ids = _publicly_listable_tenant_ids()
                return [
                    branch
                    for branch in coerced  # type: ignore[union-attr]
                    if branch.tenant_id in listable_ids
                ]
        return BranchDataAccessLayer._refresh_branch_list_all_cache()

    # ---------- write-path loads (always DB, never cache) ----------

    @staticmethod
    def get_branch_for_update(
        branch_id, tenant_id=None, *, lock: bool = False
    ) -> Branch | None:
        """
        Authoritative ORM branch for mutation paths. Bypasses read cache.

        Attaches flat ``owner_user_id`` for ownership helpers.
        """
        qs = BranchDataAccessLayer._branch_detail_queryset()
        if lock:
            qs = qs.select_for_update()
        if tenant_id is not None:
            qs = qs.filter(id=branch_id, tenant_id=tenant_id)
        else:
            qs = qs.filter(id=branch_id)
        branch = qs.first()
        if branch is not None and branch.tenant.owner_id:
            branch.owner_user_id = branch.tenant.owner.user_id  # type: ignore[attr-defined]
        return branch

    # ---------- reads (not cached) ----------

    @staticmethod
    def exists_by_name_for_tenant(tenant_id, name: str, exclude_id=None) -> bool:
        queryset = Branch.objects.filter(
            tenant_id=tenant_id, name__iexact=name)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def is_slug_exists(slug: str, exclude_id=None) -> bool:
        queryset = Branch.objects.filter(slug=slug)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    # ---------- writes ----------

    @staticmethod
    def inactive_branch(branch: Branch) -> Branch:
        branch.status = BranchStatus.INACTIVE
        branch.is_active = False
        branch.save(update_fields=["status", "is_active", "updated_at"])

        tenant_id, branch_id = branch.tenant_id, branch.id
        transaction.on_commit(
            lambda: BranchDataAccessLayer.invalidate_branch_cache(
                tenant_id, branch_id)
        )
        return branch
