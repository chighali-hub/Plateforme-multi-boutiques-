"""Routes de l'application Catalogue produits.

Voir docs/Documentation-API/03-reference-api.md section 6. Les routes
litterales de `shop/products/` (`bulk-publish/`, `import/...`) se declarent
dans PRODUCT_LITERAL_ROUTES, donc avant `shop/products/<int:pk>/` (section 1).
"""

from django.urls import path

from . import views

CATEGORY_ROUTES = [
    path(
        "shop/categories/",
        views.CategoryListCreateView.as_view(),
        name="catalog-categories-list",
    ),
    path(
        "shop/categories/<int:pk>/",
        views.CategoryDetailView.as_view(),
        name="catalog-categories-detail",
    ),
]

PRODUCT_LITERAL_ROUTES = [
    path(
        "shop/products/bulk-publish/",
        views.ProductBulkPublishView.as_view(),
        name="catalog-products-bulk-publish",
    ),
    path(
        "shop/products/bulk-update/",
        views.ProductBulkUpdateView.as_view(),
        name="catalog-products-bulk-update",
    ),
    path(
        "shop/products/bulk-delete/",
        views.ProductBulkDeleteView.as_view(),
        name="catalog-products-bulk-delete",
    ),
]

PRODUCT_ROUTES = [
    path("shop/products/", views.ProductListCreateView.as_view(), name="catalog-products-list"),
    *PRODUCT_LITERAL_ROUTES,
    path(
        "shop/products/<int:pk>/",
        views.ProductDetailView.as_view(),
        name="catalog-products-detail",
    ),
]

urlpatterns = [*CATEGORY_ROUTES, *PRODUCT_ROUTES]
