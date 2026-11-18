#!/bin/sh
set -e

echo "Esperando a PostgreSQL en $POSTGRES_HOST:$POSTGRES_PORT..."
python manage.py wait_for_db

echo "Aplicando migraciones..."
python manage.py migrate --noinput

echo "Cargando datos de prueba (solo si la base está vacía)..."
python manage.py seed_demo --if-empty

exec "$@"
