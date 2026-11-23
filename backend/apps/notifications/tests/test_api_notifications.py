"""Notifications de la cloche (boutiques et admins). Voir 03-reference-api.md section 9."""

import pytest

from apps.accounts.tests.helpers import error_code
from apps.notifications.models import Notification, NotificationType
from apps.notifications.tests.factories import NotificationFactory

pytestmark = pytest.mark.django_db
LIST = "/api/v1/notifications/"
UNREAD = "/api/v1/notifications/unread-count/"
READ_ALL = "/api/v1/notifications/read-all/"


def _read_url(notification: Notification) -> str:
    return f"{LIST}{notification.pk}/read/"


def _rejected(user, reason="votre carte d'identité n'est pas lisible.", **kwargs):
    return NotificationFactory(
        recipient=user, type=NotificationType.SHOP_REJECTED, data={"reason": reason}, **kwargs
    )


# --- Liste ------------------------------------------------------------------------
def test_list_returns_own_notifications_newest_first(shop_client, other_shop_client):
    first = _rejected(shop_client.user)
    second = NotificationFactory(recipient=shop_client.user)
    NotificationFactory(recipient=other_shop_client.user)

    response = shop_client.get(LIST)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["results"]] == [second.id, first.id]
    item = body["results"][1]
    assert set(item) == {
        "id",
        "type",
        "title",
        "message",
        "data",
        "is_read",
        "read_at",
        "created_at",
    }
    assert item["title"] == "Demande refusée"
    assert item["message"] == (
        "Votre demande a été refusée : votre carte d'identité n'est pas lisible."
    )
    assert item["data"] == {"reason": "votre carte d'identité n'est pas lisible."}
    assert (item["is_read"], item["read_at"]) == (False, None)


def test_list_renders_texts_in_arabic(shop_client):
    _rejected(shop_client.user, reason="صورة غير واضحة")

    item = shop_client.get(LIST, HTTP_ACCEPT_LANGUAGE="ar").json()["results"][0]

    assert item["title"] != "Demande refusée"
    assert "صورة غير واضحة" in item["message"]
    assert "Votre demande" not in item["message"]


@pytest.mark.parametrize("value, expected", [("true", 1), ("false", 2)])
def test_list_filters_on_is_read(shop_client, value, expected):
    NotificationFactory(recipient=shop_client.user, is_read=True)
    NotificationFactory.create_batch(2, recipient=shop_client.user)

    response = shop_client.get(LIST, {"is_read": value})

    assert response.json()["count"] == expected
    assert {item["is_read"] for item in response.json()["results"]} == {value == "true"}


def test_list_rejects_invalid_is_read_filter(shop_client):
    response = shop_client.get(LIST, {"is_read": "peut-etre"})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "is_read" in response.json()["error"]["details"]


def test_list_query_count_is_constant(shop_client, django_assert_max_num_queries):
    NotificationFactory.create_batch(30, recipient=shop_client.user)

    with django_assert_max_num_queries(4):
        response = shop_client.get(LIST, {"page_size": 30})

    assert len(response.json()["results"]) == 30


def test_admin_reads_own_notifications(admin_client):
    NotificationFactory(
        recipient=admin_client.user,
        type=NotificationType.SHOP_SUBMITTED,
        data={"shop_id": 3, "shop_name": "Aïcha Mode"},
    )

    item = admin_client.get(LIST).json()["results"][0]

    assert item["message"] == "La boutique Aïcha Mode attend votre validation."


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 200, None),
        ("PENDING", 200, None),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
@pytest.mark.parametrize("url", [LIST, UNREAD])
def test_notifications_by_state(make_shop_client, url, state, expected_status, expected_code):
    response = make_shop_client(state).get(url)

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


@pytest.mark.parametrize("method, url", [("get", LIST), ("get", UNREAD), ("post", READ_ALL)])
def test_notifications_require_authentication(api_client, method, url):
    response = getattr(api_client, method)(url)

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"


# --- Compteur -------------------------------------------------------------------------
def test_unread_count_counts_only_own_unread(shop_client, other_shop_client):
    NotificationFactory.create_batch(3, recipient=shop_client.user)
    NotificationFactory(recipient=shop_client.user, is_read=True)
    NotificationFactory(recipient=other_shop_client.user)

    response = shop_client.get(UNREAD)

    assert response.status_code == 200
    assert response.json() == {"count": 3}


# --- Lecture --------------------------------------------------------------------------
def test_mark_read_sets_read_at_once(shop_client):
    notification = _rejected(shop_client.user)

    response = shop_client.post(_read_url(notification))

    assert response.status_code == 200
    body = response.json()
    assert body["is_read"] is True
    assert body["read_at"] is not None
    assert body["title"] == "Demande refusée"
    notification.refresh_from_db()
    first_read_at = notification.read_at

    assert shop_client.post(_read_url(notification)).status_code == 200
    notification.refresh_from_db()
    assert notification.read_at == first_read_at


def test_cannot_read_other_user_notification(shop_client, other_shop_client, admin_client):
    notification = NotificationFactory(recipient=other_shop_client.user)

    for client in (shop_client, admin_client):
        response = client.post(_read_url(notification))
        assert response.status_code == 404
        assert error_code(response) == "NOT_FOUND"
    notification.refresh_from_db()
    assert notification.is_read is False


def test_mark_read_blocked_shop_is_refused(make_shop_client):
    client = make_shop_client("BLOCKED")
    notification = NotificationFactory(recipient=client.user)

    response = client.post(_read_url(notification))

    assert response.status_code == 403
    assert error_code(response) == "SHOP_BLOCKED"


def test_read_all_marks_only_own_unread(shop_client, other_shop_client):
    NotificationFactory.create_batch(3, recipient=shop_client.user)
    already = NotificationFactory(recipient=shop_client.user, is_read=True)
    foreign = NotificationFactory(recipient=other_shop_client.user)

    response = shop_client.post(READ_ALL)

    assert response.status_code == 200
    assert response.json() == {"updated_count": 3}
    assert not Notification.objects.filter(recipient=shop_client.user, is_read=False).exists()
    unread_dates = Notification.objects.filter(recipient=shop_client.user, read_at__isnull=True)
    assert unread_dates.count() == 1
    already.refresh_from_db()
    assert already.read_at is None
    foreign.refresh_from_db()
    assert foreign.is_read is False
    assert shop_client.get(UNREAD).json() == {"count": 0}
