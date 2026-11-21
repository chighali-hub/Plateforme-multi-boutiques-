from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.administration.tests.factories import RechargeFactory

pytestmark = pytest.mark.django_db


def test_recharge_must_extend_expiry():
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        RechargeFactory(previous_expires_at=now, new_expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        RechargeFactory(previous_expires_at=now, new_expires_at=now - timedelta(days=1))


@pytest.mark.parametrize("months", [0, 121])
def test_recharge_months_range(months):
    with pytest.raises(IntegrityError), transaction.atomic():
        RechargeFactory(duration_months=months)


@pytest.mark.parametrize("months", [None, 1, 120])
def test_recharge_months_bounds_accepted(months):
    assert RechargeFactory(duration_months=months).pk


def test_recharge_kept_when_admin_deleted():
    recharge = RechargeFactory()
    recharge.performed_by.delete()
    recharge.refresh_from_db()
    assert recharge.performed_by is None
