from rest_framework import serializers


def _validate_identifier(attrs: dict) -> dict:
    email = attrs.get("email")
    phone_number = attrs.get("phone_number")
    country_code = attrs.get("country_code")

    if email and phone_number:
        raise serializers.ValidationError("فقط یکی از email یا phone_number را وارد کنید.")
    if not email and not phone_number:
        raise serializers.ValidationError("وارد کردن email یا phone_number الزامی است.")
    if phone_number and not country_code:
        raise serializers.ValidationError("country_code برای phone_number الزامی است.")

    if email:
        attrs["identifier"] = email
        attrs["is_email"] = True
    else:
        attrs["identifier"] = f"{country_code}{phone_number}"
        attrs["is_email"] = False

    return attrs


class SendOTPInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=15, required=False)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class VerifyOTPInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=15, required=False)
    code = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class SetPasswordInputSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    password = serializers.CharField(min_length=8, write_only=True)


class PasswordLoginInputSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    password = serializers.CharField(write_only=True)


class CompleteProfileInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=15, required=False)
    first_name = serializers.CharField(max_length=64, required=False)
    last_name = serializers.CharField(max_length=64, required=False)
    avatar = serializers.ImageField(required=False)

    def validate(self, attrs):
        if attrs.get("phone_number") and not attrs.get("country_code"):
            raise serializers.ValidationError("country_code برای phone_number الزامی است.")
        return attrs