# Futran Audit Platform — working notes for Claude

- Specs: `docs/spec/Futran_Audit_Platform_Build_Schematic.md` (decisions, overrides) then `docs/spec/Futran_Audit_Platform_Developer_Spec_v0.2.md`.
- Plan: `docs/superpowers/plans/2026-10-13-futran-audit-platform.md`. Ledger (git-ignored): `.superpowers/sdd/2026-10-13-futran-audit-platform/progress.md`.
- Backend: `cd backend && .venv/bin/pytest`. New domain: add module to `app/models_registry.py` and `app/routers_registry.py`. Migrations: `backend/scripts/makemigration.sh "msg"`.
- Frontend: `cd frontend && npm run build` (outputs to backend/app/static).
- Tenant comes from the session only. Every endpoint calls `authorize`. Audit log is append-only.
- Copy: plain professional English, sentence case, no filler. Python >= 3.11 compatible.
- Work on branch `build/v1`; push after every task.
