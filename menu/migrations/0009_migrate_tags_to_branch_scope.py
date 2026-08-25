from django.db import migrations
from django.utils import timezone


def migrate_global_tags_to_branch_scoped(apps, schema_editor):
    """
    Copy each legacy global tag into branch-scoped rows (one per branch that
    uses it), remap MenuItem M2M links, then delete orphaned global tags.
    """
    Tag = apps.get_model("menu", "Tag")
    MenuItem = apps.get_model("menu", "MenuItem")
    ThroughModel = MenuItem.tags.through

    branch_tag_cache: dict[tuple[int, object], int] = {}
    now = timezone.now()

    for link in ThroughModel.objects.select_related("menuitem").iterator():
        old_tag = Tag.objects.filter(id=link.tag_id).first()
        if old_tag is None:
            continue

        branch_id = link.menuitem.branch_id
        cache_key = (old_tag.id, branch_id)
        if cache_key not in branch_tag_cache:
            branch_tag, created = Tag.objects.get_or_create(
                branch_id=branch_id,
                name=old_tag.name,
                defaults={
                    "slug": old_tag.slug,
                    "description": getattr(old_tag, "description", "") or "",
                    "icon": getattr(old_tag, "icon", "") or "",
                    "color": getattr(old_tag, "color", "") or "",
                    "is_active": getattr(old_tag, "is_active", True),
                    "display_order": getattr(old_tag, "display_order", 0),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            if not created and branch_tag.created_at is None:
                Tag.objects.filter(pk=branch_tag.pk).update(
                    created_at=now,
                    updated_at=now,
                )
            branch_tag_cache[cache_key] = branch_tag.id

        new_tag_id = branch_tag_cache[cache_key]
        if link.tag_id != new_tag_id:
            link.tag_id = new_tag_id
            link.save(update_fields=["tag_id"])

    Tag.objects.filter(branch__isnull=True).delete()

    Tag.objects.filter(created_at__isnull=True).update(
        created_at=now,
        updated_at=now,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    """
    Migration B — data only.

    Runs outside a single atomic block on PostgreSQL so M2M updates and tag
    deletes do not leave pending trigger events for subsequent ALTER TABLE
    operations in migration 0010.
    """

    atomic = False

    dependencies = [
        ("menu", "0008_tag_branch_schema_prepare"),
    ]

    operations = [
        migrations.RunPython(
            migrate_global_tags_to_branch_scoped,
            noop_reverse,
        ),
    ]
