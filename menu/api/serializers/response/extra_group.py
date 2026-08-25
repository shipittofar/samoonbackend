from rest_framework import serializers

from menu.models import ExtraGroup


class ExtraGroupOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtraGroup
        fields = [
            "id",
            "branch_id",
            "name",
            "description",
            "selection_type",
            "required",
            "min_selection",
            "max_selection",
            "order",
            "is_active",
            "created_at",
        ]
