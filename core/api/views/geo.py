from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from core.utils.geoip import country_for_ip


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def geo_country(request):
    """Best-guess country of the caller, from their IP (used to preselect the
    phone country code on the sign-in page). ``{"country": "IR"}`` or
    ``{"country": null}`` when unknown.

    The client IP is resolved the same way the throttles do (NUM_PROXIES), so a
    spoofed X-Forwarded-For header cannot pick the answer.
    """
    ip = BaseThrottle().get_ident(request)
    response = Response({"country": country_for_ip(ip)}, status=status.HTTP_200_OK)
    response["Cache-Control"] = "private, max-age=3600"
    return response
