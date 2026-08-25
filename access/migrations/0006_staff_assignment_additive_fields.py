import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0005_seed_rbac_reference_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="staffassignment",
            name="all_locations",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="granted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="granted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="granted_staff_assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="mode",
            field=models.CharField(
                choices=[("read", "Read"), ("manage", "Manage")],
                default="manage",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="revoked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revoked_staff_assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("future", "Future"),
                    ("revoked", "Revoked"),
                    ("expired", "Expired"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="valid_from",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staffassignment",
            name="valid_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="staffassignment",
            index=models.Index(
                fields=["membership", "status"],
                name="staff_assig_members_7f0a2a_idx",
            ),
        ),
    ]
