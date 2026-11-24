"""/api/settlement/

Business (the owner, or a platform superuser):
  GET  tenants/<id>/overview/              terms, balances, payout accounts, open payouts
  GET  tenants/<id>/statement/             ledger lines (?currency=&from=&to=&page=)
  GET  tenants/<id>/statement.csv          same, as CSV
  GET  tenants/<id>/orders/                commission per finished order (?status=)
  POST tenants/<id>/accounts/              {kind: iban|crypto, iban, holderName, bankName | asset, address, memo, label}
  POST tenants/<id>/accounts/<aid>/disable/ | default/
  GET/POST tenants/<id>/payouts/           list / request {accountId, amount}
  POST tenants/<id>/payouts/<pid>/cancel/

Platform superusers:
  GET/PUT admin/settings/                  default commission, hold days, minimum payouts, weekly auto payout
  GET  admin/overview/                     totals per currency, open payouts, accounts to review
  GET  admin/tenants/?search=              businesses with their terms and balances
  GET/PUT admin/tenants/<id>/terms/        {commissionPercent, holdDays, note}; empty = platform default
  GET  admin/payouts/?status=&search=
  POST admin/payouts/<pid>/paid/ {reference, note} | reject/ {reason}
  GET  admin/accounts/?status=
  POST admin/accounts/<aid>/approve/ | reject/ {note}
"""
from __future__ import annotations

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from settlement import services
from settlement.models import Payout, PayoutAccount, PayoutAccountStatus
from superadmin.api.permissions import IsPlatformSuperuser
from tenants.models import Tenant


def _page(qs, params, size=25):
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    return qs[(page - 1) * size: page * size], {"count": qs.count(), "page": page, "pageSize": size}


class TenantView(APIView):
    permission_classes = [IsAuthenticated]

    def tenant(self, request, tenant_id) -> Tenant:
        tenant = get_object_or_404(Tenant.objects.select_related("owner"), id=tenant_id)
        services.check_access(request.user, tenant)
        return tenant


class OverviewView(TenantView):
    def get(self, request, tenant_id):
        tenant = self.tenant(request, tenant_id)
        services.release_due(tenant=tenant)
        accounts = PayoutAccount.objects.filter(tenant=tenant).exclude(status=PayoutAccountStatus.DISABLED)
        return Response({
            "terms": services.terms_for(tenant),
            "balances": services.balances(tenant),
            "accounts": [services.serialize_account(a) for a in accounts],
            "openPayouts": [
                services.serialize_payout(p) for p in Payout.objects.filter(tenant=tenant, status="requested").select_related("account")
            ],
            "minPayout": services.get_settings()["min_payout"],
        })


class StatementView(TenantView):
    def get(self, request, tenant_id):
        return Response(services.statement(self.tenant(request, tenant_id), request.query_params))


class StatementCsvView(TenantView):
    def get(self, request, tenant_id):
        tenant = self.tenant(request, tenant_id)
        response = HttpResponse(services.statement_csv(tenant, request.query_params), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="statement.csv"'
        return response


class OrdersView(TenantView):
    def get(self, request, tenant_id):
        return Response(services.order_settlements(self.tenant(request, tenant_id), request.query_params))


class AccountsView(TenantView):
    def post(self, request, tenant_id):
        tenant = self.tenant(request, tenant_id)
        account = services.add_account(tenant, data=request.data, actor=request.user)
        return Response(services.serialize_account(account), status=201)


class AccountDisableView(TenantView):
    def post(self, request, tenant_id, account_id):
        tenant = self.tenant(request, tenant_id)
        return Response(services.serialize_account(services.disable_account(tenant, account_id, actor=request.user)))


class AccountDefaultView(TenantView):
    def post(self, request, tenant_id, account_id):
        tenant = self.tenant(request, tenant_id)
        return Response(services.serialize_account(services.make_default(tenant, account_id)))


class PayoutsView(TenantView):
    def get(self, request, tenant_id):
        tenant = self.tenant(request, tenant_id)
        rows, meta = _page(Payout.objects.filter(tenant=tenant).select_related("account"), request.query_params)
        return Response({"results": [services.serialize_payout(p) for p in rows], **meta})

    def post(self, request, tenant_id):
        tenant = self.tenant(request, tenant_id)
        payout = services.request_payout(
            tenant, account_id=request.data.get("accountId"), amount=request.data.get("amount"), actor=request.user
        )
        return Response(services.serialize_payout(payout), status=201)


class PayoutCancelView(TenantView):
    def post(self, request, tenant_id, payout_id):
        tenant = self.tenant(request, tenant_id)
        return Response(services.serialize_payout(services.cancel_payout(tenant, payout_id, actor=request.user)))


# ── Platform ─────────────────────────────────────────────────────────────────


class AdminSettingsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(services.get_settings())

    def put(self, request):
        return Response(services.save_settings(request.data if isinstance(request.data, dict) else {}, actor=request.user))


class AdminOverviewView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        services.release_due()
        return Response(services.platform_overview())


class AdminTenantsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        qs = Tenant.objects.order_by("name")
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        rows, meta = _page(qs, request.query_params, size=20)
        return Response({
            "results": [
                {"id": str(t.id), "name": t.name, "terms": services.terms_for(t), "balances": services.balances(t)}
                for t in rows
            ],
            **meta,
        })


class AdminTermsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request, tenant_id):
        return Response(services.terms_for(get_object_or_404(Tenant, id=tenant_id)))

    def put(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, id=tenant_id)
        return Response(services.set_terms(tenant, data=request.data, actor=request.user))


class AdminPayoutsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        qs = Payout.objects.select_related("tenant", "account")
        status = request.query_params.get("status") or ""
        if status:
            qs = qs.filter(status=status)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(tenant__name__icontains=search) | Q(reference__icontains=search))
        rows, meta = _page(qs, request.query_params)
        return Response({"results": [services.serialize_payout(p, admin=True) for p in rows], **meta})


class AdminPayoutPaidView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, payout_id):
        get_object_or_404(Payout, id=payout_id)
        payout = services.mark_paid(
            payout_id, actor=request.user, reference=str(request.data.get("reference") or ""), note=str(request.data.get("note") or "")
        )
        return Response(services.serialize_payout(payout, admin=True))


class AdminPayoutRejectView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def post(self, request, payout_id):
        get_object_or_404(Payout, id=payout_id)
        payout = services.reject_payout(payout_id, actor=request.user, reason=str(request.data.get("reason") or ""))
        return Response(services.serialize_payout(payout, admin=True))


class AdminAccountsView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        qs = PayoutAccount.objects.select_related("tenant")
        status = request.query_params.get("status") or ""
        if status:
            qs = qs.filter(status=status)
        rows, meta = _page(qs, request.query_params)
        return Response({
            "results": [{**services.serialize_account(a), "tenantName": a.tenant.name} for a in rows],
            **meta,
        })


class AdminAccountReviewView(APIView):
    permission_classes = [IsPlatformSuperuser]
    approve = True

    def post(self, request, account_id):
        get_object_or_404(PayoutAccount, id=account_id)
        account = services.review_account(
            account_id, approve=self.approve, actor=request.user, note=str(request.data.get("note") or "")
        )
        return Response(services.serialize_account(account))


app_name = "settlement"

urlpatterns = [
    path("tenants/<uuid:tenant_id>/overview/", OverviewView.as_view(), name="overview"),
    path("tenants/<uuid:tenant_id>/statement/", StatementView.as_view(), name="statement"),
    path("tenants/<uuid:tenant_id>/statement.csv", StatementCsvView.as_view(), name="statement-csv"),
    path("tenants/<uuid:tenant_id>/orders/", OrdersView.as_view(), name="orders"),
    path("tenants/<uuid:tenant_id>/accounts/", AccountsView.as_view(), name="accounts"),
    path("tenants/<uuid:tenant_id>/accounts/<uuid:account_id>/disable/", AccountDisableView.as_view(), name="account-disable"),
    path("tenants/<uuid:tenant_id>/accounts/<uuid:account_id>/default/", AccountDefaultView.as_view(), name="account-default"),
    path("tenants/<uuid:tenant_id>/payouts/", PayoutsView.as_view(), name="payouts"),
    path("tenants/<uuid:tenant_id>/payouts/<uuid:payout_id>/cancel/", PayoutCancelView.as_view(), name="payout-cancel"),
    path("admin/settings/", AdminSettingsView.as_view(), name="admin-settings"),
    path("admin/overview/", AdminOverviewView.as_view(), name="admin-overview"),
    path("admin/tenants/", AdminTenantsView.as_view(), name="admin-tenants"),
    path("admin/tenants/<uuid:tenant_id>/terms/", AdminTermsView.as_view(), name="admin-terms"),
    path("admin/payouts/", AdminPayoutsView.as_view(), name="admin-payouts"),
    path("admin/payouts/<uuid:payout_id>/paid/", AdminPayoutPaidView.as_view(), name="admin-payout-paid"),
    path("admin/payouts/<uuid:payout_id>/reject/", AdminPayoutRejectView.as_view(), name="admin-payout-reject"),
    path("admin/accounts/", AdminAccountsView.as_view(), name="admin-accounts"),
    path("admin/accounts/<uuid:account_id>/approve/", AdminAccountReviewView.as_view(approve=True), name="admin-account-approve"),
    path("admin/accounts/<uuid:account_id>/reject/", AdminAccountReviewView.as_view(approve=False), name="admin-account-reject"),
]
