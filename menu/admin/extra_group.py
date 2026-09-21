from django.contrib import admin

from menu.models import ExtraGroup, Extra


class ExtraInline(admin.TabularInline):
    model = Extra
    fk_name = "group"
    extra = 1
    fields = ("name", "price", "available", "order")


@admin.register(ExtraGroup)
class ExtraGroupAdmin(admin.ModelAdmin):
    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for obj in instances:
            if isinstance(obj, Extra):
                obj.branch = form.instance.branch
            obj.save()

        formset.save_m2m()

        from core.exceptions.item import ExtraReferencedByOrdersException
        from menu.selectors.item_dal import ExtraDataAccessLayer

        for obj in formset.deleted_objects:
            if isinstance(obj, Extra):
                try:
                    ExtraDataAccessLayer.delete_extra(obj)
                except ExtraReferencedByOrdersException:
                    pass
            else:
                obj.delete()

    list_display = (
        "name", "branch", "selection_type", "required",
        "min_selection", "max_selection", "order", "is_active",
    )
    list_filter = ("branch", "selection_type", "required", "is_active")
    search_fields = ("name",)
    ordering = ("order",)
    inlines = [ExtraInline]
    actions = ["remove_or_deactivate_extra_groups"]

    fieldsets = (
        (None, {
            "fields": ("branch", "name", "description")
        }),
        ("Selection rules", {
            "fields": (
                "selection_type", "required",
                "min_selection", "max_selection",
            )
        }),
        ("Display", {
            "fields": ("order", "is_active")
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        from menu.services.extra_group_bll import ExtraGroupBusinessLogicLayer

        ExtraGroupBusinessLogicLayer.delete_extra_group(obj.id, obj.branch_id)

    def delete_queryset(self, request, queryset):
        from menu.services.extra_group_bll import ExtraGroupBusinessLogicLayer

        for obj in queryset:
            ExtraGroupBusinessLogicLayer.delete_extra_group(obj.id, obj.branch_id)

    @admin.action(description="Remove or deactivate selected extra groups")
    def remove_or_deactivate_extra_groups(self, request, queryset):
        self.delete_queryset(request, queryset)
