# Console pending counts — Frontend Integration Contract
#
# This document describes the production backend contract for Console
# pending-order and pending-reservation badges. The WebSocket is a
# synchronization signal only. Authoritative counts come from HTTP.

## WebSocket

Endpoint:
    ws://<host>/ws/console/<branch_id>/?token=<access_token>

Authentication:
    Existing Django Channels JWT query-string auth
    (`core.middleware.JWTAuthMiddleware`).
    Pass the SimpleJWT access token as `token`.
    Unauthenticated connections close with code 4001.

Authorization:
    After authentication, the backend loads the branch from the URL.
    Tenant is derived from that branch — never from client input.
    Access is granted if the user is the tenant owner **or** holds
    `orders.view` or `reservations.view` on that exact tenant + branch
    (existing RBAC / StaffAssignment location scope).
    Unauthorized branch access closes with code 4003.
    Unknown branch closes with code 4004.

Tenant scope:
    Taken from `branch.tenant_id` after the branch lookup. Query
    parameters and WebSocket messages cannot change tenant.

Branch scope:
    Taken from the URL `branch_id` after permission checks. Query
    parameters (`tenant_id`, `branch_id`, `admin`) and client messages
    (`join`, injected group names) are ignored for membership.

Group naming:
    `console.{tenant_id}.{branch_id}`

Connection behavior:
    One long-lived Console workspace socket. It is not tied to a
    specific Console page. On tenant/branch switch, disconnect and
    connect to the new `/ws/console/<branch_id>/`.

Reconnect:
    Authenticate again with a valid access token, authorize, join the
    current tenant+branch group, then refetch both pending-count HTTP
    endpoints. The server holds no extra session state.

## Events

Order event:
    `order.changed`

Reservation event:
    `reservation.changed`

These names are the Console contract. The existing per-order customer
socket (`/ws/orders/<order_id>/`) still emits its original payload
(`connection_established` + `order.status.update` handler) and is
unchanged.

Payload (order):

```json
{
  "type": "order.changed",
  "data": {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "branch_id": "22222222-2222-2222-2222-222222222222",
    "order_id": "33333333-3333-3333-3333-333333333333",
    "status": "pending"
  }
}
```

Payload (reservation):

```json
{
  "type": "reservation.changed",
  "data": {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "branch_id": "22222222-2222-2222-2222-222222222222",
    "reservation_id": "44444444-4444-4444-4444-444444444444",
    "status": "pending"
  }
}
```

On successful connect the server also sends:

```json
{
  "type": "connection_established",
  "data": {
    "tenant_id": "...",
    "branch_id": "..."
  }
}
```

When emitted:
    After the database transaction commits (`transaction.on_commit`).
    Orders: create, customer cancel, tenant-owner status update.
    Reservations: create, customer cancel, console status update
    (`reservations.manage` or tenant owner).
    Rolled-back transactions do not emit.

Do not increment/decrement locally. Treat every event as “invalidate
and refetch the authoritative count”. Duplicate delivery is not
expected from the BLL publishing boundary, but refetch remains safe
if it occurs.

## Pending status definitions

Pending orders:
    `Order.status == "pending"` only.
    `accepted` (enum name CONFIRMED), `preparing`, `ready`, `served`,
    `delivered`, `completed`, `picked_up`, and `cancelled` are excluded.

Pending reservations:
    `Reservation.status == "pending"` only.
    `confirmed`, `seated`, `completed`, `cancelled`, and `no_show`
    are excluded.

## HTTP

Pending Order count endpoint:
    GET /api/orders/console-orders/tenants/{tenant_id}/branches/{branch_id}/pending-count/

Pending Reservation count endpoint:
    GET /api/reservations/console-reservations/tenants/{tenant_id}/branches/{branch_id}/pending-count/

Response format (both):

```json
{
  "count": 3
}
```

Authorization/scoping:
    `Authorization: Bearer <access_token>`
    Path `tenant_id` + `branch_id` must match a real branch of that tenant.
    Tenant owner is always allowed.
    Staff need `orders.view` (orders count) or `reservations.view`
    (reservations count) at that branch.
    Query parameters are not authorization.
    There is no `GET /api/reservations/?admin=true` list. That method
    is rejected (create-only collection).

## Frontend Integration Contract

### WebSocket endpoint

```
/ws/console/{branch_id}/?token={access_token}
```

### Connection requirements

authentication:
    SimpleJWT access token as query parameter `token`
    (same mechanism as `/ws/orders/{public_id}/`).

tenant context:
    Not sent by the client. Derived from the authorized branch.

branch context:
    URL path `branch_id`. Validated against the user’s owner
    relationship or RBAC assignment locations.

### Event types

```
order.changed
reservation.changed
```

### Payload examples

See JSON examples above.

### Count endpoints

```
GET /api/orders/console-orders/tenants/{tenant_id}/branches/{branch_id}/pending-count/
GET /api/reservations/console-reservations/tenants/{tenant_id}/branches/{branch_id}/pending-count/
```

```json
{ "count": 2 }
```

### Authorization model

Authenticated user → tenant owner **or** staff membership with an
active assignment covering the branch → permission check
(`orders.view` / `reservations.view` for counts; either permission
for the Console socket).

### Reconnect behavior

```
Client reconnects
→ re-authenticates with a current access token
→ rejoins console.{tenant_id}.{branch_id}
→ receives connection_established
→ client refetches both pending-count endpoints
→ subsequent mutations emit order.changed / reservation.changed
```
