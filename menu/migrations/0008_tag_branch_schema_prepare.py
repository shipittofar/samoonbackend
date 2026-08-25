import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

import menu.models.item


class Migration(migrations.Migration):
    """
    Migration A — schema preparation only.

    Add nullable columns and drop global uniqueness so branch-scoped tags
    can be created in the following data migration without constraint
    violations. No RunPython in this migration.
    """

    dependencies = [
        ("menu", "0007_menuitem_deleted_at"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tag",
            name="name",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="tag",
            name="slug",
            field=models.SlugField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="tag",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tags",
                to="tenants.branch",
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="tag",
            name="icon",
            field=models.CharField(
                blank=True,
                help_text="Optional emoji shown in storefront filters.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=menu.models.item.UniqueFilePath("menu_tags"),
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["jpg", "jpeg", "png", "webp", "gif"]
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="color",
            field=models.CharField(
                blank=True,
                help_text="Optional HEX color, e.g. #2ecc71",
                max_length=7,
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Inactive tags are hidden from public storefront endpoints.",
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="display_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="tag",
            name="created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tag",
            name="updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
