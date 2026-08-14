import uuid
from rest_framework.exceptions import APIException
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

#--------------------------------------------------------------
# Exception Handler
#--------------------------------------------------------------

class CubixSkillAPIException(APIException):
    """
    Standard project exception raising machine-readable error codes.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'BAD_REQUEST'
    default_detail = 'A business logic error occurred.'

    def __init__(self, detail=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.default_code = code
        super().__init__(detail=detail, code=code)

#--------------------------------------------------------------
# Pagination
#--------------------------------------------------------------

class StandardPagination(PageNumberPagination):
    """
    Standard pagination utility for list endpoints.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

#--------------------------------------------------------------
# ID Generation
#--------------------------------------------------------------

def generate_uuid() -> str:
    """
    Generate string representation of a random UUID4.
    """
    return str(uuid.uuid4())

#--------------------------------------------------------------
# Response Helper
#--------------------------------------------------------------

def api_response(data=None, message: str = "", status_code: int = status.HTTP_200_OK):
    """
    Standard API response envelope helper.
    """
    return Response({
        "success": status_code < 400,
        "message": message,
        "data": data
    }, status=status_code)
