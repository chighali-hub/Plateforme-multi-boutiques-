"""Routes de l'application Boutiques.

Voir docs/Documentation-API/03-reference-api.md section 5.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("public/themes/", views.ThemeListView.as_view(), name="shops-themes-list"),
    path(
        "shop/onboarding/design/",
        views.OnboardingDesignView.as_view(),
        name="shops-onboarding-design",
    ),
    path(
        "shop/onboarding/accept-terms/",
        views.OnboardingAcceptTermsView.as_view(),
        name="shops-onboarding-accept-terms",
    ),
    path("shop/me/", views.ShopMeView.as_view(), name="shops-me"),
    path("shop/me/design/", views.ShopDesignView.as_view(), name="shops-me-design"),
    path("shop/me/id-card/", views.IdCardUpdateView.as_view(), name="shops-me-id-card-update"),
    path(
        "shop/me/id-card/<str:side>/",
        views.IdCardFileView.as_view(),
        name="shops-me-id-card",
    ),
    path("shop/me/resubmit/", views.ResubmitView.as_view(), name="shops-me-resubmit"),
    path("shop/banks/", views.BankListCreateView.as_view(), name="shops-banks-list"),
    path("shop/banks/<int:pk>/", views.BankDetailView.as_view(), name="shops-banks-detail"),
    path("shop/recharge-info/", views.RechargeInfoView.as_view(), name="shops-recharge-info"),
    path("shop/recharges/", views.ShopRechargeListView.as_view(), name="shops-recharges-list"),
]
