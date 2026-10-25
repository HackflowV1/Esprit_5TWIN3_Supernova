"""Every run gets an isolated PostgreSQL database; never reuse colleagues' test DB."""
from copy import deepcopy
from uuid import uuid4
from config.settings import *  # noqa: F403

DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES['default']['TEST']['NAME'] = 'test_hackflow_m5_' + uuid4().hex[:16]
