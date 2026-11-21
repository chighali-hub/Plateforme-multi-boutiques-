"""Historique des recharges. Voir 04-schema-base-de-donnees.md section 8."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.shops.models import Shop

RECHARGE_MONTHS_MIN = 1
RECHARGE_MONTHS_MAX = 120


class Recharge(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="recharges")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_expires_at = models.DateTimeField()
    new_expires_at = models.DateTimeField()
    amount_received = models.PositiveIntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "administration_recharge"
        verbose_name = _("recharge")
        verbose_name_plural = _("recharges")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["shop", "-created_at"], name="admin_recharge_shop_idx"),
            models.Index(fields=["created_at"], name="admin_recharge_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(new_expires_at__gt=F("previous_expires_at")),
                name="admin_recharge_extends_expiry",
            ),
            models.CheckConstraint(
                condition=Q(duration_months__isnull=True)
                | Q(
                    duration_months__gte=RECHARGE_MONTHS_MIN,
                    duration_months__lte=RECHARGE_MONTHS_MAX,
                ),
                name="admin_recharge_months_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Recharge #{self.pk} ({self.shop_id})"
