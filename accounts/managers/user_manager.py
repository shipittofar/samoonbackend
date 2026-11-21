from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):

    def __init__(self, *args, include_deleted: bool = False, **kwargs):
        self._include_deleted = include_deleted
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        if not self._include_deleted:
            qs = qs.filter(is_deleted=False)
        return qs

    def create_user(self, phone_number: str = None, email: str = None, **extra_fields):
        if not phone_number and not email:
            raise ValueError("Either phone_number or email is required")

        user = self.model(phone_number=phone_number, email=email, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number: str, password: str, **extra_fields):
        """Used by Django's ``createsuperuser``. Only the very first superuser
        may be made this way; later ones go through ``manage.py admin_add`` and
        need a superuser's approval in the Django admin."""
        if self.model.objects.filter(is_superuser=True, is_active=True).exists():
            raise ValueError(
                "A superuser already exists. Use `manage.py admin_add` "
                "(`samoon admin-add` on the server): new superusers need approval."
            )
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user