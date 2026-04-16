#!/bin/sh
set -e

if [ "${WAIT_FOR_DB:-1}" = "1" ]; then
  python manage.py wait_for_db
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${COLLECTSTATIC:-1}" = "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
