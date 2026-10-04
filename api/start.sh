#!/bin/sh
# Default container command: the API. Set RUN_WORKER=1 to also run the job worker inside it (see app.main).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips='*'
