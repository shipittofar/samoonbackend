from faker import Faker

from tenants.models import (
    Owner,
    Tenant,
    BusinessType,
    TenantStatus,
    Branch,
    BranchStatus,
    BranchType,
    WorkingHour,
)
from seeders.base import BaseSeeder
from seeders.registry import SeedRegistry

fake = Faker("fa_IR")

TENANT_NAMES = [
    ("Savor Coffee", [BusinessType.CAFE]),
    ("Golestan Restaurant", [BusinessType.RESTAURANT]),
    ("Cafe Noon", [BusinessType.CAFE]),
    ("Shandiz Grill", [BusinessType.RESTAURANT]),
    ("Roastery 22", [BusinessType.CAFE]),
]

CITIES = ["Tehran", "Shiraz", "Isfahan", "Mashhad", "Tabriz"]
COUNTRY = "Iran"

TIMEZONES_BY_CITY = {
    "Tehran": "Asia/Tehran",
    "Shiraz": "Asia/Tehran",
    "Isfahan": "Asia/Tehran",
    "Mashhad": "Asia/Tehran",
    "Tabriz": "Asia/Tehran",
}


class OwnerSeeder(BaseSeeder):
    label = "owner"

    def run(self, registry: SeedRegistry, stdout) -> None:
        owner_users = registry.get_list("users:owners")

        for user in owner_users:
            owner, created = Owner.objects.get_or_create(user=user)
            stdout.write(
                f"[seed] Owner {'created' if created else 'exists'} for {user.full_name}"
            )
            registry.append("owners", owner)


class TenantSeeder(BaseSeeder):
    label = "tenant"

    def run(self, registry: SeedRegistry, stdout) -> None:
        owners = registry.get_list("owners")

        for i, owner in enumerate(owners):
            name, business_types = TENANT_NAMES[i % len(TENANT_NAMES)]

            tenant, created = Tenant.objects.get_or_create(
                owner=owner,
                name=name,
                defaults={
                    "business_types": business_types,
                    "status": TenantStatus.ACTIVE,
                    "tax_percentage": fake.random_int(min=0, max=10),
                },
            )
            stdout.write(
                f"[seed] Tenant {'created' if created else 'exists'}: {tenant.name}"
            )
            registry.append("tenants", tenant)
            registry.register(f"tenant:{i}", tenant)


class BranchSeeder(BaseSeeder):
    label = "branch"

    def run(self, registry: SeedRegistry, stdout) -> None:
        tenants = registry.get_list("tenants")

        for i, tenant in enumerate(tenants):
            city = CITIES[i % len(CITIES)]
            is_first_branch = True
            is_restaurant = BusinessType.RESTAURANT in (tenant.business_types or [])

            branch, created = Branch.objects.get_or_create(
                tenant=tenant,
                name=f"{city} Branch",
                defaults={
                    "type": BranchType.PHYSICAL,
                    "phone": fake.phone_number(),
                    "email": fake.company_email(),
                    "website": fake.url(),
                    "address": fake.address(),
                    "city": city,
                    "country": COUNTRY,
                    "postal_code": fake.postcode(),
                    "latitude": fake.latitude(),
                    "longitude": fake.longitude(),
                    "time_zone": TIMEZONES_BY_CITY.get(city, "Asia/Tehran"),
                    "currency": "IRR",
                    "language": "fa",
                    "settings": {},
                    "metadata": {},
                    "status": BranchStatus.ACTIVE,
                    "is_active": True,
                    "is_default": is_first_branch,
                    "delivery_enabled": True,
                    "delivery_radius_km": fake.random_int(min=3, max=15),
                    "pickup_enabled": True,
                    "table_ordering_enabled": is_restaurant,
                    "reservations_enabled": is_restaurant,
                    "max_capacity": fake.random_int(min=20, max=120),
                },
            )
            stdout.write(
                f"[seed] Branch {'created' if created else 'exists'}: {branch.name}"
            )
            registry.append("branches", branch)

            for day in range(7):
                WorkingHour.objects.get_or_create(
                    branch=branch,
                    day=day,
                    defaults={
                        "open_time": "09:00",
                        "close_time": "22:00",
                        "is_closed": False,
                    },
                )
