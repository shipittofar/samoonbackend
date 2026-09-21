from django.contrib import admin
from django.utils.html import format_html

from menu.models import MenuItemExtra, Extra, MenuItem, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "branch",
        "slug",
        "is_active",
        "display_order",
        "item_count",
    )
    list_filter = ("branch", "is_active")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("branch", "display_order", "name")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields["branch"].disabled = True
        return form

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = "Items using this tag"

    def delete_model(self, request, obj):
        from menu.services.tag_bll import TagBusinessLogicLayer

        TagBusinessLogicLayer.delete_tag(obj.id, obj.branch_id)

    def delete_queryset(self, request, queryset):
        from menu.services.tag_bll import TagBusinessLogicLayer

        for obj in queryset:
            TagBusinessLogicLayer.delete_tag(obj.id, obj.branch_id)


class MenuItemExtraInline(admin.TabularInline):
    """
    Lets the owner attach existing Extras (from the same tenant) to this
    item directly from the MenuItem edit page, with an optional
    price override.
    """
    model = MenuItemExtra
    fk_name = "item"
    extra = 1
    autocomplete_fields = ("extra",)
    fields = ("extra", "price_override")

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj is not None:
            formset.form.base_fields["extra"].queryset = Extra.objects.filter(
                branch=obj.branch
            )
        return formset


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        "name", "branch", "category", "price", "discount",
        "is_active", "available", "is_popular", "is_featured", "image_preview",
    )
    list_filter = ("branch", "category", "is_active", "available", "is_popular", "is_featured", "tags")
    search_fields = ("name", "slug", "description")
    autocomplete_fields = ("tags",)
    readonly_fields = ("slug", "created_at", "updated_at", "image_preview")
    inlines = [MenuItemExtraInline]
    actions = ["remove_from_catalog"]

    def get_queryset(self, request):
        return MenuItem.all_objects.all()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Remove selected items from catalog")
    def remove_from_catalog(self, request, queryset):
        from menu.services.item_bll import ItemBusinessLogicLayer

        for item in queryset:
            ItemBusinessLogicLayer.delete_menu_item(
                item.id, item.category_id, item.branch_id
            )

    fieldsets = (
        (None, {
            "fields": ("branch", "category", "name", "slug", "description")
        }),
        ("Pricing", {
            "fields": ("price", "discount")
        }),
        ("Details", {
            "fields": ("calories", "preparation_time", "tags")
        }),
        ("Image", {
            "fields": ("image", "image_preview")
        }),
        ("Status", {
            "fields": ("is_active", "available", "is_popular", "is_featured")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields["tags"].queryset = Tag.objects.filter(branch=obj.branch)
        return form

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 80px; border-radius: 4px;" />',
                obj.image.url,
            )
        return "-"
    image_preview.short_description = "Preview"


class ExtraLinkInline(admin.TabularInline):
    """
    Shows which items this Extra is currently attached to, from the
    Extra's own edit page.
    """
    model = MenuItemExtra
    fk_name = "extra"
    extra = 0
    autocomplete_fields = ("item",)
    fields = ("item", "price_override")
    verbose_name = "Linked item"
    verbose_name_plural = "Linked items"


@admin.register(Extra)
class ExtraAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "price", "available", "linked_item_count")
    list_filter = ("branch", "available")
    search_fields = ("name",)
    inlines = [ExtraLinkInline]

    def linked_item_count(self, obj):
        return obj.item_links.count()
    linked_item_count.short_description = "Linked items"

    def delete_model(self, request, obj):
        from core.exceptions.item import ExtraReferencedByOrdersException
        from menu.services.item_bll import ExtraBusinessLogicLayer

        try:
            ExtraBusinessLogicLayer.delete_extra(obj.id, obj.branch_id)
        except ExtraReferencedByOrdersException:
            self.message_user(
                request,
                "This extra is used on historical orders and was marked unavailable.",
                level="warning",
            )

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)
