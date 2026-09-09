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

    @action(detail=True, methods=['get'], url_path='export')
    def export_data(self, request, pk=None):
        import csv
        import re
        from django.http import HttpResponse
        from django.utils import timezone
        from core.utils import CubixSkillAPIException
        from enrollments.models import Enrollment

        course = self.get_object()

        user_academy = getattr(request.user, 'academy_id', None)
        if user_academy and course.academy_id and user_academy != course.academy_id:
            raise CubixSkillAPIException("Access denied to course in another academy.", code="CROSS_ACADEMY_FORBIDDEN", status_code=403)

        if not getattr(course, 'allow_data_export', True):
            raise CubixSkillAPIException("Data export is disabled for this course.", code="DATA_EXPORT_DISABLED", status_code=403)

        enrollments = Enrollment.objects.filter(course=course).select_related('student')

        response = HttpResponse(content_type='text/csv')
        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', course.title or 'course')
        filename = f"{clean_title}-students-{timezone.now().strftime('%Y-%m-%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Student ID',
            'Full Name',
            'Email',
            'Enrollment Status',
            'Access Type',
            'Enrolled Date',
            'Progress (%)'
        ])

        for enr in enrollments:
            student = enr.student
            student_id = str(student.id) if student else ''
            student_name = getattr(student, 'full_name', '') if student else (getattr(student, 'username', '') if student else '')
            student_email = getattr(student, 'email', '') if student else ''

            writer.writerow([
                student_id,
                student_name,
                student_email,
                enr.status,
                enr.access_type,
                enr.enrolled_at.strftime('%Y-%m-%d') if enr.enrolled_at else '',
                f"{enr.progress_percent:.2f}"
            ])

        return response

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


#--------------------------------------------------------------
# Student Course Overview View
#--------------------------------------------------------------
from rest_framework.views import APIView
from rest_framework.response import Response
import re
from django.utils.text import slugify
from django.db import models

class StudentCourseOverviewView(APIView):
    """
    Returns complete real database telemetry for a student in a specific course.
    GET /api/v1/courses/<course_uuid>/students/<student_uuid>/overview/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, course_uuid, student_uuid):
        user = request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            return Response({"detail": "User must belong to an academy."}, status=status.HTTP_403_FORBIDDEN)

        # 1. Course check (Multi-tenant security)
        try:
            course = Course.objects.get(id=course_uuid, academy=academy)
        except (Course.DoesNotExist, ValueError):
            return Response({"detail": "Course not found in your academy."}, status=status.HTTP_404_NOT_FOUND)

        # 2. Student check
        from users_roles.models import User
        from students.models import StudentProfile

        student_user = User.objects.filter(id=student_uuid).first()
        student_profile = None
        if student_user:
            student_profile = StudentProfile.objects.filter(user=student_user, academy=academy).first()
        else:
            student_profile = StudentProfile.objects.filter(id=student_uuid, academy=academy).first()
            if student_profile:
                student_user = student_profile.user

        if not student_user:
            return Response({"detail": "Student not found in your academy."}, status=status.HTTP_404_NOT_FOUND)

        # 3. Enrollment check
        from enrollments.models import Enrollment
        enrollment = Enrollment.objects.filter(course=course, student=student_user).first()
        if not enrollment:
            return Response({"detail": "Student is not enrolled in this course."}, status=status.HTTP_404_NOT_FOUND)

        # Avatar URL
        avatar_url = None
        if student_profile and getattr(student_profile, 'profile_photo', None):
            mf = student_profile.profile_photo
            if hasattr(mf, 'file') and mf.file:
                avatar_url = request.build_absolute_uri(mf.file.url) if request else mf.file.url
            elif getattr(mf, 'file_url', ''):
                avatar_url = mf.file_url

        full_name = (student_profile.display_name if student_profile and student_profile.display_name else student_user.full_name) or student_user.email
        student_code = (student_profile.student_code if student_profile and student_profile.student_code else f"CS-{str(student_user.id)[:6].upper()}")

        # 4. Progress calculation
        from modules.models import Module
        from lessons.models import Lesson
        from learning_progress.models import LessonProgress, ProgressStatus, LearningActivity

        active_modules = Module.objects.filter(course=course, is_active=True).order_by('order_index')
        total_lessons = Lesson.objects.filter(module__course=course, is_active=True, module__is_active=True).count()

        completed_lp_qs = LessonProgress.objects.filter(
            student=student_user,
            lesson__module__course=course,
            status=ProgressStatus.COMPLETED
        )
        completed_lesson_ids = set(completed_lp_qs.values_list('lesson_id', flat=True))
        completed_lessons = len(completed_lesson_ids)
        percentage = round((completed_lessons / total_lessons * 100), 2) if total_lessons > 0 else 0.0

        # Modules breakdown
        modules_data = []
        for mod in active_modules:
            mod_lessons = mod.lessons.filter(is_active=True)
            mod_total = mod_lessons.count()
            mod_comp = mod_lessons.filter(id__in=completed_lesson_ids).count()
            mod_pct = round((mod_comp / mod_total * 100), 2) if mod_total > 0 else 0.0
            modules_data.append({
                "uuid": str(mod.id),
                "title": mod.title,
                "completed_lessons": mod_comp,
                "total_lessons": mod_total,
                "percentage": mod_pct
            })

        # Lessons list
        lessons_data = []
        lp_map = {lp.lesson_id: lp for lp in LessonProgress.objects.filter(student=student_user, lesson__module__course=course)}
        for mod in active_modules:
            for les in mod.lessons.filter(is_active=True).order_by('order_index'):
                lp = lp_map.get(les.id)
                is_comp = (lp.status == ProgressStatus.COMPLETED) if lp else False
                lessons_data.append({
                    "uuid": str(les.id),
                    "module_uuid": str(mod.id),
                    "title": les.title,
                    "type": les.lesson_type,
                    "completed": is_comp,
                    "completed_at": lp.completed_at.isoformat() if (lp and lp.completed_at and is_comp) else None
                })

        # Activities from real DB
        activities_qs = LearningActivity.objects.filter(
            student=student_user,
            lesson__module__course=course
        ).order_by('-created_at')[:20]
        activities_data = []
        for act in activities_qs:
            activities_data.append({
                "id": str(act.id),
                "activity_type": act.activity_type,
                "lesson_title": act.lesson.title if act.lesson else '',
                "details": act.payload if isinstance(act.payload, dict) else {},
                "timestamp": act.created_at.isoformat() if hasattr(act, 'created_at') and act.created_at else None
            })

        # Real certificates from DB
        from certificates.models import Certificate
        certs_qs = Certificate.objects.filter(enrollment=enrollment)
        certificates_data = []
        for cert in certs_qs:
            certificates_data.append({
                "id": str(cert.id),
                "certificate_number": cert.certificate_number,
                "issued_at": cert.issued_at.isoformat() if cert.issued_at else None,
                "status": cert.status
            })

        return Response({
            "student": {
                "uuid": str(student_user.id),
                "profile_uuid": str(student_profile.id) if student_profile else None,
                "full_name": full_name,
                "email": student_user.email,
                "phone": student_user.phone or (student_profile.phone if student_profile else ''),
                "student_code": student_code,
                "avatar": avatar_url,
                "status": student_profile.status if student_profile else "ACTIVE"
            },
            "course": {
                "uuid": str(course.id),
                "title": course.title
            },
            "enrollment": {
                "uuid": str(enrollment.id),
                "status": enrollment.status,
                "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else enrollment.created_at.isoformat(),
                "completed_at": enrollment.updated_at.isoformat() if enrollment.status == 'COMPLETED' else None
            },
            "progress": {
                "completed_lessons": completed_lessons,
                "total_lessons": total_lessons,
                "percentage": percentage
            },
            "modules": modules_data,
            "lessons": lessons_data,
            "quiz_attempts": [],
            "assignment_submissions": [],
            "activities": activities_data,
            "certificates": certificates_data
        }, status=status.HTTP_200_OK)

