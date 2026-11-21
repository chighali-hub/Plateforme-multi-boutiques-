"""Boutiques, modeles de design et moyens de paiement.

Voir docs/Documentation-API/04-schema-base-de-donnees.md section 4, et
01-vue-d-ensemble.md section 4 pour le cycle de vie et l'etat calcule.
"""

import math
from datetime import datetime

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Case, Exists, OuterRef, Q, Value, When
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.storage import UploadTo, private_storage
from apps.core.text import normalize_search_text
from apps.core.validators import HEX_COLOR_PATTERN, PHONE_PATTERN

SLUG_MAX_LENGTH = 100
SLUG_FALLBACK = "boutique"
EXPIRY_REMINDER_DAYS = (7, 3, 1)


class ThemeTemplate(models.Model):
    """Modele de design propose aux boutiques."""

    class Layout(models.TextChoices):
        GRID = "GRID", _("Grille")
        LIST = "LIST", _("Liste")
        MAGAZINE = "MAGAZINE", _("Magazine")
        MINIMAL = "MINIMAL", _("Minimal")

    code = models.CharField(max_length=40, unique=True)
    name_fr = models.CharField(max_length=60)
    name_ar = models.CharField(max_length=60)
    layout = models.CharField(max_length=20, choices=Layout.choices)
    preview_image = models.FileField(upload_to="themes/", max_length=255)
    default_primary_color = models.CharField(max_length=7)
    default_accent_color = models.CharField(max_length=7)
    is_active = models.BooleanField(default=True)
    sort_order = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "shops_theme_template"
        verbose_name = _("modèle de design")
        verbose_name_plural = _("modèles de design")
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(layout__in=["GRID", "LIST", "MAGAZINE", "MINIMAL"]),
                name="shops_theme_layout_valid",
            ),
            models.CheckConstraint(
                condition=Q(default_primary_color__regex=HEX_COLOR_PATTERN)
                & Q(default_accent_color__regex=HEX_COLOR_PATTERN),
                name="shops_theme_colors_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.code


class ShopState(models.TextChoices):
    """Etat effectif calcule (jamais stocke). Ordre d'evaluation : voir Shop.state."""

    ONBOARDING = "ONBOARDING", _("Inscription en cours")
    PENDING = "PENDING", _("En attente de validation")
    REJECTED = "REJECTED", _("Refusée")
    ACTIVE = "ACTIVE", _("Active")
    EXPIRED = "EXPIRED", _("Expirée")
    BLOCKED = "BLOCKED", _("Bloquée")


class ShopQuerySet(models.QuerySet):
    def with_state(self, now: datetime | None = None) -> "ShopQuerySet":
        """Annote `computed_state`, meme regle que la propriete Shop.state.

        L'annotation ne s'appelle pas `state` pour ne pas masquer la propriete.
        Une boutique APPROVED sans date d'expiration (interdit par contrainte)
        retombe sur EXPIRED : en cas de doute, l'acces est ferme.
        """
        now = now or timezone.now()
        return self.annotate(
            computed_state=Case(
                When(is_blocked=True, then=Value(ShopState.BLOCKED)),
                When(
                    ~Q(onboarding_step=Shop.OnboardingStep.COMPLETED),
                    then=Value(ShopState.ONBOARDING),
                ),
                When(status=Shop.Status.PENDING, then=Value(ShopState.PENDING)),
                When(status=Shop.Status.REJECTED, then=Value(ShopState.REJECTED)),
                When(status=Shop.Status.APPROVED, expires_at__gt=now, then=Value(ShopState.ACTIVE)),
                default=Value(ShopState.EXPIRED),
                output_field=models.CharField(max_length=10),
            )
        )

    def active(self, now: datetime | None = None) -> "ShopQuerySet":
        now = now or timezone.now()
        return self.filter(
            is_blocked=False,
            onboarding_step=Shop.OnboardingStep.COMPLETED,
            status=Shop.Status.APPROVED,
            expires_at__gt=now,
        )

    def publicly_visible(self, now: datetime | None = None) -> "ShopQuerySet":
        """RG-40 : etat ACTIVE et au moins une banque."""
        has_bank = BankAccount.objects.filter(shop=OuterRef("pk"))
        return self.active(now).filter(Exists(has_bank))


class Shop(TimeStampedModel):
    class OnboardingStep(models.TextChoices):
        VERIFY_EMAIL = "VERIFY_EMAIL", _("Vérification de l'e-mail")
        CHOOSE_DESIGN = "CHOOSE_DESIGN", _("Choix du design")
        ACCEPT_TERMS = "ACCEPT_TERMS", _("Acceptation des conditions")
        COMPLETED = "COMPLETED", _("Terminé")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("En attente")
        APPROVED = "APPROVED", _("Validée")
        REJECTED = "REJECTED", _("Refusée")

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop"
    )
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, unique=True)
    logo = models.FileField(upload_to=UploadTo("shops/logos"), max_length=255)
    description_fr = models.CharField(max_length=500)
    description_ar = models.CharField(max_length=500)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=8)
    whatsapp = models.CharField(max_length=8)
    owner_full_name = models.CharField(max_length=120)
    id_card_front = models.FileField(
        storage=private_storage, upload_to=UploadTo("id_cards"), max_length=255
    )
    id_card_back = models.FileField(
        storage=private_storage, upload_to=UploadTo("id_cards"), max_length=255
    )
    theme = models.ForeignKey(
        ThemeTemplate, on_delete=models.PROTECT, null=True, blank=True, related_name="shops"
    )
    primary_color = models.CharField(max_length=7, blank=True, default="")
    accent_color = models.CharField(max_length=7, blank=True, default="")
    onboarding_step = models.CharField(
        max_length=20, choices=OnboardingStep.choices, default=OnboardingStep.VERIFY_EMAIL
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True, default="")
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    block_reason = models.TextField(blank=True, default="")
    blocked_at = models.DateTimeField(null=True, blank=True)
    last_expiry_reminder_days = models.SmallIntegerField(null=True, blank=True)
    search_name = models.TextField(blank=True, default="", editable=False)
    search_text_fr = models.TextField(blank=True, default="", editable=False)
    search_text_ar = models.TextField(blank=True, default="", editable=False)

    objects = ShopQuerySet.as_manager()

    SEARCH_SOURCE_FIELDS = frozenset({"name", "description_fr", "description_ar"})
    SEARCH_FIELDS = ("search_name", "search_text_fr", "search_text_ar")

    class Meta:
        db_table = "shops_shop"
        verbose_name = _("boutique")
        verbose_name_plural = _("boutiques")
        indexes = [
            models.Index(
                fields=["status", "is_blocked", "expires_at"], name="shops_shop_visibility_idx"
            ),
            models.Index(fields=["submitted_at"], name="shops_shop_submitted_idx"),
            GinIndex(
                fields=["search_text_fr"],
                opclasses=["gin_trgm_ops"],
                name="shops_shop_search_fr_trgm",
            ),
            GinIndex(
                fields=["search_text_ar"],
                opclasses=["gin_trgm_ops"],
                name="shops_shop_search_ar_trgm",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["PENDING", "APPROVED", "REJECTED"]),
                name="shops_shop_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status="APPROVED") | Q(expires_at__isnull=False),
                name="shops_shop_approved_has_expiry",
            ),
            models.CheckConstraint(
                condition=Q(
                    onboarding_step__in=[
                        "VERIFY_EMAIL",
                        "CHOOSE_DESIGN",
                        "ACCEPT_TERMS",
                        "COMPLETED",
                    ]
                ),
                name="shops_shop_onboarding_step_valid",
            ),
            models.CheckConstraint(
                condition=Q(last_expiry_reminder_days__isnull=True)
                | Q(last_expiry_reminder_days__in=EXPIRY_REMINDER_DAYS),
                name="shops_shop_reminder_days_valid",
            ),
            models.CheckConstraint(
                condition=Q(phone__regex=PHONE_PATTERN) & Q(whatsapp__regex=PHONE_PATTERN),
                name="shops_shop_phones_valid",
            ),
            models.CheckConstraint(
                condition=(Q(primary_color="") | Q(primary_color__regex=HEX_COLOR_PATTERN))
                & (Q(accent_color="") | Q(accent_color__regex=HEX_COLOR_PATTERN)),
                name="shops_shop_colors_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    # --- Etat calcule ------------------------------------------------------
    def get_state(self, now: datetime | None = None) -> str:
        """Etat effectif, evalue dans l'ordre de 01-vue-d-ensemble.md section 4.2."""
        if self.is_blocked:
            return ShopState.BLOCKED
        if self.onboarding_step != self.OnboardingStep.COMPLETED:
            return ShopState.ONBOARDING
        if self.status == self.Status.PENDING:
            return ShopState.PENDING
        if self.status == self.Status.REJECTED:
            return ShopState.REJECTED
        now = now or timezone.now()
        if self.expires_at is not None and self.expires_at > now:
            return ShopState.ACTIVE
        return ShopState.EXPIRED

    @property
    def state(self) -> str:
        return self.get_state()

    def is_publicly_visible(self, now: datetime | None = None) -> bool:
        """RG-40 : etat ACTIVE et au moins une banque."""
        return self.get_state(now) == ShopState.ACTIVE and self.bank_accounts.exists()

    def days_left(self, now: datetime | None = None) -> int:
        """Jours restants avant expiration, arrondis au superieur, minimum 0."""
        if self.expires_at is None:
            return 0
        remaining = (self.expires_at - (now or timezone.now())).total_seconds()
        return max(math.ceil(remaining / 86400), 0)

    # --- Champs derives ------------------------------------------------------
    def refresh_search_fields(self) -> None:
        self.search_name = normalize_search_text(self.name)
        self.search_text_fr = normalize_search_text(f"{self.name} {self.description_fr}")
        self.search_text_ar = normalize_search_text(f"{self.name} {self.description_ar}")

    def save(self, *args, **kwargs):
        self.refresh_search_fields()
        if not self.slug:
            self.slug = generate_unique_slug(self.name)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and self.SEARCH_SOURCE_FIELDS & set(update_fields):
            kwargs["update_fields"] = set(update_fields) | set(self.SEARCH_FIELDS)
        super().save(*args, **kwargs)


def generate_unique_slug(name: str) -> str:
    """Slug derive du nom, rendu unique par un suffixe -2, -3...

    Un nom entierement en lettres arabes donne un slug vide : on utilise alors
    `boutique`. L'unicite finale est garantie par la contrainte UNIQUE ; un
    appelant concurrent recoit une IntegrityError et recommence.
    """
    base = slugify(name)[:SLUG_MAX_LENGTH].strip("-") or SLUG_FALLBACK
    taken = set(
        Shop.objects.filter(slug__regex=rf"^{base}(-[0-9]+)?$").values_list("slug", flat=True)
    )
    if base not in taken:
        return base
    index = 2
    while True:
        suffix = f"-{index}"
        candidate = f"{base[: SLUG_MAX_LENGTH - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        index += 1


class BankAccount(TimeStampedModel):
    """Moyen de paiement affiche aux clients (Bankily, Sedad, Click...)."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="bank_accounts")
    bank_name = models.CharField(max_length=60)
    payment_code = models.CharField(max_length=40)

    class Meta:
        db_table = "shops_bank_account"
        verbose_name = _("compte bancaire")
        verbose_name_plural = _("comptes bancaires")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "bank_name", "payment_code"], name="shops_bank_unique_per_shop"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.bank_name} {self.payment_code}"
