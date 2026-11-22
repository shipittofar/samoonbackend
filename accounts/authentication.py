from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from accounts.services.session_revocation import token_is_revoked


class RevocableJWTAuthentication(JWTAuthentication):
    """JWT authentication that also rejects access tokens issued before the
    user's last password change / reset (``User.tokens_valid_after``)."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if token_is_revoked(user, validated_token):
            raise AuthenticationFailed("Token has been revoked.", code="token_revoked")
        return user
