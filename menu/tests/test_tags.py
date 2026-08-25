"""Tests for branch-scoped tag management."""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from menu.models import MenuCategory, MenuItem, Tag
from tenants.models import Branch, Owner, Tenant


def make_user(*, suffix=""):
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}{suffix}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def make_branch_for_user(user):
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return Branch.objects.create(tenant=tenant, name="Main")


def make_category(branch):
    return MenuCategory.objects.create(branch=branch, name="Mains")


def make_item(branch, category, *, name="Burger"):
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name=name,
        price=Decimal("20.00"),
    )


class BranchTagAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user(suffix="owner")
        self.other_user = make_user(suffix="other")
        self.branch = make_branch_for_user(self.owner)
        self.other_branch = make_branch_for_user(self.other_user)
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)

    def _tag_list_url(self, branch_id=None):
        return f"/api/menu/branches/{branch_id or self.branch.id}/tags/"

    def _tag_detail_url(self, tag_id, branch_id=None):
        return f"/api/menu/branches/{branch_id or self.branch.id}/tags/{tag_id}/"

    def _available_tags_url(self, branch_id=None):
        return f"/api/menu/branches/{branch_id or self.branch.id}/available-tags/"

    def test_create_list_update_delete_tag_crud(self):
        self.client.force_authenticate(user=self.owner)

        create_response = self.client.post(
            self._tag_list_url(),
            {
                "name": "Vegan",
                "icon": "🌱",
                "color": "#2ecc71",
                "display_order": 1,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        tag_id = create_response.data["id"]
        self.assertEqual(create_response.data["name"], "Vegan")
        self.assertEqual(create_response.data["icon"], "🌱")

        list_response = self.client.get(self._tag_list_url())
        self.assertEqual(list_response.status_code, 200, list_response.data)
        self.assertEqual(list_response.data["count"], 1)

        detail_response = self.client.get(self._tag_detail_url(tag_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["slug"], create_response.data["slug"])

        patch_response = self.client.patch(
            self._tag_detail_url(tag_id),
            {"description": "Plant-based items", "is_active": False},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertFalse(patch_response.data["is_active"])

        delete_response = self.client.delete(self._tag_detail_url(tag_id))
        self.assertEqual(delete_response.status_code, 204)

    def test_permissions_require_owner_or_manager(self):
        response = self.client.post(
            self._tag_list_url(),
            {"name": "Spicy"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(user=self.other_user)
        denied = self.client.post(
            self._tag_list_url(),
            {"name": "Spicy"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_unique_name_per_branch_validation(self):
        self.client.force_authenticate(user=self.owner)
        Tag.objects.create(branch=self.branch, name="Vegan")

        response = self.client.post(
            self._tag_list_url(),
            {"name": "Vegan"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_branch_isolation(self):
        self.client.force_authenticate(user=self.owner)
        local_tag = Tag.objects.create(branch=self.branch, name="Chef Choice")
        Tag.objects.create(branch=self.other_branch, name="Chef Choice")

        response = self.client.get(self._tag_detail_url(local_tag.id))
        self.assertEqual(response.status_code, 200)

        cross_branch = self.client.get(
            self._tag_detail_url(local_tag.id, branch_id=self.other_branch.id)
        )
        self.assertEqual(cross_branch.status_code, 403)

        self.client.force_authenticate(user=self.other_user)
        not_found = self.client.get(
            self._tag_detail_url(local_tag.id, branch_id=self.other_branch.id)
        )
        self.assertEqual(not_found.status_code, 404)

    def test_available_tags_public_active_only_with_item_count(self):
        active_tag = Tag.objects.create(
            branch=self.branch,
            name="Vegan",
            icon="🌱",
            color="#2ecc71",
            is_active=True,
        )
        Tag.objects.create(branch=self.branch, name="Hidden", is_active=False)
        self.item.tags.add(active_tag)

        response = self.client.get(self._available_tags_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Vegan")
        self.assertEqual(response.data[0]["item_count"], 1)

    def test_assign_tags_on_item_create_and_update(self):
        tag = Tag.objects.create(branch=self.branch, name="Spicy", icon="🌶")
        self.client.force_authenticate(user=self.owner)

        create_response = self.client.post(
            "/api/menu/create-items/",
            {
                "branch_id": str(self.branch.id),
                "category_id": str(self.category.id),
                "name": "Tacos",
                "price": "12.00",
                "tag_ids": [tag.id],
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        self.assertEqual(len(create_response.data["tags"]), 1)
        self.assertEqual(create_response.data["tags"][0]["name"], "Spicy")

        item_id = create_response.data["id"]
        other_tag = Tag.objects.create(branch=self.branch, name="Popular")
        patch_response = self.client.patch(
            f"/api/menu/items/{item_id}/?branch_id={self.branch.id}",
            {"tag_ids": [other_tag.id]},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.data)
        self.assertEqual(patch_response.data["tags"][0]["name"], "Popular")

    def test_reject_foreign_branch_tag_on_item(self):
        foreign_tag = Tag.objects.create(branch=self.other_branch, name="Foreign")
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            "/api/menu/create-items/",
            {
                "branch_id": str(self.branch.id),
                "category_id": str(self.category.id),
                "name": "Soup",
                "price": "8.00",
                "tag_ids": [foreign_tag.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_filter_menu_items_by_tags_query_param(self):
        vegan = Tag.objects.create(branch=self.branch, name="Vegan")
        spicy = Tag.objects.create(branch=self.branch, name="Spicy")
        self.item.tags.add(vegan)
        other_item = make_item(self.branch, self.category, name="Wings")
        other_item.tags.add(spicy)

        response = self.client.get(
            "/api/menu/items/",
            {
                "branch_id": str(self.branch.id),
                "tags": str(vegan.id),
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        names = [item["name"] for item in response.data["results"]]
        self.assertEqual(names, ["Burger"])

        multi = self.client.get(
            "/api/menu/items/",
            {
                "branch_id": str(self.branch.id),
                "tags": f"{vegan.id},{spicy.id}",
            },
        )
        self.assertEqual(multi.status_code, 200, multi.data)
        self.assertEqual(len(multi.data["results"]), 2)

    def test_search_and_active_filter_on_tag_list(self):
        Tag.objects.create(branch=self.branch, name="Vegan", is_active=True)
        Tag.objects.create(branch=self.branch, name="Hidden", is_active=False)
        self.client.force_authenticate(user=self.owner)

        active_only = self.client.get(
            self._tag_list_url(),
            {"is_active": "true", "search": "veg"},
        )
        self.assertEqual(active_only.status_code, 200)
        self.assertEqual(active_only.data["count"], 1)

    def test_invalid_color_validation(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._tag_list_url(),
            {"name": "Bad Color", "color": "not-a-color"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
