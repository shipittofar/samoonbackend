from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.db import transaction

from core.exceptions import BranchNotFoundException, TenantNotFoundException
from tenants.api.serializers.response.branding import TenantBrandingSerializer
from tenants.branding import build_tenant_branding, resolve_tenant_image_url
from tenants.selectors import BranchDataAccessLayer, TenantDataAccessLayer
from tenants.selectors.tenant_availability import tenant_is_publicly_listable
from website_builder.selectors import WebsiteBuilderDataAccessLayer
from website_builder.selectors.website_dal import (
    build_default_public_website_response,
    build_layout_response,
    build_public_website_response,
)


tenant_dal = TenantDataAccessLayer()
branch_dal = BranchDataAccessLayer()
website_dal = WebsiteBuilderDataAccessLayer()


class WebsiteBuilderBusinessLogicLayer:
    @staticmethod
    def _get_tenant_dto(tenant_id):
        tenant = tenant_dal.get_tenant_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        return tenant

    @staticmethod
    def _get_tenant_for_write(tenant_id):
        tenant = tenant_dal.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        return tenant

    @staticmethod
    def _get_or_create_layout(tenant_id):
        # Layout create needs an ORM Tenant FK — always load for_update.
        tenant = WebsiteBuilderBusinessLogicLayer._get_tenant_for_write(tenant_id)
        layout = website_dal.get_layout_for_tenant(tenant_id=tenant_id)
        if layout is None:
            layout = website_dal.create_default_layout(tenant=tenant)
        return layout

    @staticmethod
    def get_layout(*, tenant_id: uuid.UUID) -> dict:
        from uploads.services.media_json import resolve_media_tree

        layout = WebsiteBuilderBusinessLogicLayer._get_or_create_layout(tenant_id)
        return resolve_media_tree(build_layout_response(layout))

    @staticmethod
    def _attach_tenant_branding(response: dict, tenant) -> dict:
        branding = build_tenant_branding(tenant)
        response["branding"] = TenantBrandingSerializer(branding).data
        response["image"] = resolve_tenant_image_url(tenant)
        response["tenant"] = {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "is_active": tenant.is_active,
            "status": tenant.status,
        }
        response["is_active"] = tenant.is_active
        response["status"] = tenant.status
        return response

    @staticmethod
    def get_public_website(*, tenant_id: uuid.UUID) -> dict:
        from uploads.services.media_json import resolve_media_tree

        tenant = WebsiteBuilderBusinessLogicLayer._get_tenant_dto(tenant_id)
        if not tenant_is_publicly_listable(tenant):
            raise TenantNotFoundException()
        layout = website_dal.get_layout_for_tenant(tenant_id=tenant.id)
        if layout is None:
            response = build_default_public_website_response()
        else:
            branch_overrides = website_dal.get_all_branch_overrides(layout=layout)
            response = build_public_website_response(
                layout=layout,
                branch_overrides=branch_overrides,
            )
        return WebsiteBuilderBusinessLogicLayer._attach_tenant_branding(
            resolve_media_tree(response), tenant
        )

    @staticmethod
    @transaction.atomic
    def save_layout(*, tenant_id: uuid.UUID, layout_data: dict) -> dict:
        from uploads.services.media_json import resolve_media_tree, sanitize_media_tree

        layout_data = sanitize_media_tree(layout_data, tenant_id=tenant_id)
        layout = WebsiteBuilderBusinessLogicLayer._get_or_create_layout(tenant_id)
        saved_at = datetime.now(timezone.utc)
        layout = website_dal.save_layout(
            layout=layout,
            layout_data=layout_data,
            saved_at=saved_at,
        )
        return resolve_media_tree(build_layout_response(layout))

    @staticmethod
    def get_branch_overrides(*, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> dict:
        tenant = WebsiteBuilderBusinessLogicLayer._get_tenant_dto(tenant_id)
        branch = branch_dal.get_branch_by_id(branch_id)
        if not branch or branch.tenant_id != tenant.id:
            raise BranchNotFoundException()

        layout = WebsiteBuilderBusinessLogicLayer._get_or_create_layout(tenant_id)
        override = website_dal.get_branch_override(layout=layout, branch_id=branch_id)
        if override is None:
            return {}
        from uploads.services.media_json import resolve_media_tree

        return resolve_media_tree(override.override_data or {})

    @staticmethod
    @transaction.atomic
    def save_branch_overrides(
        *, tenant_id: uuid.UUID, branch_id: uuid.UUID, override_data: dict
    ) -> dict:
        from uploads.services.media_json import resolve_media_tree, sanitize_media_tree

        tenant = WebsiteBuilderBusinessLogicLayer._get_tenant_for_write(tenant_id)
        branch = branch_dal.get_branch_for_update(branch_id)
        if not branch or branch.tenant_id != tenant.id:
            raise BranchNotFoundException()

        layout = WebsiteBuilderBusinessLogicLayer._get_or_create_layout(tenant_id)
        override_data = sanitize_media_tree(override_data, tenant_id=tenant_id)
        override = website_dal.save_branch_override(
            layout=layout,
            branch=branch,
            override_data=override_data,
        )
        return resolve_media_tree(override.override_data or {})

    @staticmethod
    def upload_media(*, tenant_id: uuid.UUID, uploaded_file, user) -> dict:
        from uploads.services.ingest import ingest_uploaded_file

        WebsiteBuilderBusinessLogicLayer._get_tenant_dto(tenant_id)
        asset = ingest_uploaded_file(
            user=user,
            uploaded_file=uploaded_file,
            purpose="website_media",
            tenant_id=tenant_id,
            entity_type="tenant",
            entity_id=str(tenant_id),
        )
        return {"url": asset.public_url() or "", "asset_id": asset.id}
