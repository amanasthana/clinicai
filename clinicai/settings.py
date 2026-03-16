"""
ClinicAI Django Settings 
========================
Configuration for the ClinicAI clinic operating system.
Uses django-environ for all secrets/config. Never hardcode credentials.
"""

import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# Read .env file if it exists
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    # ClinicAI apps
    'core',
    'accounts',
    'reception',
    'prescription',
    'pharmacy',
    'notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.ActiveClinicMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'clinicai.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
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

WSGI_APPLICATION = 'clinicai.wsgi.application'

# Database: PostgreSQL via DATABASE_URL in .env
DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///clinicai.db')
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# India locale
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files — WhiteNoise serves in production
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (doctor letterhead uploads)
# On Azure App Service, /home is persistent storage (survives zip deploys).
# Locally, use BASE_DIR/media as before.
MEDIA_URL = '/media/'
import os as _os
MEDIA_ROOT = Path('/home/media') if _os.environ.get('WEBSITE_SITE_NAME') else BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameBackend',
]

# Session: 8 hours for clinic daily use
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Anthropic AI
ANTHROPIC_API_KEY = env('ANTHROPIC_API_KEY', default='')

# Email (password reset via Brevo SMTP)
EMAIL_BACKEND      = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST         = 'smtp-relay.brevo.com'
EMAIL_PORT         = 587
EMAIL_USE_TLS      = True
EMAIL_HOST_USER    = env('BREVO_SMTP_USER', default='')
EMAIL_HOST_PASSWORD = env('BREVO_SMTP_KEY', default='')
DEFAULT_FROM_EMAIL = 'ClinicAI <noreply@clinicai.in>'
PASSWORD_RESET_TIMEOUT = 3 * 24 * 3600  # 3 days

# Django cache (in-memory is fine for single-instance)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Pricing / Usage limits
FREE_DAILY_RX_LIMIT = 30   # prescriptions per clinic per day on free plan

# Security settings (enforced in production)
if not DEBUG:
    # Azure App Service terminates SSL at the load balancer and forwards HTTP
    # internally. Trust the X-Forwarded-Proto header so Django doesn't
    # redirect HTTPS requests to HTTPS in an infinite loop.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = env.list(
        'CSRF_TRUSTED_ORIGINS',
        default=['https://clinicai.azurewebsites.net']
    )

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[%(levelname)s %(asctime)s %(name)s] %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
