"""The live Claude adapter for the refresh pipeline, against a stand-in for the Anthropic SDK.

The API refuses JSON output (output_config.format) together with citations, and web search always returns citations
(platform.claude.com/docs: structured-outputs "Incompatible with: Citations … The API returns a 400 error";
web-search-tool "Citations are always enabled for web search"). So the adapter researches with web search first, then
asks for the JSON in a second call without tools, giving it the research and the passages the searches cited.
"""
import json
from types import SimpleNamespace as NS

import pytest

from app.core.config import Settings
from app.refresh.claude import AnthropicStructuredClient

SCHEMA = {"type": "object", "properties": {"changes": {"type": "array", "items": {"type": "object"}}}, "required": ["changes"], "additionalProperties": False}
URL = "https://www.ilga.gov/legislation/publicacts/fulltext.asp?Name=104-0001"
QUOTE = "This Act takes effect January 1, 2027."
ANSWER = {"changes": [{"field_path": "law.effective_on", "source_url": URL, "source_quote": QUOTE}]}


def _usage(i, o, searches=0):
    return NS(input_tokens=i, output_tokens=o, server_tool_use=NS(web_search_requests=searches))


class FakeMessages:
    def __init__(self):
        self.calls = []
        self.research_turns = 0

    def create(self, **kw):
        self.calls.append(kw)
        has_search = any(t.get("name") == "web_search" for t in kw.get("tools") or [])
        has_json = "output_config" in (kw.get("extra_body") or {}) or "output_config" in kw
        if has_search and has_json:
            raise AssertionError("400: citations are not supported with output_config.format")
        if has_search:
            self.research_turns += 1
            if self.research_turns == 1:  # the API pauses a long search turn; the adapter must send it back unchanged
                return NS(stop_reason="pause_turn", model="claude-test", usage=_usage(1000, 50, 2),
                          content=[NS(type="server_tool_use", name="web_search", input={"query": "Illinois HB 3773 effective date"})])
            return NS(stop_reason="end_turn", model="claude-test", usage=_usage(2000, 300, 1), content=[
                NS(type="text", text="The Illinois act now takes effect on 1 January 2027. ", citations=None),
                NS(type="text", text="It says so in section 99.", citations=[NS(type="web_search_result_location", url=URL, title="Public Act 104-0001", cited_text=QUOTE)]),
            ])
        assert has_json, "the second call must ask for JSON"
        return NS(stop_reason="end_turn", model="claude-test", usage=_usage(500, 120), content=[NS(type="text", text=json.dumps(ANSWER), citations=None)])


@pytest.fixture
def adapter():
    fake = FakeMessages()
    a = AnthropicStructuredClient(Settings(anthropic_api_key="test", secret_key="x" * 40), client=NS(messages=fake))
    return a, fake


def test_search_and_json_are_never_in_the_same_request(adapter):
    a, fake = adapter
    reply = a.propose(system="Keep the master current.", prompt="Jurisdiction code: US-IL\nRecords: …", schema=SCHEMA, allowed_domains=["ilga.gov"])
    assert json.loads(reply.text) == ANSWER
    research, structure = [c for c in fake.calls if c.get("tools")], [c for c in fake.calls if not c.get("tools")]
    assert len(structure) == 1 and research
    assert research[0]["tools"][0]["allowed_domains"] == ["ilga.gov"]


def test_a_paused_search_turn_is_continued(adapter):
    a, fake = adapter
    a.propose(system="s", prompt="Jurisdiction code: US-IL", schema=SCHEMA, allowed_domains=["ilga.gov"])
    second = [c for c in fake.calls if c.get("tools")][1]
    assert second["messages"][-1]["role"] == "assistant"  # the paused turn goes back as it came


def test_the_json_step_sees_the_research_and_the_cited_passages(adapter):
    a, fake = adapter
    a.propose(system="s", prompt="Jurisdiction code: US-IL", schema=SCHEMA, allowed_domains=["ilga.gov"])
    structure = [c for c in fake.calls if not c.get("tools")][0]
    text = json.dumps(structure["messages"])
    assert "1 January 2027" in text and URL in text and QUOTE in text
    assert "Jurisdiction code: US-IL" in text  # the records and rules travel with it


def test_usage_adds_up_across_both_steps(adapter):
    a, _ = adapter
    reply = a.propose(system="s", prompt="Jurisdiction code: US-IL", schema=SCHEMA, allowed_domains=[])
    assert (reply.input_tokens, reply.output_tokens, reply.searches) == (3500, 470, 3)
    assert reply.model == "claude-test"


def test_the_reply_carries_the_pages_and_passages_web_search_cited(adapter):
    """The JSON step has no tools, so its links and quotes are checked later against what the searches really cited."""
    a, _ = adapter
    reply = a.propose(system="s", prompt="Jurisdiction code: US-IL", schema=SCHEMA, allowed_domains=["ilga.gov"])
    assert reply.cited == {URL: [QUOTE]}
