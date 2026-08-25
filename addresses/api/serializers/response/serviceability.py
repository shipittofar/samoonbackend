from rest_framework import serializers


class AssignedBranchSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class ServiceabilityResponseSerializer(serializers.Serializer):
    serviceable = serializers.BooleanField()
    delivery_zone = serializers.CharField(allow_null=True)
    assigned_branch = AssignedBranchSerializer()
    delivery_fee = serializers.DecimalField(max_digits=10, decimal_places=2)
    estimated_delivery_time = serializers.IntegerField(allow_null=True)
    distance = serializers.FloatField(allow_null=True)
    minimum_order = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField()
    reason = serializers.CharField(allow_null=True, required=False)


class BranchResolutionResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    distance = serializers.FloatField(allow_null=True)
    delivery_radius = serializers.FloatField(allow_null=True)
    estimated_delivery_time = serializers.IntegerField(allow_null=True)


class AddressSuggestionSerializer(serializers.Serializer):
    formatted_address = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    provider = serializers.CharField()
    confidence = serializers.FloatField()


class AddressSuggestionsResponseSerializer(serializers.Serializer):
    suggestions = AddressSuggestionSerializer(many=True)
