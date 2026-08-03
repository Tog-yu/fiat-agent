"""E4 unit test: MCP content parser (DEV_SPEC §E4).

Covers:
  - text / image / metadata are separated into distinct buckets;
  - image content is NOT merged into the plain-text context;
  - empty input yields empty, safe output.
"""

from __future__ import annotations

import mcp.types as types
import pytest

from fiat_agent.mcp_clients.content_parser import (
    McpImage,
    ParsedMcpContent,
    parse_mcp_contents,
)


@pytest.mark.unit
def test_separates_text_image_metadata() -> None:
    contents = [
        types.TextContent(type="text", text="answer text"),
        types.ImageContent(type="image", data="BASE64DATA", mimeType="image/png"),
        {"type": "resource", "resource": {"uri": "x"}},
        types.TextContent(type="text", text="more text"),
    ]
    parsed = parse_mcp_contents(contents)

    assert parsed.texts == ["answer text", "more text"]
    assert len(parsed.images) == 1
    assert isinstance(parsed.images[0], McpImage)
    assert parsed.images[0].data == "BASE64DATA"
    assert parsed.images[0].mime_type == "image/png"
    assert parsed.metadata == [{"type": "resource", "resource": {"uri": "x"}}]


@pytest.mark.unit
def test_image_not_in_text_context() -> None:
    contents = [
        types.TextContent(type="text", text="hello"),
        types.ImageContent(type="image", data="IMGDATA", mimeType="image/jpeg"),
    ]
    parsed = parse_mcp_contents(contents)

    assert parsed.text_context == "hello"
    assert "IMGDATA" not in parsed.text_context
    # images are still captured separately
    assert parsed.images[0].data == "IMGDATA"


@pytest.mark.unit
def test_empty_contents() -> None:
    parsed: ParsedMcpContent = parse_mcp_contents([])
    assert parsed.texts == []
    assert parsed.images == []
    assert parsed.metadata == []
    assert parsed.text_context == ""
