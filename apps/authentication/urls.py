from django.urls import path
from .views import (
    RegisterStudentView, RegisterAcademyView, LoginView, VerifyEmailView, ResendVerificationView,
    SetupPasswordView, ForgotPasswordView, ResetPasswordView, ChangePasswordView,
    LogoutView, CurrentUserView, TokenValidateView, ResendSetupEmailView, ResendVerificationEmailView,
    CookieTokenRefreshView
)
urlpatterns = [
    path('register/academy/', RegisterAcademyView.as_view(), name='auth-register-academy'),
    path('register/student/', RegisterStudentView.as_view(), name='auth-register-student'),

    path('login/', LoginView.as_view(), name='auth-login'),
    path('token/validate/', TokenValidateView.as_view(), name='auth-token-validate'),
    path('email/verify/', VerifyEmailView.as_view(), name='auth-email-verify'),
    path('email/resend/', ResendVerificationView.as_view(), name='auth-email-resend'),
    path('email/verification/resend/', ResendVerificationEmailView.as_view(), name='auth-email-verification-resend'),

    path('password/setup/', SetupPasswordView.as_view(), name='auth-password-setup'),
    path('password/setup/resend/', ResendSetupEmailView.as_view(), name='auth-password-setup-resend'),
    path('password/forgot/', ForgotPasswordView.as_view(), name='auth-password-forgot'),
    path('password/reset/', ResetPasswordView.as_view(), name='auth-password-reset'),
    path('password/change/', ChangePasswordView.as_view(), name='auth-password-change'),
    path('token/refresh/', CookieTokenRefreshView.as_view(), name='auth-token-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', CurrentUserView.as_view(), name='auth-me'),
]
