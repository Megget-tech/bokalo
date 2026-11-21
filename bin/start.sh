#!/usr/bin/env sh
# Startar bakgrundsworkern och webbservern i samma container (en Render-tjänst).
# Workern stämmer av dörrbehörigheter varje minut och synkar medlemmar på natten.
set -e
python manage.py run_worker &
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 60
