from courses.views import (
    CourseCategoryViewSet,
    CourseLanguageViewSet,
    CourseModuleViewSet,
    CourseViewSet,
)
from django.urls import include, path
from features.views import CourseFeatureViewSet
from rest_framework.routers import DefaultRouter

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses', CourseViewSet, basename='course')
router.register(r'course-categories', CourseCategoryViewSet, basename='course-category')
router.register(r'course-languages', CourseLanguageViewSet, basename='course-language')
router.register(r'course-modules', CourseModuleViewSet, basename='course-module')
router.register(r'', CourseViewSet, basename='course-root')

category_router = DefaultRouter()
category_router.register(r'', CourseCategoryViewSet, basename='course-category-direct')

from discussions_chat.views import CourseDiscussionViewSet

course_features_list = CourseFeatureViewSet.as_view({'get': 'list'})
course_feature_enable = CourseFeatureViewSet.as_view({'post': 'enable_feature'})
course_feature_disable = CourseFeatureViewSet.as_view({'post': 'disable_feature'})
course_feature_save_bulk = CourseFeatureViewSet.as_view({'post': 'save_bulk'})
course_discussions_list = CourseDiscussionViewSet.as_view({'get': 'list', 'post': 'create'})

urlpatterns = [
    path('<uuid:course_id>/discussions/', course_discussions_list, name='course-discussions-direct'),
    path('<uuid:course_id>/features/', course_features_list, name='course-features-list-direct'),
    path('<uuid:course_id>/features/save-bulk/', course_feature_save_bulk, name='course-features-save-bulk-direct'),
    path('<uuid:course_id>/features/<str:feature_code>/enable/', course_feature_enable, name='course-feature-enable-direct'),
    path('<uuid:course_id>/features/<str:feature_code>/disable/', course_feature_disable, name='course-feature-disable-direct'),
    path('', include(router.urls)),
    path('direct-categories/', include(category_router.urls)),
]
