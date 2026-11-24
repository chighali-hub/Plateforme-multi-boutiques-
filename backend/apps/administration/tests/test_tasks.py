"""Tache planifiee des rappels d'expiration (RG-25)."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.core import mail
from django.utils import timezone

from apps.administration.tasks import send_expiry_reminders
from apps.notifications.models import Notification, NotificationType

pytestmark = pytest.mark.django_db


def test_task_sends_reminders_once(make_shop, django_capture_on_commit_callbacks):
    shop = make_shop("ACTIVE", expires_at=timezone.now() + timedelta(days=2))

    with django_capture_on_commit_callbacks(execute=True):
        first = send_expiry_reminders.delay().get()
    second = send_expiry_reminders.delay().get()

    assert (first, second) == (1, 0)
    notification = Notification.objects.get(recipient=shop.owner)
    assert notification.type == NotificationType.EXPIRY_REMINDER
    assert notification.data["days_left"] == 2
    message = mail.outbox[-1]
    assert message.to == [shop.owner.email]
    assert shop.name in message.body and "2" in message.body


def test_task_is_scheduled_every_day_at_8():
    entry = settings.CELERY_BEAT_SCHEDULE["administration.send_expiry_reminders"]

    assert entry["task"] == send_expiry_reminders.name
    schedule = entry["schedule"]
    assert schedule.hour == {8} and schedule.minute == {0}
    assert settings.CELERY_TIMEZONE == "Africa/Nouakchott"
