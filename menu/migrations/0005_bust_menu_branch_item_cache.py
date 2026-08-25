from django.db import migrations


def bust_menu_branch_item_caches(apps, schema_editor):
    """Drop stale branch item caches after the available/is_active separation."""
    MenuItem = apps.get_model("menu", "MenuItem")
    try:
        from core.cache import cache_delete
        from core.cache import CacheKeys
    except ImportError:
        return

    branch_ids = (
        MenuItem.objects.order_by()
        .values_list("branch_id", flat=True)
        .distinct()
    )
    for branch_id in branch_ids:
        cache_delete(
            CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=branch_id)
        )
        cache_delete(
            CacheKeys.MENU_BRANCH_CATEGORIES_WITH_ITEMS.format(
                branch_id=branch_id
            )
        )


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0004_menuitem_available"),
    ]

    operations = [
        migrations.RunPython(
            bust_menu_branch_item_caches,
            migrations.RunPython.noop,
        ),
    ]
