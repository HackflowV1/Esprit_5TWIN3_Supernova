#!/usr/bin/env bash
set -euo pipefail
uv run --no-sync python manage.py migrate --noinput
uv run --no-sync python manage.py seed_render_demo
exec .venv/bin/gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 2 --timeout 120 --access-logfile - --error-logfile -
