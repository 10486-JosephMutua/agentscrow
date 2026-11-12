"""A fake Groq (OpenAI-compatible) server, so the REAL `ChatGroq` + `groq` SDK + LangChain agent loop run over real HTTP.

Tests supply `handler(request_body) -> assistant_message_dict`. The helpers `tool_call(...)` and `text(...)` build messages.
Every request is recorded, so tests can assert on the prompts, tool schemas and tool results the agent actually sent.
"""

from __future__ import annotations

import itertools
import json
import threading
import time

from flask import Flask, jsonify, request
from werkzeug.serving import make_server


def tool_call(name: str, arguments: dict, call_id: str | None = None) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [{"id": call_id or f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def text(content: str) -> dict:
    return {"role": "assistant", "content": content}


class FakeGroq:
    def __init__(self, handler=None, models=("openai/gpt-oss-120b",)):
        self.handler, self.models = handler, list(models)
        self.requests: list[dict] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.app = Flask("fake-groq")
        self._server = None

        @self.app.get("/openai/v1/models")
        def list_models():
            return jsonify(object="list", data=[{"id": m, "object": "model", "created": 0, "owned_by": "fake"} for m in self.models])

        @self.app.post("/openai/v1/chat/completions")
        def completions():
            body = request.get_json()
            with self._lock:
                self.requests.append(body)
                number = next(self._ids)
            message = self.handler(body)
            finish = "tool_calls" if message.get("tool_calls") else "stop"
            return jsonify(
                id=f"chatcmpl-{number}", object="chat.completion", created=int(time.time()), model=body.get("model", "fake"),
                choices=[{"index": 0, "message": message, "finish_reason": finish}],
                usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            )

    def start(self) -> "FakeGroq":
        self._server = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    @staticmethod
    def tool_names(body: dict) -> set[str]:
        return {t["function"]["name"] for t in body.get("tools") or []}

    @staticmethod
    def has_tool_result(body: dict) -> bool:
        return any(m.get("role") == "tool" for m in body.get("messages", []))
