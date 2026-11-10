"""F1 (11-03 notes): the non-Anthropic providers, called over httpx and tested only against httpx.MockTransport.

Each test checks the request the platform sends (URL, auth header, body shape) and how the reply is read. No test reaches
the network. Provider error bodies are never repeated: they can echo a key or an internal detail."""
import json

import httpx
import pytest

from app.ai.client import AIError

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
SECRET = "sk-live-0123456789abcdef"


def recorder(reply, status=200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = reply(request) if callable(reply) else reply
        return httpx.Response(status, json=body)

    return seen, httpx.MockTransport(handler)


def body_of(req: httpx.Request) -> dict:
    return json.loads(req.content)


# ---- OpenAI
def chat_reply(content, finish="stop", model="gpt-test-2026"):
    return {"id": "c1", "model": model, "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


def test_openai_complete_sends_chat_completions_with_a_json_schema():
    from app.ai.providers.openai import OpenAIProvider

    seen, t = recorder(chat_reply('{"answer": "yes"}'))
    p = OpenAIProvider(api_key=SECRET, model="gpt-test", transport=t)
    r = p.complete(task="ask", system="Be exact.", prompt="Is it?", schema=SCHEMA, max_tokens=900)
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions" and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    b = body_of(req)
    assert b["model"] == "gpt-test" and b["max_completion_tokens"] == 900
    assert b["messages"] == [{"role": "system", "content": "Be exact."}, {"role": "user", "content": "Is it?"}]
    assert b["response_format"]["type"] == "json_schema" and b["response_format"]["json_schema"]["schema"] == SCHEMA
    assert r.data == {"answer": "yes"} and r.provider == "openai" and r.model == "gpt-test-2026" and (r.input_tokens, r.output_tokens) == (120, 30)


@pytest.mark.parametrize("reply,message", [
    (chat_reply("Sure, the answer is yes."), "not the JSON"),
    (chat_reply('{"answer": "ye', finish="length"), "cut off"),
    ({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None, "refusal": "I can't help."}}]}, "declined"),
])
def test_openai_refuses_free_text_cut_off_and_refusals(reply, message):
    from app.ai.providers.openai import OpenAIProvider

    _, t = recorder(reply)
    with pytest.raises(AIError, match=message):
        OpenAIProvider(api_key=SECRET, model="gpt-test", transport=t).complete(task="ask", system="s", prompt="p", schema=SCHEMA)


@pytest.mark.parametrize("status,message", [(401, "refused the API key"), (403, "refused the API key"), (404, "model or deployment"), (429, "too many requests"),
                                            (500, "unavailable"), (400, "rejected the request")])
def test_provider_errors_are_generic_and_never_echo_the_body(status, message):
    from app.ai.providers.openai import OpenAIProvider

    body = {"error": {"message": f"Incorrect API key provided: {SECRET}. Internal trace 9f8e."}}
    _, t = recorder(body, status=status)
    with pytest.raises(AIError) as ex:
        OpenAIProvider(api_key=SECRET, model="gpt-test", transport=t).complete(task="ask", system="s", prompt="p", schema=SCHEMA)
    assert message in str(ex.value) and SECRET not in str(ex.value) and "9f8e" not in str(ex.value)


def test_network_failure_is_reported_without_detail():
    from app.ai.providers.openai import OpenAIProvider

    def boom(request):
        raise httpx.ConnectError(f"connection to {request.url} failed", request=request)

    with pytest.raises(AIError, match="could not be reached"):
        OpenAIProvider(api_key=SECRET, model="gpt-test", transport=httpx.MockTransport(boom)).complete(task="ask", system="s", prompt="p", schema=SCHEMA)


def responses_reply():
    text = "Illinois amended the Act. It takes effect January 1, 2027."
    return {"model": "gpt-test-2026", "usage": {"input_tokens": 5000, "output_tokens": 400},
            "output": [{"type": "web_search_call", "id": "ws_1", "status": "completed", "action": {"type": "search", "query": "Illinois AI Act"}},
                       {"type": "web_search_call", "id": "ws_2", "status": "completed", "action": {"type": "open_page"}},
                       {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": [
                           {"type": "url_citation", "start_index": 0, "end_index": 25, "url": "https://www.ilga.gov/act?id=1", "title": "ILGA"},
                           {"type": "url_citation", "start_index": 26, "end_index": len(text), "url": "https://www.ilga.gov/act?id=1", "title": "ILGA"}]}]}]}


def test_openai_search_uses_the_responses_web_search_tool_limited_to_the_allowlist():
    from app.ai.providers.openai import OpenAIProvider

    seen, t = recorder(responses_reply())
    r = OpenAIProvider(api_key=SECRET, model="gpt-test", transport=t).search(system="Research.", prompt="What changed?", allowed_domains=["ilga.gov", "https://www.ftc.gov/"], max_uses=5)
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/responses"
    b = body_of(req)
    assert b["model"] == "gpt-test" and b["instructions"] == "Research." and b["input"] == "What changed?"
    assert b["tools"] == [{"type": "web_search", "filters": {"allowed_domains": ["ilga.gov", "www.ftc.gov"]}}]
    assert "web_search_call.action.sources" in b["include"]
    assert "takes effect January 1, 2027" in r.text and r.searches == 2 and (r.input_tokens, r.output_tokens) == (5000, 400)
    # the provider names the pages it used but not the passages on them, so no quote can be confirmed from its reply
    assert r.cited == {"https://www.ilga.gov/act?id=1": []} and r.provider == "openai"


# ---- Azure OpenAI
def test_azure_calls_the_v1_endpoint_with_the_deployment_and_an_api_key_header():
    from app.ai.providers.azure_openai import AzureOpenAIProvider

    seen, t = recorder(chat_reply('{"answer": "ok"}', model="gpt-test-2026"))
    p = AzureOpenAIProvider(api_key=SECRET, endpoint="https://futran-ai.openai.azure.com/", deployment="audit-gpt", model="gpt-test", transport=t)
    r = p.complete(task="ask", system="s", prompt="p", schema=SCHEMA)
    req = seen[0]
    assert str(req.url) == "https://futran-ai.openai.azure.com/openai/v1/chat/completions"
    assert req.headers["api-key"] == SECRET and "authorization" not in req.headers
    assert body_of(req)["model"] == "audit-gpt"
    assert r.provider == "azure_openai" and r.data == {"answer": "ok"} and r.model == "gpt-test-2026"


def test_azure_search_posts_to_the_v1_responses_path():
    from app.ai.providers.azure_openai import AzureOpenAIProvider

    seen, t = recorder(responses_reply())
    AzureOpenAIProvider(api_key=SECRET, endpoint="https://futran-ai.openai.azure.com", deployment="audit-gpt", transport=t).search(
        system="s", prompt="p", allowed_domains=["ilga.gov"], max_uses=3)
    assert str(seen[0].url) == "https://futran-ai.openai.azure.com/openai/v1/responses" and body_of(seen[0])["model"] == "audit-gpt"


# ---- Google Gemini
def gemini_reply(text, finish="STOP", grounding=None):
    cand = {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
    if grounding:
        cand["groundingMetadata"] = grounding
    return {"candidates": [cand], "usageMetadata": {"promptTokenCount": 210, "candidatesTokenCount": 40}, "modelVersion": "gemini-test-001"}


def test_gemini_complete_asks_for_json_matching_the_schema():
    from app.ai.providers.gemini import GeminiProvider

    seen, t = recorder(gemini_reply('{"answer": "yes"}'))
    r = GeminiProvider(api_key=SECRET, model="gemini-test", transport=t).complete(task="ask", system="Be exact.", prompt="Is it?", schema=SCHEMA, max_tokens=700)
    req = seen[0]
    assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert req.headers["x-goog-api-key"] == SECRET and SECRET not in str(req.url)
    b = body_of(req)
    assert b["systemInstruction"] == {"parts": [{"text": "Be exact."}]} and b["contents"] == [{"role": "user", "parts": [{"text": "Is it?"}]}]
    assert b["generationConfig"] == {"responseMimeType": "application/json", "responseJsonSchema": SCHEMA, "maxOutputTokens": 700}
    assert r.data == {"answer": "yes"} and r.provider == "gemini" and r.model == "gemini-test-001" and (r.input_tokens, r.output_tokens) == (210, 40)


def test_gemini_reports_a_cut_off_or_blocked_reply():
    from app.ai.providers.gemini import GeminiProvider

    _, t = recorder(gemini_reply('{"answer": "y', finish="MAX_TOKENS"))
    with pytest.raises(AIError, match="cut off"):
        GeminiProvider(api_key=SECRET, model="gemini-test", transport=t).complete(task="ask", system="s", prompt="p", schema=SCHEMA)
    _, t = recorder({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(AIError, match="declined"):
        GeminiProvider(api_key=SECRET, model="gemini-test", transport=t).complete(task="ask", system="s", prompt="p", schema=SCHEMA)


def test_gemini_search_grounds_with_google_search_and_lists_the_pages():
    from app.ai.providers.gemini import GeminiProvider

    grounding = {"webSearchQueries": ["Illinois AI Act amendment", "Illinois HB 3773"],
                 "groundingChunks": [{"web": {"uri": "https://www.ilga.gov/act?id=1", "title": "ilga.gov"}}, {"web": {"uri": "https://www.ftc.gov/x", "title": "ftc.gov"}}],
                 "groundingSupports": [{"segment": {"startIndex": 0, "endIndex": 20, "text": "Illinois amended it."}, "groundingChunkIndices": [0]}]}
    seen, t = recorder(gemini_reply("Illinois amended it.", grounding=grounding))
    r = GeminiProvider(api_key=SECRET, model="gemini-test", transport=t).search(system="s", prompt="What changed?", allowed_domains=["ilga.gov"], max_uses=4)
    b = body_of(seen[0])
    assert b["tools"] == [{"google_search": {}}] and "responseJsonSchema" not in b.get("generationConfig", {})
    assert "ilga.gov" in b["contents"][0]["parts"][0]["text"]  # Gemini has no domain filter: the allowlist goes in the prompt
    assert r.text == "Illinois amended it." and r.searches == 2 and r.cited == {"https://www.ilga.gov/act?id=1": [], "https://www.ftc.gov/x": []}


# ---- the refresh pipeline's two-step client on any provider
def test_research_then_structure_gives_the_pipeline_json_text_and_the_cited_pages():
    from app.ai.providers.base import ResearchThenStructure
    from app.ai.providers.openai import OpenAIProvider

    answer = {"changes": [{"field_path": "law.effective_on", "source_url": "https://www.ilga.gov/act?id=1", "source_quote": "It takes effect January 1, 2027."}]}

    def reply(request):
        return responses_reply() if request.url.path.endswith("/responses") else chat_reply(json.dumps(answer))

    seen, t = recorder(reply)
    c = ResearchThenStructure(OpenAIProvider(api_key=SECRET, model="gpt-test", transport=t), max_searches=6)
    out = c.propose(system="sys", prompt="Jurisdiction code: US-IL\nRecords...", schema={"type": "object"}, allowed_domains=["ilga.gov"])
    assert [r.url.path for r in seen] == ["/v1/responses", "/v1/chat/completions"]
    structure_prompt = body_of(seen[1])["messages"][1]["content"]
    assert "takes effect January 1, 2027" in structure_prompt and "https://www.ilga.gov/act?id=1" in structure_prompt
    assert json.loads(out.text) == answer and out.cited == {"https://www.ilga.gov/act?id=1": []} and out.provider == "openai"
    assert (out.input_tokens, out.output_tokens, out.searches) == (5120, 430, 2) and c.model == "gpt-test"


def test_text_research_returns_the_search_text_for_drafting():
    from app.ai.providers.base import TextResearch
    from app.ai.providers.gemini import GeminiProvider

    _, t = recorder(gemini_reply('```json\n{"short_name": "X"}\n```'))
    assert TextResearch(GeminiProvider(api_key=SECRET, model="gemini-test", transport=t)).research("Draft it.").startswith("```json")


# ---- the key never shows in a repr (a log line, a traceback's locals, a debugger)
def test_connection_config_and_providers_keep_the_key_out_of_their_repr():
    from types import SimpleNamespace as NS

    from app.ai.providers import ConnectionConfig
    from app.ai.providers.anthropic import AnthropicProvider
    from app.ai.providers.azure_openai import AzureOpenAIProvider
    from app.ai.providers.gemini import GeminiProvider
    from app.ai.providers.openai import OpenAIProvider

    cfg = ConnectionConfig(provider="openai", model="gpt-test", api_key=SECRET)
    assert SECRET not in repr(cfg) and "gpt-test" in repr(cfg)
    providers = [OpenAIProvider(api_key=SECRET, model="gpt-test"), GeminiProvider(api_key=SECRET, model="gemini-test"),
                 AzureOpenAIProvider(api_key=SECRET, endpoint="https://x.openai.azure.com", deployment="dep"),
                 AnthropicProvider(NS(ai_model=None, claude_model="claude-x", anthropic_api_key=None), api_key=SECRET, model="claude-x", client=object())]
    for p in providers:
        assert SECRET not in repr(p) and SECRET not in str(p), type(p).__name__
        assert p.model in repr(p)
