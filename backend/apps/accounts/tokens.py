"""Jetons JWT. Voir 05-aspects-transversaux.md section 4.1.

Le jeton `access` porte `user_id` et `role`. L'etat de la boutique n'y figure
pas : il est verifie en base a chaque requete.
"""

from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import aware_utcnow

from .models import User


class InvalidRefreshToken(Exception):
    """Jeton de rafraichissement invalide, expire, revoque ou inconnu."""


def issue_tokens(user: User) -> dict[str, str]:
    """Cree une paire access/refresh. Le refresh est enregistre comme emis."""
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _decode(raw: str) -> RefreshToken:
    try:
        return RefreshToken(raw)
    except TokenError as error:
        raise InvalidRefreshToken from error


def rotate_refresh_token(raw: str, check_user) -> tuple[User, dict[str, str]]:
    """Echange un refresh contre une nouvelle paire et revoque l'ancien.

    La ligne du jeton emis est verrouillee : deux rafraichissements simultanes
    du meme jeton ne peuvent pas reussir tous les deux. `check_user(user)` peut
    lever une erreur metier (boutique bloquee ou expiree) : rien n'est alors
    revoque.
    """
    token = _decode(raw)
    with transaction.atomic():
        outstanding = (
            OutstandingToken.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(jti=token["jti"])
            .first()
        )
        if outstanding is None or outstanding.user is None:
            raise InvalidRefreshToken
        if BlacklistedToken.objects.filter(token=outstanding).exists():
            raise InvalidRefreshToken
        user = outstanding.user
        if not user.is_active or str(user.pk) != str(token.get("user_id")):
            raise InvalidRefreshToken
        check_user(user)
        BlacklistedToken.objects.create(token=outstanding)
        return user, issue_tokens(user)


def revoke_refresh_token(raw: str, user: User) -> None:
    """Revoque un refresh appartenant a `user` (deconnexion)."""
    token = _decode(raw)
    if str(token.get("user_id")) != str(user.pk):
        raise InvalidRefreshToken
    token.blacklist()


def revoke_all_sessions(user: User) -> int:
    """Revoque tous les refresh non expires de l'utilisateur. Renvoie leur nombre.

    Utilisee par la reinitialisation et le changement du mot de passe, et par
    le blocage d'une boutique (phase 4).
    """
    pending = OutstandingToken.objects.filter(
        user=user, expires_at__gt=aware_utcnow(), blacklistedtoken__isnull=True
    )
    created = BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in pending], ignore_conflicts=True
    )
    return len(created)
