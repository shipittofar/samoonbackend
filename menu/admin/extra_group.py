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

        for obj in formset.deleted_objects:
            obj.delete()

    list_display = (
        "name", "branch", "selection_type", "required",
        "min_selection", "max_selection", "order", "is_active",
    )
    list_filter = ("branch", "selection_type", "required", "is_active")
    search_fields = ("name",)
    ordering = ("order",)
    inlines = [ExtraInline]

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
