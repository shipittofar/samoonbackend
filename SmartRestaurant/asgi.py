import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "SmartRestaurant.settings")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

from core.middleware import JWTAuthMiddleware  # noqa: E402
from orders.ws.routing import websocket_urlpatterns  # noqa: E402

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
})