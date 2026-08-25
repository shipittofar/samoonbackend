from django.utils import timezone
from accounts.models import User
from core.exceptions.account import AvatarNotSetException, AccountAlreadyDeletedException


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
    def set_avatar(cls, user: User, avatar) -> User:
        if user.avatar:
            user.avatar.delete(save=False)
        user.avatar = avatar
        user.save(update_fields=["avatar"])
        return user

    @classmethod
    def delete_avatar(cls, user: User) -> User:
        if not user.avatar:
            raise AvatarNotSetException()
        user.avatar.delete(save=False)
        user.avatar = None
        user.save(update_fields=["avatar"])
        return user

    @classmethod
    def soft_delete(cls, user: User) -> None:
        if user.is_deleted:
            raise AccountAlreadyDeletedException()
        user.is_deleted = True
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(update_fields=["is_deleted", "is_active", "deleted_at"])