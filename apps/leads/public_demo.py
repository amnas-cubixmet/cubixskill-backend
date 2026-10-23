"""Public demo request form for the CubixSkill marketing website."""

from django.utils import timezone
from leads.models import PlatformDemoRequest
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class PlatformDemoRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformDemoRequest
        fields = (
            'full_name', 'email', 'phone', 'country', 'academy_name',
            'student_count', 'course_count', 'current_platform',
            'main_requirement', 'preferred_date', 'preferred_time',
            'time_zone', 'message',
        )

    def validate_preferred_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError('Choose today or a future date.')
        return value


class PublicDemoThrottle(SimpleRateThrottle):
    # Rate-limited even for unauthenticated traffic.
    scope = 'public_platform_demo'
    rate = '5/hour'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class PublicPlatformDemoRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PublicDemoThrottle]

    def post(self, request):
        serializer = PlatformDemoRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        demo = serializer.save()
        return Response({
            'id': str(demo.id),
            'status': 'received',
            'message': 'Your demo request has been received. Our team will contact you to confirm a time.',
        }, status=status.HTTP_201_CREATED)
