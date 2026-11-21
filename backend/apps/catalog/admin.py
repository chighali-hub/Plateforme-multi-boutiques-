from django.contrib import admin

from .models import Category, ImportErrorRow, ImportJob, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name_fr", "name_ar", "shop", "sort_order")
    search_fields = ("name_fr", "name_ar", "shop__name")
    list_select_related = ("shop",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name_fr", "name_ar", "shop", "price", "status", "is_available", "source")
    list_filter = ("status", "is_available", "source")
    search_fields = ("name_fr", "name_ar", "shop__name")
    list_select_related = ("shop",)
    readonly_fields = ("shop", "source", "import_job", "published_at", "created_at", "updated_at")


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    """Lecture seule ; les fichiers d'import (prives) ne sont pas exposes."""

    list_display = ("id", "shop", "status", "total_rows", "success_count", "error_count")
    list_filter = ("status",)
    list_select_related = ("shop",)
    exclude = ("excel_file", "zip_file")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ImportErrorRow)
class ImportErrorRowAdmin(admin.ModelAdmin):
    list_display = ("job", "shop", "row_number", "name_fr", "price_raw")
    list_select_related = ("job", "shop")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
