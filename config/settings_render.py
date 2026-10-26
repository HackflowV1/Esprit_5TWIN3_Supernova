"""Explicit settings for the short-lived Render classroom demonstration."""
from .settings import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured

DEBUG = False
RENDER_DEMO_MODE = True
if SECRET_KEY == 'change-me-in-production' or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured('Set a generated DJANGO_SECRET_KEY in Render.')
hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
ALLOWED_HOSTS = [hostname] if hostname else []
CSRF_TRUSTED_ORIGINS = [f'https://{hostname}'] if hostname else []
MIDDLEWARE = [MIDDLEWARE[0], 'whitenoise.middleware.WhiteNoiseMiddleware', *MIDDLEWARE[1:]]
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
LANGUAGE_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 3600
X_FRAME_OPTIONS = 'DENY'
# Demo uploads are temporary on Render Free; private project files keep their
# existing permission-checked download views, outside the public media directory.
