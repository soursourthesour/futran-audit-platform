"""OpenAI over plain HTTP (httpx; the platform adds no SDK).

- JSON answers: Chat Completions, `POST https://api.openai.com/v1/chat/completions`, `Authorization: Bearer <key>`, with
  `response_format: {"type": "json_schema", "json_schema": {"name", "schema", "strict": false}}` and
  `max_completion_tokens` (reasoning models refuse `max_tokens`). Reasoning tokens count against that limit, so the
  request asks for `reasoning_effort: "low"` (Chat Completions' name; the Responses API's is `reasoning.effort`) and adds
  `REASONING_ALLOWANCE` to the caller's budget; a model that refuses either (HTTP 400 naming it) is asked once more
  without it. Source: developers.openai.com/api/docs/guides/reasoning (checked 10 November 2026). Web research keeps
  the model's default effort (it decides what to search) and gets the same larger budget. The reply is `choices[0].message.content`; a
  `finish_reason` of "length" means the JSON was cut off and `message.refusal` means the model declined.
  Strict mode is off because the platform's schemas do not all list every property as required; callers validate the
  reply themselves.
- Web research: the Responses API, `POST https://api.openai.com/v1/responses`, with the `web_search` tool and
  `filters.allowed_domains` (no scheme; at most 100; subdomains included) and `include: ["web_search_call.action.sources"]`.
  The reply's `output` holds `web_search_call` items and a `message` whose `output_text` carries `url_citation`
  annotations (url, title, start_index, end_index into the model's own text). Those offsets point at the model's
  sentences, not at a passage of the page, so pages are reported without passages.
  Source: developers.openai.com/api/docs/guides/tools-web-search (checked 10 November 2026).
- Model names at the time of writing (developers.openai.com/api/docs/models, 10 November 2026): gpt-6-astra
  (recommended default), gpt-6.1-sol, gpt-6.1-terra, gpt-6-luna. The model is free text, so a newer name works.

Tested only against httpx.MockTransport. Live calls are untested until the first real connection.
"""
import httpx

from app.ai.client import AIError, AIReply
from app.ai.providers.base import HttpProvider, SearchReply, bare_domains, completion_budget, reply_json, setting, without

OPENAI_BASE = "https://api.openai.com/v1"


class OpenAIProvider(HttpProvider):
    provider = "openai"
    label = "OpenAI"

    def __init__(self, *, api_key: str, model: str, base_url: str = OPENAI_BASE, transport: httpx.BaseTransport | None = None):
        super().__init__(api_key=api_key, model=model, transport=transport)
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request_model(self) -> str:
        return self.model

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        body = {"model": self._request_model(), "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema, "strict": False}},
                "max_completion_tokens": completion_budget(max_tokens), "reasoning_effort": "low"}
        data = self._post(f"{self.base_url}/chat/completions", body,
                          fallbacks=(("reasoning_effort", without("reasoning_effort")), ("max_completion_tokens", setting(("max_completion_tokens",), max_tokens))))
        choices = data.get("choices") or []
        if not choices:
            raise AIError("The AI provider's reply could not be read.")
        choice = choices[0] or {}
        msg = choice.get("message") or {}
        if msg.get("refusal"):
            raise AIError("The model declined to answer this request.")
        if choice.get("finish_reason") == "length":
            raise AIError("The model's reply was too long and was cut off.")
        usage = data.get("usage") or {}
        return AIReply(data=reply_json(msg.get("content")), model=data.get("model") or self.model, provider=self.provider,
                       input_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0))

    def search(self, *, system: str, prompt: str, allowed_domains: list[str], max_uses: int = 8, max_tokens: int = 16000) -> SearchReply:
        tool: dict = {"type": "web_search"}
        domains = bare_domains(allowed_domains)
        if domains:
            tool["filters"] = {"allowed_domains": domains}
        body: dict = {"model": self._request_model(), "input": prompt, "tools": [tool], "include": ["web_search_call.action.sources"],
                      "max_output_tokens": completion_budget(max_tokens), "max_tool_calls": max_uses}
        if system:
            body["instructions"] = system
        data = self._post(f"{self.base_url}/responses", body, fallbacks=(("max_output_tokens", setting(("max_output_tokens",), max_tokens)),))
        texts: list[str] = []
        cited: dict[str, list[str]] = {}
        searches = 0
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "web_search_call":
                searches += 1
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                texts.append(part.get("text") or "")
                for a in part.get("annotations") or []:
                    if isinstance(a, dict) and a.get("type") == "url_citation" and a.get("url"):
                        cited.setdefault(a["url"], [])
        if data.get("status") == "incomplete" and not texts:
            raise AIError("The model's reply was too long and was cut off.")
        usage = data.get("usage") or {}
        return SearchReply(text="".join(texts), model=data.get("model") or self.model, provider=self.provider, input_tokens=int(usage.get("input_tokens") or 0),
                           output_tokens=int(usage.get("output_tokens") or 0), searches=searches, cited=cited)
