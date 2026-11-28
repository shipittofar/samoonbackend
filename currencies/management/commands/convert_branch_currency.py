"""Move branches from one menu currency to another (e.g. old USD branches to toman).

    manage.py convert_branch_currency --from USD --to IRT                  # report only
    manage.py convert_branch_currency --from USD --to IRT --rate 98000 --apply

Without --apply nothing is written: it lists what would change. Per branch, in
one transaction:
  * item price, extra price, per-item extra price and minimum order amount are
    converted (rounded like prices in the target currency);
  * an explicit price the owner already typed in the target currency becomes
    the new main price instead of a converted one;
  * the old price is kept as an explicit price in the old currency, so a
    guest choosing that currency still sees exactly the old amount;
  * the branch currency is switched.
Past orders keep their own snapshot and are not touched. A branch whose new
amounts would not fit the price columns is skipped, with the items named.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.cache.key import CacheKeys
from currencies import services as currencies
from menu.models import Extra, MenuItem, MenuItemExtra
from tenants.models import Branch

# MenuItem.price / Extra.price / MenuItemExtra.price_override / minimum_order_amount:
# max_digits=10, decimal_places=2.
LARGEST = Decimal("99999999.99")


class Skip(Exception):
    pass


class Command(BaseCommand):
    help = "Convert branches' menu prices from one currency to another (report only unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", default="USD", help="Current branch currency (default USD).")
        parser.add_argument("--to", dest="target", default="", help="New currency (default: the platform base, IRT).")
        parser.add_argument(
            "--rate", default="",
            help="Units of --to per one unit of --from (e.g. 98000 toman per dollar). "
                 "Default: from the currency table set in the platform panel.",
        )
        parser.add_argument("--branch", action="append", default=[], help="Only this branch id (repeatable).")
        parser.add_argument("--apply", action="store_true", help="Write the changes. Without it nothing is written.")

    def handle(self, *args, **options):
        source = options["source"].upper()
        target = (options["target"] or currencies.base_code()).upper()
        table = currencies.table(use_cache=False)
        if source == target:
            raise CommandError("--from and --to are the same currency.")
        for code in (source, target):
            if code not in table:
                raise CommandError(f"Unknown currency: {code} (add it in the platform panel first).")
        rate = self._rate(options["rate"], table[source], table[target])
        info = table[target]

        branches = Branch.objects.filter(currency=source).select_related("tenant").order_by("tenant__name", "name")
        if options["branch"]:
            branches = branches.filter(id__in=options["branch"])
        branches = list(branches)
        mode = "APPLYING" if options["apply"] else "REPORT ONLY (add --apply to write)"
        self.stdout.write(f"{mode}: {len(branches)} branch(es) in {source} -> {target}, 1 {source} = {rate} {target}")

        done = skipped = 0
        for branch in branches:
            try:
                with transaction.atomic():
                    summary = self._convert(branch, source, target, rate, info, write=options["apply"])
                    if not options["apply"]:
                        transaction.set_rollback(True)
            except Skip as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"- SKIPPED {branch}: {exc}"))
                continue
            done += 1
            self.stdout.write(f"- {branch}: {summary}")
            if options["apply"]:
                transaction.on_commit(lambda b=branch: self._forget_cache(b))
        verb = "converted" if options["apply"] else "would be converted"
        self.stdout.write(self.style.SUCCESS(f"{done} branch(es) {verb}, {skipped} skipped."))

    @staticmethod
    def _rate(raw: str, src, dst) -> Decimal:
        if raw:
            try:
                rate = Decimal(raw)
            except InvalidOperation:
                raise CommandError("--rate must be a number.")
        else:
            if not src.rate or not dst.rate:
                raise CommandError(f"No exchange rate for {src.code} or {dst.code}: set it in the platform panel or pass --rate.")
            rate = src.rate / dst.rate
        if rate <= 0:
            raise CommandError("--rate must be positive.")
        return rate

    @staticmethod
    def _amount(value, rate, info, label, too_big) -> Decimal:
        new = currencies.round_to(Decimal(value) * rate, info)
        if new > LARGEST:
            too_big.append(label)
        return new

    def _convert(self, branch, source, target, rate, info, *, write: bool) -> str:
        branch = Branch.objects.select_for_update().get(pk=branch.pk)
        too_big: list[str] = []
        items = list(MenuItem.objects.filter(branch=branch).select_for_update())
        samples = []
        for item in items:
            explicit = dict(item.prices or {})
            old = item.price
            own = explicit.pop(target, None)
            try:
                new = Decimal(str(own)) if own not in (None, "") else None
            except InvalidOperation:
                new = None
            if new is None:
                new = self._amount(old, rate, info, item.name, too_big)
            elif new > LARGEST:
                too_big.append(item.name)
            explicit.setdefault(source, str(old))
            item.price, item.prices = new, explicit
            if len(samples) < 3:
                samples.append(f"{item.name} {old} {source} -> {new} {target}")

        extras = list(Extra.objects.filter(branch=branch).select_for_update())
        for extra in extras:
            extra.price = self._amount(extra.price, rate, info, f"extra {extra.name}", too_big)
        overrides = list(
            MenuItemExtra.objects.filter(item__branch=branch, price_override__isnull=False).select_for_update()
        )
        for link in overrides:
            link.price_override = self._amount(link.price_override, rate, info, f"extra price on {link.item_id}", too_big)
        if branch.minimum_order_amount is not None:
            branch.minimum_order_amount = self._amount(branch.minimum_order_amount, rate, info, "minimum order", too_big)

        if too_big:
            names = ", ".join(too_big[:10]) + (" …" if len(too_big) > 10 else "")
            raise Skip(f"{len(too_big)} amount(s) would exceed {LARGEST} {target}: {names}")

        if write:
            MenuItem.objects.bulk_update(items, ["price", "prices"])
            Extra.objects.bulk_update(extras, ["price"])
            MenuItemExtra.objects.bulk_update(overrides, ["price_override"])
            branch.currency = target
            branch.save(update_fields=["currency", "minimum_order_amount", "updated_at"])
        return (
            f"{len(items)} item(s), {len(extras)} extra(s), {len(overrides)} extra override(s)"
            + (f"; e.g. {'; '.join(samples)}" if samples else "")
        )

    @staticmethod
    def _forget_cache(branch) -> None:
        """Menu and branch data are cached per branch; drop them so they reload."""
        b, t = branch.id, branch.tenant_id
        keys = [
            CacheKeys.MENU_CATEGORY_LIST.format(branch_id=b),
            CacheKeys.MENU_ITEM_LIST_FOR_CONSOLE.format(branch_id=b),
            CacheKeys.EXTRA_LIST.format(branch_id=b),
            CacheKeys.EXTRA_GROUP_LIST.format(branch_id=b),
            CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=b),
            CacheKeys.MENU_BRANCH_CATEGORIES_WITH_ITEMS.format(branch_id=b),
            CacheKeys.BRANCH_DETAIL.format(tenant_id=t, branch_id=b),
            CacheKeys.BRANCH_LIST.format(tenant_id=t),
            CacheKeys.BRANCH_DETAIL_GLOBAL.format(branch_id=b),
            CacheKeys.BRANCH_LIST_ALL,
            CacheKeys.DISCOVER_LIST,
            CacheKeys.TENANT_DETAIL.format(tenant_id=t),
        ]
        for item in MenuItem.objects.filter(branch_id=b).values("id", "category_id"):
            keys += [
                CacheKeys.MENU_ITEM_LIST.format(branch_id=b, category_id=item["category_id"]),
                CacheKeys.MENU_ITEM_DETAIL.format(branch_id=b, category_id=item["category_id"], item_id=item["id"]),
                CacheKeys.MENU_ITEM_EXTRA_LIST.format(item_id=item["id"]),
            ]
        for extra_id in Extra.objects.filter(branch_id=b).values_list("id", flat=True):
            keys.append(CacheKeys.EXTRA_DETAIL.format(branch_id=b, extra_id=extra_id))
        try:
            cache.delete_many(list(set(keys)))
        except Exception:  # a cache outage must not undo the conversion
            pass
