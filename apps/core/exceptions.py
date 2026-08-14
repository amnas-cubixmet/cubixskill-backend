from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

#--------------------------------------------------------------
# Exception Handler
#--------------------------------------------------------------

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, 'default_code', 'ERROR')
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
