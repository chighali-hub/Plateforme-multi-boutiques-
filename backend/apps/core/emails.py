"""Envoi des e-mails transactionnels. Voir 05-aspects-transversaux.md sections 7.4 et 12.

Gabarits texte : templates/emails/<nom>.txt et templates/emails/<nom>_subject.txt.
Les textes des gabarits passent par {% translate %} / {% blocktranslate %}.
"""

import logging
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import translation

from .i18n import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

BILINGUAL_SEPARATOR = "\n\n----------------------------------------\n\n"


def _render(template: str, context: dict, language: str) -> tuple[str, str]:
    with translation.override(language):
        subject = render_to_string(f"{template}_subject.txt", context)
        body = render_to_string(f"{template}.txt", context)
    return " ".join(subject.split()), body.strip()


def render_email(template: str, context: dict, language: str | None) -> tuple[str, str]:
    """Renvoie (sujet, corps).

    Avec une langue : le message est dans cette langue. Sans langue (e-mail
    declenche par l'admin pour une boutique) : francais puis arabe.
    """
    if language in SUPPORTED_LANGUAGES:
        return _render(template, context, language)
    parts = [_render(template, context, lang) for lang in SUPPORTED_LANGUAGES]
    subject = " / ".join(part[0] for part in parts)
    body = BILINGUAL_SEPARATOR.join(part[1] for part in parts)
    return subject, body


@shared_task(
    name="core.send_templated_email",
    autoretry_for=(SMTPException, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_templated_email(
    to: str | list[str], template: str, context: dict, language: str | None = None
) -> None:
    """Rend et envoie un e-mail texte. Tache Celery : arguments serialisables.

    `template` est le chemin sans extension, ex. "emails/otp_registration".
    Le contexte n'est jamais journalise (il peut contenir un code OTP).
    """
    recipients = [to] if isinstance(to, str) else list(to)
    subject, body = render_email(template, context, language)
    EmailMessage(
        subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=recipients
    ).send(fail_silently=False)
    logger.info("E-mail %s envoye a %d destinataire(s)", template, len(recipients))
