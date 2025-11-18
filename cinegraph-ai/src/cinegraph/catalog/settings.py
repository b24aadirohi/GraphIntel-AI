import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from cinegraph.shared.runtime import flag, validate_runtime

RUNTIME = validate_runtime()

BASE_DIR = Path(__file__).resolve().parents[3]
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-change-before-public-deployment")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    s.strip()
    for s in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,catalog").split(",")
    if s.strip()
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cinegraph.catalog.apps.CatalogConfig",
]
MIDDLEWARE = [
    "cinegraph.shared.observability.DjangoRequestTelemetry",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "cinegraph.shared.security.CatalogLoginThrottle",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "cinegraph.catalog.urls"
WSGI_APPLICATION = "cinegraph.catalog.wsgi.application"
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
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "catalog.sqlite3"}}
if url := os.getenv("DATABASE_URL"):
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        DATABASES["default"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "localhost",
            "PORT": parsed.port or 5432,
            "CONN_MAX_AGE": 60,
            "OPTIONS": {k: v[-1] for k, v in parse_qs(parsed.query).items()},
        }
    elif parsed.scheme == "sqlite":
        DATABASES["default"]["NAME"] = unquote(parsed.path) if parsed.path != "/:memory:" else ":memory:"
    else:
        raise ValueError("DATABASE_URL must use postgresql:// or sqlite://")
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Trust only isolated ingress that OVERWRITES X-Forwarded-For with the socket
# client IP and X-Forwarded-Proto. Direct app access must be blocked: this flag
# trusts those headers for HTTPS detection and per-client login throttling.
if flag("DJANGO_TRUST_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = RUNTIME.production
CSRF_COOKIE_SECURE = RUNTIME.production
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False
CSRF_TRUSTED_ORIGINS = [origin for origin in (RUNTIME.catalog_origin, RUNTIME.dashboard_origin) if origin]
SECURE_SSL_REDIRECT = RUNTIME.production
SECURE_REDIRECT_EXEMPT = [r"^live/?$", r"^ready/?$", r"^health/?$"]
SECURE_HSTS_SECONDS = 31536000 if RUNTIME.production else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = RUNTIME.production
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
if RUNTIME.production:
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.getenv("DJANGO_ALLOWED_HOSTS", urlparse(RUNTIME.catalog_origin).hostname).split(",")
        if host.strip()
    ]
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ValueError("DJANGO_ALLOWED_HOSTS must name specific hosts in production")
