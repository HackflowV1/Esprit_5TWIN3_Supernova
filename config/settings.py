"""
Django settings for HackFlow project.
Configured for isolated HackFlow PostgreSQL development.
"""

import os
from .database import database_config
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # HackFlow apps
    'accounts',
    'core',
    'hackathons',
    'teams',
    'mentoring',
    'projects',
    'evaluations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'core.middleware.PreferredLanguageMiddleware',
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
        'DIRS': [
            BASE_DIR / 'projects' / 'integration_templates',
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.interface',
                'mentoring.context_processors.mentor_menu',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Fail closed: no migration, test or server may target another project's database.
DATABASES = {'default': database_config(os.environ.get('DATABASE_URL', 'postgresql://postgres@127.0.0.1:5432/hackflow_db'))}

# Custom user model
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:profile'
LOGOUT_REDIRECT_URL = 'hackathons:list'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'fr'
LANGUAGES = [('fr', 'Français'), ('en', 'English')]
LOCALE_PATHS = [
    BASE_DIR / 'locale',
    BASE_DIR / 'projects' / 'locale',
]
LANGUAGE_COOKIE_NAME = 'hackflow_language'
LANGUAGE_COOKIE_SAMESITE = 'Lax'
TIME_ZONE = 'Africa/Tunis'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AI services — environment variables prepared for future integration
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
# Fast model first, a second one when Google answers 'high demand' (503)
GEMINI_MODELS = [m.strip() for m in os.environ.get('GEMINI_MODELS', 'gemini-3.5-flash,gemini-flash-lite-latest,gemini-3-flash-preview').split(',') if m.strip()]

HACKFLOW_METRIC_PROVIDERS = {
    'M2': 'teams.services.metrics',
    'M3': 'projects.services.metrics',
}

# Project uploads are kept separate from the shared media root.
PROJECT_FILES_ROOT = BASE_DIR / 'projects' / 'private_files'

# M2: local-only inference. Download deliberately with prepare_m2_matching.
M2_MATCHING_ENABLED = os.environ.get('M2_MATCHING_ENABLED', '1') == '1'
M2_MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
M2_MODEL_CACHE = Path(os.environ.get('M2_MODEL_CACHE', str(BASE_DIR / '.cache' / 'm2-model')))
M2_SKILL_MODEL_PATH = Path(os.environ.get('M2_SKILL_MODEL_PATH', str(BASE_DIR / 'artifacts' / 'team-skill-needs' / 'v1' / 'classifier.json')))
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'm2_embeddings': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': BASE_DIR / '.cache' / 'm2-embeddings',
        'TIMEOUT': 60 * 60 * 24 * 7,
        'OPTIONS': {'MAX_ENTRIES': 10000},
    },
}
