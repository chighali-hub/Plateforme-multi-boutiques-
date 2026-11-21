"""Catalogue : categories, produits, imports Excel + ZIP.

Voir docs/Documentation-API/04-schema-base-de-donnees.md section 5.
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.storage import UploadTo, private_storage
from apps.core.text import normalize_search_text
from apps.shops.models import Shop

PRODUCT_PRICE_MIN = 1
PRODUCT_PRICE_MAX = 100_000_000


class Category(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="categories")
    name_fr = models.CharField(max_length=60, blank=True, default="")
    name_ar = models.CharField(max_length=60, blank=True, default="")
    sort_order = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalog_category"
        verbose_name = _("catégorie")
        verbose_name_plural = _("catégories")
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(name_fr="") | ~Q(name_ar=""), name="catalog_category_has_name"
            ),
            models.UniqueConstraint(
                "shop",
                Lower("name_fr"),
                condition=~Q(name_fr=""),
                name="catalog_category_unique_name_fr",
            ),
            models.UniqueConstraint(
                "shop",
                Lower("name_ar"),
                condition=~Q(name_ar=""),
                name="catalog_category_unique_name_ar",
            ),
        ]

    def __str__(self) -> str:
        return self.name_fr or self.name_ar


def product_search_texts(
    name_fr: str, name_ar: str, description_fr: str, description_ar: str
) -> tuple[str, str]:
    """Calcule (search_text_fr, search_text_ar) d'un produit.

    Utilisee par Product.save() et par les creations en masse (bulk_create),
    qui n'appellent pas save().
    """
    text_fr = normalize_search_text(f"{name_fr or name_ar} {description_fr}")
    text_ar = normalize_search_text(f"{name_ar or name_fr} {description_ar}")
    return text_fr, text_ar


class ImportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("En attente")
        PROCESSING = "PROCESSING", _("En cours")
        COMPLETED = "COMPLETED", _("Terminé")
        FAILED = "FAILED", _("Échoué")

    ACTIVE_STATUSES = (Status.PENDING, Status.PROCESSING)

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="import_jobs")
    excel_file = models.FileField(
        storage=private_storage, upload_to=UploadTo("imports"), max_length=255
    )
    zip_file = models.FileField(
        storage=private_storage, upload_to=UploadTo("imports"), max_length=255
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "catalog_import_job"
        verbose_name = _("import de produits")
        verbose_name_plural = _("imports de produits")
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["shop", "-created_at"], name="catalog_import_shop_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["PENDING", "PROCESSING", "COMPLETED", "FAILED"]),
                name="catalog_import_status_valid",
            ),
            # Un seul import PENDING ou PROCESSING par boutique, garanti par la base.
            models.UniqueConstraint(
                fields=["shop"],
                condition=Q(status__in=["PENDING", "PROCESSING"]),
                name="catalog_import_one_active_per_shop",
            ),
        ]

    def __str__(self) -> str:
        return f"Import #{self.pk} ({self.status})"


class Product(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Brouillon")
        PUBLISHED = "PUBLISHED", _("Publié")

    class Source(models.TextChoices):
        MANUAL = "MANUAL", _("Saisie manuelle")
        IMPORT = "IMPORT", _("Import")

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    name_fr = models.CharField(max_length=150, blank=True, default="")
    name_ar = models.CharField(max_length=150, blank=True, default="")
    description_fr = models.TextField(blank=True, default="")
    description_ar = models.TextField(blank=True, default="")
    price = models.PositiveIntegerField()
    image = models.FileField(upload_to=UploadTo("products"), max_length=255)
    thumbnail = models.FileField(upload_to=UploadTo("products"), max_length=255)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PUBLISHED)
    is_available = models.BooleanField(default=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    import_job = models.ForeignKey(
        ImportJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    search_text_fr = models.TextField(blank=True, default="", editable=False)
    search_text_ar = models.TextField(blank=True, default="", editable=False)
    published_at = models.DateTimeField(null=True, blank=True)

    SEARCH_SOURCE_FIELDS = frozenset({"name_fr", "name_ar", "description_fr", "description_ar"})
    SEARCH_FIELDS = ("search_text_fr", "search_text_ar")

    class Meta:
        db_table = "catalog_product"
        verbose_name = _("produit")
        verbose_name_plural = _("produits")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["shop", "status", "is_available", "price"],
                name="catalog_product_public_idx",
            ),
            models.Index(fields=["shop", "category"], name="catalog_product_category_idx"),
            models.Index(fields=["shop", "-created_at"], name="catalog_product_created_idx"),
            GinIndex(
                fields=["search_text_fr"],
                opclasses=["gin_trgm_ops"],
                name="catalog_product_search_fr_trgm",
            ),
            GinIndex(
                fields=["search_text_ar"],
                opclasses=["gin_trgm_ops"],
                name="catalog_product_search_ar_trgm",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(name_fr="") | ~Q(name_ar=""), name="catalog_product_has_name"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["DRAFT", "PUBLISHED"]), name="catalog_product_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(price__gte=PRODUCT_PRICE_MIN, price__lte=PRODUCT_PRICE_MAX),
                name="catalog_product_price_range",
            ),
            models.CheckConstraint(
                condition=Q(source__in=["MANUAL", "IMPORT"]), name="catalog_product_source_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.name_fr or self.name_ar

    def refresh_search_fields(self) -> None:
        self.search_text_fr, self.search_text_ar = product_search_texts(
            self.name_fr, self.name_ar, self.description_fr, self.description_ar
        )

    def save(self, *args, **kwargs):
        self.refresh_search_fields()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and self.SEARCH_SOURCE_FIELDS & set(update_fields):
            kwargs["update_fields"] = set(update_fields) | set(self.SEARCH_FIELDS)
        super().save(*args, **kwargs)


class ImportErrorRow(TimeStampedModel):
    """Ligne d'import invalide, en attente de correction (liste 2)."""

    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="error_rows")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="import_error_rows")
    row_number = models.PositiveIntegerField()
    name_fr = models.CharField(max_length=150, blank=True, default="")
    name_ar = models.CharField(max_length=150, blank=True, default="")
    description_fr = models.TextField(blank=True, default="")
    description_ar = models.TextField(blank=True, default="")
    price_raw = models.CharField(max_length=50, blank=True, default="")
    category_raw = models.CharField(max_length=60, blank=True, default="")
    image_filename = models.CharField(max_length=255, blank=True, default="")
    image = models.FileField(upload_to=UploadTo("products"), max_length=255, blank=True)
    thumbnail = models.FileField(upload_to=UploadTo("products"), max_length=255, blank=True)
    errors = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "catalog_import_error_row"
        verbose_name = _("ligne d'import en erreur")
        verbose_name_plural = _("lignes d'import en erreur")
        ordering = ["row_number", "id"]
        indexes = [models.Index(fields=["shop", "job"], name="catalog_errorrow_shop_job_idx")]

    def __str__(self) -> str:
        return f"Ligne {self.row_number} (import #{self.job_id})"
