"""Codes a usage unique envoyes par e-mail (RG-03).

Voir 07-securite.md section 2.1 : generation par `secrets`, stockage du seul
hachage, validite limitee, nombre d'essais limite, delai entre deux envois, et
invalidation des codes precedents a chaque emission.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import OtpExpired, OtpInvalid, OtpTooManyAttempts

from .models import OtpCode, User

logger = logging.getLogger(__name__)

OTP_DIGITS = 6


def generate_code() -> str:
    """Code a 6 chiffres, zeros de tete compris, tire par un generateur cryptographique."""
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


@dataclass(frozen=True)
class IssuedOtp:
    otp: OtpCode
    code: str


def _valid_codes(user: User, purpose: str):
    return OtpCode.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
        attempts__lt=settings.OTP_MAX_ATTEMPTS,
    )


def seconds_until_resend(user: User, purpose: str) -> int:
    """Secondes a attendre avant de pouvoir emettre un nouveau code (0 si possible)."""
    last = OtpCode.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
    if last is None:
        return 0
    available_at = last.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    remaining = (available_at - timezone.now()).total_seconds()
    return max(int(remaining + 0.999), 0)


@transaction.atomic
def issue_otp(user: User, purpose: str, sent_to: str) -> IssuedOtp:
    """Invalide les codes encore valides du meme usage, puis en cree un nouveau.

    Le code en clair n'est renvoye qu'a l'appelant, pour l'e-mail ; il n'est
    jamais stocke ni journalise.
    """
    now = timezone.now()
    _valid_codes(user, purpose).update(consumed_at=now)
    code = generate_code()
    otp = OtpCode.objects.create(
        user=user,
        purpose=purpose,
        sent_to=sent_to,
        code_hash=make_password(code),
        expires_at=now + timedelta(seconds=settings.OTP_CODE_TTL_SECONDS),
    )
    return IssuedOtp(otp=otp, code=code)


def verify_otp(user: User, purpose: str, code: str, *, consume: bool = True) -> OtpCode:
    """Verifie le dernier code emis pour cet usage.

    - aucun code en cours, expire ou deja utilise : OtpExpired ;
    - essais epuises : OtpTooManyAttempts ;
    - code faux : l'essai est compte, puis OtpInvalid (details.attempts_left),
      ou OtpTooManyAttempts au dernier essai.

    Le compteur d'essais est enregistre avant que l'erreur ne soit levee.
    Contrat : appeler cette fonction HORS de toute transaction de l'appelant.
    Dans un bloc atomic englobant, l'ecriture ne serait qu'un point de
    sauvegarde, annule avec lui, et la limite de 5 essais deviendrait
    contournable. Les services verifient le code d'abord, puis ouvrent leur
    propre transaction pour appliquer l'effet.
    """
    error: Exception | None = None
    with transaction.atomic():
        otp = (
            OtpCode.objects.select_for_update()
            .filter(user=user, purpose=purpose, consumed_at__isnull=True)
            .order_by("-created_at", "-id")
            .first()
        )
        if otp is None or otp.expires_at <= timezone.now():
            error = OtpExpired()
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            error = OtpTooManyAttempts()
        elif not check_password(str(code), otp.code_hash):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            attempts_left = settings.OTP_MAX_ATTEMPTS - otp.attempts
            if attempts_left <= 0:
                logger.warning("Essais OTP epuises pour l'utilisateur %s (%s)", user.pk, purpose)
                error = OtpTooManyAttempts()
            else:
                error = OtpInvalid(details={"attempts_left": attempts_left})
        elif consume:
            otp.consumed_at = timezone.now()
            otp.save(update_fields=["consumed_at"])
    if error is not None:
        raise error
    return otp
