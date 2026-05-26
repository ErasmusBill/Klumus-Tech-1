import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env.local")
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value.strip()) if value else default


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = _bool("DEBUG", default=False)
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

if DEBUG:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-secret-key")
else:
    SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = _csv(
    "ALLOWED_HOSTS",
    default="school.fruitfulyouth.org,fruitfulyouth.org,localhost,127.0.0.1",
)

DOMAIN_URL = os.getenv("DOMAIN_URL", "https://school.fruitfulyouth.org")
APPEND_SLASH = True

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    # Admin UI (must be before django.contrib.admin)
    "jazzmin",
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "account",
    "adminservices",
    "teacher",
    "student",
    "ai_predictor",
    # Third-party
    "django_select2",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "account.middleware.SubscriptionEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# URLs & WSGI
# ---------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "account.context_processors.notifications_context",
            ],
        },
    }
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_database_url = os.getenv("DATABASE_URL")

if _database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=600,
            ssl_require=_bool("DB_SSL_REQUIRE", default=False),
        )
    }
    if "sslmode=disable" in _database_url:
        DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "disable"
elif APP_ENV == "production":
    raise RuntimeError("DATABASE_URL must be set in production.")
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "account.CustomUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

## ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG:
    # Optimized WhiteNoise storage for production (manages compression and caching)
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_redis_url = os.getenv("REDIS_URL")

if _redis_url or APP_ENV == "production":
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url or "redis://redis:6379/0",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "klumus-cache",
            "TIMEOUT": 300,
        }
    }

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

_csrf_origins = _csv("CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS = _csrf_origins if _csrf_origins else ([DOMAIN_URL] if DOMAIN_URL else [])

SECURE_SSL_REDIRECT = _bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = _bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "erasmuscharway77@gmail.com")

_sendgrid_key = os.getenv("SENDGRID_API_KEY")
_email_host = os.getenv("EMAIL_HOST", "")

if _sendgrid_key:
    EMAIL_BACKEND = "sendgrid_backend.SendgridBackend"
    SENDGRID_API_KEY = _sendgrid_key
    SENDGRID_SANDBOX_MODE_IN_DEBUG = False
    SENDGRID_ECHO_TO_STDOUT = True
elif _email_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _email_host
    EMAIL_PORT = _int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = _bool("EMAIL_USE_TLS", default=True)
    EMAIL_USE_SSL = _bool("EMAIL_USE_SSL", default=False)
    EMAIL_TIMEOUT = _int("EMAIL_TIMEOUT", default=20)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

_celery_broker = (
    os.getenv("CELERY_BROKER_URL")
    or _redis_url
    or ("redis://redis:6379/0" if APP_ENV == "production" else "memory://")
)

CELERY_BROKER_URL = _celery_broker
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND") or (
    "cache+memory://" if _celery_broker == "memory://" else _celery_broker
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = _bool("CELERY_TASK_ALWAYS_EAGER", default=(APP_ENV != "production"))

# ---------------------------------------------------------------------------
# Third-party services
# ---------------------------------------------------------------------------

PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"
FREE_TRIAL_DAYS = _int("FREE_TRIAL_DAYS", default=30)
FREE_TRIAL_PAYSTACK_AMOUNT = os.getenv("FREE_TRIAL_PAYSTACK_AMOUNT", "0.000")

MNOTIFY_API_KEY = os.getenv("MNOTIFY_API_KEY")
MNOTIFY_SENDER_ID = os.getenv("MNOTIFY_SENDER_ID")
MNOTIFY_BASE_URL = os.getenv("MNOTIFY_BASE_URL", "https://api.mnotify.com/api")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} [{name}:{lineno}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "account": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "adminservices": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "teacher": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "student": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Jazzmin (admin UI)
# ---------------------------------------------------------------------------

JAZZMIN_SETTINGS = {
    "site_title": "Klumus Admin",
    "site_header": "Klumus",
    "site_brand": "Klumus",
    "site_logo": None,
    "welcome_sign": "Welcome to Klumus Administration",
    "copyright": "Klumus Tech",
    "search_model": ["account.CustomUser", "account.School"],
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "auth": "fas fa-users-cog",
        "account.CustomUser": "fas fa-user-shield",
        "account.School": "fas fa-school",
        "account.Subscription": "fas fa-id-card",
        "account.Package": "fas fa-box",
    },
    "order_with_respect_to": ["auth", "account"],
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "dark_mode_theme": "darkly",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "sidebar": "sidebar-light-primary",
    "no_sidebar_border": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
}