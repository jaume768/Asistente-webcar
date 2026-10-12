"""Settings de webcar-asistente.

Todo lo que cambia entre entornos sale de variables de entorno (ver
`.env.example`). En desarrollo basta con copiar `.env.example` a `.env`.
"""

from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-inseguro-cambiar")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cuentas",
    "webcar",
    "chat",
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

ROOT_URLCONF = "asistente.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "asistente.wsgi.application"

# SQLite en desarrollo; en producción DATABASE_URL-like con MySQL/Postgres
# (ver docs/PLAN.md). Solo guarda usuarios, conversaciones y acciones: los datos
# del rentacar viven en DuckDB, fuera de esta base de datos.
DATABASES = {
    "default": {
        "ENGINE": config("DB_ENGINE", default="django.db.backends.sqlite3"),
        "NAME": config("DB_NAME", default=str(BASE_DIR / "db.sqlite3")),
        "USER": config("DB_USER", default=""),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default=""),
        "PORT": config("DB_PORT", default=""),
    }
}

AUTH_USER_MODEL = "cuentas.Usuario"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "chat:inicio"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "es-es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Webcar -----------------------------------------------------------------
# Endpoint de los listados CSV. El «codi» del día y la «ruta» (código del
# rentacar) se añaden al descargar: ver webcar/cliente.py.
WEBCAR_API_URL = config("WEBCAR_API_URL", default="https://lite.webcar.rent/webcar/appapi")
WEBCAR_TIMEOUT_SECONDS = config("WEBCAR_TIMEOUT_SECONDS", default=60, cast=int)
WEBCAR_MAX_BYTES = config("WEBCAR_MAX_BYTES", default=200 * 1024 * 1024, cast=int)
# Dónde se guardan los CSV normalizados y el .duckdb de cada rentacar.
DATOS_DIR = Path(config("DATOS_DIR", default=str(BASE_DIR / "datos")))

# --- LLM ----------------------------------------------------------------------
# Cliente compatible con la API de OpenAI (chat completions + tool calling).
# Cambiando OPENAI_BASE_URL sirve cualquier proveedor compatible.
OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
OPENAI_BASE_URL = config("OPENAI_BASE_URL", default=None)
OPENAI_MODEL = config("OPENAI_MODEL", default="gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = config("OPENAI_TIMEOUT_SECONDS", default=120, cast=int)
# Vueltas máximas del bucle del agente (llamada al modelo → herramientas → …).
AGENTE_MAX_PASOS = config("AGENTE_MAX_PASOS", default=8, cast=int)
# Filas máximas que una consulta devuelve al modelo.
AGENTE_MAX_FILAS = config("AGENTE_MAX_FILAS", default=200, cast=int)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
}
