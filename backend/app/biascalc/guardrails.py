"""GenAI guardrail tests (spec §21 F11, Phase 4; wave 3 plan: fake adapter only by default).

The fake adapter answers in-process and is what tests, the demo and the browser tests use. A live run calls the client's
own endpoint and is refused unless the platform setting GUARDRAIL_TESTS_LIVE is true and the client's written permission
(a note and the signed file) is recorded on the run. Results are suggestions for question 8.1.05 and checklist 8.4 until
an auditor accepts them.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.biascalc.models import GuardrailTestRun
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.systems.models import AISystem
from app.tenancy.models import User

PROMPTS = Path(__file__).with_name("guardrail_prompts.yaml")
FAKE_FAILS = ("PI-02", "PE-01")  # the fake chatbot lets one injection and one PII echo through, so the screen shows both outcomes
REFUSAL = "I can't help with that request. I can answer questions about open roles and the application process."


@lru_cache(maxsize=1)
def prompt_set() -> dict:
    return yaml.safe_load(PROMPTS.read_text())


def evaluate(prompt: dict, reply: str) -> tuple[bool, str]:
    text = (reply or "").casefold()
    hit = next((m for m in prompt["fail_if_contains"] if m.casefold() in text), None)
    return (False, f'The reply contained "{hit}".') if hit else (True, "No marker in the reply.")


class FakeAdapter:
    """A sandbox chatbot that refuses everything except the prompts in FAKE_FAILS, which it echoes."""

    def send(self, prompt: dict) -> str:
        if prompt["id"] in FAKE_FAILS:
            return f"Sure. {prompt['prompt']} {' '.join(prompt['fail_if_contains'])}"
        return REFUSAL


class LiveAdapter:
    """POSTs {"message": prompt} to the client's sandbox endpoint and reads the reply text. Never used in tests."""

    def __init__(self, url: str, timeout: float = 20.0):
        self.url, self.timeout = url, timeout

    def send(self, prompt: dict) -> str:
        import httpx

        r = httpx.post(self.url, json={"message": prompt["prompt"]}, timeout=self.timeout)
        r.raise_for_status()
        try:
            body = r.json()
            return str(body.get("reply") or body.get("message") or body.get("text") or body)
        except ValueError:
            return r.text


def summary(run: GuardrailTestRun) -> dict:
    return {"question": "8.1.05", "answer": "yes", "checklist": "8.4", "text": f"Prompt set {run.prompt_set_version}: {run.passed_count} passed, {run.failed_count} failed."}


def run_out(db: Session, run: GuardrailTestRun) -> dict:
    who = db.get(User, run.run_by) if run.run_by else None
    return {"id": run.id, "adapter": run.adapter, "endpoint_label": run.endpoint_label, "prompt_set_version": run.prompt_set_version, "results": run.results, "passed_count": run.passed_count,
            "failed_count": run.failed_count, "status": run.status, "run_by": who.name if who else None, "run_at": run.run_at.isoformat() if run.run_at else None,
            "decision_note": run.decision_note, "suggestion": summary(run)}


def runs_for(db: Session, s: AISystem) -> list[GuardrailTestRun]:
    return list(db.scalars(select(GuardrailTestRun).where(GuardrailTestRun.ai_system_id == s.id, GuardrailTestRun.deleted_at.is_(None)).order_by(GuardrailTestRun.run_at.desc())))


def run(db: Session, settings, actor: User, s: AISystem, body: dict) -> GuardrailTestRun:
    e = db.get(Engagement, s.engagement_id)
    live = body.get("live") is True
    label = " ".join(str(body.get("endpoint_label") or "").split())[:300] or None
    note = str(body.get("permission_note") or "").strip()[:4000] or None
    file_id = body.get("permission_file_id") or None
    if live:
        if not getattr(settings, "guardrail_tests_live", False):
            raise Conflict("Live guardrail tests are switched off. A platform administrator turns them on with GUARDRAIL_TESTS_LIVE=true.")
        errs = []
        url = str(body.get("endpoint_url") or "").strip()
        if not url.startswith("https://"):
            errs.append({"field": "endpoint_url", "message": "Enter the client's sandbox endpoint (https)."})
        if not note:
            errs.append({"field": "permission_note", "message": "Record the client's written permission to test this system."})
        f = db.get(FileObject, file_id) if isinstance(file_id, str) else None
        if f is None or f.deleted_at is not None or f.engagement_id != e.id:
            errs.append({"field": "permission_file_id", "message": "Attach the signed permission from this engagement's files."})
        if errs:
            raise Invalid(errors=errs)
        adapter = LiveAdapter(url)
    else:
        adapter = FakeAdapter()
    ps = prompt_set()
    results = []
    for p in ps["prompts"]:
        reply = adapter.send(p)
        ok, reason = evaluate(p, reply)
        results.append({"id": p["id"], "category": p["category"], "title": p["title"], "passed": ok, "reason": reason, "excerpt": reply[:300]})
    r = GuardrailTestRun(organization_id=e.client_id, engagement_id=e.id, ai_system_id=s.id, prompt_set_version=str(ps["version"]), adapter="live" if live else "fake",
                         endpoint_label=label, permission_note=note, permission_file_id=file_id if live else None, results=results, passed_count=sum(x["passed"] for x in results),
                         failed_count=sum(not x["passed"] for x in results), run_by=actor.id, run_at=utcnow(), created_by=actor.id)
    db.add(r)
    db.flush()
    audit.record(db, actor_id=actor.id, action="guardrail_test.run", obj=r, after={"adapter": r.adapter, "passed": r.passed_count, "failed": r.failed_count},
                 summary=f"Ran guardrail tests on {s.reference_id} {s.name} ({r.adapter})")
    return r


def get(db: Session, run_id: str) -> GuardrailTestRun:
    r = db.get(GuardrailTestRun, run_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    return r


def decide(db: Session, actor: User, r: GuardrailTestRun, decision: str | None, note: str | None) -> dict:
    """Accept records 8.1.05 (prompt injection testing: yes) where the question applies; reject needs a reason."""
    from app.questionnaire.service import Target, save_response

    if r.status != "suggested":
        raise Conflict("This run has already been decided.")
    note = " ".join(str(note or "").split())[:2000] or None
    if decision not in ("accept", "reject"):
        raise Invalid(errors=[{"field": "decision", "message": "Accept or reject the results."}])
    if decision == "reject" and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say why the results are rejected."}])
    r.status, r.decided_by, r.decided_at, r.decision_note = ("accepted" if decision == "accept" else "rejected"), actor.id, utcnow(), note
    answer = None
    if decision == "accept":
        s, e = db.get(AISystem, r.ai_system_id), db.get(Engagement, r.engagement_id)
        try:
            with db.begin_nested():
                save_response(db, actor, Target(e, s), "8.1.05", {"value": "yes", "status": "answered", "detail": summary(r)["text"]}, futran=True)
            answer = {"applied": ["8.1.05"], "skipped": []}
        except (Invalid, NotFound, Conflict) as exc:
            answer = {"applied": [], "skipped": [{"code": "8.1.05", "reason": exc.detail}]}
    audit.record(db, actor_id=actor.id, action=f"guardrail_test.{r.status}", obj=r, after={"note": note}, summary=f"{r.status.capitalize()} guardrail test results")
    return run_out(db, r) | {"answer": answer}
