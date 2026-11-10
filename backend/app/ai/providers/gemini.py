"""Google Gemini over plain HTTP (the Gemini API, not Vertex AI).

- JSON answers: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with the key in the
  `x-goog-api-key` header (never in the URL), `systemInstruction`, `contents`, and
  `generationConfig: {responseMimeType: "application/json", responseJsonSchema: <schema>, maxOutputTokens}`.
  The reply is `candidates[0].content.parts[].text`; `finishReason` "MAX_TOKENS" means it was cut off;
  `promptFeedback.blockReason` or a safety finish means the model declined. Tokens are in `usageMetadata`
  (`promptTokenCount`, `candidatesTokenCount`); the model actually used is `modelVersion`.
- Thinking: thought tokens count toward `maxOutputTokens`, so JSON answers ask for
  `generationConfig.thinkingConfig.thinkingLevel: "low"` and every call adds `REASONING_ALLOWANCE` to the caller's budget.
  Gemini 3.x and later take `thinkingLevel` (gemini-4-argon and gemini-3.8-flash: low, medium, high); a model that
  refuses it (HTTP 400 naming thinking, as Gemini 2.5 models may) or the larger budget is asked once more without it.
  Sources: firebase.google.com/docs/ai-logic/thinking and ai.google.dev/gemini-api/docs/thinking (checked 10 November 2026).
- Web research: the same endpoint with `tools: [{"google_search": {}}]` (Grounding with Google Search). The pages it
  used are `candidates[0].groundingMetadata.groundingChunks[].web.uri` and the queries it ran are
  `groundingMetadata.webSearchQueries`. Grounding has no domain filter, so the allowlist is written into the prompt and
  the refresh pipeline still marks anything off the allowlist as low confidence. Chunk URIs are usually Google redirect
  links (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/...`) rather than the publisher's page.
  `resolve_redirect` asks that host once per link, without following the redirect and without the API key, and reads the
  `Location` header, so the cited page is the publisher's and the allowlist check works as for the other providers. When
  that fails the chunk's `web.title` (normally the publisher's domain) stands in as `https://<domain>`.
- Model names at the time of writing (ai.google.dev/gemini-api/docs/generate-content/latest-model and the grounding
  guide, 10 November 2026): gemini-4-argon, gemini-3.8-flash. The model is free text, so a newer name works.

Tested only against httpx.MockTransport. Live calls are untested until the first real connection.
"""
from urllib.parse import urlparse

import httpx

from app.ai.client import AIError, AIReply
from app.ai.providers.base import HttpProvider, SearchReply, bare_domains, completion_budget, reply_json, setting, without

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DECLINED = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}
REDIRECT_HOST = "vertexaisearch.cloud.google.com"
REDIRECT_TIMEOUT = httpx.Timeout(5.0)
MAX_REDIRECTS_RESOLVED = 20


def is_redirect(uri: str) -> bool:
    p = urlparse(uri)
    return p.scheme == "https" and (p.hostname or "").lower() == REDIRECT_HOST and p.path.startswith("/grounding-api-redirect/")


def _target(location: str | None) -> str | None:
    p = urlparse(location or "")
    if p.scheme not in ("http", "https") or not p.hostname or p.hostname.lower() == REDIRECT_HOST:
        return None
    return location


def resolve_redirect(uri: str, transport: httpx.BaseTransport | None = None) -> str | None:
    """The page a grounding redirect points at, read from its Location header, or None. Only the redirect host is asked;
    the redirect is never followed, no API key or other credential is sent, and the timeout is short."""
    if not is_redirect(uri):
        return None
    try:
        with httpx.Client(transport=transport, timeout=REDIRECT_TIMEOUT, follow_redirects=False) as http:
            r = http.head(uri)
            if not r.is_redirect:  # some redirectors refuse HEAD: ask with GET, still without following
                with http.stream("GET", uri) as r:
                    return _target(r.headers.get("location")) if r.is_redirect else None
            return _target(r.headers.get("location"))
    except httpx.HTTPError:
        return None


def _title_page(title: str | None) -> str | None:
    """Gemini's chunk title is normally the publisher's domain; it stands in when a redirect cannot be resolved."""
    t = (title or "").strip().lower().rstrip(".")
    if not t or " " in t or "." not in t or "/" in t:
        return None
    return _target(f"https://{t}")


class GeminiProvider(HttpProvider):
    provider = "gemini"
    label = "Google Gemini"

    def __init__(self, *, api_key: str, model: str, base_url: str = GEMINI_BASE, transport: httpx.BaseTransport | None = None):
        super().__init__(api_key=api_key, model=model, transport=transport)
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key}

    def _call(self, body: dict, max_tokens: int) -> tuple[dict, dict, str]:
        fallbacks = (("thinking", without("generationConfig", "thinkingConfig")),
                     ("max_output_tokens", setting(("generationConfig", "maxOutputTokens"), max_tokens)),
                     ("maxOutputTokens", setting(("generationConfig", "maxOutputTokens"), max_tokens)))
        data = self._post(f"{self.base_url}/models/{self.model}:generateContent", body, fallbacks=fallbacks)
        if (data.get("promptFeedback") or {}).get("blockReason"):
            raise AIError("The model declined to answer this request.")
        cands = data.get("candidates") or []
        if not cands or not isinstance(cands[0], dict):
            raise AIError("The AI provider's reply could not be read.")
        cand = cands[0]
        finish = cand.get("finishReason")
        if finish == "MAX_TOKENS":
            raise AIError("The model's reply was too long and was cut off.")
        if finish in DECLINED:
            raise AIError("The model declined to answer this request.")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text") or "" for p in parts if isinstance(p, dict) and not p.get("thought"))
        return data, cand, text

    @staticmethod
    def _tokens(data: dict) -> tuple[int, int]:
        u = data.get("usageMetadata") or {}
        return int(u.get("promptTokenCount") or 0), int(u.get("candidatesTokenCount") or 0)

    def _body(self, system: str, prompt: str) -> dict:
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        body = self._body(system, prompt)
        body["generationConfig"] = {"responseMimeType": "application/json", "responseJsonSchema": schema, "maxOutputTokens": completion_budget(max_tokens),
                                    "thinkingConfig": {"thinkingLevel": "low"}}
        data, _, text = self._call(body, max_tokens)
        i, o = self._tokens(data)
        return AIReply(data=reply_json(text), model=data.get("modelVersion") or self.model, provider=self.provider, input_tokens=i, output_tokens=o)

    def search(self, *, system: str, prompt: str, allowed_domains: list[str], max_uses: int = 8, max_tokens: int = 16000) -> SearchReply:
        domains = bare_domains(allowed_domains)
        if domains:
            prompt = f"{prompt}\n\nUse only these sources and their subdomains: {', '.join(domains)}."
        body = self._body(system, prompt)
        body["tools"] = [{"google_search": {}}]
        body["generationConfig"] = {"maxOutputTokens": completion_budget(max_tokens)}
        data, cand, text = self._call(body, max_tokens)
        meta = cand.get("groundingMetadata") or {}
        cited: dict[str, list[str]] = {}
        resolved = 0
        for chunk in meta.get("groundingChunks") or []:
            web = ((chunk or {}).get("web") or {}) if isinstance(chunk, dict) else {}
            uri = web.get("uri")
            if uri and is_redirect(uri):
                page = None
                if resolved < MAX_REDIRECTS_RESOLVED:
                    resolved += 1
                    page = resolve_redirect(uri, self.transport)
                uri = page or _title_page(web.get("title")) or uri
            if uri:
                cited.setdefault(uri, [])
        i, o = self._tokens(data)
        return SearchReply(text=text, model=data.get("modelVersion") or self.model, provider=self.provider, input_tokens=i, output_tokens=o,
                           searches=len(meta.get("webSearchQueries") or []), cited=cited)
