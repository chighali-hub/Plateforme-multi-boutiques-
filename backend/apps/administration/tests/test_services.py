"""Regles metier de l'administration, sans HTTP (RG-10 a RG-25)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.administration import services
from apps.administration.models import Recharge
from apps.catalog.tests.factories import ProductFactory
from apps.core.exceptions import InvalidStateTransition
from apps.core.models import AuditAction, AuditLog, PlatformSettings
from apps.notifications.models import Notification, NotificationType

pytestmark = pytest.mark.django_db
NOUAKCHOTT = ZoneInfo("Africa/Nouakchott")


# --- Calcul de recharge (RG-20 a RG-23) ---------------------------------------------
def test_recharge_of_active_shop_adds_to_current_expiry(make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 10, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=10))

    result = services.compute_new_expiry(shop, duration_months=12)

    assert result.base_date == shop.expires_at
    assert result.new_expires_at == datetime(2027, 11, 30, 10, 0, tzinfo=NOUAKCHOTT)
    assert result.is_currently_expired is False


def test_recharge_of_expired_shop_starts_from_today(make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 10, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("EXPIRED", expires_at=now - timedelta(days=40))

    result = services.compute_new_expiry(shop, duration_months=1)

    assert result.base_date == now
    assert result.new_expires_at == datetime(2026, 12, 20, 10, 0, tzinfo=NOUAKCHOTT)
    assert result.is_currently_expired is True


def test_recharge_of_january_31_plus_one_month_gives_end_of_february(make_shop, freeze_now):
    freeze_now(datetime(2027, 1, 10, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE", expires_at=datetime(2027, 1, 31, 12, 0, tzinfo=NOUAKCHOTT))

    result = services.compute_new_expiry(shop, duration_months=1)

    assert result.new_expires_at == datetime(2027, 2, 28, 12, 0, tzinfo=NOUAKCHOTT)


def test_recharge_example_five_years(make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("EXPIRED", expires_at=now - timedelta(days=1))

    result = services.compute_new_expiry(shop, duration_months=60)

    assert result.new_expires_at.date() == date(2031, 11, 20)


def test_recharge_target_date_ends_at_local_midnight(make_shop, freeze_now):
    freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE")

    result = services.compute_new_expiry(shop, target_date=date(2031, 11, 20))

    assert result.new_expires_at == datetime(2031, 11, 20, 23, 59, 59, tzinfo=NOUAKCHOTT)


@pytest.mark.parametrize("days_before_expiry", [0, 5])
def test_recharge_target_date_not_after_base_is_refused(make_shop, freeze_now, days_before_expiry):
    now = freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=10))
    target = (shop.expires_at - timedelta(days=days_before_expiry)).date()

    with pytest.raises(ValidationError) as error:
        services.compute_new_expiry(shop, target_date=target)

    assert "target_date" in error.value.detail


def test_recharge_target_date_day_after_expiry_is_accepted(make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=10))

    result = services.compute_new_expiry(shop, target_date=date(2026, 12, 1))

    assert result.new_expires_at == datetime(2026, 12, 1, 23, 59, 59, tzinfo=NOUAKCHOTT)


def test_recharge_target_date_in_the_past_for_expired_shop_is_refused(make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("EXPIRED", expires_at=now - timedelta(days=30))

    with pytest.raises(ValidationError):
        services.compute_new_expiry(shop, target_date=(now - timedelta(days=1)).date())


@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED"])
def test_recharge_of_not_approved_shop_is_refused(make_shop, state):
    with pytest.raises(InvalidStateTransition):
        services.compute_new_expiry(make_shop(state), duration_months=1)


def test_recharge_of_blocked_approved_shop_is_allowed(make_shop):
    result = services.compute_new_expiry(make_shop("BLOCKED"), duration_months=1)
    assert result.new_expires_at > result.current_expires_at


@pytest.mark.parametrize("kwargs", [{}, {"duration_months": 1, "target_date": date(2031, 1, 1)}])
def test_compute_new_expiry_needs_exactly_one_mode(make_shop, kwargs):
    with pytest.raises(ValueError):
        services.compute_new_expiry(make_shop("ACTIVE"), **kwargs)


def test_recharge_shop_records_history_and_resets_reminders(make_shop, admin_user, run_on_commit):
    shop = make_shop("ACTIVE", last_expiry_reminder_days=3)
    previous = shop.expires_at

    recharge = run_on_commit(
        services.recharge_shop,
        shop,
        admin=admin_user,
        duration_months=3,
        amount_received=9000,
        note="Bankily",
    )

    shop.refresh_from_db()
    assert shop.expires_at == recharge.new_expires_at > previous
    assert shop.last_expiry_reminder_days is None
    assert (recharge.previous_expires_at, recharge.performed_by) == (previous, admin_user)
    assert (recharge.amount_received, recharge.note, recharge.duration_months) == (
        9000,
        "Bankily",
        3,
    )
    assert Notification.objects.filter(
        recipient=shop.owner, type=NotificationType.SHOP_RECHARGED
    ).exists()
    entry = AuditLog.objects.get(action=AuditAction.SHOP_RECHARGED)
    assert entry.metadata["recharge_id"] == recharge.pk
    assert mail.outbox[-1].to == [shop.owner.email]


def test_recharge_shop_failure_changes_nothing(make_shop, admin_user):
    shop = make_shop("PENDING")

    with pytest.raises(InvalidStateTransition):
        services.recharge_shop(shop, admin=admin_user, duration_months=1)

    assert not Recharge.objects.exists()
    assert not AuditLog.objects.filter(action=AuditAction.SHOP_RECHARGED).exists()


# --- Validation (RG-11) -------------------------------------------------------------
def test_approve_uses_trial_months_setting(make_shop, admin_user, freeze_now):
    now = freeze_now(datetime(2027, 1, 31, 8, 0, tzinfo=NOUAKCHOTT))
    platform = PlatformSettings.load()
    platform.trial_months = 3
    platform.save()

    shop = services.approve_shop(make_shop("PENDING"), admin=admin_user)

    assert shop.approved_at == now
    assert shop.expires_at == datetime(2027, 4, 30, 8, 0, tzinfo=NOUAKCHOTT)


def test_approve_clears_previous_rejection_reason(make_shop, admin_user):
    shop = make_shop("PENDING", rejection_reason="Carte illisible.")

    shop = services.approve_shop(shop, admin=admin_user)

    assert shop.rejection_reason == ""


# --- Parametres ---------------------------------------------------------------------
def test_update_settings_records_old_and_new_values(admin_user):
    platform = services.update_platform_settings(
        admin=admin_user, fields={"deposit_percent": 40, "trial_months": 1}
    )

    assert platform.deposit_percent == 40 and platform.updated_by == admin_user
    entry = AuditLog.objects.get(action=AuditAction.SETTINGS_UPDATED)
    assert entry.target_type == "platform_settings"
    assert entry.metadata["changes"] == {"deposit_percent": {"old": 30, "new": 40}}
    assert PlatformSettings.load().deposit_percent == 40


def test_update_settings_without_change_writes_nothing(admin_user):
    services.update_platform_settings(admin=admin_user, fields={"deposit_percent": 30})

    assert not AuditLog.objects.filter(action=AuditAction.SETTINGS_UPDATED).exists()
    assert PlatformSettings.load().updated_by is None


def test_update_settings_rejects_unknown_field(admin_user):
    with pytest.raises(ValueError):
        services.update_platform_settings(admin=admin_user, fields={"secret": 1})


# --- Moderation ---------------------------------------------------------------------
def test_remove_product_deletes_files_after_commit(
    make_shop, admin_user, image_file, run_on_commit
):
    product = ProductFactory(shop=make_shop("ACTIVE"))
    product.image.save("image.jpg", image_file(), save=False)
    product.thumbnail.save("thumb.jpg", image_file(), save=True)
    storage, image_name, thumb_name = (
        product.image.storage,
        product.image.name,
        product.thumbnail.name,
    )

    run_on_commit(services.remove_product, product, admin=admin_user, reason="Contrefacon.")

    assert not storage.exists(image_name)
    assert not storage.exists(thumb_name)


# --- Rappels d'expiration (RG-25) ---------------------------------------------------
@pytest.mark.parametrize(
    "days_left, threshold",
    [(10, None), (8, None), (7, 7), (5, 7), (4, 7), (3, 3), (2, 3), (1, 1)],
)
def test_reminder_threshold(days_left, threshold):
    assert services.reminder_threshold(days_left) == threshold


def _reminders(shop):
    return Notification.objects.filter(recipient=shop.owner, type=NotificationType.EXPIRY_REMINDER)


def test_expiry_reminders_sent_at_7_3_and_1_days_once_each(make_shop, run_on_commit):
    start = timezone.now()
    shop = make_shop("ACTIVE", expires_at=start + timedelta(days=7, hours=2))

    sent = []
    for day in range(10):
        moment = start + timedelta(days=day)
        sent.append(run_on_commit(services.send_expiry_reminders, now=moment))
        # Deux passages le meme jour : jamais de doublon.
        assert services.send_expiry_reminders(now=moment + timedelta(hours=1)) == 0

    # Jours restants : 8, 7 (rappel), 6, 5, 4, 3 (rappel), 2, 1 (rappel), expiree, expiree.
    assert sent == [0, 1, 0, 0, 0, 1, 0, 1, 0, 0]
    shop.refresh_from_db()
    assert shop.last_expiry_reminder_days == 1
    days = sorted(n.data["days_left"] for n in _reminders(shop))
    assert len(days) == 3
    assert [services.reminder_threshold(d) for d in days] == [1, 3, 7]
    assert len([m for m in mail.outbox if m.to == [shop.owner.email]]) == 3


def test_expiry_reminders_follow_the_calendar(make_shop):
    now = timezone.now()
    seven = make_shop("ACTIVE", expires_at=now + timedelta(days=6, hours=20))
    three = make_shop("ACTIVE", expires_at=now + timedelta(days=2, hours=5))
    one = make_shop("ACTIVE", expires_at=now + timedelta(hours=5))
    far = make_shop("ACTIVE", expires_at=now + timedelta(days=20))

    assert services.send_expiry_reminders(now=now) == 3

    for shop, expected in ((seven, 7), (three, 3), (one, 1), (far, None)):
        shop.refresh_from_db()
        assert shop.last_expiry_reminder_days == expected


def test_missed_run_sends_only_the_current_threshold(make_shop):
    now = timezone.now()
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=2), last_expiry_reminder_days=None)

    assert services.send_expiry_reminders(now=now) == 1

    assert [n.data["days_left"] for n in _reminders(shop)] == [2]
    shop.refresh_from_db()
    assert shop.last_expiry_reminder_days == 3


def test_expiry_reminders_skip_blocked_and_expired_shops(make_shop):
    now = timezone.now()
    make_shop("BLOCKED", expires_at=now + timedelta(days=2))
    make_shop("EXPIRED")

    assert services.send_expiry_reminders(now=now) == 0
    assert not Notification.objects.filter(type=NotificationType.EXPIRY_REMINDER).exists()


def test_expiry_reminders_start_again_after_recharge(make_shop, admin_user):
    now = timezone.now()
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=1))
    assert services.send_expiry_reminders(now=now) == 1

    services.recharge_shop(shop, admin=admin_user, duration_months=1)
    shop.refresh_from_db()
    later = shop.expires_at - timedelta(days=6, hours=12)

    assert services.send_expiry_reminders(now=later) == 1
    shop.refresh_from_db()
    assert shop.last_expiry_reminder_days == 7
    assert _reminders(shop).count() == 2
