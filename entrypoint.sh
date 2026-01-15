#!/bin/sh
set -e

python manage.py migrate --noinput

PORT=${PORT:-8000}
exec gunicorn sidesales.wsgi:application --bind 0.0.0.0:${PORT}
