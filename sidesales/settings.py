"""
Django settings for sidesales project.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 't', 'yes', 'y', 'on'}


# SECURITY: DEBUG is off by default; must be explicitly opted-in.
DEBUG = _env_bool('DJANGO_DEBUG', False)

# SECURITY: a known fallback SECRET_KEY is only acceptable in DEBUG mode.
# In production we refuse to start rather than silently run with a guessable key.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'insecure-dev-key-do-not-use-in-production'  # noqa: S105
    else:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.'
        )


def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(',') if item.strip()]


def _normalize_host(host: str) -> str:
    cleaned = host.strip().replace('\\', '/').replace('https://', '').replace('http://', '')
    if not cleaned:
        return ''
    return cleaned.split('/')[0]


def _normalize_origin(origin: str) -> str:
    raw = origin.strip().replace('\\', '/')
    if not raw:
        return ''
    if not raw.startswith(('http://', 'https://')):
        raw = f'https://{raw.lstrip("/")}'
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ''
    if not parsed.scheme or not parsed.hostname:
        return ''
    # urlparse already handles bracketed IPv6 for us; trust its output.
    netloc = parsed.netloc
    return f'{parsed.scheme}://{netloc}'


def _hosts_from_origins(origins: list[str]) -> set[str]:
    hosts: set[str] = set()
    for origin in origins:
        try:
            parsed = urlparse(origin)
        except ValueError:
            continue
        if parsed.hostname:
            hosts.add(parsed.hostname)
    return hosts


ALLOWED_HOSTS_ENV = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost')
ALLOWED_HOSTS = [host for host in (_normalize_host(item) for item in _split_env_list(ALLOWED_HOSTS_ENV)) if host]
CSRF_TRUSTED_ORIGINS_ENV = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [
    origin for origin in (_normalize_origin(item) for item in _split_env_list(CSRF_TRUSTED_ORIGINS_ENV)) if origin
]

ALLOWED_HOSTS = sorted({*ALLOWED_HOSTS, *_hosts_from_origins(CSRF_TRUSTED_ORIGINS)})
ALLOWED_HOSTS = [host for host in ALLOWED_HOSTS if host]


def _origin_from_host(host: str, scheme: str) -> str:
    trimmed = host.strip()
    if not trimmed:
        return ''
    if ':' in trimmed and not trimmed.startswith('['):
        trimmed = f'[{trimmed}]'
    return f'{scheme}://{trimmed}'


csrf_origins_set = set(CSRF_TRUSTED_ORIGINS)
for host in ALLOWED_HOSTS:
    https_origin = _origin_from_host(host, 'https')
    if https_origin:
        csrf_origins_set.add(https_origin)
    if host in {'localhost', '127.0.0.1'}:
        http_origin = _origin_from_host(host, 'http')
        if http_origin:
            csrf_origins_set.add(http_origin)

CSRF_TRUSTED_ORIGINS = sorted(csrf_origins_set)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'operations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sidesales.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sidesales.wsgi.application'


DATABASES = {
    'default': dj_database_url.parse(
        os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
        conn_max_age=600,
    )
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'pt'
TIME_ZONE = 'Europe/Lisbon'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Django 5.x uses STORAGES; STATICFILES_STORAGE is deprecated.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

LOGIN_REDIRECT_URL = 'operations:dashboard'
LOGOUT_REDIRECT_URL = 'login'
LOGIN_URL = 'login'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'operations.User'


# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------
# These are no-ops in DEBUG so local development still works over plain HTTP,
# but become strict defaults as soon as DEBUG is off (i.e. production).

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False  # Django needs JS access for ajax CSRF.
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Honor X-Forwarded-Proto when behind a TLS-terminating proxy.
    if _env_bool('DJANGO_TRUST_FORWARDED_PROTO', True):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Basic logging: surface warnings/errors instead of silently swallowing them.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO' if not DEBUG else 'DEBUG',
    },
    'loggers': {
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}
