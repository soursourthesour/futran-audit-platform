"""Google Gemini over plain HTTP (the Gemini API, not Vertex AI).

- JSON answers: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with the key in the
  `x-goog-api-key` header (never in the URL), `systemInstruction`, `contents`, and
  `generationConfig: {responseMimeType: "application/json", responseJsonSchema: <schema>, maxOutputTokens}`.
  The reply is `candidates[0].content.parts[].text`; `finishReason` "MAX_TOKENS" means it was cut off;
  `promptFeedback.blockReason` or a safety finish means the model declined. Tokens are in `usageMetadata`
  (`promptTokenCount`, `candidatesTokenCount`); the model actually used is `modelVersion`.
- Web research: the same endpoint with `tools: [{"google_search": {}}]` (Grounding with Google Search). The pages it
  used are `candidates[0].groundingMetadata.groundingChunks[].web.uri` and the queries it ran are
  `groundingMetadata.webSearchQueries`. Grounding has no domain filter, so the allowlist is written into the prompt and
  the refresh pipeline still marks anything off the allowlist as low confidence. Chunk URIs can be Google redirect links
  rather than the publisher's page; such a link never matches an allowlisted page, so those changes stay low confidence.
- Model names at the time of writing (ai.google.dev/gemini-api/docs/generate-content/latest-model and the grounding
  guide, 10 November 2026): gemini-4-argon, gemini-3.8-flash. The model is free text, so a newer name works.

Tested only against httpx.MockTransport. Live calls are untested until the first real connection.
"""
import httpx

from app.ai.client import AIError, AIReply
from app.ai.providers.base import HttpProvider, SearchReply, bare_domains, reply_json

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DECLINED = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}


class GeminiProvider(HttpProvider):
    provider = "gemini"
    label = "Google Gemini"

    def __init__(self, *, api_key: str, model: str, base_url: str = GEMINI_BASE, transport: httpx.BaseTransport | None = None):
        super().__init__(api_key=api_key, model=model, transport=transport)
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key}

    def _call(self, body: dict) -> tuple[dict, dict, str]:
        data = self._post(f"{self.base_url}/models/{self.model}:generateContent", body)
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
        body["generationConfig"] = {"responseMimeType": "application/json", "responseJsonSchema": schema, "maxOutputTokens": max_tokens}
        data, _, text = self._call(body)
        i, o = self._tokens(data)
        return AIReply(data=reply_json(text), model=data.get("modelVersion") or self.model, provider=self.provider, input_tokens=i, output_tokens=o)

    def search(self, *, system: str, prompt: str, allowed_domains: list[str], max_uses: int = 8, max_tokens: int = 16000) -> SearchReply:
        domains = bare_domains(allowed_domains)
        if domains:
            prompt = f"{prompt}\n\nUse only these sources and their subdomains: {', '.join(domains)}."
        body = self._body(system, prompt)
        body["tools"] = [{"google_search": {}}]
        body["generationConfig"] = {"maxOutputTokens": max_tokens}
        data, cand, text = self._call(body)
        meta = cand.get("groundingMetadata") or {}
        cited: dict[str, list[str]] = {}
        for chunk in meta.get("groundingChunks") or []:
            uri = ((chunk or {}).get("web") or {}).get("uri") if isinstance(chunk, dict) else None
            if uri:
                cited.setdefault(uri, [])
        i, o = self._tokens(data)
        return SearchReply(text=text, model=data.get("modelVersion") or self.model, provider=self.provider, input_tokens=i, output_tokens=o,
                           searches=len(meta.get("webSearchQueries") or []), cited=cited)
