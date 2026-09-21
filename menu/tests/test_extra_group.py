"""Tests for ExtraGroup CRUD, validation, and MenuItem assignment."""

import uuid
from decimal import Decimal

from django.test import TestCase

from menu.models import ExtraGroup, Extra, MenuItem, MenuItemExtra, MenuItemExtraGroup, MenuCategory
from menu.services.extra_group_bll import ExtraGroupBusinessLogicLayer
from menu.services.item_bll import (
    ExtraBusinessLogicLayer,
    MenuItemExtraGroupBusinessLogicLayer,
)
from core.exceptions import (
    ExtraGroupValidationException,
    ExtraGroupNotActiveException,
    ExtraGroupAlreadyExistsException,
    ExtraAlreadyExistsException,
)
from accounts.models import User
from tenants.models import Tenant, Branch, Owner


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
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return Branch.objects.create(tenant=tenant, name="Main")


def make_category(branch):
    return MenuCategory.objects.create(branch=branch, name="Mains")


def make_item(branch, category):
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name="Burger",
        price=Decimal("9.99"),
    )


class ExtraGroupValidationTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.bll = ExtraGroupBusinessLogicLayer()

    def test_create_valid_multiple_group(self):
        group = self.bll.create_extra_group(
            branch_id=self.branch.id,
            name="Toppings",
            selection_type="multiple",
            required=False,
            min_selection=0,
            max_selection=3,
        )
        self.assertEqual(group.name, "Toppings")
        self.assertTrue(ExtraGroup.objects.filter(id=group.id).exists())

    def test_single_selection_enforces_max_one(self):
        with self.assertRaises(ExtraGroupValidationException):
            self.bll.create_extra_group(
                branch_id=self.branch.id,
                name="Size",
                selection_type="single",
                max_selection=2,
            )

    def test_required_enforces_min_one(self):
        with self.assertRaises(ExtraGroupValidationException):
            self.bll.create_extra_group(
                branch_id=self.branch.id,
                name="Sauce",
                selection_type="multiple",
                required=True,
                min_selection=0,
                max_selection=2,
            )

    def test_min_must_not_exceed_max(self):
        with self.assertRaises(ExtraGroupValidationException):
            self.bll.create_extra_group(
                branch_id=self.branch.id,
                name="Bad",
                min_selection=3,
                max_selection=1,
            )

    def test_duplicate_name_per_branch_rejected(self):
        self.bll.create_extra_group(
            branch_id=self.branch.id, name="Toppings"
        )
        with self.assertRaises(ExtraGroupAlreadyExistsException):
            self.bll.create_extra_group(
                branch_id=self.branch.id, name="Toppings"
            )


class MenuItemExtraGroupAssignmentTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)
        self.group_bll = ExtraGroupBusinessLogicLayer()
        self.assign_bll = MenuItemExtraGroupBusinessLogicLayer()
        self.extra_bll = ExtraBusinessLogicLayer()

        self.size_group = self.group_bll.create_extra_group(
            branch_id=self.branch.id,
            name="Size",
            selection_type="single",
            required=True,
            min_selection=1,
            max_selection=1,
        )
        self.small = self.extra_bll.create_extra(
            branch_id=self.branch.id,
            name="Small",
            price=Decimal("0.00"),
            group_id=self.size_group.id,
        )
        self.large = self.extra_bll.create_extra(
            branch_id=self.branch.id,
            name="Large",
            price=Decimal("2.00"),
            group_id=self.size_group.id,
        )

    def test_assign_group_materializes_menu_item_extras(self):
        self.assign_bll.assign_extra_groups_to_item(
            item_id=self.item.id,
            branch_id=self.branch.id,
            group_ids=[self.size_group.id],
        )

        self.assertTrue(
            MenuItemExtraGroup.objects.filter(
                item=self.item, extra_group=self.size_group
            ).exists()
        )
        linked_extra_ids = set(
            MenuItemExtra.objects.filter(item=self.item).values_list(
                "extra_id", flat=True
            )
        )
        self.assertEqual(linked_extra_ids, {self.small.id, self.large.id})

    def test_inactive_group_cannot_be_assigned(self):
        self.group_bll.update_extra_group(
            group_id=self.size_group.id,
            branch_id=self.branch.id,
            is_active=False,
        )
        with self.assertRaises(ExtraGroupNotActiveException):
            self.assign_bll.assign_extra_groups_to_item(
                item_id=self.item.id,
                branch_id=self.branch.id,
                group_ids=[self.size_group.id],
            )

    def test_clearing_groups_removes_materialized_extras(self):
        self.assign_bll.assign_extra_groups_to_item(
            item_id=self.item.id,
            branch_id=self.branch.id,
            group_ids=[self.size_group.id],
        )
        self.assign_bll.assign_extra_groups_to_item(
            item_id=self.item.id,
            branch_id=self.branch.id,
            group_ids=[],
        )
        self.assertEqual(MenuItemExtra.objects.filter(item=self.item).count(), 0)


class ExtraDuplicateNameTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.bll = ExtraBusinessLogicLayer()

    def test_duplicate_extra_name_per_branch_rejected(self):
        self.bll.create_extra(
            branch_id=self.branch.id,
            name="Cheese",
            price=Decimal("1.00"),
        )
        with self.assertRaises(ExtraAlreadyExistsException):
            self.bll.create_extra(
                branch_id=self.branch.id,
                name="Cheese",
                price=Decimal("2.00"),
            )

    def test_update_extra_to_existing_name_rejected(self):
        first = self.bll.create_extra(
            branch_id=self.branch.id,
            name="Bacon",
            price=Decimal("1.00"),
        )
        self.bll.create_extra(
            branch_id=self.branch.id,
            name="Egg",
            price=Decimal("1.00"),
        )
        with self.assertRaises(ExtraAlreadyExistsException):
            self.bll.update_extra(
                extra_id=first.id,
                branch_id=self.branch.id,
                name="Egg",
            )
