from django.db import transaction, IntegrityError
from rest_framework.exceptions import NotAuthenticated

from tenants.models import Tenant, Branch, WorkingHour, TenantStatus
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


tenant_dal = TenantDataAccessLayer()
branch_dal = BranchDataAccessLayer()
owner_dal = OwnerDataAccessLayer()
user_dal = UserDataAccessLayer()


def _assert_owns_tenant(user, tenant) -> None:
    """Ownership via flat ``owner_user_id`` only — no nested ORM relations."""
    if user.is_staff:
        return
    owner_user_id = getattr(tenant, "owner_user_id", None)
    if owner_user_id is None or owner_user_id != user.id:
        raise TenantPermissionDeniedException()


class TenantBusinessLogicLayer:

    @staticmethod
    @transaction.atomic
    def create_tenant(user, **data) -> Tenant:
        owner = owner_dal.get_or_create_by_user_id(user.id)

        if tenant_dal.exists_by_name_for_owner(owner.id, data["name"]):
            raise DuplicateTenantException()

        data["owner"] = owner
        # Branch lifecycle: new tenants start inactive until the first branch exists.
        data["status"] = initial_tenant_status()

        try:
            tenant = Tenant.objects.create(**data)
        except IntegrityError:
            raise DuplicateTenantException()

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

        if data.get("image") is not None:
            tenant.image = data["image"]
            update_fields.append("image")

        try:
            tenant.save(update_fields=update_fields)
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
    def delete_tenant(user, tenant_id: int) -> Tenant:
        tenant = tenant_dal.get_tenant_for_update(tenant_id)

        if tenant is None:
            raise TenantNotFoundException()

        _assert_owns_tenant(user, tenant)

        return tenant_dal.inactive_tenant(tenant)

    @staticmethod
    def get_my_tenants(user):
        if not user.is_authenticated:
            raise NotAuthenticated()
        return tenant_dal.get_tenants_for_owner(user.id)


def _assert_owns_branch(user, branch) -> None:
    """Branch ownership via flat ``owner_user_id`` / ``tenant_id`` only."""
    if user.is_staff:
        return
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

        had_lifecycle_branches = lifecycle_branches_exist(tenant.id)
        branch = Branch.objects.create(tenant_id=tenant.id, **data)
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
        branch.latitude = data.get("latitude")
        branch.longitude = data.get("longitude")

        if "image" in data:
            branch.image = data["image"]
        if "cover_image" in data:
            branch.cover_image = data["cover_image"]

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
            "image", "cover_image",
            "time_zone", "currency", "language",
            "settings", "metadata",
            "status", "is_active", "is_default",
            "cuisines", "amenities",
            "updated_at",
        ] + checkout_updates

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
        for data_key, model_field in scalar_fields.items():
            if data_key in data:
                setattr(branch, model_field, data[data_key])
                update_fields.append(model_field)

        checkout_updates = _apply_branch_checkout_fields(branch, data)
        update_fields.extend(checkout_updates)

        if image_provided:
            if branch.image:
                branch.image.delete(save=False)
            branch.image = data.get("image")
            update_fields.append("image")

        if cover_image_provided:
            if branch.cover_image:
                branch.cover_image.delete(save=False)
            branch.cover_image = data.get("cover_image")
            update_fields.append("cover_image")

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
        return branch_dal.get_branch_by_id(branch_id, tenant_id=tenant_id)

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
