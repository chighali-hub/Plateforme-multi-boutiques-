import pytest
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.core.models import AuditLog, PlatformSettings

pytestmark = pytest.mark.django_db


def test_platform_settings_row_exists_with_documented_defaults():
    row = PlatformSettings.objects.get(pk=1)
    assert (row.trial_months, row.deposit_percent, row.admin_whatsapp) == (1, 30, "")


def test_platform_settings_load_uses_cache(django_assert_num_queries):
    PlatformSettings.load()
    with django_assert_num_queries(0):
        PlatformSettings.load()


def test_platform_settings_save_invalidates_cache():
    row = PlatformSettings.load()
    row.deposit_percent = 40
    row.save()
    assert PlatformSettings.load().deposit_percent == 40


def test_platform_settings_is_a_singleton():
    PlatformSettings(admin_whatsapp="22334455").save()
    assert PlatformSettings.objects.count() == 1
    assert PlatformSettings.objects.get().admin_whatsapp == "22334455"


def test_platform_settings_cannot_be_deleted():
    with pytest.raises(PermissionError):
        PlatformSettings.load().delete()


@pytest.mark.parametrize(
    "field, value",
    [("trial_months", 13), ("deposit_percent", 0), ("deposit_percent", 101)],
)
def test_platform_settings_ranges_are_enforced_by_database(field, value):
    PlatformSettings.load()
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformSettings.objects.filter(pk=1).update(**{field: value})


@pytest.mark.parametrize(
    "field, value", [("trial_months", 0), ("trial_months", 12), ("deposit_percent", 100)]
)
def test_platform_settings_range_bounds_are_accepted(field, value):
    PlatformSettings.load()
    assert PlatformSettings.objects.filter(pk=1).update(**{field: value}) == 1


def test_platform_settings_second_row_refused_by_database():
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformSettings.objects.bulk_create([PlatformSettings(id=2)])


def test_audit_log_rejects_unknown_action_in_database():
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.bulk_create([AuditLog(action="DROP_TABLE", target_type="x")])
    assert not AuditLog.objects.filter(Q(action="DROP_TABLE")).exists()
