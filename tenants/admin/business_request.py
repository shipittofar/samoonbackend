from django.contrib import admin, messages
from rest_framework.exceptions import ValidationError

from tenants.models import BusinessRequest, BusinessRequestStatus
from tenants.services import business_request_bll


@admin.register(BusinessRequest)
class BusinessRequestAdmin(admin.ModelAdmin):
    list_display = ["name", "business_type", "city", "user", "status", "created_at", "decided_by"]
    list_filter = ["status", "business_type"]
    search_fields = ["name", "city", "user__phone_number", "user__email"]
    readonly_fields = [
        "id", "user", "status", "name", "business_type", "description", "phone", "city",
        "address", "latitude", "longitude", "service_radius_km", "rejection_reason",
        "decided_by", "decided_at", "tenant", "created_at", "updated_at",
    ]
    actions = ["approve_selected", "reject_selected"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _decide(self, request, queryset, decide, verb):
        done = 0
        for item in queryset.filter(status=BusinessRequestStatus.PENDING):
            try:
                decide(request_id=item.pk, actor=request.user)
                done += 1
            except (ValidationError, Exception) as exc:  # show the reason, keep going
                detail = getattr(exc, "detail", exc)
                self.message_user(request, f"{item.name}: {detail}", messages.ERROR)
        if done:
            self.message_user(request, f"{verb} {done} request(s).", messages.SUCCESS)

    @admin.action(description="Approve selected requests (create the business)")
    def approve_selected(self, request, queryset):
        self._decide(request, queryset, business_request_bll.approve, "Approved")

    @admin.action(description="Reject selected requests")
    def reject_selected(self, request, queryset):
        self._decide(request, queryset, business_request_bll.reject, "Rejected")
