"""Services de l'espace boutique, sans HTTP (cas limites et concurrence)."""

from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import InvalidStateTransition, OnboardingStepMismatch
from apps.shops import services
from apps.shops.models import BankAccount, Shop, ThemeTemplate

pytestmark = pytest.mark.django_db


def test_resubmit_refuses_shop_that_is_no_longer_rejected(make_shop):
    """La demande a ete renvoyee entre le controle de la vue et le verrou."""
    stale = make_shop("REJECTED")
    Shop.objects.filter(pk=stale.pk).update(status=Shop.Status.PENDING)

    with pytest.raises(InvalidStateTransition) as error:
        services.resubmit_shop(stale)

    assert error.value.details == {"current_state": "PENDING"}


def test_accept_terms_rechecks_step_under_lock(make_shop):
    stale = make_shop("ONBOARDING", onboarding_step=Shop.OnboardingStep.ACCEPT_TERMS)
    Shop.objects.filter(pk=stale.pk).update(onboarding_step=Shop.OnboardingStep.COMPLETED)

    with pytest.raises(OnboardingStepMismatch):
        services.accept_terms(stale)


def test_update_profile_refuses_unknown_field(make_shop):
    with pytest.raises(ValueError):
        services.update_profile(make_shop("ACTIVE"), fields={"status": "APPROVED"})


def test_update_profile_without_changes_does_not_save(make_shop):
    shop = make_shop("ACTIVE")
    updated_at = shop.updated_at

    services.update_profile(shop, fields={})

    shop.refresh_from_db()
    assert shop.updated_at == updated_at


def test_replace_id_card_requires_a_side(make_shop):
    with pytest.raises(ValueError):
        services.replace_id_card(make_shop("REJECTED"))


def test_replace_id_card_back_only(make_shop):
    shop = make_shop("REJECTED")
    front = shop.id_card_front.name

    shop = services.replace_id_card(shop, back=ContentFile(b"verso", name="verso.jpg"))

    assert shop.id_card_front.name == front
    assert shop.id_card_back.name.startswith("id_cards/")


def test_update_design_keeps_onboarding_completed(make_shop):
    shop = make_shop("ACTIVE")
    theme = ThemeTemplate.objects.get(code="tradition")

    shop = services.update_design(shop, theme=theme, accent_color="#0E7490")

    assert (shop.theme, shop.accent_color) == (theme, "#0E7490")
    assert shop.primary_color == theme.default_primary_color


def test_concurrent_duplicate_bank_becomes_validation_error(make_shop):
    shop = make_shop("ACTIVE")

    with mock.patch.object(BankAccount, "save", side_effect=IntegrityError("doublon")):
        with pytest.raises(ValidationError) as error:
            services.create_bank_account(shop, bank_name="Sedad", payment_code="44556677")

    assert "non_field_errors" in error.value.detail
    assert not BankAccount.objects.filter(shop=shop).exists()
