"""Pure configuration parser: only the isolated local HackFlow database is accepted."""
from urllib.parse import urlsplit, unquote, parse_qs
import re
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


def render_database_config(value):
    """Explicit Render settings only; never relax the local database guard."""
    try:
        url = urlsplit(value)
        name = unquote(url.path.lstrip('/'))
        host = url.hostname or ''
        options = parse_qs(url.query, keep_blank_values=True)
        if (url.scheme not in ('postgres', 'postgresql') or not url.username or not url.password
                or not re.fullmatch(r'hackflow_db(?:_[a-z0-9]+)?', name)
                or not re.fullmatch(r'dpg-[a-z0-9-]+(?:\.[a-z0-9-]+\.postgres\.render\.com)?', host)
                or (url.port or 5432) != 5432 or url.fragment
                or options not in ({}, {'sslmode': ['require']})):
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured('Render deployment requires its dedicated hackflow_db PostgreSQL connection URL.') from None
    return {
        'ENGINE': 'django.db.backends.postgresql', 'NAME': name,
        'USER': unquote(url.username), 'PASSWORD': unquote(url.password),
        'HOST': host, 'PORT': url.port or 5432,
        'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {'sslmode': 'require', 'connect_timeout': 15},
    }
