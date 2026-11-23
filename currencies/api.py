"""/api/currencies/

GET  (public)            enabled currencies with rates — what the site shows.
     ?all=1 (superusers) every currency, enabled or not.
POST (superusers)        add a currency.
PATCH <code>/ (superusers) rate, enabled, rounding, decimals, name, symbol,
                          sort order. Rate changes are logged with a reason.
GET  history/ (superusers) rate change log (?code=USD).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.authorization.platform import is_platform_superuser
from currencies import services
from currencies.models import Currency, CurrencyRateChange
from superadmin.api.permissions import IsPlatformSuperuser


def _dec(value) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f") if isinstance(value, Decimal) else str(value)


def serialize(c: Currency) -> dict:
    return {
        "code": c.code,
        "name": c.name,
        "symbol": c.symbol,
        "decimals": c.decimals,
        "roundingStep": _dec(c.rounding_step),
        "rate": "1" if c.is_base else _dec(c.rate),
        "isBase": c.is_base,
        "enabled": c.enabled or c.is_base,
        "sortOrder": c.sort_order,
        "rateUpdatedAt": c.rate_updated_at.isoformat() if c.rate_updated_at else None,
    }


def _positive_decimal(value, field: str, *, allow_null=False) -> Decimal | None:
    if value in (None, "") and allow_null:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError({field: "Not a number."})
    if amount <= 0:
        raise ValidationError({field: "Must be greater than zero."})
    return amount


def _apply(currency: Currency, data: dict, user) -> None:
    if "name" in data:
        currency.name = str(data["name"]).strip()[:60] or currency.name
    if "symbol" in data:
        currency.symbol = str(data["symbol"]).strip()[:10]
    if "decimals" in data:
        try:
            decimals = int(data["decimals"])
        except (TypeError, ValueError):
            raise ValidationError({"decimals": "Must be 0-4."})
        if not 0 <= decimals <= 4:
            raise ValidationError({"decimals": "Must be 0-4."})
        currency.decimals = decimals
    if "roundingStep" in data:
        currency.rounding_step = _positive_decimal(data["roundingStep"], "roundingStep")
    if "sortOrder" in data:
        try:
            currency.sort_order = max(0, int(data["sortOrder"]))
        except (TypeError, ValueError):
            raise ValidationError({"sortOrder": "Must be a number."})
    if "rate" in data and not currency.is_base:
        new_rate = _positive_decimal(data["rate"], "rate", allow_null=True)
        if new_rate != currency.rate:
            CurrencyRateChange.objects.create(
                currency=currency,
                previous_rate=currency.rate,
                new_rate=new_rate,
                reason=str(data.get("reason") or "")[:300],
                changed_by=user,
            )
            currency.rate = new_rate
            currency.rate_updated_at = timezone.now()
            currency.rate_updated_by = user
    if "enabled" in data and not currency.is_base:
        enabled = bool(data["enabled"])
        if enabled and not currency.rate:
            raise ValidationError({"enabled": "Set an exchange rate before enabling this currency."})
        currency.enabled = enabled


class CurrencyListView(APIView):
    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsPlatformSuperuser()]

    def get(self, request):
        qs = Currency.objects.all()
        show_all = request.query_params.get("all") and is_platform_superuser(request.user)
        rows = [serialize(c) for c in qs if show_all or c.enabled or c.is_base]
        return Response({"base": services.base_code(), "currencies": rows})

    def post(self, request):
        code = str(request.data.get("code") or "").strip().upper()
        if not (3 <= len(code) <= 5 and code.isalpha()):
            raise ValidationError({"code": "3-5 letters, e.g. USD."})
        if Currency.objects.filter(code=code).exists():
            raise ValidationError({"code": "Already exists."})
        with transaction.atomic():
            currency = Currency(code=code, name=str(request.data.get("name") or code)[:60])
            _apply(currency, request.data, request.user)
            currency.save()
        services.invalidate()
        return Response(serialize(currency), status=status.HTTP_201_CREATED)


class CurrencyDetailView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def patch(self, request, code):
        with transaction.atomic():
            currency = get_object_or_404(Currency.objects.select_for_update(), code=code.upper())
            _apply(currency, request.data, request.user)
            currency.save()
        services.invalidate()
        return Response(serialize(currency))


class CurrencyHistoryView(APIView):
    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        qs = CurrencyRateChange.objects.select_related("changed_by")
        code = (request.query_params.get("code") or "").upper()
        if code:
            qs = qs.filter(currency_id=code)
        out = []
        for ch in qs[:200]:
            who = ch.changed_by
            out.append({
                "code": ch.currency_id,
                "previousRate": _dec(ch.previous_rate),
                "newRate": _dec(ch.new_rate),
                "reason": ch.reason,
                "changedBy": (" ".join(p for p in (who.first_name, who.last_name) if p) or who.phone_number) if who else "",
                "changedAt": ch.changed_at.isoformat(),
            })
        return Response({"results": out})


app_name = "currencies"

urlpatterns = [
    path("", CurrencyListView.as_view(), name="list"),
    path("history/", CurrencyHistoryView.as_view(), name="history"),
    path("<str:code>/", CurrencyDetailView.as_view(), name="detail"),
]
