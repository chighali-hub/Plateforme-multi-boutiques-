from django.contrib import admin

from .models import BankAccount, Shop, ThemeTemplate


@admin.register(ThemeTemplate)
class ThemeTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "name_fr", "layout", "is_active", "sort_order")
    list_filter = ("layout", "is_active")


class BankAccountInline(admin.TabularInline):
    model = BankAccount
    extra = 0


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    """Les decisions metier (validation, blocage, recharge) passent par l'API
    d'administration, qui notifie et audite : ici ces champs sont en lecture seule.
    Les cartes d'identite (fichiers prives) ne sont pas exposees."""

    list_display = (
        "name",
        "slug",
        "owner",
        "status",
        "onboarding_step",
        "is_blocked",
        "expires_at",
    )
    list_filter = ("status", "onboarding_step", "is_blocked")
    search_fields = ("name", "slug", "owner__email")
    list_select_related = ("owner",)
    exclude = ("id_card_front", "id_card_back")
    readonly_fields = (
        "owner",
        "slug",
        "status",
        "onboarding_step",
        "rejection_reason",
        "terms_accepted_at",
        "submitted_at",
        "approved_at",
        "approved_by",
        "rejected_at",
        "expires_at",
        "is_blocked",
        "block_reason",
        "blocked_at",
        "last_expiry_reminder_days",
        "created_at",
        "updated_at",
    )
    inlines = [BankAccountInline]

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
