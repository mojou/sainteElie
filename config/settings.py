"""
Configuration Django de Gestion Saint-Élie.

Les valeurs sensibles ou propres à l'environnement sont lues depuis les variables
d'environnement (voir .env.example). Les valeurs par défaut conviennent au
développement local uniquement.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Charge un fichier .env minimal (CLE=valeur) sans dépendance externe."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return str(env(key, default)).lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    return [v.strip() for v in env(key, default).split(",") if v.strip()]


# Sécurisé par défaut : le mode debug doit être activé explicitement (fichier .env local).
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key-a-changer-en-production")
if not DEBUG and SECRET_KEY.startswith("dev-"):
    raise RuntimeError("DJANGO_SECRET_KEY doit être défini en production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")
ETABLISSEMENT_NOM = env("ETABLISSEMENT_NOM", "Complexe St Élie Palace")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "hotel",
    "caisse",
    "personnel",
    "paie",
    "stock",
    "finances",
    "projets",
    "fiches",
    "postes",
    "vitrine",
    "rapports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.SecretProvisoireMiddleware",
    "accounts.verrouillage.VerrouillageMiddleware",
    "vitrine.middleware.EspaceClientMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.envois.EnvoiUniqueMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = env("DB_ENGINE", "sqlite3")
if DB_ENGINE == "sqlite3":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {
        "default": {
            "ENGINE": f"django.db.backends.{DB_ENGINE}",
            "NAME": env("DB_NAME", "gestion_st_elie"),
            "USER": env("DB_USER", ""),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", ""),
        }
    }

# Cache partagé par tous les processus du serveur (un hébergeur en lance souvent plusieurs) : sans lui, un
# formulaire envoyé deux fois ou la limite des réservations en ligne ne seraient vérifiés que processus par processus.
# Table créée par `python manage.py createcachetable` (les tests la créent seuls).
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache_application",
                      "OPTIONS": {"MAX_ENTRIES": 5000}}}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:connexion"
LOGIN_REDIRECT_URL = "core:accueil"
LOGOUT_REDIRECT_URL = "core:accueil"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Documents archivés (reçus de remise, rapports, fiches de paie, justificatifs) :
# hors de tout dossier servi par le serveur web, lus uniquement via des vues qui vérifient les droits.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", str(BASE_DIR / "private_media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sécurité ---------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
# Page expirée : une phrase simple et retour à la page, au lieu de l'erreur technique « CSRF » (voir core/envois.py).
CSRF_FAILURE_VIEW = "core.envois.echec_csrf"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_AGE = 60 * 60 * 12  # une journée de travail
# Écran verrouillé après ce nombre de minutes sans toucher l'écran ni le clavier (0 = jamais) ; on reprend
# avec son code PIN, ou une collègue prend la place avec le sien (ordinateur partagé de la réception, tablette du bar).
VERROUILLAGE_MINUTES = int(env("VERROUILLAGE_MINUTES", "10"))
# Au-delà de ce montant (FCFA), l'application demande « C'est bien ça ? » avant d'enregistrer de l'argent reçu.
MONTANT_A_CONFIRMER = int(env("MONTANT_A_CONFIRMER", "100000"))
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

MESSAGE_TAGS = {40: "error", 30: "warning", 25: "success", 20: "info"}

# Tests : hachage rapide des mots de passe et codes PIN (sans effet hors de `manage.py test`).
if len(sys.argv) > 1 and sys.argv[1] == "test":
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
