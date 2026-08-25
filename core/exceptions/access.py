from __future__ import annotations

from core.exceptions import BaseAppException


class PermissionDeniedException(BaseAppException):
    status_code = 403
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class RoleNotFoundException(BaseAppException):
    status_code = 404
    code = "role_not_found"
    message = "Role not found."


class RoleSlugAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "role_slug_already_exists"
    message = "A role with this slug already exists."


class SystemRoleDeleteNotAllowedException(BaseAppException):
    status_code = 400
    code = "system_role_delete_not_allowed"
    message = "System roles cannot be deleted."


class SystemRoleModifyNotAllowedException(BaseAppException):
    status_code = 403
    code = "system_role_modify_not_allowed"
    message = "System role definitions cannot be modified."


class AdminRoleAccessDeniedException(BaseAppException):
    status_code = 403
    code = "admin_role_access_denied"
    message = "The admin role is restricted to platform superusers."


class UnknownPermissionSlugsException(BaseAppException):
    status_code = 400
    code = "unknown_permission_slugs"
    message = "One or more permission slugs are unknown."


class PermissionNotFoundException(BaseAppException):
    status_code = 404
    code = "permission_not_found"
    message = "Permission not found."


class StaffMembershipNotFoundException(BaseAppException):
    status_code = 404
    code = "staff_membership_not_found"
    message = "Staff membership not found."


class StaffMembershipAlreadyRemovedException(BaseAppException):
    status_code = 400
    code = "staff_membership_already_removed"
    message = "This staff membership has already been removed."


class StaffAssignmentNotFoundException(BaseAppException):
    status_code = 404
    code = "staff_assignment_not_found"
    message = "Staff assignment not found."


class NotAMemberOfTenantException(BaseAppException):
    status_code = 403
    code = "not_a_member_of_tenant"
    message = "You are not a member of this tenant."


class ActiveBranchTenantMismatchException(BaseAppException):
    status_code = 400
    code = "active_branch_tenant_mismatch"
    message = "The selected branch does not belong to the active tenant."

    def __init__(self, message=None, detail=None, diagnostics=None):
        # Temporary: carry raise_source + workspace ids so production 400s
        # identify the exact raise path without guessing.
        self.diagnostics = diagnostics or {}
        super().__init__(message=message, detail=detail)


class NotAMemberOfBranchException(BaseAppException):
    status_code = 403
    code = "not_a_member_of_branch"
    message = "You do not have access to this branch."


class AmbiguousTenantException(BaseAppException):
    status_code = 400
    code = "ambiguous_tenant"
    message = "User belongs to multiple tenants; specify X-Tenant-Slug."


class TenantAccessDeniedException(BaseAppException):
    status_code = 403
    code = "tenant_access_denied"
    message = "Caller is not a member of this tenant."


class TenantContextMismatchException(BaseAppException):
    status_code = 400
    code = "tenant_context_mismatch"
    message = "X-Tenant-Slug and X-Tenant-Id refer to different tenants."


class NoTenantContextException(BaseAppException):
    status_code = 400
    code = "no_tenant_context"
    message = "User belongs to no tenants; cannot resolve tenant context."


class PermissionOverrideNotFoundException(BaseAppException):
    status_code = 404
    code = "permission_override_not_found"
    message = "Permission override not found."


class UnknownPermissionIdsException(BaseAppException):
    status_code = 400
    code = "unknown_permission_ids"
    message = "One or more permission ids are unknown."