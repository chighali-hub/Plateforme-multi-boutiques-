"""Dashboard admin : liste, fiche, carte d'identite et actions sur les boutiques.

Voir 03-reference-api.md section 11 (RG-10 a RG-15).
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.tests.helpers import error_code
from apps.accounts.tokens import issue_tokens
from apps.administration.tests.factories import RechargeFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditAction, AuditLog
from apps.notifications.models import Notification, NotificationType
from apps.orders.tests.factories import OrderFactory
from apps.shops.models import Shop
from apps.shops.tests.factories import BankAccountFactory

pytestmark = pytest.mark.django_db
SHOPS = "/api/v1/admin/shops/"
DASHBOARD = "/api/v1/admin/dashboard/"
STATES = ("ONBOARDING", "PENDING", "REJECTED", "ACTIVE", "EXPIRED", "BLOCKED")


def _url(shop, action=""):
    return f"{SHOPS}{shop.pk}/{action + '/' if action else ''}"


def _ids(response):
    return {item["id"] for item in response.json()["results"]}


@pytest.fixture
def one_shop_per_state(make_shop):
    return {state: make_shop(state) for state in STATES}


# --- Tableau de bord ----------------------------------------------------------------
def test_dashboard_counts_shops_by_state(admin_client, one_shop_per_state, make_shop):
    make_shop("ACTIVE")
    now = timezone.now()
    RechargeFactory(shop=one_shop_per_state["ACTIVE"], amount_received=5000)
    RechargeFactory(shop=one_shop_per_state["ACTIVE"], amount_received=None)
    old = RechargeFactory(shop=one_shop_per_state["ACTIVE"], amount_received=7000)
    from apps.administration.models import Recharge

    Recharge.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=62))

    response = admin_client.get(DASHBOARD)

    assert response.status_code == 200
    body = response.json()
    assert body["shops"] == {
        "onboarding": 1,
        "pending": 1,
        "active": 2,
        "rejected": 1,
        "expired": 1,
        "blocked": 1,
        "total": 7,
    }
    assert body["recharges"]["count"] == 2
    assert body["recharges"]["amount_received"] == 5000
    assert len(body["recharges"]["month"]) == 7
    assert [item["id"] for item in body["latest_submissions"]] == [one_shop_per_state["PENDING"].pk]


def test_dashboard_lists_expiring_shops_most_urgent_first(admin_client, make_shop):
    now = timezone.now()
    later = make_shop("ACTIVE", expires_at=now + timedelta(days=6))
    sooner = make_shop("ACTIVE", expires_at=now + timedelta(days=1, hours=2))
    make_shop("ACTIVE", expires_at=now + timedelta(days=9))
    make_shop("BLOCKED", expires_at=now + timedelta(days=2))

    items = admin_client.get(DASHBOARD).json()["expiring_soon"]

    assert [item["id"] for item in items] == [sooner.pk, later.pk]
    assert items[0]["days_left"] == 2
    assert items[0]["whatsapp_url"] == f"https://wa.me/222{sooner.whatsapp}"
    assert set(items[0]) == {
        "id",
        "name",
        "logo_url",
        "phone",
        "whatsapp_url",
        "expires_at",
        "days_left",
    }


# --- Liste --------------------------------------------------------------------------
@pytest.mark.parametrize("state", STATES)
def test_shop_list_filters_each_state(admin_client, one_shop_per_state, state):
    response = admin_client.get(SHOPS, {"state": state})

    assert response.status_code == 200
    assert _ids(response) == {one_shop_per_state[state].pk}
    assert response.json()["results"][0]["state"] == state


@pytest.mark.parametrize(
    "value, expected",
    [
        ("ACTIVE,EXPIRED", {"ACTIVE", "EXPIRED"}),
        ("pending, rejected", {"PENDING", "REJECTED"}),
        ("BLOCKED,ONBOARDING,ACTIVE", {"BLOCKED", "ONBOARDING", "ACTIVE"}),
        ("", set(STATES)),
    ],
)
def test_shop_list_filters_state_combinations(admin_client, one_shop_per_state, value, expected):
    response = admin_client.get(SHOPS, {"state": value})

    assert _ids(response) == {one_shop_per_state[state].pk for state in expected}


def test_shop_list_unknown_state_returns_400(admin_client):
    response = admin_client.get(SHOPS, {"state": "ACTIVE,DELETED"})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "state" in response.json()["error"]["details"]


def test_shop_list_item_format(admin_client, make_shop):
    shop = make_shop("ACTIVE")

    item = admin_client.get(SHOPS).json()["results"][0]

    assert set(item) == {
        "id",
        "name",
        "slug",
        "logo_url",
        "owner_full_name",
        "email",
        "phone",
        "state",
        "is_blocked",
        "submitted_at",
        "approved_at",
        "expires_at",
        "days_left",
        "created_at",
    }
    assert item["email"] == shop.owner.email
    assert item["logo_url"].startswith("http://testserver/media/")
    assert item["days_left"] == 30


@pytest.mark.parametrize(
    "term",
    ["aicha", "AÏCHA", "mint ahmed", "aicha-mode@example", "4455", "AICHA-MODE@EXAMPLE.COM"],
)
def test_shop_list_search_ignores_case_and_accents(admin_client, make_shop, term):
    from apps.accounts.tests.factories import UserFactory

    shop = make_shop(
        "PENDING",
        name="Aïcha Mode",
        owner_full_name="Aïcha Mint Ahmed",
        phone="22334455",
        owner=UserFactory(email="aicha-mode@example.com"),
    )
    make_shop("PENDING", name="TechShop")

    assert _ids(admin_client.get(SHOPS, {"search": term})) == {shop.pk}


def test_shop_list_default_ordering_puts_unsubmitted_last(admin_client, make_shop):
    now = timezone.now()
    onboarding = make_shop("ONBOARDING")
    old = make_shop("PENDING", submitted_at=now - timedelta(days=2))
    recent = make_shop("PENDING", submitted_at=now)

    ids = [item["id"] for item in admin_client.get(SHOPS).json()["results"]]

    assert ids == [recent.pk, old.pk, onboarding.pk]


def test_shop_list_ordering_by_expiry(admin_client, make_shop):
    now = timezone.now()
    late = make_shop("ACTIVE", expires_at=now + timedelta(days=60))
    soon = make_shop("ACTIVE", expires_at=now + timedelta(days=2))
    pending = make_shop("PENDING")

    ids = [
        item["id"] for item in admin_client.get(SHOPS, {"ordering": "expires_at"}).json()["results"]
    ]
    desc = admin_client.get(SHOPS, {"ordering": "-expires_at"}).json()["results"]

    assert ids == [soon.pk, late.pk, pending.pk]
    assert [item["id"] for item in desc] == [late.pk, soon.pk, pending.pk]


def test_shop_list_invalid_ordering_returns_400(admin_client):
    response = admin_client.get(SHOPS, {"ordering": "owner__password"})
    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"


def test_shop_list_query_count_is_constant(admin_client, make_shop, django_assert_max_num_queries):
    make_shop("ACTIVE")
    with django_assert_max_num_queries(4):
        admin_client.get(SHOPS)
    for _ in range(25):
        make_shop("ACTIVE")
    with django_assert_max_num_queries(4):
        response = admin_client.get(SHOPS, {"page_size": 100})
    assert response.json()["count"] == 26


# --- Fiche --------------------------------------------------------------------------
def test_shop_detail_contains_full_profile(admin_client, admin_user, make_shop):
    shop = make_shop("ACTIVE", approved_by=admin_user)
    BankAccountFactory(shop=shop, bank_name="Bankily", payment_code="22334455")
    ProductFactory(shop=shop)
    ProductFactory(shop=shop, status=Product.Status.DRAFT)
    OrderFactory(shop=shop, status="DELIVERED", delivered_at=timezone.now(), total_amount=6000)
    OrderFactory(shop=shop, total_amount=1000)

    response = admin_client.get(_url(shop))

    assert response.status_code == 200
    body = response.json()
    assert body["approved_by"] == {"id": admin_user.pk, "email": admin_user.email}
    assert body["id_card_front_url"] == f"http://testserver{SHOPS}{shop.pk}/id-card/front/"
    assert body["id_card_back_url"] == f"http://testserver{SHOPS}{shop.pk}/id-card/back/"
    assert body["banks"] == [
        {"id": shop.bank_accounts.get().pk, "bank_name": "Bankily", "payment_code": "22334455"}
    ]
    assert body["stats"] == {
        "products_published": 1,
        "products_draft": 1,
        "orders_total": 2,
        "orders_delivered": 1,
        "revenue_delivered_total": 6000,
    }
    assert body["theme"]["code"] == "classique"
    assert body["whatsapp_url"] == f"https://wa.me/222{shop.whatsapp}"
    for field in ("description_fr", "description_ar", "address", "onboarding_step", "status"):
        assert field in body
    assert body["recent_audit"] == []


def test_shop_detail_unknown_shop_returns_404(admin_client):
    response = admin_client.get(f"{SHOPS}999999/")
    assert response.status_code == 404 and error_code(response) == "NOT_FOUND"


def test_shop_detail_recent_audit_includes_shop_actions(admin_client, make_shop):
    shop = make_shop("PENDING")
    admin_client.post(_url(shop, "approve"))
    admin_client.post(_url(shop, "block"), {"reason": "Fraude signalee."}, format="json")

    audit = admin_client.get(_url(shop)).json()["recent_audit"]

    assert [entry["action"] for entry in audit] == ["SHOP_BLOCKED", "SHOP_APPROVED"]
    assert audit[0]["actor_email"] == admin_client.user.email


# --- Carte d'identite ---------------------------------------------------------------
@pytest.fixture
def shop_with_id_card(make_shop, image_file):
    shop = make_shop("PENDING")
    shop.id_card_front.save("recto.jpg", image_file(), save=False)
    shop.id_card_back.save("verso.png", image_file(fmt="PNG"), save=True)
    return shop


@pytest.mark.parametrize("side, content_type", [("front", "image/jpeg"), ("back", "image/png")])
def test_admin_reads_id_card(admin_client, shop_with_id_card, side, content_type):
    response = admin_client.get(f"{_url(shop_with_id_card)}id-card/{side}/")

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Cache-Control"] == "private, no-store"


def test_id_card_unknown_side_or_missing_file_returns_404(
    admin_client, shop_with_id_card, make_shop
):
    assert admin_client.get(f"{_url(shop_with_id_card)}id-card/side/").status_code == 404
    missing = make_shop("PENDING")
    assert admin_client.get(f"{_url(missing)}id-card/front/").status_code == 404
    assert admin_client.get(f"{SHOPS}999999/id-card/front/").status_code == 404


def test_shop_cannot_read_id_card_through_admin_route(shop_client, shop_with_id_card):
    response = shop_client.get(f"{_url(shop_with_id_card)}id-card/front/")
    assert response.status_code == 403 and error_code(response) == "PERMISSION_DENIED"


# --- Validation et refus (RG-10 a RG-12) --------------------------------------------
def test_approve_pending_shop(admin_client, make_shop, django_capture_on_commit_callbacks):
    shop = make_shop("PENDING", rejection_reason="Ancien motif.")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(_url(shop, "approve"))

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ACTIVE" and body["status"] == "APPROVED"
    assert body["rejection_reason"] == "" and body["days_left"] in (30, 31)
    shop.refresh_from_db()
    assert shop.approved_by == admin_client.user and shop.approved_at is not None
    assert Notification.objects.filter(
        recipient=shop.owner, type=NotificationType.SHOP_APPROVED
    ).exists()
    entry = AuditLog.objects.get(action=AuditAction.SHOP_APPROVED)
    assert (entry.actor, entry.target_type, entry.target_id) == (admin_client.user, "shop", shop.pk)
    assert entry.ip_address == "127.0.0.1"
    message = mail.outbox[-1]
    assert message.to == [shop.owner.email]
    assert shop.name in message.body and "/" in message.subject


@pytest.mark.parametrize("state", ["ONBOARDING", "REJECTED", "ACTIVE", "EXPIRED", "BLOCKED"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_approve_or_reject_requires_pending(admin_client, make_shop, state, action):
    shop = make_shop(state)
    before = (shop.status, shop.expires_at)

    response = admin_client.post(_url(shop, action), {"reason": "Motif suffisamment long."})

    assert response.status_code == 409
    assert error_code(response) == "INVALID_STATE_TRANSITION"
    assert response.json()["error"]["details"] == {"current_state": state}
    shop.refresh_from_db()
    assert (shop.status, shop.expires_at) == before
    assert not AuditLog.objects.exists()


def test_reject_pending_shop(admin_client, make_shop, django_capture_on_commit_callbacks):
    shop = make_shop("PENDING")
    reason = "Votre carte d'identité n'est pas lisible."

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(_url(shop, "reject"), {"reason": reason}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "REJECTED" and body["rejection_reason"] == reason
    assert body["rejected_at"] is not None
    notification = Notification.objects.get(recipient=shop.owner)
    assert notification.type == NotificationType.SHOP_REJECTED
    assert notification.data == {"reason": reason}
    assert AuditLog.objects.get(action=AuditAction.SHOP_REJECTED).metadata == {"reason": reason}
    assert reason in mail.outbox[-1].body


@pytest.mark.parametrize("reason", ["", "x" * 9, "x" * 501])
def test_reject_reason_length_is_validated(admin_client, make_shop, reason):
    shop = make_shop("PENDING")

    response = admin_client.post(_url(shop, "reject"), {"reason": reason}, format="json")

    assert response.status_code == 400
    assert "reason" in response.json()["error"]["details"]
    shop.refresh_from_db()
    assert shop.status == Shop.Status.PENDING


def test_rejected_shop_resubmits_then_can_be_approved(admin_client, make_shop_client):
    client = make_shop_client("PENDING")
    shop = client.shop
    admin_client.post(_url(shop, "reject"), {"reason": "Carte illisible, merci."}, format="json")

    assert client.post("/api/v1/shop/me/resubmit/").status_code == 200
    response = admin_client.post(_url(shop, "approve"))

    assert response.status_code == 200 and response.json()["state"] == "ACTIVE"


# --- Blocage (RG-14) ----------------------------------------------------------------
@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED", "ACTIVE", "EXPIRED"])
def test_block_any_unblocked_shop(
    admin_client, make_shop, state, django_capture_on_commit_callbacks
):
    shop = make_shop(state)

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(_url(shop, "block"), {"reason": "Fraude"}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "BLOCKED" and body["is_blocked"] is True
    assert body["block_reason"] == "Fraude" and body["blocked_at"] is not None
    entry = AuditLog.objects.get(action=AuditAction.SHOP_BLOCKED)
    assert entry.metadata["previous_state"] == state
    assert "Fraude" in mail.outbox[-1].body
    assert not Notification.objects.filter(recipient=shop.owner).exists()


def test_block_already_blocked_shop_returns_409(admin_client, make_shop):
    shop = make_shop("BLOCKED")

    response = admin_client.post(_url(shop, "block"), {"reason": "Encore"}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"current_state": "BLOCKED"}


@pytest.mark.parametrize("reason", ["", "abcd", "x" * 501])
def test_block_reason_length_is_validated(admin_client, make_shop, reason):
    shop = make_shop("ACTIVE")

    response = admin_client.post(_url(shop, "block"), {"reason": reason}, format="json")

    assert response.status_code == 400
    shop.refresh_from_db()
    assert shop.is_blocked is False


def test_block_closes_shop_sessions(admin_client, api_client, make_shop):
    shop = make_shop("ACTIVE")
    tokens = issue_tokens(shop.owner)

    admin_client.post(_url(shop, "block"), {"reason": "Fraude"}, format="json")
    blocked = api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
    admin_client.post(_url(shop, "unblock"))
    after_unblock = api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})

    assert blocked.status_code in (401, 403)
    # Le jeton a ete revoque au blocage : il reste refuse apres le deblocage.
    assert after_unblock.status_code == 401 and error_code(after_unblock) == "TOKEN_INVALID"


def test_blocked_shop_is_refused_on_next_request(admin_client, make_shop_client):
    client = make_shop_client("ACTIVE")
    admin_client.post(_url(client.shop, "block"), {"reason": "Fraude"}, format="json")

    response = client.get("/api/v1/shop/me/")

    assert response.status_code == 403 and error_code(response) == "SHOP_BLOCKED"


# --- Deblocage ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "base_state, restored",
    [("ACTIVE", "ACTIVE"), ("EXPIRED", "EXPIRED"), ("PENDING", "PENDING")],
)
def test_unblock_restores_previous_state(
    admin_client, make_shop, base_state, restored, django_capture_on_commit_callbacks
):
    shop = make_shop(base_state)
    expires_at = shop.expires_at
    admin_client.post(_url(shop, "block"), {"reason": "Verification"}, format="json")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(_url(shop, "unblock"))

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == restored
    assert body["block_reason"] == "" and body["blocked_at"] is None
    shop.refresh_from_db()
    assert shop.expires_at == expires_at and shop.is_blocked is False
    assert Notification.objects.filter(
        recipient=shop.owner, type=NotificationType.SHOP_UNBLOCKED
    ).exists()
    entry = AuditLog.objects.get(action=AuditAction.SHOP_UNBLOCKED)
    assert entry.metadata["previous_block_reason"] == "Verification"
    assert mail.outbox[-1].to == [shop.owner.email]


def test_unblock_not_blocked_shop_returns_409(admin_client, make_shop):
    response = admin_client.post(_url(make_shop("ACTIVE"), "unblock"))

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"current_state": "ACTIVE"}


def test_action_on_unknown_shop_returns_404(admin_client):
    for action in ("approve", "unblock"):
        assert admin_client.post(f"{SHOPS}999999/{action}/").status_code == 404


def test_shop_data_kept_after_block(admin_client, make_shop):
    shop = make_shop("ACTIVE")
    ProductFactory(shop=shop)
    BankAccountFactory(shop=shop)

    admin_client.post(_url(shop, "block"), {"reason": "Fraude"}, format="json")

    assert Product.objects.filter(shop=shop).count() == 1
    assert shop.bank_accounts.count() == 1


def test_email_is_bilingual(admin_client, make_shop, django_capture_on_commit_callbacks):
    shop = make_shop("PENDING")

    with django_capture_on_commit_callbacks(execute=True):
        admin_client.post(
            _url(shop, "reject"), {"reason": "Carte d'identité floue."}, format="json"
        )

    body = mail.outbox[-1].body
    assert "Bonjour" in body and "السبب" in body
    assert "Carte d'identité floue." in body  # pas d'echappement HTML


def test_requests_from_unauthenticated_client_return_401(make_shop):
    response = APIClient().post(_url(make_shop("PENDING"), "approve"))
    assert response.status_code == 401 and error_code(response) == "AUTHENTICATION_REQUIRED"
