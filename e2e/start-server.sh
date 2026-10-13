#!/usr/bin/env bash
# Fresh database, reference data and an e2e admin, then serve the built app.
set -euo pipefail
PORT=${1:-8765}
cd "$(dirname "$0")/../backend"
export DATABASE_URL="sqlite:///./data/e2e.db" FILE_STORE="local:./data/e2e-files" MFA_REQUIRED=false EMAIL_MODE=outbox \
       SECRET_KEY="e2e-secret-key-0123456789abcdef" BASE_URL="http://127.0.0.1:${PORT}" DISABLE_SCHEDULER=true
rm -f data/e2e.db data/e2e.db-wal data/e2e.db-shm
.venv/bin/alembic upgrade head >/dev/null
.venv/bin/python -m app.cli seed-reference >/dev/null
.venv/bin/python -m app.cli seed-e2e
exec .venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port "$PORT" --log-level warning
