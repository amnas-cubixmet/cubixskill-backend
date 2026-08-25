from rest_framework.routers import DefaultRouter
from django.urls import path, include
from users_roles.views import UserViewSet, RoleViewSet, PermissionViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'permissions', PermissionViewSet, basename='permission')

urlpatterns = [
    path('users/summary/', UserViewSet.as_view({'get': 'summary'}), name='user-summary'),
    path('', include(router.urls)),
]
