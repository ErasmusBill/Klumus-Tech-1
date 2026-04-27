import os
from pathlib import Path
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
import dj_database_url  # pyright: ignore[reportMissingImports]

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ========================
# SECURITY CONFIGURATION
# ========================

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
DEBUG = os.getenv("DEBUG", "False").strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "school.fruitfulyouth.org,fruitfulyouth.org,localhost,127.0.0.1,0.0.0.0")

DOMAIN_URL = os.getenv("DOMAIN_URL", "https://school.fruitfulyouth.org")
APPEND_SLASH = True

# ========================
# APPLICATION DEFINITION
# ========================

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Local apps
    'account',
    'adminservices',
    'teacher',
    'student',
    "ai_predictor",

    # Third-party
    'django_select2',
]

# ========================
# JAZZMIN CONFIGURATION
# ========================

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

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'account.context_processors.notifications_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ========================
# DATABASE CONFIGURATION
# ========================

DATABASE_URL = os.getenv("DATABASE_URL")
APP_ENV = os.getenv("APP_ENV", "development")


def _db_ssl_required(app_env: str) -> bool:
    # Check for an explicit override first
    explicit = os.getenv("DB_SSL_REQUIRE")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    # Only default to True if in production AND no explicit override exists
    if app_env.strip().lower() == "production":
        # Note: If you are in Docker on a local/private network, you usually want False
        return False
    return False


if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=_db_ssl_required(APP_ENV),
        )
    }

    # Final safety check: if the URL says disable, make sure Django honors it
    if "sslmode=disable" in DATABASE_URL:
        DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "disable"
else:
    if APP_ENV == "production":
        raise RuntimeError("DATABASE_URL must be set in production.")
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ========================
# PASSWORD VALIDATION
# ========================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ========================
# INTERNATIONALIZATION
# ========================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ========================
# STATIC & MEDIA FILES
# ========================

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

if DEBUG:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = "account.CustomUser"

# ========================
# CACHE CONFIGURATION
# ========================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "klumus-cache",
        "TIMEOUT": 300,
    }
}

REDIS_URL_FOR_CACHE = os.getenv("REDIS_URL")
if REDIS_URL_FOR_CACHE or os.getenv("APP_ENV") == "production":
    _redis_url = REDIS_URL_FOR_CACHE or "redis://redis:6379/0"
    CACHES["default"] = {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": _redis_url,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }

# ========================
# THIRD-PARTY CONFIGS
# ========================

PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "erasmuscharway77@gmail.com")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").strip().lower() in {"1", "true", "yes", "on"}
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").strip().lower() in {"1", "true", "yes", "on"}
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

if SENDGRID_API_KEY:
    EMAIL_BACKEND = "sendgrid_backend.SendgridBackend"
    SENDGRID_SANDBOX_MODE_IN_DEBUG = False
    SENDGRID_ECHO_TO_STDOUT = True
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

MNOTIFY_API_KEY = os.getenv("MNOTIFY_API_KEY")
MNOTIFY_SENDER_ID = os.getenv("MNOTIFY_SENDER_ID")
MNOTIFY_BASE_URL = os.getenv("MNOTIFY_BASE_URL", "https://api.mnotify.com/api")

# ========================
# PRODUCTION SECURITY
# ========================

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Robust CSRF setup
csrf_origins = _csv_env("CSRF_TRUSTED_ORIGINS")
if not csrf_origins and DOMAIN_URL:
    csrf_origins = [DOMAIN_URL]
CSRF_TRUSTED_ORIGINS = csrf_origins

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False").strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(SECURE_SSL_REDIRECT)).strip().lower() in {"1", "true",
                                                                                                         "yes", "on"}
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", str(SECURE_SSL_REDIRECT)).strip().lower() in {"1", "true", "yes",
                                                                                                   "on"}

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB

# ========================
# CELERY CONFIGURATION
# ========================

REDIS_URL = os.getenv("REDIS_URL")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or REDIS_URL or "redis://redis:6379/0"
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND") or CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() in ("true", "1", "yes")


# ========================
# LOGGING CONFIGURATION
# ========================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'account': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'adminservices': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'teacher': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'student': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
