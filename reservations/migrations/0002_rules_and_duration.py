import datetime

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def fill_ends_at(apps, schema_editor):
    """Existing reservations were booked for two hours."""
    apps.get_model("reservations", "Reservation").objects.filter(ends_at__isnull=True).update(
        ends_at=F("reserved_at") + datetime.timedelta(hours=2)
    )


class Migration(migrations.Migration):
    # PostgreSQL cannot ALTER a table that has pending trigger events from the
    # UPDATE above in the same transaction.
    atomic = False

    dependencies = [
        ("reservations", "0001_initial"),
        ("tenants", "0022_alter_branch_currency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField("reservation", "duration_minutes", models.PositiveIntegerField(default=120)),
        migrations.AddField("reservation", "ends_at", models.DateTimeField(editable=False, null=True)),
        migrations.RunPython(fill_ends_at, migrations.RunPython.noop),
        migrations.AlterField("reservation", "ends_at", models.DateTimeField(editable=False)),
        migrations.AddIndex(
            "reservation", models.Index(fields=["branch", "ends_at"], name="reservation_branch_ends_idx"),
        ),
        migrations.CreateModel(
            name="BranchReservationRules",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slot_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("duration_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("last_before_close_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("lead_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("max_days_ahead", models.PositiveIntegerField(blank=True, null=True)),
                ("max_concurrent", models.PositiveIntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="reservation_rules", to="tenants.branch")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "branch_reservation_rules"},
        ),
    ]
