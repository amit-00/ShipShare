from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "identity",
    "github_integration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core_app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "core_app.wsgi.application"
ASGI_APPLICATION = "core_app.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DJANGO_DB_NAME", BASE_DIR / "db.sqlite3"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.User"

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

LOGIN_URL = "/auth/github/login/"

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "GITHUB_OAUTH_REDIRECT_URI",
    "http://localhost:8000/auth/github/callback/",
)
GITHUB_OAUTH_SCOPE = os.environ.get("GITHUB_OAUTH_SCOPE", "read:user user:email")
GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY = os.environ.get("GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY", "")

GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")
GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
GITHUB_APP_INSTALL_URL = os.environ.get("GITHUB_APP_INSTALL_URL", "")

INTERNAL_SHARED_SECRET = os.environ.get("INTERNAL_SHARED_SECRET", "shipshare-internal-secret")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}
