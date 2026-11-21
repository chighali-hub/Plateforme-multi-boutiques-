"""Ecriture du journal d'audit. Voir 07-securite.md section 8."""

import logging
from typing import Any

from django.conf import settings
from django.db import models

from .models import AuditAction, AuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request) -> str | None:
    """IP du client, avec la meme regle que la limitation de debit de DRF.

    Derriere NUM_PROXIES proxys de confiance, l'IP reelle est l'entree de
    X-Forwarded-For posee par le dernier proxy. Sans proxy declare, seule
    REMOTE_ADDR fait foi (un en-tete fourni par le client n'est pas digne de foi).
    """
    if request is None:
        return None
    meta = getattr(request, "META", {})
    num_proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES")
    forwarded = meta.get("HTTP_X_FORWARDED_FOR")
    if num_proxies and forwarded:
        addresses = [part.strip() for part in forwarded.split(",") if part.strip()]
        if addresses:
            return addresses[-min(num_proxies, len(addresses))]
    return meta.get("REMOTE_ADDR") or None


def log_action(
    actor,
    action: AuditAction | str,
    target: models.Model | None = None,
    metadata: dict[str, Any] | None = None,
    request=None,
    *,
    target_type: str | None = None,
) -> AuditLog:
    """Enregistre une action sensible.

    Appelee dans la transaction du service : si la transaction echoue, l'entree
    disparait avec elle. `target_type` par defaut : nom du modele en minuscules.
    """
    if target is not None and target_type is None:
        target_type = target._meta.model_name
    entry = AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=str(action),
        target_type=target_type or "",
        target_id=getattr(target, "pk", None),
        metadata=metadata or {},
        ip_address=get_client_ip(request),
    )
    logger.info("Audit %s sur %s#%s", entry.action, entry.target_type, entry.target_id)
    return entry
