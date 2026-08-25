from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["branch", "created_at"],
                name="order_branch_created_idx",
            ),
        ),
    ]
