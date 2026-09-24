from typing import Optional
from uuid import UUID

from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from addresses.models import Address


class AddressDataAccessLayer:
    @staticmethod
    def count_active_for_user(user_id: UUID) -> int:
        return Address.objects.filter(user_id=user_id).count()

    @staticmethod
    def list_for_user(user_id: UUID) -> QuerySet[Address]:
        return (
            Address.objects.filter(user_id=user_id)
            .select_related("user", "verified_by")
            .order_by("-is_default", "-created_at")
        )

    @staticmethod
    def search_for_user(
        user_id: UUID,
        *,
        query: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        title: str | None = None,
        ordering: str | None = None,
    ) -> QuerySet[Address]:
        qs = AddressDataAccessLayer.list_for_user(user_id)
        if query:
            qs = qs.filter(
                Q(street__icontains=query)
                | Q(district__icontains=query)
                | Q(city__icontains=query)
                | Q(postal_code__icontains=query)
                | Q(formatted_address__icontains=query)
                | Q(title__icontains=query)
            )
        if city:
            qs = qs.filter(city__icontains=city)
        if postal_code:
            qs = qs.filter(postal_code__icontains=postal_code)
        if title:
            qs = qs.filter(title__icontains=title)
        if ordering:
            allowed = {
                "created_at", "-created_at", "city", "-city", "title", "-title",
                "postal_code", "-postal_code", "formatted_address", "-formatted_address",
            }
            if ordering in allowed:
                qs = qs.order_by(ordering)
        return qs

    @staticmethod
    def get_for_user(address_id: UUID, user_id: UUID) -> Optional[Address]:
        return (
            Address.objects.filter(pk=address_id, user_id=user_id)
            .select_related("user", "verified_by")
            .first()
        )

    @staticmethod
    def get_for_user_by_legacy_id(legacy_id: int, user_id: UUID) -> Optional[Address]:
        return (
            Address.objects.filter(legacy_id=legacy_id, user_id=user_id)
            .select_related("user", "verified_by")
            .first()
        )

    @staticmethod
    def get_for_user_for_update(address_id: UUID, user_id: UUID) -> Optional[Address]:
        return (
            Address.objects.select_for_update()
            .filter(pk=address_id, user_id=user_id)
            .first()
        )

    @staticmethod
    def get_deleted_for_user_for_update(address_id: UUID, user_id: UUID) -> Optional[Address]:
        return (
            Address.all_objects.select_for_update()
            .filter(pk=address_id, user_id=user_id, deleted_at__isnull=False)
            .first()
        )

    @staticmethod
    def get_by_id(address_id: UUID) -> Optional[Address]:
        return Address.objects.select_related("user", "verified_by").filter(pk=address_id).first()

    @staticmethod
    def fingerprint_exists(user_id: UUID, fingerprint: str, exclude_id: UUID | None = None) -> bool:
        qs = Address.objects.filter(user_id=user_id, fingerprint=fingerprint)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.exists()

    @staticmethod
    def allocate_legacy_id() -> int:
        """Next integer id for the legacy /api/orders/addresses/ contract."""
        current = Address.all_objects.aggregate(max_id=Max("legacy_id"))["max_id"] or 0
        return int(current) + 1

    @staticmethod
    def create_address(**fields) -> Address:
        return Address.objects.create(**fields)

    @staticmethod
    def update_fields(address: Address, **fields) -> Address:
        for name, value in fields.items():
            setattr(address, name, value)
        update_names = list(fields.keys()) + ["fingerprint", "updated_at", "label"]
        address.save(update_fields=list(dict.fromkeys(update_names)))
        return address

    @staticmethod
    def unset_default_addresses(user_id: UUID, exclude_id: UUID | None = None) -> None:
        qs = Address.objects.filter(user_id=user_id, is_default=True)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        qs.update(is_default=False)

    @staticmethod
    def soft_delete(address: Address) -> None:
        address.deleted_at = timezone.now()
        address.is_default = False
        address.save(update_fields=["deleted_at", "is_default", "updated_at"])

    @staticmethod
    def restore(address: Address) -> None:
        address.deleted_at = None
        address.save(update_fields=["deleted_at", "updated_at"])

    @staticmethod
    def get_next_default_candidate(user_id: UUID, exclude_id: UUID) -> Optional[Address]:
        return (
            Address.objects.filter(user_id=user_id)
            .exclude(pk=exclude_id)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def lock_user_addresses(user_id: UUID) -> None:
        list(Address.objects.select_for_update().filter(user_id=user_id))
