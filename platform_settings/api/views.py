from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from superadmin.api.permissions import IsPlatformSuperuser
from platform_settings.services import homepage_hero


@extend_schema(tags=["Platform - Homepage"])
class HomepageHeroView(APIView):
    """GET: public (the marketplace home page reads it; 404 until a superuser
    saves one, and the site then shows its built-in default).
    PUT: platform superusers only; replaces the whole hero."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsPlatformSuperuser()]

    def perform_authentication(self, request):
        # The public read never looks at the user, so an expired token sent by
        # a visitor's browser must not turn the home page hero into a 401.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        super().perform_authentication(request)

    def get(self, request):
        hero = homepage_hero.get_hero()
        if hero is None:
            return Response({"detail": "The homepage hero has not been configured."}, status=404)
        return Response(hero)

    def put(self, request):
        return Response(homepage_hero.save_hero(user=request.user, data=request.data))
