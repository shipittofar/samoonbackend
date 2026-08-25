from django.conf import settings
from faker import Faker

from accounts.models.user import User, UserRole
from seeders.base import BaseSeeder
from seeders.registry import SeedRegistry

fake = Faker("fa_IR")


class AdminUserSeeder(BaseSeeder):
    label = "admin_user"

    def run(self, registry: SeedRegistry, stdout) -> None:
        phone_number = settings.SEED_ADMIN_PHONE_NUMBER
        password = settings.SEED_ADMIN_PASSWORD

        user, created = User.all_objects.get_or_create(
            phone_number=phone_number,
            defaults={
                "email": settings.SEED_ADMIN_EMAIL,
                "first_name": "Super",
                "last_name": "Admin",
                "role": UserRole.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_verified": True,
                "is_active": True,
            },
        )

        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
            stdout.write(f"[seed] Admin user created: {phone_number}")
        else:
            stdout.write(f"[seed] Admin user already exists: {phone_number}")

        registry.register("user:admin", user)


class OwnerUserSeeder(BaseSeeder):
    """Creates N distinct users who will each own a Tenant."""

    label = "owner_users"
    COUNT = 5

    def run(self, registry: SeedRegistry, stdout) -> None:
        for i in range(self.COUNT):
            # شماره ثابت بر اساس ایندکس تا re-run دوباره تکراری نسازه
            phone_number = f"099{i:08d}"

            user, created = User.all_objects.get_or_create(
                phone_number=phone_number,
                defaults={
                    "email": f"owner{i}@seed.local",
                    "first_name": fake.first_name(),
                    "last_name": fake.last_name(),
                    "role": UserRole.CUSTOMER,
                    "is_verified": True,
                    "is_active": True,
                },
            )
            if created:
                user.set_password("SeedPass123!")
                user.save(update_fields=["password"])

            stdout.write(
                f"[seed] Owner-user {'created' if created else 'exists'}: {user.full_name}"
            )
            registry.append("users:owners", user)


class CustomerUserSeeder(BaseSeeder):
    """Creates N distinct customer users who will place orders."""

    label = "customer_users"
    COUNT = 5

    def run(self, registry: SeedRegistry, stdout) -> None:
        for i in range(self.COUNT):
            phone_number = f"098{i:08d}"

            user, created = User.all_objects.get_or_create(
                phone_number=phone_number,
                defaults={
                    "email": f"customer{i}@seed.local",
                    "first_name": fake.first_name(),
                    "last_name": fake.last_name(),
                    "role": UserRole.CUSTOMER,
                    "is_verified": True,
                    "is_active": True,
                },
            )
            if created:
                user.set_password("SeedPass123!")
                user.save(update_fields=["password"])

            stdout.write(
                f"[seed] Customer {'created' if created else 'exists'}: {user.full_name}"
            )
            registry.append("users:customers", user)