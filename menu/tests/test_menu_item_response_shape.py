"""Lock the JSON envelope for public menu item list aliases.

These tests exist because the storefront normalizer calls ``.map()`` on
whatever body it is given. The shapes below are the implementation contract.
"""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from menu.tests.test_item_alias import make_branch, make_category, make_item

PAGINATED_KEYS = {"count", "next", "previous", "results", "tenant"}
ENVELOPE_KEYS = {"tenant", "results"}


class MenuItemResponseShapeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.empty_branch = make_branch()
        self.category = make_category(self.branch)
        self.other_category = make_category(self.branch)
        self.anchor = make_item(self.branch, self.category, name="Anchor")
        self.related_a = make_item(self.branch, self.category, name="Related A")
        self.related_b = make_item(self.branch, self.category, name="Related B")
        self.other_category_item = make_item(
            self.branch, self.other_category, name="Other Category"
        )

    def _json(self, path, params=None):
        response = self.client.get(path, params or {})
        return response, response.json()

    def test_branch_menu_with_multiple_results_is_paginated(self):
        response, body = self._json(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(body, dict)
        self.assertEqual(set(body.keys()), PAGINATED_KEYS)
        self.assertIsInstance(body["results"], list)
        self.assertEqual(body["count"], 4)
        self.assertIsNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertIn("id", body["tenant"])

    def test_branch_menu_with_zero_results_stays_paginated(self):
        response, body = self._json(
            f"/api/menu/items/branches/{self.empty_branch.id}/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), PAGINATED_KEYS)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["results"], [])
        self.assertIsNone(body["next"])
        self.assertIsNone(body["previous"])

    def test_branch_menu_paginates_when_results_exceed_page_size(self):
        for index in range(20):
            make_item(
                self.branch,
                self.category,
                name=f"Extra {index}",
            )

        response, body = self._json(
            f"/api/menu/items/branches/{self.branch.id}/",
            {"page": "1", "page_size": "20"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), PAGINATED_KEYS)
        self.assertEqual(body["count"], 24)
        self.assertEqual(len(body["results"]), 20)
        self.assertIsNotNone(body["next"])
        self.assertIsNone(body["previous"])

        page_two, page_two_body = self._json(
            f"/api/menu/items/branches/{self.branch.id}/",
            {"page": "2", "page_size": "20"},
        )
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual(set(page_two_body.keys()), PAGINATED_KEYS)
        self.assertEqual(len(page_two_body["results"]), 4)
        self.assertIsNone(page_two_body["next"])
        self.assertIsNotNone(page_two_body["previous"])

    def test_branch_menu_shape_is_unchanged_for_authenticated_clients(self):
        self.client.force_authenticate(user=self.branch.tenant.owner.user)
        response, body = self._json(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), PAGINATED_KEYS)
        self.assertIsInstance(body["results"], list)

    def test_related_items_with_multiple_results_is_an_envelope_not_an_array(self):
        response, body = self._json(
            f"/api/menu/items/{self.anchor.id}/related/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(body, dict)
        self.assertNotIsInstance(body, list)
        self.assertEqual(set(body.keys()), ENVELOPE_KEYS)
        self.assertNotIn("count", body)
        self.assertNotIn("next", body)
        self.assertNotIn("previous", body)
        names = {item["name"] for item in body["results"]}
        self.assertEqual(names, {"Related A", "Related B"})
        self.assertNotIn("Anchor", names)
        self.assertNotIn("Other Category", names)

    def test_related_items_with_zero_results_stays_an_envelope(self):
        response, body = self._json(
            f"/api/menu/items/{self.other_category_item.id}/related/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), ENVELOPE_KEYS)
        self.assertEqual(body["results"], [])

    def test_related_items_ignore_pagination_query_params(self):
        response, body = self._json(
            f"/api/menu/items/{self.anchor.id}/related/",
            {
                "branch_id": str(self.branch.id),
                "page": "1",
                "page_size": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), ENVELOPE_KEYS)
        self.assertEqual(len(body["results"]), 2)

    def test_related_missing_branch_is_an_error_object_not_200(self):
        response, body = self._json(f"/api/menu/items/{self.anchor.id}/related/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(body.keys()), {"error"})
        self.assertEqual(body["error"]["code"], "branch_not_found")
        self.assertNotIn("results", body)

    def test_featured_popular_and_search_use_the_same_envelope(self):
        self.anchor.is_featured = True
        self.anchor.is_popular = True
        self.anchor.save(update_fields=["is_featured", "is_popular"])

        cases = [
            (
                "/api/menu/items/featured/",
                {"branch_id": str(self.branch.id)},
            ),
            (
                "/api/menu/items/popular/",
                {"branch_id": str(self.branch.id)},
            ),
            (
                "/api/menu/items/search/",
                {"branch_id": str(self.branch.id), "q": "Anchor"},
            ),
        ]
        for path, params in cases:
            with self.subTest(path=path):
                response, body = self._json(path, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(body.keys()), ENVELOPE_KEYS)
                self.assertIsInstance(body["results"], list)
                self.assertGreaterEqual(len(body["results"]), 1)

    def test_featured_popular_and_search_empty_results_stay_envelopes(self):
        cases = [
            (
                "/api/menu/items/featured/",
                {"branch_id": str(self.empty_branch.id)},
            ),
            (
                "/api/menu/items/popular/",
                {"branch_id": str(self.empty_branch.id)},
            ),
            (
                "/api/menu/items/search/",
                {"branch_id": str(self.empty_branch.id), "q": "missing"},
            ),
        ]
        for path, params in cases:
            with self.subTest(path=path):
                response, body = self._json(path, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(body.keys()), ENVELOPE_KEYS)
                self.assertEqual(body["results"], [])

    def test_browse_featured_path_is_paginated_unlike_the_alias(self):
        self.anchor.is_featured = True
        self.anchor.save(update_fields=["is_featured"])

        alias, alias_body = self._json(
            "/api/menu/items/featured/",
            {"branch_id": str(self.branch.id)},
        )
        browse, browse_body = self._json(
            f"/api/menu/{self.branch.id}/items/featured/",
        )

        self.assertEqual(alias.status_code, 200)
        self.assertEqual(browse.status_code, 200)
        self.assertEqual(set(alias_body.keys()), ENVELOPE_KEYS)
        self.assertEqual(set(browse_body.keys()), PAGINATED_KEYS)
        self.assertEqual(browse_body["count"], 1)
