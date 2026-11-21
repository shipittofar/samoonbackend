"""manage.py admin_add — add a platform superuser (what `samoon admin-add` runs).

  First superuser:  created at once (nobody exists yet to approve it).
  Later ones:       only while a superuser has turned on "Allow superuser
                    requests" in the Django admin; the account then waits for
                    a superuser to approve it in Django admin → Superuser requests.

The password is asked twice on the terminal. For scripts, set
DJANGO_SUPERUSER_PASSWORD instead and pass --no-input.
"""
from __future__ import annotations

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.services import superuser_bll


class Command(BaseCommand):
    help = "Add a platform superuser (the first one directly, later ones after approval)."

    def add_arguments(self, parser):
        parser.add_argument("phone", nargs="?", help="Mobile number, e.g. 09121234567 or +989121234567")
        parser.add_argument("--country-code", default=superuser_bll.DEFAULT_COUNTRY_CODE)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--email", default="")
        parser.add_argument("--note", default="", help="Why this account needs superuser (shown to the approver).")
        parser.add_argument("--no-input", action="store_true", help="Do not prompt; read the password from DJANGO_SUPERUSER_PASSWORD.")

    def handle(self, *args, **opts):
        interactive = not opts["no_input"]
        raw_phone = opts["phone"] or (self._ask("Mobile number: ") if interactive else "")
        if not raw_phone:
            raise CommandError("A mobile number is required.")
        try:
            phone = superuser_bll.normalize_phone(raw_phone, opts["country_code"])
        except superuser_bll.SuperuserError as exc:
            raise CommandError(str(exc))

        existing = superuser_bll.find_user(phone)
        is_first = not superuser_bll.active_superusers().exists()
        if existing is not None and existing.is_superuser and existing.is_active:
            self.stdout.write(self.style.WARNING(f"{phone.full} is already a superuser. Nothing to do."))
            return

        first_name = opts["first_name"]
        if interactive and not first_name and existing is None:
            first_name = self._ask("First name (optional): ")

        password = self._password(interactive, required=existing is None or not existing.has_usable_password())

        try:
            result = superuser_bll.add_superuser(
                phone=phone,
                password=password,
                first_name=first_name,
                last_name=opts["last_name"],
                email=opts["email"] or None,
                note=opts["note"],
            )
        except superuser_bll.SuperuserError as exc:
            raise CommandError(str(exc))

        if result.outcome == "first_superuser":
            self.stdout.write(self.style.SUCCESS(
                f"Superuser {phone.full} created (first one: no approval needed).\n"
                "Sign in to /admin/ with this number and password."
            ))
        elif result.outcome == "request_filed":
            self.stdout.write(self.style.SUCCESS(
                f"Request filed for {phone.full}. It becomes a superuser once an existing "
                "superuser approves it in Django admin → Accounts → Superuser requests."
            ))
        else:
            self.stdout.write(self.style.WARNING(f"{phone.full} is already a superuser."))
        if not is_first and result.outcome == "request_filed":
            self.stdout.write("Tip: turn 'Allow superuser requests' off again when you are done.")

    def _ask(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            raise CommandError("No terminal to ask on. Pass the values as arguments and use --no-input.")

    def _password(self, interactive: bool, *, required: bool) -> str | None:
        env_password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not interactive:
            if required and not env_password:
                raise CommandError("Set DJANGO_SUPERUSER_PASSWORD (with --no-input).")
            if env_password:
                self._validate(env_password)
            return env_password or None
        hint = "" if required else " (Enter keeps the current one)"
        while True:
            first = getpass.getpass(f"Password{hint}: ")
            if not first and not required:
                return None
            if first != getpass.getpass("Password again: "):
                self.stderr.write("The passwords do not match. Try again.")
                continue
            try:
                self._validate(first)
            except CommandError as exc:
                self.stderr.write(str(exc))
                continue
            return first

    @staticmethod
    def _validate(password: str) -> None:
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages))
