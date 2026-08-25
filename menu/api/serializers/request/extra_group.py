from rest_framework import serializers


class ExtraGroupInputSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    selection_type = serializers.ChoiceField(
        choices=["single", "multiple"], default="multiple"
    )
    required = serializers.BooleanField(default=False)
    min_selection = serializers.IntegerField(default=0, min_value=0)
    max_selection = serializers.IntegerField(default=1, min_value=1)
    order = serializers.IntegerField(default=0, min_value=0)
    is_active = serializers.BooleanField(default=True)


class ExtraGroupUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    selection_type = serializers.ChoiceField(
        choices=["single", "multiple"], required=False
    )
    required = serializers.BooleanField(required=False)
    min_selection = serializers.IntegerField(min_value=0, required=False)
    max_selection = serializers.IntegerField(min_value=1, required=False)
    order = serializers.IntegerField(min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)


class ExtraGroupReorderSerializer(serializers.Serializer):
    order = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )
