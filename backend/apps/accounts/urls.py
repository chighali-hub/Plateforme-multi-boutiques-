"""Routes de l'authentification et du compte. Voir 03-reference-api.md sections 3 et 4."""

from django.urls import path

from . import views

urlpatterns = [
    path("auth/shop/register/", views.ShopRegisterView.as_view(), name="accounts-shop-register"),
    path("auth/shop/verify-email/", views.VerifyEmailView.as_view(), name="accounts-verify-email"),
    path("auth/otp/resend/", views.ResendOtpView.as_view(), name="accounts-otp-resend"),
    path("auth/shop/login/", views.ShopLoginView.as_view(), name="accounts-shop-login"),
    path("auth/admin/login/", views.AdminLoginView.as_view(), name="accounts-admin-login"),
    path("auth/token/refresh/", views.TokenRefreshView.as_view(), name="accounts-token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="accounts-logout"),
    path(
        "auth/password/forgot/",
        views.ForgotPasswordView.as_view(),
        name="accounts-password-forgot",
    ),
    path(
        "auth/password/verify-code/",
        views.VerifyResetCodeView.as_view(),
        name="accounts-password-verify-code",
    ),
    path("auth/password/reset/", views.ResetPasswordView.as_view(), name="accounts-password-reset"),
    path("auth/me/", views.MeView.as_view(), name="accounts-me"),
    path(
        "account/change-password/",
        views.ChangePasswordView.as_view(),
        name="accounts-change-password",
    ),
    path(
        "account/change-email/request/",
        views.ChangeEmailRequestView.as_view(),
        name="accounts-change-email-request",
    ),
    path(
        "account/change-email/confirm/",
        views.ChangeEmailConfirmView.as_view(),
        name="accounts-change-email-confirm",
    ),
]
