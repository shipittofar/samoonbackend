from dataclasses import dataclass


IMAGE_MIME_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})

IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_DIMENSION = 1600
WEBP_QUALITY = 80
THUMBNAIL_MAX = 400
MEDIUM_MAX = 800


@dataclass(frozen=True)
class PurposePolicy:
    purpose: str
    allowed_mime_types: frozenset[str]
    allowed_extensions: frozenset[str]
    max_bytes: int
    require_image: bool
    variant_profile: str
    max_dimension: int
    allow_multiple: bool
    tenant_required: bool
    permission_slug: str | None
    # "self" | "tenant_settings" | "branch_settings" | "menu"
    authz: str


_IMAGE_POLICY = dict(
    allowed_mime_types=IMAGE_MIME_TYPES,
    allowed_extensions=IMAGE_EXTENSIONS,
    max_bytes=DEFAULT_MAX_BYTES,
    require_image=True,
    variant_profile="image",
    max_dimension=DEFAULT_MAX_DIMENSION,
    allow_multiple=False,
)

PURPOSE_REGISTRY: dict[str, PurposePolicy] = {
    "user_avatar": PurposePolicy(
        purpose="user_avatar",
        tenant_required=False,
        permission_slug=None,
        authz="self",
        **_IMAGE_POLICY,
    ),
    "tenant_logo": PurposePolicy(
        purpose="tenant_logo",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="tenant_settings",
        **_IMAGE_POLICY,
    ),
    "tenant_discover_avatar": PurposePolicy(
        purpose="tenant_discover_avatar",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="tenant_settings",
        **_IMAGE_POLICY,
    ),
    "tenant_discover_cover": PurposePolicy(
        purpose="tenant_discover_cover",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="tenant_settings",
        **_IMAGE_POLICY,
    ),
    "tenant_hero": PurposePolicy(
        purpose="tenant_hero",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="tenant_settings",
        **_IMAGE_POLICY,
    ),
    "branch_logo": PurposePolicy(
        purpose="branch_logo",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="branch_settings",
        **_IMAGE_POLICY,
    ),
    "branch_cover": PurposePolicy(
        purpose="branch_cover",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="branch_settings",
        **_IMAGE_POLICY,
    ),
    "branch_hero": PurposePolicy(
        purpose="branch_hero",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="branch_settings",
        **_IMAGE_POLICY,
    ),
    "menu_item": PurposePolicy(
        purpose="menu_item",
        tenant_required=True,
        permission_slug="menu.manage",
        authz="menu",
        **_IMAGE_POLICY,
    ),
    "menu_category": PurposePolicy(
        purpose="menu_category",
        tenant_required=True,
        permission_slug="menu.manage",
        authz="menu",
        **_IMAGE_POLICY,
    ),
    "menu_tag": PurposePolicy(
        purpose="menu_tag",
        tenant_required=True,
        permission_slug="menu.manage",
        authz="menu",
        **_IMAGE_POLICY,
    ),
    "website_media": PurposePolicy(
        purpose="website_media",
        tenant_required=True,
        permission_slug="settings.edit",
        authz="tenant_settings",
        allowed_mime_types=IMAGE_MIME_TYPES,
        allowed_extensions=IMAGE_EXTENSIONS,
        max_bytes=DEFAULT_MAX_BYTES,
        require_image=True,
        variant_profile="image",
        max_dimension=DEFAULT_MAX_DIMENSION,
        allow_multiple=True,
    ),
}


def get_purpose(purpose: str) -> PurposePolicy:
    policy = PURPOSE_REGISTRY.get(purpose)
    if policy is None:
        from core.exceptions.uploads import UploadValidationException

        raise UploadValidationException(f"Unknown upload purpose: {purpose}")
    return policy
