from django.urls import include, path
from rest_framework.routers import DefaultRouter
from users_roles.views import PermissionViewSet, RoleViewSet, UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'permissions', PermissionViewSet, basename='permission')

urlpatterns = [
    path('users/summary/', UserViewSet.as_view({'get': 'summary'}), name='user-summary'),
    path('', include(router.urls)),
]
