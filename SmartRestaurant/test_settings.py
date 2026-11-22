"""Test runner settings — SQLite in-memory DB, local memory cache, local files."""
import os
import tempfile

# The production settings refuse to start with DEBUG off and no secret key.
# Tests run in debug mode so they need no environment setup.
os.environ.setdefault("DJANGO_DEBUG", "True")

from SmartRestaurant.settings import *  # noqa: E402, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# The local-memory cache is shared by the whole test run, so real auth limits
# would make unrelated tests fail with 429. Tests that check throttling set
# their own rates.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
        **{
            scope: "100000/minute"
            for scope in (
                "auth_otp_send",
                "auth_otp_verify",
                "auth_register",
                "auth_password_login",
                "auth_password_reset",
            )
        },
    },
}

MEDIA_ROOT = tempfile.mkdtemp()
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
AWS_STORAGE_BUCKET_NAME = ""
AWS_ACCESS_KEY_ID = ""
AWS_SECRET_ACCESS_KEY = ""
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
UPLOADS_DIRECT = True

# Websocket tests run in one process: no Redis needed. (The real settings
# build a redis:// URL from REDIS_HOST/REDIS_PORT, which tests do not set.)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}
