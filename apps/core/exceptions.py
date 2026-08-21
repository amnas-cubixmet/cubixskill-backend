from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import APIException
from django.core.exceptions import ObjectDoesNotExist

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
# Exception Handler
#--------------------------------------------------------------

def custom_exception_handler(exc, context):
    if isinstance(exc, ObjectDoesNotExist):
        return Response(
            {
                "error": {
                    "code": "TOKEN_INVALID",
                    "message": "Token is invalid, expired, or user account no longer exists."
                }
            },
            status=status.HTTP_401_UNAUTHORIZED
        )

    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, 'default_code', getattr(exc, 'code', 'ERROR'))
        if hasattr(exc, 'detail') and isinstance(exc.detail, dict):
            message = exc.detail
        elif hasattr(exc, 'detail'):
            message = str(exc.detail)
        else:
            message = str(exc)

        response.data = {
            "error": {
                "code": str(error_code).upper(),
                "message": message
            }
        }
    else:
        response = Response(
            {
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(exc)
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
