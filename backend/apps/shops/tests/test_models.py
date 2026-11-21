from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError
from django.utils import timezone

from apps.shops.models import Shop, ShopState, ThemeTemplate, generate_unique_slug
from apps.shops.tests.factories import BankAccountFactory, ShopFactory

pytestmark = pytest.mark.django_db

STATES = ["ONBOARDING", "PENDING", "REJECTED", "ACTIVE", "EXPIRED", "BLOCKED"]


@pytest.mark.parametrize("state", STATES)
def test_state_property_matches_fixture_state(make_shop, state):
    assert make_shop(state).state == state


@pytest.mark.parametrize("state", STATES)
def test_with_state_annotation_matches_property(make_shop, state):
    shop = make_shop(state)
    annotated = Shop.objects.with_state().get(pk=shop.pk)
    assert annotated.computed_state == shop.state == state


def test_with_state_counts_in_database(make_shop):
    for state in STATES:
        make_shop(state)
    make_shop("ACTIVE")
    rows = Shop.objects.with_state().values("computed_state").annotate(n=Count("id"))
    counts = {row["computed_state"]: row["n"] for row in rows}
    assert counts == {
        "ONBOARDING": 1,
        "PENDING": 1,
        "REJECTED": 1,
        "ACTIVE": 2,
        "EXPIRED": 1,
        "BLOCKED": 1,
    }


@pytest.mark.parametrize(
    "overrides, expected",
    [
        # BLOCKED l'emporte sur tout, y compris EXPIRED et ONBOARDING.
        (
            {
                "is_blocked": True,
                "status": "APPROVED",
                "onboarding_step": "COMPLETED",
                "expires_at": "past",
            },
            "BLOCKED",
        ),
        ({"is_blocked": True, "onboarding_step": "VERIFY_EMAIL"}, "BLOCKED"),
        # ONBOARDING l'emporte sur le statut.
        ({"onboarding_step": "ACCEPT_TERMS", "status": "REJECTED"}, "ONBOARDING"),
        (
            {"onboarding_step": "VERIFY_EMAIL", "status": "APPROVED", "expires_at": "future"},
            "ONBOARDING",
        ),
    ],
)
def test_state_priority_order(overrides, expected):
    now = timezone.now()
    when = {"past": now - timedelta(days=1), "future": now + timedelta(days=1)}
    if "expires_at" in overrides:
        overrides["expires_at"] = when[overrides["expires_at"]]
    shop = ShopFactory(**overrides)
    assert shop.state == expected
    assert Shop.objects.with_state().get(pk=shop.pk).computed_state == expected


def test_shop_expires_to_the_second(make_shop):
    expires_at = datetime(2026, 12, 20, 10, 0, 0, tzinfo=UTC)
    shop = make_shop("ACTIVE", expires_at=expires_at)
    one_second = timedelta(seconds=1)

    assert shop.get_state(expires_at - one_second) == ShopState.ACTIVE
    assert shop.get_state(expires_at) == ShopState.EXPIRED
    assert shop.get_state(expires_at + one_second) == ShopState.EXPIRED

    queryset = Shop.objects.filter(pk=shop.pk)
    assert queryset.with_state(expires_at - one_second).get().computed_state == "ACTIVE"
    assert queryset.with_state(expires_at).get().computed_state == "EXPIRED"


def test_publicly_visible_requires_active_state_and_a_bank(make_shop):
    visible = make_shop("ACTIVE")
    BankAccountFactory(shop=visible)
    make_shop("ACTIVE")  # sans banque
    for state in ("ONBOARDING", "PENDING", "REJECTED", "EXPIRED", "BLOCKED"):
        BankAccountFactory(shop=make_shop(state))

    assert list(Shop.objects.publicly_visible()) == [visible]
    assert visible.is_publicly_visible()
    assert not Shop.objects.exclude(pk=visible.pk).first().is_publicly_visible()


def test_days_left_rounds_up_and_never_negative(make_shop):
    now = timezone.now()
    assert make_shop("ACTIVE", expires_at=now + timedelta(days=2, hours=1)).days_left(now) == 3
    assert make_shop("ACTIVE", expires_at=now + timedelta(days=2)).days_left(now) == 2
    assert make_shop("EXPIRED").days_left(now) == 0
    assert make_shop("PENDING").days_left(now) == 0


def test_slug_generated_from_name_and_made_unique():
    first = ShopFactory(name="Aïcha Mode")
    second = ShopFactory(name="Aicha mode")
    third = ShopFactory(name="AICHA MODE")
    assert (first.slug, second.slug, third.slug) == ("aicha-mode", "aicha-mode-2", "aicha-mode-3")


def test_slug_falls_back_for_arabic_name():
    assert ShopFactory(name="متجر عائشة").slug == "boutique"
    assert ShopFactory(name="متجر").slug == "boutique-2"


def test_slug_does_not_change_when_name_changes():
    shop = ShopFactory(name="Premier Nom")
    shop.name = "Nouveau Nom"
    shop.save()
    shop.refresh_from_db()
    assert shop.slug == "premier-nom"


def test_generate_unique_slug_ignores_prefix_collisions():
    ShopFactory(name="Mode")
    ShopFactory(name="Mode Plus")
    assert generate_unique_slug("Mode") == "mode-2"


def test_search_fields_follow_name_and_descriptions():
    shop = ShopFactory(name="Aïcha Mode", description_fr="Téléphones", description_ar="مَلْحَفَة")
    assert shop.search_name == "aicha mode"
    assert shop.search_text_fr == "aicha mode telefones"
    assert shop.search_text_ar == "aicha mode ملحفه"


def test_search_fields_saved_with_partial_update():
    shop = ShopFactory(name="Ancien")
    shop.name = "Nouveau"
    shop.save(update_fields=["name"])
    shop.refresh_from_db()
    assert shop.search_name == "nouveau"


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "ARCHIVED"),
        ("onboarding_step", "UNKNOWN"),
        ("last_expiry_reminder_days", 5),
        ("phone", "1234"),
        ("whatsapp", "56123456"),
        ("primary_color", "#zzzzzz"),
    ],
)
def test_shop_constraints_reject_invalid_values(make_shop, field, value):
    shop = make_shop("PENDING")
    with pytest.raises(IntegrityError), transaction.atomic():
        Shop.objects.filter(pk=shop.pk).update(**{field: value})


def test_approved_shop_requires_expiry_date(make_shop):
    shop = make_shop("PENDING")
    with pytest.raises(IntegrityError), transaction.atomic():
        Shop.objects.filter(pk=shop.pk).update(status="APPROVED", expires_at=None)


def test_one_shop_per_owner(make_shop):
    shop = make_shop("ACTIVE")
    with pytest.raises(IntegrityError), transaction.atomic():
        ShopFactory(owner=shop.owner)


def test_bank_account_unique_per_shop(make_shop):
    shop = make_shop("ACTIVE")
    BankAccountFactory(shop=shop, bank_name="Bankily", payment_code="22334455")
    BankAccountFactory(bank_name="Bankily", payment_code="22334455")  # autre boutique : permis
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccountFactory(shop=shop, bank_name="Bankily", payment_code="22334455")


def test_six_themes_created_by_migration_with_preview_files():
    themes = list(ThemeTemplate.objects.order_by("sort_order"))
    assert [theme.code for theme in themes] == [
        "classique",
        "elegant",
        "moderne",
        "minimal",
        "magazine",
        "tradition",
    ]
    assert all(theme.is_active and theme.name_ar for theme in themes)
    assert {theme.preview_image.name for theme in themes} == {
        f"themes/{theme.code}.webp" for theme in themes
    }


def test_theme_in_use_cannot_be_deleted(make_shop):
    shop = make_shop("PENDING")
    with pytest.raises(ProtectedError):
        shop.theme.delete()
