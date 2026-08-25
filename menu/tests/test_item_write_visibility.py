"""Unit tests for independent available/is_active write handling."""

from django.http import QueryDict
from django.test import SimpleTestCase

from menu.api.serializers.request.item import (
    MenuItemInputSerializer,
    MenuItemUpdateSerializer,
)


class MenuItemIndependentFieldWriteTests(SimpleTestCase):
    def test_multipart_available_true_only_updates_available(self):
        query = QueryDict(mutable=True)
        query["available"] = "true"
        serializer = MenuItemUpdateSerializer(data=query, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"available": True})
        self.assertNotIn("is_active", serializer.validated_data)

    def test_multipart_is_active_false_only_updates_is_active(self):
        query = QueryDict(mutable=True)
        query["is_active"] = "false"
        serializer = MenuItemUpdateSerializer(data=query, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"is_active": False})
        self.assertNotIn("available", serializer.validated_data)

    def test_multipart_both_fields_persist_independently(self):
        query = QueryDict(mutable=True)
        query.setlist("available", ["true"])
        query.setlist("is_active", ["false"])
        serializer = MenuItemUpdateSerializer(data=query, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data,
            {"available": True, "is_active": False},
        )

    def test_json_both_fields_persist_independently(self):
        serializer = MenuItemUpdateSerializer(
            data={"available": False, "is_active": True},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data,
            {"available": False, "is_active": True},
        )

    def test_multipart_name_only_patch_does_not_touch_booleans(self):
        query = QueryDict(mutable=True)
        query["name"] = "Updated"
        serializer = MenuItemUpdateSerializer(data=query, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"name": "Updated"})

    def test_create_accepts_independent_available_and_is_active(self):
        query = QueryDict(mutable=True)
        query["branch_id"] = "00000000-0000-0000-0000-000000000001"
        query["category_id"] = "00000000-0000-0000-0000-000000000002"
        query["name"] = "Burger"
        query["price"] = "9.99"
        query["available"] = "false"
        query["is_active"] = "true"
        serializer = MenuItemInputSerializer(data=query)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertFalse(serializer.validated_data["available"])
        self.assertTrue(serializer.validated_data["is_active"])
