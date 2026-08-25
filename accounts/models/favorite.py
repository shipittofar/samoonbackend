import uuid

from django.conf import settings
from django.db import models


class Favorite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    menu_item = models.ForeignKey(
        "menu.MenuItem",
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_favorite"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "menu_item"],
                name="unique_user_menu_item_favorite",
            ),
        ]
        indexes = [
            models.Index(fields=["user"], name="user_favorite_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} → {self.menu_item_id}"
