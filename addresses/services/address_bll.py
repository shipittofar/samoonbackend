"""Thin facade — all logic lives in AddressDomainService."""

from addresses.services.address_domain_service import AddressDomainService

_address_domain = AddressDomainService()


class AddressBusinessLogicLayer:
    """Backward-compatible alias delegating to AddressDomainService."""

    def __init__(self, domain: AddressDomainService | None = None):
        self.domain = domain or _address_domain

    def list_addresses(self, user, **kwargs):
        return self.domain.list_addresses(user, **kwargs)

    def get_address(self, user, address_id):
        return self.domain.get_address(user, address_id)

    def get_address_for_legacy_id(self, user, legacy_id):
        return self.domain.get_address(user, legacy_id)

    def create_address(self, user, validated_data, *, actor=None):
        return self.domain.create(user, validated_data, actor=actor)

    def update_address(self, user, address_id, validated_data, *, actor=None):
        return self.domain.update(user, address_id, validated_data, actor=actor)

    def delete_address(self, user, address_id, *, actor=None):
        return self.domain.delete(user, address_id, actor=actor)

    def restore_address(self, user, address_id, *, actor=None):
        return self.domain.restore(user, address_id, actor=actor)

    def set_default_address(self, user, address_id, *, actor=None):
        return self.domain.set_default(user, address_id, actor=actor)

    def resolve_checkout_snapshot(self, *, user, branch, delivery_data):
        return self.domain.resolve_checkout_snapshot(
            user=user, branch=branch, delivery_data=delivery_data
        )

    # Deprecated helpers kept for direct imports
    def snapshot_fields_from_address(self, address):
        return self.domain._snapshot_from_address(address)

    def snapshot_fields_from_raw(self, data):
        return self.domain._snapshot_from_raw(data)
