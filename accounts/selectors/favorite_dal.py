from django.db.models import QuerySet

from accounts.models import Favorite
from menu.models import MenuItem


class FavoriteDataAccessLayer:

    @staticmethod
    def favorites_queryset_for_user(user_id, *, branch_id=None) -> QuerySet[Favorite]:
        queryset = (
            Favorite.objects.filter(
                user_id=user_id,
                menu_item__deleted_at__isnull=True,
            )
            .select_related(
                "menu_item",
                "menu_item__branch",
                "menu_item__branch__tenant",
            )
            .order_by("-created_at")
        )
        if branch_id is not None:
            queryset = queryset.filter(menu_item__branch_id=branch_id)
        return queryset

    @staticmethod
    def list_menu_item_ids_for_user(user_id, *, branch_id=None) -> list:
        queryset = FavoriteDataAccessLayer.favorites_queryset_for_user(
            user_id,
            branch_id=branch_id,
        )
        return list(queryset.values_list("menu_item_id", flat=True))

    @staticmethod
    def get_favorite_for_user(user_id, menu_item_id) -> Favorite | None:
        return (
            FavoriteDataAccessLayer.favorites_queryset_for_user(user_id)
            .filter(menu_item_id=menu_item_id)
            .first()
        )

    @staticmethod
    def get_favoritable_menu_item(item_id) -> MenuItem | None:
        return (
            MenuItem.objects.select_related("branch", "branch__tenant")
            .filter(
                id=item_id,
                deleted_at__isnull=True,
                is_active=True,
            )
            .first()
        )

    @staticmethod
    def create_favorite(user, menu_item: MenuItem) -> tuple[Favorite, bool]:
        favorite, created = Favorite.objects.get_or_create(
            user=user,
            menu_item=menu_item,
        )
        if created:
            favorite = (
                FavoriteDataAccessLayer.favorites_queryset_for_user(user.id)
                .get(id=favorite.id)
            )
        return favorite, created

    @staticmethod
    def delete_favorite(user_id, menu_item_id) -> bool:
        deleted_count, _ = Favorite.objects.filter(
            user_id=user_id,
            menu_item_id=menu_item_id,
        ).delete()
        return deleted_count > 0
