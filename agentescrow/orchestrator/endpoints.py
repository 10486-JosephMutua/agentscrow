"""Where the orchestrator finds its MCP servers.

Production uses HTTP URLs (the servers run as separate processes). Tests and the offline
demo use in-process ``FastMCP`` objects, which need no ports and behave identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentescrow.config import Settings
from agentescrow.mcp_client import McpToolbox
from agentescrow.mcp_servers.paypal_escrow_server import build_paypal_server
from agentescrow.mcp_servers.workbench_server import build_workbench_server


@dataclass(frozen=True)
class McpEndpoints:
    paypal_target: Any
    workbench_target: Any

    async def paypal(self) -> McpToolbox:
        return await McpToolbox.connect(self.paypal_target)

    async def workbench(self) -> McpToolbox:
        return await McpToolbox.connect(self.workbench_target)


def http_endpoints(settings: Settings) -> McpEndpoints:
    return McpEndpoints(settings.paypal_mcp_url, settings.workbench_mcp_url)


def inprocess_endpoints(settings: Settings, paypal_client: Any = None) -> McpEndpoints:
    """Build both servers inside this process. The PayPal server (and any simulator) is shared by all calls."""
    return McpEndpoints(build_paypal_server(settings, paypal_client), build_workbench_server(settings))
