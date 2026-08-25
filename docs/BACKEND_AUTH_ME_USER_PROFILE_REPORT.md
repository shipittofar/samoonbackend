# GET /api/auth/me/ — Complete User Profile Contract

## Dependency trace

`URL → View → User model → Response builder`:

- `SmartRestaurant/urls.py` → `path('api/auth/', include('accounts.api.urls', ...))`
- `accounts/api/urls.py` → `path("me/", MeView.as_view(), name="me")`
- `accounts/api/views/auth.py::MeView.get()` — a hand-built `Response(dict)`,
  not a `ModelSerializer` (this is why the `user` sub-object previously
  only had 3 fields hardcoded into the dict literal — there was no
  serializer in the loop to have picked up the rest of the model
  automatically).
- `accounts/models/user.py::User` — the source of every added field
  (`phone_number`, `first_name`, `last_name`, `avatar`, `is_verified`,
  `created_at` all already exist on the model; nothing was added there).

No frontend code exists in this repository (confirmed backend-only, same
as every prior phase) — this fix is backend-contract-only, per what's
actually in scope here.

## Change

`accounts/api/views/auth.py::MeView.get()` — the `user` dict now includes
all six requested fields, read live from `request.user` on every request
(never hardcoded):

```python
avatar_url = None
if user.avatar:
    avatar_url = request.build_absolute_uri(user.avatar.url) if request else user.avatar.url

"user": {
    "id": str(user.id),
    "email": user.email,
    "accountType": user.account_type,
    "phone_number": user.phone_number or "",
    "first_name": user.first_name or "",
    "last_name": user.last_name or "",
    "avatar": avatar_url,
    "is_verified": user.is_verified,
    "created_at": user.created_at,
},
```

- **`avatar`** — `null` when unset (an `ImageField` with no file), an
  absolute URL when set — matching the existing avatar-serialization
  pattern already used by `UserOutputSerializer.get_avatar()` elsewhere
  in this app, for consistency.
- **`phone_number`/`first_name`/`last_name`** — the model allows these to
  be `None` (`blank=True, null=True`); coerced to `""` to match the
  documented target contract's example (`"phone_number": ""`), not left
  as `null`.
- **`is_verified`** — plain boolean passthrough, never `null` (model
  default `False`).
- **`created_at`** — passed through as the raw `datetime` object; DRF's
  `JSONRenderer` (via `rest_framework.utils.encoders.JSONEncoder`, already
  in use for every other endpoint in this API) serializes it as ISO 8601
  UTC (`"2026-07-18T20:21:53.194904Z"`), matching the rest of the API's
  datetime format with no extra formatting code needed.

`memberships`/`activeMembership`/RBAC/branch-access logic is completely
untouched — confirmed by `test_profile_fields_do_not_affect_memberships_or_rbac`
(new test, asserts the exact same membership/role/branch-access shape as
before this change).

## Backward compatibility

Every previously-existing key (`id`, `email`, `accountType`,
`memberships`, `activeMembership`) is unchanged in name, type, and
meaning — this is a strictly additive change to the `user` sub-object.
Any consumer reading only the original three `user` fields keeps working
unmodified.

`MeView` is the only place this dict is built — `login`, `OTP verify`
(`VerifyOTPView`), `token refresh` (`TokenRefreshView`, from
`rest_framework_simplejwt`), `profile update`, and `logout` all use the
separate, pre-existing `UserOutputSerializer`
(`accounts/api/serializers/response/user.py`), which already had all six
of these fields (that serializer was not touched — no duplicate user
model or serializer was created, per the instruction). Those flows were
verified unaffected by re-running the full test suite.

## Tests added

`access/tests/test_schema_alignment.py::AuthMeUserProfileContractTests`
(6 tests):
- `test_normal_verified_user` — full field-set + type assertions, ISO
  8601 `created_at` format check.
- `test_unverified_user` — `is_verified: false`.
- `test_user_without_avatar` — `avatar: null`.
- `test_user_without_phone_number` — `phone_number: ""` (not `null`).
- `test_user_without_first_or_last_name` — both coerced to `""`.
- `test_profile_fields_do_not_affect_memberships_or_rbac` — membership
  roles, branch access, and active-membership resolution are identical to
  pre-change behavior.

## Verification

- `python manage.py check` — clean.
- `python manage.py test` — **67/67 passing** (61 pre-existing + 6 new).
- `python manage.py makemigrations --check --dry-run` — no changes (no
  model change was needed — every added field already existed on `User`).
