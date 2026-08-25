from decimal import Decimal

from rest_framework import serializers


class BranchMetricsStaffDetailsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    inactive = serializers.IntegerField()
    tenantWideAssignments = serializers.IntegerField(
        source="tenant_wide_assignments"
    )
    managerIncluded = serializers.BooleanField(source="manager_included")


class BranchMetricsReservationDetailsSerializer(serializers.Serializer):
    implemented = serializers.BooleanField()
    value = serializers.IntegerField()


class BranchMetricsCalculationDetailsSerializer(serializers.Serializer):
    orderDateField = serializers.CharField(source="order_date_field")
    period = serializers.CharField()


class BranchMetricsDetailsSerializer(serializers.Serializer):
    cancelledOrders = serializers.IntegerField(source="cancelled_orders")
    refundedOrders = serializers.IntegerField(source="refunded_orders")
    failedPayments = serializers.IntegerField(source="failed_payments")
    pendingOrders = serializers.IntegerField(source="pending_orders")
    completedOrders = serializers.IntegerField(source="completed_orders")
    guestOrders = serializers.IntegerField(source="guest_orders")
    paidOrders = serializers.IntegerField(source="paid_orders")
    staff = BranchMetricsStaffDetailsSerializer()
    reservation = BranchMetricsReservationDetailsSerializer()
    calculation = BranchMetricsCalculationDetailsSerializer()


class BranchMetricsResponseSerializer(serializers.Serializer):
    branchId = serializers.UUIDField(source="branch_id")
    totalOrders = serializers.IntegerField(source="total_orders")
    totalRevenue = serializers.SerializerMethodField()
    totalReservations = serializers.IntegerField(source="total_reservations")
    totalCustomers = serializers.IntegerField(source="total_customers")
    staffCount = serializers.IntegerField(source="staff_count")
    averageOrderValue = serializers.SerializerMethodField()
    period = serializers.CharField()
    details = BranchMetricsDetailsSerializer()

    def get_totalRevenue(self, obj) -> float:
        value = obj["total_revenue"]
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def get_averageOrderValue(self, obj) -> float:
        value = obj["average_order_value"]
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
