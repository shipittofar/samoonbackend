"""Menu templates: validate their content and copy one into a branch."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import ValidationError

from menu.authorization.branch_menu import assert_branch_menu_write
from menu.models import MenuCategory, MenuItem, MenuTemplate
from menu.selectors.category_dal import CategoryDataAccessLayer
from menu.selectors.item_dal import ItemDataAccessLayer

MAX_CATEGORIES = 50
MAX_ITEMS_PER_CATEGORY = 100


def _text(value, field: str, *, required: bool = False, max_length: int = 255) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValidationError({"content": f"{field} is required."})
    if len(text) > max_length:
        raise ValidationError({"content": f"{field} is too long (max {max_length})."})
    return text


def _optional_int(value, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError({"content": f"{field} must be a whole number."})
    if number < 0:
        raise ValidationError({"content": f"{field} cannot be negative."})
    return number


def validate_content(content) -> dict:
    """Normalised ``{"categories": [...]}``; raises ValidationError."""
    if not isinstance(content, dict):
        raise ValidationError({"content": "content must be an object with a categories list."})
    categories = content.get("categories") or []
    if not isinstance(categories, list):
        raise ValidationError({"content": "categories must be a list."})
    if len(categories) > MAX_CATEGORIES:
        raise ValidationError({"content": f"At most {MAX_CATEGORIES} categories."})

    clean_categories = []
    seen_categories = set()
    for c_index, category in enumerate(categories, start=1):
        if not isinstance(category, dict):
            raise ValidationError({"content": f"Category {c_index} must be an object."})
        name = _text(category.get("name"), f"Category {c_index} name", required=True)
        if name.lower() in seen_categories:
            raise ValidationError({"content": f"Category '{name}' appears twice."})
        seen_categories.add(name.lower())
        items = category.get("items") or []
        if not isinstance(items, list) or len(items) > MAX_ITEMS_PER_CATEGORY:
            raise ValidationError(
                {"content": f"Category '{name}': items must be a list of at most {MAX_ITEMS_PER_CATEGORY}."}
            )
        clean_items = []
        seen_items = set()
        for i_index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValidationError({"content": f"'{name}' item {i_index} must be an object."})
            item_name = _text(item.get("name"), f"'{name}' item {i_index} name", required=True)
            if item_name.lower() in seen_items:
                raise ValidationError({"content": f"Item '{item_name}' appears twice in '{name}'."})
            seen_items.add(item_name.lower())
            try:
                price = Decimal(str(item.get("price") if item.get("price") not in (None, "") else "0"))
            except InvalidOperation:
                raise ValidationError({"content": f"Item '{item_name}': price must be a number."})
            if price < 0 or price >= Decimal("100000000"):
                raise ValidationError({"content": f"Item '{item_name}': price is out of range."})
            clean_items.append({
                "name": item_name,
                "description": _text(item.get("description"), f"Item '{item_name}' description", max_length=2000),
                "price": str(price.quantize(Decimal("0.01"))),
                "preparation_time": _optional_int(item.get("preparation_time"), f"Item '{item_name}' preparation_time"),
                "calories": _optional_int(item.get("calories"), f"Item '{item_name}' calories"),
            })
        clean_categories.append({
            "name": name,
            "description": _text(category.get("description"), f"Category '{name}' description", max_length=2000),
            "items": clean_items,
        })
    return {"categories": clean_categories}


def templates_for_tenant(tenant):
    """Active templates for the tenant's business types (all active ones when
    the tenant has not chosen a type yet)."""
    qs = MenuTemplate.objects.filter(is_active=True)
    types = [t for t in (tenant.business_types or []) if t]
    if types:
        qs = qs.filter(business_type__in=types)
    return qs


@transaction.atomic
def apply_template(*, template: MenuTemplate, branch_id, user) -> dict:
    """Copy the template into the branch. Existing categories with the same
    name are reused and existing items (same name in that category) are left
    untouched, so applying twice adds nothing twice."""
    branch = assert_branch_menu_write(user, branch_id)
    if not template.is_active and not user.is_superuser:
        raise ValidationError({"template": "This template is not available."})

    created_categories = created_items = skipped_items = 0
    next_order = (
        MenuCategory.objects.filter(branch_id=branch.id).order_by("-sort_order")
        .values_list("sort_order", flat=True).first() or 0
    )
    for category_data in validate_content(template.content)["categories"]:
        category = MenuCategory.objects.filter(branch_id=branch.id, name=category_data["name"]).first()
        if category is None:
            next_order += 1
            category = CategoryDataAccessLayer.create_category(
                branch_id=branch.id,
                name=category_data["name"],
                description=category_data["description"],
                sort_order=next_order,
            )
            created_categories += 1
        for item_data in category_data["items"]:
            if MenuItem.all_objects.filter(category_id=category.id, name=item_data["name"]).exists():
                skipped_items += 1
                continue
            ItemDataAccessLayer.create_item(
                branch_id=branch.id,
                category_id=category.id,
                name=item_data["name"],
                price=Decimal(item_data["price"]),
                description=item_data["description"],
                calories=item_data["calories"],
                preparation_time=item_data["preparation_time"],
            )
            created_items += 1
    return {
        "created_categories": created_categories,
        "created_items": created_items,
        "skipped_items": skipped_items,
    }
