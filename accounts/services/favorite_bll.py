from django.db import transaction

from accounts.selectors.favorite_dal import FavoriteDataAccessLayer
from accounts.utils.favorite_sync import compute_favorites_sync_state
from core.exceptions.favorite import (
    FavoriteMenuItemNotFoundException,
    FavoriteMenuItemNotFavoritableException,
)
from menu.models import MenuItem

favorite_dal = FavoriteDataAccessLayer()


class FavoriteBusinessLogicLayer:

    @staticmethod
    def get_sync_state(user, *, branch_id=None) -> dict:
        sync = compute_favorites_sync_state(user_id=user.id, branch_id=branch_id)
        favorite_ids = favorite_dal.list_menu_item_ids_for_user(
            user.id,
            branch_id=branch_id,
        )
        return {
            "sync": sync,
            "favorite_ids": favorite_ids,
        }

    @staticmethod
    def list_favorites(user, *, branch_id=None):
        return favorite_dal.favorites_queryset_for_user(user.id, branch_id=branch_id)

    @staticmethod
    @transaction.atomic
    def add_favorite(user, menu_item_id) -> dict:
        existing = favorite_dal.get_favorite_for_user(user.id, menu_item_id)
        if existing is not None:
            sync = compute_favorites_sync_state(user_id=user.id)
            return {
                "favorite": existing,
                "sync": sync,
                "created": False,
            }

        menu_item = favorite_dal.get_favoritable_menu_item(menu_item_id)
        if menu_item is not None:
            favorite, created = favorite_dal.create_favorite(user, menu_item)
            sync = compute_favorites_sync_state(user_id=user.id)
            return {
                "favorite": favorite,
                "sync": sync,
                "created": created,
            }

        item = MenuItem.objects.filter(id=menu_item_id).only("id", "deleted_at", "is_active").first()
        if item is None or item.deleted_at is not None:
            raise FavoriteMenuItemNotFoundException()
        if not item.is_active:
            raise FavoriteMenuItemNotFavoritableException()
        raise FavoriteMenuItemNotFoundException()

    @staticmethod
    @transaction.atomic
    def remove_favorite(user, menu_item_id) -> dict:
        removed = favorite_dal.delete_favorite(user.id, menu_item_id)
        sync = compute_favorites_sync_state(user_id=user.id)
        return {
            "removed": removed,
            "menu_item_id": menu_item_id,
            "sync": sync,
        }
