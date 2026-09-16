from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TABLE = "ho_ngheo"

TASKS = {
    "aggregate",
    "group_aggregate",
    "list_records",
    "lookup_person",
    "compare_years",
    "summary",
    "multi_metric_table",
}

METRICS = {"count_households", "avg", "sum", "ratio"}
OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "IN", "LIKE"}
MAX_LIMIT = 100


@dataclass(frozen=True)
class Filter:
    col: str
    op: str
    value: Any


@dataclass(frozen=True)
class OrderBy:
    col: str
    direction: str = "asc"


@dataclass
class QueryPlan:
    task: str
    metric: str | None = None
    target_col: str | None = None
    filters: list[Filter] = field(default_factory=list)
    or_filters: list[Filter] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    select: list[str] = field(default_factory=list)
    order_by: OrderBy | None = None
    limit: int | None = None
    person_name: str | None = None

    # Optional ratio controls. Giữ mặc định rỗng để tương thích các plan cũ.
    # numerator_filters/denominator_filters dùng khi câu hỏi nói rõ mẫu số khác
    # quy ước mặc định, ví dụ: "tỷ lệ hộ cận nghèo trên tổng số hộ có ...".
    denominator_scope: str | None = None  # None | "per_group" | "global"
    numerator_filters: list[Filter] = field(default_factory=list)
    denominator_filters: list[Filter] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)