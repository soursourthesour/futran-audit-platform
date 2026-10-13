#!/usr/bin/env bash
# Usage: scripts/makemigration.sh "message"  — autogenerates a migration against a scratch SQLite DB at head.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -u /tmp/fap-mig-XXXX.db)
export DATABASE_URL="sqlite:///$tmp"
.venv/bin/alembic upgrade head >/dev/null
.venv/bin/alembic revision --autogenerate -m "$1"
.venv/bin/alembic upgrade head >/dev/null
rm -f "$tmp"
