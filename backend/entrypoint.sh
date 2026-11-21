#!/bin/sh
set -e

# Attendre que PostgreSQL accepte les connexions.
echo "Attente de PostgreSQL sur ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
until nc -z "${POSTGRES_HOST:-db}" "${POSTGRES_PORT:-5432}"; do
  sleep 1
done
echo "PostgreSQL est disponible."

# Les migrations ne sont lancees que par le service web (RUN_MIGRATIONS=1).
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

exec "$@"
