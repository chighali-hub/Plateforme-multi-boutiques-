"""Outils partages par les tests de l'authentification."""

import re

from django.core import mail

CODE_PATTERN = re.compile(r"\b(\d{6})\b")


def last_code_sent_to(email: str) -> str:
    """Code a 6 chiffres du dernier e-mail envoye a `email`."""
    for message in reversed(mail.outbox):
        if email in message.to:
            match = CODE_PATTERN.search(message.body)
            if match:
                return match.group(1)
    raise AssertionError(f"Aucun code envoye a {email}")


def error_code(response) -> str:
    return response.json()["error"]["code"]
