"""Format d'erreur unique de l'API et exceptions metier.

Toutes les erreurs sortent sous la forme :
    {"error": {"code": "...", "message": "...", "details": {...}}}

Voir docs/Documentation-API/03-reference-api.md (sections 0.4 et 0.5) et
05-aspects-transversaux.md (section 3).
"""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import RequestDataTooBig
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)


class BusinessError(drf_exceptions.APIException):
    """Erreur metier levee par un service. Jamais une Response."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BUSINESS_ERROR"
    default_message = _("Opération impossible.")

    def __init__(self, message=None, details: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(detail=self.message, code=self.code)


# --- 400 ------------------------------------------------------------------------
class OtpInvalid(BusinessError):
    code = "OTP_INVALID"
    default_message = _("Le code saisi est incorrect.")


class OtpExpired(BusinessError):
    code = "OTP_EXPIRED"
    default_message = _("Ce code a expiré ou n'est plus valable. Demandez un nouveau code.")


class OtpTooManyAttempts(BusinessError):
    code = "OTP_TOO_MANY_ATTEMPTS"
    default_message = _("Trop d'essais incorrects. Demandez un nouveau code.")


class ResetTokenInvalid(BusinessError):
    code = "RESET_TOKEN_INVALID"
    default_message = _("Ce lien de réinitialisation est invalide ou a expiré.")


# --- 401 ------------------------------------------------------------------------
class InvalidCredentials(BusinessError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"
    default_message = _("E-mail ou mot de passe incorrect.")


# --- 403 ------------------------------------------------------------------------
class EmailNotVerified(BusinessError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "EMAIL_NOT_VERIFIED"
    default_message = _("Votre adresse e-mail n'est pas encore vérifiée.")


class ShopBlocked(BusinessError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "SHOP_BLOCKED"
    default_message = _("Ce compte est bloqué. Contactez l'administrateur.")


class ShopExpired(BusinessError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "SHOP_EXPIRED"
    default_message = _("Ce compte a expiré. Pour le recharger, contactez l'administrateur.")


class ShopStateForbidden(BusinessError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "SHOP_STATE_FORBIDDEN"
    default_message = _("Cette action n'est pas disponible dans l'état actuel de la boutique.")


# --- 409 ------------------------------------------------------------------------
class EmailAlreadyUsed(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "EMAIL_ALREADY_USED"
    default_message = _("Cette adresse e-mail est déjà utilisée.")


class AlreadyVerified(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "ALREADY_VERIFIED"
    default_message = _("Cette adresse e-mail est déjà vérifiée.")


class InvalidStateTransition(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "INVALID_STATE_TRANSITION"
    default_message = _("Cette action n'est pas possible dans l'état actuel.")


class OnboardingStepMismatch(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "ONBOARDING_STEP_MISMATCH"
    default_message = _("Cette étape de l'inscription n'est pas disponible maintenant.")


class LimitReached(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "LIMIT_REACHED"
    default_message = _("La limite autorisée est atteinte.")


class ImportAlreadyRunning(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "IMPORT_ALREADY_RUNNING"
    default_message = _("Un import est déjà en cours.")


class CartChanged(BusinessError):
    status_code = status.HTTP_409_CONFLICT
    code = "CART_CHANGED"
    default_message = _("Certains produits du panier ne sont plus disponibles.")


# --- 413 ------------------------------------------------------------------------
class FileTooLarge(BusinessError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    code = "FILE_TOO_LARGE"
    default_message = _("Le fichier est trop volumineux.")


# --- 429 ------------------------------------------------------------------------
class OtpResendTooSoon(BusinessError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "OTP_RESEND_TOO_SOON"
    default_message = _("Veuillez patienter avant de demander un nouveau code.")


# --- Correspondance des exceptions DRF -----------------------------------------
_MESSAGES = {
    "VALIDATION_ERROR": _("Les données envoyées sont invalides."),
    "AUTHENTICATION_REQUIRED": _("Authentification requise."),
    "TOKEN_INVALID": _("Session invalide ou expirée."),
    "PERMISSION_DENIED": _("Vous n'avez pas accès à cette ressource."),
    "NOT_FOUND": _("Ressource introuvable."),
    "METHOD_NOT_ALLOWED": _("Méthode non autorisée."),
    "UNSUPPORTED_MEDIA_TYPE": _("Format de requête non pris en charge."),
    "NOT_ACCEPTABLE": _("Format de réponse non disponible."),
    "THROTTLED": _("Trop de requêtes. Réessayez plus tard."),
    "FILE_TOO_LARGE": _("Le fichier est trop volumineux."),
    "SERVER_ERROR": _("Une erreur inattendue est survenue."),
}


def _error_response(code: str, message, details: dict | None, http_status: int, headers=None):
    body = {"error": {"code": code, "message": str(message), "details": details or {}}}
    return Response(body, status=http_status, headers=headers)


def _classify(exc: Exception) -> tuple[str, int, dict] | None:
    """Renvoie (code, statut HTTP, details) pour une exception connue."""
    if isinstance(exc, drf_exceptions.ValidationError):
        detail = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        return "VALIDATION_ERROR", status.HTTP_400_BAD_REQUEST, detail
    if isinstance(exc, drf_exceptions.NotAuthenticated):
        return "AUTHENTICATION_REQUIRED", status.HTTP_401_UNAUTHORIZED, {}
    if isinstance(exc, InvalidToken | TokenError | drf_exceptions.AuthenticationFailed):
        return "TOKEN_INVALID", status.HTTP_401_UNAUTHORIZED, {}
    if isinstance(exc, drf_exceptions.PermissionDenied | DjangoPermissionDenied):
        return "PERMISSION_DENIED", status.HTTP_403_FORBIDDEN, {}
    if isinstance(exc, drf_exceptions.NotFound | Http404):
        return "NOT_FOUND", status.HTTP_404_NOT_FOUND, {}
    if isinstance(exc, drf_exceptions.MethodNotAllowed):
        return "METHOD_NOT_ALLOWED", status.HTTP_405_METHOD_NOT_ALLOWED, {}
    if isinstance(exc, drf_exceptions.NotAcceptable):
        return "NOT_ACCEPTABLE", status.HTTP_406_NOT_ACCEPTABLE, {}
    if isinstance(exc, drf_exceptions.UnsupportedMediaType):
        return "UNSUPPORTED_MEDIA_TYPE", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, {}
    if isinstance(exc, drf_exceptions.Throttled):
        retry_after = int(exc.wait) if exc.wait is not None else None
        return "THROTTLED", status.HTTP_429_TOO_MANY_REQUESTS, {"retry_after": retry_after}
    if isinstance(exc, RequestDataTooBig):
        return "FILE_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, {}
    if isinstance(exc, drf_exceptions.ParseError):
        return "VALIDATION_ERROR", status.HTTP_400_BAD_REQUEST, {}
    return None


def api_exception_handler(exc: Exception, context: dict) -> Response:
    """Gestionnaire unique declare dans REST_FRAMEWORK["EXCEPTION_HANDLER"].

    Les exceptions inattendues sont journalisees avec la pile d'appels et
    renvoyees sous un message generique, sans aucun detail interne.
    """
    if isinstance(exc, BusinessError):
        return _error_response(exc.code, exc.message, exc.details, exc.status_code)

    classified = _classify(exc)
    if classified is not None:
        code, http_status, details = classified
        headers = {}
        if code == "THROTTLED" and details.get("retry_after") is not None:
            headers["Retry-After"] = str(details["retry_after"])
        return _error_response(code, _MESSAGES[code], details, http_status, headers)

    view = context.get("view")
    logger.exception(
        "Erreur inattendue dans la vue %s", view.__class__.__name__ if view else "inconnue"
    )
    return _error_response(
        "SERVER_ERROR", _MESSAGES["SERVER_ERROR"], {}, status.HTTP_500_INTERNAL_SERVER_ERROR
    )
