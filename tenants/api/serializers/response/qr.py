from rest_framework import serializers

from tenants.models.qr_code import QrDestinationType
from tenants.services.public_url import qr_payload
from tenants.services.qr_bll import QrCodeBusinessLogicLayer


class QrResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    url = serializers.CharField()


class QrManagementResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    url = serializers.CharField()
    entity_type = serializers.CharField()
    entity_id = serializers.UUIDField()
    destination_type = serializers.CharField()
    is_active = serializers.BooleanField()


class QrDestinationRequestSerializer(serializers.Serializer):
    destination_type = serializers.ChoiceField(choices=QrDestinationType.choices)


def serialize_qr(obj, request=None) -> dict | None:
    code = QrCodeBusinessLogicLayer.active_code_for(obj)
    if not code:
        return None
    return qr_payload(code, request)


def serialize_qr_management(qr, request=None) -> dict:
    payload = qr_payload(qr.code, request)
    return {
        "code": payload["code"],
        "url": payload["url"],
        "entity_type": qr.entity_type,
        "entity_id": qr.entity_id,
        "destination_type": qr.destination_type,
        "is_active": qr.is_active,
    }

