from rest_framework import serializers

from reservations.models import Reservation, ReservationStatus


class CreateReservationRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    guest_name = serializers.CharField(max_length=255)
    guest_phone = serializers.CharField(max_length=32)
    party_size = serializers.IntegerField(min_value=1)
    reserved_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class UpdateReservationStatusRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReservationStatus.choices)


class ReservationResponseSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="branch.tenant_id", read_only=True)
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)

    class Meta:
        model = Reservation
        fields = [
            "id",
            "tenant_id",
            "branch_id",
            "guest_name",
            "guest_phone",
            "party_size",
            "reserved_at",
            "notes",
            "status",
            "created_at",
            "updated_at",
        ]


class PendingCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
