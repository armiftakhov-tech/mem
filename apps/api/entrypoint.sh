#!/bin/sh
set -e
# AGENTS.md §7.3, §22: миграции до старта; при ошибке контейнер падает, а не стартует без схемы.
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10
