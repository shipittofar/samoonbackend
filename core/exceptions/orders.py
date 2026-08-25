# orders/exceptions.py
from core.exceptions import BaseAppException


class OrderNotFoundException(BaseAppException):
    status_code = 404
    code = "order_not_found"
    message = "Order not found."


class TenantNotFoundException(BaseAppException):
    status_code = 404
    code = "tenant_not_found"
    message = "Tenant not found or inactive."


class DeliveryAddressRequiredException(BaseAppException):
    status_code = 400
    code = "delivery_address_required"
    message = "Delivery address is required for delivery orders."


class TableNumberRequiredException(BaseAppException):
    status_code = 400
    code = "table_number_required"
    message = "Table number is required for dine-in orders."


class MenuItemNotFoundException(BaseAppException):
    status_code = 400
    code = "menu_item_not_found"
    message = "One or more menu items were not found or are inactive."


class MenuItemNotInTenantException(BaseAppException):
    status_code = 400
    code = "menu_item_not_in_tenant"
    message = "One or more menu items do not belong to this tenant."


class ExtraNotAvailableException(BaseAppException):
    status_code = 400
    code = "extra_not_available"
    message = "One or more extras are not available for the selected item."


class MenuItemUnavailableException(BaseAppException):
    status_code = 400
    code = "menu_item_unavailable"
    message = "One or more menu items are currently unavailable for ordering."


class InvalidDiscountCodeException(BaseAppException):
    status_code = 400
    code = "invalid_discount_code"
    message = "Discount code is invalid or expired."


class OrderNotEditableException(BaseAppException):
    status_code = 400
    code = "order_not_editable"
    message = "Order can no longer be edited."


class OrderNotCancellableException(BaseAppException):
    status_code = 400
    code = "order_not_cancellable"
    message = "Order can no longer be cancelled."


class OrderAlreadyCancelledException(BaseAppException):
    status_code = 400
    code = "order_already_cancelled"
    message = "Order is already cancelled."


class InvalidOrderStatusTransitionException(BaseAppException):
    status_code = 400
    code = "invalid_order_status_transition"
    message = "This status transition is not allowed."


class NotTenantOwnerException(BaseAppException):
    status_code = 403
    code = "not_tenant_owner"
    message = "You do not have permission to manage this tenant's orders."


class OrderingDisabledException(BaseAppException):
    status_code = 400
    code = "ordering_disabled"
    message = "Ordering is not enabled for this branch."


class OrderTypeNotEnabledException(BaseAppException):
    status_code = 400
    code = "order_type_not_enabled"
    message = "This order type is not enabled for this branch."


class PaymentMethodNotEnabledException(BaseAppException):
    status_code = 400
    code = "payment_method_not_enabled"
    message = "This payment method is not enabled for this branch."


class CashOnDeliveryNotEnabledException(BaseAppException):
    status_code = 400
    code = "cash_on_delivery_not_enabled"
    message = "Cash on delivery is not available for this branch."


class MinimumOrderNotMetException(BaseAppException):
    status_code = 400
    code = "minimum_order_not_met"
    message = "Order subtotal does not meet the minimum order amount."