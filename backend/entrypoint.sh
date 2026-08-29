#!/bin/sh
# Container entrypoint: apply migrations before the app starts serving
# traffic, then hand off to the command passed in (gunicorn by
# default; overridable for one-off management commands).
set -e

python manage.py migrate --noinput

exec "$@"
