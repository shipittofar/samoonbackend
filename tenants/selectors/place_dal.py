from tenants.models import Tenant


class TenantDataAccessLayer:

    @staticmethod
    def exists_by_slug(slug: str) -> bool:
        return Tenant.objects.filter(slug=slug).exists()

    @staticmethod
    def get_by_slug(slug: str) -> Tenant:
        return Tenant.objects.get(slug=slug)

    @staticmethod
    def get_all():
        return Tenant.objects.all()

    @staticmethod
    def is_slug_exists(slug: str, exclude_id: int | None = None) -> bool:
        queryset = Tenant.objects.filter(slug=slug)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def get_tenant_by_id(tenant_id: int) -> Tenant | None:
        return (
            Tenant.objects
            .select_related("owner")
            .prefetch_related("working_hours")
            .filter(id=tenant_id)
            .first()
        )

    @staticmethod
    def get_tenants():
        return (
            Tenant.objects
            .select_related("owner")
            .prefetch_related("working_hours")
            .all()
            .order_by("-created_at")
        )

    @staticmethod
    def owner_exists(owner_id: int) -> bool:
        from django.contrib.auth import get_user_model
        return get_user_model().objects.filter(id=owner_id).exists()

    @staticmethod
    def inactive_tenant(tenant: Tenant) -> Tenant:
        from tenants.selectors.tenant_dal import TenantDataAccessLayer as ConsoleTenantDAL

        return ConsoleTenantDAL.inactive_tenant(tenant)