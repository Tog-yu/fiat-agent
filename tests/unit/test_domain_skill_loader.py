"""H1 unit test: Domain Skill loader (DEV_SPEC §H1).

Verifies the acceptance criterion: *different task_type loads different prompt,
tools and output schema*. Also covers discovery, caching, and the not-found path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fiat_agent.context.builder import ContextBuilder
from fiat_agent.schemas.common import ActorContext, Environment, TaskType
from fiat_agent.skills.loader import (
    DomainSkill,
    SkillLoader,
    SkillNotFound,
    load_skill,
)

# The five business task types and the tools each skill should declare.
EXPECTED = {
    TaskType.RAG_QA: {
        "name": "法币知识问答",
        "tools": ["rag_query"],
        "schema_keys": {"answer", "citations", "confidence", "has_evidence"},
    },
    TaskType.ALERT_DIAGNOSIS: {
        "name": "告警诊断",
        "tools": ["es_query", "db_query", "rag_query", "lark_notify"],
        "schema_keys": {"impact", "possible_causes", "confidence", "next_steps"},
    },
    TaskType.TEST_ENV_AUTOMATION: {
        "name": "测试环境自动化",
        "tools": ["test_env"],
        "schema_keys": {"steps", "is_test", "environment"},
    },
    TaskType.CASHBACK_RECONCILE: {
        "name": "返现对账",
        "tools": ["cashback_reconcile", "rag_query"],
        "schema_keys": {"summary", "issues", "is_dry_run"},
    },
    TaskType.LOGISTICS_VALIDATION: {
        "name": "物流校验",
        "tools": ["db_query", "rag_query"],
        "schema_keys": {"validated", "invalid", "field_errors", "state_violations"},
    },
}


def test_all_five_task_types_have_a_skill():
    loader = SkillLoader()
    loaded = set(loader.task_types())
    assert loaded == set(EXPECTED.keys())


def test_each_skill_carries_correct_name_tools_and_output_schema():
    loader = SkillLoader()
    for task_type, expect in EXPECTED.items():
        skill = loader.get(task_type)
        assert isinstance(skill, DomainSkill)
        assert skill.name == expect["name"]
        assert skill.tools == expect["tools"]
        assert skill.output_schema is not None
        # output_schema is a JSON schema -> top-level "properties" holds the fields
        props = set(skill.output_schema.get("properties", {}).keys())
        assert expect["schema_keys"] <= props, (task_type, expect["schema_keys"] - props)
        # the body system prompt is non-empty and task-type specific
        assert skill.system_prompt.strip()


def test_prompts_tools_and_schemas_differ_per_task_type():
    """Acceptance: distinct (prompt, tools, output_schema) per task_type."""
    loader = SkillLoader()
    skills = loader.all()
    assert len(skills) == len(EXPECTED)

    # Distinct system prompts.
    prompts = [s.system_prompt for s in skills]
    assert len(set(prompts)) == len(prompts), "system prompts are not all distinct"

    # Distinct tool sets.
    tool_sets = [tuple(s.tools) for s in skills]
    assert len(set(tool_sets)) == len(tool_sets), "tool sets are not all distinct"

    # Distinct output schemas (compared as dicts).
    schemas = [s.output_schema for s in skills]
    assert len({id(x) for x in schemas}) == len(schemas)  # distinct objects
    assert len({tuple(sorted(x["properties"].keys())) for x in schemas}) == len(
        schemas
    ), "output schemas are not all distinct"


def test_loader_is_cached_and_idempotent():
    loader = SkillLoader()
    first = loader.get(TaskType.RAG_QA)
    second = loader.get(TaskType.RAG_QA)
    assert first is second  # cached, not re-parsed


def test_load_skill_convenience_returns_same_content():
    via_loader = SkillLoader().get(TaskType.ALERT_DIAGNOSIS)
    via_fn = load_skill(TaskType.ALERT_DIAGNOSIS)
    assert via_loader == via_fn


def test_unknown_task_type_raises_skill_not_found():
    """A loader pointed at an empty skills dir finds nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        empty = SkillLoader(Path(tmp))
        assert empty.task_types() == []
        assert empty.get_or_none(TaskType.RAG_QA) is None
        try:
            empty.get(TaskType.RAG_QA)
        except SkillNotFound:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected SkillNotFound")


def test_domain_skill_is_consumed_by_context_builder():
    """The loaded skill's system prompt is injected into the built context."""
    actor = ActorContext(
        actor_id="u1",
        roles=["oncall"],
        environment=Environment.DEV,
        task_type=TaskType.RAG_QA,
    )
    skill = load_skill(TaskType.RAG_QA)
    builder = ContextBuilder()
    prompt = builder.build_system_prompt(actor, task_type=TaskType.RAG_QA, skill=skill)
    assert skill.name in prompt
    assert skill.system_prompt in prompt
    # Without a skill the domain section is absent.
    plain = builder.build_system_prompt(actor, task_type=TaskType.RAG_QA)
    assert skill.system_prompt not in plain
