"""Notification types: category, priority, deep link and the text in each
site language (fa, en, ar). Text is rendered when a notification is read, in
the reader's language, from its ``data`` (``{name}`` placeholders)."""
from __future__ import annotations

from dataclasses import dataclass, field

LANGUAGES = ("fa", "en", "ar")
DEFAULT_LANGUAGE = "fa"

CATEGORIES = (
    "order", "reservation", "staff", "branch", "promotion", "tenant",
    "vendor", "loyalty", "payment", "system", "audit",
)


@dataclass(frozen=True)
class NotificationType:
    category: str
    priority: str
    title: dict[str, str]
    message: dict[str, str]
    link_type: str = ""
    channels: tuple[str, ...] = field(default=("in_app",))


ORDER_STATUS = {
    "fa": {
        "pending": "در انتظار تأیید", "accepted": "تأیید شد", "confirmed": "تأیید شد", "preparing": "در حال آماده‌سازی",
        "ready": "آماده است", "out_for_delivery": "در راه است", "delivered": "تحویل داده شد",
        "picked_up": "تحویل گرفته شد", "served": "سرو شد", "completed": "تکمیل شد", "cancelled": "لغو شد",
    },
    "en": {
        "pending": "pending", "accepted": "confirmed", "confirmed": "confirmed", "preparing": "being prepared",
        "ready": "ready", "out_for_delivery": "on its way", "delivered": "delivered",
        "picked_up": "picked up", "served": "served", "completed": "completed", "cancelled": "cancelled",
    },
    "ar": {
        "pending": "قيد الانتظار", "accepted": "تم التأكيد", "confirmed": "تم التأكيد", "preparing": "قيد التحضير",
        "ready": "جاهز", "out_for_delivery": "في الطريق", "delivered": "تم التوصيل",
        "picked_up": "تم الاستلام", "served": "تم التقديم", "completed": "مكتمل", "cancelled": "ملغى",
    },
}

TYPES: dict[str, NotificationType] = {
    # ── Orders ────────────────────────────────────────────────────────────
    "order_created": NotificationType(
        category="order", priority="high", link_type="order", channels=("in_app", "push"),
        title={"fa": "سفارش جدید", "en": "New order", "ar": "طلب جديد"},
        message={
            "fa": "سفارش جدید #{order_number} از {customer} در {branch}",
            "en": "New order #{order_number} from {customer} at {branch}",
            "ar": "طلب جديد #{order_number} من {customer} في {branch}",
        },
    ),
    "order_cancelled_by_customer": NotificationType(
        category="order", priority="high", link_type="order",
        title={"fa": "سفارش لغو شد", "en": "Order cancelled", "ar": "تم إلغاء الطلب"},
        message={
            "fa": "{customer} سفارش #{order_number} را لغو کرد",
            "en": "{customer} cancelled order #{order_number}",
            "ar": "ألغى {customer} الطلب #{order_number}",
        },
    ),
    "order_status_changed": NotificationType(
        category="order", priority="normal", link_type="order", channels=("in_app", "push"),
        title={"fa": "وضعیت سفارش", "en": "Order update", "ar": "تحديث الطلب"},
        message={
            "fa": "سفارش #{order_number} شما در {branch} {status_label}",
            "en": "Your order #{order_number} at {branch} is {status_label}",
            "ar": "طلبك #{order_number} في {branch}: {status_label}",
        },
    ),
    # ── Reservations ──────────────────────────────────────────────────────
    "reservation_created": NotificationType(
        category="reservation", priority="high", link_type="reservation",
        title={"fa": "رزرو جدید", "en": "New reservation", "ar": "حجز جديد"},
        message={
            "fa": "{customer} برای {party_size} نفر در {branch} رزرو کرد ({when})",
            "en": "{customer} booked for {party_size} at {branch} ({when})",
            "ar": "حجز {customer} لـ {party_size} في {branch} ({when})",
        },
    ),
    "reservation_cancelled_by_customer": NotificationType(
        category="reservation", priority="normal", link_type="reservation",
        title={"fa": "رزرو لغو شد", "en": "Reservation cancelled", "ar": "تم إلغاء الحجز"},
        message={
            "fa": "{customer} رزرو {when} در {branch} را لغو کرد",
            "en": "{customer} cancelled the {when} booking at {branch}",
            "ar": "ألغى {customer} حجز {when} في {branch}",
        },
    ),
    "reservation_confirmed": NotificationType(
        category="reservation", priority="normal", link_type="reservation",
        title={"fa": "رزرو تأیید شد", "en": "Reservation confirmed", "ar": "تم تأكيد الحجز"},
        message={
            "fa": "رزرو شما در {branch} برای {when} تأیید شد",
            "en": "Your booking at {branch} for {when} is confirmed",
            "ar": "تم تأكيد حجزك في {branch} بتاريخ {when}",
        },
    ),
    "reservation_cancelled": NotificationType(
        category="reservation", priority="high", link_type="reservation",
        title={"fa": "رزرو لغو شد", "en": "Reservation cancelled", "ar": "تم إلغاء الحجز"},
        message={
            "fa": "رزرو شما در {branch} برای {when} لغو شد",
            "en": "Your booking at {branch} for {when} was cancelled",
            "ar": "تم إلغاء حجزك في {branch} بتاريخ {when}",
        },
    ),
    # ── Business registration ─────────────────────────────────────────────
    "business_request_created": NotificationType(
        category="tenant", priority="high", link_type="tenant",
        title={"fa": "درخواست ثبت کسب‌وکار", "en": "New business request", "ar": "طلب تسجيل نشاط"},
        message={
            "fa": "{applicant} درخواست ثبت «{business}» را فرستاد",
            "en": "{applicant} asked to register “{business}”",
            "ar": "أرسل {applicant} طلب تسجيل «{business}»",
        },
    ),
    "business_request_approved": NotificationType(
        category="tenant", priority="high", link_type="tenant", channels=("in_app", "push"),
        title={"fa": "کسب‌وکار شما تأیید شد", "en": "Your business is approved", "ar": "تمت الموافقة على نشاطك"},
        message={
            "fa": "«{business}» تأیید شد. کنسول مدیریت برای شما باز است؛ اطلاعات آن را تکمیل کنید.",
            "en": "“{business}” was approved. Your console is open — complete its details.",
            "ar": "تمت الموافقة على «{business}». لوحة الإدارة متاحة لك؛ أكمل بياناته.",
        },
    ),
    "business_request_rejected": NotificationType(
        category="tenant", priority="high", link_type="tenant",
        title={"fa": "درخواست شما رد شد", "en": "Business request declined", "ar": "تم رفض الطلب"},
        message={
            "fa": "درخواست ثبت «{business}» رد شد. {reason}",
            "en": "The request for “{business}” was declined. {reason}",
            "ar": "تم رفض طلب «{business}». {reason}",
        },
    ),
    # ── Staff ─────────────────────────────────────────────────────────────
    "staff_created": NotificationType(
        category="staff", priority="normal", link_type="tenant",
        title={"fa": "به تیم اضافه شدید", "en": "You joined a team", "ar": "انضممت إلى فريق"},
        message={
            "fa": "شما به کارکنان «{business}» اضافه شدید",
            "en": "You were added to the staff of “{business}”",
            "ar": "تمت إضافتك إلى فريق «{business}»",
        },
    ),
    "staff_suspended": NotificationType(
        category="staff", priority="high",
        title={"fa": "دسترسی شما معلق شد", "en": "Access suspended", "ar": "تم تعليق وصولك"},
        message={
            "fa": "دسترسی شما به «{business}» معلق شد",
            "en": "Your access to “{business}” was suspended",
            "ar": "تم تعليق وصولك إلى «{business}»",
        },
    ),
    "staff_removed": NotificationType(
        category="staff", priority="high",
        title={"fa": "از تیم حذف شدید", "en": "Removed from team", "ar": "تمت إزالتك من الفريق"},
        message={
            "fa": "شما از کارکنان «{business}» حذف شدید",
            "en": "You were removed from the staff of “{business}”",
            "ar": "تمت إزالتك من فريق «{business}»",
        },
    ),
    # ── Account security ──────────────────────────────────────────────────
    "password_changed": NotificationType(
        category="system", priority="urgent",
        title={"fa": "رمز عبور تغییر کرد", "en": "Password changed", "ar": "تم تغيير كلمة المرور"},
        message={
            "fa": "رمز عبور حساب شما تغییر کرد و از همه‌ی دستگاه‌ها خارج شدید. اگر شما نبودید، فوراً رمز را بازیابی کنید.",
            "en": "Your password was changed and all devices were signed out. If this wasn't you, reset it now.",
            "ar": "تم تغيير كلمة مرورك وتسجيل الخروج من جميع الأجهزة. إن لم تكن أنت، أعد تعيينها فوراً.",
        },
    ),
}


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def pick_language(raw: str | None) -> str:
    """First supported language in an Accept-Language-style string."""
    for part in (raw or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def render(type_: str, data: dict, language: str) -> tuple[str, str]:
    spec = TYPES.get(type_)
    if spec is None:
        return type_, ""
    lang = language if language in LANGUAGES else DEFAULT_LANGUAGE
    values = _SafeDict({k: v for k, v in (data or {}).items() if isinstance(v, (str, int, float))})
    status = (data or {}).get("status")
    if status:
        values["status_label"] = ORDER_STATUS.get(lang, {}).get(status, status)
    title = spec.title.get(lang) or spec.title["en"]
    message = (spec.message.get(lang) or spec.message["en"]).format_map(values)
    return title, " ".join(message.split())
