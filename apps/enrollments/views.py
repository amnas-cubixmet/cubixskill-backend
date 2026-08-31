from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from users_roles.models import User
from courses.models import Course
from core.utils import CubixSkillAPIException
from enrollments.models import Enrollment, AccessType, EnrollmentSource, EnrollmentStatus
from enrollments.selectors import EnrollmentSelector
from enrollments.services import EnrollmentService
from enrollments.permissions import IsStudentOwnerOrAcademyStaff
from enrollments.serializers import (
    EnrollmentSerializer,
    EnrollmentDetailSerializer,
    CreateEnrollmentSerializer,
    BulkEnrollmentSerializer,
    ExtendEnrollmentSerializer,
    LifecycleActionSerializer,
    EnrollmentAccessPeriodSerializer,
    EnrollmentEventSerializer,
)
from modules.models import Module
from lessons.models import Lesson
from learning_progress.models import CourseProgress, LessonProgress, ProgressStatus

from django.utils import timezone
from django.db.models import Count, Q

#--------------------------------------------------------------
# Student Academy Access Service
#--------------------------------------------------------------

class StudentAcademyAccessService:
    VALID_STATUSES = [EnrollmentStatus.ACTIVE, EnrollmentStatus.EXPIRED]

    @classmethod
    def get_accessible_academies(cls, user):
        from academy.models import Academy
        if not user.is_authenticated:
            return Academy.objects.none()

        return Academy.objects.filter(
            courses__enrollments__student=user,
            courses__enrollments__status__in=cls.VALID_STATUSES
        ).annotate(
            active_courses_count=Count(
                'courses__enrollments',
                filter=Q(courses__enrollments__student=user, courses__enrollments__status=EnrollmentStatus.ACTIVE),
                distinct=True
            ),
            completed_courses_count=Count(
                'courses__enrollments',
                filter=Q(courses__enrollments__student=user, courses__enrollments__progress_percent=100),
                distinct=True
            ),
            total_courses_count=Count(
                'courses__enrollments',
                filter=Q(courses__enrollments__student=user, courses__enrollments__status__in=cls.VALID_STATUSES),
                distinct=True
            )
        ).distinct().select_related('logo', 'favicon')


#--------------------------------------------------------------
# Student Enrollment ViewSet
#--------------------------------------------------------------

class StudentEnrollmentViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Students to view their own course enrollments and accessible academies."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EnrollmentSerializer

    def get_queryset(self):
        return EnrollmentSelector.get_student_enrollments(self.request.user)

    @action(detail=False, methods=['get'], url_path='academies')
    def academies(self, request):
        academies_qs = StudentAcademyAccessService.get_accessible_academies(request.user)
        results = []
        for acad in academies_qs:
            logo_url = ''
            if acad.logo and hasattr(acad.logo, 'file') and acad.logo.file:
                logo_url = acad.logo.file.url
            elif hasattr(acad, 'logo_url') and acad.logo_url:
                logo_url = acad.logo_url

            favicon_url = ''
            if acad.favicon and hasattr(acad.favicon, 'file') and acad.favicon.file:
                favicon_url = acad.favicon.file.url

            results.append({
                'id': str(acad.id),
                'uuid': str(acad.id),
                'academy_uuid': str(acad.id),
                'name': acad.name,
                'tagline': getattr(acad, 'tagline', '') or 'Modern Learning Platform',
                'logo_url': logo_url,
                'favicon_url': favicon_url,
                'theme_color': acad.theme_color or '#2563EB',
                'active_courses_count': acad.active_courses_count,
                'completed_courses_count': acad.completed_courses_count,
                'total_courses_count': acad.total_courses_count,
                'enrolled_courses_count': acad.total_courses_count,
                'overall_progress_percent': 0,
                'last_active_at': 'Recently active'
            })
        return Response({
            'count': len(results),
            'results': results
        })

    @action(detail=False, methods=['get'], url_path=r'academies/(?P<academy_uuid>[^/.]+)/courses')
    def academy_courses(self, request, academy_uuid=None):
        """Returns ONLY the courses belonging to the requested Academy that the request.user is enrolled in."""
        user = request.user
        if not user.is_authenticated:
            return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        from academy.models import Academy
        try:
            academy = Academy.objects.get(id=academy_uuid)
        except (Academy.DoesNotExist, ValueError):
            return Response({'detail': 'Academy not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check that student has access to this academy
        enrollments = Enrollment.objects.filter(
            student=user,
            course__academy=academy,
            status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.EXPIRED]
        ).select_related('course', 'course__academy')

        if not enrollments.exists():
            return Response({'detail': 'You are not enrolled in any courses for this academy.'}, status=status.HTTP_403_FORBIDDEN)

        courses_data = []
        for enr in enrollments:
            c = enr.course
            thumbnail_url = ''
            if hasattr(c, 'thumbnail') and c.thumbnail:
                thumbnail_url = c.thumbnail.url if hasattr(c.thumbnail, 'url') else str(c.thumbnail)

            courses_data.append({
                'id': str(c.id),
                'uuid': str(c.id),
                'course_uuid': str(c.id),
                'title': c.title,
                'description': c.description,
                'thumbnail': thumbnail_url,
                'level': getattr(c, 'level', 'Intermediate'),
                'enrollment_status': enr.status,
                'access_type': enr.access_type,
                'progress_percentage': enr.progress_percent,
                'completed_lessons': getattr(enr, 'completed_lessons_count', 0),
                'total_lessons': getattr(c, 'total_lessons_count', 0) or 10,
                'academy_uuid': str(academy.id)
            })

        logo_url = academy.logo.file.url if (academy.logo and hasattr(academy.logo, 'file') and academy.logo.file) else ''

        return Response({
            'academy': {
                'id': str(academy.id),
                'uuid': str(academy.id),
                'name': academy.name,
                'logo_url': logo_url,
            },
            'courses': courses_data
        })

    @action(detail=False, methods=['get'], url_path=r'academies/(?P<academy_uuid>[^/.]+)/courses/(?P<course_uuid>[^/.]+)/overview')
    def course_overview(self, request, academy_uuid=None, course_uuid=None):
        """Returns private learning overview data for a specific course for request.user."""
        user = request.user
        if not user.is_authenticated:
            return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        from academy.models import Academy
        try:
            academy = Academy.objects.get(id=academy_uuid)
            course = Course.objects.get(id=course_uuid, academy=academy)
        except (Academy.DoesNotExist, Course.DoesNotExist, ValueError):
            return Response({'detail': 'Course or Academy not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            enrollment = Enrollment.objects.get(
                student=user,
                course=course,
                status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.EXPIRED]
            )
        except Enrollment.DoesNotExist:
            return Response({
                'code': 'NOT_ENROLLED',
                'detail': 'You are not actively enrolled in this course.'
            }, status=status.HTTP_403_FORBIDDEN)

        from learning_progress.services import StudentCourseProgressionService
        progression = StudentCourseProgressionService.get_student_course_progression(user, course)
        lessons_map = progression['lessons_map']

        thumbnail_url = course.thumbnail.url if (hasattr(course, 'thumbnail') and course.thumbnail and hasattr(course.thumbnail, 'url')) else str(getattr(course, 'thumbnail', ''))
        modules = Module.objects.filter(course=course, is_active=True).prefetch_related('lessons').order_index_sorted() if hasattr(Module.objects, 'order_index_sorted') else Module.objects.filter(course=course, is_active=True).order_by('order_index')

        completed_lesson_ids = list(LessonProgress.objects.filter(
            student=user,
            lesson__module__course=course,
            status=ProgressStatus.COMPLETED
        ).values_list('lesson_id', flat=True))

        modules_data = []
        total_lessons_count = 0
        for mod in modules:
            mod_lessons = mod.lessons.filter(is_active=True).order_by('order_index')
            lessons_list = []
            for les in mod_lessons:
                total_lessons_count += 1
                les_info = lessons_map.get(str(les.id), {})
                lessons_list.append({
                    'id': str(les.id),
                    'title': les.title,
                    'order': les.order_index,
                    'lesson_type': les.lesson_type,
                    'duration_minutes': les.duration_minutes,
                    'is_demo': les.is_demo,
                    'completed': les.id in completed_lesson_ids or les_info.get('completed', False),
                    'unlocked': les_info.get('unlocked', True),
                    'lock_reason': les_info.get('lock_reason', None),
                    'required_lesson': les_info.get('required_lesson', None),
                })
            modules_data.append({
                'id': str(mod.id),
                'title': mod.title,
                'order': mod.order_index,
                'lessons': lessons_list
            })

        course_progress, _ = CourseProgress.objects.get_or_create(student=user, course=course, defaults={'enrollment': enrollment})

        from features.services import StudentFeatureService
        course_features = StudentFeatureService.get_course_features(user, course)

        return Response({
            'academy': {
                'id': str(academy.id),
                'uuid': str(academy.id),
                'name': academy.name,
            },
            'course': {
                'id': str(course.id),
                'uuid': str(course.id),
                'title': course.title,
                'description': course.description,
                'thumbnail': thumbnail_url,
                'level': getattr(course, 'level', 'Intermediate'),
                'lesson_locking_enabled': progression['lesson_locking_enabled'],
                'features': course_features,
            },
            'enrollment': {
                'id': str(enrollment.id),
                'status': enrollment.status,
                'access_type': enrollment.access_type,
                'enrolled_at': enrollment.created_at,
            },
            'progress': {
                'percentage': float(course_progress.progress_percent),
                'completed_lessons': len(completed_lesson_ids),
                'total_lessons': total_lessons_count,
            },
            'curriculum_summary': {
                'modules_count': len(modules_data),
                'lessons_count': total_lessons_count,
                'has_content': total_lessons_count > 0,
            },
            'lesson_locking_enabled': progression['lesson_locking_enabled'],
            'resume_lesson_id': progression['resume_lesson_id'],
            'modules': modules_data,
        })

    @action(detail=False, methods=['get'], url_path=r'academies/(?P<academy_uuid>[^/.]+)/courses/(?P<course_uuid>[^/.]+)/learn')
    def course_learn_bootstrap(self, request, academy_uuid=None, course_uuid=None):
        """Bootstrap endpoint for private student course player."""
        return self.course_overview(request, academy_uuid=academy_uuid, course_uuid=course_uuid)

    @action(detail=False, methods=['get'], url_path=r'academies/(?P<academy_uuid>[^/.]+)/courses/(?P<course_uuid>[^/.]+)/lessons/(?P<lesson_uuid>[^/.]+)')
    def lesson_detail(self, request, academy_uuid=None, course_uuid=None, lesson_uuid=None):
        """Returns details and media resources for a specific student lesson."""
        user = request.user
        if not user.is_authenticated:
            return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        from academy.models import Academy
        from lessons.models import Lesson
        try:
            academy = Academy.objects.get(id=academy_uuid)
            course = Course.objects.get(id=course_uuid, academy=academy)
            lesson = Lesson.objects.get(id=lesson_uuid, module__course=course, is_active=True)
        except (Academy.DoesNotExist, Course.DoesNotExist, Lesson.DoesNotExist, ValueError):
            return Response({'detail': 'Requested resource not found'}, status=status.HTTP_404_NOT_FOUND)

        from learning_progress.services import StudentCourseProgressionService
        can_access, code, detail_msg, req_les = StudentCourseProgressionService.can_student_access_lesson(user, course, lesson)
        if not can_access:
            if code == "LESSON_LOCKED":
                return Response({
                    'code': 'LESSON_LOCKED',
                    'detail': detail_msg,
                    'required_lesson': req_les
                }, status=status.HTTP_403_FORBIDDEN)
            return Response({'code': code, 'detail': detail_msg}, status=status.HTTP_403_FORBIDDEN)

        from learning_progress.models import LessonProgress, ProgressStatus
        progress = LessonProgress.objects.filter(student=user, lesson=lesson).first()

        resources_data = []
        for res in lesson.resources.all():
            mf = res.media_file
            res_url = res.url
            if not res_url and mf:
                if mf.file_url:
                    res_url = mf.file_url
                elif mf.storage_key:
                    res_url = f"/media/{mf.storage_key.lstrip('/')}"
                elif mf.relative_path:
                    res_url = f"/media/{mf.relative_path.lstrip('/')}"
                elif mf.storage_path:
                    res_url = f"/media/{mf.storage_path.lstrip('/')}"

            if res_url and request and not (res_url.startswith('http://') or res_url.startswith('https://')):
                res_url = request.build_absolute_uri(res_url)

            resources_data.append({
                'id': str(res.id),
                'resource_uuid': str(res.id),
                'resourceUuid': str(res.id),
                'title': res.title,
                'description': res.description or '',
                'url': res_url or '',
                'file_url': res_url or '',
                'fileUrl': res_url or '',
                'resource_type': res.resource_type or 'document',
                'resourceType': res.resource_type or 'document',
                'allow_download': res.allow_download,
                'allowDownload': res.allow_download,
                'file_name': mf.original_filename if mf else (res.title or 'Resource'),
                'fileName': mf.original_filename if mf else (res.title or 'Resource'),
                'mime_type': mf.mime_type if mf else 'application/pdf',
                'mimeType': mf.mime_type if mf else 'application/pdf',
                'size_bytes': mf.size_bytes if mf else 0,
                'fileSize': mf.size_bytes if mf else 0,
            })

        # Media URL (primary media if uploaded)
        primary_media = lesson.media_files.filter(media_role='PRIMARY').first()
        if not primary_media:
            primary_media = lesson.media_files.first()
        media_url = None
        if primary_media and primary_media.media_file:
            media_url = primary_media.media_file.file_url or primary_media.media_file.relative_path or None

        # Content (rich text or description)
        rich_text_obj = getattr(lesson, 'rich_text', None)
        content = rich_text_obj.content if rich_text_obj else lesson.description

        # Quiz data (if QUIZ type)
        quiz_data = None
        quiz_obj = getattr(lesson, 'quiz', None)
        if quiz_obj:
            questions_data = []
            for q in quiz_obj.questions.all():
                options_data = [{'id': str(o.id), 'text': o.option_text} for o in q.options.all()]
                questions_data.append({
                    'id': str(q.id),
                    'question_type': q.question_type,
                    'question_text': q.question_text,
                    'explanation': q.explanation,
                    'points': q.points,
                    'options': options_data,
                })
            quiz_data = {
                'id': str(quiz_obj.id),
                'title': quiz_obj.title,
                'instructions': quiz_obj.instructions,
                'passing_score': quiz_obj.passing_score,
                'time_limit_minutes': quiz_obj.time_limit_minutes,
                'questions': questions_data,
            }

        # Assignment data (if ASSIGNMENT type)
        assignment_data = None
        assignment_obj = getattr(lesson, 'assignment', None)
        if assignment_obj:
            assignment_data = {
                'id': str(assignment_obj.id),
                'title': assignment_obj.title,
                'instructions': assignment_obj.instructions,
                'due_date': assignment_obj.due_date.isoformat() if assignment_obj.due_date else None,
                'due_days': assignment_obj.due_days,
                'max_marks': assignment_obj.max_marks,
                'allow_text_submission': assignment_obj.allow_text_submission,
                'allow_file_submission': assignment_obj.allow_file_submission,
            }

        is_completed = progress.status == ProgressStatus.COMPLETED if progress else False

        return Response({
            'lesson': {
                'id': str(lesson.id),
                'uuid': str(lesson.id),
                'title': lesson.title,
                'description': lesson.description,
                'content': content,
                'lesson_type': lesson.lesson_type,
                'duration_minutes': lesson.duration_minutes,
                'is_demo': lesson.is_demo,
                'allow_download': lesson.allow_download,
                'external_url': lesson.external_url,
                'media_url': media_url,
                'completed': is_completed,
                'is_completed': is_completed,
                'unlocked': True,
                'quiz': quiz_data,
                'assignment': assignment_data,
                'resources': resources_data,
            },
            'resources': resources_data,
        })

    @action(detail=False, methods=['post'], url_path=r'academies/(?P<academy_uuid>[^/.]+)/courses/(?P<course_uuid>[^/.]+)/lessons/(?P<lesson_uuid>[^/.]+)/complete')
    def mark_lesson_complete(self, request, academy_uuid=None, course_uuid=None, lesson_uuid=None):
        """Idempotently marks a lesson complete and recalculates course progress."""
        user = request.user
        if not user.is_authenticated:
            return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        from academy.models import Academy
        from lessons.models import Lesson
        from learning_progress.models import CourseProgress, LessonProgress, ProgressStatus

        try:
            academy = Academy.objects.get(id=academy_uuid)
            course = Course.objects.get(id=course_uuid, academy=academy)
            lesson = Lesson.objects.get(id=lesson_uuid, module__course=course, is_active=True)
        except (Academy.DoesNotExist, Course.DoesNotExist, Lesson.DoesNotExist, ValueError):
            return Response({'detail': 'Requested resource not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            enrollment = Enrollment.objects.get(
                student=user,
                course=course,
                status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.EXPIRED]
            )
        except Enrollment.DoesNotExist:
            return Response({'detail': 'You are not enrolled in this course.'}, status=status.HTTP_403_FORBIDDEN)

        course_progress, _ = CourseProgress.objects.get_or_create(student=user, course=course, defaults={'enrollment': enrollment})

        lesson_progress, _ = LessonProgress.objects.get_or_create(
            student=user,
            lesson=lesson,
            defaults={'course_progress': course_progress}
        )
        if lesson_progress.status != ProgressStatus.COMPLETED:
            lesson_progress.status = ProgressStatus.COMPLETED
            lesson_progress.completion_percent = 100.00
            lesson_progress.completed_at = timezone.now()
            lesson_progress.save()

        total_active_lessons = Lesson.objects.filter(module__course=course, is_active=True).count()
        completed_lessons = LessonProgress.objects.filter(
            student=user,
            lesson__module__course=course,
            status=ProgressStatus.COMPLETED
        ).count()

        pct = (completed_lessons / total_active_lessons * 100.0) if total_active_lessons > 0 else 0.0
        course_progress.completed_lessons = completed_lessons
        course_progress.total_lessons = total_active_lessons
        course_progress.progress_percent = round(pct, 2)
        if completed_lessons >= total_active_lessons and total_active_lessons > 0:
            course_progress.status = ProgressStatus.COMPLETED
        elif completed_lessons > 0:
            course_progress.status = ProgressStatus.IN_PROGRESS
        course_progress.save()

        enrollment.progress_percent = course_progress.progress_percent
        enrollment.save(update_fields=['progress_percent'])

        from learning_progress.services import StudentCourseProgressionService
        progression = StudentCourseProgressionService.get_student_course_progression(user, course)

        return Response({
            'success': True,
            'lesson_id': str(lesson.id),
            'completed': True,
            'course_progress_percent': float(course_progress.progress_percent),
            'completed_lessons': completed_lessons,
            'total_lessons': total_active_lessons,
            'next_lesson': {
                'id': progression['resume_lesson_id'],
                'unlocked': True
            } if progression.get('resume_lesson_id') else None
        })

#--------------------------------------------------------------
# Enrollment ViewSet
#--------------------------------------------------------------

class EnrollmentViewSet(viewsets.ModelViewSet):
    """ViewSet for Academy Admins/Staff to manage student enrollments."""
    permission_classes = [permissions.IsAuthenticated, IsStudentOwnerOrAcademyStaff]

    def get_serializer_class(self):
        if self.action in ['retrieve']:
            return EnrollmentDetailSerializer
        return EnrollmentSerializer

    def get_queryset(self):
        params = self.request.query_params
        return EnrollmentSelector.get_academy_enrollments(
            user=self.request.user,
            course_id=params.get('course') or params.get('course_id'),
            student_id=params.get('student') or params.get('student_id'),
            status=params.get('status'),
            access_type=params.get('access_type'),
            source=params.get('source'),
            expired=params.get('expired') == 'true' if params.get('expired') else None,
            expiring_soon=params.get('expiring_soon') == 'true' if params.get('expiring_soon') else None,
            search=params.get('search')
        )

    def create(self, request, *args, **kwargs):
        serializer = CreateEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            student = User.objects.get(id=data['student_id'])
            course = Course.objects.get(id=data['course_id'])
        except User.DoesNotExist:
            raise CubixSkillAPIException("Student user not found.", code="USER_NOT_FOUND", status_code=404)
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

        enrollment = EnrollmentService.enroll_student(
            student=student,
            course=course,
            access_type=data.get('access_type', AccessType.FULL),
            source=data.get('source', EnrollmentSource.MANUAL),
            source_reference=data.get('source_reference', ''),
            is_lifetime=data.get('is_lifetime', True),
            access_expires_at=data.get('access_expires_at'),
            created_by=request.user
        )
        return Response(EnrollmentDetailSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.resume_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def extend(self, request, pk=None):
        enrollment = self.get_object()
        serializer = ExtendEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = EnrollmentService.extend_access(
            enrollment,
            additional_days=data.get('additional_days'),
            new_expiry_date=data.get('new_expiry_date'),
            reason=data.get('reason', ''),
            performed_by=request.user
        )
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.suspend_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.resume_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.revoke_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.cancel_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        enrollment = self.get_object()
        is_lifetime = request.data.get('is_lifetime', True)
        access_expires_at = request.data.get('access_expires_at')
        source_reference = request.data.get('source_reference', '')

        updated = EnrollmentService.upgrade_demo_to_full(
            enrollment,
            is_lifetime=is_lifetime,
            access_expires_at=access_expires_at,
            source_reference=source_reference,
            performed_by=request.user
        )
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=False, methods=['post'])
    def bulk(self, request):
        serializer = BulkEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            course = Course.objects.get(id=data['course_id'])
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

        students = User.objects.filter(id__in=data['student_ids'])
        results = EnrollmentService.bulk_enroll(
            students=students,
            course=course,
            access_type=data.get('access_type', AccessType.FULL),
            is_lifetime=data.get('is_lifetime', True),
            access_expires_at=data.get('access_expires_at'),
            created_by=request.user
        )
        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        enrollment = self.get_object()
        history = EnrollmentSelector.get_enrollment_history(enrollment.id)
        return Response({
            'access_periods': EnrollmentAccessPeriodSerializer(history['periods'], many=True).data,
            'events': EnrollmentEventSerializer(history['events'], many=True).data
        })
