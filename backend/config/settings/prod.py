"""Parametres de production."""

from .base import *  # noqa: F401,F403

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# L'API est derriere un seul proxy de confiance (Nginx) : l'IP reelle du client
# est lue dans X-Forwarded-For pour la limitation de debit.
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": 1}  # noqa: F405
