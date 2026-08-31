from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from courses.models import Course
from lessons.models import Lesson
from students.models import StudentCustomFieldDefinition
from features.services import CourseFeatureService

class CertificateFieldDiscoveryService:
    """
    Authoritative service to discover dynamic certificate fields for a given Course context.
    Evaluates real course lessons, quizzes, assignments, and academy custom fields.
    """

    @classmethod
    def get_available_fields_for_course(cls, course_id: str, academy=None) -> list[dict]:
        course = get_object_or_404(Course, pk=course_id)

        # Tenant guard if academy is provided
        if academy and course.academy_id and course.academy_id != academy.id:
            raise ValidationError("Access denied: Course belongs to another academy.")

        fields = []

        # 1. Base Student Fields (Grouped under Personal Details)
        fields.extend([
            {"key": "student.full_name", "label": "Student Name", "group": "Personal Details (Custom Student Fields)", "type": "text", "available": True},
            {"key": "student.student_code", "label": "Student ID", "group": "Personal Details (Custom Student Fields)", "type": "text", "available": True},
            {"key": "student.email", "label": "Student Email", "group": "Personal Details (Custom Student Fields)", "type": "text", "available": True},
            {"key": "student.phone", "label": "Student Phone", "group": "Personal Details (Custom Student Fields)", "type": "text", "available": True},
        ])

        # 2. Base Course Fields
        fields.extend([
            {"key": "course.title", "label": "Course Name", "group": "Course", "type": "text", "available": True},
            {"key": "course.code", "label": "Course Code", "group": "Course", "type": "text", "available": True},
            {"key": "academy.name", "label": "Academy Name", "group": "Academy", "type": "text", "available": True},
            {"key": "instructor.name", "label": "Instructor Name", "group": "Academy", "type": "text", "available": True},
        ])

        # 3. Base Certificate Fields
        fields.extend([
            {"key": "certificate.number", "label": "Certificate Number", "group": "Certificate", "type": "text", "available": True},
            {"key": "certificate.issue_date", "label": "Issue Date", "group": "Certificate", "type": "text", "available": True},
            {"key": "certificate.completion_date", "label": "Completion Date", "group": "Certificate", "type": "text", "available": True},
        ])

        # 4. Enrollment & Progress Fields
        fields.extend([
            {"key": "enrollment.enrolled_at", "label": "Enrollment Date", "group": "Enrollment", "type": "text", "available": True},
            {"key": "enrollment.progress_percent", "label": "Completion Percentage", "group": "Enrollment", "type": "text", "available": True},
        ])

        # 5. Assessment Fields — Discovered by inspecting real course lessons & features
        has_lessons_feature = CourseFeatureService.has_feature(course, 'LESSONS')
        if has_lessons_feature:
            course_lessons = Lesson.objects.filter(module__course=course)
            has_assignments = course_lessons.filter(lesson_type='ASSIGNMENT').exists()
            has_quizzes = course_lessons.filter(lesson_type='TEST').exists()

            fields.append({
                "key": "assessment.overall_score",
                "label": "Overall Course Score",
                "group": "Assessment",
                "type": "number",
                "available": True
            })

            if has_assignments:
                fields.append({
                    "key": "assessment.assignment_overall_score",
                    "label": "Overall Assignment Score",
                    "group": "Assessment",
                    "type": "number",
                    "available": True
                })

            if has_quizzes:
                fields.append({
                    "key": "assessment.quiz_overall_score",
                    "label": "Overall Quiz Score",
                    "group": "Assessment",
                    "type": "number",
                    "available": True
                })

        # 6. Personal Details / Student Custom Fields
        target_academy = course.academy or academy
        if target_academy:
            custom_defs = StudentCustomFieldDefinition.objects.filter(
                academy=target_academy,
                available_for_certificate=True,
                is_active=True
            ).order_by('sort_order')

            for cf in custom_defs:
                fields.append({
                    "key": f"student.custom.{cf.key}",
                    "label": f"Student {cf.label}",
                    "group": "Personal Details (Custom Student Fields)",
                    "type": "text",
                    "available": True
                })

        return fields
