from rest_framework.throttling import UserRateThrottle


class AddressCreateThrottle(UserRateThrottle):
    scope = "address_create"


class AddressUpdateThrottle(UserRateThrottle):
    scope = "address_update"


class AddressDeleteThrottle(UserRateThrottle):
    scope = "address_delete"


class AddressReadThrottle(UserRateThrottle):
    scope = "address_read"
