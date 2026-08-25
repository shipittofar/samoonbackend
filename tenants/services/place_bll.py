import uuid

from django.db import transaction

from accounts.services.workspace_bll import workspace_bll
from tenants.models import Tenant, WorkingHour
from tenants.selectors import TenantDataAccessLayer, OwnerDataAccessLayer
from tenants.services.tenant_activation import initial_tenant_status
from core.exceptions import TenantNotFoundException


tenant_dal = TenantDataAccessLayer()
owner_dal = OwnerDataAccessLayer()


class TenantBusinessLogicLayer:
    """
    Legacy/place tenant writes.

    NOTE: Console HTTP routes use ``tenants.services.tenant_bll`` (no owner
    mutation). Ownership transfer is NOT exposed at
    ``/tenants/{id}/transfer-ownership/`` (that route is unwired / 404).

    The only supported production paths that change ``Tenant.owner_id`` are:
      1. ``transfer_ownership`` (canonical)
      2. ``update_tenant`` when ``owner`` differs (delegates to 1)
      3. Django Admin Tenant change form (delegates to 1)

    ``Branch.tenant_id`` is never modified by ownership transfer.
    """

    @staticmethod
    def _sync_working_hours(tenant: Tenant, working_hours_data: list[dict]) -> None:
        """Replace-strategy: existing working hours get wiped and recreated."""
        tenant.working_hours.all().delete()

        if not working_hours_data:
            return

        WorkingHour.objects.bulk_create(
            [WorkingHour(tenant=tenant, **wh) for wh in working_hours_data]
        )

    @staticmethod
    @transaction.atomic
    def create_tenant(**data) -> Tenant:
        working_hours_data = data.pop("working_hours", [])

        data["slug"] = uuid.uuid4().hex
        owner = owner_dal.get_or_create_by_user_id(data.pop("owner"))
        data["owner"] = owner
        data["status"] = initial_tenant_status()

        tenant = Tenant.objects.create(**data)

        tenant_dal._sync_working_hours(tenant, working_hours_data)

        return tenant

    @staticmethod
    @transaction.atomic
    def transfer_ownership(
        *,
        tenant_id,
        new_owner_user_id,
        actor_id=None,
    ) -> Tenant:
        """
        Canonical ownership transfer.

        Changes ``Tenant.owner_id`` only. Does not reparent branches.
        Clears the previous owner's workspace pointers when they pointed at
        this tenant, records audit, and invalidates owner-list caches.
        """
        tenant = (
            Tenant.objects.select_for_update()
            .select_related("owner", "owner__user")
            .filter(id=tenant_id)
            .first()
        )
        if tenant is None:
            raise TenantNotFoundException()

        previous_owner_id = tenant.owner_id
        previous_owner_user_id = tenant.owner.user_id
        new_owner = owner_dal.get_or_create_by_user_id(new_owner_user_id)

        if previous_owner_id == new_owner.id:
            return tenant

        tenant.owner_id = new_owner.id
        tenant.save(update_fields=["owner", "updated_at"])

        TenantBusinessLogicLayer._reconcile_after_ownership_transfer(
            tenant=tenant,
            actor_id=actor_id,
            previous_owner_id=previous_owner_id,
            previous_owner_user_id=previous_owner_user_id,
            new_owner_user_id=new_owner.user_id,
        )
        return tenant

    @staticmethod
    @transaction.atomic
    def update_tenant(tenant_id: int, *, actor_id=None, **data) -> Tenant:
        # Bypass cache and lock the row so concurrent transfers/workspace
        # switches cannot race on the same Tenant.owner_id.
        tenant = (
            Tenant.objects.select_for_update()
            .select_related("owner", "owner__user")
            .filter(id=tenant_id)
            .first()
        )

        if not tenant:
            raise TenantNotFoundException()

        working_hours_data = data.pop("working_hours", None)
        requested_owner_user_id = data["owner"]

        tenant.name = data["name"]
        tenant.tax_percentage = data.get("tax_percentage", tenant.tax_percentage)
        tenant.business_types = data.get("business_types", tenant.business_types)
        tenant.status = data["status"]
        tenant.is_active = data.get("is_active", tenant.is_active)

        update_fields = [
            "name",
            "tax_percentage",
            "business_types",
            "status",
            "is_active",
            "updated_at",
        ]

        if data.get("image") is not None:
            tenant.image = data["image"]
            update_fields.append("image")

        tenant.save(update_fields=update_fields)

        if working_hours_data is not None:
            tenant_dal._sync_working_hours(tenant, working_hours_data)

        # Always invalidate after field writes — transfer_ownership only busts
        # caches when the owner actually changes (early-return otherwise).
        tenant_id_for_cache = tenant.id
        owner_user_id_for_cache = tenant.owner.user_id

        def _invalidate_after_field_update():
            tenant_dal.invalidate_tenant_cache(
                tenant_id_for_cache, owner_user_id_for_cache
            )

        transaction.on_commit(_invalidate_after_field_update)

        # Owner changes go through the canonical transfer path only.
        return TenantBusinessLogicLayer.transfer_ownership(
            tenant_id=tenant.id,
            new_owner_user_id=requested_owner_user_id,
            actor_id=actor_id,
        )

    @staticmethod
    def _reconcile_after_ownership_transfer(
        *,
        tenant: Tenant,
        actor_id,
        previous_owner_id,
        previous_owner_user_id,
        new_owner_user_id,
    ) -> None:
        """
        Ownership transfer moves Tenant.owner only.

        Branches stay on Branch.tenant_id (same tenant) and therefore move
        with the tenant. Workspace pointers on the previous owner must be
        cleared when they pointed at this tenant, otherwise the previous
        owner keeps a stale activeTenant/activeBranch after losing access.
        """
        from access.services.permission_audit_bll import permission_audit_bll
        from accounts.models import User

        previous_owner_user = User.objects.filter(id=previous_owner_user_id).first()
        if previous_owner_user is not None:
            # clear_workspace_if_tenant locks the user row (select_for_update).
            workspace_bll.clear_workspace_if_tenant(
                previous_owner_user, tenant.id
            )

        permission_audit_bll.record_ownership_transfer(
            tenant_id=tenant.id,
            actor_id=actor_id,
            old_owner_id=previous_owner_id,
            new_owner_id=tenant.owner_id,
        )

        # Branches remain on Branch.tenant_id for this tenant — no reparenting
        # and no async/job path. Only Owner + workspace pointers change.

        # Invalidate after commit so a rolled-back transfer cannot leave
        # owner-list caches pointing at the post-transfer state.
        transferred_tenant_id = tenant.id
        old_owner_user_id = previous_owner_user_id
        new_owner_uid = new_owner_user_id

        def _invalidate_owner_caches():
            tenant_dal.invalidate_tenant_cache(
                transferred_tenant_id, old_owner_user_id
            )
            if new_owner_uid != old_owner_user_id:
                tenant_dal._refresh_tenant_owner_list_cache(new_owner_uid)

        transaction.on_commit(_invalidate_owner_caches)

    @staticmethod
    def get_tenant(tenant_id: int):
        tenant = tenant_dal.get_tenant_by_id(tenant_id)

        if not tenant:
            raise TenantNotFoundException()

        return tenant

    @staticmethod
    def get_tenants():
        return tenant_dal.get_tenants()

    @staticmethod
    def delete_tenant(tenant_id: int) -> Tenant:
        tenant = tenant_dal.get_tenant_for_update(tenant_id)

        if tenant is None:
            raise TenantNotFoundException()

        return tenant_dal.inactive_tenant(tenant)
