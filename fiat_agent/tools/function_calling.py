"""Function-call schema generation (phase D4, DEV_SPEC D4).

Converts a tool definition into the JSON shape each provider expects:

* :func:`to_openai_tool_schema` -> OpenAI / DeepSeek ``/v1/chat/completions``
  ``tools`` entry (``{"type": "function", "function": {...}}``).
* :func:`to_anthropic_tool_schema` -> Anthropic ``tools`` entry
  (``{"name", "description", "input_schema"}``).

Both accept the same flexible ``tool_definition`` input:

* the canonical :class:`~fiat_agent.tools.schemas.ToolDefinition`,
* a Pydantic ``BaseModel`` class or instance (its ``model_json_schema`` is used),
* an MCP ``tools/list`` item (``{"name", "description", "inputSchema"}``),
* or a plain dict already in canonical / OpenAI / Anthropic shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from fiat_agent.tools.schemas import ToolDefinition


def _normalize(tool_definition: Any) -> tuple[str, str, dict[str, Any]]:
    """Return ``(name, description, json_schema)`` for any supported input."""
    # Canonical ToolDefinition instance.
    if isinstance(tool_definition, ToolDefinition):
        return (
            tool_definition.name,
            tool_definition.description,
            tool_definition.input_schema or {},
        )

    # Pydantic model class -> JSON schema from the class.
    if isinstance(tool_definition, type) and issubclass(tool_definition, BaseModel):
        schema = tool_definition.model_json_schema()
        name = tool_definition.__name__
        description = schema.get("description") or (tool_definition.__doc__ or "").strip()
        return name, description, schema

    # Pydantic model instance -> JSON schema from the instance's class.
    if isinstance(tool_definition, BaseModel):
        schema = tool_definition.model_json_schema()
        model_cls = type(tool_definition)
        name = model_cls.__name__
        description = schema.get("description") or (model_cls.__doc__ or "").strip()
        return name, description, schema

    # Dict forms.
    if isinstance(tool_definition, dict):
        # OpenAI shape already: {"type": "function", "function": {...}}
        fn = tool_definition.get("function")
        if isinstance(fn, dict):
            return fn.get("name", ""), fn.get("description", ""), fn.get("parameters", {})

        # MCP tools/list item.
        if "inputSchema" in tool_definition:
            return (
                tool_definition.get("name", ""),
                tool_definition.get("description", ""),
                tool_definition.get("inputSchema", {}),
            )

        # Canonical dict (name + input_schema).
        if "input_schema" in tool_definition:
            return (
                tool_definition.get("name", ""),
                tool_definition.get("description", ""),
                tool_definition.get("input_schema", {}),
            )

        # Fallback: treat a bare JSON schema dict as the parameters.
        return tool_definition.get("name", ""), tool_definition.get("description", ""), tool_definition

    raise TypeError(f"Unsupported tool_definition type: {type(tool_definition)!r}")


def to_openai_tool_schema(tool_definition: Any) -> dict[str, Any]:
    """Convert a tool definition into an OpenAI ``tools`` entry."""
    name, description, schema = _normalize(tool_definition)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def to_anthropic_tool_schema(tool_definition: Any) -> dict[str, Any]:
    """Convert a tool definition into an Anthropic ``tools`` entry."""
    name, description, schema = _normalize(tool_definition)
    return {
        "name": name,
        "description": description,
        "input_schema": schema,
    }
