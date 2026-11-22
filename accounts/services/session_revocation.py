"""Sign a user out everywhere: after a password change or reset, or when the
account is deleted.

Two layers, because access tokens are stateless:
- every outstanding refresh token is blacklisted, so no device can get a new
  access token;
- ``User.tokens_valid_after`` is moved to now, and access tokens issued before
  it are rejected (``AccessTokenRevocationMixin`` / websocket middleware) —
  otherwise a stolen access token would keep working until it expires.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone


def revoke_all_sessions(user) -> None:
    # Whole seconds: a token's "iat" claim is in whole seconds, so a token
    # issued later in this same second (the new session of the person who
    # just changed their password) must still count as valid.
    user.tokens_valid_after = timezone.now().replace(microsecond=0)
    user.save(update_fields=["tokens_valid_after"])
    try:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    except Exception:  # blacklist app not installed
        return
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def token_is_revoked(user, validated_token) -> bool:
    """True when the token was issued before the user's last sign-out-everywhere."""
    cutoff = getattr(user, "tokens_valid_after", None)
    if cutoff is None:
        return False
    iat = validated_token.get("iat")
    if iat is None:
        return True  # cannot prove it is newer
    try:
        issued = datetime.fromtimestamp(int(iat), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return True
    return issued < cutoff
