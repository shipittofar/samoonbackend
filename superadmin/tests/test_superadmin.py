from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from access.tests.helpers import make_branch, make_tenant, make_user
from menu.models import MenuItem, MenuTemplate
from tenants.models import BusinessRequest, Tenant

CONTENT = {"categories": [{"name": "Coffee", "items": [{"name": "Latte", "price": "3.5"}]}]}


class SuperadminFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.root = make_user(is_superuser=True, is_staff=True)
        self.client = APIClient()

    def test_request_approve_creates_business_and_console(self):
        applicant = make_user()
        self.client.force_authenticate(applicant)
        self.assertEqual(self.client.post("/api/tenants/create/", {"name": "X"}, format="json").status_code, 403)
        r = self.client.post("/api/tenants/business-requests/", {
            "name": "Cafe Sara", "business_type": "cafe", "city": "Tehran",
            "latitude": "35.7", "longitude": "51.4"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.client.force_authenticate(self.root)
        ok = self.client.post(f"/api/superadmin/business-requests/{r.json()['id']}/approve/")
        self.assertEqual(ok.status_code, 200, ok.content)
        tenant = Tenant.objects.get(name="Cafe Sara")
        self.assertEqual(tenant.owner.user, applicant)
        self.assertEqual(tenant.branches.first().city, "Tehran")
        self.client.force_authenticate(applicant)
        me = self.client.get("/api/auth/me/").json()
        self.assertEqual(me["user"]["accountType"], "business")

    def test_superuser_search_detail_and_open_any_business(self):
        _, tenant = make_tenant()
        make_branch(tenant)
        self.client.force_authenticate(self.root)
        self.assertEqual(self.client.get("/api/superadmin/tenants/", {"search": tenant.name[:4]}).json()["count"], 1)
        self.assertEqual(self.client.get(f"/api/superadmin/tenants/{tenant.id}/").status_code, 200)
        self.assertEqual(self.client.post("/api/authorization/switch-tenant/", {"tenantId": str(tenant.id)}, format="json").status_code, 204)
        me = self.client.get("/api/auth/me/").json()
        self.assertEqual(me["user"]["accountType"], "business")
        self.assertTrue(any(m["platformAccess"] for m in me["memberships"]))
        staff = make_user(is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get("/api/superadmin/tenants/").status_code, 403)

    def test_templates_created_by_superuser_applied_by_owner(self):
        owner_user, tenant = make_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(business_types=["cafe"])
        branch = make_branch(tenant)
        self.client.force_authenticate(self.root)
        t = self.client.post("/api/superadmin/menu-templates/", {
            "name": "Basic cafe", "business_type": "cafe", "content": CONTENT}, format="json")
        self.assertEqual(t.status_code, 201, t.content)
        self.client.force_authenticate(owner_user)
        listed = self.client.get(f"/api/menu/branches/{branch.id}/templates/").json()
        self.assertEqual(len(listed), 1)
        url = f"/api/menu/branches/{branch.id}/templates/{t.json()['id']}/apply/"
        self.assertEqual(self.client.post(url).json()["created_items"], 1)
        self.assertEqual(self.client.post(url).json()["skipped_items"], 1)
        self.assertEqual(MenuItem.all_objects.filter(branch=branch, name="Latte").count(), 1)


class SuperadminRulesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.root = make_user(is_superuser=True, is_staff=True)
        self.client = APIClient()

    def file(self, user, name="Pizza"):
        self.client.force_authenticate(user)
        return self.client.post(
            "/api/tenants/business-requests/", {"name": name, "business_type": "restaurant"}, format="json"
        )

    def test_one_pending_request_and_reject_with_reason(self):
        applicant = make_user()
        first = self.file(applicant)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.file(applicant, "Again").status_code, 400)

        self.client.force_authenticate(self.root)
        rejected = self.client.post(
            f"/api/superadmin/business-requests/{first.json()['id']}/reject/", {"reason": "No address"}, format="json"
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(
            self.client.post(f"/api/superadmin/business-requests/{first.json()['id']}/approve/").status_code, 400
        )

        self.client.force_authenticate(applicant)
        mine = self.client.get("/api/tenants/business-requests/").json()
        self.assertEqual(mine[0]["status"], "rejected")
        self.assertEqual(mine[0]["rejection_reason"], "No address")
        self.assertEqual(self.client.get("/api/auth/me/").json()["user"]["accountType"], "customer")
        # after a rejection a new request may be filed
        self.assertEqual(self.file(applicant, "Second try").status_code, 201)

    def test_only_superusers_review_and_manage_templates(self):
        applicant = make_user()
        request_id = self.file(applicant).json()["id"]
        owner_user, tenant = make_tenant()
        for user in (applicant, owner_user, make_user(is_staff=True)):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(f"/api/superadmin/business-requests/{request_id}/approve/").status_code, 403)
            self.assertEqual(self.client.get("/api/superadmin/menu-templates/").status_code, 403)
            self.assertEqual(self.client.get("/api/superadmin/overview/").status_code, 403)

    def test_template_content_is_validated_and_others_cannot_apply(self):
        self.client.force_authenticate(self.root)
        bad = self.client.post("/api/superadmin/menu-templates/", {
            "name": "Bad", "business_type": "cafe",
            "content": {"categories": [{"name": "A", "items": [{"name": "X", "price": "abc"}]}]}}, format="json")
        self.assertEqual(bad.status_code, 400)
        template = MenuTemplate.objects.create(name="T", business_type="cafe", content=CONTENT)
        _, tenant = make_tenant()
        branch = make_branch(tenant)
        stranger = make_user()
        self.client.force_authenticate(stranger)
        self.assertEqual(
            self.client.post(f"/api/menu/branches/{branch.id}/templates/{template.id}/apply/").status_code, 403
        )
        self.assertFalse(MenuItem.all_objects.filter(branch=branch).exists())
