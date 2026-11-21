from pathlib import Path
from smtplib import SMTPException
from unittest import mock

import pytest
from django.core import mail
from django.utils import translation

from apps.core.emails import BILINGUAL_SEPARATOR, render_email, send_templated_email

TEMPLATES_DIR = Path(__file__).parent / "templates"


@pytest.fixture(autouse=True)
def _test_templates(settings):
    settings.TEMPLATES = [
        {**settings.TEMPLATES[0], "DIRS": [TEMPLATES_DIR, *settings.TEMPLATES[0]["DIRS"]]}
    ]


def test_render_email_in_requested_language():
    subject, body = render_email("emails/test_message", {"code": "012345"}, "fr")
    assert subject == "Code de vérification"
    assert body == "Votre code : 012345"


def test_render_email_without_language_is_bilingual():
    with mock.patch(
        "apps.core.emails._render",
        side_effect=lambda template, context, lang: (f"S-{lang}", f"B-{lang}"),
    ):
        subject, body = render_email("emails/test_message", {}, None)
    assert subject == "S-fr / S-ar"
    assert body == f"B-fr{BILINGUAL_SEPARATOR}B-ar"


def test_render_email_restores_active_language():
    with translation.override("fr"):
        render_email("emails/test_message", {"code": "1"}, "ar")
        assert translation.get_language() == "fr"


def test_send_templated_email_delivers_message(settings):
    settings.DEFAULT_FROM_EMAIL = "no-reply@plateforme.test"
    send_templated_email.delay("aicha@example.com", "emails/test_message", {"code": "482913"}, "fr")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["aicha@example.com"]
    assert message.from_email == "no-reply@plateforme.test"
    assert "482913" in message.body


def test_send_templated_email_is_registered_with_retry_policy():
    assert send_templated_email.name == "core.send_templated_email"
    assert send_templated_email.max_retries == 3
    assert SMTPException in send_templated_email.autoretry_for
