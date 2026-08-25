"""D5 — tenant/branch DTO cache + for_update split."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from access.tests.helpers import make_branch, make_tenant, make_user
from core.cache import CacheKeys, CacheTTL
from tenants.dto import BranchDTO, TenantDiscoverDTO, TenantDTO
from tenants.models import Tenant
from tenants.selectors.tenant_dal import BranchDataAccessLayer, TenantDataAccessLayer
from tenants.services.tenant_bll import (
    BranchBusinessLogicLayer,
    TenantBusinessLogicLayer,
    _assert_owns_branch,
    _assert_owns_tenant,
)
from core.exceptions import (
    BranchPermissionDeniedException,
    TenantPermissionDeniedException,
)


class TenantBranchDtoCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner_user, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="DTO Branch")

    def tearDown(self):
        cache.clear()

    def test_get_tenant_by_id_returns_dto_not_model(self):
        dto = TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        self.assertIsInstance(dto, TenantDTO)
        self.assertNotIsInstance(dto, Tenant)
        self.assertEqual(dto.owner_user_id, self.owner_user.id)
        self.assertEqual(dto.name, self.tenant.name)

        raw = cache.get(CacheKeys.TENANT_DETAIL.format(tenant_id=self.tenant.id))
        self.assertIsInstance(raw, dict)
        self.assertEqual(raw["id"], self.tenant.id)

    def test_tenant_ttl_is_safety_net_range(self):
        self.assertGreaterEqual(CacheTTL.TENANT, 5 * 60)
        self.assertLessEqual(CacheTTL.TENANT, 15 * 60)
        self.assertEqual(CacheTTL.TENANT, CacheTTL.BRANCH)

    def test_cache_miss_rebuilds_dto_from_db(self):
        cache.clear()
        dto = TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        self.assertIsInstance(dto, TenantDTO)
        self.assertEqual(dto.id, self.tenant.id)

    def test_get_tenant_for_update_bypasses_cache(self):
        TenantDataAccessLayer._refresh_tenant_detail_cache(self.tenant.id)
        key = CacheKeys.TENANT_DETAIL.format(tenant_id=self.tenant.id)
        cache.set(key, {"id": self.tenant.id, "name": "STALE"}, timeout=60)

        model = TenantDataAccessLayer.get_tenant_for_update(self.tenant.id)
        self.assertIsInstance(model, Tenant)
        self.assertEqual(model.name, self.tenant.name)
        self.assertEqual(model.owner_user_id, self.owner_user.id)
        # Cache left untouched by for_update
        self.assertEqual(cache.get(key)["name"], "STALE")

    def test_get_branch_by_id_returns_dto(self):
        dto = BranchDataAccessLayer.get_branch_by_id(
            self.branch.id, tenant_id=self.tenant.id
        )
        self.assertIsInstance(dto, BranchDTO)
        self.assertEqual(dto.tenant_id, self.tenant.id)
        self.assertEqual(dto.owner_user_id, self.owner_user.id)

    def test_get_branch_for_update_bypasses_cache(self):
        BranchDataAccessLayer._refresh_branch_detail_cache(
            self.branch.id, self.tenant.id
        )
        key = CacheKeys.BRANCH_DETAIL.format(
            tenant_id=self.tenant.id, branch_id=self.branch.id
        )
        cache.set(key, {"id": self.branch.id, "name": "STALE"}, timeout=60)

        model = BranchDataAccessLayer.get_branch_for_update(
            self.branch.id, tenant_id=self.tenant.id
        )
        self.assertEqual(model.name, self.branch.name)
        self.assertEqual(cache.get(key)["name"], "STALE")

    def test_ownership_helpers_use_flat_fields(self):
        dto = TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        _assert_owns_tenant(self.owner_user, dto)

        other = make_user()
        with self.assertRaises(TenantPermissionDeniedException):
            _assert_owns_tenant(other, dto)

        branch_dto = BranchDataAccessLayer.get_branch_by_id(
            self.branch.id, tenant_id=self.tenant.id
        )
        _assert_owns_branch(self.owner_user, branch_dto)
        with self.assertRaises(BranchPermissionDeniedException):
            _assert_owns_branch(other, branch_dto)

    def test_update_tenant_uses_for_update_and_refreshes_dto_cache(self):
        TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        with self.captureOnCommitCallbacks(execute=True):
            TenantBusinessLogicLayer.update_tenant(
                self.owner_user,
                self.tenant.id,
                name="Renamed",
                status=self.tenant.status,
            )
        dto = TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        self.assertEqual(dto.name, "Renamed")

    def test_create_and_inactive_branch_write_paths(self):
        with self.captureOnCommitCallbacks(execute=True):
            branch = BranchBusinessLogicLayer.create_branch(
                self.owner_user,
                self.tenant.id,
                name="New Branch",
            )
        self.assertIsNotNone(
            BranchDataAccessLayer.get_branch_by_id(branch.id, tenant_id=self.tenant.id)
        )
        with self.captureOnCommitCallbacks(execute=True):
            BranchBusinessLogicLayer.delete_branch(
                self.owner_user, self.tenant.id, branch.id
            )
        dto = BranchDataAccessLayer.get_branch_by_id(
            branch.id, tenant_id=self.tenant.id
        )
        self.assertFalse(dto.is_active)

    def test_discover_list_caches_nested_dto(self):
        cache.clear()
        rows = TenantDataAccessLayer.get_discover_tenants()
        self.assertTrue(rows)
        self.assertIsInstance(rows[0], TenantDiscoverDTO)
        raw = cache.get(CacheKeys.DISCOVER_LIST)
        self.assertIsInstance(raw, list)
        self.assertIsInstance(raw[0], dict)
        self.assertIn("branches", raw[0])
        self.assertIn("business_types", raw[0])

    def test_tenant_dto_from_cache_dict_defaults_is_active_false(self):
        payload = TenantDTO.from_model(
            TenantDataAccessLayer.get_tenant_for_update(self.tenant.id)
        ).to_cache_dict()
        payload.pop("is_active", None)
        dto = TenantDTO.from_cache_dict(payload)
        self.assertFalse(dto.is_active)

    def test_tenant_discover_dto_from_cache_dict_defaults_visibility_fields(self):
        payload = TenantDiscoverDTO.from_model(
            TenantDataAccessLayer.get_tenant_for_update(self.tenant.id)
        ).to_cache_dict()
        payload.pop("is_active", None)
        payload.pop("status", None)
        dto = TenantDiscoverDTO.from_cache_dict(payload)
        self.assertFalse(dto.is_active)
        self.assertEqual(dto.status, "inactive")

    def test_branch_dto_from_cache_dict_defaults_tenant_state_false(self):
        payload = BranchDTO.from_model(
            BranchDataAccessLayer.get_branch_for_update(self.branch.id, self.tenant.id)
        ).to_cache_dict()
        payload.pop("tenant_is_active", None)
        payload.pop("tenant_status", None)
        dto = BranchDTO.from_cache_dict(payload)
        self.assertFalse(dto.tenant_is_active)
        self.assertEqual(dto.tenant_status, "inactive")
