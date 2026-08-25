from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


def validate_password_strength(password: str, user=None) -> str:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)})
    return password


def validate_passwords_match(password: str, confirm_password: str) -> None:
    if password != confirm_password:
        raise serializers.ValidationError({"confirm_password": ["Passwords do not match."]})
