from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from authentication.views import (
    RegisterStudentView, RegisterAcademyView, LoginView, VerifyEmailView, ResendVerificationView,
    SetupPasswordView, ForgotPasswordView, ResetPasswordView, ChangePasswordView,
    LogoutView, CurrentUserView, TokenValidateView
)
urlpatterns = [
    path('register/academy/', RegisterAcademyView.as_view(), name='auth-register-academy'),
    path('register/student/', RegisterStudentView.as_view(), name='auth-register-student'),

    path('login/', LoginView.as_view(), name='auth-login'),
    path('token/validate/', TokenValidateView.as_view(), name='auth-token-validate'),
    path('email/verify/', VerifyEmailView.as_view(), name='auth-email-verify'),
    path('email/resend/', ResendVerificationView.as_view(), name='auth-email-resend'),

    path('password/setup/', SetupPasswordView.as_view(), name='auth-password-setup'),
    path('password/forgot/', ForgotPasswordView.as_view(), name='auth-password-forgot'),
    path('password/reset/', ResetPasswordView.as_view(), name='auth-password-reset'),
    path('password/change/', ChangePasswordView.as_view(), name='auth-password-change'),
    path('token/refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', CurrentUserView.as_view(), name='auth-me'),
]
