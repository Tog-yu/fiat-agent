"""Unit tests for D4 function-call schema generation.

Covers the two acceptance criteria from DEV_SPEC D4:

* Pydantic schema convertible -> to_openai_tool_schema / to_anthropic_tool_schema
* MCP tools/list schema convertible -> same entry points
"""

import json

import pytest
from pydantic import BaseModel

from fiat_agent.tools.function_calling import (
    to_anthropic_tool_schema,
    to_openai_tool_schema,
)
from fiat_agent.tools.schemas import ToolDefinition


class WeatherArgs(BaseModel):
    """Get the weather forecast for a city."""

    city: str
    days: int = 3


MCP_TOOL = {
    "name": "search_docs",
    "description": "Search the knowledge base",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


@pytest.mark.unit
def test_pydantic_to_openai_shape():
    schema = to_openai_tool_schema(WeatherArgs)
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "WeatherArgs"
    assert fn["description"] == "Get the weather forecast for a city."
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "city" in params["properties"]
    assert params["properties"]["city"]["type"] == "string"
    assert params["required"] == ["city"]
    # default preserved
    assert params["properties"]["days"]["default"] == 3


@pytest.mark.unit
def test_pydantic_to_anthropic_shape():
    schema = to_anthropic_tool_schema(WeatherArgs)
    assert schema["name"] == "WeatherArgs"
    assert schema["description"] == "Get the weather forecast for a city."
    assert schema["input_schema"]["type"] == "object"
    assert "city" in schema["input_schema"]["properties"]
    assert "function" not in schema


@pytest.mark.unit
def test_mcp_tools_list_to_openai():
    schema = to_openai_tool_schema(MCP_TOOL)
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "search_docs"
    assert fn["description"] == "Search the knowledge base"
    assert fn["parameters"] == MCP_TOOL["inputSchema"]


@pytest.mark.unit
def test_mcp_tools_list_to_anthropic():
    schema = to_anthropic_tool_schema(MCP_TOOL)
    assert schema["name"] == "search_docs"
    assert schema["input_schema"] == MCP_TOOL["inputSchema"]


@pytest.mark.unit
def test_canonical_tool_definition():
    tool = ToolDefinition(
        name="calc",
        description="Calculator",
        input_schema={
            "type": "object",
            "properties": {"expr": {"type": "string"}},
            "required": ["expr"],
        },
    )
    oai = to_openai_tool_schema(tool)
    ant = to_anthropic_tool_schema(tool)
    assert oai["function"]["name"] == "calc"
    assert ant["name"] == "calc"
    assert oai["function"]["parameters"] == tool.input_schema
    assert ant["input_schema"] == tool.input_schema


@pytest.mark.unit
def test_schemas_are_json_serializable():
    oai = to_openai_tool_schema(WeatherArgs)
    ant = to_anthropic_tool_schema(MCP_TOOL)
    json.dumps(oai)
    json.dumps(ant)


@pytest.mark.unit
def test_pydantic_instance_accepted():
    # Passing an instance (not the class) must also work.
    schema = to_openai_tool_schema(WeatherArgs(city="Shanghai"))
    assert schema["function"]["name"] == "WeatherArgs"
    assert "city" in schema["function"]["parameters"]["properties"]
