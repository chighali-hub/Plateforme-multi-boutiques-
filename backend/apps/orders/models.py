"""Commandes et lignes de commande.

Voir docs/Documentation-API/04-schema-base-de-donnees.md section 6.
"""

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product
from apps.core.models import TimeStampedModel
from apps.core.storage import UploadTo, private_storage
from apps.core.validators import PHONE_PATTERN
from apps.shops.models import BankAccount, Shop

ORDER_MAX_LINES = 50
ORDER_ITEM_MAX_QUANTITY = 99


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", _("Nouvelle")
        CONFIRMED = "CONFIRMED", _("Confirmée")
        DELIVERED = "DELIVERED", _("Livrée")
        REJECTED = "REJECTED", _("Refusée")

    reference = models.CharField(max_length=20, unique=True)
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="orders")
    customer_name = models.CharField(max_length=100)
    customer_phone = models.CharField(max_length=8)
    delivery_address = models.CharField(max_length=255, blank=True, default="")
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    bank_name_snapshot = models.CharField(max_length=60, blank=True, default="")
    total_amount = models.PositiveIntegerField()
    deposit_percent = models.PositiveSmallIntegerField()
    deposit_required = models.PositiveIntegerField()
    amount_paid = models.PositiveIntegerField()
    payment_proof = models.FileField(
        storage=private_storage, upload_to=UploadTo("payment_proofs"), max_length=255
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    rejection_reason = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders_order"
        verbose_name = _("commande")
        verbose_name_plural = _("commandes")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["shop", "status", "-created_at"], name="orders_order_shop_status_idx"
            ),
            models.Index(fields=["shop", "delivered_at"], name="orders_order_revenue_idx"),
            models.Index(fields=["customer_phone"], name="orders_order_phone_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["SUBMITTED", "CONFIRMED", "DELIVERED", "REJECTED"]),
                name="orders_order_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status="DELIVERED") | Q(delivered_at__isnull=False),
                name="orders_order_delivered_has_date",
            ),
            models.CheckConstraint(
                condition=~Q(status="REJECTED") | ~Q(rejection_reason=""),
                name="orders_order_rejected_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gt=0), name="orders_order_total_positive"
            ),
            models.CheckConstraint(
                condition=Q(deposit_percent__gte=1, deposit_percent__lte=100),
                name="orders_order_deposit_percent_range",
            ),
            models.CheckConstraint(
                condition=Q(customer_phone__regex=PHONE_PATTERN), name="orders_order_phone_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.reference

    @property
    def remaining_amount(self) -> int:
        return max(self.total_amount - self.amount_paid, 0)


class OrderItem(models.Model):
    """Ligne de commande : copie du produit au moment de l'achat (RG-46)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items"
    )
    product_name_fr = models.CharField(max_length=150, blank=True, default="")
    product_name_ar = models.CharField(max_length=150, blank=True, default="")
    product_thumbnail = models.CharField(max_length=255, blank=True, default="")
    unit_price = models.PositiveIntegerField()
    quantity = models.PositiveSmallIntegerField()
    line_total = models.PositiveIntegerField()

    class Meta:
        db_table = "orders_order_item"
        verbose_name = _("ligne de commande")
        verbose_name_plural = _("lignes de commande")
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(unit_price__gt=0), name="orders_item_unit_price_positive"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1, quantity__lte=ORDER_ITEM_MAX_QUANTITY),
                name="orders_item_quantity_range",
            ),
            models.CheckConstraint(
                condition=Q(line_total=F("unit_price") * F("quantity")),
                name="orders_item_line_total_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product_name_fr or self.product_name_ar}"
