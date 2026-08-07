"""Development settings — debug on, permissive hosts, optional SQLite fallback."""

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Trust any ngrok tunnel domain in dev so POST requests (login, checkout, etc.)
# don't get a 403 "Origin checking failed" when testing through a tunnel — ngrok's
# free-tier URL changes every time you restart it, so this covers all of them
# instead of needing to hardcode/update one URL each time.
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS + [
    "https://*.ngrok-free.dev",
    "https://*.ngrok-free.app",
    "https://*.ngrok.io",
    "https://*.ngrok.app",
]

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")

try:
    import debug_toolbar  # noqa: F401

    # INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    # MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1", "localhost"]
except ImportError:
    pass

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "floward-dev",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
