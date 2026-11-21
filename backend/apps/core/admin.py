from django.contrib import admin

from .models import AuditLog, PlatformSettings


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    list_display = ("admin_whatsapp", "admin_contact_email", "trial_months", "deposit_percent")
    readonly_fields = ("updated_by", "updated_at")

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Lecture seule : le journal d'audit n'est jamais modifie."""

    list_display = ("created_at", "action", "target_type", "target_id", "actor", "ip_address")
    list_filter = ("action", "target_type")
    search_fields = ("actor__email",)
    list_select_related = ("actor",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
