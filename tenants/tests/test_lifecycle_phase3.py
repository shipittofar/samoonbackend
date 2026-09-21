"""Phase 3 user soft-delete and branch/QR deactivation."""
import uuid

from django.test import TestCase

from accounts.models import User
from accounts.services.profile_bll import ProfileBusinessLogicLayer
from tenants.admin.qr import QrCodeAdmin
from tenants.admin.tenant import BranchAdmin
from tenants.models import Branch, BranchStatus, Owner, QrCode, QrEntityType, Tenant
from tenants.services.qr_bll import QrCodeBusinessLogicLayer
from tenants.services.tenant_bll import BranchBusinessLogicLayer


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
        "is_staff": True,
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


class UserLifecycleTests(TestCase):
    def test_soft_delete_hides_from_default_manager(self):
        user = make_user()
        user.set_password("secret123")
        user.save(update_fields=["password"])
        ProfileBusinessLogicLayer.soft_delete(user)
        stored = User.all_objects.get(id=user.id)
        self.assertTrue(stored.is_deleted)
        self.assertFalse(stored.is_active)
        self.assertIsNotNone(stored.deleted_at)
        self.assertFalse(User.objects.filter(id=user.id).exists())
        from accounts.services.auth_service import PasswordAuthBusinessLogicLayer
        from core.exceptions.account import InvalidCredentialsException, UserInactiveException

        with self.assertRaises((InvalidCredentialsException, UserInactiveException)):
            PasswordAuthBusinessLogicLayer.login(
                identifier=user.phone_number,
                is_email=False,
                password="secret123",
            )


class BranchQrLifecycleTests(TestCase):
    def setUp(self):
        self.owner_user = make_user()
        owner = Owner.objects.create(user=self.owner_user)
        self.tenant = Tenant.objects.create(owner=owner, name=f"T{uuid.uuid4().hex[:6]}")
        self.branch = Branch.objects.create(
            tenant=self.tenant, name="Main", status=BranchStatus.ACTIVE, is_active=True
        )

    def test_branch_deactivate_keeps_row(self):
        BranchBusinessLogicLayer.delete_branch(
            user=self.owner_user,
            tenant_id=self.tenant.id,
            branch_id=self.branch.id,
        )
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.status, BranchStatus.INACTIVE)
        self.assertFalse(self.branch.is_active)
        self.assertTrue(Branch.objects.filter(id=self.branch.id).exists())
        request = type("R", (), {"user": self.owner_user})()
        self.assertFalse(BranchAdmin(Branch, None).has_delete_permission(request, self.branch))

    def test_qr_disable_regenerate_keeps_old_row(self):
        qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH,
            entity_id=self.branch.id,
            is_active=True,
        )
        QrCodeBusinessLogicLayer.disable(self.owner_user, qr)
        QrCodeBusinessLogicLayer.disable(self.owner_user, qr)
        qr.refresh_from_db()
        self.assertFalse(qr.is_active)
        self.assertTrue(QrCode.objects.filter(id=qr.id).exists())

        qr.is_active = True
        qr.save(update_fields=["is_active"])
        new_qr = QrCodeBusinessLogicLayer.regenerate(self.owner_user, qr)
        qr.refresh_from_db()
        self.assertFalse(qr.is_active)
        self.assertTrue(new_qr.is_active)
        self.assertNotEqual(new_qr.id, qr.id)
        self.assertTrue(QrCode.objects.filter(id=qr.id).exists())
        request = type("R", (), {"user": self.owner_user})()
        self.assertFalse(QrCodeAdmin(QrCode, None).has_delete_permission(request, qr))
