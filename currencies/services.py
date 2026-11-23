"""Currency conversion — the single implementation the API and orders use.

The frontend mirrors these rules (src/lib/currency) for display; orders are
priced here, so the snapshot stored on an order is authoritative.

Rules
- An owner's explicit price for a currency (MenuItem.prices) always wins.
- Otherwise: amount_in_target = amount * rate(source) / rate(target), rounded
  half-up to the target's rounding step (and its decimals).
- Same currency: unchanged. No usable rate on either side: not convertible.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.cache import cache

from currencies.models import Currency

CACHE_KEY = "currencies:table:v1"
CACHE_SECONDS = 60
DEFAULT_BASE = "IRT"


@dataclass(frozen=True)
class CurrencyInfo:
    code: str
    name: str
    symbol: str
    decimals: int
    rounding_step: Decimal
    rate: Decimal | None
    is_base: bool
    enabled: bool


def table(*, use_cache: bool = True) -> dict[str, CurrencyInfo]:
    """All currencies by code (enabled or not)."""
    if use_cache:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return cached
    data = {
        c.code: CurrencyInfo(
            code=c.code,
            name=c.name,
            symbol=c.symbol,
            decimals=c.decimals,
            rounding_step=c.rounding_step,
            rate=Decimal(1) if c.is_base else c.rate,
            is_base=c.is_base,
            enabled=c.enabled or c.is_base,
        )
        for c in Currency.objects.all()
    }
    cache.set(CACHE_KEY, data, CACHE_SECONDS)
    return data


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def base_code() -> str:
    for info in table().values():
        if info.is_base:
            return info.code
    return DEFAULT_BASE


def is_known(code: str | None) -> bool:
    return bool(code) and code in table()


def round_to(amount: Decimal, info: CurrencyInfo, *, use_step: bool = True) -> Decimal:
    """Half-up to the rounding step (prices) or just to the decimals
    (tax, fees, discounts — small amounts must not round to zero)."""
    step = info.rounding_step if use_step and info.rounding_step and info.rounding_step > 0 else Decimal(1).scaleb(-info.decimals)
    rounded = (amount / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    return rounded.quantize(Decimal(1).scaleb(-info.decimals), rounding=ROUND_HALF_UP)


def convert(amount, source: str, target: str, *, use_step: bool = True) -> Decimal | None:
    """``amount`` in ``source`` expressed in ``target``, or None if impossible.
    ``use_step=False`` for adjustments (tax, fees): round to decimals only."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError):
        return None
    if source == target:
        return value
    currencies = table()
    src, dst = currencies.get(source), currencies.get(target)
    if src is None or dst is None or not src.rate or not dst.rate:
        return None
    return round_to(value * src.rate / dst.rate, dst, use_step=use_step)


def price_in(*, base_price, source: str, explicit: dict | None, target: str) -> Decimal | None:
    """An item's price in ``target``: the owner's explicit price, else converted."""
    if explicit and target in explicit and explicit[target] not in (None, ""):
        try:
            return Decimal(str(explicit[target]))
        except (InvalidOperation, TypeError):
            pass
    return convert(base_price, source, target)


def clean_explicit_prices(raw, *, source: str) -> dict[str, str]:
    """Validate an owner's per-currency prices: known codes, not the item's
    own currency, non-negative amounts with that currency's decimals."""
    from rest_framework.exceptions import ValidationError

    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValidationError({"prices": "Expected an object of currency code -> price."})
    currencies = table()
    out: dict[str, str] = {}
    for code, value in raw.items():
        code = str(code).upper()
        info = currencies.get(code)
        if info is None:
            raise ValidationError({"prices": f"Unknown currency: {code}"})
        if code == source:
            continue  # that is the item's main price
        if value in (None, ""):
            continue
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValidationError({"prices": f"{code}: not a number."})
        if amount < 0 or amount > Decimal("1e12"):
            raise ValidationError({"prices": f"{code}: out of range."})
        out[code] = str(amount.quantize(Decimal(1).scaleb(-info.decimals), rounding=ROUND_HALF_UP))
    return out


def snapshot_order(order, display_currency: str | None) -> None:
    """Record on ``order`` the currency it is priced in and, when the customer
    viewed prices in another enabled currency, that currency, the rates used
    and the total they saw. The amounts charged are unchanged (business
    currency). Item prices use the owner's explicit prices where set, exactly
    like the menu showed them; extras and adjustments are converted."""
    source = (getattr(order.branch, "currency", "") or base_code()).upper()
    fields = {"currency": source, "display_currency": "", "display_total": None, "exchange_rates": {}}
    target = (display_currency or "").upper()
    info = table().get(target)
    if target and target != source and info is not None and info.enabled:
        total = Decimal("0")
        ok = True
        for item in order.items.select_related("menu_item"):
            menu_item = item.menu_item
            unit = price_in(
                base_price=item.unit_price,
                source=source,
                explicit=getattr(menu_item, "prices", None) if menu_item else None,
                target=target,
            )
            extras = item.total_price - item.unit_price * item.quantity
            extras_converted = convert(extras, source, target, use_step=False) if extras else Decimal("0")
            if unit is None or extras_converted is None:
                ok = False
                break
            total += unit * item.quantity + extras_converted
        adjustments = order.total - order.subtotal
        adjustments_converted = convert(adjustments, source, target, use_step=False) if adjustments else Decimal("0")
        if ok and adjustments_converted is not None:
            src_rate = table()[source].rate if source in table() else None
            fields.update(
                display_currency=target,
                display_total=round_to(total + adjustments_converted, info, use_step=False),
                exchange_rates={source: str(src_rate), target: str(info.rate)},
            )
    for name, value in fields.items():
        setattr(order, name, value)
    order.save(update_fields=list(fields))
