"""/api/wallet/

Customer (own wallet only):
  GET  ""                      balances per currency
  GET  transactions/           ledger lines (?currency=&page=&pageSize=)

Platform superusers:
  GET  admin/users/?search=    users with their balances
  GET  admin/users/<id>/       one user's accounts and recent lines
  POST admin/users/<id>/adjust/  {currency, amount (+/-), reason, idempotencyKey}
  POST admin/users/<id>/freeze/  {currency, frozen}
  GET  admin/health/           ledger invariants (also: manage.py wallet_check)
  GET/PUT admin/limits/        {"per_transaction": {...}, "daily_spend": {...}, "daily_topup": {...}}
  GET  admin/topups/?status=&provider=&search=   top-ups (status=review: waiting for a superuser)
  POST admin/topups/<id>/approve/ {amount?, note}  |  reject/ {reason}
  GET/PUT admin/topup-settings/  gateways, coins, receiving addresses, min/max

Top-ups:
  GET  topups/options/         what the customer can use now
  GET/POST topups/             own top-ups / start {method, provider, amount, asset}
  GET  topups/<id>/            status;  POST topups/<id>/tx/ {txHash};  POST topups/<id>/cancel/
  GET/POST topups/<id>/callback/   bank gateways return the payer here (public)
  POST topups/webhook/<provider>/  signed crypto notifications (public)
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from superadmin.api.permissions import IsPlatformSuperuser
from wallet import services, topups
from wallet.gateways import GatewayError
from wallet.models import AccountKind, LedgerEntry, TopUp, WalletAccount

MAX_PAGE = 100


def _dec(value) -> str:
    return format(Decimal(value).quantize(Decimal("0.0001")).normalize(), "f")


def _account(a: WalletAccount) -> dict:
    return {"currency": a.currency, "balance": _dec(a.balance), "frozen": a.is_frozen}


def _line(e: LedgerEntry) -> dict:
    tx = e.transaction
    return {
        "id": e.id,
        "transactionId": str(tx.id),
        "kind": tx.kind,
        "currency": e.account.currency,
        "amount": _dec(e.amount),
        "balanceAfter": _dec(e.balance_after),
        "description": tx.description,
        "orderId": str(tx.order_id) if tx.order_id else None,
        "orderNumber": tx.order.order_number if tx.order_id else None,
        "createdAt": e.created_at.isoformat(),
    }


def _lines(qs, params) -> dict:
    currency = (params.get("currency") or "").upper()
    if currency:
        qs = qs.filter(account__currency=currency)
    try:
        page = max(1, int(params.get("page", 1)))
        size = min(MAX_PAGE, max(1, int(params.get("pageSize", 20))))
    except ValueError:
        page, size = 1, 20
    count = qs.count()
    rows = qs.select_related("transaction__order", "account")[(page - 1) * size: page * size]
    return {"results": [_line(e) for e in rows], "count": count, "page": page, "pageSize": size}


class MyWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = WalletAccount.objects.filter(kind=AccountKind.CUSTOMER, user=request.user).order_by("currency")
        return Response({"accounts": [_account(a) for a in accounts]})


class MyTransactionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LedgerEntry.objects.filter(account__kind=AccountKind.CUSTOMER, account__user=request.user)
        return Response(_lines(qs, request.query_params))


# ── Superuser ────────────────────────────────────────────────────────────────


def _user_row(u: User) -> dict:
    return {
        "id": str(u.id),
        "name": " ".join(p for p in (u.first_name, u.last_name) if p),
        "phone": u.phone_number or "",
        "email": u.email or "",
        "accounts": [_account(a) for a in u.wallet_accounts.filter(kind=AccountKind.CUSTOMER).order_by("currency")],
    }


class AdminUsersView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        q = (request.query_params.get("search") or "").strip()
        qs = User.objects.filter(is_deleted=False)
        if q:
            qs = qs.filter(Q(phone_number__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        else:
            qs = qs.filter(wallet_accounts__kind=AccountKind.CUSTOMER).distinct()
        return Response({"results": [_user_row(u) for u in qs.order_by("-created_at")[:50]]})


class AdminUserDetailView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        qs = LedgerEntry.objects.filter(account__kind=AccountKind.CUSTOMER, account__user=user)
        return Response({**_user_row(user), "lines": _lines(qs, request.query_params)})


class AdminAdjustView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        currency = str(request.data.get("currency") or "").upper()
        from currencies.services import is_known

        if not is_known(currency):
            raise ValidationError({"currency": "Unknown currency."})
        key = str(request.data.get("idempotencyKey") or request.headers.get("Idempotency-Key") or "").strip()
        if len(key) < 8:
            raise ValidationError({"idempotencyKey": "Send a unique key per adjustment (prevents double posting)."})
        tx = services.adjust(
            user=user,
            currency=currency,
            amount=request.data.get("amount"),
            reason=str(request.data.get("reason") or ""),
            actor=request.user,
            idempotency_key=f"adjust:{key}",
        )
        return Response({"transactionId": str(tx.id), **_user_row(user)})


class AdminFreezeView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        currency = str(request.data.get("currency") or "").upper()
        account = services.customer_account(user, currency)
        account.is_frozen = bool(request.data.get("frozen"))
        account.save(update_fields=["is_frozen", "updated_at"])
        return Response(_user_row(user))


class AdminHealthView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(services.health())


class AdminLimitsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(services.limits())

    def put(self, request):
        from platform_settings.models import PlatformSetting

        data = request.data if isinstance(request.data, dict) else {}
        clean: dict[str, dict[str, str]] = {}
        for name in ("per_transaction", "daily_spend", "daily_topup"):
            raw = data.get(name) or {}
            if not isinstance(raw, dict):
                raise ValidationError({name: "Expected currency -> amount."})
            clean[name] = {}
            for code, value in raw.items():
                if value in (None, ""):
                    continue
                try:
                    amount = Decimal(str(value))
                except InvalidOperation:
                    raise ValidationError({name: f"{code}: not a number."})
                if amount <= 0:
                    raise ValidationError({name: f"{code}: must be positive."})
                clean[name][str(code).upper()] = str(amount)
        row, _ = PlatformSetting.objects.get_or_create(key=services.LIMITS_KEY)
        row.value = clean
        row.updated_by = request.user
        row.save()
        return Response(clean)


# ── Top-ups (phase E) ────────────────────────────────────────────────────────


def _page(qs, params) -> dict:
    try:
        page = max(1, int(params.get("page", 1)))
        size = min(MAX_PAGE, max(1, int(params.get("pageSize", 20))))
    except ValueError:
        page, size = 1, 20
    count = qs.count()
    return {"rows": qs[(page - 1) * size: page * size], "count": count, "page": page, "pageSize": size}


def _paged(page: dict, rows: list) -> dict:
    return {"results": rows, "count": page["count"], "page": page["page"], "pageSize": page["pageSize"]}


class TopUpOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(topups.options())


class MyTopUpsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_topup"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        page = _page(TopUp.objects.filter(user=request.user), request.query_params)
        return Response(_paged(page, [topups.serialize(t) for t in page["rows"]]))

    def post(self, request):
        data = request.data
        result = topups.start(
            user=request.user,
            method=str(data.get("method") or ""),
            provider=str(data.get("provider") or ""),
            amount=data.get("amount"),
            asset=str(data.get("asset") or ""),
            request=request,
        )
        return Response(result, status=201)


class MyTopUpDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, topup_id):
        return Response(topups.serialize(get_object_or_404(TopUp, id=topup_id, user=request.user)))


class MyTopUpTxView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, topup_id):
        get_object_or_404(TopUp, id=topup_id, user=request.user)
        topup = topups.submit_tx(user=request.user, topup_id=topup_id, tx_hash=str(request.data.get("txHash") or ""))
        return Response(topups.serialize(topup))


class MyTopUpCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, topup_id):
        get_object_or_404(TopUp, id=topup_id, user=request.user)
        return Response(topups.serialize(topups.cancel(user=request.user, topup_id=topup_id)))


class TopUpCallbackView(APIView):
    """The payer's browser returns here from a bank gateway (GET or POST form).
    We verify with the gateway, then send the browser to the wallet page."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def _handle(self, request, topup_id):
        params = dict(request.query_params.items())
        if hasattr(request.data, "items"):
            params.update({k: (v if isinstance(v, str) else str(v)) for k, v in request.data.items()})
        try:
            topups.confirm(topup_id, params)
        except TopUp.DoesNotExist:
            pass
        return HttpResponseRedirect(f"{settings.PUBLIC_SITE_URL}/dashboard/wallet?topup={topup_id}")

    def get(self, request, topup_id):
        return self._handle(request, topup_id)

    def post(self, request, topup_id):
        return self._handle(request, topup_id)


class TopUpWebhookView(APIView):
    """Signed server-to-server notification from a crypto gateway."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, provider):
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            topups.webhook(provider, request.body, headers)
        except GatewayError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"ok": True})


class AdminTopUpsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        topups.expire_stale()
        qs = TopUp.objects.select_related("user")
        params = request.query_params
        status = params.get("status") or ""
        if status == "review":
            # Direct transfers with a hash, and verified payments not yet credited.
            qs = qs.filter(
                Q(provider="direct", status="pending", receipt_ref__gt="") | Q(verified=True, ledger_transaction__isnull=True)
            )
        elif status:
            qs = qs.filter(status=status)
        if params.get("provider"):
            qs = qs.filter(provider=params["provider"])
        search = (params.get("search") or "").strip()
        if search:
            cond = (
                Q(user__phone_number__icontains=search)
                | Q(user__email__icontains=search)
                | Q(receipt_ref__icontains=search)
                | Q(gateway_ref=search)
            )
            if search.isdigit():
                cond |= Q(order_number=int(search))
            qs = qs.filter(cond)
        page = _page(qs, params)
        return Response(_paged(page, [topups.serialize(t, admin=True) for t in page["rows"]]))


class AdminTopUpDetailView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request, topup_id):
        topup = get_object_or_404(TopUp.objects.select_related("user"), id=topup_id)
        return Response(topups.serialize(topup, admin=True))


class AdminTopUpApproveView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, topup_id):
        get_object_or_404(TopUp, id=topup_id)
        topup = topups.approve(
            topup_id=topup_id, actor=request.user, amount=request.data.get("amount"), note=str(request.data.get("note") or "")
        )
        return Response(topups.serialize(topup, admin=True))


class AdminTopUpRejectView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, topup_id):
        get_object_or_404(TopUp, id=topup_id)
        topup = topups.reject(topup_id=topup_id, actor=request.user, reason=str(request.data.get("reason") or ""))
        return Response(topups.serialize(topup, admin=True))


class AdminTopUpSettingsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(topups.admin_settings())

    def put(self, request):
        topups.save_settings(request.data if isinstance(request.data, dict) else {}, actor=request.user)
        return Response(topups.admin_settings())


app_name = "wallet"

urlpatterns = [
    path("", MyWalletView.as_view(), name="mine"),
    path("transactions/", MyTransactionsView.as_view(), name="transactions"),
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/users/<uuid:user_id>/", AdminUserDetailView.as_view(), name="admin-user"),
    path("admin/users/<uuid:user_id>/adjust/", AdminAdjustView.as_view(), name="admin-adjust"),
    path("admin/users/<uuid:user_id>/freeze/", AdminFreezeView.as_view(), name="admin-freeze"),
    path("admin/health/", AdminHealthView.as_view(), name="admin-health"),
    path("admin/limits/", AdminLimitsView.as_view(), name="admin-limits"),
    path("topups/", MyTopUpsView.as_view(), name="topups"),
    path("topups/options/", TopUpOptionsView.as_view(), name="topup-options"),
    path("topups/webhook/<str:provider>/", TopUpWebhookView.as_view(), name="topup-webhook"),
    path("topups/<uuid:topup_id>/", MyTopUpDetailView.as_view(), name="topup"),
    path("topups/<uuid:topup_id>/tx/", MyTopUpTxView.as_view(), name="topup-tx"),
    path("topups/<uuid:topup_id>/cancel/", MyTopUpCancelView.as_view(), name="topup-cancel"),
    path("topups/<uuid:topup_id>/callback/", TopUpCallbackView.as_view(), name="topup-callback"),
    path("admin/topups/", AdminTopUpsView.as_view(), name="admin-topups"),
    path("admin/topups/<uuid:topup_id>/", AdminTopUpDetailView.as_view(), name="admin-topup"),
    path("admin/topups/<uuid:topup_id>/approve/", AdminTopUpApproveView.as_view(), name="admin-topup-approve"),
    path("admin/topups/<uuid:topup_id>/reject/", AdminTopUpRejectView.as_view(), name="admin-topup-reject"),
    path("admin/topup-settings/", AdminTopUpSettingsView.as_view(), name="admin-topup-settings"),
]
