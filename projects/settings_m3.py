"""Opt-in M3 development settings; the team's config stays untouched."""
from copy import deepcopy
from config.settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, 'projects']  # noqa: F405
ROOT_URLCONF = 'projects.urls_m3'
PROJECT_FILES_ROOT = BASE_DIR / 'projects' / 'private_files'  # noqa: F405
HACKFLOW_METRIC_PROVIDERS = {**HACKFLOW_METRIC_PROVIDERS, 'M3': 'projects.services.metrics'}  # noqa: F405
LOCALE_PATHS = [BASE_DIR / 'projects' / 'locale', *LOCALE_PATHS]  # noqa: F405

# The M3 preview layers navigation over the shared base without editing it.
# Django's same-name inheritance resolves the parent from the next directory.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]['DIRS'] = [BASE_DIR / 'projects' / 'integration_templates', *TEMPLATES[0]['DIRS']]  # noqa: F405
