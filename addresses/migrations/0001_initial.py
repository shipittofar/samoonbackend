import uuid

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0004_favorite"),
    ]

    operations = [
        migrations.CreateModel(
            name="Address",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("legacy_id", models.PositiveIntegerField(blank=True, help_text="Preserved integer PK from the legacy orders.Address table.", null=True, unique=True)),
                ("title", models.CharField(max_length=100)),
                ("label", models.CharField(choices=[("home", "Home"), ("work", "Work"), ("office", "Office"), ("parents", "Parents"), ("custom", "Custom")], default="custom", max_length=20)),
                ("first_name", models.CharField(max_length=64)),
                ("last_name", models.CharField(max_length=64)),
                ("company", models.CharField(blank=True, default="", max_length=128)),
                ("phone", models.CharField(max_length=20)),
                ("country_code", models.CharField(max_length=5)),
                ("country", models.CharField(help_text="ISO 3166-1 alpha-2 country code.", max_length=2)),
                ("province", models.CharField(blank=True, default="", max_length=100)),
                ("city", models.CharField(max_length=100)),
                ("district", models.CharField(blank=True, default="", max_length=100)),
                ("street", models.CharField(max_length=500)),
                ("building_number", models.CharField(blank=True, default="", max_length=32)),
                ("unit", models.CharField(blank=True, default="", max_length=32)),
                ("postal_code", models.CharField(max_length=20)),
                ("latitude", models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)])),
                ("longitude", models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)])),
                ("delivery_notes", models.TextField(blank=True, default="")),
                ("is_default", models.BooleanField(default=False)),
                ("is_verified", models.BooleanField(default=False)),
                ("verification_method", models.CharField(choices=[("none", "None"), ("sms", "SMS"), ("manual", "Manual")], default="none", max_length=20)),
                ("fingerprint", models.CharField(editable=False, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="addresses", to="accounts.user")),
            ],
            options={
                "db_table": "user_address",
                "ordering": ["-is_default", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["user"], name="user_address_user_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["user", "is_default"], name="user_address_default_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["city"], name="user_address_city_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["postal_code"], name="user_address_postal_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["title"], name="user_address_title_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["deleted_at"], name="user_address_deleted_idx"),
        ),
        migrations.AddConstraint(
            model_name="address",
            constraint=models.UniqueConstraint(condition=models.Q(("deleted_at__isnull", True), ("is_default", True)), fields=("user",), name="unique_active_default_address_per_user"),
        ),
        migrations.AddConstraint(
            model_name="address",
            constraint=models.UniqueConstraint(condition=models.Q(("deleted_at__isnull", True)), fields=("user", "fingerprint"), name="unique_active_address_fingerprint_per_user"),
        ),
    ]
