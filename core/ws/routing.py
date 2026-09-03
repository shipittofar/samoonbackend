from django.urls import re_path

from core.ws.consumers import ConsoleConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/console/(?P<branch_id>[0-9a-f-]+)/$",
        ConsoleConsumer.as_asgi(),
    ),
]
