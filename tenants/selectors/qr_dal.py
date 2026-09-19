from django.db.models import OuterRef, Subquery

from tenants.models.qr_code import QrCode, QrEntityType


def active_qr_code_subquery(entity_type: str):
    return Subquery(
        QrCode.objects.filter(
            entity_type=entity_type,
            entity_id=OuterRef("pk"),
            is_active=True,
        ).values("code")[:1]
    )


def annotate_qr_code(queryset, entity_type: str):
    return queryset.annotate(qr_code=active_qr_code_subquery(entity_type))


def get_by_code(code: str) -> QrCode | None:
    return QrCode.objects.filter(code=code).first()


def get_active_for_entity(entity_type: str, entity_id) -> QrCode | None:
    return QrCode.objects.filter(
        entity_type=entity_type,
        entity_id=entity_id,
        is_active=True,
    ).first()


def get_latest_for_entity(entity_type: str, entity_id) -> QrCode | None:
    """Active QR if present, otherwise the most recently updated row."""
    active = get_active_for_entity(entity_type, entity_id)
    if active is not None:
        return active
    return (
        QrCode.objects.filter(entity_type=entity_type, entity_id=entity_id)
        .order_by("-updated_at", "-created_at")
        .first()
    )


def tenant_entity_type() -> str:
    return QrEntityType.TENANT


def branch_entity_type() -> str:
    return QrEntityType.BRANCH
