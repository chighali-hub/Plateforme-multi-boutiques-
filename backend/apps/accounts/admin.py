from django.contrib import admin

from .models import OtpCode, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "is_email_verified", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_email_verified")
    search_fields = ("email",)
    ordering = ("-date_joined",)
    # Le hachage du mot de passe n'est jamais affiche ni modifiable ici.
    exclude = ("password",)
    readonly_fields = ("last_login", "date_joined", "updated_at")


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    """Lecture seule, sans le hachage du code."""

    list_display = ("user", "purpose", "sent_to", "attempts", "expires_at", "consumed_at")
    list_filter = ("purpose",)
    search_fields = ("user__email", "sent_to")
    exclude = ("code_hash",)
    list_select_related = ("user",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
