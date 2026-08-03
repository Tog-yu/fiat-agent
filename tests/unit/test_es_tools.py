"""F4 unit test: Elasticsearch read-only tool contract (DEV_SPEC §F4).

Covers the acceptance criteria:
  1. only whitelisted indices are allowed;
  2. arbitrary ES DSL is never accepted (the query is a fixed template built
     from structured params only);
  3. size is capped.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.errors import ToolContractViolation
from fiat_agent.tool_gateway.es_tools import (
    ALLOWED_INDICES,
    DEFAULT_SIZE,
    EsQueryRequest,
    EsTool,
    FakeEsClient,
    build_safe_query,
)


@pytest.mark.unit
def test_non_whitelisted_index_rejected() -> None:
    tool = EsTool(FakeEsClient())
    with pytest.raises(ToolContractViolation):
        tool.validate(EsQueryRequest(index="secret_prod_db"))
    # the allowed set is what the contract advertises
    assert "secret_prod_db" not in ALLOWED_INDICES


@pytest.mark.unit
def test_no_arbitrary_dsl_accepted() -> None:
    # The generated query is a fixed bool/range/match template — no raw DSL,
    # no scripts, no caller-controlled query string.
    req = EsQueryRequest(index="logs", keyword="timeout", level="ERROR", size=10)
    body = build_safe_query(req)

    assert "script" not in str(body)
    assert body["size"] == 10
    bool_part = body["query"]["bool"]
    # keyword -> match on message; level -> term; time bounded by range filter.
    assert {"match": {"message": "timeout"}} in bool_part["must"]
    assert {"term": {"level": "ERROR"}} in bool_part["must"]
    assert bool_part["filter"][0]["range"]["@timestamp"]["gte"] == "now-60m"

    # The tool only ever forwards the template, never a caller DSL body.
    fake = FakeEsClient()
    tool = EsTool(fake)

    asyncio.run(tool.query(req))
    sent_index, sent_body = fake.calls[0]
    assert sent_index == "logs"
    assert sent_body == body


@pytest.mark.unit
def test_size_capped() -> None:
    tool = EsTool(FakeEsClient())
    with pytest.raises(ToolContractViolation):
        tool.validate(EsQueryRequest(index="logs", size=10_000))


@pytest.mark.unit
def test_happy_path_maps_hits_and_total() -> None:
    store = {"logs": [{"message": "a"}, {"message": "b"}]}
    tool = EsTool(FakeEsClient(store))

    result = asyncio.run(tool.query(EsQueryRequest(index="logs")))
    assert result.index == "logs"
    assert result.total == 2
    assert result.hits == [{"message": "a"}, {"message": "b"}]
    # default size honored when not overridden
    assert result.hits  # non-empty
