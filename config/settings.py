"""Inställningar för brf-bokning.

Allt som skiljer mellan miljöer läses från miljövariabler (se .env.example).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
# Render sätter värdnamnet automatiskt (t.ex. bokalo.onrender.com).
if env("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))
    CSRF_TRUSTED_ORIGINS.append(f"https://{env('RENDER_EXTERNAL_HOSTNAME')}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "booking",
    "access",
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "booking.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Databas: DATABASE_URL (Render), POSTGRES_*-variabler (Docker Compose) eller SQLite lokalt.
if env("DATABASE_URL"):
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(env("DATABASE_URL"), conn_max_age=600)}
elif env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "db"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LANGUAGE_CODE = "sv"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Inloggning (django-allauth) -------------------------------------------
# Bara befintliga medlemmar kan logga in; ingen fri registrering
# (se booking.adapters.MemberOnlyAccountAdapter).
ACCOUNT_ADAPTER = "booking.adapters.MemberOnlyAccountAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "none"  # e-post kommer från medlemsregistret
ACCOUNT_LOGIN_BY_CODE_ENABLED = True  # engångskod via e-post ("magisk länk")
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 15 * 60
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGOUT_ON_GET = False
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "booking:home"
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"

# --- E-post ----------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Brf-bokning <bokning@example.se>")

# --- Föreningen --------------------------------------------------------------
SITE_NAME = env("SITE_NAME", "Brf Bokning")

# --- Passersystem ------------------------------------------------------------
# Byt till "access.providers.axema.AxemaProvider" när Axema-kopplingen finns.
ACCESS_PROVIDER = env("ACCESS_PROVIDER", "access.providers.fake.FakeProvider")
# Hur ofta workern stämmer av (sekunder) och när nattlig medlemssynk körs.
WORKER_INTERVAL_SECONDS = int(env("WORKER_INTERVAL_SECONDS", "60"))
MEMBER_SYNC_HOUR = int(env("MEMBER_SYNC_HOUR", "3"))

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# --- Betalning ---------------------------------------------------------------
# "payments.providers.stripe.StripeProvider" i drift med onlinebetalning.
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", "payments.providers.fake.FakePaymentProvider")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
# Hur länge en obetald bokning håller tiden (Stripe kräver minst 30 min).
PAYMENT_HOLD_MINUTES = int(env("PAYMENT_HOLD_MINUTES", "30"))

# --- Larm till styrelsen ------------------------------------------------------
# Kommaseparerad lista: "Namn <e-post>,..." – får larm om dörrbehörigheter som fallerar.
ADMINS = [
    (a.split("<")[0].strip(), a.split("<")[-1].rstrip(">").strip())
    for a in env("BOARD_EMAILS", "").split(",")
    if "@" in a
]
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ACCESS_ALERT_AFTER_ATTEMPTS = int(env("ACCESS_ALERT_AFTER_ATTEMPTS", "3"))
