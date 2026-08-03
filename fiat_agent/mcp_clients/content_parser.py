"""MCP content parser (phase E4, DEV_SPEC §6.5).

Turns a list of MCP content items (``TextContent`` / ``ImageContent`` /
``EmbeddedResource``) into separated, structured parts: plain text, images, and
metadata. Images are deliberately kept OUT of the plain-text context
(acceptance criterion 2) so image data is never silently concatenated into the
text the LLM reads.
"""

from __future__ import annotations

from typing import Any

from fiat_agent.schemas.common import FiatModel


class McpImage(FiatModel):
    """An image returned by an MCP tool. B64 ``data`` + its MIME type."""

    data: str
    mime_type: str = "application/octet-stream"


class ParsedMcpContent(FiatModel):
    """Structured result of parsing one MCP tool response's content list."""

    texts: list[str] = []
    images: list[McpImage] = []
    metadata: list[dict] = []

    @property
    def text_context(self) -> str:
        """Only textual content — never images or raw metadata."""
        return "\n".join(t for t in self.texts if t)


def _to_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    return {"value": str(obj)}


def parse_mcp_contents(contents: list[Any]) -> ParsedMcpContent:
    """Split MCP content items into text / image / metadata buckets."""
    parsed = ParsedMcpContent()
    for item in contents:
        ctype = getattr(item, "type", None)
        if ctype == "text":
            parsed.texts.append(getattr(item, "text", "") or "")
        elif ctype == "image":
            parsed.images.append(
                McpImage(
                    data=getattr(item, "data", "") or "",
                    mime_type=getattr(item, "mimeType", "application/octet-stream")
                    or "application/octet-stream",
                )
            )
        else:
            parsed.metadata.append(_to_dict(item))
    return parsed
