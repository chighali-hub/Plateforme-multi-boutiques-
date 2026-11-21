"""Garde-fou : les tests tournent toujours avec config.settings.test.

Dans Docker, le fichier .env fixe DJANGO_SETTINGS_MODULE a config.settings.dev.
Sans l'option --ds de pytest.ini, cette variable l'emporterait : les e-mails
partiraient vers Mailpit et les taches Celery vers le worker, et certains tests
echoueraient en local alors que la CI est verte.
"""

import os

from django.conf import settings


def test_tests_use_test_settings_module():
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings.test"


def test_test_settings_isolate_side_effects():
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")
