import random
from decimal import Decimal

from faker import Faker

from menu.models import (
    Tag,
    MenuCategory,
    MenuItem,
    Extra,
    MenuItemExtra,
    ExtraGroup,
    MenuItemExtraGroup,
)
from seeders.base import BaseSeeder
from seeders.registry import SeedRegistry

fake = Faker("fa_IR")

TAG_NAMES = ["Vegetarian", "Vegan", "Spicy", "Classic", "Gluten-Free"]

CATEGORY_NAMES = ["Hot Drinks", "Cold Drinks", "Breakfast", "Main Course", "Desserts"]

ITEM_NAME_POOL = [
    "Espresso", "Cappuccino", "Iced Latte", "Cold Brew", "Turkish Coffee",
    "Grilled Chicken", "Beef Burger", "Margherita Pizza", "Caesar Salad",
    "Chocolate Cake", "Tiramisu", "Cheesecake", "Omelette", "Pancakes",
    "Club Sandwich", "Lamb Kebab", "Mushroom Soup", "Fish and Chips",
    "Fruit Smoothie", "Lemonade",
]

EXTRA_GROUP_DEFINITIONS = [
    {
        "name": "Size",
        "description": "Choose one size",
        "selection_type": "single",
        "required": True,
        "min_selection": 1,
        "max_selection": 1,
        "extras": ["Small", "Medium", "Large"],
    },
    {
        "name": "Sauces",
        "description": "Add extra sauces",
        "selection_type": "multiple",
        "required": False,
        "min_selection": 0,
        "max_selection": 3,
        "extras": ["BBQ Sauce", "Garlic Mayo", "Hot Sauce"],
    },
    {
        "name": "Toppings",
        "description": "Customize with toppings",
        "selection_type": "multiple",
        "required": False,
        "min_selection": 0,
        "max_selection": 5,
        "extras": ["Extra Cheese", "Mushroom", "Jalapeño", "Avocado"],
    },
]


class TagSeeder(BaseSeeder):
    """Create branch-scoped tags for every seeded branch."""

    label = "tag"

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")

        for branch in branches:
            for order, name in enumerate(TAG_NAMES):
                tag, created = Tag.objects.get_or_create(
                    branch=branch,
                    name=name,
                    defaults={
                        "is_active": True,
                        "display_order": order,
                    },
                )
                stdout.write(
                    f"[seed] Tag {'created' if created else 'exists'}: "
                    f"{branch.name} / {tag.name}"
                )
                registry.append(f"tags:{branch.pk}", tag)


class MenuCategorySeeder(BaseSeeder):
    label = "menu_category"

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")

        for branch in branches:
            for i, cat_name in enumerate(CATEGORY_NAMES):
                category, created = MenuCategory.objects.get_or_create(
                    branch=branch,
                    name=cat_name,
                    defaults={
                        "description": fake.sentence(),
                        "sort_order": i,
                    },
                )
                stdout.write(
                    f"[seed] Category {'created' if created else 'exists'}: "
                    f"{branch.name} / {category.name}"
                )
                registry.append(f"categories:{branch.pk}", category)


class ExtraGroupSeeder(BaseSeeder):
    label = "extra_group"

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")

        for branch in branches:
            for order, definition in enumerate(EXTRA_GROUP_DEFINITIONS, start=1):
                group, created = ExtraGroup.objects.get_or_create(
                    branch=branch,
                    name=definition["name"],
                    defaults={
                        "description": definition["description"],
                        "selection_type": definition["selection_type"],
                        "required": definition["required"],
                        "min_selection": definition["min_selection"],
                        "max_selection": definition["max_selection"],
                        "order": order,
                        "is_active": True,
                    },
                )
                stdout.write(
                    f"[seed] ExtraGroup {'created' if created else 'exists'}: "
                    f"{branch.name} / {group.name}"
                )
                registry.append(f"extra_groups:{branch.pk}", group)

                for extra_order, extra_name in enumerate(definition["extras"], start=1):
                    extra, extra_created = Extra.objects.get_or_create(
                        branch=branch,
                        group=group,
                        name=extra_name,
                        defaults={
                            "price": Decimal(random.randrange(0, 30)) * 1000,
                            "available": True,
                            "order": extra_order,
                        },
                    )
                    if extra_created:
                        stdout.write(
                            f"[seed] Extra {'created' if extra_created else 'exists'}: "
                            f"{group.name} / {extra.name}"
                        )
                    registry.append(f"extras:{branch.pk}", extra)


class MenuItemSeeder(BaseSeeder):
    label = "menu_item"

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")

        for branch in branches:
            categories = registry.get_list(f"categories:{branch.pk}")
            tags = registry.get_list(f"tags:{branch.pk}")

            for category in categories:
                names = random.sample(ITEM_NAME_POOL, k=5)

                for name in names:
                    item, created = MenuItem.objects.get_or_create(
                        branch=branch,
                        category=category,
                        name=name,
                        defaults={
                            "description": fake.sentence(),
                            "price": Decimal(random.randrange(50, 500)) * 1000,
                            "discount": random.choice([0, 0, 5, 10, 15]),
                            "calories": random.randint(150, 900),
                            "preparation_time": random.randint(5, 40),
                            "is_active": True,
                            "available": True,
                            "is_popular": random.choice([True, False]),
                            "is_featured": random.choice([True, False]),
                        },
                    )
                    if created:
                        item.tags.set(random.sample(tags, k=random.randint(1, 3)))

                    stdout.write(
                        f"[seed] MenuItem {'created' if created else 'exists'}: "
                        f"{branch.name} / {category.name} / {item.name}"
                    )
                    registry.append(f"items:{branch.pk}", item)


class MenuItemExtraGroupSeeder(BaseSeeder):
    """Assigns extra groups to items and materializes MenuItemExtra links."""

    label = "menu_item_extra_group"

    def run(self, registry: SeedRegistry, stdout) -> None:
        from menu.selectors.extra_group_dal import MenuItemExtraGroupDataAccessLayer

        branches = registry.get_list("branches")

        for branch in branches:
            items = registry.get_list(f"items:{branch.pk}")
            groups = registry.get_list(f"extra_groups:{branch.pk}")

            if not groups:
                continue

            for item in items:
                assigned = random.sample(
                    groups, k=min(random.randint(1, 2), len(groups))
                )
                for group in assigned:
                    MenuItemExtraGroup.objects.get_or_create(
                        item=item,
                        extra_group=group,
                    )
                MenuItemExtraGroupDataAccessLayer.sync_item_extras_from_groups(
                    item.id, branch.id
                )
                stdout.write(
                    f"[seed] Assigned {len(assigned)} extra group(s) to {item.name}"
                )


class MenuItemExtraSeeder(BaseSeeder):
    """Legacy seeder kept for backward compatibility; skipped when groups exist."""

    label = "menu_item_extra"

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")

        for branch in branches:
            if registry.get_list(f"extra_groups:{branch.pk}"):
                stdout.write(
                    f"[seed] Skipping legacy MenuItemExtra seeder for {branch.name} "
                    "(extra groups already seeded)"
                )
                continue

            items = registry.get_list(f"items:{branch.pk}")
            extras = registry.get_list(f"extras:{branch.pk}")

            if not extras:
                continue

            for item in items:
                linked_extras = random.sample(extras, k=min(2, len(extras)))

                for extra in linked_extras:
                    link, created = MenuItemExtra.objects.get_or_create(
                        item=item,
                        extra=extra,
                        defaults={
                            "price_override": (
                                None if random.random() > 0.3
                                else Decimal(random.randrange(5, 30)) * 1000
                            ),
                        },
                    )
                    if created:
                        stdout.write(f"[seed] Linked extra: {item.name} + {extra.name}")
