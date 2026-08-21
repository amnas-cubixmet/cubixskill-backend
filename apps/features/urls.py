from django.urls import path, include
from rest_framework.routers import DefaultRouter
from features.views import (
    FeatureViewSet,
    CourseFeatureViewSet,
    student_course_features_view,
    student_available_features_view,
    academy_features_summary_view,
)

router = DefaultRouter()
router.register(r'features', FeatureViewSet, basename='feature')

course_features_list = CourseFeatureViewSet.as_view({'get': 'list'})
course_feature_enable = CourseFeatureViewSet.as_view({'post': 'enable_feature'})
course_feature_disable = CourseFeatureViewSet.as_view({'post': 'disable_feature'})
course_feature_save_bulk = CourseFeatureViewSet.as_view({'post': 'save_bulk'})

urlpatterns = [
    path('', include(router.urls)),
    
    # Course Feature management APIs
    path('courses/<uuid:course_id>/features/', course_features_list, name='course-features-list'),
    path('courses/<uuid:course_id>/features/save-bulk/', course_feature_save_bulk, name='course-features-save-bulk'),
    path('courses/<uuid:course_id>/features/<str:feature_code>/enable/', course_feature_enable, name='course-feature-enable'),
    path('courses/<uuid:course_id>/features/<str:feature_code>/disable/', course_feature_disable, name='course-feature-disable'),
    
    # Student Feature entitlement APIs
    path('student/courses/<uuid:course_id>/features/', student_course_features_view, name='student-course-features'),
    path('student/features/', student_available_features_view, name='student-available-features'),

    # Academy derived summary API
    path('academy/features/', academy_features_summary_view, name='academy-features-summary'),
]
