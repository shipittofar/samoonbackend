"""Platform-level identity: who runs the whole platform.

A Django superuser (``is_superuser``, active) is the platform operator. They
have every permission in every tenant (owner-level access), regardless of
tenant status, and are the only ones who may edit global role definitions.

``is_staff`` means only "may sign in to the Django admin". It grants nothing
in the API.
"""
from __future__ import annotations


def is_platform_superuser(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )
