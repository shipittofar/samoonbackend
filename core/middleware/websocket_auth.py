# core/websocket_auth.py
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from accounts.services.session_revocation import token_is_revoked

User = get_user_model()


@database_sync_to_async
def get_user_from_token(token: str):
    try:
        validated_token = AccessToken(token)
        user = User.objects.get(id=validated_token["user_id"])
    except (TokenError, User.DoesNotExist):
        return AnonymousUser()
    if not user.is_active or token_is_revoked(user, validated_token):
        return AnonymousUser()
    return user


class JWTAuthMiddleware(BaseMiddleware):
    """
    JWT query-string authentication for Django Channels.

    Usage:
        ws://host/ws/orders/<public_id>/?token=<access_token>
        ws://host/ws/console/<branch_id>/?token=<access_token>
    """

    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope["query_string"].decode())
        token = query_string.get("token", [None])[0]

        scope["user"] = (
            await get_user_from_token(token) if token else AnonymousUser()
        )
        return await super().__call__(scope, receive, send)