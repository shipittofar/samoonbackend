# orders/api/views.py
from rest_framework import generics, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from orders.services import OrdersBusinessLogicLayer
from orders.api.serializers.request import (
    CreateOrderRequestSerializer,
    UpdateOrderRequestSerializer,
    UpdateOrderStatusRequestSerializer,
    ValidateDiscountRequestSerializer,
)
from orders.api.serializers.response import (
    OrderListItemResponseSerializer,
    OrderResponseSerializer,
    ValidateDiscountResponseSerializer,
)


class OrderConsolePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100



@extend_schema(
    tags=["Orders - Orders"],
    summary="List & Create Orders",
    description="List all orders belonging to the authenticated customer or create a new order.",
)
class OrderListCreateView(generics.ListCreateAPIView):
    """
    GET  /orders/  -> list orders belonging to the logged-in customer.
    POST /orders/  -> create a new order for the logged-in customer.
    """

    permission_classes = [permissions.IsAuthenticated]
    bll_class = OrdersBusinessLogicLayer

    def get_bll(self) -> OrdersBusinessLogicLayer:
        return self.bll_class()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateOrderRequestSerializer
        return OrderListItemResponseSerializer

    def get_queryset(self):
        return self.get_bll().list_orders_for_customer(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = CreateOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = self.get_bll().create_order(
            customer=request.user,
            validated_data=dict(serializer.validated_data),
        )

        return Response(OrderResponseSerializer(order).data, status=201)


@extend_schema(
    tags=["Orders - Orders"],
    summary="Retrieve & Update Order",
    description="Retrieve a specific order or update it while it is still pending.",
)
class OrderDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /orders/{public_id}/  -> retrieve a single order.
    PATCH /orders/{public_id}/  -> edit an order (only while still pending).
    """

    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "public_id"
    bll_class = OrdersBusinessLogicLayer

    def get_bll(self) -> OrdersBusinessLogicLayer:
        return self.bll_class()

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return UpdateOrderRequestSerializer
        return OrderResponseSerializer

    def get_object(self):
        return self.get_bll().get_order_detail(
            customer=self.request.user,
            public_id=self.kwargs["public_id"],
        )

    def update(self, request, *args, **kwargs):
        serializer = UpdateOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = self.get_bll().update_order(
            customer=request.user,
            public_id=self.kwargs["public_id"],
            validated_data=dict(serializer.validated_data),
        )

        return Response(OrderResponseSerializer(order).data, status=200)


@extend_schema(
    tags=["Orders - Orders"],
    summary="Cancel Order",
    description="Cancel an order that belongs to the authenticated customer while it is still cancellable.",
)
class OrderCancelView(APIView):
    """
    POST /orders/{public_id}/cancel/ -> cancel an order belonging to the
    logged-in customer, while it is still in a cancellable state.
    """

    permission_classes = [permissions.IsAuthenticated]
    bll_class = OrdersBusinessLogicLayer

    def get_bll(self) -> OrdersBusinessLogicLayer:
        return self.bll_class()

    @extend_schema(
        tags=["Orders - Orders"],
        summary="Cancel Order",
        description="Cancel an order that belongs to the authenticated customer while it is still cancellable.",
    )
    def post(self, request, public_id, *args, **kwargs):
        order = self.get_bll().cancel_order(customer=request.user, public_id=public_id)
        return Response(OrderResponseSerializer(order).data, status=200)


@extend_schema(
    tags=["Orders - Orders"],
    summary="Update Order Status",
    description="Update the status of an order. Only the owner of the tenant may perform this action.",
)
class OrderStatusUpdateView(APIView):
    """
    PATCH /orders/{public_id}/status/ -> update the order status.
    Restricted to the owner of the tenant the order belongs to.
    """

    permission_classes = [permissions.IsAuthenticated]
    bll_class = OrdersBusinessLogicLayer

    def get_bll(self) -> OrdersBusinessLogicLayer:
        return self.bll_class()

    @extend_schema(
        tags=["Orders - Orders"],
        summary="Update Order Status",
        description="Update the status of an order. Only the owner of the tenant may perform this action.",
    )
    def patch(self, request, public_id, *args, **kwargs):
        serializer = UpdateOrderStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = self.get_bll().update_order_status(
            user=request.user,
            public_id=public_id,
            new_status=serializer.validated_data["status"],
        )

        return Response(OrderResponseSerializer(order).data, status=200)


@extend_schema(
    tags=["Orders - Console"],
    summary="Console Orders List (all branches)",
    description=(
        "List all orders across every branch of a tenant. "
        "Only the tenant owner can access."
    ),
    parameters=[
        OpenApiParameter(
            name="branch_id",
            type=str,
            description="Optional branch UUID to narrow results to one branch.",
        ),
        OpenApiParameter(
            name="status",
            type=str,
            description="Optional order status filter.",
        ),
        OpenApiParameter(
            name="search",
            type=str,
            description="Optional search term matched against order number or customer contact.",
        ),
        OpenApiParameter(
            name="page",
            type=int,
            description="Page number for pagination.",
        ),
        OpenApiParameter(
            name="page_size",
            type=int,
            description="Number of results per page.",
        ),
    ],
)
class ConsoleTenantOrdersListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderListItemResponseSerializer
    pagination_class = OrderConsolePagination

    bll_class = OrdersBusinessLogicLayer

    def get_bll(self):
        return self.bll_class()

    def get_queryset(self):
        branch_id = self.request.query_params.get("branch_id")
        return self.get_bll().list_orders_for_console_tenant(
            user=self.request.user,
            tenant_id=self.kwargs["tenant_id"],
            branch_id=branch_id or None,
            status=self.request.query_params.get("status") or None,
            search=self.request.query_params.get("search") or None,
        )


@extend_schema(
    tags=["Orders - Console"],
    summary="Console Orders List",
    description="List all orders for a branch. Only tenant owner can access.",
)
class ConsoleOrderListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderListItemResponseSerializer
    pagination_class = OrderConsolePagination

    bll_class = OrdersBusinessLogicLayer

    def get_bll(self):
        return self.bll_class()

    def get_queryset(self):
        return self.get_bll().list_orders_for_console(
            user=self.request.user,
            tenant_id=self.kwargs["tenant_id"],
            branch_id=self.kwargs["branch_id"],
        )


@extend_schema(
    tags=["Orders - Orders"],
    summary="Validate Discount Code",
    description="Check whether a discount code is valid for a given tenant without creating an order.",
)
class ValidateDiscountView(APIView):
    """
    POST /orders/validate-discount/ -> check whether a discount code is
    usable for a given tenant, without creating an order.
    """

    permission_classes = [permissions.IsAuthenticated]
    bll_class = OrdersBusinessLogicLayer

    def get_bll(self) -> OrdersBusinessLogicLayer:
        return self.bll_class()

    @extend_schema(
        tags=["Orders - Orders"],
        summary="Validate Discount Code",
        description="Check whether a discount code is valid for a given tenant without creating an order.",
    )
    def post(self, request, *args, **kwargs):
        serializer = ValidateDiscountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = self.get_bll().validate_discount(
            branch_id=serializer.validated_data["branch_id"],
            discount_code=serializer.validated_data["discount_code"],
            subtotal=serializer.validated_data.get("subtotal"),
        )

        return Response(ValidateDiscountResponseSerializer(result).data, status=200)
