from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from core.exceptions.qr import (
    QrAlreadyExistsException,
    QrDisabledException,
    QrInvalidDestinationException,
    QrNotFoundException,
    UnauthorizedQrAccessException,
)
from core.exceptions.tenant import (
    BranchNotFoundException,
    BranchPermissionDeniedException,
    TenantNotFoundException,
    TenantPermissionDeniedException,
)
from core.utils.slug import DEFAULT_SLUG_LENGTH, generate_random_slug
from tenants.models import Branch, BranchStatus, Tenant
from tenants.models.qr_code import QrCode, QrDestinationType, QrEntityType
from tenants.selectors import qr_dal
from tenants.selectors.tenant_availability import (
    tenant_is_operationally_available,
)
from tenants.services.public_url import absolute_public_url, destination_path
from tenants.services.tenant_bll import _assert_owns_branch, _assert_owns_tenant

logger = logging.getLogger(__name__)

MAX_CODE_ATTEMPTS = 12


def _default_destination(entity_type: str) -> str:
    if entity_type == QrEntityType.TENANT:
        return QrDestinationType.TENANT
    return QrDestinationType.BRANCH


class QrCodeBusinessLogicLayer:

    @staticmethod
    def ensure_for_tenant(tenant: Tenant) -> QrCode:
        return QrCodeBusinessLogicLayer._ensure(
            entity_type=QrEntityType.TENANT,
            entity_id=tenant.id,
            destination_type=QrDestinationType.TENANT,
        )

    @staticmethod
    def ensure_for_branch(branch: Branch) -> QrCode:
        return QrCodeBusinessLogicLayer._ensure(
            entity_type=QrEntityType.BRANCH,
            entity_id=branch.id,
            destination_type=QrDestinationType.BRANCH,
        )

    @staticmethod
    def attach_after_save(instance) -> None:
        if instance is None or getattr(instance, "pk", None) is None:
            return
        if isinstance(instance, Tenant):
            QrCodeBusinessLogicLayer.ensure_for_tenant(instance)
        elif isinstance(instance, Branch):
            QrCodeBusinessLogicLayer.ensure_for_branch(instance)

    @staticmethod
    def _ensure(*, entity_type: str, entity_id, destination_type: str) -> QrCode:
        existing = qr_dal.get_active_for_entity(entity_type, entity_id)
        if existing is not None:
            return existing
        try:
            return QrCodeBusinessLogicLayer._create(
                entity_type=entity_type,
                entity_id=entity_id,
                destination_type=destination_type,
            )
        except QrAlreadyExistsException:
            existing = qr_dal.get_active_for_entity(entity_type, entity_id)
            if existing is not None:
                return existing
            raise

    @staticmethod
    def _create(*, entity_type: str, entity_id, destination_type: str) -> QrCode:
        last_error: IntegrityError | None = None
        for _ in range(MAX_CODE_ATTEMPTS):
            code = generate_random_slug(DEFAULT_SLUG_LENGTH)
            try:
                with transaction.atomic():
                    return QrCode.objects.create(
                        code=code,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        destination_type=destination_type,
                        is_active=True,
                    )
            except IntegrityError as exc:
                last_error = exc
                if qr_dal.get_active_for_entity(entity_type, entity_id) is not None:
                    raise QrAlreadyExistsException() from exc
                continue
        raise IntegrityError("Unable to allocate a unique QR code") from last_error

    @staticmethod
    def active_code_for(obj) -> str | None:
        annotated = getattr(obj, "qr_code", None)
        if annotated:
            return annotated
        entity_type, entity_id = QrCodeBusinessLogicLayer._entity_from_obj(obj)
        if entity_type is None or entity_id is None:
            return None
        qr = qr_dal.get_active_for_entity(entity_type, entity_id)
        return qr.code if qr is not None else None

    @staticmethod
    def _entity_from_obj(obj) -> tuple[str | None, object | None]:
        if obj is None:
            return None, None
        class_name = type(obj).__name__
        if isinstance(obj, Tenant) or class_name in {"TenantDTO", "TenantDiscoverDTO"}:
            return QrEntityType.TENANT, obj.id
        if isinstance(obj, Branch) or class_name in {"BranchDTO", "BranchDiscoverDTO"}:
            return QrEntityType.BRANCH, obj.id
        if getattr(obj, "tenant_id", None) is not None:
            return QrEntityType.BRANCH, getattr(obj, "id", None)
        return QrEntityType.TENANT, getattr(obj, "id", None)

    @staticmethod
    def resolve_redirect_url(code: str) -> str:
        qr = qr_dal.get_by_code(code)
        if qr is None:
            logger.info("qr.resolve not_found")
            raise QrNotFoundException()
        if not qr.is_active:
            logger.info("qr.resolve disabled")
            raise QrDisabledException()

        tenant, branch = QrCodeBusinessLogicLayer._load_entities(qr)
        dest_type = qr.destination_type or _default_destination(qr.entity_type)
        path = destination_path(
            dest_type,
            tenant_slug=tenant.slug,
            branch_slug=branch.slug if branch is not None else None,
        )
        logger.info(
            "qr.resolve ok entity_type=%s destination_type=%s",
            qr.entity_type,
            dest_type,
        )
        return absolute_public_url(path)

    @staticmethod
    def _load_entities(qr: QrCode) -> tuple[Tenant, Branch | None]:
        if qr.entity_type == QrEntityType.TENANT:
            tenant = Tenant.objects.filter(id=qr.entity_id).first()
            if tenant is None or not tenant_is_operationally_available(tenant):
                logger.info("qr.resolve tenant_unavailable")
                raise TenantNotFoundException()
            return tenant, None

        if qr.entity_type == QrEntityType.BRANCH:
            branch = (
                Branch.objects.select_related("tenant")
                .filter(id=qr.entity_id)
                .first()
            )
            if (
                branch is None
                or not branch.is_active
                or branch.status != BranchStatus.ACTIVE
            ):
                logger.info("qr.resolve branch_unavailable")
                raise BranchNotFoundException()
            tenant = branch.tenant
            if tenant is None or not tenant_is_operationally_available(tenant):
                logger.info("qr.resolve tenant_unavailable")
                raise TenantNotFoundException()
            return tenant, branch

        logger.info("qr.resolve unknown_entity_type")
        raise QrNotFoundException()

    @staticmethod
    def disable(user, qr: QrCode) -> QrCode:
        QrCodeBusinessLogicLayer._assert_can_manage(user, qr)
        qr.is_active = False
        qr.save(update_fields=["is_active", "updated_at"])
        QrCodeBusinessLogicLayer._schedule_cache_invalidation(qr)
        return qr

    @staticmethod
    def enable(user, qr: QrCode) -> QrCode:
        QrCodeBusinessLogicLayer._assert_can_manage(user, qr)
        if qr.is_active:
            return qr
        if qr_dal.get_active_for_entity(qr.entity_type, qr.entity_id) is not None:
            raise QrAlreadyExistsException()
        qr.is_active = True
        qr.save(update_fields=["is_active", "updated_at"])
        QrCodeBusinessLogicLayer._schedule_cache_invalidation(qr)
        return qr

    @staticmethod
    def set_destination(user, qr: QrCode, destination_type: str) -> QrCode:
        QrCodeBusinessLogicLayer._assert_can_manage(user, qr)
        if destination_type not in QrDestinationType.values:
            raise QrInvalidDestinationException()
        if qr.entity_type == QrEntityType.TENANT and destination_type != QrDestinationType.TENANT:
            # Tenant QRs only resolve to the tenant public URL in v1.
            destination_type = QrDestinationType.TENANT
        qr.destination_type = destination_type
        qr.save(update_fields=["destination_type", "updated_at"])
        QrCodeBusinessLogicLayer._schedule_cache_invalidation(qr)
        return qr

    @staticmethod
    def regenerate(user, qr: QrCode) -> QrCode:
        QrCodeBusinessLogicLayer._assert_can_manage(user, qr)
        with transaction.atomic():
            qr.is_active = False
            qr.save(update_fields=["is_active", "updated_at"])
            new_qr = QrCodeBusinessLogicLayer._create(
                entity_type=qr.entity_type,
                entity_id=qr.entity_id,
                destination_type=qr.destination_type,
            )
            QrCodeBusinessLogicLayer._schedule_cache_invalidation(new_qr)
            return new_qr

    @staticmethod
    def get_tenant_qr(user, tenant_id) -> QrCode:
        tenant = QrCodeBusinessLogicLayer._load_owned_tenant(user, tenant_id)
        qr = qr_dal.get_active_for_entity(QrEntityType.TENANT, tenant.id)
        if qr is None:
            raise QrNotFoundException()
        return qr

    @staticmethod
    def get_branch_qr(user, branch_id) -> QrCode:
        branch = QrCodeBusinessLogicLayer._load_owned_branch(user, branch_id)
        qr = qr_dal.get_active_for_entity(QrEntityType.BRANCH, branch.id)
        if qr is None:
            raise QrNotFoundException()
        return qr

    @staticmethod
    def enable_tenant_qr(user, tenant_id) -> QrCode:
        tenant = QrCodeBusinessLogicLayer._load_owned_tenant(user, tenant_id)
        qr = QrCodeBusinessLogicLayer._qr_for_enable(
            QrEntityType.TENANT, tenant.id
        )
        return QrCodeBusinessLogicLayer.enable(user, qr)

    @staticmethod
    def enable_branch_qr(user, branch_id) -> QrCode:
        branch = QrCodeBusinessLogicLayer._load_owned_branch(user, branch_id)
        qr = QrCodeBusinessLogicLayer._qr_for_enable(
            QrEntityType.BRANCH, branch.id
        )
        return QrCodeBusinessLogicLayer.enable(user, qr)

    @staticmethod
    def disable_tenant_qr(user, tenant_id) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_tenant_qr(user, tenant_id)
        return QrCodeBusinessLogicLayer.disable(user, qr)

    @staticmethod
    def disable_branch_qr(user, branch_id) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_branch_qr(user, branch_id)
        return QrCodeBusinessLogicLayer.disable(user, qr)

    @staticmethod
    def regenerate_tenant_qr(user, tenant_id) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_tenant_qr(user, tenant_id)
        return QrCodeBusinessLogicLayer.regenerate(user, qr)

    @staticmethod
    def regenerate_branch_qr(user, branch_id) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_branch_qr(user, branch_id)
        return QrCodeBusinessLogicLayer.regenerate(user, qr)

    @staticmethod
    def set_tenant_qr_destination(user, tenant_id, destination_type: str) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_tenant_qr(user, tenant_id)
        return QrCodeBusinessLogicLayer.set_destination(user, qr, destination_type)

    @staticmethod
    def set_branch_qr_destination(user, branch_id, destination_type: str) -> QrCode:
        qr = QrCodeBusinessLogicLayer.get_branch_qr(user, branch_id)
        return QrCodeBusinessLogicLayer.set_destination(user, qr, destination_type)

    @staticmethod
    def _qr_for_enable(entity_type: str, entity_id) -> QrCode:
        qr = qr_dal.get_latest_for_entity(entity_type, entity_id)
        if qr is None:
            raise QrNotFoundException()
        return qr

    @staticmethod
    def _load_owned_tenant(user, tenant_id) -> Tenant:
        tenant = (
            Tenant.objects.select_related("owner")
            .filter(id=tenant_id)
            .first()
        )
        if tenant is None:
            raise TenantNotFoundException()
        tenant.owner_user_id = tenant.owner.user_id  # type: ignore[attr-defined]
        try:
            _assert_owns_tenant(user, tenant)
        except TenantPermissionDeniedException:
            raise UnauthorizedQrAccessException()
        return tenant

    @staticmethod
    def _load_owned_branch(user, branch_id) -> Branch:
        branch = (
            Branch.objects.select_related("tenant", "tenant__owner")
            .filter(id=branch_id)
            .first()
        )
        if branch is None:
            raise BranchNotFoundException()
        owner = getattr(branch.tenant, "owner", None)
        branch.owner_user_id = owner.user_id if owner is not None else None
        try:
            _assert_owns_branch(user, branch)
        except (BranchPermissionDeniedException, TenantPermissionDeniedException):
            raise UnauthorizedQrAccessException()
        return branch

    @staticmethod
    def _schedule_cache_invalidation(qr: QrCode) -> None:
        entity_type = qr.entity_type
        entity_id = qr.entity_id

        def _invalidate():
            from tenants.selectors.tenant_dal import (
                BranchDataAccessLayer,
                TenantDataAccessLayer,
            )

            if entity_type == QrEntityType.TENANT:
                tenant = (
                    Tenant.objects.select_related("owner")
                    .filter(id=entity_id)
                    .first()
                )
                if tenant is not None:
                    TenantDataAccessLayer.invalidate_tenant_cache(
                        tenant.id, tenant.owner.user_id
                    )
                return
            if entity_type == QrEntityType.BRANCH:
                branch = Branch.objects.filter(id=entity_id).first()
                if branch is not None:
                    BranchDataAccessLayer.invalidate_branch_cache(
                        branch.tenant_id, branch.id
                    )

        transaction.on_commit(_invalidate)

    @staticmethod
    def _assert_can_manage(user, qr: QrCode) -> None:
        if qr.entity_type == QrEntityType.TENANT:
            tenant = Tenant.objects.select_related("owner").filter(id=qr.entity_id).first()
            if tenant is None:
                raise TenantNotFoundException()
            tenant.owner_user_id = tenant.owner.user_id  # type: ignore[attr-defined]
            try:
                _assert_owns_tenant(user, tenant)
            except TenantPermissionDeniedException:
                raise UnauthorizedQrAccessException()
            return

        if qr.entity_type == QrEntityType.BRANCH:
            branch = (
                Branch.objects.select_related("tenant", "tenant__owner")
                .filter(id=qr.entity_id)
                .first()
            )
            if branch is None:
                raise BranchNotFoundException()
            owner = getattr(branch.tenant, "owner", None)
            branch.owner_user_id = owner.user_id if owner is not None else None
            try:
                _assert_owns_branch(user, branch)
            except (BranchPermissionDeniedException, TenantPermissionDeniedException):
                raise UnauthorizedQrAccessException()
            return

        raise UnauthorizedQrAccessException()
