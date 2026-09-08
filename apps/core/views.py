from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    Lightweight, production-safe health check endpoint.
    Checks database connection without exposing internal details or credentials.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
        except Exception:
            db_status = "error"

        http_status = status.HTTP_200_OK if db_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE

        return Response(
            {
                "status": "healthy" if db_status == "ok" else "unhealthy",
                "database": db_status
            },
            status=http_status
        )
