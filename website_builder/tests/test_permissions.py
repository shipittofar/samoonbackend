"""Permission coverage tests for Website Builder endpoints."""
import copy
import tempfile
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from access.models import (
    Permission,
    Role,
    RolePermission,
    StaffMembership,
    StaffMembershipStatus,
)
from access.tests.helpers import create_canonical_assignment
from accounts.models import User
from tenants.models import Branch, Owner, Tenant
from website_builder.tests.test_website_builder import (
    BRANCH_OVERRIDE_PAYLOAD,
    FULL_LAYOUT_PAYLOAD,
    LAYOUT_URL,
    MEDIA_URL,
    OVERRIDES_URL,
    make_branch,
    make_tenant_with_owner,
    make_user,
)


def ensure_role(slug: str) -> Role:
    role, _ = Role.objects.get_or_create(
        slug=slug,
        defaults={"name": slug.title(), "system_role": True},
    )
    return role


def ensure_permission(slug: str, *, resource: str, action: str) -> Permission:
    permission, _ = Permission.objects.get_or_create(
        slug=slug,
        defaults={"resource": resource, "action": action},
    )
    return permission


def grant_role_permission(role: Role, permission: Permission) -> None:
    RolePermission.objects.get_or_create(role=role, permission=permission)


def make_staff_assignment(*, user, tenant, role_slug="manager"):
    role = ensure_role(role_slug)
    permission = ensure_permission(
        "settings.view",
        resource="settings",
        action="view",
    )
    grant_role_permission(role, permission)

    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    create_canonical_assignment(
        membership=membership,
        role=role,
        all_locations=True,
    )
    return membership


class WebsiteBuilderOwnerPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.client.force_authenticate(user=self.owner_user)
        self.layout_url = LAYOUT_URL.format(tenant_id=self.tenant.id)
        self.overrides_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.branch.id,
        )
        self.media_url = MEDIA_URL.format(tenant_id=self.tenant.id)

    def test_owner_can_get_layout(self):
        response = self.client.get(self.layout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_put_layout(self):
        response = self.client.put(
            self.layout_url,
            copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_get_overrides(self):
        response = self.client.get(self.overrides_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_put_overrides(self):
        response = self.client.put(
            self.overrides_url,
            copy.deepcopy(BRANCH_OVERRIDE_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        },
        MEDIA_ROOT=tempfile.mkdtemp(),
    )
    def test_owner_can_post_media(self):
        upload = SimpleUploadedFile(
            "hero.png",
            b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
        )
        response = self.client.post(
            self.media_url,
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class WebsiteBuilderStaffPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.staff_user = make_user()
        make_staff_assignment(user=self.staff_user, tenant=self.tenant, role_slug="manager")
        self.client.force_authenticate(user=self.staff_user)
        self.layout_url = LAYOUT_URL.format(tenant_id=self.tenant.id)
        self.overrides_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.branch.id,
        )

    def test_staff_with_settings_view_can_get_layout(self):
        response = self.client.get(self.layout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_staff_with_settings_view_can_put_layout(self):
        response = self.client.put(
            self.layout_url,
            copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_staff_with_settings_view_can_get_overrides(self):
        response = self.client.get(self.overrides_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_staff_with_settings_view_can_put_overrides(self):
        response = self.client.put(
            self.overrides_url,
            copy.deepcopy(BRANCH_OVERRIDE_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class WebsiteBuilderUnauthorizedPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.other_user, self.other_tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.unauthorized_user = make_user()
        waiter_role = ensure_role("waiter")
        membership = StaffMembership.objects.create(
            user=self.unauthorized_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        create_canonical_assignment(
            membership=membership,
            role=waiter_role,
            all_locations=True,
        )
        self.client.force_authenticate(user=self.unauthorized_user)
        self.layout_url = LAYOUT_URL.format(tenant_id=self.tenant.id)
        self.other_tenant_layout_url = LAYOUT_URL.format(tenant_id=self.other_tenant.id)
        self.overrides_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.branch.id,
        )

    def test_staff_without_permission_can_get_layout(self):
        response = self.client.get(self.layout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_staff_without_permission_gets_403_on_layout_put(self):
        response = self.client.put(
            self.layout_url,
            copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_without_permission_gets_403_on_overrides(self):
        response = self.client.get(self.overrides_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_owner_without_permission_gets_403_on_other_tenant_layout(self):
        response = self.client.put(
            self.other_tenant_layout_url,
            copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class WebsiteLayoutPublicAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _, self.tenant = make_tenant_with_owner()
        self.layout_url = LAYOUT_URL.format(tenant_id=self.tenant.id)

    def test_unauthenticated_get_layout_succeeds(self):
        response = self.client.get(self.layout_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("sections", response.data)

    def test_unauthenticated_put_layout_is_forbidden(self):
        response = self.client.put(
            self.layout_url,
            copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
