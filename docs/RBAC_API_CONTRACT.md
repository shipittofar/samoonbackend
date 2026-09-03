# RBAC API Contract

> **Audit date:** 2026-08-06  
> **Scope:** API contract verification with lightweight URL compatibility aliases.  
> **Source of truth:** `SmartRestaurant/urls.py`, `access/api/urls.py`, `access/api/urls_tenant_compat.py`, `access/api/urls_permissions.py`, `accounts/api/urls.py`, `tenants/api/urls.py`, view/serializer classes, and integration tests under `access/tests/`.

---

## 1. URL mount structure

```
/                                    → api_root (endpoint index)
/api/auth/                           → accounts.api.urls          (authentication + session)
/api/permissions/                    → access.api.urls_permissions (static permission catalog)
/api/authorization/                  → access.api.urls            (RBAC admin + tenant staff ops) **CANONICAL**
/api/access/                         → access.api.urls            (compatibility alias → same views)
/api/tenants/                        → tenants.api.urls           (tenant CRUD + tenant role catalog)
                                       └─ access.api.urls_tenant_compat (tenant-scoped RBAC alias)
```

### Canonical vs compatibility paths

| Use case | **Canonical (preferred)** | **Compatibility alias** |
|----------|---------------------------|---------------------------|
| Staff memberships / assignments / overrides / audit | `/api/authorization/tenants/{tenant_id}/...` | `/api/access/tenants/{tenant_id}/...` **or** `/api/tenants/{tenant_id}/...` |
| Platform roles / switch-tenant | `/api/authorization/...` | `/api/access/...` |
| Permission catalog | `/api/permissions/` | — (no alias needed) |
| Tenant role catalog | `/api/tenants/{tenant_id}/roles/` | — (already on tenants mount) |

All compatibility routes delegate to the **same view classes** — no duplicated business logic.

### Prefix validation (frontend expectations)

| Expected prefix | Status | Notes |
|-----------------|--------|-------|
| `/api/access/...` | **Valid (alias)** | Mirrors `/api/authorization/...` via `include(('access.api.urls', 'access'), namespace='access-compat')`. |
| `/api/authorization/...` | **Valid (canonical)** | Primary mount for roles, staff memberships, assignments, overrides, audit, switch-tenant/branch. |
| `/api/tenants/{id}/staff-*` | **Valid (alias)** | Tenant-scoped RBAC via `access.api.urls_tenant_compat` — same views as `/api/authorization/tenants/{id}/...`. |
| `/api/permissions/...` | **Valid** | Static permission catalog (`GET /api/permissions/`). Distinct from `/api/authorization/permissions/` (DB-backed admin list). |
| `/api/auth/me*` | **Valid** | Session identity and permission resolution. |

### Authentication

All endpoints below require **JWT** unless noted otherwise.

```
Authorization: Bearer <access_token>
```

Configured in `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES` → `JWTAuthentication`.

### Tenant context headers (session endpoints only)

Used by `GET /api/auth/me/permissions/` and `GET /api/auth/me/effective-permissions/` when the user belongs to multiple tenants:

| Header | Purpose |
|--------|---------|
| `X-Tenant-Slug` | Resolve tenant by slug |
| `X-Tenant-Id` | Resolve tenant by UUID |

Resolution order: slug header → id header → `user.active_tenant_id` → sole membership → error if ambiguous.

### Default pagination

`PageNumberPagination` with `PAGE_SIZE = 20` (global default). Paginated list responses:

```json
{
  "count": 42,
  "next": "https://host/api/...?page=2",
  "previous": null,
  "results": [ /* ... */ ]
}
```

Endpoints that return a **bare array** (no pagination wrapper) are called out per endpoint.

---

## 2. Complete RBAC API table

### 2.1 Authentication & session

#### `GET /api/auth/me/`

| Field | Value |
|-------|-------|
| **View** | `MeView` (`accounts/api/views/auth.py`) |
| **Auth** | `IsAuthenticated` |
| **Permissions** | None (any authenticated user) |
| **Request serializer** | — |
| **Response serializer** | `UserMeOutputSerializer` |

**Example response:**

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "owner@example.com",
    "accountType": "business",
    "phone_number": "+15551234567",
    "first_name": "Jane",
    "last_name": "Doe",
    "avatar": null,
    "is_verified": true,
    "created_at": "2026-01-15T10:00:00Z"
  },
  "memberships": [
    {
      "tenantId": "660e8400-e29b-41d4-a716-446655440001",
      "tenantName": "My Restaurant",
      "tenantSlug": "my-restaurant",
      "roles": ["owner"],
      "branchAccess": { "scope": "all" },
      "branches": [
        { "id": "...", "name": "Main", "slug": "main", "status": "active", "isDefault": true }
      ]
    }
  ],
  "activeMembership": {
    "tenantId": "660e8400-e29b-41d4-a716-446655440001",
    "branchId": null
  },
  "tenantRoles": [
    {
      "tenant_id": "660e8400-e29b-41d4-a716-446655440001",
      "tenant_slug": "my-restaurant",
      "role": "owner",
      "permissions": ["orders.view", "staff.manage"]
    }
  ],
  "ownership": [
    {
      "ownerId": "...",
      "userId": "...",
      "status": null,
      "plan": null,
      "maxTenants": null,
      "billing": { "customerId": null, "billingEmail": null },
      "createdAt": "2026-01-15T10:00:00Z",
      "verifiedAt": null
    }
  ],
  "staffAssignments": [
    {
      "assignmentId": "...",
      "staffId": "...",
      "tenantId": "...",
      "branchIds": "all",
      "role": "manager",
      "mode": "manage",
      "status": "active",
      "validFrom": null,
      "validUntil": null,
      "grantedBy": null,
      "grantedAt": "2026-02-01T08:00:00Z"
    }
  ]
}
```

> **Note:** `staffAssignments` on `/auth/me` uses **camelCase** (`assignmentId`, `branchIds`). Assignment CRUD under `/api/authorization/...` uses **snake_case** (`assignment_id`, `locations`). See §5.

---

#### `GET /api/auth/me/permissions/`

| Field | Value |
|-------|-------|
| **View** | `MePermissionsView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | Resolved tenant membership (no explicit permission slug required) |
| **Tenant context** | `X-Tenant-Slug` / `X-Tenant-Id` / active tenant / sole membership |
| **Request serializer** | — |
| **Response serializer** | `MePermissionsSerializer` |

**Example response:**

```json
{
  "permissions": ["orders.view", "staff.manage", "menu.view"]
}
```

**Error codes (400):** `ambiguous_tenant`, `no_tenant_context` (tested in `access/tests/test_permission_catalog.py`).

---

#### `GET /api/auth/me/effective-permissions/`

| Field | Value |
|-------|-------|
| **View** | `MeEffectivePermissionsView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | Resolved tenant membership |
| **Tenant context** | Same as `/me/permissions/` |
| **Request serializer** | — |
| **Response serializer** | `EffectivePermissionsSerializer` |

**Example response:**

```json
{
  "permissions": ["orders.view", "analytics.view"],
  "inherited_permissions": ["orders.view"],
  "overrides": [
    { "permission": "analytics.view", "effect": "allow" }
  ]
}
```

---

### 2.2 Permission catalog

Two distinct endpoints serve permission data. Do not conflate them.

#### `GET /api/permissions/` — static catalog

| Field | Value |
|-------|-------|
| **View** | `PermissionCatalogListView` (`access/api/views/tenant_roles.py`) |
| **Auth** | `IsAuthenticated` |
| **Permissions** | None |
| **Pagination** | **None** (bare JSON array) |
| **Response serializer** | `PermissionCatalogSerializer` |

**Example response:**

```json
[
  {
    "key": "orders.view",
    "resource": "orders",
    "action": "view",
    "description": "View orders"
  }
]
```

---

#### `GET /api/authorization/permissions/` — DB permission list (admin)

| Field | Value |
|-------|-------|
| **View** | `PermissionListView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` (superuser, `is_staff`, or `rbac.manage_roles` in any tenant) |
| **Pagination** | Yes (page size 20) |
| **Response serializer** | `PermissionSerializer` |

**Example response (paginated):**

```json
{
  "count": 80,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440000",
      "resource": "orders",
      "action": "view",
      "slug": "orders.view",
      "description": "View orders"
    }
  ]
}
```

---

#### `GET /api/authorization/permissions/{permission_id}/` — permission detail

| Field | Value |
|-------|-------|
| **View** | `PermissionRetrieveView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Response serializer** | `PermissionSerializer` |

**Example response:**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "resource": "orders",
  "action": "view",
  "slug": "orders.view",
  "description": "View orders"
}
```

---

### 2.3 Tenant roles (read-only catalog)

#### `GET /api/tenants/{tenant_id}/roles/`

| Field | Value |
|-------|-------|
| **View** | `TenantRoleListView` (`access/api/views/tenant_roles.py`) |
| **Auth** | `IsAuthenticated` |
| **Permissions** | Tenant member + effective `staff.view` (owners bypass via `TenantOwnerChecker`) |
| **Pagination** | **None** (bare JSON array) |
| **Response serializer** | `TenantRoleListSerializer` |

**Example response:**

```json
[
  {
    "id": "880e8400-e29b-41d4-a716-446655440000",
    "name": "Manager",
    "slug": "manager",
    "is_system_role": true,
    "editable": false,
    "permissions": ["orders.view", "staff.view", "staff.manage"]
  }
]
```

> Returns **system roles only** with their seeded permission slugs. This is a tenant-scoped **read catalog**, not CRUD.

---

### 2.4 Platform role definitions (global admin)

Mounted at `/api/authorization/roles/`. Requires `CanManageRoleDefinitions`.

#### `GET /api/authorization/roles/`

| Field | Value |
|-------|-------|
| **View** | `RoleListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Pagination** | Yes |
| **Response serializer** | `RoleSerializer` |

**Example response (paginated `results` item):**

```json
{
  "id": "...",
  "slug": "manager",
  "name": "Manager",
  "description": "",
  "system_role": true,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

---

#### `POST /api/authorization/roles/`

| Field | Value |
|-------|-------|
| **View** | `RoleListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Request serializer** | `RoleCreateSerializer` |
| **Response serializer** | `RoleSerializer` |
| **Status** | `201 Created` |

**Example request:**

```json
{
  "slug": "custom-role",
  "name": "Custom Role",
  "description": "Optional description"
}
```

**Example response:**

```json
{
  "id": "...",
  "slug": "custom-role",
  "name": "Custom Role",
  "description": "Optional description",
  "system_role": false,
  "created_at": "2026-08-06T12:00:00Z",
  "updated_at": "2026-08-06T12:00:00Z"
}
```

---

#### `GET /api/authorization/roles/{role_id}/`

| Field | Value |
|-------|-------|
| **View** | `RoleRetrieveDestroyView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Response serializer** | `RoleSerializer` |

---

#### `DELETE /api/authorization/roles/{role_id}/`

| Field | Value |
|-------|-------|
| **View** | `RoleRetrieveDestroyView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Response** | `204 No Content` |

---

#### Role permissions sub-resource

**`GET /api/authorization/roles/{role_id}/permissions/`**

| Field | Value |
|-------|-------|
| **View** | `RolePermissionManageView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `CanManageRoleDefinitions` |
| **Response serializer** | `PermissionSerializer` (array, not paginated) |

**Example response:**

```json
[
  {
    "id": "...",
    "resource": "orders",
    "action": "view",
    "slug": "orders.view",
    "description": "View orders"
  }
]
```

---

**`PUT /api/authorization/roles/{role_id}/permissions/`** — atomic replace

| Field | Value |
|-------|-------|
| **Request serializer** | `RolePermissionReplaceSerializer` |
| **Response serializer** | `PermissionSerializer` (array) |

**Example request:**

```json
{
  "permission_ids": [
    "770e8400-e29b-41d4-a716-446655440000",
    "770e8400-e29b-41d4-a716-446655440001"
  ]
}
```

---

**`POST /api/authorization/roles/{role_id}/permissions/`** — additive (by slug)

| Field | Value |
|-------|-------|
| **Request serializer** | `RolePermissionAddSerializer` |
| **Response serializer** | `RoleSerializer` |

**Example request:**

```json
{
  "permission_slugs": ["orders.view", "menu.view"]
}
```

---

### 2.5 Staff memberships

All paths prefixed with `/api/authorization/tenants/{tenant_id}/`.

#### `GET /api/authorization/tenants/{tenant_id}/staff-memberships/`

| Field | Value |
|-------|-------|
| **View** | `StaffMembershipListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` (tenant owner bypasses) |
| **Pagination** | Yes |
| **Response serializer** | `StaffMembershipSerializer` |

**Example response item:**

```json
{
  "id": "...",
  "tenant": "...",
  "user": "...",
  "status": "active",
  "invited_by": "...",
  "joined_at": null,
  "created_at": "...",
  "updated_at": "..."
}
```

---

#### `POST /api/authorization/tenants/{tenant_id}/staff-memberships/`

| Field | Value |
|-------|-------|
| **Request serializer** | `StaffMembershipCreateSerializer` |
| **Response serializer** | `StaffMembershipSerializer` |
| **Status** | `201 Created` |

**Example request:**

```json
{
  "user": "990e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

`status` is optional; defaults to `"pending"`. Allowed values: `pending`, `active`, `suspended`, `removed`.

---

#### `GET /api/authorization/tenants/{tenant_id}/staff-memberships/{membership_id}/`

| Field | Value |
|-------|-------|
| **View** | `StaffMembershipRetrieveUpdateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` |
| **Response serializer** | `StaffMembershipSerializer` |

---

#### `PATCH /api/authorization/tenants/{tenant_id}/staff-memberships/{membership_id}/`

| Field | Value |
|-------|-------|
| **Request serializer** | `StaffMembershipUpdateSerializer` |
| **Response serializer** | `StaffMembershipSerializer` |

**Example request:**

```json
{
  "status": "active"
}
```

Only `status` is writable. Partial update always allowed (`partial=True`).

---

#### `DELETE /api/authorization/tenants/{tenant_id}/staff-memberships/{membership_id}/remove/`

| Field | Value |
|-------|-------|
| **View** | `StaffMembershipRemoveView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` |
| **Behavior** | Soft-remove: sets `status = "removed"` (row retained) |
| **Response serializer** | `StaffMembershipSerializer` |
| **Status** | `200 OK` (not 204) |

> **Not implemented:** `DELETE` on the membership detail URL itself. Removal uses the `/remove/` sub-path.

---

### 2.6 Staff assignments

Canonical write path for role grants. All under `/api/authorization/tenants/{tenant_id}/`.

#### `GET /api/authorization/tenants/{tenant_id}/staff-assignments/`

| Field | Value |
|-------|-------|
| **View** | `StaffAssignmentListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` |
| **Query params** | `membership_id` (optional UUID filter) |
| **Pagination** | Yes |
| **Response serializer** | `StaffAssignmentSerializer` (`access/api/serializers/response/access.py`) |

**Example response item:**

```json
{
  "assignment_id": "aa0e8400-e29b-41d4-a716-446655440000",
  "role": {
    "id": "...",
    "slug": "manager",
    "name": "Manager"
  },
  "locations": [
    { "id": "...", "name": "Branch A" }
  ],
  "all_locations": false,
  "mode": "manage",
  "status": "active",
  "valid_from": null,
  "valid_until": null,
  "granted_by": "...",
  "granted_at": "2026-08-06T12:00:00Z",
  "revoked_by": null,
  "revoked_at": null
}
```

When `all_locations` is `true`, `locations` is `[]`.

---

#### `POST /api/authorization/tenants/{tenant_id}/staff-assignments/`

| Field | Value |
|-------|-------|
| **Request serializer** | `StaffAssignmentCreateSerializer` |
| **Response serializer** | `StaffAssignmentSerializer` |
| **Status** | `201 Created` |

**Verified request fields** (from serializer + tests):

```json
{
  "membership_id": "990e8400-e29b-41d4-a716-446655440000",
  "role_id": "880e8400-e29b-41d4-a716-446655440000",
  "location_ids": ["bb0e8400-e29b-41d4-a716-446655440000"],
  "all_locations": false,
  "mode": "manage",
  "valid_from": null,
  "valid_until": null
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `membership_id` | Yes | Must belong to `tenant_id` in URL |
| `role_id` | Yes | UUID of `Role` |
| `location_ids` | Yes (may be `[]`) | Branch UUIDs; must be `[]` when `all_locations=true` |
| `all_locations` | Yes | `true` = tenant-wide scope |
| `mode` | No | `"manage"` (default) or `"read"` |
| `valid_from` | No | ISO datetime or `null` |
| `valid_until` | No | ISO datetime or `null` |

**Validation rules:**
- `all_locations=true` + non-empty `location_ids` → `400`
- `all_locations=false` + empty `location_ids` → `400`

---

#### `GET /api/authorization/tenants/{tenant_id}/staff-assignments/{assignment_id}/`

| Field | Value |
|-------|-------|
| **View** | `StaffAssignmentRetrieveUpdateDestroyView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` |
| **Response serializer** | `StaffAssignmentSerializer` |

---

#### `PUT /api/authorization/tenants/{tenant_id}/staff-assignments/{assignment_id}/`

| Field | Value |
|-------|-------|
| **Request serializer** | `StaffAssignmentUpdateSerializer` (full replace) |
| **Response serializer** | `StaffAssignmentSerializer` |

**Example request:**

```json
{
  "role_id": "...",
  "location_ids": ["..."],
  "all_locations": false,
  "mode": "read",
  "valid_from": null,
  "valid_until": null
}
```

All of `role_id`, `location_ids`, `all_locations`, `mode` are required on PUT.

---

#### `PATCH /api/authorization/tenants/{tenant_id}/staff-assignments/{assignment_id}/`

| Field | Value |
|-------|-------|
| **Request serializer** | `StaffAssignmentUpdateSerializer` (partial) |

**Example request (scope-only update):**

```json
{
  "location_ids": ["...", "..."],
  "all_locations": false
}
```

---

#### `DELETE /api/authorization/tenants/{tenant_id}/staff-assignments/{assignment_id}/`

| Field | Value |
|-------|-------|
| **Behavior** | Soft-revoke: `status = "revoked"`, sets `revoked_by` / `revoked_at` |
| **Response serializer** | `StaffAssignmentSerializer` |
| **Status** | `200 OK` (returns revoked assignment body) |

---

### 2.7 Permission overrides

#### Tenant-scoped (all memberships)

**`GET /api/authorization/tenants/{tenant_id}/permission-overrides/`**

| Field | Value |
|-------|-------|
| **View** | `PermissionOverrideListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.view` (GET) / `staff.manage` (POST) |
| **Query params** | `membership_id` (optional UUID filter) |
| **Pagination** | Yes |
| **Response serializer** | `PermissionOverrideSerializer` |

**`POST /api/authorization/tenants/{tenant_id}/permission-overrides/`**

| Field | Value |
|-------|-------|
| **Request serializer** | `PermissionOverrideCreateSerializer` |
| **Status** | `201 Created` |

**Example request:**

```json
{
  "membership_id": "...",
  "permission_id": "...",
  "effect": "allow"
}
```

`effect`: `"allow"` or `"deny"`.

---

**`GET /api/authorization/tenants/{tenant_id}/permission-overrides/{override_id}/`**

| Field | Value |
|-------|-------|
| **View** | `PermissionOverrideRetrieveUpdateDestroyView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.manage` |
| **Response serializer** | `PermissionOverrideSerializer` |

---

**`PATCH /api/authorization/tenants/{tenant_id}/permission-overrides/{override_id}/`**

| Field | Value |
|-------|-------|
| **Request serializer** | `PermissionOverrideUpdateSerializer` |

**Example request:**

```json
{
  "effect": "deny"
}
```

---

**`DELETE /api/authorization/tenants/{tenant_id}/permission-overrides/{override_id}/`**

| Status | `204 No Content` |

**Example override response:**

```json
{
  "id": "...",
  "membership": "...",
  "permission": {
    "id": "...",
    "slug": "analytics.view",
    "resource": "analytics",
    "action": "view",
    "description": "..."
  },
  "effect": "allow",
  "created_by": "...",
  "created_at": "...",
  "updated_at": "..."
}
```

---

#### Membership-scoped

**`GET /api/authorization/tenants/{tenant_id}/memberships/{membership_id}/permission-overrides/`**

| Field | Value |
|-------|-------|
| **View** | `MembershipPermissionOverrideListCreateView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.view` (GET) / `staff.manage` (POST) |
| **Pagination** | Yes |

**`POST /api/authorization/tenants/{tenant_id}/memberships/{membership_id}/permission-overrides/`**

| Field | Value |
|-------|-------|
| **Request serializer** | `MembershipPermissionOverrideCreateSerializer` |

**Example request:**

```json
{
  "permission_id": "...",
  "effect": "deny"
}
```

> `membership_id` comes from the URL, not the body.

---

**`GET/PATCH/DELETE /api/authorization/tenants/{tenant_id}/memberships/{membership_id}/permission-overrides/{override_id}/`**

| Field | Value |
|-------|-------|
| **View** | `MembershipPermissionOverrideRetrieveUpdateDestroyView` |
| **Permissions** | `staff.manage` (all methods) |
| **PATCH request** | `PermissionOverrideUpdateSerializer` (`effect` only) |
| **DELETE status** | `204 No Content` |

---

### 2.8 Permission audit

#### `GET /api/authorization/tenants/{tenant_id}/permission-audit/`

| Field | Value |
|-------|-------|
| **View** | `PermissionAuditListView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | `staff.view` |
| **Pagination** | Yes (default page size 20) |
| **Filters** | **None** — no query-param filters; queryset is all audit rows for `tenant_id`, ordered `-created_at` |
| **Response serializer** | `PermissionAuditSerializer` |

**Example response (paginated):**

```json
{
  "count": 6,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "...",
      "action": "assignment_created",
      "actor": "...",
      "tenant": "...",
      "membership": "...",
      "assignment": "...",
      "permission": null,
      "metadata": {},
      "created_at": "2026-08-06T12:00:00Z"
    }
  ]
}
```

**Known `action` values** (from `PermissionAuditAction`): `assignment_created`, `assignment_updated`, `assignment_revoked`, `override_created`, `override_updated`, `override_removed`, `role_permissions_changed`, `ownership_transferred`.

---

### 2.9 Context switching (related)

#### `POST /api/authorization/switch-tenant/`

| Field | Value |
|-------|-------|
| **View** | `SwitchActiveTenantAPIView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | None |
| **Request serializer** | `SwitchActiveTenantInputSerializer` |
| **Status** | `204 No Content` |

**Example request:**

```json
{
  "tenantId": "660e8400-e29b-41d4-a716-446655440001"
}
```

---

#### `POST /api/authorization/switch-branch/`

| Field | Value |
|-------|-------|
| **View** | `SwitchActiveBranchAPIView` |
| **Auth** | `IsAuthenticated` |
| **Permissions** | None |
| **Request serializer** | `SwitchActiveBranchInputSerializer` |
| **Status** | `204 No Content` |

**Example request:**

```json
{
  "branchId": "bb0e8400-e29b-41d4-a716-446655440000"
}
```

---

## 3. Missing / not-implemented endpoints

| Expected capability | Status | Actual replacement |
|---------------------|--------|-------------------|
| `PATCH/PUT /api/authorization/roles/{role_id}/` (update role metadata) | **Not implemented** | Create + delete only; no update view registered |
| `DELETE /api/authorization/tenants/.../staff-memberships/{id}/` | **Not implemented** | Use `DELETE .../staff-memberships/{id}/remove/` (works on canonical and alias paths) |
| Hard `DELETE` on staff assignments | **Not implemented** | `DELETE` soft-revokes (`status=revoked`) |
| Audit endpoint filters (by action, actor, date) | **Not implemented** | Full tenant list only, paginated |
| `GET` detail on permission overrides via tenant list URL | **Implemented** | `GET .../permission-overrides/{override_id}/` |

### Compatibility aliases added (2026-08-06)

These paths now work and point to existing views:

| Alias path | Canonical equivalent |
|------------|---------------------|
| `/api/access/tenants/{tenant_id}/staff-memberships/` | `/api/authorization/tenants/{tenant_id}/staff-memberships/` |
| `/api/access/tenants/{tenant_id}/staff-assignments/` | `/api/authorization/tenants/{tenant_id}/staff-assignments/` |
| `/api/access/tenants/{tenant_id}/permission-overrides/` | `/api/authorization/tenants/{tenant_id}/permission-overrides/` |
| `/api/access/tenants/{tenant_id}/permission-audit/` | `/api/authorization/tenants/{tenant_id}/permission-audit/` |
| `/api/access/roles/` | `/api/authorization/roles/` |
| `/api/tenants/{tenant_id}/staff-memberships/` | `/api/authorization/tenants/{tenant_id}/staff-memberships/` |
| `/api/tenants/{tenant_id}/staff-assignments/` | `/api/authorization/tenants/{tenant_id}/staff-assignments/` |
| `/api/tenants/{tenant_id}/permission-overrides/` | `/api/authorization/tenants/{tenant_id}/permission-overrides/` |
| `/api/tenants/{tenant_id}/permission-audit/` | `/api/authorization/tenants/{tenant_id}/permission-audit/` |

---

## 4. Deprecated / legacy notes

| Item | Status |
|------|--------|
| `RolePermissionAddView` class | Marked `deprecated=True` in OpenAPI schema; **not a separate URL**. Same route as `RolePermissionManageView` — `POST` adds by slug, `PUT` replaces by id. |
| `/api/access/` prefix | Compatibility alias added at `/api/access/` → same `access.api.urls` module. Prefer `/api/authorization/` for new code. |
| `StaffAssignment` camelCase serializer in `access/api/serializers/response/rbac.py` | Used only for `/api/auth/me` embedding, **not** for assignment CRUD responses. |
| Pre-D2 assignment shape (`branch` FK on assignment) | Removed; locations via `location_ids` / junction table. |

---

## 5. Frontend integration recommendations

### 5.1 Use the correct base paths

**Canonical (recommended for new frontend code):**

```text
Session / identity     → /api/auth/me*
Permission catalog UI  → GET /api/permissions/          (static, array)
Tenant role picker     → GET /api/tenants/{tenantId}/roles/  (array)
Staff CRUD             → /api/authorization/tenants/{tenantId}/staff-memberships/
Assignments            → /api/authorization/tenants/{tenantId}/staff-assignments/
Overrides              → /api/authorization/tenants/{tenantId}/permission-overrides/
                         or .../memberships/{membershipId}/permission-overrides/
Audit log              → /api/authorization/tenants/{tenantId}/permission-audit/
Platform role admin    → /api/authorization/roles/      (requires rbac.manage_roles)
```

**Compatibility aliases (existing frontend paths):**

```text
/api/access/tenants/{tenantId}/staff-*     → same as /api/authorization/tenants/{tenantId}/staff-*
/api/access/roles/                         → same as /api/authorization/roles/
/api/tenants/{tenantId}/staff-memberships/ → same as /api/authorization/tenants/{tenantId}/staff-memberships/
/api/tenants/{tenantId}/staff-assignments/ → same as /api/authorization/tenants/{tenantId}/staff-assignments/
```

### 5.2 Handle two response dialects

| Context | Assignment field names | Location scope |
|---------|----------------------|----------------|
| `/api/auth/me` | camelCase: `assignmentId`, `branchIds`, `validFrom` | `branchIds: "all"` or array of UUID strings |
| `/api/authorization/.../staff-assignments` | snake_case: `assignment_id`, `locations`, `valid_from` | `all_locations: true` + `locations: []`, or `locations: [{id, name}]` |

Do not assume one shape works for both.

### 5.3 Tenant context for permission endpoints

When the user has multiple tenants, send `X-Tenant-Id` or `X-Tenant-Slug` on:

- `GET /api/auth/me/permissions/`
- `GET /api/auth/me/effective-permissions/`

Alternatively, call `POST /api/authorization/switch-tenant/` first to set `user.active_tenant_id`.

### 5.4 Pagination handling

Expect paginated `{count, next, previous, results}` for:

- Staff memberships, assignments, overrides (list)
- Permission audit
- `/api/authorization/permissions/` and `/api/authorization/roles/`

Expect **bare arrays** for:

- `GET /api/permissions/`
- `GET /api/tenants/{tenant_id}/roles/`

### 5.5 Permission gates

| Action | Minimum permission |
|--------|-------------------|
| View staff roster / audit / override lists | `staff.view` |
| Manage staff, assignments, overrides | `staff.manage` |
| View tenant role catalog | `staff.view` (+ tenant membership) |
| Platform role CRUD + role permission editing | `rbac.manage_roles` (or superuser/staff) |

Tenant owners bypass `RequirePermission` checks via `TenantOwnerChecker`.

### 5.6 Revoke vs delete semantics

- **Assignments:** `DELETE` → soft revoke, returns `200` with `status: "revoked"`.
- **Memberships:** `DELETE .../remove/` → soft remove, returns `200` with `status: "removed"`.
- **Overrides:** `DELETE` → hard delete, returns `204`.

---

## 6. Verification methods used

| Method | Result |
|--------|--------|
| Static URL audit | `SmartRestaurant/urls.py`, `access/api/urls.py`, `accounts/api/urls.py`, `tenants/api/urls.py` |
| `grep` for RBAC routes | Confirmed all registrations; no `/api/access/` matches |
| Integration tests | `access/tests/test_staff_assignment_api.py`, `test_wave4_rbac_advanced.py`, `test_permission_catalog.py`, `test_me_contract.py`, `test_rbac_role_protection.py` |
| Django URL resolver (`manage.py shell`) | Verified via `access/tests/test_url_compat.py` |

---

## 7. Quick-reference endpoint index

| Method | Path | View |
|--------|------|------|
| GET | `/api/auth/me/` | `MeView` |
| GET | `/api/auth/me/permissions/` | `MePermissionsView` |
| GET | `/api/auth/me/effective-permissions/` | `MeEffectivePermissionsView` |
| GET | `/api/permissions/` | `PermissionCatalogListView` |
| GET | `/api/authorization/permissions/` | `PermissionListView` |
| GET | `/api/authorization/permissions/{permission_id}/` | `PermissionRetrieveView` |
| GET | `/api/tenants/{tenant_id}/roles/` | `TenantRoleListView` |
| GET, POST | `/api/authorization/roles/` | `RoleListCreateView` |
| GET, DELETE | `/api/authorization/roles/{role_id}/` | `RoleRetrieveDestroyView` |
| GET, PUT, POST | `/api/authorization/roles/{role_id}/permissions/` | `RolePermissionManageView` |
| GET, POST | `/api/authorization/tenants/{tenant_id}/staff-memberships/` | `StaffMembershipListCreateView` |
| GET, PATCH | `/api/authorization/tenants/{tenant_id}/staff-memberships/{membership_id}/` | `StaffMembershipRetrieveUpdateView` |
| DELETE | `/api/authorization/tenants/{tenant_id}/staff-memberships/{membership_id}/remove/` | `StaffMembershipRemoveView` |
| GET, POST | `/api/authorization/tenants/{tenant_id}/staff-assignments/` | `StaffAssignmentListCreateView` |
| GET, PUT, PATCH, DELETE | `/api/authorization/tenants/{tenant_id}/staff-assignments/{assignment_id}/` | `StaffAssignmentRetrieveUpdateDestroyView` |
| GET, POST | `/api/authorization/tenants/{tenant_id}/permission-overrides/` | `PermissionOverrideListCreateView` |
| GET, PATCH, DELETE | `/api/authorization/tenants/{tenant_id}/permission-overrides/{override_id}/` | `PermissionOverrideRetrieveUpdateDestroyView` |
| GET, POST | `/api/authorization/tenants/{tenant_id}/memberships/{membership_id}/permission-overrides/` | `MembershipPermissionOverrideListCreateView` |
| GET, PATCH, DELETE | `/api/authorization/tenants/{tenant_id}/memberships/{membership_id}/permission-overrides/{override_id}/` | `MembershipPermissionOverrideRetrieveUpdateDestroyView` |
| GET | `/api/authorization/tenants/{tenant_id}/permission-audit/` | `PermissionAuditListView` |
| POST | `/api/authorization/switch-tenant/` | `SwitchActiveTenantAPIView` |
| POST | `/api/authorization/switch-branch/` | `SwitchActiveBranchAPIView` |
