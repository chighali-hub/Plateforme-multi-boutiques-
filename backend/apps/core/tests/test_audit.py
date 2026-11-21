import pytest
from rest_framework.test import APIRequestFactory

from apps.core.audit import get_client_ip, log_action
from apps.core.models import AuditAction, AuditLog

pytestmark = pytest.mark.django_db


def test_log_action_records_actor_target_metadata_and_ip(admin_user, make_shop):
    shop = make_shop("PENDING")
    request = APIRequestFactory().post("/", REMOTE_ADDR="197.231.1.10")

    entry = log_action(
        admin_user, AuditAction.SHOP_APPROVED, target=shop, metadata={"k": 1}, request=request
    )

    entry.refresh_from_db()
    assert entry.actor == admin_user
    assert (entry.action, entry.target_type, entry.target_id) == ("SHOP_APPROVED", "shop", shop.id)
    assert entry.metadata == {"k": 1}
    assert entry.ip_address == "197.231.1.10"


def test_log_action_without_request_or_actor():
    entry = log_action(None, AuditAction.SETTINGS_UPDATED, target_type="platform_settings")
    assert entry.actor is None and entry.ip_address is None and entry.target_id is None


def test_client_ip_ignores_forwarded_header_without_trusted_proxy(settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": None}
    request = APIRequestFactory().get("/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert get_client_ip(request) == "10.0.0.2"


def test_client_ip_uses_entry_set_by_trusted_proxy(settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    request = APIRequestFactory().get(
        "/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="6.6.6.6, 197.231.1.10"
    )
    # Le client peut forger la premiere valeur ; seule la derniere vient du proxy.
    assert get_client_ip(request) == "197.231.1.10"


def test_audit_entries_are_append_only():
    entry = log_action(None, AuditAction.ADMIN_LOGIN, target_type="user")
    entry.metadata = {"modifie": True}
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()
    assert AuditLog.objects.get(pk=entry.pk).metadata == {}
