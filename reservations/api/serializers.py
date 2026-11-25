from django.utils import timezone
from rest_framework import serializers

from reservations.models import Reservation, ReservationStatus
from reservations.services.rules import LIMITS
from reservations.services.slots import branch_zone, longest_end


class CreateReservationRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    guest_name = serializers.CharField(max_length=255)
    guest_phone = serializers.CharField(max_length=32)
    party_size = serializers.IntegerField(min_value=1)
    # Either the branch's local date and time (what the booking form shows) or
    # an exact moment.
    date = serializers.DateField(required=False)
    time = serializers.TimeField(required=False)
    reserved_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)

    def validate(self, attrs):
        if not attrs.get("reserved_at") and not (attrs.get("date") and attrs.get("time")):
            raise serializers.ValidationError({"time": "Choose a date and time."})
        return attrs


class AvailableSlotsQuerySerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    date = serializers.DateField()
    guests = serializers.IntegerField(min_value=1, required=False, default=1)


class ConsoleReservationsQuerySerializer(serializers.Serializer):
    branch_id = serializers.UUIDField(required=False)
    date = serializers.DateField(required=False)
    status = serializers.ChoiceField(choices=ReservationStatus.choices, required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


class UpdateReservationStatusRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReservationStatus.choices)


class ReservationResponseSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    business_name = serializers.CharField(source="branch.tenant.name", read_only=True)
    can_cancel = serializers.SerializerMethodField()
    # In the branch's own time zone, so guest and business read the same hour.
    local_date = serializers.SerializerMethodField()
    local_time = serializers.SerializerMethodField()
    local_end_time = serializers.SerializerMethodField()
    confirmation_code = serializers.SerializerMethodField()
    tenant_id = serializers.UUIDField(source="branch.tenant_id", read_only=True)
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)

    class Meta:
        model = Reservation
        fields = [
            "id",
            "tenant_id",
            "branch_id",
            "branch_name",
            "business_name",
            "guest_name",
            "guest_phone",
            "party_size",
            "reserved_at",
            "local_date",
            "local_time",
            "local_end_time",
            "duration_minutes",
            "ends_at",
            "confirmation_code",
            "notes",
            "status",
            "can_cancel",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def _local(obj):
        return obj.reserved_at.astimezone(branch_zone(obj.branch))

    def get_local_date(self, obj) -> str:
        return self._local(obj).strftime("%Y-%m-%d")

    def get_local_time(self, obj) -> str:
        return self._local(obj).strftime("%H:%M")

    def get_local_end_time(self, obj) -> str:
        return obj.ends_at.astimezone(branch_zone(obj.branch)).strftime("%H:%M")

    def get_confirmation_code(self, obj) -> str:
        """Short code to quote at the door."""
        return obj.id.hex[:8].upper()

    def get_can_cancel(self, obj) -> bool:
        """The customer may still call it off: not handled yet and not in the past."""
        return (
            obj.status in (ReservationStatus.PENDING, ReservationStatus.CONFIRMED)
            and obj.reserved_at > timezone.now()
        )


class ConsoleReservationResponseSerializer(ReservationResponseSerializer):
    customer_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta(ReservationResponseSerializer.Meta):
        fields = [*ReservationResponseSerializer.Meta.fields, "customer_id"]


class ConsoleReservationDetailSerializer(ConsoleReservationResponseSerializer):
    # How long it could run at most before the branch is full (staff editor).
    max_duration_minutes = serializers.SerializerMethodField()

    class Meta(ConsoleReservationResponseSerializer.Meta):
        fields = [*ConsoleReservationResponseSerializer.Meta.fields, "max_duration_minutes"]

    def get_max_duration_minutes(self, obj) -> int:
        free = int((longest_end(obj) - obj.reserved_at).total_seconds() // 60)
        return max(free, obj.duration_minutes)


class UpdateReservationDurationRequestSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField(
        min_value=LIMITS["duration_minutes"][0], max_value=LIMITS["duration_minutes"][1]
    )


class PendingCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
