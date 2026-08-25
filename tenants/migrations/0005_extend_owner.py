from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0004_rename_branch_marketplace_visible_idx_branch_marketp_ca8d82_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="owner",
            name="billing_customer_id",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="owner",
            name="billing_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name="owner",
            name="max_tenants",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="owner",
            name="plan",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="owner",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("active", "Active"),
                    ("suspended", "Suspended"),
                    ("pending_verification", "Pending Verification"),
                ],
                max_length=30,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="owner",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
