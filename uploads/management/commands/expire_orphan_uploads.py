from django.core.management.base import BaseCommand

from uploads.services.upload_bll import expire_unattached_assets


class Command(BaseCommand):
    help = "Expire unattached upload assets past their TTL and delete storage objects."

    def handle(self, *args, **options):
        count = expire_unattached_assets()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} orphan upload(s)."))
