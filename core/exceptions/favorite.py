from core.exceptions import BaseAppException


class FavoriteMenuItemNotFoundException(BaseAppException):
    status_code = 404
    code = "favorite_menu_item_not_found"
    message = "Menu item not found or is no longer available."


class FavoriteMenuItemNotFavoritableException(BaseAppException):
    status_code = 400
    code = "favorite_menu_item_not_favoritable"
    message = "This menu item cannot be added to favorites."


class FavoriteSyncVersionMismatchException(BaseAppException):
    status_code = 409
    code = "favorite_sync_version_mismatch"
    message = "Favorites have changed on the server. Refresh and try again."
