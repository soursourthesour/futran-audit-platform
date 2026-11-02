"""AI foundation (spec §21 rules; wave 3 plan "Rules for every AI-powered feature"): the AIInteraction and Obligation
records, the engagement switch, Response.source, and the single model adapter with its in-process fake."""
import json
from types import SimpleNamespace as NS

import pytest

from app.core.config import Settings


def test_ai_interaction_and_obligation_tables_exist(db):
    from app.ai.models import AIInteraction, Obligation

    i = AIInteraction(organization_id="org-1", engagement_id=None, feature="copilot_prefill", call_id="call-1", model="fake-ai", provider="fake", prompt_version="prefill-1",
                      input_refs=[{"type": "file", "id": "f1"}], output={"answer": "yes"}, citations=[{"file_id": "f1", "page": 2, "quote": "x", "found": True}], confidence="high", status="suggested")
    db.add(i)
    db.flush()
    assert i.decided_by is None and i.reason is None and i.status == "suggested"
    cols = set(Obligation.__table__.c.keys())
    assert {"regulation_id", "text", "actor", "citation", "effective_date", "control_ids", "question_ids", "status", "approved_by"} <= cols


def test_engagement_ai_switch_and_response_source_columns(db):
    from app.engagements.models import Engagement
    from app.questionnaire.models import Response

    assert Engagement.__table__.c.ai_features_enabled.nullable
    assert Response.__table__.c.source.nullable


# ---- the adapter
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}


class StubMessages:
    def __init__(self, text):
        self.text, self.calls = text, []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(model="claude-test", usage=NS(input_tokens=900, output_tokens=40), stop_reason="end_turn", content=[NS(type="text", text=self.text)])


def test_anthropic_adapter_asks_for_schema_json_without_tools():
    from app.ai.client import AnthropicAIClient

    stub = StubMessages(json.dumps({"answer": "yes"}))
    c = AnthropicAIClient(Settings(anthropic_api_key="k", secret_key="x" * 40), client=NS(messages=stub))
    reply = c.complete(task="ask", system="You read documents.", prompt="Question?", schema=SCHEMA)
    assert reply.data == {"answer": "yes"} and reply.model == "claude-test" and reply.input_tokens == 900 and reply.provider == "anthropic"
    call = stub.calls[0]
    assert call["extra_body"]["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert "tools" not in call  # no web search: the model reads only what the platform gives it


def test_anthropic_adapter_rejects_free_text():
    from app.ai.client import AIError, AnthropicAIClient

    c = AnthropicAIClient(Settings(anthropic_api_key="k", secret_key="x" * 40), client=NS(messages=StubMessages("Sure! The answer is yes.")))
    with pytest.raises(AIError):
        c.complete(task="ask", system="s", prompt="p", schema=SCHEMA)


def test_client_for_prefers_injected_factory_then_fake_then_anthropic():
    from app.ai.client import AnthropicAIClient, FakeAIClient, client_for

    injected = FakeAIClient()
    assert client_for(NS(ai_client_factory=lambda s: injected), Settings(secret_key="x" * 40)) is injected
    assert isinstance(client_for(NS(), Settings(secret_key="x" * 40, ai_client="fake")), FakeAIClient)
    assert client_for(NS(), Settings(secret_key="x" * 40, ai_client="anthropic", anthropic_api_key=None)) is None
    assert isinstance(client_for(NS(), Settings(secret_key="x" * 40, ai_client="anthropic", anthropic_api_key="k")), AnthropicAIClient)


def test_fake_returns_canned_replies_and_records_calls():
    from app.ai.client import FakeAIClient

    fake = FakeAIClient(replies={"ask": {"answer": "From the canned reply."}})
    r = fake.complete(task="ask", system="s", prompt="p", schema=SCHEMA, context={"question": "q"})
    assert r.data == {"answer": "From the canned reply."} and r.provider == "fake" and fake.calls[0]["task"] == "ask"
    fn = FakeAIClient(replies={"ask": lambda ctx: {"answer": ctx["question"].upper()}})
    assert fn.complete(task="ask", system="s", prompt="p", schema=SCHEMA, context={"question": "why"}).data == {"answer": "WHY"}
