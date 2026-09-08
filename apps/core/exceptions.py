import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    ValidationError,
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    NotFound,
    Throttled,
)
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied
from django.http import Http404

logger = logging.getLogger('django')

#--------------------------------------------------------------
# CubixSkill Custom Base API Exception
#--------------------------------------------------------------

class CubixSkillAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'An error occurred.'
    default_code = 'BAD_REQUEST'

    def __init__(self, detail=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.default_code = code
        super().__init__(detail, code)


#--------------------------------------------------------------
# Canonical Production Exception Handler
#--------------------------------------------------------------

def custom_exception_handler(exc, context):
    if isinstance(exc, ObjectDoesNotExist):
        return Response(
            {
                "code": "TOKEN_INVALID",
                "message": "Resource or user account no longer exists."
            },
            status=status.HTTP_401_UNAUTHORIZED
        )

    if isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDenied()
    elif isinstance(exc, Http404):
        exc = NotFound()

    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, 'default_code', getattr(exc, 'code', 'ERROR'))
        if isinstance(exc, ValidationError):
            error_code = 'VALIDATION_ERROR'
        elif isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            error_code = 'AUTHENTICATION_REQUIRED'
        elif isinstance(exc, PermissionDenied):
            error_code = 'PERMISSION_DENIED'
        elif isinstance(exc, NotFound):
            error_code = 'NOT_FOUND'
        elif isinstance(exc, Throttled):
            error_code = 'RATE_LIMITED'

        error_code_str = str(error_code).upper()

        if isinstance(response.data, dict):
            # Check if dict already has code / message
            if 'code' in response.data and 'message' in response.data:
                res_data = response.data
            else:
                detail = response.data.get('detail', None)
                if detail:
                    msg = str(detail)
                    fields = {k: v for k, v in response.data.items() if k != 'detail'}
                else:
                    msg = "Please correct the highlighted validation errors." if error_code_str == 'VALIDATION_ERROR' else "An error occurred."
                    fields = response.data

                res_data = {
                    "code": error_code_str,
                    "message": msg,
                }
                if fields:
                    res_data["errors"] = fields
        elif isinstance(response.data, list):
            res_data = {
                "code": error_code_str,
                "message": "Validation failed.",
                "errors": response.data
            }
        else:
            res_data = {
                "code": error_code_str,
                "message": str(response.data)
            }

        response.data = res_data
    else:
        # Log internal server error server-side with full stack trace
        view = context.get('view', None)
        request = context.get('request', None)
        view_name = view.__class__.__name__ if view else 'UnknownView'
        path = request.path if request else 'UnknownPath'
        method = request.method if request else 'UnknownMethod'

        logger.error(
            f"Unhandled Exception in {method} {path} (View: {view_name}): {exc}",
            exc_info=exc
        )

        response = Response(
            {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
