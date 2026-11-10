"""Anthropic Claude as a connected provider, through the `anthropic` SDK the platform already uses.

JSON answers use `AnthropicAIClient` (structured outputs, `output_config.format`); law and litigation refresh use
`AnthropicStructuredClient` (web search, then a JSON call); Draft with AI uses `AnthropicClaudeClient` (web search,
free text). This module only feeds them the saved key and model instead of ANTHROPIC_API_KEY and CLAUDE_MODEL.
"""
from app.ai.client import AnthropicAIClient


class AnthropicProvider(AnthropicAIClient):
    label = "Anthropic Claude"

    def __init__(self, settings, *, api_key: str, model: str, client=None):
        super().__init__(settings, client=client, api_key=api_key, model=model)
        self.settings = settings
        self.api_key = api_key

    def __repr__(self) -> str:  # the key stays out of logs and tracebacks
        return f"{type(self).__name__}(model={self.model!r})"

    def refresh_client(self, settings):
        from app.refresh.claude import AnthropicStructuredClient

        return AnthropicStructuredClient(settings, api_key=self.api_key, model=self.model)

    def drafting_client(self, settings):
        from app.laws.refresh import AnthropicClaudeClient

        return AnthropicClaudeClient(settings, api_key=self.api_key, model=self.model)
