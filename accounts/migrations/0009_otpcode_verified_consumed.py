from django.db import migrations, models


class Migration(migrations.Migration):
    """OTP proof of ownership: verified_at (correct code entered) and consumed_at
    (verification already spent, e.g. by sign-up). is_used alone proved nothing."""

    dependencies = [
        ('accounts', '0008_imagefield_max_length_512'),
    ]

    operations = [
        migrations.AddField(
            model_name='otpcode',
            name='verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='otpcode',
            name='consumed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
