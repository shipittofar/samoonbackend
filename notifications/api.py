"""/api/notifications/ — the signed-in user's own notifications and
preferences. Shapes follow the frontend (src/types/notification.ts).
Text comes back in the request's language (Accept-Language: fa / en / ar)."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications import catalog
from notifications.models import (
    PRIORITY_RANK,
    Notification,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
)
from notifications.services import serialize

MAX_PAGE_SIZE = 100

DEFAULT_PREFS = {
    # category: (channels, minPriority) — same defaults as the frontend
    "order": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "reservation": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "staff": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "branch": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "promotion": ({"in_app": True, "push": False, "email": False, "sms": False}, "normal"),
    "tenant": ({"in_app": True, "push": True, "email": True, "sms": False}, "high"),
    "vendor": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "loyalty": ({"in_app": True, "push": False, "email": False, "sms": False}, "low"),
    "payment": ({"in_app": True, "push": True, "email": True, "sms": False}, "high"),
    "system": ({"in_app": True, "push": True, "email": False, "sms": False}, "normal"),
    "audit": ({"in_app": True, "push": True, "email": False, "sms": False}, "high"),
}


def _lang(request) -> str:
    return catalog.pick_language(request.query_params.get("lang") or request.headers.get("Accept-Language"))


def _tenant_param(params) -> str | None:
    value = (params.get("tenantId") or params.get("tenant_id") or "").strip()
    return value or None


def _own(request):
    return Notification.objects.filter(recipient=request.user).exclude(status=NotificationStatus.DELETED)


def _filtered(request, params):
    qs = _own(request)
    tenant_id = _tenant_param(params)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    branch_id = (params.get("branchId") or "").strip()
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    for key, field in (("category", "category"), ("priority", "priority"), ("type", "type")):
        value = (params.get(key) or "").strip()
        if value:
            qs = qs.filter(**{field: value})
    state = (params.get("status") or "").strip()
    if state:
        qs = qs.filter(status=state)
    date_from = parse_date(params.get("dateFrom") or "")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = parse_date(params.get("dateTo") or "")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    search = (params.get("search") or "").strip()
    if search:
        # Text is rendered per language, so search the stored details.
        qs = qs.filter(
            Q(type__icontains=search) | Q(category__icontains=search)
            | Q(actor_name__icontains=search) | Q(data__icontains=search)
        )
    return qs


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        qs = _filtered(request, params)
        sort_by = params.get("sortBy") if params.get("sortBy") in {"created_at", "priority", "status"} else "created_at"
        prefix = "" if params.get("sortOrder") == "asc" else "-"
        qs = qs.order_by(f"{prefix}{sort_by}", "-created_at")
        try:
            page = max(1, int(params.get("page", 1)))
            page_size = min(MAX_PAGE_SIZE, max(1, int(params.get("pageSize", 20))))
        except ValueError:
            page, page_size = 1, 20
        count = qs.count()
        lang = _lang(request)
        rows = qs[(page - 1) * page_size: page * page_size]
        return Response({
            "results": [serialize(n, lang) for n in rows],
            "count": count,
            "page": page,
            "pageSize": page_size,
            "totalPages": max(1, -(-count // page_size)),
            "unreadCount": qs.filter(status=NotificationStatus.UNREAD).count(),
        })

    def post(self, request):
        # Notifications come from server-side events only.
        return Response(
            {"detail": "Notifications are created by the server."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class NotificationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, notification_id):
        return Response(serialize(get_object_or_404(_own(request), id=notification_id), _lang(request)))

    def delete(self, request, notification_id):
        n = get_object_or_404(_own(request), id=notification_id)
        n.status = NotificationStatus.DELETED
        n.save(update_fields=["status"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        n = get_object_or_404(_own(request), id=notification_id)
        if n.status == NotificationStatus.UNREAD:
            n.status = NotificationStatus.READ
            n.read_at = timezone.now()
            n.save(update_fields=["status", "read_at"])
        return Response(serialize(n, _lang(request)))


class NotificationArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        n = get_object_or_404(_own(request), id=notification_id)
        now = timezone.now()
        n.status = NotificationStatus.ARCHIVED
        n.archived_at = now
        n.read_at = n.read_at or now
        n.save(update_fields=["status", "archived_at", "read_at"])
        return Response(serialize(n, _lang(request)))


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        params = request.data if isinstance(request.data, dict) else {}
        qs = _filtered(request, {**params, "status": NotificationStatus.UNREAD})
        count = qs.update(status=NotificationStatus.READ, read_at=timezone.now())
        return Response({"count": count})


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = {**request.query_params.dict(), "status": NotificationStatus.UNREAD}
        return Response({"count": _filtered(request, params).count()})


class NotificationSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _filtered(request, {k: v for k, v in request.query_params.items() if k in {"tenantId", "branchId"}})
        unread = qs.filter(status=NotificationStatus.UNREAD)
        latest = qs.exclude(status=NotificationStatus.ARCHIVED).order_by("-created_at").first()
        out = {
            "unreadCount": unread.count(),
            "urgentCount": unread.filter(priority=NotificationPriority.URGENT).count(),
            "categories": dict(Counter(unread.values_list("category", flat=True))),
        }
        if latest:
            out["latestNotification"] = serialize(latest, _lang(request))
        return Response(out)


class NotificationStatisticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        qs = _filtered(request, {k: v for k, v in params.items() if k != "status"})
        date_to = parse_date(params.get("dateTo") or "") or timezone.localdate()
        date_from = parse_date(params.get("dateFrom") or "") or (date_to - timedelta(days=30))
        rows = list(qs.values("status", "category", "priority", "branch_id", "type", "created_at"))
        total = len(rows)
        read = sum(1 for r in rows if r["status"] == NotificationStatus.READ)
        archived = sum(1 for r in rows if r["status"] == NotificationStatus.ARCHIVED)
        unread = sum(1 for r in rows if r["status"] == NotificationStatus.UNREAD)
        by_category = {c: 0 for c in catalog.CATEGORIES}
        by_priority = {p: 0 for p in PRIORITY_RANK}
        by_branch: Counter = Counter()
        by_day: Counter = Counter()
        by_type: Counter = Counter()
        for r in rows:
            by_category[r["category"]] = by_category.get(r["category"], 0) + 1
            by_priority[r["priority"]] = by_priority.get(r["priority"], 0) + 1
            if r["branch_id"]:
                by_branch[str(r["branch_id"])] += 1
            by_day[timezone.localtime(r["created_at"]).date().isoformat()] += 1
            by_type[r["type"]] += 1
        return Response({
            "totalNotifications": total,
            "unreadCount": unread,
            "readCount": read,
            "archivedCount": archived,
            "readRate": round((read + archived) / total, 4) if total else 0,
            "notificationsByCategory": by_category,
            "notificationsByPriority": by_priority,
            "notificationsByBranch": dict(by_branch),
            "notificationsByDay": dict(by_day),
            "topTypes": [{"type": t, "count": c} for t, c in by_type.most_common(5)],
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        })


# ── Preferences ──────────────────────────────────────────────────────────────


def _pref_dict(user, tenant_id, category, pref=None) -> dict:
    channels, min_priority = DEFAULT_PREFS.get(category, ({"in_app": True, "push": False, "email": False, "sms": False}, "low"))
    return {
        "id": str(pref.id) if pref else f"pref-{user.id}-{tenant_id or 'personal'}-{category}",
        "userId": str(user.id),
        "tenantId": str(tenant_id) if tenant_id else "",
        "category": category,
        "enabled": pref.enabled if pref else True,
        "channels": {**channels, **(pref.channels if pref else {})},
        "minPriority": pref.min_priority if pref else min_priority,
        "updated_at": (pref.updated_at if pref else timezone.now()).isoformat(),
    }


def _pref_list(user, tenant_id) -> list[dict]:
    stored = {p.category: p for p in NotificationPreference.objects.filter(user=user, tenant_id=tenant_id)}
    return [_pref_dict(user, tenant_id, c, stored.get(c)) for c in catalog.CATEGORIES]


def _check_tenant_access(user, tenant_id) -> bool:
    if not tenant_id:
        return True
    from access.services.membership_bll import membership_service

    return user.is_superuser or str(tenant_id) in membership_service.get_valid_tenant_ids(user)


def _save_pref(user, tenant_id, category, data) -> NotificationPreference:
    pref, _ = NotificationPreference.objects.get_or_create(user=user, tenant_id=tenant_id, category=category)
    if "enabled" in data:
        pref.enabled = bool(data["enabled"])
    if isinstance(data.get("channels"), dict):
        pref.channels = {k: bool(v) for k, v in data["channels"].items() if k in {"in_app", "push", "email", "sms"}}
    if data.get("minPriority") in PRIORITY_RANK:
        pref.min_priority = data["minPriority"]
    pref.save()
    return pref


class PreferenceListView(APIView):
    """GET ?tenantId= (empty = personal) — every category, defaults filled in.
    POST {tenantId, category, enabled?, channels?, minPriority?} — upsert."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = _tenant_param(request.query_params)
        if not _check_tenant_access(request.user, tenant_id):
            return Response({"detail": "Not a member of this business."}, status=403)
        return Response(_pref_list(request.user, tenant_id))

    def post(self, request):
        tenant_id = _tenant_param(request.data)
        category = request.data.get("category")
        if category not in catalog.CATEGORIES:
            return Response({"category": "Unknown category."}, status=400)
        if not _check_tenant_access(request.user, tenant_id):
            return Response({"detail": "Not a member of this business."}, status=403)
        pref = _save_pref(request.user, tenant_id, category, request.data)
        return Response(_pref_dict(request.user, tenant_id, category, pref), status=201)


class PreferenceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, category):
        if category not in catalog.CATEGORIES:
            return Response({"category": "Unknown category."}, status=400)
        tenant_id = _tenant_param(request.data)
        if not _check_tenant_access(request.user, tenant_id):
            return Response({"detail": "Not a member of this business."}, status=403)
        pref = _save_pref(request.user, tenant_id, category, request.data)
        return Response(_pref_dict(request.user, tenant_id, category, pref))


class PreferenceResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant_id = _tenant_param(request.data)
        NotificationPreference.objects.filter(user=request.user, tenant_id=tenant_id).delete()
        return Response(_pref_list(request.user, tenant_id))


app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="create"),
    path("rich/", NotificationListView.as_view(), name="list"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="unread-count"),
    path("summary/", NotificationSummaryView.as_view(), name="summary"),
    path("statistics/", NotificationStatisticsView.as_view(), name="statistics"),
    path("read-all/", NotificationReadAllView.as_view(), name="read-all"),
    path("preferences/", PreferenceListView.as_view(), name="preferences"),
    path("preferences/reset/", PreferenceResetView.as_view(), name="preferences-reset"),
    path("preferences/<str:category>/", PreferenceDetailView.as_view(), name="preference"),
    path("<uuid:notification_id>/", NotificationDetailView.as_view(), name="detail"),
    path("<uuid:notification_id>/read/", NotificationReadView.as_view(), name="read"),
    path("<uuid:notification_id>/archive/", NotificationArchiveView.as_view(), name="archive"),
]
