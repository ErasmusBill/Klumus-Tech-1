"""
Django settings for config project.
Updated for Render Deployment with SendGrid & Twilio Integration
"""

from pathlib import Path
import os
from dotenv import load_dotenv # pyright: ignore[reportMissingImports]
import dj_database_url # pyright: ignore[reportMissingImports]

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ========================
# SECURITY CONFIGURATION
# ========================

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
DEBUG = os.getenv("DEBUG", "True").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)

fly_app_name = os.getenv("FLY_APP_NAME")
if fly_app_name:
    ALLOWED_HOSTS.append(f"{fly_app_name}.fly.dev")

DOMAIN_URL = os.getenv("DOMAIN_URL", "")

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
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=False
        )
    }
else:
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

CACHE_DEFAULT_TIMEOUT = 300

# ========================
# PAYSTACK CONFIGURATION
# ========================

PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"

# ========================
# SENDGRID EMAIL CONFIGURATION
# ========================


# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# DEFAULT_FROM_EMAIL = "eramuscharway77@gmail.com"


# EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'
# SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
# DEFAULT_FROM_EMAIL = "eramuscharway77@gmail.com"
# SENDGRID_SANDBOX_MODE_IN_DEBUG = False

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
DEFAULT_FROM_EMAIL = "erasmuscharway77@gmail.com"

# In local development (or when API key is missing), keep email local
# so user actions like registration don't crash on missing SendGrid backend.
if SENDGRID_API_KEY:
    EMAIL_BACKEND = "sendgrid_backend.SendgridBackend"
    SENDGRID_SANDBOX_MODE_IN_DEBUG = False
    SENDGRID_ECHO_TO_STDOUT = True
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# In settings.py
# EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# EMAIL_HOST = "smtp.sendgrid.net"
# EMAIL_PORT = 587 # Changed from  2525 
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = "apikey"
# EMAIL_HOST_PASSWORD = os.getenv("SENDGRID_API_KEY")
# DEFAULT_FROM_EMAIL = "erasmuscharway77@gmail.com"
# ========================
# TWILIO CONFIGURATION
# ========================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


# Debug: Check if environment variables are loaded
print("=== ENVIRONMENT VARIABLE DEBUG ===")
print(f"TWILIO_ACCOUNT_SID: {'SET' if TWILIO_ACCOUNT_SID else 'NOT SET'}")
print(f"TWILIO_AUTH_TOKEN: {'SET' if TWILIO_AUTH_TOKEN else 'NOT SET'}")
print(f"TWILIO_PHONE_NUMBER: {'SET' if TWILIO_PHONE_NUMBER else 'NOT SET'}")
print("===================================")

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    print("⚠️  Twilio credentials not properly set in environment variables")

# ========================
# RENDER DEPLOYMENT SETTINGS
# ========================

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = []
if render_hostname:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_hostname}")
if fly_app_name:
    CSRF_TRUSTED_ORIGINS.append(f"https://{fly_app_name}.fly.dev")



# settings.py - Add these for better performance
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
