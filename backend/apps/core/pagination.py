"""Pagination des listes. Voir 03-reference-api.md section 0.6."""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Pagination par defaut de l'API : 20 elements, 100 au maximum."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PublicPagination(StandardPagination):
    """Listes du site public : 24 elements par page (grille de cartes)."""

    page_size = 24
