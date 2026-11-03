"""Built-in assistant (#27): Clipcura talks to an Ollama server itself and runs the model's tool calls through
the same API and limits as MCP. The Ollama server is faked with httpx.MockTransport."""
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.assistant import Assistant, OllamaError, ollama
from clipcura.core import config, events, logs
from tests.conftest import needs_ffmpeg

BASE = "http://127.0.0.1"
OLLAMA = "https://ollama.example.test"
KEY = "sk-test-ollama-key-123"


class FakeOllama:
    """Answers /api/version, /api/tags and /api/chat; each chat request takes the next scripted reply."""

    def __init__(self, replies: list[dict] | None = None, status: int = 200) -> None:
        self.replies = list(replies or [])
        self.status = status
        self.requests: list[httpx.Request] = []
        self.chats: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "unauthorized"})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.5"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "qwen3.6:27b", "size": 17_420_432_739, "details": {"parameter_size": "27.8B"},
                 "capabilities": ["completion", "vision", "tools", "thinking"]},
                {"name": "gemma3:4b", "size": 3_000_000_000, "details": {"parameter_size": "4.3B"},
                 "capabilities": ["completion", "vision"]},
                {"name": "gpt-oss:20b", "size": 13_000_000_000, "details": {"parameter_size": "20.9B"},
                 "capabilities": ["completion", "tools", "thinking"]},
            ]})
        if request.url.path == "/api/chat":
            self.chats.append(json.loads(request.content))
            reply = self.replies.pop(0) if self.replies else text("Done.")
            return httpx.Response(200, content=_stream(reply))
        return httpx.Response(404, json={"error": "not found"})


def text(content: str) -> dict:
    return {"content": content}


def tool(name: str, **arguments) -> dict:
    return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def _stream(reply: dict) -> bytes:
    """Ollama streams NDJSON: text in pieces, tool calls in one chunk, then a final `done` line."""
    lines = []
    content = reply.get("content", "")
    for i in range(0, len(content), 4):
        lines.append({"message": {"role": "assistant", "content": content[i:i + 4]}, "done": False})
    if reply.get("tool_calls"):
        lines.append({"message": {"role": "assistant", "content": "", "tool_calls": reply["tool_calls"]},
                      "done": False})
    lines.append({"message": {"role": "assistant", "content": ""}, "done": True})
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


def settings(**over) -> config.AssistantConfig:
    return config.AssistantConfig(**({"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b", "key": KEY} | over))


@pytest.fixture
def api(tmp_path):
    """In-process API (`human`), a client seen as the assistant (`ai`) and a fake Ollama behind it."""
    cfg = config.load_config()
    config.allow_root(tmp_path)
    fake = FakeOllama()
    with TestClient(create_app(assistant=None), base_url=BASE) as human:
        human.headers["Authorization"] = f"Bearer {cfg.token}"
        ai = TestClient(human.app, base_url=BASE)
        ai.headers.update({"Authorization": f"Bearer {cfg.token}", "X-Clipcura-Actor": "ai"})
        assistant = Assistant(connect=lambda: ai, transport=httpx.MockTransport(fake))
        human.app.state.assistant = assistant
        yield human, assistant, fake


# --- talking to the server ------------------------------------------------------------------------------------
def test_models_lists_only_models_that_can_use_tools_and_sends_the_key():
    fake = FakeOllama()
    server = ollama.Ollama(OLLAMA, KEY, transport=httpx.MockTransport(fake))
    assert server.version() == "0.40.5"
    models = server.models()
    assert [m["name"] for m in models] == ["gpt-oss:20b", "qwen3.6:27b"]   # gemma3:4b cannot call tools
    assert next(m for m in models if m["name"] == "qwen3.6:27b")["vision"] is True
    assert all(r.headers["authorization"] == f"Bearer {KEY}" for r in fake.requests)


def test_no_key_sends_no_authorization_header():
    fake = FakeOllama()
    ollama.Ollama(OLLAMA, "", transport=httpx.MockTransport(fake)).version()
    assert "authorization" not in fake.requests[0].headers


def test_a_refused_key_says_so():
    server = ollama.Ollama(OLLAMA, "wrong", transport=httpx.MockTransport(FakeOllama(status=401)))
    with pytest.raises(OllamaError, match="access key"):
        server.version()


def test_an_unreachable_server_names_the_address():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    server = ollama.Ollama(OLLAMA, "", transport=httpx.MockTransport(refuse))
    with pytest.raises(OllamaError, match="ollama.example.test"):
        server.version()


def test_only_http_addresses_are_accepted():
    with pytest.raises(OllamaError, match="http"):
        ollama.Ollama("file:///etc/passwd", "")


# --- the conversation loop ------------------------------------------------------------------------------------
def test_the_model_calls_a_tool_and_answers_with_its_result(api):
    _, assistant, fake = api
    fake.replies = [tool("list_profiles"), text("You have the social-30 profile.")]
    conv = assistant.ask("Which profiles do I have?", lang="en", settings=settings(), wait=True)

    roles = [item["role"] for item in conv.transcript]
    assert roles == ["user", "tool", "assistant"]
    assert conv.transcript[1]["name"] == "list_profiles" and conv.transcript[1]["ok"] is True
    assert conv.transcript[2]["text"] == "You have the social-30 profile."

    first, second = fake.chats
    assert first["model"] == "qwen3.6:27b" and first["stream"] is True
    assert {t["function"]["name"] for t in first["tools"]} >= {"scan_folder", "plan_fixes", "apply_fixes"}
    assert not any("approve" in t["function"]["name"] for t in first["tools"])
    result = next(m for m in second["messages"] if m["role"] == "tool")
    assert result["tool_name"] == "list_profiles" and "social-30" in result["content"]


def test_tools_run_as_the_assistant_so_the_folder_whitelist_holds(api, tmp_path_factory):
    _, assistant, fake = api
    outside = tmp_path_factory.mktemp("outside")
    fake.replies = [tool("scan_folder", path=str(outside)), text("That folder is not allowed.")]
    conv = assistant.ask("Check the folder", lang="en", settings=settings(), wait=True)

    step = conv.transcript[1]
    assert step["ok"] is False and "allow the folder" in step["summary"]
    # The model hears about the refusal and can tell the person what to do.
    assert "allow the folder" in next(m for m in fake.chats[1]["messages"] if m["role"] == "tool")["content"]


def test_an_unknown_tool_is_reported_back_to_the_model(api):
    _, assistant, fake = api
    fake.replies = [tool("approve_job", job_id="x"), text("I cannot approve jobs.")]
    conv = assistant.ask("Approve it", lang="en", settings=settings(), wait=True)
    assert conv.transcript[1]["ok"] is False
    assert conv.transcript[-1]["text"] == "I cannot approve jobs."


def test_a_model_that_never_stops_calling_tools_is_stopped(api):
    _, assistant, fake = api
    fake.replies = [tool("list_rules")] * 50
    conv = assistant.ask("Loop", lang="en", settings=settings(), wait=True)
    assert conv.transcript[-1]["role"] == "error"
    assert len(fake.chats) == assistant.max_rounds


def test_the_conversation_continues_with_its_history(api):
    _, assistant, fake = api
    fake.replies = [text("Hello."), text("Still here.")]
    conv = assistant.ask("Hi", lang="en", settings=settings(), wait=True)
    assistant.ask("Again", lang="en", settings=settings(), conversation_id=conv.id, wait=True)
    messages = fake.chats[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] and "Answer in Czech" not in messages[0]["content"]


def test_czech_conversations_ask_the_model_for_czech(api):
    _, assistant, fake = api
    assistant.ask("Ahoj", lang="cs", settings=settings(), wait=True)
    assert "Answer in Czech" in fake.chats[0]["messages"][0]["content"]


def test_text_streams_to_the_gui_as_events(api):
    _, assistant, fake = api
    seen: list[dict] = []
    unsubscribe = events.subscribe(lambda e: seen.append(e) if e["type"] == "assistant" else None)
    try:
        fake.replies = [text("Twelve chars")]
        conv = assistant.ask("Hi", lang="en", settings=settings(), wait=True)
    finally:
        unsubscribe()
    kinds = [e["kind"] for e in seen]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "".join(e["delta"] for e in seen if e["kind"] == "text") == "Twelve chars"
    assert all(e["conversation"] == conv.id for e in seen)


def test_a_server_error_ends_the_turn_with_a_message(api):
    _, assistant, fake = api
    fake.status = 401
    conv = assistant.ask("Hi", lang="en", settings=settings(), wait=True)
    assert conv.transcript[-1]["role"] == "error" and "access key" in conv.transcript[-1]["text"]
    assert conv.busy is False


# --- the API --------------------------------------------------------------------------------------------------
def wait_idle(human, conv_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        data = human.get(f"/api/assistant/conversations/{conv_id}").json()
        if not data["busy"]:
            return data
        time.sleep(0.05)
    raise AssertionError("assistant did not finish")


def test_settings_never_send_the_key_back(api):
    human, _, _ = api
    r = human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b",
                                                   "key": KEY})
    assert r.status_code == 200
    for body in (r.json(), human.get("/api/assistant").json(), human.get("/api/config").json()):
        assert KEY not in json.dumps(body)
    status = human.get("/api/assistant").json()
    assert status["has_key"] is True and status["url"] == OLLAMA and status["enabled"] is True
    # Leaving the key out keeps it; an empty string removes it.
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b"})
    assert config.load_config().assistant.key == KEY
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "x", "key": ""})
    assert human.get("/api/assistant").json()["has_key"] is False


def test_the_key_is_masked_in_the_log(api):
    human, _, _ = api
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "m", "key": KEY})
    assert KEY not in logs.mask(f"oops {KEY} leaked", logs.secrets())


def test_only_a_person_configures_or_uses_the_assistant(api):
    human, _, _ = api
    ai = {"X-Clipcura-Actor": "ai"}
    assert human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "m"},
                     headers=ai).status_code == 403
    assert human.post("/api/assistant/conversations", json={"text": "hi"}, headers=ai).status_code == 403
    assert human.post("/api/assistant/test", json={}, headers=ai).status_code == 403


def test_a_conversation_needs_the_assistant_turned_on(api):
    human, _, _ = api
    r = human.post("/api/assistant/conversations", json={"text": "hi"})
    assert r.status_code == 409


def test_test_connection_uses_the_typed_values_and_lists_models(api):
    human, _, fake = api
    r = human.post("/api/assistant/test", json={"url": OLLAMA, "key": KEY})
    assert r.status_code == 200
    assert r.json()["version"] == "0.40.5" and "qwen3.6:27b" in [m["name"] for m in r.json()["models"]]
    assert fake.requests[-1].headers["authorization"] == f"Bearer {KEY}"


def test_test_connection_reports_a_refused_key(api):
    human, _, fake = api
    fake.status = 403
    r = human.post("/api/assistant/test", json={"url": OLLAMA, "key": "nope"})
    assert r.status_code == 502 and "access key" in r.json()["detail"]


def test_chat_through_the_api(api):
    human, _, fake = api
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b", "key": KEY})
    fake.replies = [tool("list_rules"), text("These are the checks.")]
    r = human.post("/api/assistant/conversations", json={"text": "What do you check?", "lang": "en"})
    assert r.status_code == 202
    data = wait_idle(human, r.json()["conversation"])
    assert [i["role"] for i in data["transcript"]] == ["user", "tool", "assistant"]
    # A second message while one is running is refused, not interleaved.
    fake.replies = [text("ok")]
    assert human.post("/api/assistant/conversations", json={"text": "more", "conversation": data["id"]}
                      ).status_code == 202
    wait_idle(human, data["id"])
    assert human.get("/api/assistant/conversations/nope").status_code == 404


def test_explain_a_log_entry_starts_a_conversation_with_its_details(api):
    human, _, fake = api
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b"})
    entry = {"ts": "2026-11-03T10:00:00Z", "level": "ERROR", "process": "service", "source": "clipcura.jobs",
             "message": "Job j1 failed: Invalid data found when processing input"}
    fake.replies = [text("The file is damaged.")]
    r = human.post("/api/assistant/explain", json={"log": entry, "lang": "en"})
    assert r.status_code == 202
    data = wait_idle(human, r.json()["conversation"])
    prompt = fake.chats[0]["messages"][1]["content"]
    assert "Invalid data found when processing input" in prompt
    assert data["transcript"][0]["role"] == "user" and data["transcript"][-1]["text"] == "The file is damaged."


def test_explain_an_unknown_job_is_404(api):
    human, _, _ = api
    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "m"})
    assert human.post("/api/assistant/explain", json={"job_id": "nope"}).status_code == 404


@needs_ffmpeg
def test_explain_a_job_sends_its_error_recipe_and_measured_values(api, raw_folder):
    from clipcura.core import service
    human, _, fake = api
    raw = raw_folder("a44k.mp4")
    config.allow_root(raw)
    scan = service.scan(raw)
    (job,) = service.apply(service.plan(scan.scan_id).plan_id)
    context = service.job_context(job.job_id)
    assert context["file"] == "a44k.mp4" and context["job"]["status"] == "done"
    assert context["ffmpeg"][0] == "ffmpeg" and context["media"]["audio"]["sample_rate"] == 44100
    assert "audio_rate" in [f["rule_id"] for f in context["findings"]]

    human.put("/api/assistant/settings", json={"enabled": True, "url": OLLAMA, "model": "qwen3.6:27b"})
    fake.replies = [text("It converted fine.")]
    r = human.post("/api/assistant/explain", json={"job_id": job.job_id, "lang": "cs"})
    data = wait_idle(human, r.json()["conversation"])
    assert data["transcript"][0]["text"] == "Vysvětli, co se stalo: a44k.mp4"
    assert "44100" in fake.chats[0]["messages"][1]["content"]
