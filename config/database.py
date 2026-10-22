"""Pure configuration parser: only the isolated local HackFlow database is accepted."""
from urllib.parse import urlsplit, unquote
from django.core.exceptions import ImproperlyConfigured


def database_config(value):
    message = 'DATABASE_URL must target local PostgreSQL hackflow_db on port 5432 without query options.'
    try:
        url = urlsplit(value)
        if (url.scheme not in ('postgres', 'postgresql') or url.path != '/hackflow_db'
                or url.hostname not in ('127.0.0.1', 'localhost') or (url.port or 5432) != 5432
                or url.query or url.fragment):
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured(message) from None
    return {
        'ENGINE': 'django.db.backends.postgresql', 'NAME': 'hackflow_db',
        'USER': unquote(url.username or 'postgres'), 'PASSWORD': unquote(url.password or ''),
        'HOST': url.hostname, 'PORT': url.port or 5432,
        'TEST': {'NAME': 'test_hackflow_db'},
    }
