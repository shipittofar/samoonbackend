from django.core.management.base import BaseCommand
from django.db import transaction

from seeders.cache_bust import bust_caches_after_seed
from seeders.registry import SeedRegistry
from seeders.runners.accounts_seeder import (
    AdminUserSeeder,
    OwnerUserSeeder,
    CustomerUserSeeder,
)
from seeders.runners.tenants_seeder import (
    OwnerSeeder,
    TenantSeeder,
    BranchSeeder,
)
from seeders.runners.menu_seeder import (
    TagSeeder,
    MenuCategorySeeder,
    MenuItemSeeder,
    ExtraGroupSeeder,
    MenuItemExtraGroupSeeder,
)
from seeders.runners.orders_seeder import (
    AddressSeeder,
    OrderSeeder,
)

SEEDER_PIPELINE = [
    AdminUserSeeder,
    OwnerUserSeeder,
    CustomerUserSeeder,
    OwnerSeeder,
    TenantSeeder,
    BranchSeeder,
    TagSeeder,
    MenuCategorySeeder,
    MenuItemSeeder,
    ExtraGroupSeeder,
    MenuItemExtraGroupSeeder,
    AddressSeeder,
    OrderSeeder,
]


class Command(BaseCommand):
    help = "Seed the database with default data required for the app to run (e.g. admin user)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            nargs="+",
            help="Run only the given seeder labels (e.g. --only admin_user)",
        )

    def handle(self, *args, **options):
        only = options.get("only")
        registry = SeedRegistry()

        with transaction.atomic():
            for seeder_cls in SEEDER_PIPELINE:
                seeder = seeder_cls()
                if only and seeder.label not in only:
                    continue
                seeder.run(registry, self.stdout)

            # Schedule after commit so we never refresh caches from a rolled-back txn.
            transaction.on_commit(lambda: bust_caches_after_seed(registry))

        self.stdout.write(self.style.SUCCESS("Seeding completed."))
