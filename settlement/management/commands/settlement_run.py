from django.core.management.base import BaseCommand

from settlement.services import run_scheduled


class Command(BaseCommand):
    help = "Release finished hold periods and create weekly payout requests (when enabled)."

    def handle(self, *args, **options):
        result = run_scheduled()
        self.stdout.write(f"Released {result['released']} order(s); {result['autoPayouts']} automatic payout request(s).")
