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
        user.is_deleted = True
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(update_fields=["is_deleted", "is_active", "deleted_at"])
