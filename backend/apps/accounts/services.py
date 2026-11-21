"""Inscription, connexion, jetons, mot de passe et e-mail du compte.

Regles : RG-01 a RG-08 (01-vue-d-ensemble.md section 5) ; securite :
07-securite.md section 2. Les services levent des exceptions metier ; ils ne
connaissent ni la requete HTTP ni la serialisation.
"""

import logging
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import update_last_login
from django.core import signing
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.audit import log_action
from apps.core.emails import send_templated_email
from apps.core.exceptions import (
    AlreadyVerified,
    EmailAlreadyUsed,
    EmailNotVerified,
    InvalidCredentials,
    OtpExpired,
    OtpResendTooSoon,
    ResetTokenInvalid,
)
from apps.core.models import AuditAction
from apps.core.permissions import ensure_shop_not_locked
from apps.shops.models import Shop

from . import otp as otp_service
from .models import OtpCode, User
from .tokens import issue_tokens, revoke_all_sessions

logger = logging.getLogger(__name__)

PASSWORD_RESET_SALT = "password-reset"
SLUG_RETRIES = 5


@cache
def _dummy_password_hash() -> str:
    return make_password("mot-de-passe-factice-pour-temps-constant")


def _equalize_timing(password: str | None) -> None:
    """Hache un mot de passe factice quand le compte n'existe pas.

    Le temps de reponse ne permet alors pas de deviner si l'e-mail existe.
    """
    check_password(password or "", _dummy_password_hash())


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user(email: str) -> User | None:
    return User.objects.filter(email=normalize_email(email)).first()


def _send_on_commit(to: str, template: str, context: dict[str, Any], language: str | None):
    transaction.on_commit(lambda: send_templated_email.delay(to, template, context, language))


def _send_otp(issued: otp_service.IssuedOtp, template: str, language: str | None) -> None:
    context = {
        "code": issued.code,
        "minutes": settings.OTP_CODE_TTL_SECONDS // 60,
    }
    _send_on_commit(issued.otp.sent_to, template, context, language)


OTP_TEMPLATES = {
    OtpCode.Purpose.REGISTRATION: "emails/otp_registration",
    OtpCode.Purpose.PASSWORD_RESET: "emails/otp_password_reset",
    OtpCode.Purpose.EMAIL_CHANGE: "emails/otp_email_change",
}


def _issue_and_send(user: User, purpose: str, sent_to: str, language: str | None) -> None:
    issued = otp_service.issue_otp(user, purpose, sent_to)
    _send_otp(issued, OTP_TEMPLATES[purpose], language)


# --- Inscription (RG-01, RG-02, RG-03) ------------------------------------------
@dataclass(frozen=True)
class RegistrationFiles:
    """Fichiers deja valides et traites (logo WebP, cartes sans metadonnees)."""

    logo: ContentFile
    id_card_front: ContentFile
    id_card_back: ContentFile


def _email_conflict(email: str) -> EmailAlreadyUsed:
    existing = find_user(email)
    return EmailAlreadyUsed(details={"is_verified": bool(existing and existing.is_email_verified)})


def _create_shop_with_unique_slug(owner: User, fields: dict[str, Any], files) -> Shop:
    """Cree la boutique ; recommence si un slug identique est pris en concurrence."""
    for _attempt in range(SLUG_RETRIES):
        shop = Shop(owner=owner, **fields)
        shop.logo.save(files.logo.name, files.logo, save=False)
        shop.id_card_front.save(files.id_card_front.name, files.id_card_front, save=False)
        shop.id_card_back.save(files.id_card_back.name, files.id_card_back, save=False)
        try:
            with transaction.atomic():
                shop.save()
            return shop
        except IntegrityError:
            _delete_files(shop)
            if not Shop.objects.filter(slug=shop.slug).exists():
                raise
    raise IntegrityError("Slug de boutique impossible a reserver.")


def _delete_files(shop: Shop) -> None:
    for field_file in (shop.logo, shop.id_card_front, shop.id_card_back):
        if field_file and field_file.name:
            field_file.storage.delete(field_file.name)


def register_shop(
    *,
    email: str,
    password: str,
    shop_fields: dict[str, Any],
    files: RegistrationFiles,
    language: str | None,
) -> User:
    """Cree le compte (e-mail non verifie) et la boutique, puis envoie l'OTP.

    Etat initial : onboarding_step = VERIFY_EMAIL, status = PENDING.
    Leve EmailAlreadyUsed (409) si l'e-mail est deja pris, y compris par une
    inscription concurrente.
    """
    email = normalize_email(email)
    if User.objects.filter(email=email).exists():
        raise _email_conflict(email)

    shop: Shop | None = None
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email, password=password, role=User.Role.SHOP
                    )
            except IntegrityError:
                raise _email_conflict(email) from None
            shop = _create_shop_with_unique_slug(user, shop_fields, files)
            _issue_and_send(user, OtpCode.Purpose.REGISTRATION, email, language)
    except Exception:
        # La transaction est annulee : les fichiers deja ecrits seraient orphelins.
        if shop is not None:
            _delete_files(shop)
        raise
    logger.info("Boutique %s inscrite, en attente de verification de l'e-mail", shop.pk)
    return user


def resend_otp(email: str, purpose: str, language: str | None) -> None:
    """Renvoie un code ; la reponse ne revele pas si l'e-mail existe.

    REGISTRATION : seulement pour un compte boutique non verifie ; un renvoi
    trop tot leve OtpResendTooSoon (429).
    PASSWORD_RESET : seulement si le compte existe ; un renvoi trop tot est
    ignore en silence (aucun e-mail, meme reponse).
    """
    user = find_user(email)
    if purpose == OtpCode.Purpose.REGISTRATION:
        if user is None or user.is_email_verified or user.role != User.Role.SHOP:
            return
        wait = otp_service.seconds_until_resend(user, purpose)
        if wait:
            raise OtpResendTooSoon(details={"retry_after": wait})
        with transaction.atomic():
            _issue_and_send(user, purpose, user.email, language)
        return
    if purpose == OtpCode.Purpose.PASSWORD_RESET:
        request_password_reset(email, language)


def verify_registration_email(email: str, code: str) -> User:
    """Valide l'OTP d'inscription : e-mail verifie, etape CHOOSE_DESIGN.

    Un e-mail inconnu donne OtpExpired, comme un code absent (aucune divulgation).
    """
    user = find_user(email)
    if user is None or user.role != User.Role.SHOP:
        _equalize_timing(code)
        raise OtpExpired()
    if user.is_email_verified:
        raise AlreadyVerified()
    otp_service.verify_otp(user, OtpCode.Purpose.REGISTRATION, code)
    with transaction.atomic():
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified", "updated_at"])
        Shop.objects.filter(owner=user, onboarding_step=Shop.OnboardingStep.VERIFY_EMAIL).update(
            onboarding_step=Shop.OnboardingStep.CHOOSE_DESIGN, updated_at=timezone.now()
        )
    update_last_login(None, user)
    return user


# --- Connexion ------------------------------------------------------------------
def _check_credentials(email: str, password: str, role: str) -> User:
    """Meme erreur INVALID_CREDENTIALS pour un e-mail inconnu, un mot de passe
    faux, un compte inactif ou un role different."""
    user = find_user(email)
    if user is None:
        _equalize_timing(password)
        raise InvalidCredentials()
    if not user.check_password(password) or not user.is_active or user.role != role:
        raise InvalidCredentials()
    return user


def login_shop(email: str, password: str) -> User:
    """Connexion boutique. Controles, dans l'ordre : identifiants et role,
    e-mail verifie (RG-04), boutique non bloquee, boutique non expiree."""
    user = _check_credentials(email, password, User.Role.SHOP)
    if not user.is_email_verified:
        raise EmailNotVerified(details={"email": user.email})
    shop = Shop.objects.filter(owner=user).first()
    if shop is None:
        raise InvalidCredentials()
    ensure_shop_not_locked(shop)
    update_last_login(None, user)
    return user


def login_admin(email: str, password: str, request=None) -> User:
    """Connexion administrateur ; chaque succes est audite (ADMIN_LOGIN)."""
    user = _check_credentials(email, password, User.Role.ADMIN)
    update_last_login(None, user)
    log_action(user, AuditAction.ADMIN_LOGIN, target=user, request=request)
    return user


def check_user_can_refresh(user: User) -> None:
    """Une boutique bloquee ou expiree ne rafraichit pas ses jetons."""
    if user.role == User.Role.SHOP:
        shop = Shop.objects.filter(owner=user).first()
        if shop is not None:
            ensure_shop_not_locked(shop)


# --- Mot de passe oublie (RG-07) -------------------------------------------------
def request_password_reset(email: str, language: str | None) -> None:
    """Etape 1 : envoie un OTP si le compte existe ; meme effet visible sinon.

    Pendant le delai de renvoi, aucun nouvel e-mail n'est envoye.
    """
    user = find_user(email)
    if user is None or not user.is_active:
        _equalize_timing(email)
        return
    if otp_service.seconds_until_resend(user, OtpCode.Purpose.PASSWORD_RESET):
        return
    with transaction.atomic():
        _issue_and_send(user, OtpCode.Purpose.PASSWORD_RESET, user.email, language)


def verify_password_reset_code(email: str, code: str) -> str:
    """Etape 2 : verifie l'OTP et renvoie un jeton signe, valable 15 minutes.

    Le code n'est pas consomme ici : il l'est par l'etape 3, ce qui rend le
    jeton a usage unique.
    """
    user = find_user(email)
    if user is None or not user.is_active:
        _equalize_timing(code)
        raise OtpExpired()
    otp = otp_service.verify_otp(user, OtpCode.Purpose.PASSWORD_RESET, code, consume=False)
    signer = signing.TimestampSigner(salt=PASSWORD_RESET_SALT)
    return signer.sign_object({"user": user.pk, "otp": otp.pk})


def _read_reset_token(token: str) -> tuple[int, int]:
    signer = signing.TimestampSigner(salt=PASSWORD_RESET_SALT)
    try:
        payload = signer.unsign_object(token, max_age=settings.PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS)
        return int(payload["user"]), int(payload["otp"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise ResetTokenInvalid() from None


def reset_password(token: str, new_password: str, request=None) -> User:
    """Etape 3 : nouveau mot de passe ; toutes les sessions sont fermees.

    Le mot de passe doit avoir ete valide par l'appelant (RG-06). Le code OTP
    lie au jeton est consomme dans la meme transaction : un jeton rejoue, ou
    rendu caduc par un code plus recent, leve ResetTokenInvalid.
    """
    user_id, otp_id = _read_reset_token(token)
    with transaction.atomic():
        otp = (
            OtpCode.objects.select_for_update()
            .select_related("user")
            .filter(
                pk=otp_id,
                user_id=user_id,
                purpose=OtpCode.Purpose.PASSWORD_RESET,
                consumed_at__isnull=True,
            )
            .first()
        )
        if otp is None or not otp.user.is_active:
            raise ResetTokenInvalid()
        user = otp.user
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        otp.consumed_at = timezone.now()
        otp.save(update_fields=["consumed_at"])
        revoke_all_sessions(user)
        log_action(user, AuditAction.PASSWORD_RESET, target=user, request=request)
    return user


def user_for_reset_token(token: str) -> User:
    """Utilisateur vise par un jeton (pour valider le mot de passe contre son e-mail)."""
    user_id, _otp_id = _read_reset_token(token)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ResetTokenInvalid()
    return user


# --- Compte connecte ---------------------------------------------------------------
def change_password(user: User, new_password: str) -> dict[str, str]:
    """Change le mot de passe (deja controle par l'appelant), ferme toutes les
    sessions et renvoie une nouvelle paire de jetons pour la session courante."""
    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        revoke_all_sessions(user)
        return issue_tokens(user)


def request_email_change(user: User, new_email: str, language: str | None) -> str:
    """Envoie un OTP a la nouvelle adresse (RG-08). Mot de passe deja verifie.

    Leve EmailAlreadyUsed si l'adresse est prise, OtpResendTooSoon pendant le
    delai de renvoi.
    """
    new_email = normalize_email(new_email)
    if User.objects.filter(email=new_email).exists():
        raise EmailAlreadyUsed()
    wait = otp_service.seconds_until_resend(user, OtpCode.Purpose.EMAIL_CHANGE)
    if wait:
        raise OtpResendTooSoon(details={"retry_after": wait})
    with transaction.atomic():
        _issue_and_send(user, OtpCode.Purpose.EMAIL_CHANGE, new_email, language)
    return new_email


def confirm_email_change(user: User, code: str, request=None, language: str | None = None):
    """Applique le changement d'e-mail et previent l'ancienne adresse."""
    otp = otp_service.verify_otp(user, OtpCode.Purpose.EMAIL_CHANGE, code)
    new_email = normalize_email(otp.sent_to)
    old_email = user.email
    try:
        with transaction.atomic():
            if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                raise EmailAlreadyUsed()
            user.email = new_email
            user.save(update_fields=["email", "updated_at"])
            log_action(
                user,
                AuditAction.EMAIL_CHANGED,
                target=user,
                metadata={"old_email": old_email, "new_email": new_email},
                request=request,
            )
            _send_on_commit(
                old_email,
                "emails/email_changed_notice",
                {"new_email": new_email},
                language,
            )
    except IntegrityError:
        raise EmailAlreadyUsed() from None
    return user
