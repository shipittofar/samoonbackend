from django.utils import timezone
from accounts.models import User
from core.exceptions.account import AvatarNotSetException, AccountAlreadyDeletedException
from uploads.services.compat import apply_image_input


class ProfileBusinessLogicLayer:

    @classmethod
    def update_profile(cls, user: User, first_name: str = None, last_name: str = None) -> User:
        updated_fields = []
        if first_name is not None:
            user.first_name = first_name
            updated_fields.append("first_name")
        if last_name is not None:
            user.last_name = last_name
            updated_fields.append("last_name")

        if updated_fields:
            user.save(update_fields=updated_fields)
        return user

    @classmethod
    def set_avatar(
        cls,
        user: User,
        avatar=None,
        avatar_asset_id=None,
        avatar_provided: bool = False,
        avatar_asset_id_provided: bool = False,
    ) -> User:
        if not avatar_provided and not avatar_asset_id_provided:
            avatar_provided = avatar is not None
            avatar_asset_id_provided = avatar_asset_id is not None
        fields = apply_image_input(
            instance=user,
            user=user,
            image_field="avatar",
            asset_fk="avatar_asset",
            purpose="user_avatar",
            tenant_id=None,
            file=avatar,
            file_provided=avatar_provided,
            asset_id=avatar_asset_id,
            asset_id_provided=avatar_asset_id_provided,
            entity_type="user",
            entity_id=str(user.id),
            ingest_legacy=True,
        )
        if fields:
            user.save(update_fields=list(dict.fromkeys(fields)))
        return user

    @classmethod
    def delete_avatar(cls, user: User) -> User:
        if not user.avatar and not user.avatar_asset_id:
            raise AvatarNotSetException()
        fields = apply_image_input(
            instance=user,
            user=user,
            image_field="avatar",
            asset_fk="avatar_asset",
            purpose="user_avatar",
            file=None,
            file_provided=True,
            asset_id=None,
            asset_id_provided=False,
            entity_type="user",
            entity_id=str(user.id),
            ingest_legacy=True,
        )
        user.save(update_fields=list(dict.fromkeys(fields or ["avatar", "avatar_asset"])))
        return user

    @classmethod
    def soft_delete(cls, user: User) -> None:
        if user.is_deleted:
            raise AccountAlreadyDeletedException()
        # Give the phone and email back so the person can sign up again; keep
        # the old values for support and for restore().
        user.deleted_phone_number = user.phone_number
        user.deleted_email = user.email
        user.phone_number = None
        user.email = None
        user.is_deleted = True
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(update_fields=[
            "deleted_phone_number", "deleted_email", "phone_number", "email",
            "is_deleted", "is_active", "deleted_at",
        ])
        _revoke_all_tokens(user)

    @classmethod
    def restore(cls, user: User) -> User:
        """Undo soft_delete. Refused when the phone or email was taken by an
        account created after the deletion."""
        if not user.is_deleted:
            return user
        phone, email = user.deleted_phone_number, user.deleted_email
        others = User.objects.exclude(pk=user.pk)
        if phone and others.filter(phone_number=phone).exists():
            raise AccountRestoreConflict(f"{phone} now belongs to another account.")
        if email and others.filter(email=email).exists():
            raise AccountRestoreConflict(f"{email} now belongs to another account.")
        user.phone_number, user.email = phone, email
        user.deleted_phone_number = user.deleted_email = None
        user.is_deleted = False
        user.is_active = True
        user.deleted_at = None
        user.save(update_fields=[
            "deleted_phone_number", "deleted_email", "phone_number", "email",
            "is_deleted", "is_active", "deleted_at",
        ])
        return user


class AccountRestoreConflict(Exception):
    """The message is shown to the admin."""


def _revoke_all_tokens(user: User) -> None:
    """Sign a deleted account out everywhere (refresh and access tokens)."""
    from accounts.services.session_revocation import revoke_all_sessions

    revoke_all_sessions(user)
