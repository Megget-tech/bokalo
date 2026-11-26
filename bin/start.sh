#!/usr/bin/env sh
# Startar allt i en enda container (Railway/Render): databasmigrering,
# bakgrundsworkern och webbservern.
#
# En gunicorn-process med trådar räcker gott för en förening och håller nere
# minnesanvändningen (Railway debiterar per använt GB RAM).
set -e
python manage.py migrate --noinput
python manage.py run_worker &
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_WORKERS:-1}" --threads "${WEB_THREADS:-4}" --worker-class gthread \
  --timeout 60 --access-logfile -
