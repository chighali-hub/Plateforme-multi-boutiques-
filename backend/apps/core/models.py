"""Modeles communs : horodatage, parametres de la plateforme, journal d'audit.

Voir docs/Documentation-API/04-schema-base-de-donnees.md, section 3.
"""

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Ajoute created_at et updated_at, horodates par le serveur en UTC."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PlatformSettings(models.Model):
    """Parametres modifiables par l'administrateur. Une seule ligne (id = 1)."""

    SINGLETON_ID = 1
    CACHE_KEY = "core:platform_settings"
    CACHE_TIMEOUT_SECONDS = 300

    id = models.BigIntegerField(primary_key=True, default=SINGLETON_ID, editable=False)
    admin_whatsapp = models.CharField(max_length=8, blank=True, default="")
    admin_contact_email = models.EmailField(max_length=254, blank=True, default="")
    trial_months = models.PositiveSmallIntegerField(default=1)
    deposit_percent = models.PositiveSmallIntegerField(default=30)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_platform_settings"
        verbose_name = _("paramètres de la plateforme")
        verbose_name_plural = _("paramètres de la plateforme")
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="core_settings_singleton"),
            models.CheckConstraint(
                condition=Q(trial_months__gte=0, trial_months__lte=12),
                name="core_settings_trial_months_range",
            ),
            models.CheckConstraint(
                condition=Q(deposit_percent__gte=1, deposit_percent__lte=100),
                name="core_settings_deposit_percent_range",
            ),
        ]

    def __str__(self) -> str:
        return str(_("Paramètres de la plateforme"))

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        # La cle primaire a une valeur par defaut : sans ce controle, Django
        # tenterait un INSERT et violerait l'unicite de la ligne existante.
        if self._state.adding and type(self).objects.filter(pk=self.SINGLETON_ID).exists():
            self._state.adding = False
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):
        raise PermissionError("La ligne des parametres de la plateforme ne se supprime pas.")

    @classmethod
    def load(cls) -> "PlatformSettings":
        """Renvoie la ligne unique, depuis le cache si possible.

        La ligne est creee par une migration de donnees ; get_or_create couvre
        une base remise a zero a la main.
        """
        instance = cache.get(cls.CACHE_KEY)
        if instance is None:
            instance, _created = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
            cache.set(cls.CACHE_KEY, instance, cls.CACHE_TIMEOUT_SECONDS)
        return instance


class AuditAction(models.TextChoices):
    SHOP_SUBMITTED = "SHOP_SUBMITTED", _("Boutique soumise")
    SHOP_RESUBMITTED = "SHOP_RESUBMITTED", _("Boutique soumise à nouveau")
    SHOP_APPROVED = "SHOP_APPROVED", _("Boutique validée")
    SHOP_REJECTED = "SHOP_REJECTED", _("Boutique refusée")
    SHOP_BLOCKED = "SHOP_BLOCKED", _("Boutique bloquée")
    SHOP_UNBLOCKED = "SHOP_UNBLOCKED", _("Boutique débloquée")
    SHOP_RECHARGED = "SHOP_RECHARGED", _("Boutique rechargée")
    PRODUCT_REMOVED_BY_ADMIN = "PRODUCT_REMOVED_BY_ADMIN", _("Produit retiré par l'administrateur")
    SETTINGS_UPDATED = "SETTINGS_UPDATED", _("Paramètres modifiés")
    ADMIN_LOGIN = "ADMIN_LOGIN", _("Connexion administrateur")
    PASSWORD_RESET = "PASSWORD_RESET", _("Mot de passe réinitialisé")
    EMAIL_CHANGED = "EMAIL_CHANGED", _("E-mail modifié")


class AuditLog(models.Model):
    """Journal des actions sensibles. Ajout seulement : jamais modifie ni supprime."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50, choices=AuditAction.choices)
    target_type = models.CharField(max_length=50)
    target_id = models.BigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_audit_log"
        verbose_name = _("entrée d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="core_audit_target_idx"),
            models.Index(fields=["action"], name="core_audit_action_idx"),
            models.Index(fields=["-created_at"], name="core_audit_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=AuditAction.values), name="core_audit_action_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}#{self.target_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Une entree d'audit ne se modifie pas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Une entree d'audit ne se supprime pas.")
