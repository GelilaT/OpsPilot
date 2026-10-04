#!/bin/sh
# Default container command: the API. With RUN_WORKER=1 the job worker runs alongside it, which lets a single
# free Render web service do both. docker-compose and a dedicated worker service leave RUN_WORKER unset.
if [ "${RUN_WORKER:-0}" = "1" ]; then
  procrastinate --app=app.workers.app.app worker &
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips='*'
