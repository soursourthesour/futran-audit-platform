#!/usr/bin/env bash
# Fresh database, reference data and test users, then serve the built app.
# Usage: start-server.sh PORT [late]. "late" loads ABC Corp at stage 6 and Meridian at stage 3 (see app.demo.seed_demo.e2e_late).
set -euo pipefail
PORT=${1:-8765}
MODE=${2:-fresh}
cd "$(dirname "$0")/../backend"
DB="e2e"; [ "$MODE" = "late" ] && DB="e2e-late"
export DATABASE_URL="sqlite:///./data/${DB}.db" FILE_STORE="local:./data/${DB}-files" MFA_REQUIRED=false EMAIL_MODE=outbox \
       SECRET_KEY="e2e-secret-key-0123456789abcdef" BASE_URL="http://127.0.0.1:${PORT}" DISABLE_SCHEDULER=true REFRESH_CLIENT=fake
rm -f "data/${DB}.db" "data/${DB}.db-wal" "data/${DB}.db-shm"
.venv/bin/alembic upgrade head >/dev/null
.venv/bin/python -m app.cli seed-reference >/dev/null
if [ "$MODE" = "late" ]; then
  .venv/bin/python -m app.cli seed-e2e --late > "data/${DB}.json"
else
  .venv/bin/python -m app.cli seed-e2e
fi
exec .venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port "$PORT" --log-level warning
