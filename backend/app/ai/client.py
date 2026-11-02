"""The one model adapter for the platform's AI features (wave 3 plan, AI rule 5).

`AIClient.complete` sends a system prompt and a user prompt and asks for JSON that matches `schema`
(`output_config.format`, see platform.claude.com/docs/en/build-with-claude/structured-outputs). No tools and no web
search: the model reads only the text the platform puts in the prompt. The reply must be JSON; free text is refused
(AIError) and never read. Callers check every quote against the source text themselves (AI rule 2), so the citations
feature is not used (it cannot be combined with structured output).

`FakeAIClient` is the in-process fake for tests, the demo and the browser tests (AI_CLIENT=fake). Without a canned
reply it answers with the deterministic handlers in `app.ai.fake`, which only ever quote text they were given.
"""
import json
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings


class AIError(RuntimeError):
    """The model could not be reached, or its reply was not the JSON asked for."""


@dataclass
class AIReply:
    data: dict
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0


class AIClient(Protocol):
    model: str
    provider: str

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply: ...


def parse_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise AIError("The model's reply was not the JSON the platform asked for.") from None
    if not isinstance(data, dict):
        raise AIError("The model's reply was not a JSON object.")
    return data


class AnthropicAIClient:
    provider = "anthropic"

    def __init__(self, settings: Settings, client=None):
        self.model = settings.ai_model or settings.claude_model
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.client = client

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        try:
            msg = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}],
                                              extra_body={"output_config": {"format": {"type": "json_schema", "schema": schema}}})
        except Exception as e:  # noqa: BLE001 - any SDK or network failure is reported the same way
            raise AIError(f"The model could not be reached: {type(e).__name__}.") from e
        texts = [getattr(b, "text", "") for b in getattr(msg, "content", []) if getattr(b, "type", "") == "text"]
        usage = getattr(msg, "usage", None)
        return AIReply(data=parse_json(texts[-1] if texts else ""), model=getattr(msg, "model", None) or self.model, provider=self.provider,
                       input_tokens=getattr(usage, "input_tokens", 0) or 0, output_tokens=getattr(usage, "output_tokens", 0) or 0)


@dataclass
class FakeAIClient:
    """Canned replies by task (a dict, or a callable taking the call's context); otherwise `app.ai.fake` answers."""

    replies: dict = field(default_factory=dict)
    model: str = "fake-ai"
    provider: str = "fake"
    calls: list = field(default_factory=list)

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        self.calls.append({"task": task, "system": system, "prompt": prompt, "schema": schema, "context": context})
        if task in self.replies:
            reply = self.replies[task]
            reply = reply(context or {}) if callable(reply) else reply
        else:
            from app.ai.fake import answer

            reply = answer(task, context or {})
        if isinstance(reply, str):
            reply = parse_json(reply)
        return AIReply(data=reply, model=self.model, provider=self.provider, input_tokens=len(prompt) // 4, output_tokens=len(json.dumps(reply)) // 4)


def client_for(app_state, settings: Settings) -> AIClient | None:
    """An injected factory (pytest), the fake (AI_CLIENT=fake: demo and browser tests), else Anthropic when a key is set.
    None when no model is available."""
    factory = getattr(app_state, "ai_client_factory", None) if app_state is not None else None
    if factory is not None:
        return factory(settings)
    if settings.ai_client == "fake":
        return FakeAIClient()
    if settings.anthropic_api_key:
        return AnthropicAIClient(settings)
    return None
