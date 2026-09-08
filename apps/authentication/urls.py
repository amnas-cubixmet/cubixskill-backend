from django.urls import path

from .views import (
    ChangePasswordView,
    CookieTokenRefreshView,
    CurrentUserView,
    ForgotPasswordView,
    InstructorCookieTokenRefreshView,
    InstructorCurrentUserView,
    InstructorLoginView,
    InstructorLogoutView,
    LoginView,
    LogoutView,
    RegisterAcademyView,
    RegisterStudentView,
    ResendSetupEmailView,
    ResendVerificationEmailView,
    ResendVerificationView,
    ResetPasswordView,
    SetupPasswordView,
    StudentCookieTokenRefreshView,
    StudentCurrentUserView,
    StudentLoginView,
    StudentLogoutView,
    TokenValidateView,
    VerifyEmailView,
)

urlpatterns = [
    # Dedicated Student Auth Endpoints
    path('student/login/', StudentLoginView.as_view(), name='auth-student-login'),
    path('student/refresh/', StudentCookieTokenRefreshView.as_view(), name='auth-student-refresh'),
    path('student/logout/', StudentLogoutView.as_view(), name='auth-student-logout'),
    path('student/me/', StudentCurrentUserView.as_view(), name='auth-student-me'),

    # Dedicated Instructor Auth Endpoints
    path('instructor/login/', InstructorLoginView.as_view(), name='auth-instructor-login'),
    path('instructor/refresh/', InstructorCookieTokenRefreshView.as_view(), name='auth-instructor-refresh'),
    path('instructor/logout/', InstructorLogoutView.as_view(), name='auth-instructor-logout'),
    path('instructor/me/', InstructorCurrentUserView.as_view(), name='auth-instructor-me'),

    # Generic & Public Auth Endpoints
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

