"""Azure OpenAI over plain HTTP, through the v1 API.

The v1 API takes the resource endpoint plus `/openai/v1/` and needs no `api-version`; the deployment name goes in the
`model` field; key authentication uses the `api-key` header. Chat Completions (`/openai/v1/chat/completions`) and the
Responses API (`/openai/v1/responses`, including the `web_search` tool with `filters.allowed_domains`) have the same
shapes as OpenAI's, so this provider reuses `OpenAIProvider` with a different base URL, header and request model.
Web search on Azure must be allowed for the subscription and sends queries to Grounding with Bing, outside the Azure
data boundary.
Sources: learn.microsoft.com/azure/foundry/openai/api-version-lifecycle and
learn.microsoft.com/azure/foundry/openai/how-to/web-search (checked 10 November 2026).

`model` is the model behind the deployment, recorded on each AI interaction; it defaults to the deployment name.
Tested only against httpx.MockTransport. Live calls are untested until the first real connection.
"""
import httpx

from app.ai.providers.openai import OpenAIProvider

AZURE_HOST_SUFFIXES = (".openai.azure.com", ".services.ai.azure.com", ".cognitiveservices.azure.com")


class AzureOpenAIProvider(OpenAIProvider):
    provider = "azure_openai"
    label = "Azure OpenAI"

    def __init__(self, *, api_key: str, endpoint: str, deployment: str, model: str | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(api_key=api_key, model=model or deployment, base_url=f"{endpoint.rstrip('/')}/openai/v1", transport=transport)
        self.deployment = deployment

    def _headers(self) -> dict:
        return {"api-key": self.api_key}

    def _request_model(self) -> str:
        return self.deployment
