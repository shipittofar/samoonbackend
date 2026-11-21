from rest_framework import serializers
from accounts.api.validators.phone_numbers import build_full_phone
from accounts.phone import InvalidPhoneNumber, clean_country_code, normalize_national
from accounts.api.validators.password import validate_password_strength, validate_passwords_match


def _validate_identifier(attrs: dict) -> dict:
    email = attrs.get("email")
    phone_number = attrs.get("phone_number")
    country_code = attrs.get("country_code")

    if isinstance(email, str):
        email = email.strip().lower() or None
        attrs["email"] = email
    if isinstance(phone_number, str):
        phone_number = phone_number.strip() or None
        attrs["phone_number"] = phone_number
    if isinstance(country_code, str):
        country_code = country_code.strip() or None
        attrs["country_code"] = country_code

    if email and phone_number:
        raise serializers.ValidationError("Provide only one of email or phone_number.")
    if not email and not phone_number:
        raise serializers.ValidationError("Either email or phone_number is required.")
    if phone_number and not country_code:
        raise serializers.ValidationError("country_code is required for phone_number.")

    if email:
        attrs["identifier"] = email
        attrs["is_email"] = True
    else:
        attrs["identifier"] = build_full_phone(country_code, phone_number)
        attrs["country_code"] = clean_country_code(country_code)
        attrs["is_email"] = False

    return attrs


class SendOTPInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=20, required=False)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class VerifyOTPInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=20, required=False)
    code = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class SetPasswordInputSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        validate_passwords_match(attrs["password"], attrs["confirm_password"])
        user = self.context["request"].user
        validate_password_strength(attrs["password"], user=user)
        return attrs


class ChangePasswordInputSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        validate_passwords_match(attrs["new_password"], attrs["confirm_password"])
        user = self.context["request"].user
        validate_password_strength(attrs["new_password"], user=user)
        return attrs


class PasswordLoginInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=20, required=False)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class PhoneVerificationRequestInputSerializer(serializers.Serializer):
    country_code = serializers.CharField(max_length=5)
    phone_number = serializers.CharField(max_length=20)

    def validate(self, attrs):
        # Stored form: "+98" + "912…" (no trunk 0); see accounts/phone.py.
        try:
            code = clean_country_code(attrs["country_code"])
            attrs["phone_number"] = normalize_national(code, attrs["phone_number"])
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError({"phone_number": str(exc)})
        attrs["country_code"] = code
        return attrs


class PhoneVerificationConfirmInputSerializer(PhoneVerificationRequestInputSerializer):
    code = serializers.CharField(min_length=6, max_length=6)


class EmailVerificationRequestInputSerializer(serializers.Serializer):
    email = serializers.EmailField()


class EmailVerificationConfirmInputSerializer(EmailVerificationRequestInputSerializer):
    code = serializers.CharField(min_length=6, max_length=6)


class UpdateProfileInputSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=64, required=False)
    last_name = serializers.CharField(max_length=64, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required to update.")
        return attrs


class SetAvatarInputSerializer(serializers.Serializer):
    avatar = serializers.ImageField(required=False)
    avatar_asset_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if "avatar" in attrs and "avatar_asset_id" in attrs:
            raise serializers.ValidationError(
                "Provide either avatar or avatar_asset_id, not both."
            )
        if "avatar" not in attrs and "avatar_asset_id" not in attrs:
            raise serializers.ValidationError("avatar or avatar_asset_id is required.")
        return attrs


class ForgetPasswordRequestInputSerializer(serializers.Serializer):
    country_code = serializers.CharField(max_length=5)
    phone_number = serializers.CharField(max_length=20)

    def validate(self, attrs):
        attrs["phone_number"] = build_full_phone(attrs["country_code"], attrs["phone_number"])
        return attrs


class ForgetPasswordConfirmInputSerializer(ForgetPasswordRequestInputSerializer):
    code = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        validate_passwords_match(attrs["new_password"], attrs["confirm_password"])
        validate_password_strength(attrs["new_password"])
        return attrs


class RegisterInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=20, required=False)
    first_name = serializers.CharField(max_length=64)
    last_name = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate(self, attrs):
        return _validate_identifier(attrs)


class LogoutInputSerializer(serializers.Serializer):
    refresh = serializers.CharField()
