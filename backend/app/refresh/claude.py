"""Claude adapter for the refresh pipeline (spec §25.3 steps 2–3).

`StructuredClaude.propose` sends one jurisdiction's records and source allowlist and gets back JSON that must match the
ProposedChange[] schema. Web search is limited to the allowlisted domains. The backend validates the reply again
(pipeline.validate); a reply that is not schema-valid JSON is rejected, never read as free text.

`FakeRefreshClient` is the in-process fake used by tests, the demo and the browser tests (REFRESH_CLIENT=fake).
"""
import json
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings


@dataclass
class ClaudeReply:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0


class StructuredClaude(Protocol):
    model: str

    def propose(self, *, system: str, prompt: str, schema: dict, allowed_domains: list[str]) -> ClaudeReply: ...


RESEARCH_NOTE = ("First research only. Search the allowlisted sources and write plain notes: for each change you find, the record it "
                 "affects, the old and new value, and the page it comes from. Do not write JSON yet.")
STRUCTURE_NOTE = ("Turn the research below into the JSON the schema describes. Use only changes the research supports. Each source_url must "
                  "be one of the cited pages listed, and each source_quote must be copied from that page's cited passage. If the research "
                  "found nothing, reply with an empty list of changes.")
MAX_PAUSES = 4  # a long search turn can pause; it is sent back unchanged up to this many times


class AnthropicStructuredClient:
    """Two calls per jurisdiction. The API refuses JSON output together with citations, and web search always cites, so
    the first call researches with web search and the second turns that research into schema-checked JSON, with no tools.
    See platform.claude.com/docs/en/build-with-claude/structured-outputs (Incompatible with: Citations) and
    platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool (Citations are always enabled for web search)."""

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.model = settings.claude_model
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.client = client

    def propose(self, *, system: str, prompt: str, schema: dict, allowed_domains: list[str]) -> ClaudeReply:
        tool = {"type": self.settings.claude_web_search_tool, "name": "web_search", "max_uses": self.settings.refresh_max_searches}
        if allowed_domains:
            tool["allowed_domains"] = allowed_domains[:100]
        totals = {"in": 0, "out": 0, "searches": 0}
        model = self.model

        def count(msg) -> None:
            nonlocal model
            usage = getattr(msg, "usage", None)
            stu = getattr(usage, "server_tool_use", None) if usage else None
            totals["in"] += getattr(usage, "input_tokens", 0) or 0
            totals["out"] += getattr(usage, "output_tokens", 0) or 0
            totals["searches"] += getattr(stu, "web_search_requests", 0) or 0
            model = getattr(msg, "model", None) or model

        # 1. Research with web search (free text with citations).
        messages: list[dict] = [{"role": "user", "content": f"{prompt}\n\n{RESEARCH_NOTE}"}]
        notes: list[str] = []
        cited: dict[str, list[str]] = {}
        for _ in range(MAX_PAUSES + 1):
            msg = self.client.messages.create(model=self.model, max_tokens=16000, system=system, tools=[tool], messages=messages)
            count(msg)
            for b in msg.content:
                if getattr(b, "type", "") != "text":
                    continue
                notes.append(getattr(b, "text", "") or "")
                for c in getattr(b, "citations", None) or []:
                    url, quote = getattr(c, "url", None), getattr(c, "cited_text", None)
                    if url and quote and quote not in cited.setdefault(url, []):
                        cited[url].append(quote)
            if getattr(msg, "stop_reason", "") != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": msg.content}]

        # 2. Structure the research as JSON (no tools, so no citations).
        sources = "\n".join(f"- {url}\n" + "\n".join(f"    \"{q}\"" for q in quotes) for url, quotes in cited.items()) or "- none"
        content = f"{prompt}\n\n{STRUCTURE_NOTE}\n\nResearch:\n{''.join(notes).strip() or '(no findings)'}\n\nCited pages and passages:\n{sources}"
        msg = self.client.messages.create(
            model=self.model, max_tokens=16000, system=system, messages=[{"role": "user", "content": content}],
            extra_body={"output_config": {"format": {"type": "json_schema", "schema": schema}}},
        )
        count(msg)
        texts = [getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"]
        return ClaudeReply(text=texts[-1] if texts else "", model=model, input_tokens=totals["in"], output_tokens=totals["out"], searches=totals["searches"])


@dataclass
class FakeRefreshClient:
    """Returns canned replies by jurisdiction code (law runs) or `litigation:<code>` (litigation runs).
    A reply is a dict (sent back as JSON) or a str (sent back as is, to test free-text rejection)."""

    replies: dict = field(default_factory=dict)
    model: str = "fake-claude"
    tokens: tuple[int, int] = (12000, 1500)
    searches: int = 3
    calls: list = field(default_factory=list)

    def propose(self, *, system: str, prompt: str, schema: dict, allowed_domains: list[str]) -> ClaudeReply:
        key = _key_from(prompt)
        self.calls.append({"key": key, "prompt": prompt, "system": system, "allowed_domains": allowed_domains})
        reply = self.replies.get(key, {"changes": []})
        if callable(reply):
            reply = reply(prompt)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return ClaudeReply(text=text, model=self.model, input_tokens=self.tokens[0], output_tokens=self.tokens[1], searches=self.searches)


def _key_from(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("Jurisdiction code: "):
            return line.split(": ", 1)[1].strip()
    return ""


def client_for(app_state, settings: Settings) -> StructuredClaude | None:
    """The client a run uses: an injected factory (tests), the fake (REFRESH_CLIENT=fake: demo, browser tests),
    else Anthropic when a key is set. None when refresh cannot run."""
    factory = getattr(app_state, "refresh_client_factory", None) if app_state is not None else None
    if factory is not None:
        return factory(settings)
    if settings.refresh_client == "fake":
        from app.refresh.demo import demo_client

        return demo_client()
    if settings.anthropic_api_key:
        return AnthropicStructuredClient(settings)
    return None
