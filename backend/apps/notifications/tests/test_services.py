import pytest

from apps.accounts.tests.factories import AdminUserFactory, UserFactory
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import REQUIRED_DATA, notify, notify_admins, render
from apps.notifications.tests.factories import NotificationFactory

pytestmark = pytest.mark.django_db

SAMPLE_DATA = {
    "SHOP_SUBMITTED": {"shop_id": 3, "shop_name": "Aicha Mode"},
    "SHOP_RESUBMITTED": {"shop_id": 3, "shop_name": "Aicha Mode"},
    "SHOP_APPROVED": {"expires_at": "2026-12-20T10:00:00+00:00"},
    "SHOP_REJECTED": {"reason": "carte illisible"},
    "SHOP_UNBLOCKED": {},
    "SHOP_RECHARGED": {
        "previous_expires_at": "2026-12-20T10:00:00+00:00",
        "new_expires_at": "2027-01-20T10:00:00+00:00",
    },
    "EXPIRY_REMINDER": {"expires_at": "2026-12-20T10:00:00+00:00", "days_left": 3},
    "ORDER_NEW": {
        "order_id": 42,
        "reference": "CMD-2026-000042",
        "total_amount": 6000,
        "customer_name": "Mariem",
    },
    "IMPORT_COMPLETED": {"job_id": 1, "success_count": 98, "error_count": 2},
    "IMPORT_FAILED": {"job_id": 1, "failure_reason": "fichier illisible"},
    "PRODUCT_REMOVED": {"product_name": "Melhfa", "reason": "contenu interdit"},
}


def test_every_type_has_a_payload_contract():
    assert set(REQUIRED_DATA) == set(NotificationType.values) == set(SAMPLE_DATA)


def test_notify_creates_unread_notification():
    user = UserFactory()
    notification = notify(user, NotificationType.SHOP_REJECTED, {"reason": "illisible"})
    assert notification.recipient == user
    assert notification.is_read is False
    assert notification.data == {"reason": "illisible"}


def test_notify_rejects_incomplete_payload():
    with pytest.raises(ValueError):
        notify(UserFactory(), NotificationType.ORDER_NEW, {"order_id": 1})
    assert not Notification.objects.exists()


def test_notify_rejects_unknown_type():
    with pytest.raises(ValueError):
        notify(UserFactory(), "SHOP_DELETED", {})


def test_notify_serializes_datetimes(make_shop):
    shop = make_shop("ACTIVE")
    notification = notify(
        shop.owner, NotificationType.SHOP_APPROVED, {"expires_at": shop.expires_at}
    )
    notification.refresh_from_db()
    assert notification.data == {"expires_at": shop.expires_at.isoformat()}


def test_notify_admins_targets_active_admins_only():
    first, second = AdminUserFactory(), AdminUserFactory()
    AdminUserFactory(is_active=False)
    UserFactory()

    created = notify_admins(NotificationType.SHOP_SUBMITTED, SAMPLE_DATA["SHOP_SUBMITTED"])

    assert {n.recipient_id for n in created} == {first.id, second.id}
    assert Notification.objects.count() == 2


@pytest.mark.parametrize("notification_type", list(SAMPLE_DATA))
@pytest.mark.parametrize("language", ["fr", "ar"])
def test_render_produces_text_for_every_type(notification_type, language):
    notification = NotificationFactory(type=notification_type, data=SAMPLE_DATA[notification_type])
    title, message = render(notification, language)
    assert title and message
    assert "%(" not in title + message


def test_render_french_examples():
    rejected = NotificationFactory(type="SHOP_REJECTED", data={"reason": "carte illisible"})
    assert render(rejected, "fr") == (
        "Demande refusée",
        "Votre demande a été refusée : carte illisible",
    )
    reminder = NotificationFactory(type="EXPIRY_REMINDER", data=SAMPLE_DATA["EXPIRY_REMINDER"])
    assert render(reminder, "fr")[1] == "Votre compte expire dans 3 jours, le 20/12/2026."


def test_render_singular_day():
    reminder = NotificationFactory(
        type="EXPIRY_REMINDER", data={"expires_at": "2026-12-20T10:00:00+00:00", "days_left": 1}
    )
    assert render(reminder, "fr")[1] == "Votre compte expire dans 1 jour, le 20/12/2026."


def test_render_arabic_differs_from_french():
    notification = NotificationFactory(type="SHOP_REJECTED", data={"reason": "x"})
    assert render(notification, "ar") != render(notification, "fr")


def test_render_tolerates_missing_keys_in_stored_data():
    notification = NotificationFactory(type="SHOP_REJECTED", data={})
    assert render(notification, "fr")[1] == "Votre demande a été refusée : "
