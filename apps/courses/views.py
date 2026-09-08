from core.permissions import CanAccessAcademyPermission
from core.utils import api_response
from courses.models import CourseCategory, CourseModule
from courses.selectors import CourseSelector
from courses.serializers import (
    CourseCategorySerializer,
    CourseDetailSerializer,
    CourseLanguageSerializer,
    CourseListSerializer,
    CourseModuleSerializer,
    CourseWriteSerializer,
)
from courses.services import CourseService
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action

#--------------------------------------------------------------
# Course ViewSet
#--------------------------------------------------------------

class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get_serializer_class(self):
        if self.action == 'list':
            return CourseListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return CourseWriteSerializer
        return CourseDetailSerializer

    def get_queryset(self):
        filters = {
            'status': self.request.query_params.get('status'),
            'level': self.request.query_params.get('level'),
            'category': self.request.query_params.get('category'),
            'search': self.request.query_params.get('search')
        }
        return CourseSelector.get_academy_courses(user=self.request.user, filters=filters)

    def perform_create(self, serializer):
        serializer.save(academy=self.request.user.academy)

    @action(detail=True, methods=['get'], url_path='publish-readiness')
    def publish_readiness(self, request, pk=None):
        course = self.get_object()
        from courses.services import CoursePublishReadinessService
        readiness = CoursePublishReadinessService.get_readiness(course)
        return Response(readiness, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        course = self.get_object()
        published_course = CourseService.publish_course(course, request.user)
        return api_response(data=CourseDetailSerializer(published_course).data, message="Course published successfully.")

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        course = self.get_object()
        archived_course = CourseService.archive_course(course, request.user)
        return api_response(data=CourseDetailSerializer(archived_course).data, message="Course archived successfully.")

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        course = self.get_object()
        duplicated_course = CourseService.duplicate_course(course, request.user)
        return api_response(
            data=CourseDetailSerializer(duplicated_course).data,
            message="Course duplicated successfully.",
            status_code=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def reorder_modules(self, request, pk=None):
        course = self.get_object()
        module_order_map = request.data.get('module_order_map', {})
        CourseService.reorder_modules(course, module_order_map)
        return api_response(message="Modules reordered successfully.")

    @action(detail=True, methods=['get', 'patch', 'put'])
    def fees(self, request, pk=None):
        course = self.get_object()

        if request.method in ['PATCH', 'PUT']:
            serializer = CourseWriteSerializer(course, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            course.refresh_from_db()

        from decimal import Decimal

        from enrollments.models import AccessType, Enrollment, EnrollmentStatus
        from payments.models import OrderStatus, PaymentOrder

        completed_orders = PaymentOrder.objects.filter(course=course, status=OrderStatus.COMPLETED)
        pending_orders = PaymentOrder.objects.filter(course=course, status__in=[OrderStatus.PENDING, OrderStatus.PROCESSING, OrderStatus.CREATED])
        refunded_orders = PaymentOrder.objects.filter(course=course, status__in=[OrderStatus.REFUNDED, OrderStatus.PARTIALLY_REFUNDED])

        total_revenue = sum(o.final_amount for o in completed_orders) or Decimal('0.00')
        pending_amount = sum(o.final_amount for o in pending_orders) or Decimal('0.00')
        refunded_amount = sum(o.final_amount for o in refunded_orders) or Decimal('0.00')

        paid_enrollments_count = Enrollment.objects.filter(
            course=course,
            status=EnrollmentStatus.ACTIVE,
            access_type=AccessType.FULL
        ).count()

        fee_data = {
            "course_id": str(course.id),
            "course_title": course.title,
            "is_free": course.is_free,
            "price": str(course.price),
            "sale_price": str(course.sale_price) if course.sale_price is not None else None,
            "currency": course.currency or "INR",
            "demo_enabled": course.demo_enabled,
            "demo_duration_days": course.demo_duration_days,
            "certificate_enabled": course.certificate_enabled,
            "revenue_summary": {
                "total_revenue": float(total_revenue),
                "paid_enrollments": paid_enrollments_count,
                "amount_collected": float(total_revenue),
                "pending_payments": float(pending_amount),
                "refunded_payments": float(refunded_amount)
            }
        }

        return api_response(data=fee_data, message="Course fee configuration loaded successfully.")

#--------------------------------------------------------------
# Category ViewSet
import difflib
import re

from courses.models import CategoryAlias, CategoryMergeAudit, Course, CourseLanguage
from courses.serializers import CategoryMergeAuditSerializer, CategoryMergeSerializer
from django.db import models, transaction
from django.utils.text import slugify
from rest_framework.decorators import action
from rest_framework.response import Response


def normalize_category_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r'\s+', ' ', name.strip())

#--------------------------------------------------------------
# Category ViewSet
#--------------------------------------------------------------

class CourseCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CourseCategorySerializer

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        qs = CourseCategory.objects.filter(academy=academy)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                models.Q(name__icontains=search) |
                models.Q(slug__icontains=search) |
                models.Q(aliases__name__icontains=search) |
                models.Q(aliases__slug__icontains=search)
            ).distinct()
        return qs

    def create(self, request, *args, **kwargs):
        academy = getattr(request.user, 'academy', None)
        raw_name = request.data.get('name', '')
        norm_name = normalize_category_name(raw_name)
        if not norm_name:
            return Response({'message': 'Category name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        norm_slug = slugify(norm_name)

        # 1. Check exact canonical match
        exact = CourseCategory.objects.filter(academy=academy, slug=norm_slug).first()
        if not exact:
            exact = CourseCategory.objects.filter(academy=academy, name__iexact=norm_name).first()
        if exact:
            serializer = self.get_serializer(exact)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # 2. Check alias match
        alias = CategoryAlias.objects.filter(academy=academy, slug=norm_slug).select_related('canonical_category').first()
        if not alias:
            alias = CategoryAlias.objects.filter(academy=academy, name__iexact=norm_name).select_related('canonical_category').first()
        if alias and alias.canonical_category:
            serializer = self.get_serializer(alias.canonical_category)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # 3. Create new canonical category
        description = request.data.get('description', '')
        category = CourseCategory.objects.create(
            academy=academy,
            name=norm_name,
            description=description
        )
        serializer = self.get_serializer(category)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='check-similar')
    def check_similar(self, request):
        academy = getattr(request.user, 'academy', None)
        name = request.query_params.get('name', '').strip()
        if not name:
            return Response({'exact_match': None, 'alias_match': None, 'similar_categories': []})

        norm_name = normalize_category_name(name)
        norm_slug = slugify(norm_name)

        # Exact match
        exact = CourseCategory.objects.filter(academy=academy, slug=norm_slug).first()
        if not exact:
            exact = CourseCategory.objects.filter(academy=academy, name__iexact=norm_name).first()

        # Alias match
        alias = CategoryAlias.objects.filter(academy=academy, slug=norm_slug).select_related('canonical_category').first()
        if not alias:
            alias = CategoryAlias.objects.filter(academy=academy, name__iexact=norm_name).select_related('canonical_category').first()

        # Similar categories search
        all_cats = CourseCategory.objects.filter(academy=academy)
        similar_cats = []

        norm_lower = norm_name.lower()
        for cat in all_cats:
            if exact and cat.id == exact.id:
                continue
            cat_lower = cat.name.lower()
            ratio = difflib.SequenceMatcher(None, norm_lower, cat_lower).ratio()
            is_substring = norm_lower in cat_lower or cat_lower in norm_lower
            if ratio >= 0.55 or is_substring:
                similar_cats.append(cat)

        return Response({
            'exact_match': CourseCategorySerializer(exact).data if exact else None,
            'alias_match': CourseCategorySerializer(alias.canonical_category).data if (alias and alias.canonical_category) else None,
            'similar_categories': CourseCategorySerializer(similar_cats, many=True).data
        })

    @action(detail=False, methods=['post'], url_path='merge')
    @transaction.atomic
    def merge(self, request):
        academy = getattr(request.user, 'academy', None)
        serializer = CategoryMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_id = serializer.validated_data['source_category_id']
        target_id = serializer.validated_data['target_category_id']

        source_cat = CourseCategory.objects.filter(academy=academy, id=source_id).first()
        target_cat = CourseCategory.objects.filter(academy=academy, id=target_id).first()

        if not source_cat or not target_cat:
            return Response({'message': 'Source or Target category not found in your academy.'}, status=status.HTTP_404_NOT_FOUND)

        # 1. Reassign courses
        reassigned_courses = Course.objects.filter(academy=academy, category=source_cat)
        count = reassigned_courses.count()
        reassigned_courses.update(category=target_cat)

        # 2. Create CategoryAlias for old source name
        if not CategoryAlias.objects.filter(academy=academy, name__iexact=source_cat.name).exists():
            CategoryAlias.objects.create(
                academy=academy,
                canonical_category=target_cat,
                name=source_cat.name,
                created_by=request.user
            )

        # 3. Log audit trail
        CategoryMergeAudit.objects.create(
            academy=academy,
            source_category_name=source_cat.name,
            target_category=target_cat,
            courses_reassigned_count=count,
            merged_by=request.user
        )

        # 4. Delete source category
        source_name = source_cat.name
        source_cat.delete()

        return Response({
            'message': f"Category '{source_name}' successfully merged into '{target_cat.name}'. Reassigned {count} courses.",
            'target_category': CourseCategorySerializer(target_cat).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='merge-audits')
    def merge_audits(self, request):
        academy = getattr(request.user, 'academy', None)
        audits = CategoryMergeAudit.objects.filter(academy=academy)
        serializer = CategoryMergeAuditSerializer(audits, many=True)
        return Response(serializer.data)


#--------------------------------------------------------------
# Module ViewSet
#--------------------------------------------------------------

class CourseModuleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CourseModuleSerializer

    def get_queryset(self):
        return CourseModule.objects.filter(course__academy=self.request.user.academy)


#--------------------------------------------------------------
# Course Language ViewSet
#--------------------------------------------------------------

def normalize_language_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r'\s+', ' ', name.strip()).title()

class CourseLanguageViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CourseLanguageSerializer

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        qs = CourseLanguage.objects.filter(models.Q(academy=academy) | models.Q(academy__isnull=True))
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                models.Q(name__icontains=search) |
                models.Q(code__icontains=search) |
                models.Q(slug__icontains=search)
            ).distinct()
        return qs.order_index_by() if hasattr(qs, 'order_index_by') else qs.order_by('name')

    def create(self, request, *args, **kwargs):
        academy = getattr(request.user, 'academy', None)
        raw_name = request.data.get('name', '')
        norm_name = normalize_language_name(raw_name)
        if not norm_name:
            return Response({'message': 'Language name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        norm_slug = slugify(norm_name)

        # Exact match check to prevent duplicates
        exact = CourseLanguage.objects.filter(models.Q(academy=academy) | models.Q(academy__isnull=True), slug=norm_slug).first()
        if not exact:
            exact = CourseLanguage.objects.filter(models.Q(academy=academy) | models.Q(academy__isnull=True), name__iexact=norm_name).first()
        
        if exact:
            serializer = self.get_serializer(exact)
            return Response(serializer.data, status=status.HTTP_200_OK)

        lang = CourseLanguage.objects.create(
            academy=academy,
            name=norm_name,
            code=request.data.get('code', '')
        )
        serializer = self.get_serializer(lang)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
