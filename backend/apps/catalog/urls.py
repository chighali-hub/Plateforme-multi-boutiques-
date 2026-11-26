"""Routes de l'application Catalogue produits.

Voir docs/Documentation-API/03-reference-api.md section 6.
"""

from django.urls import path

from . import views

urlpatterns = [
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
