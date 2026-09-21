"""Phase 3 MenuItem soft-delete, category/extra protection."""
import uuid
from decimal import Decimal

from django.db.models.deletion import ProtectedError
from django.test import TestCase

from accounts.models import Favorite, User
from accounts.selectors.favorite_dal import FavoriteDataAccessLayer
from core.exceptions.category import CategoryHasItemsException
from core.exceptions.item import ExtraReferencedByOrdersException
from menu.models import Extra, ExtraGroup, MenuCategory, MenuItem
from menu.selectors.item_visibility import queryset_public_active_items
from menu.services.category_bll import CategoryBusinessLogicLayer
from menu.services.extra_group_bll import ExtraGroupBusinessLogicLayer
from menu.services.item_bll import ExtraBusinessLogicLayer, ItemBusinessLogicLayer
from orders.models import Order, OrderItem, OrderItemExtra, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def make_branch():
    owner = Owner.objects.create(user=make_user())
    tenant = Tenant.objects.create(owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}")
    return Branch.objects.create(tenant=tenant, name="Main", pickup_enabled=True)


class MenuItemSoftDeleteTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.category = MenuCategory.objects.create(branch=self.branch, name="Mains")
        self.item = MenuItem.objects.create(
            branch=self.branch,
            category=self.category,
            name="Burger",
            price=Decimal("10.00"),
        )

    def test_delete_sets_deleted_at_and_keeps_row(self):
        ItemBusinessLogicLayer.delete_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        ItemBusinessLogicLayer.delete_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        self.assertFalse(MenuItem.objects.filter(id=self.item.id).exists())
        stored = MenuItem.all_objects.get(id=self.item.id)
        self.assertIsNotNone(stored.deleted_at)

    def test_order_item_survives_and_hard_delete_is_protected(self):
        order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
        )
        OrderItem.objects.create(
            order=order,
            menu_item=self.item,
            name="Burger",
            quantity=1,
            unit_price=Decimal("10.00"),
            total_price=Decimal("10.00"),
        )
        ItemBusinessLogicLayer.delete_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        self.assertTrue(OrderItem.objects.filter(menu_item_id=self.item.id).exists())
        with self.assertRaises(ProtectedError):
            MenuItem.all_objects.get(id=self.item.id).delete()

    def test_storefront_and_favorites_exclude_deleted(self):
        user = make_user()
        Favorite.objects.create(user=user, menu_item=self.item)
        ItemBusinessLogicLayer.delete_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        qs = queryset_public_active_items(self.branch.id)
        self.assertFalse(qs.filter(id=self.item.id).exists())
        self.assertEqual(FavoriteDataAccessLayer.list_menu_item_ids_for_user(user.id), [])

    def test_restore_clears_deleted_at(self):
        ItemBusinessLogicLayer.delete_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        restored = ItemBusinessLogicLayer.restore_menu_item(
            self.item.id, self.category.id, self.branch.id
        )
        self.assertIsNone(restored.deleted_at)
        self.assertTrue(MenuItem.objects.filter(id=self.item.id).exists())

    def test_category_with_items_cannot_be_deleted(self):
        with self.assertRaises(CategoryHasItemsException):
            CategoryBusinessLogicLayer.delete_menu_category(
                self.category.id, self.branch.id
            )
        self.assertTrue(MenuCategory.objects.filter(id=self.category.id).exists())
        self.assertTrue(MenuItem.all_objects.filter(id=self.item.id).exists())

    def test_empty_category_can_be_hard_deleted(self):
        empty = MenuCategory.objects.create(branch=self.branch, name="Empty")
        CategoryBusinessLogicLayer.delete_menu_category(empty.id, self.branch.id)
        self.assertFalse(MenuCategory.objects.filter(id=empty.id).exists())

    def test_extra_referenced_by_order_is_not_hard_deleted(self):
        group = ExtraGroup.objects.create(branch=self.branch, name="Size")
        extra = Extra.objects.create(
            branch=self.branch, group=group, name="Large", price=Decimal("1.00")
        )
        order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
        )
        order_item = OrderItem.objects.create(
            order=order,
            menu_item=self.item,
            name="Burger",
            quantity=1,
            unit_price=Decimal("10.00"),
            total_price=Decimal("11.00"),
        )
        OrderItemExtra.objects.create(
            order_item=order_item, extra=extra, price=Decimal("1.00")
        )
        with self.assertRaises(ExtraReferencedByOrdersException):
            ExtraBusinessLogicLayer.delete_extra(extra.id, self.branch.id)
        extra.refresh_from_db()
        self.assertFalse(extra.available)
        self.assertTrue(Extra.objects.filter(id=extra.id).exists())

    def test_extra_group_with_extras_deactivates(self):
        group = ExtraGroup.objects.create(branch=self.branch, name="Size", is_active=True)
        Extra.objects.create(
            branch=self.branch, group=group, name="Large", price=Decimal("1.00")
        )
        ExtraGroupBusinessLogicLayer.delete_extra_group(group.id, self.branch.id)
        group.refresh_from_db()
        self.assertFalse(group.is_active)
        self.assertTrue(Extra.objects.filter(group=group).exists())
