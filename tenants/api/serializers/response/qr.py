from rest_framework import serializers

from tenants.services.public_url import qr_payload
from tenants.services.qr_bll import QrCodeBusinessLogicLayer


class QrResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    url = serializers.CharField()


def serialize_qr(obj, request=None) -> dict | None:
    code = QrCodeBusinessLogicLayer.active_code_for(obj)
    if not code:
        return None
    return qr_payload(code, request)
