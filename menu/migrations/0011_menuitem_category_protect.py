from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0010_tag_branch_schema_finalize"),
    ]

    operations = [
        migrations.AlterField(
            model_name="menuitem",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items",
                to="menu.menucategory",
            ),
        ),
    ]
