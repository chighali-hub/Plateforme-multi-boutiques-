import pytest

from apps.accounts.models import User


@pytest.mark.django_db
def test_create_user_defaults_to_shop_role():
    user = User.objects.create_user(email="Boutique@Example.com", password="motdepasse-solide")
    assert user.email == "boutique@example.com"
    assert user.role == User.Role.SHOP
    assert user.is_shop and not user.is_admin
    assert user.check_password("motdepasse-solide")


@pytest.mark.django_db
def test_create_superuser_is_admin():
    admin = User.objects.create_superuser(email="admin@example.com", password="motdepasse-solide")
    assert admin.role == User.Role.ADMIN
    assert admin.is_staff and admin.is_superuser and admin.is_email_verified
