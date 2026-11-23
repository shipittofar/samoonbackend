from django.core.management.base import BaseCommand, CommandError

from wallet.services import health


class Command(BaseCommand):
    help = "Verify the wallet ledger: balanced transactions, cached balances, no negative customer wallets."

    def handle(self, *args, **options):
        report = health()
        self.stdout.write(f"accounts: {report['accounts']}  transactions: {report['transactions']}")
        for problem in report["problems"]:
            self.stdout.write(self.style.ERROR(problem))
        if not report["ok"]:
            raise CommandError("Wallet ledger check FAILED")
        self.stdout.write(self.style.SUCCESS("Wallet ledger OK"))
