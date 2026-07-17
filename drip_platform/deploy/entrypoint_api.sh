#!/usr/bin/env bash
# API entrypoint: wait for DB -> migrate (as superuser) -> bootstrap app_rw ->
# start uvicorn (as app_rw). Runs once; worker/scheduler wait on the api.
set -euo pipefail

echo "[api] waiting for postgres…"
python - <<'PY'
import os, time, sqlalchemy as sa
url = os.environ["MIGRATE_DATABASE_URL"]
for i in range(60):
    try:
        sa.create_engine(url).connect().close(); print("[api] db up"); break
    except Exception as e:
        time.sleep(2)
else:
    raise SystemExit("[api] db never came up")
PY

echo "[api] running migrations (superuser)…"
DATABASE_URL="$MIGRATE_DATABASE_URL" alembic upgrade head

echo "[api] bootstrapping app_rw role + grants…"
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  "host=postgres user=postgres dbname=drip" \
  -v app_pw="${APP_DB_PASSWORD}" -f deploy/bootstrap.sql

echo "[api] starting uvicorn (runtime = app_rw, RLS enforced)…"
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
