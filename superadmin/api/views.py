"""Platform superuser console API (/api/superadmin/).

Every view here is superuser-only: search every business and see its
details, review business registration requests, and manage the menu
templates offered to owners.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.constants import MembershipStatus
from access.models import StaffMembership
from accounts.models import User
from menu.models import MenuCategory, MenuItem, MenuTemplate
from orders.models import Order
from reservations.models import Reservation
from tenants.models import Branch, BusinessRequest, BusinessRequestStatus, Owner, Tenant
from tenants.services import business_request_bll

from .permissions import IsPlatformSuperuser
from .serializers import (
    MenuTemplateSerializer,
    PlatformBusinessRequestSerializer,
    PlatformTenantListSerializer,
    _user_block,
)

SUPERUSER = (IsAuthenticated, IsPlatformSuperuser)


class OverviewView(APIView):
    permission_classes = SUPERUSER

    def get(self, request):
        return Response({
            "tenants": Tenant.objects.count(),
            "active_tenants": Tenant.objects.filter(is_active=True, status="active").count(),
            "owners": Owner.objects.count(),
            "users": User.objects.count(),
            "pending_business_requests": BusinessRequest.objects.filter(
                status=BusinessRequestStatus.PENDING
            ).count(),
            "menu_templates": MenuTemplate.objects.count(),
        })


class TenantListView(generics.ListAPIView):
    """Search: ?search= (name, slug, owner phone/email/name, branch city),
    ?business_type=, ?status=active|inactive|closed, ?owner_status=."""

    permission_classes = SUPERUSER
    serializer_class = PlatformTenantListSerializer

    def get_queryset(self):
        params = self.request.query_params
        first_city = Subquery(
            Branch.objects.filter(tenant_id=OuterRef("pk")).exclude(city="")
            .order_by("-is_default", "created_at").values("city")[:1]
        )
        qs = (
            Tenant.objects.select_related("owner__user")
            .annotate(branch_count=Count("branches", distinct=True), first_city=first_city)
            .order_by("-created_at")
        )
        term = (params.get("search") or "").strip()
        if term:
            qs = qs.filter(
                Q(name__icontains=term)
                | Q(slug__icontains=term)
                | Q(owner__user__phone_number__icontains=term)
                | Q(owner__user__email__icontains=term)
                | Q(owner__user__first_name__icontains=term)
                | Q(owner__user__last_name__icontains=term)
                | Q(branches__city__icontains=term)
                | Q(branches__name__icontains=term)
            ).distinct()
        business_type = params.get("business_type")
        if business_type:
            qs = qs.filter(business_types__contains=[business_type])
        tenant_status = params.get("status")
        if tenant_status:
            qs = qs.filter(status=tenant_status)
        owner_status = params.get("owner_status")
        if owner_status == "active":
            qs = qs.filter(Q(owner__status__isnull=True) | Q(owner__status__in=["", "active"]))
        elif owner_status:
            qs = qs.filter(owner__status=owner_status)
        return qs


class TenantDetailView(APIView):
    permission_classes = SUPERUSER

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant.objects.select_related("owner__user"), pk=tenant_id)
        branches = list(
            Branch.objects.filter(tenant=tenant)
            .annotate(
                category_count=Count("categories", distinct=True),
                item_count=Count("items", distinct=True),
            )
            .order_by("-is_default", "created_at")
        )
        month_ago = timezone.now() - timedelta(days=30)
        orders = Order.objects.filter(branch__tenant=tenant)
        owner = tenant.owner
        origin = BusinessRequest.objects.filter(tenant=tenant).first()
        return Response({
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "description": tenant.description,
            "status": tenant.status,
            "is_active": tenant.is_active,
            "business_types": tenant.business_types or [],
            "tax_percentage": str(tenant.tax_percentage),
            "service_charge_percentage": str(tenant.service_charge_percentage),
            "settings": tenant.settings or {},
            "created_at": tenant.created_at,
            "updated_at": tenant.updated_at,
            "owner": {
                **(_user_block(owner.user) or {}),
                "status": owner.status or "active",
                "plan": owner.plan,
                "verified_at": owner.verified_at,
                "since": owner.created_at,
                "other_tenants": list(
                    Tenant.objects.filter(owner=owner).exclude(pk=tenant.pk).values("id", "name")
                ),
            },
            "counts": {
                "branches": len(branches),
                "categories": MenuCategory.objects.filter(branch__tenant=tenant).count(),
                "menu_items": MenuItem.objects.filter(branch__tenant=tenant).count(),
                "staff": StaffMembership.objects.filter(
                    tenant=tenant, status=MembershipStatus.ACTIVE
                ).count(),
                "orders": orders.count(),
                "orders_last_30_days": orders.filter(created_at__gte=month_ago).count(),
                "revenue_last_30_days": str(
                    orders.filter(created_at__gte=month_ago).aggregate(s=Sum("total"))["s"] or 0
                ),
                "reservations": Reservation.objects.filter(branch__tenant=tenant).count(),
            },
            "branches": [
                {
                    "id": str(b.id),
                    "name": b.name,
                    "slug": b.slug,
                    "status": b.status,
                    "is_active": b.is_active,
                    "is_default": b.is_default,
                    "phone": b.phone,
                    "city": b.city,
                    "address": b.address,
                    "latitude": str(b.latitude) if b.latitude is not None else None,
                    "longitude": str(b.longitude) if b.longitude is not None else None,
                    "delivery_radius_km": b.delivery_radius_km,
                    "ordering_enabled": b.ordering_enabled,
                    "delivery_enabled": b.delivery_enabled,
                    "pickup_enabled": b.pickup_enabled,
                    "table_ordering_enabled": b.table_ordering_enabled,
                    "reservations_enabled": b.reservations_enabled,
                    "marketplace_visible": b.marketplace_visible,
                    "category_count": b.category_count,
                    "item_count": b.item_count,
                    "created_at": b.created_at,
                }
                for b in branches
            ],
            "registration_request": (
                {"id": str(origin.id), "created_at": origin.created_at, "decided_at": origin.decided_at}
                if origin else None
            ),
        })


class BusinessRequestListView(generics.ListAPIView):
    """?status=pending|approved|rejected (default pending), ?search=."""

    permission_classes = SUPERUSER
    serializer_class = PlatformBusinessRequestSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = BusinessRequest.objects.select_related("user", "decided_by")
        wanted = params.get("status", BusinessRequestStatus.PENDING)
        if wanted != "all":
            qs = qs.filter(status=wanted)
        term = (params.get("search") or "").strip()
        if term:
            qs = qs.filter(
                Q(name__icontains=term) | Q(city__icontains=term)
                | Q(user__phone_number__icontains=term) | Q(user__email__icontains=term)
            )
        return qs


class BusinessRequestApproveView(APIView):
    permission_classes = SUPERUSER

    def post(self, request, request_id):
        get_object_or_404(BusinessRequest, pk=request_id)
        item = business_request_bll.approve(request_id=request_id, actor=request.user)
        return Response(PlatformBusinessRequestSerializer(item).data)


class BusinessRequestRejectView(APIView):
    permission_classes = SUPERUSER

    def post(self, request, request_id):
        get_object_or_404(BusinessRequest, pk=request_id)
        item = business_request_bll.reject(
            request_id=request_id, actor=request.user, reason=request.data.get("reason", "")
        )
        return Response(PlatformBusinessRequestSerializer(item).data)


class MenuTemplateListCreateView(generics.ListCreateAPIView):
    """?business_type= filters the list."""

    permission_classes = SUPERUSER
    serializer_class = MenuTemplateSerializer
    pagination_class = None

    def get_queryset(self):
        qs = MenuTemplate.objects.all()
        business_type = self.request.query_params.get("business_type")
        if business_type:
            qs = qs.filter(business_type=business_type)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class MenuTemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = SUPERUSER
    serializer_class = MenuTemplateSerializer
    queryset = MenuTemplate.objects.all()
    lookup_url_kwarg = "template_id"
