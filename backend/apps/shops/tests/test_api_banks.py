"""Banques de la boutique : CRUD, unicite, limite de 10, isolation (RG-40).

Voir 03-reference-api.md section 5 (Banques).
"""

import pytest

from apps.accounts.tests.helpers import error_code
from apps.shops.models import BankAccount
from apps.shops.tests.factories import BankAccountFactory

pytestmark = pytest.mark.django_db
BANKS = "/api/v1/shop/banks/"


def _detail(bank: BankAccount) -> str:
    return f"{BANKS}{bank.pk}/"


# --- Liste ------------------------------------------------------------------------
def test_list_banks_returns_only_own_banks_unpaginated(shop_client, other_shop_client):
    own = BankAccount.objects.get(shop=shop_client.shop)
    second = BankAccountFactory(shop=shop_client.shop, bank_name="Sedad")

    response = shop_client.get(BANKS)

    assert response.status_code == 200
    body = response.json()
    assert [bank["id"] for bank in body] == [own.id, second.id]
    assert set(body[0]) == {"id", "bank_name", "payment_code", "created_at", "updated_at"}


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 200, None),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_list_banks_by_state(make_shop_client, state, expected_status, expected_code):
    response = make_shop_client(state).get(BANKS)

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


def test_list_banks_query_count_is_constant(shop_client, django_assert_max_num_queries):
    BankAccountFactory.create_batch(9, shop=shop_client.shop)

    with django_assert_max_num_queries(3):
        response = shop_client.get(BANKS)

    assert len(response.json()) == 10


# --- Creation -----------------------------------------------------------------------
def test_create_bank_returns_201(shop_client):
    response = shop_client.post(
        BANKS, {"bank_name": "  Sedad ", "payment_code": " 44556677 "}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["bank_name"], body["payment_code"]) == ("Sedad", "44556677")
    assert BankAccount.objects.filter(shop=shop_client.shop, pk=body["id"]).exists()


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"payment_code": "44556677"}, "bank_name"),
        ({"bank_name": "Sedad"}, "payment_code"),
        ({"bank_name": "S", "payment_code": "44556677"}, "bank_name"),
        ({"bank_name": "x" * 61, "payment_code": "44556677"}, "bank_name"),
        ({"bank_name": "Sedad", "payment_code": "4"}, "payment_code"),
        ({"bank_name": "Sedad", "payment_code": "4" * 41}, "payment_code"),
    ],
)
def test_create_bank_validates_fields(shop_client, payload, field):
    response = shop_client.post(BANKS, payload, format="json")

    assert response.status_code == 400
    assert field in response.json()["error"]["details"]


def test_create_duplicate_bank_is_refused(shop_client):
    existing = BankAccount.objects.get(shop=shop_client.shop)

    response = shop_client.post(
        BANKS,
        {"bank_name": existing.bank_name.upper(), "payment_code": existing.payment_code},
        format="json",
    )

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in response.json()["error"]["details"]
    assert BankAccount.objects.filter(shop=shop_client.shop).count() == 1


def test_same_bank_and_code_allowed_in_another_shop(shop_client, other_shop_client):
    existing = BankAccount.objects.get(shop=shop_client.shop)

    response = other_shop_client.post(
        BANKS,
        {"bank_name": existing.bank_name, "payment_code": existing.payment_code},
        format="json",
    )

    assert response.status_code == 201


def test_eleventh_bank_reaches_the_limit(shop_client):
    BankAccountFactory.create_batch(9, shop=shop_client.shop)

    response = shop_client.post(
        BANKS, {"bank_name": "Click", "payment_code": "99887766"}, format="json"
    )

    assert response.status_code == 409
    assert error_code(response) == "LIMIT_REACHED"
    assert response.json()["error"]["details"] == {"limit": 10}
    assert BankAccount.objects.filter(shop=shop_client.shop).count() == 10


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 201, None),
        ("ACTIVE", 201, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_create_bank_by_state(make_shop_client, state, expected_status, expected_code):
    response = make_shop_client(state).post(
        BANKS, {"bank_name": "Click", "payment_code": "99887766"}, format="json"
    )

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


# --- Modification -------------------------------------------------------------------
def test_update_bank_changes_only_given_fields(shop_client):
    bank = BankAccount.objects.get(shop=shop_client.shop)

    response = shop_client.patch(_detail(bank), {"payment_code": "33445566"}, format="json")

    assert response.status_code == 200
    bank.refresh_from_db()
    assert bank.payment_code == "33445566"
    assert bank.bank_name == "Bankily"


def test_update_bank_into_duplicate_is_refused(shop_client):
    first = BankAccount.objects.get(shop=shop_client.shop)
    second = BankAccountFactory(shop=shop_client.shop, bank_name="Sedad")

    response = shop_client.patch(
        _detail(second),
        {"bank_name": first.bank_name, "payment_code": first.payment_code},
        format="json",
    )

    assert response.status_code == 400
    assert "non_field_errors" in response.json()["error"]["details"]
    second.refresh_from_db()
    assert second.bank_name == "Sedad"


def test_update_bank_keeping_same_values_is_allowed(shop_client):
    bank = BankAccount.objects.get(shop=shop_client.shop)

    response = shop_client.patch(
        _detail(bank),
        {"bank_name": bank.bank_name, "payment_code": bank.payment_code},
        format="json",
    )

    assert response.status_code == 200


def test_update_bank_validates_fields(shop_client):
    bank = BankAccount.objects.get(shop=shop_client.shop)

    response = shop_client.patch(_detail(bank), {"bank_name": "B"}, format="json")

    assert response.status_code == 400
    assert "bank_name" in response.json()["error"]["details"]


# --- Suppression --------------------------------------------------------------------
def test_delete_last_bank_hides_shop_from_public(shop_client):
    bank = BankAccount.objects.get(shop=shop_client.shop)

    response = shop_client.delete(_detail(bank))

    assert response.status_code == 204
    assert not BankAccount.objects.filter(pk=bank.pk).exists()
    assert shop_client.get("/api/v1/shop/me/").json()["is_publicly_visible"] is False


@pytest.mark.parametrize("method", ["patch", "delete"])
@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", None, None),
        ("ACTIVE", None, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_write_bank_by_state(make_shop_client, method, state, expected_status, expected_code):
    client = make_shop_client(state)
    bank = BankAccountFactory(shop=client.shop, bank_name="Masrvi")

    response = getattr(client, method)(_detail(bank), {"payment_code": "11223344"}, format="json")

    if expected_status is None:
        assert response.status_code == (200 if method == "patch" else 204)
    else:
        assert response.status_code == expected_status
        assert error_code(response) == expected_code
        assert BankAccount.objects.filter(pk=bank.pk, payment_code=bank.payment_code).exists()


# --- Isolation ------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_shop_cannot_touch_other_shop_bank(shop_client, other_shop_client, method):
    other_bank = BankAccount.objects.get(shop=other_shop_client.shop)
    before = (other_bank.bank_name, other_bank.payment_code)

    response = getattr(shop_client, method)(
        _detail(other_bank), {"payment_code": "11223344"}, format="json"
    )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    other_bank.refresh_from_db()
    assert (other_bank.bank_name, other_bank.payment_code) == before


def test_unknown_bank_returns_404(shop_client):
    assert shop_client.delete(f"{BANKS}999999/").status_code == 404


def test_banks_refuse_anonymous_and_admin(api_client, admin_client):
    assert error_code(api_client.get(BANKS)) == "AUTHENTICATION_REQUIRED"
    assert error_code(admin_client.get(BANKS)) == "PERMISSION_DENIED"
