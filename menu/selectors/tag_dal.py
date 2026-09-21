from django.db import transaction
from django.db.models import Count, Q

from core.cache import CacheKeys, CacheTTL, cache_delete, cache_get, cache_set
from menu.models import Tag

TAG_TTL = CacheTTL.TAG


class TagDataAccessLayer:

    @staticmethod
    def _refresh_tag_list_cache(branch_id) -> list[Tag]:
        data = list(
            Tag.objects.filter(branch_id=branch_id).order_by(
                "display_order", "name"
            )
        )
        key = CacheKeys.TAG_LIST.format(branch_id=branch_id)
        cache_set(key, data, TAG_TTL)
        return data

    @staticmethod
    def _refresh_tag_detail_cache(tag_id, branch_id) -> Tag | None:
        instance = Tag.objects.filter(id=tag_id, branch_id=branch_id).first()
        key = CacheKeys.TAG_DETAIL.format(branch_id=branch_id, tag_id=tag_id)
        if instance is not None:
            cache_set(key, instance, TAG_TTL)
        else:
            cache_delete(key)
        return instance

    @staticmethod
    def invalidate_tag_cache(branch_id, tag_id=None) -> None:
        TagDataAccessLayer._refresh_tag_list_cache(branch_id)
        if tag_id is not None:
            TagDataAccessLayer._refresh_tag_detail_cache(tag_id, branch_id)

    @staticmethod
    def get_all_tags(branch_id, *, is_active: bool | None = None):
        tags = TagDataAccessLayer._get_cached_or_db_list(branch_id)
        if is_active is None:
            return tags
        return [tag for tag in tags if tag.is_active is is_active]

    @staticmethod
    def _get_cached_or_db_list(branch_id):
        key = CacheKeys.TAG_LIST.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return TagDataAccessLayer._refresh_tag_list_cache(branch_id)

    @staticmethod
    def get_tag_by_id(tag_id, branch_id) -> Tag | None:
        key = CacheKeys.TAG_DETAIL.format(branch_id=branch_id, tag_id=tag_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return TagDataAccessLayer._refresh_tag_detail_cache(tag_id, branch_id)

    @staticmethod
    def tag_exists(branch_id, *, name: str | None = None, slug: str | None = None, exclude_id=None) -> bool:
        qs = Tag.objects.filter(branch_id=branch_id)
        if name is not None:
            qs = qs.filter(name=name)
        if slug is not None:
            qs = qs.filter(slug=slug)
        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    @staticmethod
    def get_missing_tag_ids(tag_ids: set, branch_id) -> set:
        if not tag_ids:
            return set()
        existing = set(
            Tag.objects.filter(
                id__in=tag_ids,
                branch_id=branch_id,
            ).values_list("id", flat=True)
        )
        return tag_ids - existing

    @staticmethod
    def get_available_tags(branch_id, *, include_item_count: bool = True):
        qs = Tag.objects.filter(branch_id=branch_id, is_active=True).order_by(
            "display_order", "name"
        )
        if include_item_count:
            qs = qs.annotate(
                item_count=Count(
                    "items",
                    filter=Q(items__is_active=True),
                    distinct=True,
                )
            )
        return qs

    @staticmethod
    def filter_tags_queryset(
        branch_id,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        ordering: str | None = None,
    ):
        qs = Tag.objects.filter(branch_id=branch_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(slug__icontains=search)
                | Q(description__icontains=search)
            )

        allowed_ordering = {
            "display_order": "display_order",
            "-display_order": "-display_order",
            "name": "name",
            "-name": "-name",
            "created_at": "created_at",
            "-created_at": "-created_at",
        }
        if ordering in allowed_ordering:
            qs = qs.order_by(allowed_ordering[ordering], "name")
        else:
            qs = qs.order_by("display_order", "name")
        return qs

    @staticmethod
    def create_tag(
        branch_id,
        name: str,
        *,
        slug: str = "",
        description: str = "",
        icon: str = "",
        image=None,
        color: str = "",
        is_active: bool = True,
        display_order: int = 0,
    ) -> Tag:
        tag = Tag(
            branch_id=branch_id,
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            color=color,
            is_active=is_active,
            display_order=display_order,
        )
        if image is not None:
            tag.image = image
        tag.save()

        transaction.on_commit(
            lambda: TagDataAccessLayer.invalidate_tag_cache(branch_id, tag.id)
        )
        return tag

    @staticmethod
    def update_tag(
        tag: Tag,
        *,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        image=None,
        image_provided: bool = False,
        color: str | None = None,
        is_active: bool | None = None,
        display_order: int | None = None,
    ) -> Tag:
        if name is not None:
            tag.name = name
        if slug is not None:
            tag.slug = slug
        if description is not None:
            tag.description = description
        if icon is not None:
            tag.icon = icon
        if image_provided:
            if tag.image:
                tag.image.delete(save=False)
            tag.image = image
        if color is not None:
            tag.color = color
        if is_active is not None:
            tag.is_active = is_active
        if display_order is not None:
            tag.display_order = display_order
        tag.save()

        transaction.on_commit(
            lambda: TagDataAccessLayer.invalidate_tag_cache(
                tag.branch_id, tag.id
            )
        )
        return tag

    @staticmethod
    def delete_tag(tag: Tag) -> None:
        branch_id, tag_id = tag.branch_id, tag.id
        if tag.items.exists():
            tag.is_active = False
            tag.save(update_fields=["is_active", "updated_at"])
            transaction.on_commit(
                lambda: TagDataAccessLayer._refresh_tag_list_cache(branch_id)
            )
            return

        tag.delete()

        def _on_commit():
            TagDataAccessLayer._refresh_tag_list_cache(branch_id)
            cache_delete(
                CacheKeys.TAG_DETAIL.format(branch_id=branch_id, tag_id=tag_id)
            )

        transaction.on_commit(_on_commit)
