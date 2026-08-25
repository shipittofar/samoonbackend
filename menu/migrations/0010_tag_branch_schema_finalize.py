import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Migration C — finalize schema.

    Apply NOT NULL constraints, per-branch uniqueness, and model options
    after data migration 0009 has populated branch_id on every remaining tag.
    """

    dependencies = [
        ("menu", "0009_migrate_tags_to_branch_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tag",
            name="branch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tags",
                to="tenants.branch",
            ),
        ),
        migrations.AlterField(
            model_name="tag",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="tag",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                fields=("branch", "name"),
                name="menu_tag_unique_name_per_branch",
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                fields=("branch", "slug"),
                name="menu_tag_unique_slug_per_branch",
            ),
        ),
        migrations.AlterModelOptions(
            name="tag",
            options={"ordering": ["display_order", "name"]},
        ),
    ]
