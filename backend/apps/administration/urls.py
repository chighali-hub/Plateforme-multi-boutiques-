"""Routes de l'application Administration de la plateforme.

Voir docs/Documentation-API/03-reference-api.md section 11 (et section 10 pour
/public/platform-info/).
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "public/platform-info/",
        views.PlatformInfoView.as_view(),
        name="administration-platform-info",
    ),
    path("admin/dashboard/", views.DashboardView.as_view(), name="administration-dashboard"),
    path("admin/shops/", views.ShopListView.as_view(), name="administration-shops-list"),
    path(
        "admin/shops/<int:pk>/",
        views.ShopDetailView.as_view(),
        name="administration-shops-detail",
    ),
    path(
        "admin/shops/<int:pk>/id-card/<str:side>/",
        views.ShopIdCardView.as_view(),
        name="administration-shops-id-card",
    ),
    path(
        "admin/shops/<int:pk>/approve/",
        views.ApproveShopView.as_view(),
        name="administration-shops-approve",
    ),
    path(
        "admin/shops/<int:pk>/reject/",
        views.RejectShopView.as_view(),
        name="administration-shops-reject",
    ),
    path(
        "admin/shops/<int:pk>/block/",
        views.BlockShopView.as_view(),
        name="administration-shops-block",
    ),
    path(
        "admin/shops/<int:pk>/unblock/",
        views.UnblockShopView.as_view(),
        name="administration-shops-unblock",
    ),
    path(
        "admin/shops/<int:pk>/recharge-preview/",
        views.RechargePreviewView.as_view(),
        name="administration-shops-recharge-preview",
    ),
    path(
        "admin/shops/<int:pk>/recharge/",
        views.RechargeShopView.as_view(),
        name="administration-shops-recharge",
    ),
    path(
        "admin/shops/<int:pk>/recharges/",
        views.ShopRechargeListView.as_view(),
        name="administration-shops-recharges",
    ),
    path(
        "admin/shops/<int:pk>/products/",
        views.ShopProductListView.as_view(),
        name="administration-shops-products",
    ),
    path(
        "admin/shops/<int:pk>/products/<int:product_id>/remove/",
        views.RemoveProductView.as_view(),
        name="administration-shops-products-remove",
    ),
    path("admin/recharges/", views.RechargeListView.as_view(), name="administration-recharges"),
    path(
        "admin/settings/",
        views.PlatformSettingsView.as_view(),
        name="administration-settings",
    ),
    path("admin/audit-logs/", views.AuditLogListView.as_view(), name="administration-audit-logs"),
]
