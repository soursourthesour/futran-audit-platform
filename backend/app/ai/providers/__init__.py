"""The AI providers the Futran Admin can connect (F1, 11-03 notes). One platform-wide connection (plan ruling).

`CATALOGUE` is what the settings screen offers; `build(cfg, settings, transport)` makes the provider object for a saved
connection. Anthropic goes through the `anthropic` SDK already installed; the others are called over httpx.
Model names are free text: the suggestions below are the providers' current names on 10 November 2026 (sources in each
module's docstring) and go stale, which is why any name is accepted.
"""
from dataclasses import dataclass

CATALOGUE: list[dict] = [
    {"id": "anthropic", "label": "Anthropic Claude", "needs_endpoint": False,
     "models": ["claude-sonnet-5-5", "claude-opus-5-5"], "key_help": "An API key from the Claude Console (platform.claude.com), starting sk-ant-."},
    {"id": "openai", "label": "OpenAI", "needs_endpoint": False,
     "models": ["gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"], "key_help": "A project API key from the OpenAI platform, starting sk-."},
    {"id": "azure_openai", "label": "Azure OpenAI", "needs_endpoint": True,
     "models": ["gpt-6-astra", "gpt-6.1-sol", "gpt-5.5"], "key_help": "Key 1 or Key 2 from the Azure OpenAI resource's Keys and Endpoint page."},
    {"id": "gemini", "label": "Google Gemini", "needs_endpoint": False,
     "models": ["gemini-4-argon", "gemini-3.8-flash"], "key_help": "An API key from Google AI Studio (the Gemini API, not Vertex AI)."},
]
LABELS = {p["id"]: p["label"] for p in CATALOGUE} | {"fake": "Demonstration model"}


@dataclass
class ConnectionConfig:
    provider: str
    model: str
    api_key: str
    endpoint: str | None = None
    deployment: str | None = None


def build(cfg: ConnectionConfig, settings, transport=None):
    """The provider for a saved connection. Under AI_PROVIDER_HTTP=fake (browser tests) the demonstration stand-in
    answers instead, so nothing reaches the network."""
    if getattr(settings, "ai_provider_http", "live") == "fake":
        from app.ai.providers.demo import DemoProvider

        return DemoProvider(cfg)
    if cfg.provider == "anthropic":
        from app.ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(settings, api_key=cfg.api_key, model=cfg.model)
    if cfg.provider == "openai":
        from app.ai.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=cfg.api_key, model=cfg.model, transport=transport)
    if cfg.provider == "azure_openai":
        from app.ai.providers.azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider(api_key=cfg.api_key, endpoint=cfg.endpoint or "", deployment=cfg.deployment or cfg.model, model=cfg.model, transport=transport)
    if cfg.provider == "gemini":
        from app.ai.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=cfg.api_key, model=cfg.model, transport=transport)
    raise ValueError(f"unknown AI provider {cfg.provider!r}")
