"""Administration des boutiques : decisions, blocage, recharge, parametres, moderation.

Voir 03-reference-api.md section 11 et 01-vue-d-ensemble.md (RG-10 a RG-25).
Les services ecrivent et appliquent les regles ; les vues ne font qu'appeler.
Les notifications et l'audit sont ecrits dans la transaction du service (ils
disparaissent avec elle) ; les e-mails partent apres sa validation.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.tokens import revoke_all_sessions
from apps.catalog.models import Product
from apps.core.audit import log_action
from apps.core.emails import send_templated_email
from apps.core.exceptions import InvalidStateTransition
from apps.core.models import AuditAction, PlatformSettings
from apps.core.storage import delete_file_on_commit
from apps.notifications.models import NotificationType
from apps.notifications.services import notify
from apps.shops.models import EXPIRY_REMINDER_DAYS, Shop, ShopState

from .models import Recharge

logger = logging.getLogger(__name__)

TARGET_DATE_TOO_EARLY = _(
    "La date cible doit être postérieure à la date d'expiration actuelle et à aujourd'hui."
)
SETTINGS_FIELDS = ("admin_whatsapp", "admin_contact_email", "trial_months", "deposit_percent")
EXPIRY_REMINDER_WINDOW = timedelta(days=max(EXPIRY_REMINDER_DAYS))


def _local_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIME_ZONE)


def format_local_date(moment: datetime | None) -> str:
    """Date JJ/MM/AAAA dans le fuseau metier (Africa/Nouakchott)."""
    if moment is None:
        return ""
    return moment.astimezone(_local_tz()).strftime("%d/%m/%Y")


def _lock(shop: Shop) -> Shop:
    """Relit la boutique sous verrou de ligne (a appeler dans une transaction).

    Seule la ligne de la boutique est verrouillee : PostgreSQL refuse FOR UPDATE
    sur le cote nullable d'une jointure (theme facultatif).
    """
    return (
        Shop.objects.select_for_update(of=("self",))
        .select_related("theme", "owner")
        .get(pk=shop.pk)
    )


def _email_shop_on_commit(shop: Shop, template: str, context: dict[str, Any]) -> None:
    """E-mail a la boutique apres la validation de la transaction.

    Declenche par l'administrateur : le message est en francais et en arabe.
    """
    to = shop.owner.email
    payload = {"shop_name": shop.name, **context}
    transaction.on_commit(lambda: send_templated_email.delay(to, template, payload, None))


def _ensure_state(shop: Shop, *allowed: str) -> str:
    state = shop.get_state()
    if state not in allowed:
        raise InvalidStateTransition(details={"current_state": state})
    return state


# --- Validation et refus (RG-10 a RG-12) ------------------------------------------
def approve_shop(shop: Shop, *, admin: User, request=None) -> Shop:
    """Valide une boutique en attente (RG-10, RG-11).

    Effets : statut APPROVED, approved_at et approved_by, expiration = maintenant
    + duree d'essai (`trial_months`), motif de refus efface, notification
    SHOP_APPROVED + e-mail, audit SHOP_APPROVED.
    Leve InvalidStateTransition (409) si la boutique n'est pas PENDING.
    """
    with transaction.atomic():
        shop = _lock(shop)
        _ensure_state(shop, ShopState.PENDING)
        trial_months = PlatformSettings.load().trial_months
        now = timezone.now()
        shop.status = Shop.Status.APPROVED
        shop.approved_at = now
        shop.approved_by = admin
        shop.expires_at = now + relativedelta(months=trial_months)
        shop.rejection_reason = ""
        shop.last_expiry_reminder_days = None
        shop.save(
            update_fields=[
                "status",
                "approved_at",
                "approved_by",
                "expires_at",
                "rejection_reason",
                "last_expiry_reminder_days",
                "updated_at",
            ]
        )
        notify(shop.owner, NotificationType.SHOP_APPROVED, {"expires_at": shop.expires_at})
        log_action(
            admin,
            AuditAction.SHOP_APPROVED,
            target=shop,
            metadata={"expires_at": shop.expires_at.isoformat(), "trial_months": trial_months},
            request=request,
        )
        _email_shop_on_commit(
            shop, "emails/shop_approved", {"expires_at": format_local_date(shop.expires_at)}
        )
    logger.info("Boutique %s validee", shop.pk)
    return shop


def reject_shop(shop: Shop, *, admin: User, reason: str, request=None) -> Shop:
    """Refuse une boutique en attente, avec un motif (RG-10, RG-12).

    Effets : statut REJECTED, rejected_at, rejection_reason, notification
    SHOP_REJECTED + e-mail, audit SHOP_REJECTED.
    Leve InvalidStateTransition (409) si la boutique n'est pas PENDING.
    """
    with transaction.atomic():
        shop = _lock(shop)
        _ensure_state(shop, ShopState.PENDING)
        shop.status = Shop.Status.REJECTED
        shop.rejected_at = timezone.now()
        shop.rejection_reason = reason
        shop.save(update_fields=["status", "rejected_at", "rejection_reason", "updated_at"])
        notify(shop.owner, NotificationType.SHOP_REJECTED, {"reason": reason})
        log_action(
            admin,
            AuditAction.SHOP_REJECTED,
            target=shop,
            metadata={"reason": reason},
            request=request,
        )
        _email_shop_on_commit(shop, "emails/shop_rejected", {"reason": reason})
    logger.info("Boutique %s refusee", shop.pk)
    return shop


# --- Blocage (RG-14, RG-15) -------------------------------------------------------
def block_shop(shop: Shop, *, admin: User, reason: str, request=None) -> Shop:
    """Bloque une boutique, quel que soit son etat (RG-14).

    Effets : is_blocked, blocked_at, block_reason ; toutes les sessions de la
    boutique sont fermees (refresh en liste noire) ; e-mail ; audit SHOP_BLOCKED.
    Aucune donnee n'est supprimee (RG-15).
    Leve InvalidStateTransition (409) si la boutique est deja bloquee.
    """
    with transaction.atomic():
        shop = _lock(shop)
        if shop.is_blocked:
            raise InvalidStateTransition(details={"current_state": ShopState.BLOCKED})
        previous_state = shop.get_state()
        shop.is_blocked = True
        shop.blocked_at = timezone.now()
        shop.block_reason = reason
        shop.save(update_fields=["is_blocked", "blocked_at", "block_reason", "updated_at"])
        revoked = revoke_all_sessions(shop.owner)
        log_action(
            admin,
            AuditAction.SHOP_BLOCKED,
            target=shop,
            metadata={
                "reason": reason,
                "previous_state": previous_state,
                "revoked_sessions": revoked,
            },
            request=request,
        )
        _email_shop_on_commit(shop, "emails/shop_blocked", {"reason": reason})
    logger.info("Boutique %s bloquee", shop.pk)
    return shop


def unblock_shop(shop: Shop, *, admin: User, request=None) -> Shop:
    """Debloque une boutique (RG-14).

    Le statut et la date d'expiration ne changent pas : l'etat est recalcule.
    Effets : notification SHOP_UNBLOCKED + e-mail, audit SHOP_UNBLOCKED (le motif
    du blocage est recopie dans `metadata.previous_block_reason`).
    Leve InvalidStateTransition (409) si la boutique n'est pas bloquee.
    """
    with transaction.atomic():
        shop = _lock(shop)
        if not shop.is_blocked:
            raise InvalidStateTransition(details={"current_state": shop.get_state()})
        previous_reason = shop.block_reason
        shop.is_blocked = False
        shop.block_reason = ""
        shop.blocked_at = None
        shop.save(update_fields=["is_blocked", "block_reason", "blocked_at", "updated_at"])
        notify(shop.owner, NotificationType.SHOP_UNBLOCKED, {})
        log_action(
            admin,
            AuditAction.SHOP_UNBLOCKED,
            target=shop,
            metadata={"previous_block_reason": previous_reason, "state": shop.get_state()},
            request=request,
        )
        _email_shop_on_commit(shop, "emails/shop_unblocked", {})
    logger.info("Boutique %s debloquee", shop.pk)
    return shop


# --- Recharge (RG-20 a RG-24) -----------------------------------------------------
@dataclass(frozen=True)
class RechargeComputation:
    current_expires_at: datetime
    base_date: datetime
    new_expires_at: datetime
    is_currently_expired: bool


def target_date_end(target_date: date) -> datetime:
    """Fin de la journee cible (23:59:59, heure de Nouakchott)."""
    return datetime.combine(target_date, time(23, 59, 59), tzinfo=_local_tz())


def compute_new_expiry(
    shop: Shop,
    *,
    duration_months: int | None = None,
    target_date: date | None = None,
    now: datetime | None = None,
) -> RechargeComputation:
    """Calcule la nouvelle date d'expiration sans rien enregistrer.

    Partage par l'apercu et la recharge. Regles :
    - RG-20 : seule une boutique APPROVED (active, expiree ou bloquee) se recharge ;
    - RG-22 : en mois, `max(expires_at, maintenant) + N mois` (mois calendaires) ;
    - RG-23 : une date cible doit etre posterieure au jour (heure de Nouakchott) de
      `max(expires_at, maintenant)` ; l'expiration est fixee a 23:59:59 ce jour-la.

    Leve InvalidStateTransition (409) si le statut n'est pas APPROVED et
    ValidationError (400) si la date cible est trop proche.
    """
    if (duration_months is None) == (target_date is None):
        raise ValueError("Exactement un parametre parmi duration_months et target_date.")
    if shop.status != Shop.Status.APPROVED or shop.expires_at is None:
        raise InvalidStateTransition(details={"current_state": shop.get_state()})
    now = now or timezone.now()
    current = shop.expires_at
    base = max(current, now)
    if duration_months is not None:
        new_expires_at = base + relativedelta(months=duration_months)
    else:
        if target_date <= base.astimezone(_local_tz()).date():
            raise ValidationError({"target_date": [TARGET_DATE_TOO_EARLY]})
        new_expires_at = target_date_end(target_date)
    return RechargeComputation(
        current_expires_at=current,
        base_date=base,
        new_expires_at=new_expires_at,
        is_currently_expired=current <= now,
    )


def recharge_shop(
    shop: Shop,
    *,
    admin: User,
    duration_months: int | None = None,
    target_date: date | None = None,
    amount_received: int | None = None,
    note: str = "",
    request=None,
) -> Recharge:
    """« Charger le compte » (RG-20 a RG-24).

    Transaction avec verrou sur la boutique : expires_at mis a jour, rappels
    d'expiration remis a zero, ligne d'historique, notification SHOP_RECHARGED
    + e-mail, audit SHOP_RECHARGED.
    Leve les memes erreurs que compute_new_expiry.
    """
    with transaction.atomic():
        shop = _lock(shop)
        computation = compute_new_expiry(
            shop, duration_months=duration_months, target_date=target_date
        )
        shop.expires_at = computation.new_expires_at
        shop.last_expiry_reminder_days = None
        shop.save(update_fields=["expires_at", "last_expiry_reminder_days", "updated_at"])
        recharge = Recharge.objects.create(
            shop=shop,
            performed_by=admin,
            duration_months=duration_months,
            previous_expires_at=computation.current_expires_at,
            new_expires_at=computation.new_expires_at,
            amount_received=amount_received,
            note=note or "",
        )
        notify(
            shop.owner,
            NotificationType.SHOP_RECHARGED,
            {
                "previous_expires_at": computation.current_expires_at,
                "new_expires_at": computation.new_expires_at,
            },
        )
        log_action(
            admin,
            AuditAction.SHOP_RECHARGED,
            target=shop,
            metadata={
                "recharge_id": recharge.pk,
                "previous_expires_at": computation.current_expires_at.isoformat(),
                "new_expires_at": computation.new_expires_at.isoformat(),
                "duration_months": duration_months,
                "target_date": target_date.isoformat() if target_date else None,
                "amount_received": amount_received,
            },
            request=request,
        )
        _email_shop_on_commit(
            shop,
            "emails/shop_recharged",
            {
                "previous_expires_at": format_local_date(computation.current_expires_at),
                "new_expires_at": format_local_date(computation.new_expires_at),
            },
        )
    logger.info("Boutique %s rechargee", shop.pk)
    return recharge


# --- Parametres de la plateforme --------------------------------------------------
def update_platform_settings(
    *, admin: User, fields: dict[str, Any], request=None
) -> PlatformSettings:
    """Modifie les parametres ; audit SETTINGS_UPDATED avec anciennes et nouvelles valeurs.

    L'enregistrement invalide le cache de PlatformSettings.load(). Les changements
    s'appliquent aux prochaines validations et commandes uniquement.
    """
    unknown = set(fields) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Parametres inconnus : {sorted(unknown)}")
    with transaction.atomic():
        platform = PlatformSettings.objects.select_for_update().get(
            pk=PlatformSettings.SINGLETON_ID
        )
        changes = {
            name: {"old": getattr(platform, name), "new": value}
            for name, value in fields.items()
            if getattr(platform, name) != value
        }
        if not changes:
            return platform
        for name, change in changes.items():
            setattr(platform, name, change["new"])
        platform.updated_by = admin
        platform.save()
        log_action(
            admin,
            AuditAction.SETTINGS_UPDATED,
            target=platform,
            target_type="platform_settings",
            metadata={"changes": changes},
            request=request,
        )
    logger.info("Parametres de la plateforme modifies : %s", sorted(changes))
    return platform


# --- Moderation des produits ------------------------------------------------------
def remove_product(product: Product, *, admin: User, reason: str, request=None) -> None:
    """Supprime un produit interdit.

    Effets : suppression du produit (les commandes gardent leurs copies, RG-46),
    fichiers image supprimes apres validation, notification PRODUCT_REMOVED a
    la boutique, audit PRODUCT_REMOVED_BY_ADMIN avec le nom et le prix.
    """
    with transaction.atomic():
        product = (
            Product.objects.select_for_update(of=("self",))
            .select_related("shop__owner")
            .get(pk=product.pk)
        )
        shop = product.shop
        product_name = product.name_fr or product.name_ar
        log_action(
            admin,
            AuditAction.PRODUCT_REMOVED_BY_ADMIN,
            target=product,
            metadata={
                "shop_id": shop.pk,
                "product_name": product_name,
                "name_fr": product.name_fr,
                "name_ar": product.name_ar,
                "price": product.price,
                "reason": reason,
            },
            request=request,
        )
        delete_file_on_commit(product.image)
        delete_file_on_commit(product.thumbnail)
        product.delete()
        notify(
            shop.owner,
            NotificationType.PRODUCT_REMOVED,
            {"product_name": product_name, "reason": reason},
        )
    logger.info("Produit retire par l'administrateur (boutique %s)", shop.pk)


# --- Rappels d'expiration (RG-25) -------------------------------------------------
def reminder_threshold(days_left: int) -> int | None:
    """Palier de rappel (7, 3 ou 1) atteint pour un nombre de jours restants."""
    reached = [days for days in EXPIRY_REMINDER_DAYS if days_left <= days]
    return min(reached) if reached else None


def _send_expiry_reminder(shop_id: int, now: datetime) -> bool:
    """Envoie au plus un rappel a une boutique ; renvoie True si un rappel est parti.

    La boutique est relue sous verrou : deux executions simultanees de la
    tache ne peuvent pas envoyer deux fois le meme rappel.
    """
    with transaction.atomic():
        shop = (
            Shop.objects.select_for_update(of=("self",))
            .select_related("owner")
            .filter(pk=shop_id)
            .first()
        )
        if shop is None or shop.get_state(now) != ShopState.ACTIVE:
            return False
        days_left = shop.days_left(now)
        threshold = reminder_threshold(days_left)
        if threshold is None:
            return False
        last = shop.last_expiry_reminder_days
        if last is not None and last <= threshold:
            return False
        shop.last_expiry_reminder_days = threshold
        shop.save(update_fields=["last_expiry_reminder_days", "updated_at"])
        notify(
            shop.owner,
            NotificationType.EXPIRY_REMINDER,
            {"expires_at": shop.expires_at, "days_left": days_left},
        )
        _email_shop_on_commit(
            shop,
            "emails/expiry_reminder",
            {"expires_at": format_local_date(shop.expires_at), "days_left": days_left},
        )
    return True


def send_expiry_reminders(now: datetime | None = None) -> int:
    """Rappels a 7, 3 et 1 jour(s) avant l'expiration (RG-25). Renvoie le nombre envoye.

    Idempotent : `last_expiry_reminder_days` retient le dernier palier envoye ;
    une execution manquee est rattrapee par le palier suivant, sans doublon.
    La recharge remet ce champ a NULL, ce qui relance les rappels.
    """
    now = now or timezone.now()
    shop_ids = list(
        Shop.objects.active(now)
        .filter(expires_at__lte=now + EXPIRY_REMINDER_WINDOW)
        .order_by("expires_at", "id")
        .values_list("id", flat=True)
    )
    sent = sum(1 for shop_id in shop_ids if _send_expiry_reminder(shop_id, now))
    logger.info("Rappels d'expiration envoyes : %d", sent)
    return sent
