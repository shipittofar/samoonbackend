import uuid
from decimal import Decimal

from django.db import transaction
from faker import Faker

from addresses.models import Address, AddressLabel
from orders.models import (
    Order,
    OrderDeliveryAddress,
    OrderType,
    PaymentMethod,
    PaymentStatus,
    OrderStatus,
    OrderItem,
    OrderItemExtra,
    OrderStatusHistory,
)
from orders.services.orders_bll import OrdersBusinessLogicLayer
from seeders.base import BaseSeeder
from seeders.registry import SeedRegistry

fake = Faker("fa_IR")


class AddressSeeder(BaseSeeder):
    label = "address"

    def run(self, registry: SeedRegistry, stdout) -> None:
        customers = registry.get_list("users:customers")

        for customer in customers:
            for title, is_default in [("Home", True), ("Work", False)]:
            phone = "".join(ch for ch in (customer.phone_number or "") if ch.isdigit())[-10:] or "9123456789"
            country_code = customer.country_code or "+98"
            defaults = {
                "label": AddressLabel.HOME if title == "Home" else AddressLabel.WORK,
                "first_name": customer.first_name or "Customer",
                "last_name": customer.last_name or "",
                "phone": phone,
                "country_code": country_code,
                "country": "IR",
                "province": fake.city(),
                "city": fake.city(),
                "street": fake.street_address(),
                "postal_code": fake.postcode() or "1234567890",
                "latitude": float(fake.latitude()),
                "longitude": float(fake.longitude()),
                "is_default": is_default,
            }
            address, created = Address.objects.get_or_create(
                user=customer,
                title=title,
                defaults=defaults,
            )
            if title == "Work" and address.is_default:
                address.is_default = False
                address.save(update_fields=["is_default"])
                stdout.write(
                    f"[seed] Address {'created' if created else 'exists'}: "
                    f"{customer.full_name} / {title}"
                )
                registry.append(f"addresses:{customer.pk}", address)


class OrderSeeder(BaseSeeder):
    """Creates 5 diverse orders per branch, each with 1-3 items and random extras."""

    label = "order"
    ORDERS_PER_BRANCH = 5

    def run(self, registry: SeedRegistry, stdout) -> None:
        branches = registry.get_list("branches")
        customers = registry.get_list("users:customers")

        if not customers:
            stdout.write("[seed] Skipping orders: no customers found in registry")
            return

        order_counter = 1
        orders_bll = OrdersBusinessLogicLayer()

        for branch in branches:
            tenant = branch.tenant
            items = registry.get_list(f"items:{branch.pk}")
            extras = registry.get_list(f"extras:{branch.pk}")

            if not items:
                stdout.write(f"[seed] Skipping orders for {branch}: no menu items")
                continue

            for _ in range(self.ORDERS_PER_BRANCH):
                order_number = f"ORD-SEED-{order_counter:05d}"
                order_counter += 1

                try:
                    self._create_single_order(
                        registry=registry,
                        stdout=stdout,
                        branch=branch,
                        tenant=tenant,
                        customers=customers,
                        items=items,
                        extras=extras,
                        order_number=order_number,
                        orders_bll=orders_bll,
                    )
                except Exception as exc:
                    stdout.write(
                        f"[seed] FAILED to create order {order_number}: {exc!r}"
                    )

    @transaction.atomic
    def _create_single_order(
        self, *, registry, stdout, branch, tenant, customers, items, extras, order_number, orders_bll
    ):
        import random

        customer = random.choice(customers)
        order_type = random.choice(list(OrderType.values))

        delivery_address = None
        table_number = None

        if order_type == OrderType.DELIVERY:
            customer_addresses = registry.get_list(f"addresses:{customer.pk}")
            book_address = random.choice(customer_addresses) if customer_addresses else None
            if book_address is not None:
                snapshot_data = orders_bll.address_bll.snapshot_fields_from_address(book_address)
                delivery_address = OrderDeliveryAddress.objects.create(**snapshot_data)
        elif order_type == OrderType.DINE_IN:
            table_number = random.randint(1, 20)

        order, created = Order.objects.get_or_create(
            order_number=order_number,
            defaults={
                "customer": customer,
                "branch": branch,
                "order_type": order_type,
                "status": random.choice(list(OrderStatus.values)),
                "payment_method": random.choice(list(PaymentMethod.values)),
                "payment_status": random.choice(list(PaymentStatus.values)),
                "delivery_address": delivery_address,
                "table_number": table_number,
                "notes": fake.sentence() if random.random() > 0.7 else "",
            },
        )

        if not created:
            stdout.write(f"[seed] Order exists: {order.order_number}")
            return

        selected_items = random.sample(items, k=min(random.randint(1, 3), len(items)))
        subtotal = Decimal("0")

        for menu_item in selected_items:
            quantity = random.randint(1, 3)
            unit_price = menu_item.price

            image_value = getattr(menu_item, "image", "") or ""
            if hasattr(image_value, "url"):
                image_value = image_value.url

            order_item = OrderItem.objects.create(
                order=order,
                menu_item=menu_item,
                name=menu_item.name,
                image=image_value,
                quantity=quantity,
                unit_price=unit_price,
                total_price=unit_price * quantity,
            )

            item_extras_total = Decimal("0")
            if extras:
                chosen_extras = random.sample(extras, k=random.randint(0, min(2, len(extras))))
                for extra in chosen_extras:
                    OrderItemExtra.objects.create(
                        order_item=order_item,
                        extra=extra,
                        price=extra.price,
                    )
                    item_extras_total += extra.price

            order_item.total_price = (unit_price * quantity) + item_extras_total
            order_item.save(update_fields=["total_price"])

            subtotal += order_item.total_price

        tax_rate = tenant.tax_percentage
        tax = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
        discount_amount = (
            subtotal * Decimal(random.choice([0, 5, 10])) / Decimal("100")
        ).quantize(Decimal("0.01"))
        service_charge = (
            subtotal * Decimal("5") / Decimal("100")
        ).quantize(Decimal("0.01")) if order.order_type == OrderType.DINE_IN else Decimal("0")

        total = subtotal - discount_amount + tax + service_charge

        order.subtotal = subtotal
        order.discount_amount = discount_amount
        order.tax = tax
        order.service_charge = service_charge
        order.total = total
        order.save(update_fields=[
            "subtotal", "discount_amount", "tax", "service_charge", "total"
        ])

        OrderStatusHistory.objects.create(
            order=order,
            status=OrderStatus.PENDING,
            note="Order created (seed)",
        )
        if order.status != OrderStatus.PENDING:
            OrderStatusHistory.objects.create(
                order=order,
                status=order.status,
                note="Seed shortcut to current status",
            )

        stdout.write(
            f"[seed] Order created: {order.order_number} "
            f"({branch}, {order.status}, total={order.total})"
        )
        registry.append("orders", order)
