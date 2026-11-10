"""The stand-in for a saved connection under AI_PROVIDER_HTTP=fake (browser tests). Nothing reaches the network.

JSON answers come from the platform's demonstration model (`app.ai.fake`) but are recorded under the connected provider
and model, so a browser test can follow a connection through to the AI log. A key containing "invalid" is refused, so the
screen's error path can be shown without a real provider. Searches find nothing.
"""
from app.ai.client import AIError, AIReply, FakeAIClient
from app.ai.providers.base import ResearchThenStructure, SearchReply, TextResearch


class DemoProvider:
    def __init__(self, cfg):
        self.cfg = cfg
        self.provider = cfg.provider
        self.model = cfg.model
        self._fake = FakeAIClient(replies={"connection_test": {"ok": True}})

    def _check(self) -> None:
        if "invalid" in (self.cfg.api_key or "").lower():
            raise AIError("The AI provider refused the API key. Check the key and that it is active.")

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        self._check()
        r = self._fake.complete(task=task, system=system, prompt=prompt, schema=schema, context=context, max_tokens=max_tokens)
        return AIReply(data=r.data, model=self.model, provider=self.provider, input_tokens=r.input_tokens, output_tokens=r.output_tokens)

    def search(self, *, system: str, prompt: str, allowed_domains: list[str], max_uses: int = 8, max_tokens: int = 16000) -> SearchReply:
        self._check()
        return SearchReply(text="", model=self.model, provider=self.provider)

    def refresh_client(self, settings):
        return ResearchThenStructure(self, settings.refresh_max_searches)

    def drafting_client(self, settings):
        return TextResearch(self)
