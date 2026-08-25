import copy

from rest_framework import serializers


REQUIRED_LAYOUT_FIELDS = (
    "sections",
    "hero",
    "about",
    "contact",
    "faq",
    "theme",
    "status",
)

VALID_STATUSES = {"draft", "published"}


class HomepageLayoutSerializer(serializers.Serializer):
    """Lossless HomepageLayout serializer aligned with the frontend contract."""

    sections = serializers.ListField(child=serializers.DictField(), required=False)
    hero = serializers.DictField(required=False)
    about = serializers.DictField(required=False)
    contact = serializers.DictField(required=False)
    faq = serializers.ListField(child=serializers.DictField(), required=False)
    theme = serializers.DictField(required=False)
    status = serializers.ChoiceField(choices=sorted(VALID_STATUSES), required=False)
    lastPublishedAt = serializers.CharField(required=False, allow_null=True)
    lastSavedAt = serializers.CharField(required=False, allow_null=True)
    publishedVersion = serializers.DictField(required=False, allow_null=True)
    versions = serializers.ListField(child=serializers.DictField(), required=False)
    brandTheme = serializers.CharField(required=False, allow_null=True)
    heroConfig = serializers.DictField(required=False, allow_null=True)
    sectionTemplates = serializers.DictField(required=False, allow_null=True)
    navItems = serializers.ListField(child=serializers.DictField(), required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")

        errors = {}
        for field_name in REQUIRED_LAYOUT_FIELDS:
            if field_name not in data:
                errors[field_name] = "This field is required."

        if errors:
            raise serializers.ValidationError(errors)

        status = data.get("status")
        if status not in VALID_STATUSES:
            raise serializers.ValidationError(
                {"status": f'Must be one of: {", ".join(sorted(VALID_STATUSES))}.'}
            )

        if not isinstance(data.get("sections"), list):
            raise serializers.ValidationError({"sections": "Expected a list."})
        if not isinstance(data.get("hero"), dict):
            raise serializers.ValidationError({"hero": "Expected an object."})
        if not isinstance(data.get("about"), dict):
            raise serializers.ValidationError({"about": "Expected an object."})
        if not isinstance(data.get("contact"), dict):
            raise serializers.ValidationError({"contact": "Expected an object."})
        if not isinstance(data.get("faq"), list):
            raise serializers.ValidationError({"faq": "Expected a list."})
        if not isinstance(data.get("theme"), dict):
            raise serializers.ValidationError({"theme": "Expected an object."})

        return copy.deepcopy(data)

    def to_representation(self, instance):
        if instance is None:
            return {}
        return copy.deepcopy(instance)


class BranchContentOverridesSerializer(serializers.Serializer):
    """Lossless BranchContentOverrides serializer."""

    heroHeadline = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    heroSubheadline = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    heroImage = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    gallery = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
    )
    about = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def to_internal_value(self, data):
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        return copy.deepcopy(data)

    def to_representation(self, instance):
        if not instance:
            return {}
        return copy.deepcopy(instance)


class WebsiteMediaUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)


class WebsiteMediaUploadResponseSerializer(serializers.Serializer):
    url = serializers.CharField()
