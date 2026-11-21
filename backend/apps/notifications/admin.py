from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "type", "is_read", "created_at")
    list_filter = ("type", "is_read")
    search_fields = ("recipient__email",)
    list_select_related = ("recipient",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
