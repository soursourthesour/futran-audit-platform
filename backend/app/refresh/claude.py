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


class AnthropicStructuredClient:
    def __init__(self, settings: Settings):
        import anthropic

        self.settings = settings
        self.model = settings.claude_model
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def propose(self, *, system: str, prompt: str, schema: dict, allowed_domains: list[str]) -> ClaudeReply:
        tool = {"type": self.settings.claude_web_search_tool, "name": "web_search", "max_uses": self.settings.refresh_max_searches}
        if allowed_domains:
            tool["allowed_domains"] = allowed_domains[:100]
        msg = self.client.messages.create(
            model=self.model, max_tokens=16000, system=system, tools=[tool], messages=[{"role": "user", "content": prompt}],
            extra_body={"output_config": {"format": {"type": "json_schema", "schema": schema}}},
        )
        texts = [getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"]
        usage = getattr(msg, "usage", None)
        stu = getattr(usage, "server_tool_use", None) if usage else None
        return ClaudeReply(
            text=texts[-1] if texts else "", model=getattr(msg, "model", self.model),
            input_tokens=getattr(usage, "input_tokens", 0) or 0, output_tokens=getattr(usage, "output_tokens", 0) or 0,
            searches=getattr(stu, "web_search_requests", 0) or 0,
        )


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
