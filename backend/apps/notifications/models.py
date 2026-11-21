"""Notifications in-app. Voir 04-schema-base-de-donnees.md section 7.

Le texte n'est pas stocke : il est produit a la lecture, dans la langue de la
requete, a partir de `type` et `data` (voir services.render).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class NotificationType(models.TextChoices):
    SHOP_SUBMITTED = "SHOP_SUBMITTED", _("Nouvelle boutique à valider")
    SHOP_RESUBMITTED = "SHOP_RESUBMITTED", _("Boutique soumise à nouveau")
    SHOP_APPROVED = "SHOP_APPROVED", _("Boutique validée")
    SHOP_REJECTED = "SHOP_REJECTED", _("Boutique refusée")
    SHOP_UNBLOCKED = "SHOP_UNBLOCKED", _("Boutique débloquée")
    SHOP_RECHARGED = "SHOP_RECHARGED", _("Compte rechargé")
    EXPIRY_REMINDER = "EXPIRY_REMINDER", _("Rappel d'expiration")
    ORDER_NEW = "ORDER_NEW", _("Nouvelle commande")
    IMPORT_COMPLETED = "IMPORT_COMPLETED", _("Import terminé")
    IMPORT_FAILED = "IMPORT_FAILED", _("Import échoué")
    PRODUCT_REMOVED = "PRODUCT_REMOVED", _("Produit retiré")


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=40, choices=NotificationType.choices)
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_notification"
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="notif_recipient_read_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(type__in=NotificationType.values), name="notif_type_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} -> {self.recipient_id}"
