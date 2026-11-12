"""Helpers for calling MCP tools from regular (non-LLM) code.

Agents receive MCP tools as LangChain tools. The orchestrator uses the *same* tools for
deterministic steps (authorize, capture, void, payout), so there is exactly one code path
into PayPal: the PayPal MCP server.

``target`` is anything ``langchain.mcp.MCPAdapter`` accepts: an ``http(s)`` URL in
production, or an in-process ``FastMCP`` instance in tests and demos.
"""

from __future__ import annotations

import json
import logging
import uuid
import warnings
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

# ``langchain.mcp`` is in beta and warns once on import; keep our logs readable.
warnings.filterwarnings("ignore", message=".*langchain.mcp.*beta.*")
from langchain.mcp import MCPAdapter  # noqa: E402

logger = logging.getLogger(__name__)


class ToolCallFailed(RuntimeError):
    """An MCP tool ran and reported an error (for example a refused mandate or a PayPal error)."""

    def __init__(self, tool: str, message: str) -> None:
        self.tool = tool
        super().__init__(f"{tool} failed: {message}")


def _text_of(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(parts)


def tool_result_dict(message: ToolMessage) -> dict[str, Any]:
    """Return a tool message's payload as a dict (structured content, else parsed text)."""
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict) and isinstance(artifact.get("structured_content"), dict):
        return artifact["structured_content"]
    try:
        parsed = json.loads(_text_of(message))
    except ValueError:
        return {"text": _text_of(message)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


class McpToolbox:
    """A named collection of LangChain tools discovered from one MCP server."""

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @classmethod
    async def connect(cls, target: Any) -> "McpToolbox":
        tools = await MCPAdapter(target).list_tools()
        logger.debug("Discovered MCP tools: %s", sorted(tool.name for tool in tools))
        return cls(tools)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def select(self, names: set[str]) -> list[BaseTool]:
        """Return only the named tools (least privilege for each agent)."""
        missing = names - set(self._tools)
        if missing:
            raise KeyError(f"MCP server does not expose: {sorted(missing)}")
        return [tool for name, tool in self._tools.items() if name in names]

    async def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        """Invoke a tool and return its result dict, raising :class:`ToolCallFailed` on tool errors."""
        if name not in self._tools:
            raise KeyError(f"Unknown MCP tool {name!r}; available: {self.names}")
        logger.info("MCP call -> %s", name)
        message = await self._tools[name].ainvoke(
            {"name": name, "args": arguments, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}
        )
        if not isinstance(message, ToolMessage):
            raise ToolCallFailed(name, f"unexpected result type {type(message).__name__}")
        if message.status == "error":
            raise ToolCallFailed(name, _text_of(message))
        return tool_result_dict(message)
