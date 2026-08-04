"""Unit tests for the logistics state machine + field validation (§H7).

Acceptance (DEV_SPEC §H7):
  1. 非法状态流转被拒绝 (illegal state transitions are rejected).
  2. 地址、单号、卡号异常可识别 (address / tracking-no / card-no anomalies
     are detectable).

Tests are hermetic: they exercise the pure :class:`LogisticsTableParser`, the
deterministic :class:`LogisticsStateMachine`, the file reader (CSV via stdlib,
XLSX via openpyxl when available), and the read-only workflow through fakes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.auth.policy import can_execute
from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse, TokenUsage
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.skills.loader import load_skill
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition
from fiat_agent.tool_gateway.logistics_tools import (
    IllegalStateTransitionError,
    LogisticsStateMachine,
    LogisticsStateViolation,
    LogisticsStatus,
    LogisticsTableParser,
    LogisticsValidationTool,
    LogisticsParseError,
    is_valid_card_no,
    make_logistics_validate_handler,
    normalize_status,
    read_rows,
)
from fiat_agent.workflows.logistics_validation import (
    LogisticsValidationResult,
    run_logistics_validation,
)


# --- fixtures ---------------------------------------------------------------
def _zh_rows() -> list[dict]:
    """Default (Chinese-header) rows covering clean + each anomaly kind."""
    valid_card = "4111111111111111"  # classic Visa test number (Luhn-valid)
    return [
        # 0: clean transition 已揽收 -> 运输中
        {"运单号": "SF1234567890", "原状态": "已揽收", "新状态": "运输中",
         "地址": "北京市朝阳区建国路1号", "卡号": valid_card, "更新时间": "2026-01-01"},
        # 1: illegal transition 已创建 -> 已签收 (从未发货直接到已签收)
        {"运单号": "SF1234567891", "原状态": "已创建", "新状态": "已签收",
         "地址": "上海市浦东新区世纪大道100号", "卡号": valid_card, "更新时间": "2026-01-02"},
        # 2: bad tracking number format
        {"运单号": "AB", "原状态": "已揽收", "新状态": "运输中",
         "地址": "广州市天河区天河路5号", "卡号": valid_card, "更新时间": "2026-01-03"},
        # 3: bad card number (too short / fails Luhn)
        {"运单号": "SF1234567893", "原状态": "已揽收", "新状态": "运输中",
         "地址": "深圳市南山区科技园", "卡号": "1234", "更新时间": "2026-01-04"},
        # 4: short / placeholder address
        {"运单号": "SF1234567894", "原状态": "已揽收", "新状态": "运输中",
         "地址": "短", "卡号": valid_card, "更新时间": "2026-01-05"},
        # 5: unknown status
        {"运单号": "SF1234567895", "原状态": "火星状态", "新状态": "运输中",
         "地址": "杭州市西湖区文三路9号", "卡号": valid_card, "更新时间": "2026-01-06"},
    ]


def _en_rows() -> list[dict]:
    """English-header variant to prove the mapping is configurable."""
    return [
        {"tracking": "SF9999999999", "prev": "picked_up", "next": "in_transit",
         "addr": "1 Main St, Beijing", "card": "4111111111111111", "ts": "2026-02-01"},
        # illegal transition under english aliases
        {"tracking": "SF8888888888", "prev": "created", "next": "delivered",
         "addr": "2 Side St, Shanghai", "card": "4111111111111111", "ts": "2026-02-02"},
    ]


# --- state machine ----------------------------------------------------------
def test_state_machine_allows_legal_chain():
    sm = LogisticsStateMachine()
    chain = [
        (LogisticsStatus.CREATED, LogisticsStatus.PICKED_UP),
        (LogisticsStatus.PICKED_UP, LogisticsStatus.IN_TRANSIT),
        (LogisticsStatus.IN_TRANSIT, LogisticsStatus.OUT_FOR_DELIVERY),
        (LogisticsStatus.OUT_FOR_DELIVERY, LogisticsStatus.DELIVERED),
        (LogisticsStatus.DELIVERED, LogisticsStatus.RETURNED),
    ]
    for prev, new in chain:
        assert sm.is_allowed(prev, new) is True


def test_state_machine_rejects_illegal_transition():
    sm = LogisticsStateMachine()
    # 从未发货直接到已签收
    assert sm.is_allowed(LogisticsStatus.CREATED, LogisticsStatus.DELIVERED) is False
    # returned is terminal
    assert sm.is_allowed(LogisticsStatus.RETURNED, LogisticsStatus.IN_TRANSIT) is False
    # cannot jump straight to delivered from picked_up
    assert sm.is_allowed(LogisticsStatus.PICKED_UP, LogisticsStatus.DELIVERED) is False
    with pytest.raises(IllegalStateTransitionError):
        sm.validate(LogisticsStatus.CREATED, LogisticsStatus.DELIVERED)


def test_state_machine_allows_noop_update():
    sm = LogisticsStateMachine()
    assert sm.is_allowed(LogisticsStatus.DELIVERED, LogisticsStatus.DELIVERED) is True


def test_normalize_status_handles_aliases_and_unknowns():
    assert normalize_status("已签收") is LogisticsStatus.DELIVERED
    assert normalize_status("签收") is LogisticsStatus.DELIVERED
    assert normalize_status("in_transit") is LogisticsStatus.IN_TRANSIT
    assert normalize_status("") is None
    assert normalize_status("火星状态") is None


# --- parser: state violations ----------------------------------------------
def test_illegal_transition_flaged_as_state_violation():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    viol = [v for v in res.state_violations if v.tracking_no == "SF1234567891"]
    assert len(viol) == 1
    v = viol[0]
    assert isinstance(v, LogisticsStateViolation)
    assert v.from_status == "created"
    assert v.to_status == "delivered"
    assert "非法状态流转" in v.detail


def test_clean_row_has_no_state_violation():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    # row 0 is a clean 已揽收 -> 运输中 transition
    assert all(v.tracking_no != "SF1234567890" for v in res.state_violations)


# --- parser: field anomalies ------------------------------------------------
def test_tracking_no_format_anomaly():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    errs = [e for e in res.field_errors if e.tracking_no == "AB"]
    assert len(errs) == 1
    assert errs[0].field == "tracking_no"
    assert "格式异常" in errs[0].detail


def test_missing_tracking_no_anomaly():
    rows = [{"原状态": "已揽收", "新状态": "运输中", "地址": "北京市朝阳区建国路1号"}]
    res = LogisticsTableParser().parse_rows(rows)
    miss = [e for e in res.field_errors if e.field == "tracking_no" and "缺少" in e.detail]
    assert len(miss) == 1


def test_address_anomaly_short_and_placeholder():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    short = [e for e in res.field_errors if e.tracking_no == "SF1234567894"]
    assert len(short) == 1
    assert short[0].field == "address"


def test_card_no_anomaly():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    errs = [e for e in res.field_errors if e.tracking_no == "SF1234567893"]
    assert len(errs) == 1
    assert errs[0].field == "card_no"
    assert "卡号格式异常" in errs[0].detail


def test_unknown_status_flagged():
    res = LogisticsTableParser().parse_rows(_zh_rows())
    errs = [e for e in res.field_errors if e.tracking_no == "SF1234567895"]
    assert any(e.field == "prev_status" for e in errs)


def test_valid_card_number_passes():
    assert is_valid_card_no("4111111111111111") is True
    assert is_valid_card_no("5500 0000 0000 0004") is True  # spaces stripped
    assert is_valid_card_no("1234") is False
    assert is_valid_card_no("4111111111111112") is False  # Luhn fail


# --- configurable field mapping ---------------------------------------------
def test_custom_field_map_parses_english_headers():
    parser = LogisticsTableParser(
        field_map={
            "tracking_no": "tracking",
            "prev_status": "prev",
            "new_status": "next",
            "address": "addr",
            "card_no": "card",
            "updated_at": "ts",
        }
    )
    res = parser.parse_rows(_en_rows())
    assert res.row_count == 2
    # row 1 (english) illegal created -> delivered
    assert len(res.state_violations) == 1
    assert res.state_violations[0].from_status == "created"


# --- file reader + tool -----------------------------------------------------
def test_read_rows_csv(tmp_path: Path):
    p = tmp_path / "logi.csv"
    p.write_text(
        "运单号,原状态,新状态,地址,卡号,更新时间\n"
        "SF1234567890,已揽收,运输中,北京市朝阳区建国路1号,4111111111111111,2026-01-01\n",
        encoding="utf-8-sig",
    )
    rows = read_rows(p)
    res = LogisticsTableParser().parse_rows(rows)
    assert res.row_count == 1
    assert res.records[0].tracking_no == "SF1234567890"
    assert res.state_violations == []
    assert res.field_errors == []


def test_read_rows_xlsx_round_trip(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "logi.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["运单号", "原状态", "新状态", "地址", "卡号", "更新时间"])
    ws.append(["SF1234567890", "已揽收", "运输中", "北京市朝阳区建国路1号",
               "4111111111111111", "2026-01-01"])
    ws.append(["SF1234567891", "已创建", "已签收", "上海市浦东新区世纪大道100号",
               "4111111111111111", "2026-01-02"])  # illegal transition
    wb.save(p)

    rows = read_rows(p)
    res = LogisticsTableParser().parse_rows(rows)
    assert res.row_count == 2
    assert len(res.state_violations) == 1


def test_read_rows_unsupported_type(tmp_path: Path):
    p = tmp_path / "logi.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        read_rows(p)


def test_tool_execute_via_file(tmp_path: Path):
    p = tmp_path / "logi.csv"
    p.write_text(
        "运单号,原状态,新状态,地址,卡号,更新时间\n"
        "SF1234567890,已创建,已签收,北京市朝阳区建国路1号,4111111111111111,2026-01-01\n",
        encoding="utf-8-sig",
    )
    out = asyncio.run(LogisticsValidationTool().execute({"file_path": str(p)}))
    assert out["row_count"] == 1
    assert out["state_violation_count"] == 1


# --- workflow: read-only aggregation ----------------------------------------
@pytest.mark.unit
def test_workflow_aggregates_validated_and_invalid(tmp_path: Path):
    csv_path = tmp_path / "logi.csv"
    csv_path.write_text(
        # row0 clean | row1 illegal transition | row2 bad tracking
        # row3 bad card | row4 short address
        "运单号,原状态,新状态,地址,卡号,更新时间\n"
        "SF1234567890,已揽收,运输中,北京市朝阳区建国路1号,4111111111111111,2026-01-01\n"
        "SF1234567891,已创建,已签收,上海市浦东新区世纪大道100号,4111111111111111,2026-01-02\n"
        "AB,已揽收,运输中,广州市天河区天河路5号,4111111111111111,2026-01-03\n"
        "SF1234567893,已揽收,运输中,深圳市南山区科技园,1234,2026-01-04\n"
        "SF1234567894,已揽收,运输中,短,4111111111111111,2026-01-05\n",
        encoding="utf-8-sig",
    )

    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="logistics_validate", risk_level=RiskLevel.L1, approval_required=False)
    )
    # Register a fake production-write tool to PROVE it is never called.
    submit_calls = {"n": 0}

    async def submit_handler(actor, args, ctx):
        submit_calls["n"] += 1
        raise AssertionError("logistics_submit must never be called in validation")

    gateway = ToolGateway(audit)
    gateway.register_handler("logistics_validate", make_logistics_validate_handler())
    gateway.register_handler("logistics_submit", submit_handler)

    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)

    result: LogisticsValidationResult = asyncio.run(
        run_logistics_validation(
            str(csv_path),
            actor=actor,
            registry=registry,
            gateway=gateway,
            audit_service=audit,
        )
    )

    # Read-only guarantee: validate ran, submit never did.
    assert submit_calls["n"] == 0
    assert any(
        c.tool_name == "logistics_validate" and c.status == "success"
        for c in gateway.tool_calls
    )
    assert all(c.tool_name == "logistics_validate" for c in gateway.tool_calls)

    # Aggregation matches the skill output schema (1-based rows).
    assert result.validated == 1
    assert result.invalid == 4
    assert len(result.field_errors) == 3  # bad tracking + bad card + short addr
    assert len(result.state_violations) == 1
    assert result.field_errors[0]["row"] >= 1


@pytest.mark.unit
def test_workflow_parse_error_is_reported(tmp_path: Path):
    bad = tmp_path / "missing.csv"
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="logistics_validate", risk_level=RiskLevel.L1))
    gateway = ToolGateway(audit)
    gateway.register_handler("logistics_validate", make_logistics_validate_handler())

    result = asyncio.run(
        run_logistics_validation(
            str(bad),
            actor=ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV),
            registry=registry,
            gateway=gateway,
            audit_service=audit,
        )
    )
    assert result.error is not None


# --- skill + policy wiring --------------------------------------------------
def test_logistics_validate_policy_allows_readonly():
    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)
    decision = can_execute(actor, "logistics_validate")
    assert decision.allowed is True
    assert decision.risk_level == RiskLevel.L1
    assert decision.approval_required is False  # read-only, never auto-approve


def test_skill_loads_for_logistics_validation():
    skill = load_skill(TaskType.LOGISTICS_VALIDATION)
    assert skill.task_type is TaskType.LOGISTICS_VALIDATION
    assert "rag_query" in skill.tools
    assert "db_query" in skill.tools
    assert "logistics_validation" in skill.source_path
