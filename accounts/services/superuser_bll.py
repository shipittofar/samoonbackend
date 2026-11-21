"""Adding, approving and revoking platform superusers.

See accounts/models/superuser_request.py for the rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import (
    PlatformSecuritySettings,
    SuperuserRequest,
    SuperuserRequestStatus,
    User,
)

DEFAULT_COUNTRY_CODE = "+98"

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_COUNTRY_CODE = re.compile(r"^\+[1-9]\d{0,3}$")


class SuperuserError(Exception):
    """A rule stopped the operation; the message is shown to the operator."""


@dataclass(frozen=True)
class PhoneNumber:
    country_code: str  # "+98"
    national: str  # "9121234567"

    @property
    def full(self) -> str:
        return f"{self.country_code}{self.national}"

    def stored_variants(self) -> list[str]:
        """How this number may already be stored. Sign-up does not strip the
        trunk 0, so "+98" + "0912…" exists alongside "+98" + "912…"."""
        return [self.full, f"{self.country_code}0{self.national}"]


def normalize_phone(raw: str, country_code: str = DEFAULT_COUNTRY_CODE) -> PhoneNumber:
    """Accepts 09121234567, 9121234567, +989121234567, 00989121234567, Persian
    digits, spaces and dashes. A number in international form must use
    ``country_code`` (pass another one for a non-Iranian number)."""
    if not _COUNTRY_CODE.match(country_code or ""):
        raise SuperuserError("Country code must look like +98.")
    value = re.sub(r"[\s\-().]", "", (raw or "").translate(_DIGITS))
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        if not value.startswith(country_code):
            raise SuperuserError(
                f"The number does not start with {country_code}. "
                "Pass its country code with --country-code."
            )
        national = value[len(country_code):]
    else:
        national = value
    national = national.lstrip("0")
    if not national.isdigit() or not 6 <= len(national) <= 14:
        raise SuperuserError("That is not a valid phone number.")
    return PhoneNumber(country_code=country_code, national=national)


def active_superusers():
    return User.objects.filter(is_superuser=True, is_active=True)


def find_user(phone: PhoneNumber) -> User | None:
    return User.all_objects.filter(phone_number__in=phone.stored_variants()).first()


@dataclass(frozen=True)
class AddResult:
    user: User
    outcome: str  # "first_superuser" | "request_filed" | "already_superuser"
    request: SuperuserRequest | None = None


@transaction.atomic
def add_superuser(
    *,
    phone: PhoneNumber,
    password: str | None,
    first_name: str = "",
    last_name: str = "",
    email: str | None = None,
    note: str = "",
) -> AddResult:
    """First superuser: created at once. Later ones: a pending request, only
    while a superuser allows requests in the Django admin."""
    # Serialise concurrent runs, so two "first" superusers cannot both slip in.
    PlatformSecuritySettings.load()
    settings_row = PlatformSecuritySettings.objects.select_for_update().get(pk=1)
    is_first = not active_superusers().exists()

    user = find_user(phone)
    if user is not None and user.is_deleted:
        raise SuperuserError("This number belongs to a deleted account. Restore it in the Django admin first.")
    if user is not None and user.is_superuser and user.is_active:
        return AddResult(user=user, outcome="already_superuser")
    if not is_first and not settings_row.allow_superuser_requests:
        raise SuperuserError(
            "Adding superusers is switched off. A superuser must turn on "
            "'Allow superuser requests' in the Django admin "
            "(Accounts → Platform security settings), then run this again."
        )
    if user is not None and SuperuserRequest.objects.filter(
        user=user, status=SuperuserRequestStatus.PENDING
    ).exists():
        raise SuperuserError("This account already has a pending superuser request.")
    if email and User.all_objects.filter(email=email).exclude(pk=getattr(user, "pk", None)).exists():
        raise SuperuserError("That email belongs to another account.")

    if user is None:
        user = User.objects.create_user(
            phone_number=phone.full,
            country_code=phone.country_code,
            first_name=first_name or None,
            last_name=last_name or None,
            email=email or None,
        )
    else:
        changed = []
        for field, value in (("first_name", first_name), ("last_name", last_name), ("email", email)):
            if value and not getattr(user, field):
                setattr(user, field, value)
                changed.append(field)
        if changed:
            user.save(update_fields=changed)

    if password:
        user.set_password(password)
        user.save(update_fields=["password"])
    elif not user.has_usable_password():
        raise SuperuserError("A password is required: the Django admin signs in with phone + password.")

    if is_first:
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.save(update_fields=["is_superuser", "is_staff", "is_active"])
        request = SuperuserRequest.objects.create(
            user=user,
            status=SuperuserRequestStatus.APPROVED,
            note=note or "First superuser (no one to approve).",
            decided_at=timezone.now(),
        )
        return AddResult(user=user, outcome="first_superuser", request=request)

    request = SuperuserRequest.objects.create(user=user, note=note)
    return AddResult(user=user, outcome="request_filed", request=request)


def _assert_decider(actor: User) -> None:
    if not (actor and actor.is_active and actor.is_superuser):
        raise SuperuserError("Only an active superuser can decide superuser requests.")


@transaction.atomic
def approve(request: SuperuserRequest, *, actor: User) -> None:
    _assert_decider(actor)
    request = SuperuserRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != SuperuserRequestStatus.PENDING:
        raise SuperuserError("This request was already decided.")
    if request.user_id == actor.id:
        raise SuperuserError("You cannot approve your own request.")
    user = request.user
    if user.is_deleted:
        raise SuperuserError("The account was deleted.")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    request.status = SuperuserRequestStatus.APPROVED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_by", "decided_at"])


@transaction.atomic
def reject(request: SuperuserRequest, *, actor: User) -> None:
    _assert_decider(actor)
    request = SuperuserRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != SuperuserRequestStatus.PENDING:
        raise SuperuserError("This request was already decided.")
    request.status = SuperuserRequestStatus.REJECTED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_by", "decided_at"])


@transaction.atomic
def revoke(user: User, *, actor: User) -> None:
    """Take superuser (and Django admin access) away from ``user``."""
    _assert_decider(actor)
    if user.pk == actor.pk:
        raise SuperuserError("You cannot revoke your own superuser access.")
    if not user.is_superuser:
        return
    if not active_superusers().exclude(pk=user.pk).exists():
        raise SuperuserError("The platform must keep at least one active superuser.")
    user.is_superuser = False
    user.is_staff = False
    user.save(update_fields=["is_superuser", "is_staff"])
