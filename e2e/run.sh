#!/usr/bin/env bash
# Build the web app and run the Playwright suite. Usage: e2e/run.sh [spec-file ...]
set -euo pipefail
cd "$(dirname "$0")"
(cd ../frontend && npm run build >/dev/null)
export PW_CHROMIUM=${PW_CHROMIUM:-$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}
npx playwright test "$@"
