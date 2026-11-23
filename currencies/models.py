from django.conf import settings
from django.db import models


class Currency(models.Model):
    """A currency prices can be shown in.

    ``rate`` is how many units of the platform base currency one unit of this
    currency is worth (base currency: rate 1). It is entered by platform
    superusers (free-market rates differ from official ones), and every change
    is kept in CurrencyRateChange. A currency without a rate can still be used
    for prices an owner typed in explicitly, but nothing converts into it.

    Codes are ISO 4217, plus ``IRT`` for the Iranian toman (1 IRT = 10 IRR),
    which is how prices are quoted in Iran.
    """

    code = models.CharField(max_length=5, primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=10, blank=True)
    decimals = models.PositiveSmallIntegerField(default=2)
    # Converted prices are rounded to a multiple of this (e.g. 1000 toman, 0.10 USD).
    rounding_step = models.DecimalField(max_digits=18, decimal_places=8, default=1)
    rate = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    is_base = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=100)
    rate_updated_at = models.DateTimeField(null=True, blank=True)
    rate_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name_plural = "currencies"
        constraints = [
            models.UniqueConstraint(fields=["is_base"], condition=models.Q(is_base=True), name="single_base_currency"),
        ]

    def __str__(self) -> str:
        return self.code


class CurrencyRateChange(models.Model):
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name="rate_changes")
    previous_rate = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    new_rate = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:
        return f"{self.currency_id}: {self.previous_rate} -> {self.new_rate}"
