from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "product_name_fr",
        "product_name_ar",
        "product_thumbnail",
        "unit_price",
        "quantity",
        "line_total",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Lecture seule : montants et statuts ne changent que par les services.
    La capture de paiement (fichier prive) n'est pas exposee."""

    list_display = ("reference", "shop", "status", "total_amount", "amount_paid", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "shop__name")
    list_select_related = ("shop",)
    exclude = ("payment_proof",)
    inlines = [OrderItemInline]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
