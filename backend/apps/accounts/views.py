"""Vues de l'authentification et du compte. Voir 03-reference-api.md sections 3 et 4.

Vues fines : validation par serializer, appel d'un service, reponse.
"""

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import TokenInvalid
from apps.core.permissions import IsActiveAccount

from . import serializers, services
from .tokens import (
    InvalidRefreshToken,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)

TAG_AUTH = "Auth"
TAG_ACCOUNT = "Compte"


def _errors(*codes: str) -> dict:
    """Reponses d'erreur documentees dans Swagger : {statut: description}."""
    by_status: dict[int, list[str]] = {}
    for item in codes:
        http_status, code = item.split(" ", 1)
        by_status.setdefault(int(http_status), []).append(code)
    return {
        http_status: OpenApiResponse(description=", ".join(names))
        for http_status, names in by_status.items()
    }


def _language(request) -> str:
    return getattr(request, "LANGUAGE_CODE", None) or settings.LANGUAGE_CODE


def _tokens_response(request, user, http_status=status.HTTP_200_OK) -> Response:
    payload = {**issue_tokens(user), "user": user}
    data = serializers.TokensSerializer(payload, context={"request": request}).data
    return Response(data, status=http_status)


class PublicAuthView(APIView):
    """Endpoints publics : aucun jeton lu (un jeton perime ne bloque pas la connexion)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []


class ShopRegisterView(PublicAuthView):
    throttle_scope = "auth"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Inscription d'une boutique",
        request={"multipart/form-data": serializers.RegisterSerializer},
        responses={
            201: serializers.RegisterResponseSerializer,
            **_errors(
                "400 VALIDATION_ERROR",
                "409 EMAIL_ALREADY_USED",
                "413 FILE_TOO_LARGE",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_shop(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            shop_fields=serializer.shop_fields(),
            files=serializer.processed_files(),
            language=_language(request),
        )
        return Response(
            {
                "email": user.email,
                "otp_expires_in": settings.OTP_CODE_TTL_SECONDS,
                "resend_available_in": settings.OTP_RESEND_COOLDOWN_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(PublicAuthView):
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Valider l'e-mail d'inscription",
        request=serializers.EmailCodeSerializer,
        responses={
            200: serializers.TokensSerializer,
            **_errors(
                "400 VALIDATION_ERROR",
                "400 OTP_INVALID",
                "400 OTP_EXPIRED",
                "400 OTP_TOO_MANY_ATTEMPTS",
                "409 ALREADY_VERIFIED",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.EmailCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.verify_registration_email(**serializer.validated_data)
        return _tokens_response(request, user)


class ResendOtpView(PublicAuthView):
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Renvoyer un code",
        request=serializers.ResendOtpSerializer,
        responses={
            200: serializers.ResendResponseSerializer,
            **_errors("400 VALIDATION_ERROR", "429 OTP_RESEND_TOO_SOON", "429 THROTTLED"),
        },
    )
    def post(self, request):
        serializer = serializers.ResendOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resend_otp(language=_language(request), **serializer.validated_data)
        return Response({"resend_available_in": settings.OTP_RESEND_COOLDOWN_SECONDS})


class ShopLoginView(PublicAuthView):
    throttle_scope = "auth"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Connexion boutique",
        request=serializers.LoginSerializer,
        responses={
            200: serializers.TokensSerializer,
            **_errors(
                "400 VALIDATION_ERROR",
                "401 INVALID_CREDENTIALS",
                "403 EMAIL_NOT_VERIFIED",
                "403 SHOP_BLOCKED",
                "403 SHOP_EXPIRED",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.login_shop(**serializer.validated_data)
        return _tokens_response(request, user)


class AdminLoginView(PublicAuthView):
    throttle_scope = "admin_auth"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Connexion administrateur",
        request=serializers.LoginSerializer,
        responses={
            200: serializers.TokensSerializer,
            **_errors("400 VALIDATION_ERROR", "401 INVALID_CREDENTIALS", "429 THROTTLED"),
        },
    )
    def post(self, request):
        serializer = serializers.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.login_admin(request=request, **serializer.validated_data)
        return _tokens_response(request, user)


class TokenRefreshView(PublicAuthView):
    @extend_schema(
        tags=[TAG_AUTH],
        summary="Rafraichir les jetons",
        request=serializers.RefreshSerializer,
        responses={
            200: serializers.TokenPairSerializer,
            **_errors("401 TOKEN_INVALID", "403 SHOP_BLOCKED", "403 SHOP_EXPIRED"),
        },
    )
    def post(self, request):
        serializer = serializers.RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _user, tokens = rotate_refresh_token(
                serializer.validated_data["refresh"], services.check_user_can_refresh
            )
        except InvalidRefreshToken:
            raise TokenInvalid() from None
        return Response(tokens)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Deconnexion",
        request=serializers.RefreshSerializer,
        responses={204: None, **_errors("401 TOKEN_INVALID", "401 AUTHENTICATION_REQUIRED")},
    )
    def post(self, request):
        serializer = serializers.RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            revoke_refresh_token(serializer.validated_data["refresh"], request.user)
        except InvalidRefreshToken:
            raise TokenInvalid() from None
        return Response(status=status.HTTP_204_NO_CONTENT)


class ForgotPasswordView(PublicAuthView):
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Mot de passe oublie : envoyer un code",
        request=serializers.ForgotPasswordSerializer,
        responses={
            200: serializers.ForgotResponseSerializer,
            **_errors("400 VALIDATION_ERROR", "429 THROTTLED"),
        },
    )
    def post(self, request):
        serializer = serializers.ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"], _language(request))
        return Response(
            {
                "otp_expires_in": settings.OTP_CODE_TTL_SECONDS,
                "resend_available_in": settings.OTP_RESEND_COOLDOWN_SECONDS,
            }
        )


class VerifyResetCodeView(PublicAuthView):
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Mot de passe oublie : verifier le code",
        request=serializers.EmailCodeSerializer,
        responses={
            200: serializers.ResetTokenResponseSerializer,
            **_errors(
                "400 VALIDATION_ERROR",
                "400 OTP_INVALID",
                "400 OTP_EXPIRED",
                "400 OTP_TOO_MANY_ATTEMPTS",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.EmailCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = services.verify_password_reset_code(**serializer.validated_data)
        return Response(
            {"reset_token": token, "expires_in": settings.PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS}
        )


class ResetPasswordView(PublicAuthView):
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Mot de passe oublie : definir le nouveau mot de passe",
        request=serializers.ResetPasswordSerializer,
        responses={
            204: None,
            **_errors("400 VALIDATION_ERROR", "400 RESET_TOKEN_INVALID", "429 THROTTLED"),
        },
    )
    def post(self, request):
        serializer = serializers.ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["reset_token"]
        serializer.validate_password_for(services.user_for_reset_token(token))
        services.reset_password(token, serializer.validated_data["new_password"], request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        tags=[TAG_AUTH],
        summary="Utilisateur connecte",
        responses={
            200: serializers.UserSerializer,
            **_errors("401 AUTHENTICATION_REQUIRED", "403 SHOP_BLOCKED", "403 SHOP_EXPIRED"),
        },
    )
    def get(self, request):
        return Response(serializers.UserSerializer(request.user, context={"request": request}).data)


class ChangePasswordView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        tags=[TAG_ACCOUNT],
        summary="Changer le mot de passe",
        request=serializers.ChangePasswordSerializer,
        responses={200: serializers.TokensSerializer, **_errors("400 VALIDATION_ERROR")},
    )
    def post(self, request):
        serializer = serializers.ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        tokens = services.change_password(request.user, serializer.validated_data["new_password"])
        data = serializers.TokensSerializer(
            {**tokens, "user": request.user}, context={"request": request}
        ).data
        return Response(data)


class ChangeEmailRequestView(APIView):
    permission_classes = [IsActiveAccount]
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_ACCOUNT],
        summary="Changer l'e-mail : envoyer un code a la nouvelle adresse",
        request=serializers.ChangeEmailRequestSerializer,
        responses={
            200: serializers.EmailChangeResponseSerializer,
            **_errors(
                "400 VALIDATION_ERROR",
                "409 EMAIL_ALREADY_USED",
                "429 OTP_RESEND_TOO_SOON",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.ChangeEmailRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        sent_to = services.request_email_change(
            request.user, serializer.validated_data["new_email"], _language(request)
        )
        return Response(
            {
                "sent_to": sent_to,
                "otp_expires_in": settings.OTP_CODE_TTL_SECONDS,
                "resend_available_in": settings.OTP_RESEND_COOLDOWN_SECONDS,
            }
        )


class ChangeEmailConfirmView(APIView):
    permission_classes = [IsActiveAccount]
    throttle_scope = "otp"

    @extend_schema(
        tags=[TAG_ACCOUNT],
        summary="Changer l'e-mail : confirmer le code",
        request=serializers.ChangeEmailConfirmSerializer,
        responses={
            200: serializers.UserSerializer,
            **_errors(
                "400 OTP_INVALID",
                "400 OTP_EXPIRED",
                "400 OTP_TOO_MANY_ATTEMPTS",
                "409 EMAIL_ALREADY_USED",
                "429 THROTTLED",
            ),
        },
    )
    def post(self, request):
        serializer = serializers.ChangeEmailConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.confirm_email_change(
            request.user,
            serializer.validated_data["code"],
            request=request,
            language=_language(request),
        )
        return Response(serializers.UserSerializer(user, context={"request": request}).data)
