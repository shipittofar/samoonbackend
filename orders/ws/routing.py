from django.urls import re_path

from orders.ws import OrderStatusConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/orders/(?P<public_id>[0-9a-f-]+)/$",
        OrderStatusConsumer.as_asgi(),
    ),
]