from django.contrib import admin

from .models import Recharge


@admin.register(Recharge)
class RechargeAdmin(admin.ModelAdmin):
    """Lecture seule : une recharge passe par l'API (calcul, verrou, notification)."""

    list_display = ("shop", "previous_expires_at", "new_expires_at", "performed_by", "created_at")
    search_fields = ("shop__name",)
    list_select_related = ("shop", "performed_by")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
