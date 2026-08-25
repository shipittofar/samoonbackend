from uuid import UUID

from tenants.models import Branch
from tenants.selectors.tenant_availability import OPERATIONAL_TENANT_LOOKUP


class AddressBranchDataAccessLayer:
    @staticmethod
    def get_active_branch(branch_id: UUID) -> Branch | None:
        return (
            Branch.objects.select_related("tenant")
            .filter(pk=branch_id, is_active=True, **OPERATIONAL_TENANT_LOOKUP)
            .first()
        )
