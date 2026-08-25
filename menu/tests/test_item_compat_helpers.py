"""Unit tests for MenuItem computed-field helpers (no database required)."""

from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone

from menu.api.serializers.response.item import MenuItemOutputSerializer
from menu.utils.item_compat import (
    build_nutritional_info,
    compute_discounted_price,
    compute_is_new,
    compute_rating,
    compute_rating_count,
)


class MenuItemCompatHelperTests(SimpleTestCase):
    def test_discounted_price_percentage(self):
        self.assertEqual(
            compute_discounted_price(Decimal("24.99"), Decimal("10")),
            Decimal("22.49"),
        )
        self.assertIsNone(compute_discounted_price(Decimal("10.00"), Decimal("0")))

    def test_is_new_within_window(self):
        recent = timezone.now() - timedelta(days=3)
        old = timezone.now() - timedelta(days=90)
        self.assertTrue(compute_is_new(recent))
        self.assertFalse(compute_is_new(old))

    def test_rating_placeholders(self):
        self.assertEqual(compute_rating(), Decimal("0.00"))
        self.assertEqual(compute_rating_count(), 0)

    def test_nutritional_info_from_calories(self):
        self.assertIsNone(build_nutritional_info(None))
        self.assertEqual(
            build_nutritional_info(850),
            {"calories": 850, "protein": 0, "carbs": 0, "fat": 0},
        )


class MenuItemOutputSerializerTests(SimpleTestCase):
    def test_serializes_without_get_discounted_price_regression(self):
        class Fake:
            id = "00000000-0000-0000-0000-000000000001"
            branch_id = "00000000-0000-0000-0000-000000000002"
            category_id = "00000000-0000-0000-0000-000000000003"
            category = None
            name = "Test"
            slug = "test"
            description = ""
            price = Decimal("10.00")
            discount = Decimal("10")
            image = None
            calories = None
            preparation_time = None
            is_active = True
            available = False
            is_popular = False
            is_featured = False
            created_at = timezone.now()
            updated_at = timezone.now()
            _prefetched_objects_cache = {}

            @property
            def tags(self):
                return []

            @property
            def item_extra_groups(self):
                return type(
                    "QS",
                    (),
                    {"values_list": lambda *args, **kwargs: []},
                )()

            @property
            def item_extras(self):
                class ExtrasQS:
                    def select_related(self, *args, **kwargs):
                        return self

                    def all(self):
                        return []

                return ExtrasQS()

        data = MenuItemOutputSerializer(Fake()).data
        self.assertTrue(data["is_active"])
        self.assertFalse(data["available"])
        self.assertEqual(str(data["discounted_price"]), "9.00")
