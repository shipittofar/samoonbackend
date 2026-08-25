"""Regression tests for tenants admin forms."""
import uuid

from django import forms
from django.test import TestCase

from accounts.models import User
from tenants.admin.tenant import WorkingHourForm
from tenants.models import Branch, Owner, Tenant, WorkingHour


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


class WorkingHourFormTests(TestCase):
    def setUp(self):
        owner = Owner.objects.create(user=make_user())
        self.tenant = Tenant.objects.create(owner=owner, name="Test Tenant")
        self.saved_branch = Branch.objects.create(
            tenant=self.tenant,
            name="Saved Branch",
        )

    def test_clean_allows_unsaved_branch_on_add(self):
        """Branch add + WorkingHourInline: parent branch has pk=None during clean()."""
        unsaved_branch = Branch(tenant=self.tenant, name="New Branch")
        form = WorkingHourForm()
        form.cleaned_data = {
            "branch": unsaved_branch,
            "day": WorkingHour.Weekday.MONDAY,
            "open_time": "09:00",
            "close_time": "17:00",
            "is_closed": False,
        }

        try:
            form.clean()
        except ValueError as exc:
            self.fail(f"clean() must not query with an unsaved branch: {exc}")

    def test_clean_enforces_max_hours_for_saved_branch(self):
        for day in range(7):
            WorkingHour.objects.create(
                branch=self.saved_branch,
                day=day,
                is_closed=True,
            )

        form = WorkingHourForm()
        form.cleaned_data = {
            "branch": self.saved_branch,
            "day": WorkingHour.Weekday.MONDAY,
            "open_time": "09:00",
            "close_time": "17:00",
            "is_closed": False,
        }

        with self.assertRaises(forms.ValidationError):
            form.clean()
