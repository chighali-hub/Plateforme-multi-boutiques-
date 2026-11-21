from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.shops.models import BankAccount, Shop, ThemeTemplate


class ThemeTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ThemeTemplate
        django_get_or_create = ("code",)

    code = "classique"
    name_fr = "Classique"
    name_ar = "كلاسيكي"
    layout = ThemeTemplate.Layout.GRID
    preview_image = "themes/classique.webp"
    default_primary_color = "#064E3B"
    default_accent_color = "#D4A52A"


class ShopFactory(factory.django.DjangoModelFactory):
    """Boutique dans l'etat voulu, via les traits : ShopFactory(active=True)."""

    class Meta:
        model = Shop

    owner = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Boutique {n}")
    logo = "shops/logos/2026/01/logo.webp"
    description_fr = "Melhfas, voiles et parfums"
    description_ar = "ملاحف و خمارات و عطور"
    address = "Tevragh Zeina, Nouakchott"
    phone = "36123456"
    whatsapp = "36123456"
    owner_full_name = "Proprietaire Test"
    id_card_front = "id_cards/2026/01/recto.jpg"
    id_card_back = "id_cards/2026/01/verso.jpg"
    onboarding_step = Shop.OnboardingStep.CHOOSE_DESIGN
    status = Shop.Status.PENDING

    class Params:
        onboarding = factory.Trait(onboarding_step=Shop.OnboardingStep.CHOOSE_DESIGN)
        pending = factory.Trait(
            onboarding_step=Shop.OnboardingStep.COMPLETED,
            theme=factory.SubFactory(ThemeTemplateFactory),
            primary_color="#064E3B",
            accent_color="#D4A52A",
            terms_accepted_at=factory.LazyFunction(timezone.now),
            submitted_at=factory.LazyFunction(timezone.now),
        )
        rejected = factory.Trait(
            pending=True,
            status=Shop.Status.REJECTED,
            rejection_reason="Carte d'identite illisible.",
            rejected_at=factory.LazyFunction(timezone.now),
        )
        active = factory.Trait(
            pending=True,
            status=Shop.Status.APPROVED,
            approved_at=factory.LazyFunction(timezone.now),
            expires_at=factory.LazyFunction(lambda: timezone.now() + timedelta(days=30)),
        )
        expired = factory.Trait(
            active=True,
            expires_at=factory.LazyFunction(lambda: timezone.now() - timedelta(days=1)),
        )
        blocked = factory.Trait(
            active=True,
            is_blocked=True,
            block_reason="Fraude signalee.",
            blocked_at=factory.LazyFunction(timezone.now),
        )


class BankAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BankAccount

    shop = factory.SubFactory(ShopFactory, active=True)
    bank_name = "Bankily"
    payment_code = factory.Sequence(lambda n: f"{22000000 + n}")
