"""Espace boutique : onboarding, profil, carte d'identite, banques.

Voir 03-reference-api.md section 5 et 01-vue-d-ensemble.md (RG-05, RG-13).
Les services ecrivent et appliquent les regles ; les vues ne font qu'appeler.
"""

import logging
from typing import Any

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.core.audit import log_action
from apps.core.exceptions import InvalidStateTransition, LimitReached, OnboardingStepMismatch
from apps.core.models import AuditAction
from apps.core.storage import delete_file_on_commit
from apps.notifications.models import NotificationType
from apps.notifications.services import notify_admins

from .models import BankAccount, Shop, ShopState, ThemeTemplate

logger = logging.getLogger(__name__)

MAX_BANK_ACCOUNTS = 10
DESIGN_STEPS = frozenset({Shop.OnboardingStep.CHOOSE_DESIGN, Shop.OnboardingStep.ACCEPT_TERMS})
PROFILE_FIELDS = frozenset(
    {
        "name",
        "description_fr",
        "description_ar",
        "address",
        "phone",
        "whatsapp",
        "owner_full_name",
    }
)
BANK_DUPLICATE = _("Cette banque avec ce code de paiement est déjà enregistrée.")


def _lock(shop: Shop) -> Shop:
    """Relit la boutique sous verrou de ligne (a appeler dans une transaction).

    Seule la ligne de la boutique est verrouillee (`of=("self",)`) : PostgreSQL
    refuse FOR UPDATE sur le cote nullable d'une jointure (theme facultatif).
    """
    return (
        Shop.objects.select_for_update(of=("self",))
        .select_related("theme", "owner")
        .get(pk=shop.pk)
    )


def _apply_design(
    shop: Shop, theme: ThemeTemplate, primary_color: str | None, accent_color: str | None
) -> None:
    """Modele + couleurs ; une couleur absente reprend celle du modele."""
    shop.theme = theme
    shop.primary_color = primary_color or theme.default_primary_color
    shop.accent_color = accent_color or theme.default_accent_color


# --- Onboarding (RG-05) ---------------------------------------------------------
def choose_design(
    shop: Shop,
    *,
    theme: ThemeTemplate,
    primary_color: str | None = None,
    accent_color: str | None = None,
) -> Shop:
    """Enregistre le design choisi pendant l'inscription et passe a ACCEPT_TERMS.

    Peut etre rappele depuis ACCEPT_TERMS (retour en arriere).
    Leve OnboardingStepMismatch (409) depuis toute autre etape.
    """
    with transaction.atomic():
        shop = _lock(shop)
        if shop.onboarding_step not in DESIGN_STEPS:
            raise OnboardingStepMismatch(details={"onboarding_step": shop.onboarding_step})
        _apply_design(shop, theme, primary_color, accent_color)
        shop.onboarding_step = Shop.OnboardingStep.ACCEPT_TERMS
        shop.save(
            update_fields=[
                "theme",
                "primary_color",
                "accent_color",
                "onboarding_step",
                "updated_at",
            ]
        )
    return shop


def accept_terms(shop: Shop, *, request=None) -> Shop:
    """« J'accepte » : la demande est soumise a l'administrateur (RG-05).

    Effets : terms_accepted_at et submitted_at = maintenant, etape COMPLETED
    (l'etat devient PENDING), notification SHOP_SUBMITTED a tous les admins,
    audit SHOP_SUBMITTED. Leve OnboardingStepMismatch (409) hors de ACCEPT_TERMS.
    """
    with transaction.atomic():
        shop = _lock(shop)
        if shop.onboarding_step != Shop.OnboardingStep.ACCEPT_TERMS:
            raise OnboardingStepMismatch(details={"onboarding_step": shop.onboarding_step})
        now = timezone.now()
        shop.terms_accepted_at = now
        shop.submitted_at = now
        shop.onboarding_step = Shop.OnboardingStep.COMPLETED
        shop.save(
            update_fields=["terms_accepted_at", "submitted_at", "onboarding_step", "updated_at"]
        )
        notify_admins(NotificationType.SHOP_SUBMITTED, {"shop_id": shop.pk, "shop_name": shop.name})
        log_action(shop.owner, AuditAction.SHOP_SUBMITTED, target=shop, request=request)
    logger.info("Boutique %s soumise a la validation", shop.pk)
    return shop


# --- Profil -----------------------------------------------------------------------
def update_profile(shop: Shop, *, fields: dict[str, Any], logo: ContentFile | None = None) -> Shop:
    """Modifie le profil. Le slug ne change jamais (liens partages).

    Un nouveau logo remplace l'ancien, supprime apres la validation de la
    transaction. Les colonnes de recherche sont recalculees par Shop.save().
    """
    unknown = set(fields) - PROFILE_FIELDS
    if unknown:
        raise ValueError(f"Champs de profil inconnus : {sorted(unknown)}")
    with transaction.atomic():
        shop = _lock(shop)
        for name, value in fields.items():
            setattr(shop, name, value)
        update_fields = set(fields)
        if logo is not None:
            delete_file_on_commit(shop.logo)
            shop.logo.save(logo.name, logo, save=False)
            update_fields.add("logo")
        if update_fields:
            shop.save(update_fields=[*update_fields, "updated_at"])
    return shop


def update_design(
    shop: Shop,
    *,
    theme: ThemeTemplate,
    primary_color: str | None = None,
    accent_color: str | None = None,
) -> Shop:
    """Change le design depuis l'onglet Parametres (memes regles que l'onboarding)."""
    with transaction.atomic():
        shop = _lock(shop)
        _apply_design(shop, theme, primary_color, accent_color)
        shop.save(update_fields=["theme", "primary_color", "accent_color", "updated_at"])
    return shop


def replace_id_card(
    shop: Shop, *, front: ContentFile | None = None, back: ContentFile | None = None
) -> Shop:
    """Remplace le recto et/ou le verso de la carte d'identite (boutique refusee, RG-13).

    Les anciens fichiers prives sont supprimes apres la validation de la transaction.
    """
    if front is None and back is None:
        raise ValueError("Au moins une face de la carte d'identite est attendue.")
    with transaction.atomic():
        shop = _lock(shop)
        update_fields = ["updated_at"]
        for field_name, content in (("id_card_front", front), ("id_card_back", back)):
            if content is None:
                continue
            field_file = getattr(shop, field_name)
            delete_file_on_commit(field_file)
            field_file.save(content.name, content, save=False)
            update_fields.append(field_name)
        shop.save(update_fields=update_fields)
    return shop


def resubmit_shop(shop: Shop, *, request=None) -> Shop:
    """« Renvoyer la demande de validation » (RG-13).

    La boutique refusee repasse a PENDING (submitted_at = maintenant). Le motif
    du refus est conserve sur la boutique jusqu'a la prochaine decision et
    recopie dans l'audit SHOP_RESUBMITTED ; les admins sont notifies.
    Leve InvalidStateTransition (409) si la boutique n'est plus refusee.
    """
    with transaction.atomic():
        shop = _lock(shop)
        state = shop.get_state()
        if state != ShopState.REJECTED:
            raise InvalidStateTransition(details={"current_state": state})
        shop.status = Shop.Status.PENDING
        shop.submitted_at = timezone.now()
        shop.save(update_fields=["status", "submitted_at", "updated_at"])
        notify_admins(
            NotificationType.SHOP_RESUBMITTED, {"shop_id": shop.pk, "shop_name": shop.name}
        )
        log_action(
            shop.owner,
            AuditAction.SHOP_RESUBMITTED,
            target=shop,
            metadata={"previous_rejection_reason": shop.rejection_reason},
            request=request,
        )
    logger.info("Boutique %s soumise a nouveau", shop.pk)
    return shop


# --- Banques ----------------------------------------------------------------------
def _ensure_bank_is_unique(
    shop: Shop, bank_name: str, payment_code: str, exclude_pk: int | None = None
) -> None:
    duplicates = BankAccount.objects.filter(
        shop=shop, bank_name__iexact=bank_name, payment_code=payment_code
    )
    if exclude_pk is not None:
        duplicates = duplicates.exclude(pk=exclude_pk)
    if duplicates.exists():
        raise ValidationError({"non_field_errors": [BANK_DUPLICATE]})


def _save_bank(bank: BankAccount) -> BankAccount:
    """Enregistre ; un doublon concurrent (contrainte UNIQUE) devient une erreur 400."""
    try:
        with transaction.atomic():
            bank.save()
    except IntegrityError:
        raise ValidationError({"non_field_errors": [BANK_DUPLICATE]}) from None
    return bank


def create_bank_account(shop: Shop, *, bank_name: str, payment_code: str) -> BankAccount:
    """Ajoute un moyen de paiement. Couple (banque, code) unique, 10 au maximum.

    Leve LimitReached (409) au-dela de 10 banques, ValidationError (400) pour un doublon.
    """
    with transaction.atomic():
        shop = _lock(shop)
        if BankAccount.objects.filter(shop=shop).count() >= MAX_BANK_ACCOUNTS:
            raise LimitReached(details={"limit": MAX_BANK_ACCOUNTS})
        _ensure_bank_is_unique(shop, bank_name, payment_code)
        return _save_bank(BankAccount(shop=shop, bank_name=bank_name, payment_code=payment_code))


def update_bank_account(bank: BankAccount, *, fields: dict[str, str]) -> BankAccount:
    """Modifie le nom de la banque et/ou le code de paiement."""
    with transaction.atomic():
        bank = BankAccount.objects.select_for_update().get(pk=bank.pk)
        for name, value in fields.items():
            setattr(bank, name, value)
        _ensure_bank_is_unique(bank.shop, bank.bank_name, bank.payment_code, exclude_pk=bank.pk)
        return _save_bank(bank)


def delete_bank_account(bank: BankAccount) -> None:
    """Supprime une banque. Sans banque, la boutique n'est plus visible (RG-40)."""
    bank.delete()
