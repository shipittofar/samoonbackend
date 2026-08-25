"""API tests for POST /api/branches/console-branches/tenants/{tenant_id}/create/."""
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, Owner, Tenant, WorkingHour


CREATE_URL = "/api/branches/console-branches/tenants/{tenant_id}/create/"

FRONTEND_PAYLOAD = {
    "name": "wwe",
    "slug": "e",
    "description": "w",
    "type": "physical",
    "location": {
        "address": "w",
        "city": "w",
        "country": "w",
    },
    "contact": {},
    "businessHours": [
        {
            "day": "Monday",
            "open": "09:00",
            "close": "22:00",
            "isClosed": False,
        }
    ],
    "deliveryEnabled": False,
    "pickupEnabled": True,
    "tableOrderingEnabled": False,
    "reservationsEnabled": False,
    "orderingEnabled": True,
    "marketplaceVisible": True,
    "isDefault": False,
}


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class BranchConsoleCreateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.client.force_authenticate(user=self.owner_user)
        self.url = CREATE_URL.format(tenant_id=self.tenant.id)

    def test_create_persists_frontend_nested_payload(self):
        response = self.client.post(self.url, FRONTEND_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(data["name"], "wwe")
        self.assertEqual(data["description"], "w")
        self.assertEqual(data["location"]["address"], "w")
        self.assertEqual(data["location"]["city"], "w")
        self.assertEqual(data["location"]["country"], "w")
        self.assertEqual(len(data["businessHours"]), 1)
        self.assertEqual(data["businessHours"][0]["day"], "Monday")
        self.assertEqual(data["businessHours"][0]["open"], "09:00")
        self.assertEqual(data["businessHours"][0]["close"], "22:00")
        self.assertFalse(data["businessHours"][0]["isClosed"])
        self.assertNotEqual(data["slug"], "e")

        branch = Branch.objects.get(id=data["id"])
        self.assertEqual(branch.description, "w")
        self.assertEqual(branch.address, "w")
        self.assertEqual(branch.city, "w")
        self.assertEqual(branch.country, "w")
        self.assertTrue(branch.slug)

        working_hours = list(branch.working_hours.order_by("day"))
        self.assertEqual(len(working_hours), 1)
        self.assertEqual(working_hours[0].day, WorkingHour.Weekday.MONDAY)
        self.assertEqual(
            working_hours[0].open_time.strftime("%H:%M"), "09:00"
        )
        self.assertEqual(
            working_hours[0].close_time.strftime("%H:%M"), "22:00"
        )
        self.assertFalse(working_hours[0].is_closed)

        self.assertFalse(data["deliveryEnabled"])
        self.assertTrue(data["pickupEnabled"])
        self.assertFalse(data["tableOrderingEnabled"])
        self.assertTrue(data["orderingEnabled"])
        self.assertTrue(data["marketplaceVisible"])
        self.assertFalse(branch.delivery_enabled)
        self.assertTrue(branch.pickup_enabled)
        self.assertTrue(branch.marketplace_visible)

    def test_create_ignores_frontend_slug(self):
        response = self.client.post(self.url, FRONTEND_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.json()["slug"], "e")

    def test_invalid_business_hours_day_returns_validation_error(self):
        payload = {
            **FRONTEND_PAYLOAD,
            "businessHours": [
                {
                    "day": "NotADay",
                    "open": "09:00",
                    "close": "22:00",
                    "isClosed": False,
                }
            ],
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("businessHours", response.json())

    def test_invalid_contact_email_returns_validation_error(self):
        payload = {
            **FRONTEND_PAYLOAD,
            "contact": {"email": "not-an-email"},
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contact", response.json())

    def test_legacy_flat_create_payload_still_works(self):
        payload = {
            "name": "Legacy Branch",
            "description": "legacy desc",
            "type": "physical",
            "address": "123 Main",
            "city": "NYC",
            "country": "US",
            "phone": "+15551234567",
            "email": "branch@example.com",
            "working_hours": [
                {
                    "day": WorkingHour.Weekday.TUESDAY,
                    "open_time": "10:00",
                    "close_time": "18:00",
                    "is_closed": False,
                }
            ],
            "is_default": True,
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["description"], "legacy desc")
        self.assertEqual(data["location"]["address"], "123 Main")
        self.assertEqual(data["location"]["city"], "NYC")
        self.assertEqual(data["contact"]["phone_number"], "+15551234567")
        self.assertEqual(data["contact"]["email"], "branch@example.com")
        self.assertEqual(data["businessHours"][0]["day"], "Tuesday")
        self.assertTrue(data["isDefault"])
