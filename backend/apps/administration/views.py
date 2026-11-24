"""Vues du dashboard administrateur et informations publiques de la plateforme.

Voir 03-reference-api.md sections 10 (platform-info) et 11. Tous les endpoints
/admin/ exigent role = ADMIN (IsPlatformAdmin) : une boutique recoit
403 PERMISSION_DENIED.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.core.models import PlatformSettings
from apps.core.openapi import error_responses
from apps.core.permissions import IsPlatformAdmin
from apps.core.storage import private_file_response
from apps.core.whatsapp import build_whatsapp_url
from apps.shops.models import Shop, ShopState

from . import selectors, serializers, services

TAG_DASHBOARD = "Admin - Tableau de bord"
TAG_SHOPS = "Admin - Boutiques"
TAG_RECHARGES = "Admin - Recharges"
TAG_PRODUCTS = "Admin - Moderation"
TAG_SETTINGS = "Admin - Parametres"
TAG_AUDIT = "Admin - Journal d'audit"
TAG_PLATFORM = "Public - Plateforme"

ADMIN_ERRORS = ("401 AUTHENTICATION_REQUIRED", "401 TOKEN_INVALID", "403 PERMISSION_DENIED")
SHOP_ERRORS = (*ADMIN_ERRORS, "404 NOT_FOUND")
ID_CARD_FIELDS = {"front": "id_card_front", "back": "id_card_back"}

SHOP_ID = OpenApiParameter(
    "pk", int, OpenApiParameter.PATH, description="Identifiant de la boutique"
)
DATE_PARAMS = [
    OpenApiParameter("date_from", OpenApiTypes.DATE, description="AAAA-MM-JJ, inclus"),
    OpenApiParameter("date_to", OpenApiTypes.DATE, description="AAAA-MM-JJ, inclus"),
]


def _query(serializer_class, request) -> dict:
    """Valide les parametres de la requete ; une valeur invalide renvoie 400."""
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _get_shop(pk: int) -> Shop:
    return get_object_or_404(selectors.shop_detail_queryset(), pk=pk)


def _detail_response(request, shop: Shop) -> Response:
    shop = _get_shop(shop.pk)
    data = serializers.AdminShopDetailSerializer(shop, context={"request": request}).data
    return Response(data)


class AdminAPIView(APIView):
    permission_classes = [IsPlatformAdmin]


class AdminListAPIView(ListAPIView):
    permission_classes = [IsPlatformAdmin]
    filter_backends: list = []


# --- Tableau de bord ----------------------------------------------------------------
class DashboardView(AdminAPIView):
    @extend_schema(
        tags=[TAG_DASHBOARD],
        summary="Tableau de bord administrateur",
        responses={200: serializers.AdminDashboardSerializer, **error_responses(*ADMIN_ERRORS)},
    )
    def get(self, request):
        now = timezone.now()
        context = {"request": request}
        data = {
            "shops": selectors.shop_state_counts(now),
            "expiring_soon": serializers.ExpiringShopSerializer(
                selectors.expiring_soon_shops(now), many=True, context=context
            ).data,
            "recharges": selectors.month_recharges(now),
            "latest_submissions": serializers.SubmissionSerializer(
                selectors.latest_submissions(now), many=True, context=context
            ).data,
        }
        return Response(data)


# --- Boutiques ----------------------------------------------------------------------
class ShopListView(AdminListAPIView):
    """Liste paginee, filtrable par etat calcule, recherche insensible aux accents."""

    serializer_class = serializers.AdminShopSummarySerializer

    def get_queryset(self):
        params = _query(serializers.AdminShopListQuerySerializer, self.request)
        return selectors.admin_shops(
            states=params.get("state"),
            search=params.get("search", ""),
            ordering=params["ordering"],
        )

    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Liste des boutiques",
        parameters=[
            OpenApiParameter(
                "state",
                str,
                description="Etats separes par des virgules : "
                + ", ".join(ShopState.values)
                + ". Ex. ACTIVE,EXPIRED",
            ),
            OpenApiParameter(
                "search", str, description="Nom, e-mail, telephone ou nom du proprietaire"
            ),
            OpenApiParameter("ordering", str, enum=list(selectors.SHOP_ORDERINGS)),
        ],
        responses={
            200: serializers.AdminShopSummarySerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ShopDetailView(AdminAPIView):
    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Fiche complete d'une boutique",
        parameters=[SHOP_ID],
        responses={200: serializers.AdminShopDetailSerializer, **error_responses(*SHOP_ERRORS)},
    )
    def get(self, request, pk: int):
        shop = _get_shop(pk)
        return Response(
            serializers.AdminShopDetailSerializer(shop, context={"request": request}).data
        )


class ShopIdCardView(AdminAPIView):
    """Fichier prive de la carte d'identite (Cache-Control: private, no-store)."""

    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Lire une face de la carte d'identite d'une boutique",
        parameters=[
            SHOP_ID,
            OpenApiParameter("side", str, OpenApiParameter.PATH, enum=["front", "back"]),
        ],
        responses={(200, "image/*"): OpenApiTypes.BINARY, **error_responses(*SHOP_ERRORS)},
    )
    def get(self, request, pk: int, side: str):
        field_name = ID_CARD_FIELDS.get(side)
        if field_name is None:
            raise NotFound()
        shop = get_object_or_404(Shop, pk=pk)
        field_file = getattr(shop, field_name)
        if not field_file or not field_file.storage.exists(field_file.name):
            raise NotFound()
        return private_file_response(field_file)


class ApproveShopView(AdminAPIView):
    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Valider une boutique",
        parameters=[SHOP_ID],
        request=None,
        responses={
            200: serializers.AdminShopDetailSerializer,
            **error_responses(*SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request, pk: int):
        shop = services.approve_shop(_get_shop(pk), admin=request.user, request=request)
        return _detail_response(request, shop)


class RejectShopView(AdminAPIView):
    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Refuser une boutique",
        parameters=[SHOP_ID],
        request=serializers.RejectSerializer,
        responses={
            200: serializers.AdminShopDetailSerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request, pk: int):
        shop = _get_shop(pk)
        serializer = serializers.RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.reject_shop(
            shop, admin=request.user, reason=serializer.validated_data["reason"], request=request
        )
        return _detail_response(request, shop)


class BlockShopView(AdminAPIView):
    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Bloquer une boutique",
        parameters=[SHOP_ID],
        request=serializers.ReasonSerializer,
        responses={
            200: serializers.AdminShopDetailSerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request, pk: int):
        shop = _get_shop(pk)
        serializer = serializers.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.block_shop(
            shop, admin=request.user, reason=serializer.validated_data["reason"], request=request
        )
        return _detail_response(request, shop)


class UnblockShopView(AdminAPIView):
    @extend_schema(
        tags=[TAG_SHOPS],
        summary="Debloquer une boutique",
        parameters=[SHOP_ID],
        request=None,
        responses={
            200: serializers.AdminShopDetailSerializer,
            **error_responses(*SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request, pk: int):
        shop = services.unblock_shop(_get_shop(pk), admin=request.user, request=request)
        return _detail_response(request, shop)


# --- Recharges ----------------------------------------------------------------------
class RechargePreviewView(AdminAPIView):
    @extend_schema(
        tags=[TAG_RECHARGES],
        summary="Apercu de la nouvelle date d'expiration (rien n'est enregistre)",
        parameters=[
            SHOP_ID,
            OpenApiParameter("duration_months", int, description="1 a 120"),
            OpenApiParameter("target_date", OpenApiTypes.DATE, description="AAAA-MM-JJ"),
        ],
        responses={
            200: serializers.RechargePreviewSerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def get(self, request, pk: int):
        shop = _get_shop(pk)
        params = _query(serializers.RechargeModeSerializer, request)
        computation = services.compute_new_expiry(shop, **params)
        return Response(serializers.RechargePreviewSerializer(computation).data)


class RechargeShopView(AdminAPIView):
    @extend_schema(
        tags=[TAG_RECHARGES],
        summary="Charger le compte d'une boutique",
        parameters=[SHOP_ID],
        request=serializers.RechargeCreateSerializer,
        responses={
            201: serializers.RechargeResultSerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request, pk: int):
        shop = _get_shop(pk)
        serializer = serializers.RechargeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recharge = services.recharge_shop(
            shop, admin=request.user, request=request, **serializer.validated_data
        )
        context = {"request": request}
        data = {
            "recharge": serializers.RechargeSerializer(recharge, context=context).data,
            "shop": serializers.AdminShopSummarySerializer(_get_shop(pk), context=context).data,
        }
        return Response(data, status=status.HTTP_201_CREATED)


class ShopRechargeListView(AdminListAPIView):
    serializer_class = serializers.RechargeSerializer

    def get_queryset(self):
        shop = get_object_or_404(Shop, pk=self.kwargs["pk"])
        return selectors.recharges(shop_id=shop.pk)

    @extend_schema(
        tags=[TAG_RECHARGES],
        summary="Historique des recharges d'une boutique",
        parameters=[SHOP_ID],
        responses={
            200: serializers.RechargeSerializer(many=True),
            **error_responses(*SHOP_ERRORS),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class RechargeListView(AdminListAPIView):
    serializer_class = serializers.RechargeWithShopSerializer

    def get_queryset(self):
        params = _query(serializers.RechargeListQuerySerializer, self.request)
        return selectors.recharges(
            shop_id=params.get("shop"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
        )

    @extend_schema(
        tags=[TAG_RECHARGES],
        summary="Toutes les recharges",
        parameters=[
            OpenApiParameter("shop", int, description="Identifiant de la boutique"),
            *DATE_PARAMS,
        ],
        responses={
            200: serializers.RechargeWithShopSerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# --- Produits (moderation) ----------------------------------------------------------
class ShopProductListView(AdminListAPIView):
    serializer_class = serializers.AdminProductSerializer

    def get_queryset(self):
        shop = get_object_or_404(Shop, pk=self.kwargs["pk"])
        params = _query(serializers.ProductListQuerySerializer, self.request)
        return selectors.shop_products(shop, params)

    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Produits d'une boutique (moderation)",
        parameters=[
            SHOP_ID,
            OpenApiParameter("search", str),
            OpenApiParameter("category", int),
            OpenApiParameter("uncategorized", str, enum=["true"]),
            OpenApiParameter("status", str, enum=Product.Status.values),
            OpenApiParameter("is_available", str, enum=["true", "false"]),
            OpenApiParameter("source", str, enum=Product.Source.values),
            OpenApiParameter("import_job", int),
            OpenApiParameter("min_price", int),
            OpenApiParameter("max_price", int),
            OpenApiParameter("ordering", str, enum=list(selectors.PRODUCT_ORDERINGS)),
        ],
        responses={
            200: serializers.AdminProductSerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class RemoveProductView(AdminAPIView):
    @extend_schema(
        tags=[TAG_PRODUCTS],
        summary="Retirer un produit interdit",
        parameters=[
            SHOP_ID,
            OpenApiParameter("product_id", int, OpenApiParameter.PATH),
        ],
        request=serializers.ReasonSerializer,
        responses={204: None, **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS)},
    )
    def post(self, request, pk: int, product_id: int):
        shop = get_object_or_404(Shop, pk=pk)
        product = get_object_or_404(Product, pk=product_id, shop=shop)
        serializer = serializers.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.remove_product(
            product, admin=request.user, reason=serializer.validated_data["reason"], request=request
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Parametres ---------------------------------------------------------------------
class PlatformSettingsView(AdminAPIView):
    @staticmethod
    def _current() -> PlatformSettings:
        return PlatformSettings.objects.select_related("updated_by").get(
            pk=PlatformSettings.SINGLETON_ID
        )

    @extend_schema(
        tags=[TAG_SETTINGS],
        summary="Parametres de la plateforme",
        responses={200: serializers.PlatformSettingsSerializer, **error_responses(*ADMIN_ERRORS)},
    )
    def get(self, request):
        PlatformSettings.load()  # cree la ligne si la base a ete videe a la main
        return Response(serializers.PlatformSettingsSerializer(self._current()).data)

    @extend_schema(
        tags=[TAG_SETTINGS],
        summary="Modifier les parametres de la plateforme",
        request=serializers.PlatformSettingsSerializer,
        responses={
            200: serializers.PlatformSettingsSerializer,
            **error_responses("400 VALIDATION_ERROR", *ADMIN_ERRORS),
        },
    )
    def patch(self, request):
        PlatformSettings.load()
        serializer = serializers.PlatformSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_platform_settings(
            admin=request.user, fields=dict(serializer.validated_data), request=request
        )
        return Response(serializers.PlatformSettingsSerializer(self._current()).data)


# --- Journal d'audit ----------------------------------------------------------------
class AuditLogListView(AdminListAPIView):
    serializer_class = serializers.AuditLogSerializer

    def get_queryset(self):
        params = _query(serializers.AuditLogQuerySerializer, self.request)
        return selectors.audit_logs(
            action=params.get("action"),
            actor_id=params.get("actor"),
            target_type=params.get("target_type"),
            target_id=params.get("target_id"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
        )

    @extend_schema(
        tags=[TAG_AUDIT],
        summary="Journal d'audit",
        parameters=[
            OpenApiParameter("action", str),
            OpenApiParameter("actor", int, description="Identifiant de l'utilisateur"),
            OpenApiParameter("target_type", str, description="Ex. shop, product"),
            OpenApiParameter("target_id", int),
            *DATE_PARAMS,
        ],
        responses={
            200: serializers.AuditLogSerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# --- Public -------------------------------------------------------------------------
class PlatformInfoView(APIView):
    """Contact de l'administrateur et acompte : page « compte expire » et en-tete du site."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        tags=[TAG_PLATFORM],
        summary="Informations publiques de la plateforme",
        responses={200: serializers.PlatformInfoSerializer},
    )
    def get(self, request):
        platform = PlatformSettings.load()
        whatsapp = platform.admin_whatsapp
        data = {
            "admin_whatsapp": whatsapp,
            "admin_whatsapp_url": build_whatsapp_url(whatsapp) if whatsapp else "",
            "admin_contact_email": platform.admin_contact_email,
            "deposit_percent": platform.deposit_percent,
        }
        return Response(serializers.PlatformInfoSerializer(data).data)
