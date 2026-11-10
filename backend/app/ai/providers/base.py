"""What every model provider shares (F1, 11-03 notes: "refresh with LLM of choice").

A provider does two things:

- `complete(...)` asks for JSON matching a schema and returns an `AIReply` (the copilot, obligations, questionnaires,
  Explain this question, the connection test).
- `search(...)` researches with the provider's own web search and returns plain text plus the pages it cited
  (law refresh, the litigation tracker, Draft with AI).

The HTTP providers (OpenAI, Azure OpenAI, Gemini) go through `HttpProvider._post`, which turns every failure into an
`AIError` with a fixed, generic message. Provider error bodies are never read into a message: they can echo a key, a
prompt or an internal detail. `ResearchThenStructure` and `TextResearch` adapt any provider to the refresh pipeline's
`propose(...)` and the drafting `research(prompt)` interfaces.
"""
from dataclasses import dataclass, field

import httpx

from app.ai.client import AIError, AIReply, parse_json

TIMEOUT = httpx.Timeout(180.0, connect=15.0)  # a web-search turn can take minutes


@dataclass
class SearchReply:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    # pages the search cited, each with the passages it quoted from them. The HTTP providers name pages but not passages,
    # so their lists are empty and the refresh pipeline treats every quote as unconfirmed (low confidence, second review).
    cited: dict[str, list[str]] = field(default_factory=dict)


STATUS_MESSAGES = {
    401: "The AI provider refused the API key. Check the key and that it is active.",
    403: "The AI provider refused the API key. Check the key and that it is active.",
    404: "The AI provider does not recognise this model or deployment. Check the name.",
    408: "The AI provider took too long to answer. Try again.",
    429: "The AI provider reported too many requests or no remaining quota. Try again later or check the account's limits.",
}


def status_message(status: int) -> str:
    if status in STATUS_MESSAGES:
        return STATUS_MESSAGES[status]
    if status >= 500:
        return "The AI provider is unavailable at the moment. Try again later."
    return f"The AI provider rejected the request (HTTP {status}). Check the model name and the provider's settings."


def bare_domains(domains: list[str]) -> list[str]:
    """Allowlist entries as the providers' domain filters want them: no scheme, no path, at most 100."""
    out: list[str] = []
    for d in domains or []:
        d = str(d).strip().lower()
        for prefix in ("https://", "http://"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        d = d.split("/", 1)[0]
        if d and d not in out:
            out.append(d)
    return out[:100]


class HttpProvider:
    provider = "http"
    label = "AI provider"

    def __init__(self, *, api_key: str, model: str, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model
        self.transport = transport

    def __repr__(self) -> str:  # the key stays out of logs and tracebacks
        return f"{type(self).__name__}(model={self.model!r})"

    def _headers(self) -> dict:
        raise NotImplementedError

    def _post(self, url: str, body: dict) -> dict:
        try:
            with httpx.Client(transport=self.transport, timeout=TIMEOUT) as http:
                r = http.post(url, json=body, headers={**self._headers(), "Content-Type": "application/json"})
        except httpx.TimeoutException:
            raise AIError(STATUS_MESSAGES[408]) from None
        except httpx.HTTPError as e:
            raise AIError(f"The AI provider could not be reached ({type(e).__name__}). Check the endpoint and the network.") from None
        if r.status_code >= 400:
            raise AIError(status_message(r.status_code))
        try:
            data = r.json()
        except ValueError:
            raise AIError("The AI provider's reply could not be read.") from None
        if not isinstance(data, dict):
            raise AIError("The AI provider's reply could not be read.")
        return data

    def complete(self, *, task: str, system: str, prompt: str, schema: dict, context: dict | None = None, max_tokens: int = 8000) -> AIReply:
        raise NotImplementedError

    def search(self, *, system: str, prompt: str, allowed_domains: list[str], max_uses: int = 8, max_tokens: int = 16000) -> SearchReply:
        raise NotImplementedError

    def refresh_client(self, settings):
        return ResearchThenStructure(self, settings.refresh_max_searches)

    def drafting_client(self, settings):
        return TextResearch(self)


def reply_json(text: str | None) -> dict:
    return parse_json(text or "")


RESEARCH_NOTE = ("First research only. Search the allowlisted sources and write plain notes: for each change you find, the record it "
                 "affects, the old and new value, and the page it comes from. Do not write JSON yet.")
STRUCTURE_NOTE = ("Turn the research below into the JSON the schema describes. Use only changes the research supports. Each source_url must "
                  "be one of the cited pages listed, and each source_quote must be copied from that page. If the research found nothing, "
                  "reply with an empty list of changes.")


class ResearchThenStructure:
    """The refresh pipeline's `propose(...)` on any provider: one web-search call for notes, then one JSON call that turns
    the notes into the schema (no tools). Returns the shape of `app.refresh.claude.ClaudeReply`."""

    def __init__(self, provider: HttpProvider, max_searches: int = 8):
        self.p = provider
        self.model = provider.model
        self.provider = provider.provider
        self.max_searches = max_searches

    def propose(self, *, system: str, prompt: str, schema: dict, allowed_domains: list[str]):
        from app.refresh.claude import ClaudeReply

        found = self.p.search(system=system, prompt=f"{prompt}\n\n{RESEARCH_NOTE}", allowed_domains=allowed_domains, max_uses=self.max_searches)
        pages = "\n".join(f"- {url}" for url in found.cited) or "- none"
        content = f"{prompt}\n\n{STRUCTURE_NOTE}\n\nResearch:\n{found.text.strip() or '(no findings)'}\n\nCited pages:\n{pages}"
        out = self.p.complete(task="refresh_structure", system=system, prompt=content, schema=schema, max_tokens=16000)
        import json

        return ClaudeReply(text=json.dumps(out.data), model=out.model or found.model, input_tokens=found.input_tokens + out.input_tokens,
                           output_tokens=found.output_tokens + out.output_tokens, searches=found.searches, cited=dict(found.cited), provider=self.provider)


class TextResearch:
    """Draft with AI's `research(prompt) -> str` on any provider (web search, free text the drafting code parses)."""

    def __init__(self, provider: HttpProvider, max_searches: int = 8):
        self.p = provider
        self.model = provider.model
        self.provider = provider.provider
        self.max_searches = max_searches

    def research(self, prompt: str) -> str:
        return self.p.search(system="", prompt=prompt, allowed_domains=[], max_uses=self.max_searches, max_tokens=8000).text
