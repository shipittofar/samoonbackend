from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_delivery_address_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="formatted_address",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="floor",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="address_type",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="branch_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="delivery_zone",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="verification_status",
            field=models.CharField(blank=True, default="pending", max_length=20),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="distance_km",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="delivery_fee",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="estimated_delivery_time",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="orderdeliveryaddress",
            name="calculated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
