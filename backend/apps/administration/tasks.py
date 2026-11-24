"""Taches Celery de l'administration. Voir 05-aspects-transversaux.md section 13."""

from celery import shared_task

from . import services


@shared_task(name="administration.send_expiry_reminders")
def send_expiry_reminders() -> int:
    """Rappels d'expiration a 7, 3 et 1 jour(s) (RG-25). Tous les jours a 08:00."""
    return services.send_expiry_reminders()
