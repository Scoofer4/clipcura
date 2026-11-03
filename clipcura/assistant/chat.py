"""The built-in assistant's conversations (#27): Clipcura runs the tool loop an MCP client would run.

The model gets the MCP server's tools, and each call it asks for goes through that server, so it reaches the
local API as actor "ai" with exactly the limits of an assistant connected over MCP: no approving, no settings,
only allowed folders. Conversations live in memory for the life of the service.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from clipcura.assistant.ollama import Ollama, OllamaError
from clipcura.core import events
from clipcura.core.config import AssistantConfig
from clipcura.mcp.server import INSTRUCTIONS, build_server

Lang = Literal["en", "cs"]
log = logging.getLogger("clipcura.assistant")

SYSTEM = INSTRUCTIONS + """

You are the assistant built into the Clipcura window: the person types tasks here and sees every tool you
call. Use the tools instead of guessing, and say plainly what you did and what now waits for the person.
You cannot approve conversions, change settings or allow folders; tell the person where to do that in
Clipcura (AI activity for approvals, Settings for folders). Keep answers short. Paths are Windows paths."""

LANGUAGE = {"en": "Answer in English.", "cs": 'Answer in Czech and pass lang="cs" to the tools.'}
MAX_TOOL_CHARS = 20_000      # a big report would push the conversation out of a small model's context
MAX_CONVERSATIONS = 50


class AssistantBusy(Exception):
    pass


@dataclass
class Conversation:
    id: str
    messages: list[dict]                       # what the model sees
    transcript: list[dict] = field(default_factory=list)   # what the person sees
    busy: bool = False
    updated: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def title(self) -> str:
        first = next((i["text"] for i in self.transcript if i["role"] == "user"), "")
        return first[:80]

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "busy": self.busy, "updated": self.updated,
                "transcript": self.transcript}


class Assistant:
    max_rounds = 12   # model replies per task; a model stuck calling tools must not run forever

    def __init__(self, connect: Callable[[], httpx.Client] | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._tools_server = build_server(connect or _connect)
        self._transport = transport
        self._tool_defs: list[dict] | None = None
        self._lock = threading.Lock()
        self.conversations: dict[str, Conversation] = {}

    def server(self, url: str, key: str) -> Ollama:
        return Ollama(url, key, transport=self._transport)

    def tools(self) -> list[dict]:
        if self._tool_defs is None:
            listed = asyncio.run(self._tools_server.list_tools())
            self._tool_defs = [{"type": "function", "function": {
                "name": t.name, "description": t.description or "", "parameters": t.input_schema}} for t in listed]
        return self._tool_defs

    def get(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def ask(self, text: str, lang: Lang, settings: AssistantConfig, conversation_id: str | None = None,
            shown: str | None = None, wait: bool = False) -> Conversation:
        """Start a task. `shown` is what the transcript shows instead of a long generated prompt."""
        server = self.server(settings.url, settings.key)   # a bad address fails here, before a thread starts
        with self._lock:
            if conversation_id is not None:
                conv = self.conversations.get(conversation_id)
                if conv is None:
                    raise KeyError(conversation_id)
                if conv.busy:
                    raise AssistantBusy(conversation_id)
            else:
                conv = Conversation(uuid.uuid4().hex[:12],
                                    [{"role": "system", "content": f"{SYSTEM}\n{LANGUAGE[lang]}"}])
                self._remember(conv)
            conv.busy = True
            conv.cancel.clear()
        conv.messages.append({"role": "user", "content": text})
        item: dict[str, Any] = {"role": "user", "text": shown or text}
        if shown:
            item["details"] = text
        conv.transcript.append(item)
        log.info("Assistant task on %s (%s): %s", server.host, settings.model, (shown or text)[:200])
        run = lambda: self._turn(conv, server, settings.model)
        if wait:
            run()
        else:
            threading.Thread(target=run, name=f"assistant-{conv.id}", daemon=True).start()
        return conv

    def stop(self, conversation_id: str) -> bool:
        conv = self.conversations.get(conversation_id)
        if conv is None or not conv.busy:
            return False
        conv.cancel.set()
        return True

    def _remember(self, conv: Conversation) -> None:
        self.conversations[conv.id] = conv
        idle = sorted((c for c in self.conversations.values() if not c.busy), key=lambda c: c.updated)
        for old in idle[:max(0, len(self.conversations) - MAX_CONVERSATIONS)]:
            self.conversations.pop(old.id, None)

    # --- one task: model reply, tools, model reply… --------------------------------------------------------
    def _turn(self, conv: Conversation, server: Ollama, model: str) -> None:
        def emit(kind: str, **data: Any) -> None:
            conv.updated = time.time()
            events.publish("assistant", conversation=conv.id, kind=kind, **data)

        emit("start")
        try:
            for _ in range(self.max_rounds):
                text_item: dict | None = None

                def on_text(delta: str) -> None:
                    nonlocal text_item
                    if text_item is None:
                        text_item = {"role": "assistant", "text": ""}
                        conv.transcript.append(text_item)
                    text_item["text"] += delta
                    emit("text", delta=delta)

                reply = server.chat(model, conv.messages, self.tools(), on_text, conv.cancel)
                conv.messages.append(reply)
                if conv.cancel.is_set():
                    self._error(conv, emit, "Stopped.")
                    return
                calls = reply.get("tool_calls") or []
                if not calls:
                    return
                for call in calls:
                    self._run_tool(conv, emit, call)
            self._error(conv, emit, f"Stopped after {self.max_rounds} steps without an answer. "
                                    "Try a more specific task or another model.")
        except OllamaError as e:
            self._error(conv, emit, str(e))
        except Exception:
            log.exception("Assistant task failed")
            self._error(conv, emit, "The assistant failed unexpectedly; the details are in the log.")
        finally:
            conv.busy = False
            emit("done")

    def _run_tool(self, conv: Conversation, emit: Callable[..., None], call: dict) -> None:
        fn = call.get("function") or {}
        name = str(fn.get("name", ""))
        arguments = fn.get("arguments") or {}
        if isinstance(arguments, str):   # some models send the arguments as a JSON string
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {}
        index = len(conv.transcript)
        conv.transcript.append({"role": "tool", "name": name, "arguments": arguments, "ok": None, "summary": ""})
        emit("tool", index=index, name=name, arguments=arguments)
        try:
            result = asyncio.run(self._tools_server.call_tool(name, arguments))
            data: Any = result.structured_content
            if data is None:
                data = {"text": "".join(getattr(c, "text", "") for c in result.content)}
            ok = not getattr(result, "is_error", False)
            summary = str(data.get("summary", "")) if isinstance(data, dict) else ""
        except ToolError as e:
            ok, data, summary = False, {"error": str(e)}, str(e)
        except Exception as e:   # the tool itself crashed: the model gets a short note, the log the details
            log.exception("Assistant tool %s failed", name)
            ok, data, summary = False, {"error": f"{type(e).__name__}: {e}"}, "The tool failed; see the log."
        content = json.dumps(data, ensure_ascii=False, default=str)
        if len(content) > MAX_TOOL_CHARS:
            content = content[:MAX_TOOL_CHARS] + " …(cut: ask for less, e.g. filter the report by status)"
        conv.messages.append({"role": "tool", "tool_name": name, "content": content})
        conv.transcript[index].update(ok=ok, summary=summary[:500])
        (log.info if ok else log.warning)("Assistant tool %s -> %s%s", name, "ok" if ok else "failed",
                                          f": {summary[:200]}" if summary else "")
        emit("tool_done", index=index, ok=ok, summary=summary[:500])

    def _error(self, conv: Conversation, emit: Callable[..., None], text: str) -> None:
        log.warning("Assistant: %s", text)
        conv.transcript.append({"role": "error", "text": text})
        emit("error", text=text)


def _connect() -> httpx.Client:
    """The service this assistant runs in. Unlike MCP it never starts one: it is part of a running service."""
    from clipcura.api.server import running_server
    from clipcura.core.config import load_config
    info = running_server()
    if info is None:
        raise OllamaError("The Clipcura service is not running.")
    return httpx.Client(base_url=info["url"], timeout=600,
                        headers={"Authorization": f"Bearer {load_config().token}", "X-Clipcura-Actor": "ai"})


# --- "Explain" (#27): a conversation that starts with the details of a failure ---------------------------------
def explain_prompt(kind: Literal["job", "log"], details: dict, lang: Lang) -> tuple[str, str]:
    """The prompt for the model and the short line the person sees."""
    what = "conversion job failed" if kind == "job" else "entry appeared in Clipcura's log"
    prompt = (f"This {what}. Explain in plain words what went wrong and what the person can do about it. "
              "If you need more, use the tools (for example get_logs or get_report). Details:\n"
              f"```json\n{json.dumps(details, ensure_ascii=False, indent=1, default=str)[:MAX_TOOL_CHARS]}\n```")
    name = details.get("file") or details.get("message", "")
    name = str(name)[:120]
    shown = (f"Vysvětli, co se stalo: {name}" if lang == "cs" else f"Explain what happened: {name}")
    return prompt, shown
