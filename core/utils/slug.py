import secrets
import string

DEFAULT_SLUG_LENGTH = 8
SLUG_ALPHABET = string.ascii_lowercase + string.digits


def generate_random_slug(length: int = DEFAULT_SLUG_LENGTH) -> str:
    """Generate a random URL-safe slug using lowercase letters and digits."""
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(length))


def assign_unique_slug(instance, model_class, length: int = DEFAULT_SLUG_LENGTH) -> None:
    """
    Assign a unique random slug to instance.slug if it is not already set.
    Retries generation until a non-colliding slug is found.
    """
    if instance.slug:
        return

    slug = generate_random_slug(length)
    while model_class.objects.filter(slug=slug).exists():
        slug = generate_random_slug(length)
    instance.slug = slug


def assign_unique_branch_slug(
    instance,
    model_class,
    *,
    branch_field: str = "branch_id",
    length: int = DEFAULT_SLUG_LENGTH,
) -> None:
    """
    Assign a slug unique within the instance's branch.
    Falls back to global uniqueness when branch is unset.
    """
    if instance.slug:
        return

    branch_id = getattr(instance, branch_field, None)
    slug = generate_random_slug(length)
    while _branch_slug_exists(model_class, branch_id, slug):
        slug = generate_random_slug(length)
    instance.slug = slug


def _branch_slug_exists(model_class, branch_id, slug: str) -> bool:
    if branch_id is None:
        return model_class.objects.filter(slug=slug).exists()
    return model_class.objects.filter(branch_id=branch_id, slug=slug).exists()