"""Unit tests for the cashback table parser / tool (phase H5, DEV_SPEC §H5).

Acceptance: configurable field mapping; duplicate records and amount-format
anomalies are detectable. Tests are hermetic — they exercise the pure
:class:`CashbackTableParser` plus the file readers (CSV via stdlib, XLSX via
openpyxl when available).
"""

from __future__ import annotations

import asyncio
import csv
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from fiat_agent.auth.policy import can_execute
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel
from fiat_agent.tool_gateway.cashback_tools import (
    AmountFormatError,
    CashbackParseTool,
    CashbackTableParser,
    IssueType,
    parse_amount,
    read_rows,
)


# --- raw fixtures ---------------------------------------------------------
def _zh_rows() -> list[dict]:
    """Default (Chinese-header) source rows incl. a dup and a bad amount."""
    return [
        {"交易号": "T1001", "用户ID": "U1", "金额": "¥1,234.50", "币种": "CNY", "状态": "paid", "日期": "2026-01-01"},
        {"交易号": "T1002", "用户ID": "U2", "金额": "(88.00)", "币种": "CNY", "状态": "paid", "日期": "2026-01-02"},
        {"交易号": "T1001", "用户ID": "U1", "金额": "1,234.50", "币种": "CNY", "状态": "paid", "日期": "2026-01-01"},  # dup
        {"交易号": "T1003", "用户ID": "U3", "金额": "N/A", "币种": "CNY", "状态": "pending", "日期": "2026-01-03"},  # bad
        {"交易号": "T1004", "用户ID": "U4", "金额": "abc", "币种": "CNY", "状态": "paid", "日期": "2026-01-04"},      # bad
    ]


def _en_rows() -> list[dict]:
    """English-header variant to prove the mapping is configurable."""
    return [
        {"txn_id": "A1", "user": "U1", "amount": "10.00", "ccy": "USD", "state": "paid", "day": "2026-02-01"},
        {"txn_id": "A1", "user": "U1", "amount": "10.00", "ccy": "USD", "state": "paid", "day": "2026-02-01"},  # dup
    ]


# --- parse_amount ---------------------------------------------------------
def test_parse_amount_handles_symbols_and_separators():
    assert parse_amount("¥1,234.50") == Decimal("1234.50")
    assert parse_amount("$1,000.00") == Decimal("1000.00")
    assert parse_amount(" 500 ") == Decimal("500")
    assert parse_amount("(88.00)") == Decimal("-88.00")  # accounting negative
    assert parse_amount("1.234,50") == Decimal("1234.50")  # EU decimal comma


def test_parse_amount_rejects_garbage():
    for bad in ("abc", "N/A", "", None, "1.234,5x"):
        with pytest.raises(AmountFormatError):
            parse_amount(bad)


# --- configurable field mapping ------------------------------------------
def test_default_field_map_parses_chinese_headers():
    res = CashbackTableParser().parse_rows(_zh_rows())
    assert res.row_count == 5
    assert res.records[0].amount == Decimal("1234.50")
    assert res.records[0].currency == "CNY"
    assert res.records[1].amount == Decimal("-88.00")  # parentheses negative


def test_custom_field_map_parses_english_headers():
    parser = CashbackTableParser(
        field_map={
            "txn_id": "txn_id",
            "user_id": "user",
            "amount": "amount",
            "currency": "ccy",
            "status": "state",
            "date": "day",
        }
    )
    res = parser.parse_rows(_en_rows())
    assert res.row_count == 2
    assert res.records[0].amount == Decimal("10.00")
    assert res.records[0].currency == "USD"


# --- duplicate detection --------------------------------------------------
def test_duplicate_detection_flags_later_occurrences():
    res = CashbackTableParser().parse_rows(_zh_rows())
    assert len(res.duplicates) == 1
    dup = res.duplicates[0]
    assert dup.type is IssueType.DUPLICATE
    assert dup.txn_id == "T1001"
    assert dup.row_index == 2  # second occurrence
    # the first occurrence is still a normal record
    assert res.records[0].txn_id == "T1001"


def test_custom_dedup_key():
    rows = [
        {"交易号": "X", "用户ID": "U1", "金额": "1.00", "币种": "CNY", "状态": "paid", "日期": "d"},
        {"交易号": "Y", "用户ID": "U1", "金额": "1.00", "币种": "CNY", "状态": "paid", "日期": "d"},  # same user_id
    ]
    parser = CashbackTableParser(dedup_key="user_id")
    res = parser.parse_rows(rows)
    assert len(res.duplicates) == 1
    assert res.duplicates[0].txn_id == "U1"


# --- amount format anomalies ---------------------------------------------
def test_amount_format_anomalies_collected():
    res = CashbackTableParser().parse_rows(_zh_rows())
    # rows 3 (N/A) and 4 (abc) should be flagged; row 0/1/2 parse fine.
    assert len(res.amount_errors) == 2
    flagged = {e.row_index for e in res.amount_errors}
    assert flagged == {3, 4}
    assert all(e.type is IssueType.AMOUNT_FORMAT for e in res.amount_errors)
    # good rows still have a parsed amount
    assert res.records[0].amount is not None
    assert res.records[4].amount is None


def test_missing_amount_field_is_anomaly():
    rows = [{"交易号": "T1", "用户ID": "U1", "币种": "CNY", "状态": "paid", "日期": "d"}]
    res = CashbackTableParser().parse_rows(rows)
    assert len(res.amount_errors) == 1
    assert res.amount_errors[0].detail == "missing amount"


# --- file readers ---------------------------------------------------------
def test_read_rows_csv(tmp_path: Path):
    p = tmp_path / "rebate.csv"
    p.write_text(
        "交易号,用户ID,金额,币种,状态,日期\nT1,U1,100.00,CNY,paid,2026-01-01\n",
        encoding="utf-8-sig",
    )
    rows = read_rows(p)
    res = CashbackTableParser().parse_rows(rows)
    assert res.row_count == 1
    assert res.records[0].amount == Decimal("100.00")


def test_read_rows_xlsx_round_trip(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "rebate.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["交易号", "用户ID", "金额", "币种", "状态", "日期"])
    ws.append(["T1", "U1", "200.00", "CNY", "paid", "2026-01-01"])
    ws.append(["T1", "U1", "200.00", "CNY", "paid", "2026-01-01"])  # dup
    wb.save(p)

    rows = read_rows(p)
    res = CashbackTableParser().parse_rows(rows)
    assert res.row_count == 2
    assert res.records[0].amount == Decimal("200.00")
    assert len(res.duplicates) == 1


def test_read_rows_unsupported_type(tmp_path: Path):
    p = tmp_path / "rebate.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        read_rows(p)


# --- tool + policy wiring -------------------------------------------------
def test_tool_execute_via_file(tmp_path: Path):
    p = tmp_path / "r.csv"
    p.write_text(
        "交易号,用户ID,金额,币种,状态,日期\nT1,U1,5.00,CNY,paid,d\nT1,U1,5.00,CNY,paid,d\n",
        encoding="utf-8-sig",
    )
    out = asyncio.run(CashbackParseTool().execute({"file_path": str(p)}))
    assert out["row_count"] == 2
    assert out["duplicate_count"] == 1


def test_cashback_parse_policy_allows_readonly():
    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)
    decision = can_execute(actor, "cashback_parse")
    assert decision.allowed is True
    assert decision.risk_level == RiskLevel.L1
    # never requires approval — it only reads.
    assert decision.approval_required is False
