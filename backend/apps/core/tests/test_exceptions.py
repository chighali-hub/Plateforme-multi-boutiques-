import json
import logging

import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import RequestDataTooBig
from django.http import Http404
from rest_framework import exceptions, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.core.exceptions import (
    BusinessError,
    CartChanged,
    InvalidStateTransition,
    ShopExpired,
)


class _Input(serializers.Serializer):
    phone = serializers.CharField(max_length=8)


def _call(exc: Exception | None = None, data=None, headers=None):
    class _View(APIView):
        permission_classes = [AllowAny]
        authentication_classes: list = []

        def post(self, request):
            if exc is not None:
                raise exc
            _Input(data=request.data).is_valid(raise_exception=True)
            return Response({})

    request = APIRequestFactory().post("/", data or {}, format="json", **(headers or {}))
    return _View.as_view()(request)


def _error(response) -> dict:
    response.render()
    return json.loads(response.content)["error"]


def test_validation_error_lists_fields():
    response = _call(data={"phone": "123456789"})
    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert "phone" in error["details"]
    assert error["message"]


def test_validation_error_with_list_detail_goes_to_non_field_errors():
    response = _call(exceptions.ValidationError(["Panier vide."]))
    assert _error(response)["details"] == {"non_field_errors": ["Panier vide."]}


@pytest.mark.parametrize(
    "exc, http_status, code",
    [
        (exceptions.NotAuthenticated(), 401, "AUTHENTICATION_REQUIRED"),
        (exceptions.AuthenticationFailed(), 401, "TOKEN_INVALID"),
        (InvalidToken(), 401, "TOKEN_INVALID"),
        (exceptions.PermissionDenied(), 403, "PERMISSION_DENIED"),
        (DjangoPermissionDenied(), 403, "PERMISSION_DENIED"),
        (exceptions.NotFound(), 404, "NOT_FOUND"),
        (Http404(), 404, "NOT_FOUND"),
        (exceptions.MethodNotAllowed("PUT"), 405, "METHOD_NOT_ALLOWED"),
        (exceptions.UnsupportedMediaType("text/xml"), 415, "UNSUPPORTED_MEDIA_TYPE"),
        (exceptions.ParseError(), 400, "VALIDATION_ERROR"),
        (RequestDataTooBig(), 413, "FILE_TOO_LARGE"),
    ],
)
def test_drf_exceptions_map_to_stable_codes(exc, http_status, code):
    response = _call(exc)
    assert response.status_code == http_status
    error = _error(response)
    assert error["code"] == code
    assert error["details"] == {}


def test_throttled_exposes_retry_after_rounded_up():
    response = _call(exceptions.Throttled(wait=41.2))
    assert response.status_code == 429
    error = _error(response)
    assert error["code"] == "THROTTLED"
    assert error["details"] == {"retry_after": 42}
    assert response["Retry-After"] == "42"


def test_business_error_keeps_code_status_and_details():
    response = _call(InvalidStateTransition(details={"current_status": "DELIVERED"}))
    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "INVALID_STATE_TRANSITION"
    assert error["details"] == {"current_status": "DELIVERED"}


def test_business_error_custom_message():
    response = _call(CartChanged(message="Panier modifie.", details={"current_total": 4500}))
    assert _error(response)["message"] == "Panier modifie."


def test_shop_expired_is_forbidden():
    assert _call(ShopExpired()).status_code == 403


def test_base_business_error_defaults_to_400():
    response = _call(BusinessError())
    assert response.status_code == 400
    assert _error(response)["code"] == "BUSINESS_ERROR"


def test_unexpected_exception_returns_generic_500_without_leak(caplog):
    secret = "SELECT password FROM accounts_user"
    with caplog.at_level(logging.ERROR, logger="apps.core.exceptions"):
        response = _call(RuntimeError(secret))
    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "SERVER_ERROR"
    assert error["details"] == {}
    response.render()
    assert secret not in response.content.decode()
    assert "RuntimeError" not in response.content.decode()
    # La pile d'appels est journalisee cote serveur.
    assert any(record.exc_info for record in caplog.records)


def test_messages_follow_accept_language():
    response = _call(exceptions.NotFound(), headers={"HTTP_ACCEPT_LANGUAGE": "fr"})
    assert _error(response)["message"] == "Ressource introuvable."
