"""Cashback Excel/CSV parsing tool (phase H5, DEV_SPEC §H5).

Parses rebate / task-cashback spreadsheets (Excel ``.xlsx`` or ``.csv``) into
normalized records. The column->field mapping is **configurable** so the same
parser works across differently-headed source files; duplicate transaction ids
and unparseable amount strings are detected and surfaced as issues. This is a
**read-only** parse step — no production write happens here (the dry-run
reconciliation is H6).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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


class CashbackParseError(Exception):
    """Unrecoverable parse error (e.g. unsupported file type, missing dep)."""


class AmountFormatError(Exception):
    """Raised when a raw amount string cannot be normalized to a number."""


class IssueType(str, Enum):
    """Category of a problem found while parsing a row."""

    DUPLICATE = "duplicate"
    AMOUNT_FORMAT = "amount_format"
    MISSING_FIELD = "missing_field"


# Default column header -> logical field mapping. Headers use the Chinese
# labels common in rebate exports; override via ``field_map`` for other files.
DEFAULT_FIELD_MAP: dict[str, str] = {
    "txn_id": "交易号",
    "user_id": "用户ID",
    "amount": "金额",
    "currency": "币种",
    "status": "状态",
    "date": "日期",
}

# Currency symbols / spaces stripped before number parsing.
_CURRENCY_SYMBOLS = "¥$€£￥"


@dataclass
class CashbackRecord:
    """One normalized cashback row (read-only projection of the source)."""

    __test__ = False  # not a pytest test class

    row_index: int
    txn_id: Optional[str]
    user_id: Optional[str]
    amount: Optional[Decimal]
    currency: Optional[str]
    status: Optional[str]
    date: Optional[str]
    raw: dict[str, Any]


@dataclass
class CashbackIssue:
    """A problem detected on a specific row."""

    __test__ = False  # not a pytest test class

    type: IssueType
    row_index: int
    detail: str
    txn_id: Optional[str] = None


@dataclass
class CashbackParseResult:
    """Outcome of parsing a cashback file."""

    __test__ = False  # not a pytest test class

    row_count: int
    records: list[CashbackRecord] = field(default_factory=list)
    duplicates: list[CashbackIssue] = field(default_factory=list)
    amount_errors: list[CashbackIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def issues(self) -> list[CashbackIssue]:
        """All detected issues (duplicates + amount errors)."""
        return self.duplicates + self.amount_errors

    def to_dict(self) -> dict[str, Any]:
        def _rec(r: CashbackRecord) -> dict[str, Any]:
            return {
                "row_index": r.row_index,
                "txn_id": r.txn_id,
                "user_id": r.user_id,
                "amount": str(r.amount) if r.amount is not None else None,
                "currency": r.currency,
                "status": r.status,
                "date": r.date,
            }

        return {
            "row_count": self.row_count,
            "record_count": len(self.records),
            "duplicate_count": len(self.duplicates),
            "amount_error_count": len(self.amount_errors),
            "records": [_rec(r) for r in self.records],
            "duplicates": [
                {"type": i.type.value, "row_index": i.row_index,
                 "detail": i.detail, "txn_id": i.txn_id}
                for i in self.duplicates
            ],
            "amount_errors": [
                {"type": i.type.value, "row_index": i.row_index,
                 "detail": i.detail, "txn_id": i.txn_id}
                for i in self.amount_errors
            ],
            "warnings": list(self.warnings),
        }


def _norm(value: Any) -> Optional[str]:
    """Normalize a raw cell value to a trimmed string (None if blank)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def parse_amount(raw: Any) -> Decimal:
    """Normalize a messy amount string to a :class:`Decimal`.

    Handles a leading currency symbol (``¥ $ € £``), thousands separators,
    and accounting-style negatives ``(1,234.50)``. Raises
    :class:`AmountFormatError` for anything that is empty or non-numeric so the
    caller can record it as a *format anomaly* rather than crash.
    """
    if raw is None:
        raise AmountFormatError("empty amount")
    s = str(raw).strip()
    if s == "" or s.lower() in {"n/a", "na", "null", "none", "-"}:
        raise AmountFormatError(f"unparseable amount: {raw!r}")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.lstrip("+-")

    for ch in _CURRENCY_SYMBOLS + " ":
        s = s.replace(ch, "")

    # Resolve separator ambiguity: the *last* separator is the decimal point.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # EU form "1.234,50" -> comma is decimal, dot is thousands.
            s = s.replace(".", "").replace(",", ".")
        else:
            # US form "1,234.50" -> dot is decimal, comma is thousands.
            s = s.replace(",", "")
    elif "," in s and "." not in s:
        # Only comma: "1234,50" is a decimal comma; "1,234" / "1,234,567" are
        # thousands separators. Heuristic: a single comma followed by 1-2 digits
        # (and a leading integer part) is a decimal.
        parts = s.split(",")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[1]) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    try:
        value = Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise AmountFormatError(f"unparseable amount: {raw!r}") from exc

    return -value if negative else value


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``.csv`` or ``.xlsx`` file into a list of header->value dicts.

    CSV is read with the stdlib (UTF-8 with BOM tolerant). XLSX requires
    ``openpyxl``; a clear error is raised if it is missing.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    if suffix in (".xlsx", ".xlsm"):
        if not _HAS_OPENPYXL:
            raise CashbackParseError(
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
    raise CashbackParseError(f"unsupported file type: {suffix or '(none)'}")


class CashbackTableParser:
    """Pure parsing logic over in-memory rows (no file IO, easy to test)."""

    __test__ = False  # not a pytest test class

    def __init__(
        self,
        field_map: Optional[dict[str, str]] = None,
        dedup_key: str = "txn_id",
    ) -> None:
        # Configurable mapping: logical field -> source column header.
        self.field_map = dict(field_map) if field_map else dict(DEFAULT_FIELD_MAP)
        self.dedup_key = dedup_key

    def _lookup(self, row: dict[str, Any], logical: str) -> Any:
        col = self.field_map.get(logical)
        if col is None:
            return None
        return row.get(col)

    def parse_rows(self, rows: list[dict[str, Any]]) -> CashbackParseResult:
        """Parse raw rows into normalized records and detect issues.

        Duplicate detection uses ``dedup_key`` (default ``txn_id``); the first
        occurrence is kept, later ones are flagged. Amount anomalies (empty or
        non-numeric) are recorded per row without aborting the whole parse.
        """
        result = CashbackParseResult(row_count=len(rows))
        seen: dict[str, int] = {}

        for idx, raw in enumerate(rows):
            txn_id = _norm(self._lookup(raw, "txn_id"))
            user_id = _norm(self._lookup(raw, "user_id"))
            currency = _norm(self._lookup(raw, "currency"))
            status = _norm(self._lookup(raw, "status"))
            date = _norm(self._lookup(raw, "date"))

            amount_raw = self._lookup(raw, "amount")
            amount: Optional[Decimal] = None
            if amount_raw is None or _norm(amount_raw) is None:
                result.amount_errors.append(
                    CashbackIssue(IssueType.AMOUNT_FORMAT, idx, "missing amount", txn_id)
                )
            else:
                try:
                    amount = parse_amount(amount_raw)
                except AmountFormatError as exc:
                    result.amount_errors.append(
                        CashbackIssue(IssueType.AMOUNT_FORMAT, idx, str(exc), txn_id)
                    )

            record = CashbackRecord(
                row_index=idx,
                txn_id=txn_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
                status=status,
                date=date,
                raw=raw,
            )

            # Duplicate detection follows the configurable dedup_key (default txn_id).
            dedup_value = _norm(self._lookup(raw, self.dedup_key))
            if dedup_value:
                if dedup_value in seen:
                    result.duplicates.append(
                        CashbackIssue(
                            IssueType.DUPLICATE,
                            idx,
                            f"duplicate {self.dedup_key}={dedup_value!r} "
                            f"(first seen at row {seen[dedup_value]})",
                            dedup_value,
                        )
                    )
                else:
                    seen[dedup_value] = idx

            result.records.append(record)

        return result


class CashbackParseTool:
    """Gateway-facing cashback parse tool (bound to a parser config)."""

    __test__ = False  # not a pytest test class

    def __init__(
        self,
        field_map: Optional[dict[str, str]] = None,
        dedup_key: str = "txn_id",
    ) -> None:
        self._field_map = field_map
        self._dedup_key = dedup_key

    async def parse_file(
        self, file_path: str | Path, field_map: Optional[dict[str, str]] = None
    ) -> CashbackParseResult:
        rows = read_rows(file_path)
        parser = CashbackTableParser(
            field_map if field_map is not None else self._field_map,
            self._dedup_key,
        )
        return parser.parse_rows(rows)

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Gateway handler body: ``{"file_path": ..., "field_map"?: ...}``."""
        file_path = arguments.get("file_path")
        if not file_path:
            raise CashbackParseError("missing required argument 'file_path'")
        result = await self.parse_file(file_path, arguments.get("field_map"))
        return result.to_dict()


def make_cashback_parse_handler(
    field_map: Optional[dict[str, str]] = None,
    dedup_key: str = "txn_id",
) -> Any:
    """Build an async gateway handler for the ``cashback_parse`` tool."""
    tool = CashbackParseTool(field_map, dedup_key)

    async def handler(actor: Any, arguments: dict[str, Any], context: Any = None) -> dict:
        return await tool.execute(arguments)

    return handler
