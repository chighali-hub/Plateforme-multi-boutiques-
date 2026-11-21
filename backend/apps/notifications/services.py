"""Creation et rendu des notifications. Voir 05-aspects-transversaux.md section 12.

Une notification stocke `type` + `data`. Le titre et le message sont produits a
la lecture, dans la langue demandee (render).
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import translation
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User

from .models import Notification, NotificationType

# Cles de `data` exigees par type (04-schema-base-de-donnees.md section 7).
REQUIRED_DATA: dict[str, frozenset[str]] = {
    NotificationType.SHOP_SUBMITTED: frozenset({"shop_id", "shop_name"}),
    NotificationType.SHOP_RESUBMITTED: frozenset({"shop_id", "shop_name"}),
    NotificationType.SHOP_APPROVED: frozenset({"expires_at"}),
    NotificationType.SHOP_REJECTED: frozenset({"reason"}),
    NotificationType.SHOP_UNBLOCKED: frozenset(),
    NotificationType.SHOP_RECHARGED: frozenset({"previous_expires_at", "new_expires_at"}),
    NotificationType.EXPIRY_REMINDER: frozenset({"expires_at", "days_left"}),
    NotificationType.ORDER_NEW: frozenset(
        {"order_id", "reference", "total_amount", "customer_name"}
    ),
    NotificationType.IMPORT_COMPLETED: frozenset({"job_id", "success_count", "error_count"}),
    NotificationType.IMPORT_FAILED: frozenset({"job_id", "failure_reason"}),
    NotificationType.PRODUCT_REMOVED: frozenset({"product_name", "reason"}),
}

_DATE_KEYS = frozenset({"expires_at", "previous_expires_at", "new_expires_at"})


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _check_payload(notification_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if notification_type not in REQUIRED_DATA:
        raise ValueError(f"Type de notification inconnu : {notification_type}")
    missing = REQUIRED_DATA[notification_type] - data.keys()
    if missing:
        raise ValueError(f"Donnees manquantes pour {notification_type} : {sorted(missing)}")
    return {key: _serialize(value) for key, value in data.items()}


def notify(user: User, notification_type: str, data: dict[str, Any] | None = None) -> Notification:
    """Cree une notification pour un utilisateur. Aucun envoi synchrone.

    Leve ValueError si le type est inconnu ou si `data` est incomplet : c'est
    une erreur de programmation, pas une erreur utilisateur.
    """
    payload = _check_payload(str(notification_type), data or {})
    return Notification.objects.create(recipient=user, type=notification_type, data=payload)


def notify_admins(notification_type: str, data: dict[str, Any] | None = None) -> list[Notification]:
    """Cree une notification pour chaque administrateur actif."""
    payload = _check_payload(str(notification_type), data or {})
    admins: Iterable[User] = User.objects.filter(role=User.Role.ADMIN, is_active=True)
    return Notification.objects.bulk_create(
        [Notification(recipient=admin, type=notification_type, data=payload) for admin in admins]
    )


class _Params(dict):
    """Parametres de formatage : une cle absente donne une chaine vide."""

    def __missing__(self, key: str) -> str:
        return ""


def _format_date(value: Any) -> str:
    moment = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(moment, datetime):
        return str(value or "")
    return moment.astimezone(ZoneInfo(settings.TIME_ZONE)).strftime("%d/%m/%Y")


def _texts(notification_type: str, params: _Params) -> tuple[str, str]:
    if notification_type == NotificationType.SHOP_SUBMITTED:
        return (
            _("Nouvelle boutique à valider"),
            _("La boutique %(shop_name)s attend votre validation.") % params,
        )
    if notification_type == NotificationType.SHOP_RESUBMITTED:
        return (
            _("Boutique soumise à nouveau"),
            _("La boutique %(shop_name)s a renvoyé sa demande de validation.") % params,
        )
    if notification_type == NotificationType.SHOP_APPROVED:
        return (
            _("Boutique validée"),
            _("Votre boutique est validée. Elle est active jusqu'au %(expires_at)s.") % params,
        )
    if notification_type == NotificationType.SHOP_REJECTED:
        return (
            _("Demande refusée"),
            _("Votre demande a été refusée : %(reason)s") % params,
        )
    if notification_type == NotificationType.SHOP_UNBLOCKED:
        return _("Boutique débloquée"), _("Votre boutique a été débloquée.")
    if notification_type == NotificationType.SHOP_RECHARGED:
        return (
            _("Compte rechargé"),
            _("Votre compte est rechargé jusqu'au %(new_expires_at)s.") % params,
        )
    if notification_type == NotificationType.EXPIRY_REMINDER:
        days = int(params.get("days_left") or 0)
        return (
            _("Votre compte expire bientôt"),
            ngettext(
                "Votre compte expire dans %(days_left)s jour, le %(expires_at)s.",
                "Votre compte expire dans %(days_left)s jours, le %(expires_at)s.",
                days,
            )
            % params,
        )
    if notification_type == NotificationType.ORDER_NEW:
        return (
            _("Nouvelle commande"),
            _("Commande %(reference)s de %(customer_name)s : %(total_amount)s MRU.") % params,
        )
    if notification_type == NotificationType.IMPORT_COMPLETED:
        return (
            _("Import terminé"),
            _(
                "Produits créés en brouillon : %(success_count)s. "
                "Lignes en erreur : %(error_count)s."
            )
            % params,
        )
    if notification_type == NotificationType.IMPORT_FAILED:
        return (
            _("Import échoué"),
            _("L'import n'a pas pu être traité : %(failure_reason)s") % params,
        )
    if notification_type == NotificationType.PRODUCT_REMOVED:
        return (
            _("Produit retiré"),
            _("Le produit %(product_name)s a été retiré par l'administrateur : %(reason)s")
            % params,
        )
    return _("Notification"), ""


def render(notification: Notification, language: str | None = None) -> tuple[str, str]:
    """Renvoie (titre, message) dans la langue demandee (defaut : langue active)."""
    params = _Params(notification.data or {})
    for key in _DATE_KEYS & params.keys():
        params[key] = _format_date(params[key])
    if language:
        with translation.override(language):
            return _texts(notification.type, params)
    return _texts(notification.type, params)
