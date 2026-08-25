import re

from menu.models import Tag
from menu.selectors import CategoryDataAccessLayer, TagDataAccessLayer
from core.exceptions import (
    BranchNotFoundException,
    TagAlreadyExistsException,
    TagNotFoundException,
    TagValidationException,
)

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

category_dal = CategoryDataAccessLayer()
tag_dal = TagDataAccessLayer()


class TagBusinessLogicLayer:

    @staticmethod
    def _validate_color(color: str | None) -> None:
        if color and not HEX_COLOR_PATTERN.match(color):
            raise TagValidationException("Color must be a valid HEX value like #2ecc71.")

    @staticmethod
    def _validate_icon(icon: str | None) -> None:
        if icon and len(icon) > 16:
            raise TagValidationException("Icon must be at most 16 characters.")

    @staticmethod
    def _validate_display_order(display_order: int | None) -> None:
        if display_order is not None and display_order < 0:
            raise TagValidationException(
                "display_order must be greater than or equal to 0."
            )

    @staticmethod
    def _validate_image(image) -> None:
        if image is None:
            return
        content_type = getattr(image, "content_type", None)
        if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise TagValidationException(
                "Image must be JPEG, PNG, WebP, or GIF."
            )

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
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        TagBusinessLogicLayer._validate_color(color)
        TagBusinessLogicLayer._validate_icon(icon)
        TagBusinessLogicLayer._validate_display_order(display_order)
        TagBusinessLogicLayer._validate_image(image)

        if tag_dal.tag_exists(branch_id, name=name):
            raise TagAlreadyExistsException()

        if slug and tag_dal.tag_exists(branch_id, slug=slug):
            raise TagAlreadyExistsException()

        return tag_dal.create_tag(
            branch_id=branch_id,
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            image=image,
            color=color,
            is_active=is_active,
            display_order=display_order,
        )

    @staticmethod
    def update_tag(
        tag_id,
        branch_id,
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
        tag = tag_dal.get_tag_by_id(tag_id, branch_id)
        if tag is None:
            raise TagNotFoundException()

        TagBusinessLogicLayer._validate_color(color)
        TagBusinessLogicLayer._validate_icon(icon)
        TagBusinessLogicLayer._validate_display_order(display_order)
        if image_provided:
            TagBusinessLogicLayer._validate_image(image)

        if name is not None and tag_dal.tag_exists(
            branch_id, name=name, exclude_id=tag_id
        ):
            raise TagAlreadyExistsException()

        if slug is not None and slug and tag_dal.tag_exists(
            branch_id, slug=slug, exclude_id=tag_id
        ):
            raise TagAlreadyExistsException()

        return tag_dal.update_tag(
            tag=tag,
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            image=image,
            image_provided=image_provided,
            color=color,
            is_active=is_active,
            display_order=display_order,
        )

    @staticmethod
    def get_tag_list(
        branch_id,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        ordering: str | None = None,
    ):
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()
        return tag_dal.filter_tags_queryset(
            branch_id,
            search=search,
            is_active=is_active,
            ordering=ordering,
        )

    @staticmethod
    def get_tag_detail(tag_id, branch_id) -> Tag:
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        tag = tag_dal.get_tag_by_id(tag_id, branch_id)
        if tag is None:
            raise TagNotFoundException()
        return tag

    @staticmethod
    def delete_tag(tag_id, branch_id) -> None:
        tag = tag_dal.get_tag_by_id(tag_id, branch_id)
        if tag is None:
            raise TagNotFoundException()
        tag_dal.delete_tag(tag)

    @staticmethod
    def get_available_tags(branch_id, *, include_item_count: bool = True):
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()
        return tag_dal.get_available_tags(
            branch_id,
            include_item_count=include_item_count,
        )
