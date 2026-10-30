"""The fake Claude client for the demo and the browser tests (REFRESH_CLIENT=fake). It never calls the network and
does no research: every proposal it makes says so in its summary, so nobody mistakes it for a real finding."""
import json
import re

from app.refresh.claude import FakeRefreshClient, cites_of

NOTE = "Test client proposal, not research"


def _records(prompt: str) -> list[dict]:
    m = re.search(r"Approved records \(JSON\):\n(.*?)\n\nSource allowlist:", prompt, re.S)
    try:
        return json.loads(m.group(1)) if m else []
    except json.JSONDecodeError:
        return []


def _first_source(prompt: str) -> str | None:
    m = re.search(r"Source allowlist:\n- [^:\n]+: (https?://\S+)", prompt)
    return m.group(1) if m else None


def _reply(prompt: str) -> dict:
    recs = _records(prompt)
    src = _first_source(prompt)
    if not recs or not src:
        return {"changes": []}
    r = recs[0]
    if "case_id" in r:
        return {"changes": [{"change_type": "case_update", "case_id": r["case_id"], "field_path": "case.stage_note", "old_value": r.get("stage_note"),
                             "new_value": f"{NOTE}: check the docket", "summary": f"{NOTE}: stage note for {r['name']}", "source_url": src,
                             "source_quote": "Placeholder quote from the test client.", "confidence": "high"}]}
    return {"changes": [
        {"change_type": "guidance", "regulation_id": r["regulation_id"], "field_path": "law.litigation_text", "old_value": None,
         "new_value": f"{NOTE}.", "summary": f"{NOTE}: litigation note for {r['short_name']}", "source_url": src,
         "source_quote": "Placeholder quote from the test client.", "confidence": "high"},
        {"change_type": "effective_date", "regulation_id": r["regulation_id"], "field_path": "law.effective_text", "old_value": None,
         "new_value": f"{NOTE}: date to confirm", "summary": f"{NOTE}: effective date wording for {r['short_name']}", "source_url": "https://example.org/test-client",
         "source_quote": "Placeholder quote from the test client.", "confidence": "medium"},
    ]}


class DemoClient(FakeRefreshClient):
    def propose(self, *, system, prompt, schema, allowed_domains):
        self.replies = {}
        reply = super().propose(system=system, prompt=prompt, schema=schema, allowed_domains=allowed_domains)
        made = _reply(prompt)
        reply.text, reply.cited = json.dumps(made), cites_of(made)
        return reply


def demo_client() -> FakeRefreshClient:
    return DemoClient(replies={}, model="test client (no network)")
