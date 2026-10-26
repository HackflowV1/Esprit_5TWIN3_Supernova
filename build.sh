#!/usr/bin/env bash
set -euo pipefail
python -m pip install 'uv>=0.9,<0.10'
uv sync --frozen --no-dev
uv run --no-sync python scripts/download_m2_model.py
uv run --no-sync python manage.py collectstatic --noinput
uv run --no-sync python manage.py check --deploy --fail-level ERROR
