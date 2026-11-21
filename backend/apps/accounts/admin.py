from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "is_email_verified", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_email_verified")
    search_fields = ("email",)
    ordering = ("-date_joined",)
