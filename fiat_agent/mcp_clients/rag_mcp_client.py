"""MCP stdio client for the modular RAG MCP server (phase E1, DEV_SPEC §2.4, §7.2).

Wraps the `mcp` Python SDK stdio transport to:
  - start the RAG server as a subprocess (config-driven: cwd / command / args),
  - perform the JSON-RPC `initialize` handshake,
  - expose the live `ClientSession` for later tool calls (E2/E3),
  - tear the subprocess down cleanly on `close()`.

Transport contract (DEV_SPEC E1 criterion 2): the MCP stdio transport reads
JSON-RPC **only from stdout** and routes stderr to a separate log stream, so a
server log line never corrupts the protocol stream. This client relies on that
guarantee and does not parse stderr as messages.
"""

from __future__ import annotations

import os
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from fiat_agent.config import McpServerConfig, Settings, load_settings
from fiat_agent.errors import FiatAgentError, ToolExecutionError


class McpClientNotStartedError(FiatAgentError):
    """Raised when a session operation runs before start()/initialize()."""

    code = "mcp_client_not_started"


class RagMcpClient:
    """Lifecycle manager for a single MCP stdio server connection.

    Typical use::

        async with RagMcpClient.from_settings() as client:
            tools = await client.session.list_tools()

    The context manager enters ``start()`` then ``initialize()`` and guarantees
    ``close()`` on exit, even if the handshake fails.
    """

    def __init__(
        self,
        config: McpServerConfig | None = None,
        *,
        settings: Settings | None = None,
        config_name: str = "rag",
    ) -> None:
        if config is None:
            if settings is None:
                settings = load_settings()
            config = settings.mcp_servers.get(config_name)
            if config is None or not config.name:
                raise McpClientNotStartedError(
                    f"配置中找不到 MCP server: {config_name}"
                )
        self.config: McpServerConfig = config
        self._server_params = self._build_params(config)
        self._process_cm: Any = None
        self._read: Any = None
        self._write: Any = None
        self._session_cm: Any = None
        self._session: ClientSession | None = None
        self._init_result: Any = None
        self._started = False

    @staticmethod
    def _build_params(config: McpServerConfig) -> StdioServerParameters:
        # Inherit the parent environment so server-specific env vars (API keys,
        # paths) are visible to the subprocess; the venv interpreter resolves
        # its own site-packages regardless of env.
        return StdioServerParameters(
            command=config.command or "python",
            args=list(config.args),
            cwd=config.cwd,
            env=dict(os.environ),
        )

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, config_name: str = "rag"
    ) -> "RagMcpClient":
        """Build a client from loaded settings (default: the `rag` server)."""
        return cls(settings=settings, config_name=config_name)

    async def start(self) -> None:
        """Spawn the server subprocess and open the stdio transport + session."""
        if self._started:
            return
        self._process_cm = stdio_client(self._server_params)
        self._read, self._write = await self._process_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        self._started = True

    async def initialize(self) -> Any:
        """Perform the JSON-RPC initialize handshake. Requires start() first."""
        if not self._started or self._session is None:
            raise McpClientNotStartedError(
                "调用 initialize() 之前必须先调用 start()"
            )
        self._init_result = await self._session.initialize()
        return self._init_result

    @property
    def session(self) -> ClientSession:
        """The live MCP session (available after start())."""
        if self._session is None:
            raise McpClientNotStartedError(
                "MCP session 尚未建立，请先调用 start() 与 initialize()"
            )
        return self._session

    @property
    def server_info(self) -> Any:
        """Server identification reported during initialize()."""
        if self._init_result is None:
            raise McpClientNotStartedError("尚未 initialize()，无 server info")
        return self._init_result.serverInfo

    @property
    def is_started(self) -> bool:
        return self._started

    async def call_tool(self, name: str, arguments: dict) -> list[Any]:
        """Call an MCP tool by name and return its content items.

        Raises `ToolExecutionError` when the server reports an error
        (``isError``), so a failed RAG lookup never silently enters the trusted
        context (DEV_SPEC E3 criterion 2).
        """
        if self._session is None:
            raise McpClientNotStartedError("请先调用 start() 与 initialize()")
        result = await self._session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            texts = [getattr(c, "text", "") for c in result.content if getattr(c, "text", None)]
            detail = "; ".join(t for t in texts if t)
            raise ToolExecutionError(f"MCP 工具 {name} 返回错误: {detail}")
        return list(result.content)

    async def query_knowledge_hub(
        self, query: str, top_k: int = 5, collection: str | None = None
    ) -> list[Any]:
        """Query the RAG knowledge hub (wraps the `query_knowledge_hub` MCP tool).

        Args:
            query: the search question / keywords.
            top_k: max number of results (server default 5).
            collection: optional collection name to narrow the search scope.
        """
        arguments: dict[str, Any] = {"query": query, "top_k": top_k}
        if collection is not None:
            arguments["collection"] = collection
        return await self.call_tool("query_knowledge_hub", arguments)

    async def close(self) -> None:
        """Terminate the session and the server subprocess if still running."""
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._process_cm is not None:
            await self._process_cm.__aexit__(None, None, None)
            self._process_cm = None
        self._init_result = None
        self._started = False

    async def __aenter__(self) -> "RagMcpClient":
        await self.start()
        await self.initialize()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
