import logging
import traceback

from rest_framework.views import exception_handler
from rest_framework.response import Response
from core.exceptions import BaseAppException

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        return response

    if isinstance(exc, BaseAppException):
        error_body = {
            "status_code": exc.status_code,
            "code": exc.code,
            "message": exc.message,
        }
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            error_body["diagnostics"] = diagnostics
        return Response(
            {"error": error_body},
            status=exc.status_code,
        )

    logger.exception(
        "Unhandled exception in %s: %s",
        context.get("view"),
        exc,
    )

    return Response(
        {
            "error": {
                "code": "server_error",
                "message": "Internal server error",
            }
        },
        status=500,
    )