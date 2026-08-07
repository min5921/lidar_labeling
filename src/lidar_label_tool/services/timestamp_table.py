from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping


TimestampUnit = Literal["ns", "us", "ms", "s"]
_UNIT_SCALE: dict[TimestampUnit, int] = {
    "ns": 1,
    "us": 1_000,
    "ms": 1_000_000,
    "s": 1_000_000_000,
}
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class TimestampTableError(ValueError):
    def __init__(self, code: str, message: str, *, row_number: int | None = None) -> None:
        self.code = code
        self.row_number = row_number
        location = f" row {row_number}" if row_number is not None else ""
        super().__init__(f"{code}{location}: {message}")


@dataclass(frozen=True, slots=True)
class TimestampRow:
    sample_id: str
    timestamp_ns: int
    source_row_number: int


@dataclass(frozen=True, slots=True)
class TimestampTable:
    path: Path
    sample_id_column: str
    value_column: str
    unit: TimestampUnit
    clock_domain: str
    offset_ns: int
    rows: tuple[TimestampRow, ...]
    by_sample_id: Mapping[str, int]
    duplicate_timestamp_count: int
    reordered_row_count: int

    def timestamp_for(self, source_sample_id: str) -> int | None:
        return self.by_sample_id.get(source_sample_id)


def read_timestamp_table(
    path: Path,
    *,
    sample_id_column: str,
    value_column: str,
    unit: TimestampUnit,
    clock_domain: str,
    offset_ns: int = 0,
) -> TimestampTable:
    """Read integer timestamps exactly and normalize them to signed int64 nanoseconds."""
    table_path = Path(path)
    if unit not in _UNIT_SCALE:
        raise TimestampTableError("timestamp_unit_invalid", f"unsupported unit: {unit}")
    if not sample_id_column or not value_column:
        raise TimestampTableError(
            "timestamp_column_invalid",
            "sample_id_column and value_column are required",
        )
    if not clock_domain:
        raise TimestampTableError(
            "clock_domain_invalid",
            "clock_domain must not be empty",
        )
    try:
        stream = table_path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise TimestampTableError(
            "timestamp_file_unreadable",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    rows: list[TimestampRow] = []
    values: dict[str, int] = {}
    timestamp_counts: dict[int, int] = {}
    reordered = 0
    previous: int | None = None
    try:
        with stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise TimestampTableError(
                    "timestamp_header_missing",
                    "CSV has no header",
                )
            missing = {
                sample_id_column,
                value_column,
            } - set(reader.fieldnames)
            if missing:
                raise TimestampTableError(
                    "timestamp_column_missing",
                    f"missing columns: {', '.join(sorted(missing))}",
                )
            for row_number, raw in enumerate(reader, start=2):
                sample_id = raw.get(sample_id_column)
                value = raw.get(value_column)
                if sample_id is None or sample_id == "":
                    raise TimestampTableError(
                        "timestamp_sample_id_empty",
                        "sample ID is empty",
                        row_number=row_number,
                    )
                if sample_id in values:
                    raise TimestampTableError(
                        "timestamp_sample_id_duplicate",
                        f"duplicate sample ID: {sample_id!r}",
                        row_number=row_number,
                    )
                if value is None or value.strip() == "":
                    raise TimestampTableError(
                        "timestamp_value_empty",
                        f"timestamp is empty for sample {sample_id!r}",
                        row_number=row_number,
                    )
                try:
                    raw_integer = int(value.strip(), 10)
                except ValueError as exc:
                    raise TimestampTableError(
                        "timestamp_value_invalid",
                        f"timestamp must be an integer: {value!r}",
                        row_number=row_number,
                    ) from exc
                if raw_integer < 0:
                    raise TimestampTableError(
                        "timestamp_value_negative",
                        f"timestamp must be non-negative: {raw_integer}",
                        row_number=row_number,
                    )
                normalized = raw_integer * _UNIT_SCALE[unit] + offset_ns
                if not _INT64_MIN <= normalized <= _INT64_MAX:
                    raise TimestampTableError(
                        "timestamp_out_of_range",
                        f"normalized timestamp is outside int64: {normalized}",
                        row_number=row_number,
                    )
                if previous is not None and normalized < previous:
                    reordered += 1
                previous = normalized
                values[sample_id] = normalized
                timestamp_counts[normalized] = timestamp_counts.get(normalized, 0) + 1
                rows.append(TimestampRow(sample_id, normalized, row_number))
    except csv.Error as exc:
        raise TimestampTableError(
            "timestamp_csv_invalid",
            str(exc),
        ) from exc

    if not rows:
        raise TimestampTableError("timestamp_table_empty", "CSV has no data rows")
    duplicate_count = sum(count - 1 for count in timestamp_counts.values() if count > 1)
    return TimestampTable(
        path=table_path.resolve(),
        sample_id_column=sample_id_column,
        value_column=value_column,
        unit=unit,
        clock_domain=clock_domain,
        offset_ns=offset_ns,
        rows=tuple(rows),
        by_sample_id=MappingProxyType(values),
        duplicate_timestamp_count=duplicate_count,
        reordered_row_count=reordered,
    )
