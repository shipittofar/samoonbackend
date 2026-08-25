from rest_framework import serializers


class PublicWebsiteLayoutSerializer(serializers.Serializer):
    hero = serializers.DictField(required=False)
    about = serializers.DictField(required=False)
    contact = serializers.DictField(required=False)
    faq = serializers.ListField(child=serializers.DictField(), required=False)
    brandTheme = serializers.CharField(required=False, allow_null=True)
    heroConfig = serializers.DictField(required=False, allow_null=True)
    sectionTemplates = serializers.DictField(required=False, allow_null=True)
    navItems = serializers.ListField(child=serializers.DictField(), required=False)


class PublicWebsiteResponseSerializer(serializers.Serializer):
    layout = PublicWebsiteLayoutSerializer()
    theme = serializers.DictField()
    branding = serializers.DictField()
    image = serializers.CharField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    status = serializers.CharField(required=False)
    tenant = serializers.DictField(required=False)
    sections = serializers.ListField(child=serializers.DictField())
    branchOverrides = serializers.DictField(child=serializers.DictField(), required=False)
