#!/bin/sh
set -e

python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Ensuring bootstrap superuser exists"
    python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

User = get_user_model()
if username and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username=username, email=email, password=password)
        print("Bootstrap superuser created")
    else:
        print("Bootstrap superuser already exists")
PY
fi

PORT=${PORT:-8000}
exec gunicorn sidesales.wsgi:application --bind 0.0.0.0:${PORT}
