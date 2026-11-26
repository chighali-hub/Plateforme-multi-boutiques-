"""Vues du catalogue de l'espace boutique : categories et produits.

Voir 03-reference-api.md section 6. Tous ces endpoints exigent l'etat ACTIVE
(matrice de la section 0.3) et partent toujours de `request.shop`.
"""

from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.openapi import error_responses
from apps.core.permissions import IsShopOwner, ShopStateAllowed
from apps.shops.models import ShopState

from . import selectors, serializers, services
from .filters import ProductFilterSet
from .models import Category, Product

TAG_CATEGORIES = "Boutique - Catégories"
TAG_PRODUCTS = "Boutique - Produits"

SHOP_ERRORS = (
    "401 AUTHENTICATION_REQUIRED",
    "403 PERMISSION_DENIED",
    "403 SHOP_BLOCKED",
    "403 SHOP_EXPIRED",
    "403 SHOP_STATE_FORBIDDEN",
)


def _get_category(request, pk: int) -> Category:
    """Categorie de la boutique connectee, avec `products_count`.

    Une categorie d'une autre boutique renvoie 404, jamais 403.
    """
    return get_object_or_404(selectors.get_shop_categories(request.shop), pk=pk)


class CategoryListCreateView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Mes catégories",
        description="Liste non paginée, triée par `sort_order`, puis `name_fr`.",
        responses={
            200: serializers.CategorySerializer(many=True),
            **error_responses(*SHOP_ERRORS),
        },
    )
    def get(self, request):
        categories = selectors.get_shop_categories(request.shop)
        return Response(serializers.CategorySerializer(categories, many=True).data)

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Ajouter une catégorie",
        request=serializers.CategorySerializer,
        responses={
            201: serializers.CategorySerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 LIMIT_REACHED"),
        },
    )
    def post(self, request):
        serializer = serializers.CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(request.shop, serializer.validated_data)
        return Response(
            serializers.CategorySerializer(_get_category(request, category.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class CategoryDetailView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Modifier une catégorie",
        request=serializers.CategorySerializer(partial=True),
        responses={
            200: serializers.CategorySerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "404 NOT_FOUND"),
        },
    )
    def patch(self, request, pk: int):
        category = _get_category(request, pk)
        serializer = serializers.CategorySerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_category(category, serializer.validated_data)
        return Response(serializers.CategorySerializer(_get_category(request, pk)).data)

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Supprimer une catégorie",
        description="Les produits de la catégorie deviennent sans catégorie (RG-32).",
        responses={204: None, **error_responses(*SHOP_ERRORS, "404 NOT_FOUND")},
    )
    def delete(self, request, pk: int):
        services.delete_category(_get_category(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Produits ---------------------------------------------------------------------
PRODUCT_WRITE_ERRORS = ("400 VALIDATION_ERROR", *SHOP_ERRORS, "413 FILE_TOO_LARGE")


def _get_product(request, pk: int) -> Product:
    """Produit de la boutique connectee ; celui d'une autre boutique renvoie 404."""
    return get_object_or_404(selectors.get_shop_products(request.shop), pk=pk)


def _product_response(request, pk: int, http_status: int = status.HTTP_200_OK) -> Response:
    """Relit le produit (categorie comprise) et le renvoie au format `Product`."""
    product = _get_product(request, pk)
    data = serializers.ProductSerializer(product, context={"request": request}).data
    return Response(data, status=http_status)


class ProductListCreateView(ListAPIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = serializers.ProductSerializer
    # Filtres stricts (400 sur une valeur invalide) ; tri compris (`ordering`).
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProductFilterSet

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Generation du schema Swagger : aucune boutique connectee.
            return Product.objects.none()
        return selectors.get_shop_products(self.request.shop)

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Mes produits",
        description="Page de produits de la boutique, brouillons compris. Les filtres se "
        "combinent (ET logique) ; une valeur invalide renvoie 400 VALIDATION_ERROR. Tri par "
        "défaut : du plus récent au plus ancien.",
        parameters=[
            OpenApiParameter(
                "import_job",
                int,
                description="Identifiant d'un import (entier ≥ 1) : produits issus de cet import "
                "(liste 1 : `?status=DRAFT&import_job=12`).",
            ),
            OpenApiParameter("min_price", int, description="Prix minimum, inclus (entier ≥ 0)."),
            OpenApiParameter(
                "max_price",
                int,
                description="Prix maximum, inclus (entier ≥ 0) ; `min_price > max_price` → 400.",
            ),
        ],
        responses={
            200: serializers.ProductSerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "404 NOT_FOUND"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Ajouter un produit",
        request={"multipart/form-data": serializers.ProductWriteSerializer},
        responses={
            201: serializers.ProductSerializer,
            **error_responses(*PRODUCT_WRITE_ERRORS, "409 LIMIT_REACHED"),
        },
    )
    def post(self, request):
        serializer = serializers.ProductWriteSerializer(
            data=request.data, context={"shop": request.shop}
        )
        serializer.is_valid(raise_exception=True)
        product = services.create_product_from_data(
            request.shop, serializer.product_fields(), serializer.validated_data["image"]
        )
        return _product_response(request, product.pk, status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Détail d'un produit",
        responses={
            200: serializers.ProductSerializer,
            **error_responses(*SHOP_ERRORS, "404 NOT_FOUND"),
        },
    )
    def get(self, request, pk: int):
        return _product_response(request, pk)

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Modifier un produit",
        description="Mêmes champs que la création, tous facultatifs. JSON accepté si aucune "
        "image n'est envoyée.",
        request={
            "multipart/form-data": serializers.ProductWriteSerializer(partial=True),
            "application/json": serializers.ProductWriteSerializer(partial=True),
        },
        responses={
            200: serializers.ProductSerializer,
            **error_responses(*PRODUCT_WRITE_ERRORS, "404 NOT_FOUND"),
        },
    )
    def patch(self, request, pk: int):
        product = _get_product(request, pk)
        serializer = serializers.ProductWriteSerializer(
            data=request.data, partial=True, context={"shop": request.shop}
        )
        serializer.is_valid(raise_exception=True)
        services.update_product(
            product, serializer.product_fields(), serializer.validated_data.get("image")
        )
        return _product_response(request, pk)

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Supprimer un produit",
        description="Suppression définitive ; les commandes gardent leurs copies.",
        responses={204: None, **error_responses(*SHOP_ERRORS, "404 NOT_FOUND")},
    )
    def delete(self, request, pk: int):
        services.delete_product(_get_product(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
