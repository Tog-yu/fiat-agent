"""Logistics table parsing + validation tool (phase H7, DEV_SPEC §H7).

Parses an imported logistics spreadsheet (``.csv`` / ``.xlsx``) and runs two
kinds of deterministic checks, both mandated by DEV_SPEC §2.2 to be
**deterministic (no LLM)**:

1. **Field validation** — tracking number, address and (optional) card number
   are checked for presence / format anomalies.
2. **State-machine validation** — each row describes a logistics status
   transition (``prev_status`` → ``new_status``); illegal transitions such as
   *created → delivered* (从未发货直接到已签收) are rejected.

This is a **read-only** validation step. No production logistics data is ever
mutated here; the (optional) production-submit guard is H8.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# openpyxl is optional; only needed when parsing .xlsx files. It is imported
# lazily so the CSV path works with zero third-party dependencies.
try:  # pragma: no cover - environment dependent
    import openpyxl

    _HAS_OPENPYXL = True
except Exception:  # pragma: no cover - optional dep
    openpyxl = None  # type: ignore[assignment]
    _HAS_OPENPYXL = False


# --------------------------------------------------------------------------- #
# Logistics state machine (deterministic, DEV_SPEC §2.2)
# --------------------------------------------------------------------------- #
class LogisticsStatus(str, Enum):
    """Canonical logistics lifecycle states."""

    CREATED = "created"              # 已创建 / 待揽收 / 未发货
    PICKED_UP = "picked_up"          # 已揽收
    IN_TRANSIT = "in_transit"        # 运输中
    OUT_FOR_DELIVERY = "out_for_delivery"  # 派送中
    DELIVERED = "delivered"          # 已签收
    EXCEPTION = "exception"          # 异常
    RETURNED = "returned"            # 已退回


# Allowed forward edges of the lifecycle. ``RETURNED`` is terminal.
_ALLOWED_TRANSITIONS: dict[LogisticsStatus, set[LogisticsStatus]] = {
    LogisticsStatus.CREATED: {LogisticsStatus.PICKED_UP},
    LogisticsStatus.PICKED_UP: {LogisticsStatus.IN_TRANSIT},
    LogisticsStatus.IN_TRANSIT: {
        LogisticsStatus.OUT_FOR_DELIVERY,
        LogisticsStatus.EXCEPTION,
    },
    LogisticsStatus.OUT_FOR_DELIVERY: {
        LogisticsStatus.DELIVERED,
        LogisticsStatus.EXCEPTION,
    },
    LogisticsStatus.EXCEPTION: {
        LogisticsStatus.IN_TRANSIT,
        LogisticsStatus.RETURNED,
    },
    LogisticsStatus.DELIVERED: {LogisticsStatus.RETURNED},
    LogisticsStatus.RETURNED: set(),  # terminal — no outgoing edges
}

# Alias map: normalized (lowercased) source label -> canonical status.
_RAW_ALIASES: dict[LogisticsStatus, list[str]] = {
    LogisticsStatus.CREATED: ["已创建", "下单", "待揽收", "已下单", "未发货", "新建"],
    LogisticsStatus.PICKED_UP: ["已揽收", "已取件", "揽收"],
    LogisticsStatus.IN_TRANSIT: ["运输中", "在途", "转运中", "运输"],
    LogisticsStatus.OUT_FOR_DELIVERY: ["派送中", "派件中", "投递中", "派送"],
    LogisticsStatus.DELIVERED: ["已签收", "签收", "妥投", "签收完成"],
    LogisticsStatus.EXCEPTION: ["异常", "问题件", "异常件"],
    LogisticsStatus.RETURNED: ["已退回", "退回", "退货", "退回件"],
}

_STATUS_ALIASES: dict[str, LogisticsStatus] = {}
for _canon, _aliases in _RAW_ALIASES.items():
    _STATUS_ALIASES[_canon.value] = _canon
    for _alias in _aliases:
        _STATUS_ALIASES[_alias.lower()] = _canon


def normalize_status(raw: Any) -> Optional[LogisticsStatus]:
    """Map a raw status string (Chinese or English) to a canonical enum.

    Returns ``None`` for blank / unknown values so the caller can flag them as
    field anomalies rather than crash.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s == "":
        return None
    return _STATUS_ALIASES.get(s)


class IllegalStateTransitionError(Exception):
    """Raised when a status transition is not permitted by the state machine."""

    def __init__(self, prev: LogisticsStatus, new: LogisticsStatus) -> None:
        self.prev = prev
        self.new = new
        super().__init__(f"illegal logistics transition: {prev.value} -> {new.value}")


class LogisticsStateMachine:
    """Deterministic validator for logistics status transitions.

    Mirrors the determinism requirement in DEV_SPEC §2.2: no model is involved.
    """

    __test__ = False  # not a pytest test class

    def is_allowed(self, prev: Optional[LogisticsStatus], new: Optional[LogisticsStatus]) -> bool:
        """Return ``True`` iff ``prev -> new`` is a legal transition.

        A no-op update (``prev == new``) is always allowed. ``None`` inputs
        (unknown / missing status) are treated as *not* validatable and return
        ``False`` — the caller flags them separately as field anomalies.
        """
        if prev is None or new is None:
            return False
        if prev == new:
            return True  # benign no-op update
        return new in _ALLOWED_TRANSITIONS.get(prev, set())

    def validate(self, prev: Optional[LogisticsStatus], new: Optional[LogisticsStatus]) -> None:
        """Raise :class:`IllegalStateTransitionError` if the edge is illegal."""
        if not self.is_allowed(prev, new):
            raise IllegalStateTransitionError(prev or LogisticsStatus.CREATED,
                                             new or LogisticsStatus.DELIVERED)


# --------------------------------------------------------------------------- #
# Field-level validation helpers
# --------------------------------------------------------------------------- #
_TRACKING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{5,31}$")

# Placeholder strings that should never appear as a real delivery address.
_ADDRESS_PLACEHOLDERS = {"无", "none", "n/a", "na", "null", "test", "测试", "地址"}


def is_valid_card_no(raw: Any) -> bool:
    """Return ``True`` iff the card number is 12–19 digits passing Luhn.

    Used for the (optional) COD / card-on-delivery number in a logistics row.
    """
    if raw is None:
        return False
    digits = re.sub(r"[\s-]", "", str(raw))
    if not digits.isdigit() or not (12 <= len(digits) <= 19):
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --------------------------------------------------------------------------- #
# Result data structures
# --------------------------------------------------------------------------- #
class LogisticsParseError(Exception):
    """Unrecoverable parse error (e.g. unsupported file type, missing dep)."""


@dataclass
class LogisticsFieldError:
    """A field-level anomaly on a specific row."""

    __test__ = False  # not a pytest test class

    type: str = "field_error"
    row_index: int = 0
    field: str = ""
    detail: str = ""
    tracking_no: Optional[str] = None


@dataclass
class LogisticsStateViolation:
    """An illegal status transition on a specific row."""

    __test__ = False  # not a pytest test class

    type: str = "state_violation"
    row_index: int = 0
    from_status: str = ""
    to_status: str = ""
    detail: str = ""
    tracking_no: Optional[str] = None


@dataclass
class LogisticsRecord:
    """One normalized logistics row (read-only projection of the source)."""

    __test__ = False  # not a pytest test class

    row_index: int
    tracking_no: Optional[str]
    prev_status: Optional[str]
    new_status: Optional[str]
    address: Optional[str]
    card_no: Optional[str]
    updated_at: Optional[str]
    raw: dict[str, Any]


@dataclass
class LogisticsParseResult:
    """Outcome of parsing + validating a logistics file."""

    __test__ = False  # not a pytest test class

    row_count: int
    records: list[LogisticsRecord] = field(default_factory=list)
    field_errors: list[LogisticsFieldError] = field(default_factory=list)
    state_violations: list[LogisticsStateViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_with_issues(self) -> set[int]:
        """Row indices that have at least one field error or state violation."""
        s: set[int] = set()
        s.update(e.row_index for e in self.field_errors)
        s.update(v.row_index for v in self.state_violations)
        return s

    def to_dict(self) -> dict[str, Any]:
        def _rec(r: LogisticsRecord) -> dict[str, Any]:
            return {
                "row_index": r.row_index,
                "tracking_no": r.tracking_no,
                "prev_status": r.prev_status,
                "new_status": r.new_status,
                "address": r.address,
                "card_no": r.card_no,
                "updated_at": r.updated_at,
            }

        return {
            "row_count": self.row_count,
            "record_count": len(self.records),
            "field_error_count": len(self.field_errors),
            "state_violation_count": len(self.state_violations),
            "records": [_rec(r) for r in self.records],
            "field_errors": [
                {
                    "type": e.type,
                    "row_index": e.row_index,
                    "field": e.field,
                    "detail": e.detail,
                    "tracking_no": e.tracking_no,
                }
                for e in self.field_errors
            ],
            "state_violations": [
                {
                    "type": v.type,
                    "row_index": v.row_index,
                    "from_status": v.from_status,
                    "to_status": v.to_status,
                    "detail": v.detail,
                    "tracking_no": v.tracking_no,
                }
                for v in self.state_violations
            ],
            "warnings": list(self.warnings),
        }


def _norm(value: Any) -> Optional[str]:
    """Normalize a raw cell value to a trimmed string (None if blank)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


# Default column header -> logical field mapping (Chinese logistics export).
DEFAULT_FIELD_MAP: dict[str, str] = {
    "tracking_no": "运单号",
    "prev_status": "原状态",
    "new_status": "新状态",
    "address": "地址",
    "card_no": "卡号",
    "updated_at": "更新时间",
}


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``.csv`` or ``.xlsx`` file into a list of header->value dicts.

    CSV uses the stdlib (UTF-8 with BOM tolerant). XLSX requires ``openpyxl``.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    if suffix in (".xlsx", ".xlsm"):
        if not _HAS_OPENPYXL:
            raise LogisticsParseError(
                "openpyxl is required to parse .xlsx files; install it first"
            )
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)  # type: ignore[union-attr]
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        out: list[dict[str, Any]] = []
        for r in rows[1:]:
            out.append(
                {headers[i]: (r[i] if i < len(r) else None) for i in range(len(headers))}
            )
        return out
    raise LogisticsParseError(f"unsupported file type: {suffix or '(none)'}")


class LogisticsTableParser:
    """Pure parsing + validation over in-memory rows (no file IO, easy to test)."""

    __test__ = False  # not a pytest test class

    def __init__(
        self,
        field_map: Optional[dict[str, str]] = None,
        state_machine: Optional[LogisticsStateMachine] = None,
    ) -> None:
        # Configurable mapping: logical field -> source column header.
        self.field_map = dict(field_map) if field_map else dict(DEFAULT_FIELD_MAP)
        self._sm = state_machine or LogisticsStateMachine()

    def _lookup(self, row: dict[str, Any], logical: str) -> Any:
        col = self.field_map.get(logical)
        if col is None:
            return None
        return row.get(col)

    def parse_rows(self, rows: list[dict[str, Any]]) -> LogisticsParseResult:
        """Parse and validate raw rows into records + field/state issues.

        Every row is checked for field anomalies (tracking number, address,
        card number, unknown status) and, when both statuses are known, for an
        illegal state-machine transition. A single row may carry several
        issues; parsing never aborts on the first error.
        """
        result = LogisticsParseResult(row_count=len(rows))

        for idx, raw in enumerate(rows):
            tracking = _norm(self._lookup(raw, "tracking_no"))
            prev_raw = _norm(self._lookup(raw, "prev_status"))
            new_raw = _norm(self._lookup(raw, "new_status"))
            address = _norm(self._lookup(raw, "address"))
            card = _norm(self._lookup(raw, "card_no"))
            updated = _norm(self._lookup(raw, "updated_at"))

            # --- field validation: tracking number (required) ----------
            if not tracking:
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="tracking_no", detail="缺少运单号", tracking_no=tracking,
                    )
                )
            elif not _TRACKING_RE.match(tracking):
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="tracking_no",
                        detail="运单号格式异常（应为 6–32 位字母/数字/连字符）",
                        tracking_no=tracking,
                    )
                )

            # --- field validation: address (required) ------------------
            if not address or len(address) < 5:
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="address", detail="地址异常（缺失或过短）", tracking_no=tracking,
                    )
                )
            elif address.lower() in _ADDRESS_PLACEHOLDERS:
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="address", detail="地址疑似占位符", tracking_no=tracking,
                    )
                )

            # --- field validation: card number (optional, format-checked) --
            if card and not is_valid_card_no(card):
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="card_no",
                        detail="卡号格式异常（应为 12–19 位数字且通过 Luhn 校验）",
                        tracking_no=tracking,
                    )
                )

            # --- status normalization (feed the state machine) --------
            prev = normalize_status(prev_raw)
            new = normalize_status(new_raw)
            if prev_raw and prev is None:
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="prev_status", detail=f"未知原状态 {prev_raw!r}",
                        tracking_no=tracking,
                    )
                )
            if new_raw and new is None:
                result.field_errors.append(
                    LogisticsFieldError(
                        type="field_error", row_index=idx,
                        field="new_status", detail=f"未知新状态 {new_raw!r}",
                        tracking_no=tracking,
                    )
                )

            # --- state-machine validation -----------------------------
            if prev is not None and new is not None and prev != new:
                if not self._sm.is_allowed(prev, new):
                    result.state_violations.append(
                        LogisticsStateViolation(
                            type="state_violation", row_index=idx,
                            from_status=prev.value, to_status=new.value,
                            detail=f"非法状态流转：{prev.value} → {new.value}",
                            tracking_no=tracking,
                        )
                    )

            result.records.append(
                LogisticsRecord(
                    row_index=idx,
                    tracking_no=tracking,
                    prev_status=prev_raw,
                    new_status=new_raw,
                    address=address,
                    card_no=card,
                    updated_at=updated,
                    raw=raw,
                )
            )

        return result


class LogisticsValidationTool:
    """Gateway-facing logistics validation tool (bound to a parser config)."""

    __test__ = False  # not a pytest test class

    def __init__(self, field_map: Optional[dict[str, str]] = None) -> None:
        self._field_map = field_map

    async def validate_file(
        self, file_path: str | Path, field_map: Optional[dict[str, str]] = None
    ) -> LogisticsParseResult:
        rows = read_rows(file_path)
        parser = LogisticsTableParser(field_map if field_map is not None else self._field_map)
        return parser.parse_rows(rows)

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Gateway handler body: ``{"file_path": ..., "field_map"?: ...}``."""
        file_path = arguments.get("file_path")
        if not file_path:
            raise LogisticsParseError("missing required argument 'file_path'")
        result = await self.validate_file(file_path, arguments.get("field_map"))
        return result.to_dict()


def make_logistics_validate_handler(field_map: Optional[dict[str, str]] = None) -> Any:
    """Build an async gateway handler for the ``logistics_validate`` tool."""
    tool = LogisticsValidationTool(field_map)

    async def handler(actor: Any, arguments: dict[str, Any], context: Any = None) -> dict:
        return await tool.execute(arguments)

    return handler
