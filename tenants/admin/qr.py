from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from core.exceptions.qr import (
    QrAlreadyExistsException,
    QrInvalidDestinationException,
    QrNotFoundException,
    UnauthorizedQrAccessException,
)
from tenants.models import QrCode
from tenants.services.qr_bll import QrCodeBusinessLogicLayer


@admin.register(QrCode)
class QrCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "entity_type",
        "entity_id",
        "destination_type",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("entity_type", "destination_type", "is_active")
    search_fields = ("code",)
    readonly_fields = (
        "id",
        "code",
        "entity_type",
        "entity_id",
        "is_active",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    actions = ("enable_qr_codes", "disable_qr_codes", "regenerate_qr_codes")
    fieldsets = (
        (None, {
            "fields": (
                "code",
                "entity_type",
                "entity_id",
                "destination_type",
                "is_active",
            ),
            "description": _(
                "Regenerate issues a new printed code (old /qr/<code>/ returns 410). "
                "Changing destination keeps the same printed code. "
                "Enable/Disable via actions. Tenant QR destinations stay tenant. "
                "Menu QR destinations stay menu. Reservation-page QR destinations stay reservation. "
                "entity_type menu/reservation rows are owned by a Branch UUID "
                "(storefront resource, not a booking record)."
            ),
        }),
        (_("Timestamps"), {"fields": ("id", "created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            return
        if "destination_type" in getattr(form, "changed_data", []):
            QrCodeBusinessLogicLayer.set_destination(
                request.user, obj, obj.destination_type
            )
            obj.refresh_from_db()
            return
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Enable selected QR codes"))
    def enable_qr_codes(self, request, queryset):
        self._run_service_action(
            request, queryset, QrCodeBusinessLogicLayer.enable, _("Enabled %(count)d QR code(s).")
        )

    @admin.action(description=_("Disable selected QR codes (printed codes stop resolving)"))
    def disable_qr_codes(self, request, queryset):
        self._run_service_action(
            request, queryset, QrCodeBusinessLogicLayer.disable, _("Disabled %(count)d QR code(s).")
        )

    @admin.action(
        description=_(
            "Regenerate selected QR codes (issues new codes; old printed QRs become invalid)"
        )
    )
    def regenerate_qr_codes(self, request, queryset):
        self._run_service_action(
            request,
            queryset,
            QrCodeBusinessLogicLayer.regenerate,
            _("Regenerated %(count)d QR code(s)."),
        )

    def _run_service_action(self, request, queryset, operation, success_message):
        ok = 0
        for qr in queryset:
            try:
                operation(request.user, qr)
                ok += 1
            except (
                QrAlreadyExistsException,
                QrInvalidDestinationException,
                QrNotFoundException,
                UnauthorizedQrAccessException,
            ) as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
        if ok:
            self.message_user(
                request,
                success_message % {"count": ok},
                level=messages.SUCCESS,
            )
