"""Permissions communes. Voir 05-aspects-transversaux.md section 4.2 et
03-reference-api.md sections 0.2 et 0.3.

Pour toute vue de l'espace boutique, l'ordre des controles est fixe :
1. boutique bloquee -> 403 SHOP_BLOCKED ;
2. boutique expiree -> 403 SHOP_EXPIRED ;
3. etat non autorise pour la vue -> 403 SHOP_STATE_FORBIDDEN.
"""

from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.permissions import BasePermission

from apps.accounts.models import User
from apps.shops.models import Shop, ShopState

from .exceptions import ShopBlocked, ShopExpired, ShopStateForbidden
from .models import PlatformSettings
from .whatsapp import build_whatsapp_url


def admin_contact_details(shop: Shop | None = None) -> dict:
    """Coordonnees WhatsApp de l'administrateur, avec message pre-rempli."""
    admin_whatsapp = PlatformSettings.load().admin_whatsapp
    if not admin_whatsapp:
        return {"admin_whatsapp": "", "whatsapp_url": ""}
    text = None
    if shop is not None:
        text = _(
            "Bonjour, je souhaite recharger le compte de la boutique %(name)s (%(email)s)."
        ) % {"name": shop.name, "email": shop.owner.email}
    return {
        "admin_whatsapp": admin_whatsapp,
        "whatsapp_url": build_whatsapp_url(admin_whatsapp, text),
    }


def ensure_shop_not_locked(shop: Shop) -> str:
    """Leve SHOP_BLOCKED ou SHOP_EXPIRED si la boutique a perdu l'acces.

    Renvoie l'etat calcule. Partagee par les permissions, la connexion et le
    rafraichissement des jetons : la regle est ecrite une seule fois.
    """
    now = timezone.now()
    state = shop.get_state(now)
    if state == ShopState.BLOCKED:
        raise ShopBlocked(details=admin_contact_details())
    if state == ShopState.EXPIRED:
        details = {"expired_at": shop.expires_at.isoformat() if shop.expires_at else None}
        details.update(admin_contact_details(shop))
        raise ShopExpired(details=details)
    return state


class IsPlatformAdmin(BasePermission):
    """Authentifie et role ADMIN ; sinon 401 ou 403 PERMISSION_DENIED."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role == User.Role.ADMIN)


class IsShopOwner(BasePermission):
    """Authentifie, role SHOP, possede une boutique, ni bloquee ni expiree.

    Place la boutique dans `request.shop`. Les vues utilisent `request.shop`,
    jamais un identifiant de boutique venant de la requete.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.role == User.Role.SHOP):
            return False
        shop = Shop.objects.select_related("theme", "owner").filter(owner_id=user.pk).first()
        if shop is None:
            return False
        ensure_shop_not_locked(shop)
        request.shop = shop
        return True


class ShopStateAllowed(BasePermission):
    """Etat de la boutique dans la liste ; sinon 403 SHOP_STATE_FORBIDDEN.

    S'utilise apres IsShopOwner, sous forme d'instance :
        [IsShopOwner(), ShopStateAllowed("REJECTED", "ACTIVE")]
    ou dans `permission_classes` (l'instance est appelable et se renvoie).
    """

    def __init__(self, *states: str):
        unknown = set(states) - set(ShopState.values)
        if not states or unknown:
            raise ValueError(f"Etats de boutique invalides : {sorted(unknown) or 'aucun'}")
        self.states = frozenset(states)

    def __call__(self):
        return self

    def has_permission(self, request, view) -> bool:
        shop = getattr(request, "shop", None)
        if shop is None:
            return False
        state = shop.get_state()
        if state not in self.states:
            raise ShopStateForbidden(details={"state": state})
        return True
