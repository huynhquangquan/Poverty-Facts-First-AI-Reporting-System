from __future__ import annotations

import re
import sqlite3
from typing import Any

import pandas as pd

from poverty_chatbot.config import DB_PATH
from core.schema import TABLE, Filter, OrderBy, QueryPlan
from core.catalog import (
    FLAG_GROUPS,
    NUMERIC_COLUMNS,
    FEATURE_CATALOG,
    SUPPORT_TERM_ALIASES,
    DERIVED_METRIC_DEFINITIONS,
    BASE_RECORD_COLUMNS,
)
from poverty_chatbot.query_plan import (
    validate_plan,
    vn_name_key,
    vn_text_key_keep_accents,
    _multi_metric_filter_cols,
    _ranking_position,
    _multi_numeric_metric_cols,
)

def _record_select_columns(plan: QueryPlan) -> list[str]:
    columns = list(plan.select or BASE_RECORD_COLUMNS)

    if "id_ho" not in columns:
        columns.append("id_ho")

    return list(dict.fromkeys(columns))

def _compile_single_filter_condition(item: Filter) -> tuple[str, list[Any]]:
    if item.op == "IN":
        values = list(item.value)
        return f"{item.col} IN ({','.join('?' for _ in values)})", values
    return f"{item.col} {item.op} ?", [item.value]


def _compile_filter_list_where(filters: list[Filter]) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for item in filters:
        cond, cond_params = _compile_single_filter_condition(item)
        clauses.append(cond)
        params.extend(cond_params)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params


def _ratio_target_condition(plan: QueryPlan) -> tuple[str, list[Any]]:
    target_filters = [
        item for item in plan.filters
        if item.col == plan.target_col and item.op in {"=", "IN"}
    ]

    if target_filters:
        clauses, params = [], []
        for item in target_filters:
            cond, cond_params = _compile_single_filter_condition(item)
            clauses.append(cond)
            params.extend(cond_params)
        return " AND ".join(clauses), params

    if plan.target_col == "gioi_tinh":
        return "gioi_tinh = 'Nữ'", []

    return f"{plan.target_col} = 1", []

RATIO_DISPLAY_TEXT_COLS = {
    "bien_dong_dau_ky",
    "gioi_tinh",
    "dan_toc_chi_tiet",
    "tinh_trang_nha",
    "nguon_nuoc",
    "suc_khoe_chu_ho",
    "trinh_do_hoc_van_chu_ho",
}

def _ratio_uses_global_denominator(question: str | None, plan: QueryPlan | None = None) -> bool:
    scope = getattr(plan, "denominator_scope", None) if plan is not None else None
    if scope in {"per_group", "global"}:
        return scope == "global"

    q_key = vn_name_key(question or "")

    per_group_signal = any(x in q_key for x in (
        "theo huyen", "tung huyen", "moi huyen",
        "theo xa", "tung xa", "moi xa",
        "theo dan toc", "theo gioi tinh", "theo phan loai",
    ))

    explicit_global_signal = any(x in q_key for x in (
        "toan tinh",
        "ca tinh",
        "toan bo du lieu",
        "tong toan tinh",
        "tong so ho toan tinh",
        "tong ho ra soat toan tinh",
        "tong so ho ra soat toan tinh",
    ))

    # "trên tổng số hộ theo huyện/xã" là mẫu số theo từng nhóm, không phải
    # mẫu số global. Chỉ dùng global khi câu hỏi nói rõ toàn tỉnh/toàn bộ dữ liệu.
    if per_group_signal and not explicit_global_signal:
        return False

    return explicit_global_signal


def _ratio_filter_parts(plan: QueryPlan, question: str | None = None) -> tuple[list[Filter], list[Filter]]:
    # Nếu planner đã set numerator_filters/denominator_filters rõ ràng thì
    # executor ưu tiên dùng chúng. Giữ getattr để tương thích schema cũ.
    if getattr(plan, "numerator_filters", None):
        denominator_filters = list(getattr(plan, "denominator_filters", []) or [])
        numerator_filters = list(getattr(plan, "numerator_filters", []) or [])
        return denominator_filters, numerator_filters

    # Compatibility path cho plan cũ:
    # - numerator = toàn bộ điều kiện lọc + target_col nếu target chưa nằm trong filter
    # - denominator = chỉ giữ filter nền, không giữ các đặc trưng thuộc tử số.
    numerator_filters = list(plan.filters)

    if plan.target_col and not any(
        item.col == plan.target_col and item.op in {"=", "IN"}
        for item in numerator_filters
    ):
        numerator_filters.append(Filter(plan.target_col, "=", 1))

    global_denominator = _ratio_uses_global_denominator(question, plan)

    denominator_filters: list[Filter] = []
    for item in plan.filters:
        if item.col == plan.target_col:
            continue

        # Năm luôn là filter nền.
        if item.col == "nam":
            denominator_filters.append(item)
            continue

        # Địa bàn là filter nền khi không dùng mẫu số global.
        if item.col in {"huyen", "xa_phuong"}:
            if not global_denominator:
                denominator_filters.append(item)
            continue

        # Phân loại hộ là mẫu số nền khi user nói rõ "hộ nghèo/cận nghèo/...".
        # Ví dụ: tỷ lệ thiếu BHYT của hộ nghèo = thiếu BHYT / tổng hộ nghèo.
        if item.col == "phan_loai":
            denominator_filters.append(item)
            continue

        # Các đặc trưng còn lại như giới tính, trẻ dưới 6, nhà kiên cố...
        # mặc định thuộc tử số, không thu hẹp mẫu số.
        continue

    return denominator_filters, numerator_filters


def _compile_filter_list_condition(filters: list[Filter]) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for item in filters:
        cond, cond_params = _compile_single_filter_condition(item)
        clauses.append(cond)
        params.extend(cond_params)
    return (" AND ".join(clauses) if clauses else "1=1"), params

def _ratio_display_select_sql(plan: QueryPlan) -> str:
    selects = []

    for item in plan.filters:
        if item.op == "=" and item.col in RATIO_DISPLAY_TEXT_COLS:
            selects.append(f"{_sql_lit(item.value)} AS {item.col}")

    # Cột nhị phân nhom_chu_ho_nu là biến tương đương với gioi_tinh = 'Nữ'.
    # Thêm cột hiển thị để result shape không mất thông tin người dùng hỏi.
    if (
        plan.target_col == "nhom_chu_ho_nu"
        and not any(item.col == "gioi_tinh" for item in plan.filters)
    ):
        selects.append("'Nữ' AS gioi_tinh")

    return (", ".join(dict.fromkeys(selects)) + ", ") if selects else ""

DEFAULT_LIST_RECORD_LIMIT = 50

CHILD_DEPRIVATION_METRICS = {
    "te_th_bhyt": ("so_tre_thieu_bhyt", "BHYT trẻ em"),
    "te_th_dinh_duong": ("so_tre_thieu_dinh_duong", "Dinh dưỡng trẻ em"),
    "te_th_di_hoc": ("so_tre_thieu_di_hoc", "Đi học trẻ em"),
}


def _child_deprivation_count_col(flag_col: str | None) -> str | None:
    item = CHILD_DEPRIVATION_METRICS.get(flag_col or "")
    return item[0] if item else None


def _child_deprivation_flag_for_count_col(count_col: str | None) -> str | None:
    for flag_col, (metric_col, _label) in CHILD_DEPRIVATION_METRICS.items():
        if metric_col == count_col:
            return flag_col
    return None


def _child_deprivation_flag_from_plan(plan: QueryPlan) -> str | None:
    if plan.target_col in CHILD_DEPRIVATION_METRICS:
        return plan.target_col
    for item in list(getattr(plan, "numerator_filters", []) or []) + list(plan.filters):
        if item.col in CHILD_DEPRIVATION_METRICS and item.op in {"=", "IN"}:
            return item.col
    return None


def _is_child_deprivation_ratio_question(question: str | None) -> bool:
    q_key = vn_name_key(question or "")
    if "tre" not in q_key:
        return False
    if not any(x in q_key for x in ("ty le", "ti le", "phan tram", "ty trong")):
        return False
    if re.search(r"\b(?:ty le|ti le)\s+(?:so\s+)?ho\b", q_key):
        return False
    return True


def _compile_child_deprivation_ratio_plan(
    plan: QueryPlan,
    question: str | None,
) -> tuple[str, tuple[Any, ...]] | None:
    flag_col = _child_deprivation_flag_from_plan(plan)
    count_col = _child_deprivation_count_col(flag_col)
    if not flag_col or not count_col or not _is_child_deprivation_ratio_question(question):
        return None

    base_filters = [
        item for item in plan.filters
        if item.col not in CHILD_DEPRIVATION_METRICS
    ]
    base_where, base_params = _compile_filter_list_where(base_filters)

    if plan.task == "aggregate":
        ratio_expr = (
            f"ROUND(COALESCE(SUM({count_col}), 0) * 100.0 "
            f"/ NULLIF(COALESCE(SUM(so_tre_em), 0), 0), 1)"
        )
        sql = (
            f"SELECT "
            f"COALESCE(SUM({count_col}), 0) AS so_tre_thieu, "
            f"COUNT(DISTINCT CASE WHEN {flag_col} = 1 THEN id_ho END) AS so_ho_co_tre_thieu, "
            f"COALESCE(SUM(so_tre_em), 0) AS tong_tre, "
            f"{ratio_expr} AS ty_le_pct, "
            f'{ratio_expr} AS "ty_le_%" '
            f"FROM {TABLE}{base_where}"
        )
        return sql, tuple(base_params)

    if plan.task == "group_aggregate" and plan.group_by and "tre_em" not in plan.group_by:
        group_cols = list(plan.group_by)
        groups_sql = ", ".join(group_cols)
        ratio_expr = (
            f"ROUND(COALESCE(SUM({count_col}), 0) * 100.0 "
            f"/ NULLIF(COALESCE(SUM(so_tre_em), 0), 0), 1)"
        )
        order_col = "ty_le_pct"
        if plan.order_by and plan.order_by.col in {
            "so_tre_thieu", "so_ho_co_tre_thieu", "tong_tre", "ty_le_pct", "ty_le_%",
        }:
            order_col = "ty_le_pct" if plan.order_by.col == "ty_le_%" else plan.order_by.col
        direction = plan.order_by.direction.upper() if plan.order_by else "DESC"
        order_sql = f"{order_col} {direction}, " + ", ".join(f"{col} ASC" for col in group_cols)
        limit_sql = f" LIMIT {int(plan.limit)}" if plan.limit else ""
        sql = (
            f"SELECT {groups_sql}, "
            f"COALESCE(SUM({count_col}), 0) AS so_tre_thieu, "
            f"COUNT(DISTINCT CASE WHEN {flag_col} = 1 THEN id_ho END) AS so_ho_co_tre_thieu, "
            f"COALESCE(SUM(so_tre_em), 0) AS tong_tre, "
            f"{ratio_expr} AS ty_le_pct, "
            f'{ratio_expr} AS "ty_le_%" '
            f"FROM {TABLE}{base_where} "
            f"GROUP BY {groups_sql} "
            f"ORDER BY {order_sql}{limit_sql}"
        )
        return sql, tuple(base_params)

    return None


def _compile_child_deprivation_group_plan(plan: QueryPlan) -> tuple[str, tuple[Any, ...]] | None:
    if plan.task not in {"group_aggregate", "compare_years"} or "tre_em" not in plan.group_by:
        return None

    group = FLAG_GROUPS.get("tre_em")
    if not group:
        return None

    label_col = group["label_col"]
    mapping = dict(group["columns"])
    requested_cols = {
        item.col
        for item in plan.filters
        if item.op == "=" and item.value == 1 and item.col in mapping.values()
    }
    if requested_cols:
        mapping = {label: col for label, col in mapping.items() if col in requested_cols}

    where, params = _base_where_from_filters(plan.filters)
    selects: list[str] = []
    for label, flag_col in mapping.items():
        count_col = _child_deprivation_count_col(flag_col)
        if not count_col:
            continue
        ratio_expr = (
            f"ROUND(COALESCE(SUM({count_col}), 0) * 100.0 "
            f"/ NULLIF(COALESCE(SUM(so_tre_em), 0), 0), 1)"
        )
        year_select = "nam, " if plan.task == "compare_years" else ""
        group_by = " GROUP BY nam" if plan.task == "compare_years" else ""
        selects.append(
            f"SELECT {_sql_lit(label)} AS {label_col}, "
            f"{year_select}"
            f"COALESCE(SUM({count_col}), 0) AS so_tre_thieu, "
            f"COUNT(DISTINCT CASE WHEN {flag_col} = 1 THEN id_ho END) AS so_ho_co_tre_thieu, "
            f"COALESCE(SUM(so_tre_em), 0) AS tong_tre, "
            f"{ratio_expr} AS ty_le_pct, "
            f'{ratio_expr} AS "ty_le_%" '
            f"FROM {TABLE}{where}{group_by}"
        )

    if not selects:
        return None

    order_col = "ty_le_pct" if plan.metric == "ratio" else "so_tre_thieu"
    if plan.order_by and plan.order_by.col in {"so_tre_thieu", "so_ho_co_tre_thieu", "tong_tre", "ty_le_%", "ty_le_pct"}:
        order_col = "ty_le_pct" if plan.order_by.col == "ty_le_%" else plan.order_by.col
    direction = plan.order_by.direction.upper() if plan.order_by else "DESC"
    order_parts = [f"{order_col} {direction}", f"{label_col} ASC"]
    if plan.task == "compare_years":
        order_parts = ["nam ASC", *order_parts]
    limit_sql = f" LIMIT {int(plan.limit)}" if plan.limit and plan.task == "group_aggregate" else ""
    sql = f"SELECT * FROM ({' UNION ALL '.join(selects)}) AS child_deprivation ORDER BY {', '.join(order_parts)}{limit_sql}"
    return sql, tuple(params * len(selects))


def compile_plan(plan: QueryPlan, question: str | None = None) -> tuple[str, tuple[Any, ...]]:
    plan = validate_plan(plan)
    clauses, params = ([], [])
    filters = list(plan.filters)
    if plan.metric == "sum":
        own_child_flag = _child_deprivation_flag_for_count_col(plan.target_col)
        if own_child_flag:
            filters = [item for item in filters if item.col != own_child_flag]
    if plan.task == 'lookup_person':
        filters.append(Filter('chu_ho', 'LIKE', f'%{plan.person_name}%'))
    for item in filters:
        if item.op == 'IN':
            values = list(item.value)
            clauses.append(f"{item.col} IN ({','.join(('?' for _ in values))})")
            params.extend(values)
        else:
            clauses.append(f'{item.col} {item.op} ?')
            params.append(item.value)
    if plan.or_filters:
        or_clauses = []
        for item in plan.or_filters:
            if item.op == 'IN':
                values = list(item.value)
                or_clauses.append(f"{item.col} IN ({','.join(('?' for _ in values))})")
                params.extend(values)
            else:
                or_clauses.append(f'{item.col} {item.op} ?')
                params.append(item.value)
        if or_clauses:
            clauses.append('(' + ' OR '.join(or_clauses) + ')')
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    if plan.task in {'list_records', 'lookup_person'}:
        columns = _record_select_columns(plan)
        order = plan.order_by or OrderBy('chu_ho', 'asc')
        order_parts = [f"{order.col} {order.direction.upper()}"]

        if order.col != "chu_ho":
            order_parts.append("chu_ho ASC")

        order_parts.append("MIN(rowid) ASC")

        order_sql = ", ".join(order_parts)
        effective_limit = plan.limit
        if plan.task == 'list_records' and effective_limit is None:
            effective_limit = DEFAULT_LIST_RECORD_LIMIT
        limit_sql = f' LIMIT {int(effective_limit)}' if effective_limit else ''

        sql = (
            f"SELECT {', '.join(columns)} "
            f"FROM {TABLE}{where} "
            f"GROUP BY id_ho "
            f"ORDER BY {order_sql}{limit_sql}"
        )
        return (sql, tuple(params))
    if plan.task == 'summary':
        sql = f'SELECT COUNT(DISTINCT id_ho) AS tong_ho, COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS ho_ngheo, COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS ho_can_ngheo, COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS ho_khong_ngheo FROM {TABLE}{where}'
        return (sql, tuple(['Hộ nghèo', 'Hộ cận nghèo', 'Hộ không nghèo'] + params))
    child_ratio_sql = _compile_child_deprivation_ratio_plan(plan, question)
    if child_ratio_sql is not None:
        return child_ratio_sql
    child_group_sql = _compile_child_deprivation_group_plan(plan)
    if child_group_sql is not None:
        return child_group_sql
    if plan.metric == 'ratio' and plan.task == 'aggregate':
        denominator_filters, numerator_filters = _ratio_filter_parts(plan, question)
        ratio_where, ratio_params = _compile_filter_list_where(denominator_filters)
        target_condition, target_params = _compile_filter_list_condition(numerator_filters)

        ratio_expr = (
            f"ROUND(COUNT(DISTINCT CASE WHEN {target_condition} THEN id_ho END) "
            f"* 100.0 / NULLIF(COUNT(DISTINCT id_ho), 0), 1)"
        )

        extra_select = _ratio_display_select_sql(plan)

        sql = (
            f"SELECT {extra_select}"
            f"COUNT(DISTINCT CASE WHEN {target_condition} THEN id_ho END) AS so_ho, "
            f"COUNT(DISTINCT id_ho) AS tong_ho, "
            f"{ratio_expr} AS ty_le_pct, "
            f'{ratio_expr} AS "ty_le_%" '
            f"FROM {TABLE}{ratio_where}"
        )

        # target_condition xuất hiện 3 lần trong SELECT.
        return sql, tuple(target_params * 3 + ratio_params)
    if plan.metric == 'ratio' and plan.task == 'group_aggregate':
        group_cols = list(plan.group_by or [])
        denominator_filters, numerator_filters = _ratio_filter_parts(plan, question)
        ratio_where, ratio_params = _compile_filter_list_where(denominator_filters)
        target_condition, target_params = _compile_filter_list_condition(numerator_filters)

        groups_sql = ", ".join(group_cols)
        global_denominator = _ratio_uses_global_denominator(question, plan)
        if global_denominator:
            denominator_expr = f"(SELECT COUNT(DISTINCT id_ho) FROM {TABLE}{ratio_where})"
        else:
            denominator_expr = "COUNT(DISTINCT id_ho)"
        ratio_expr = (
            f"ROUND(COUNT(DISTINCT CASE WHEN {target_condition} THEN id_ho END) "
            f"* 100.0 / NULLIF({denominator_expr}, 0), 1)"
        )

        ratio_direction = 'DESC'
        if plan.order_by is not None:
            ratio_direction = plan.order_by.direction.upper()
        order_sql = f'ty_le_pct {ratio_direction}'
        for col in group_cols:
            order_sql += f", {col} ASC"

        limit_sql = f" LIMIT {int(plan.limit)}" if plan.limit else ""

        sql = (
            f"SELECT {groups_sql}, "
            f"COUNT(DISTINCT CASE WHEN {target_condition} THEN id_ho END) AS so_ho, "
            f"{denominator_expr} AS tong_ho, "
            f"{ratio_expr} AS ty_le_pct, "
            f'{ratio_expr} AS "ty_le_%" '
            f"FROM {TABLE}{ratio_where} "
            f"GROUP BY {groups_sql} "
            f"ORDER BY {order_sql}{limit_sql}"
        )

        if global_denominator:
            params = (
                target_params + ratio_params
                + target_params + ratio_params
                + target_params + ratio_params
                + ratio_params
            )
            return sql, tuple(params)
        return sql, tuple(target_params * 3 + ratio_params)
    if plan.metric == 'count_households':
        expression, alias = ('COUNT(DISTINCT id_ho)', 'so_ho')
    elif plan.metric == 'sum':
        sum_aliases = {
            'so_nhan_khau': 'tong_nhan_khau',
            'so_tre_em': 'tong_tre_em',
            'dien_tich_dat': 'tong_dien_tich_dat',
            'so_tre_thieu_bhyt': 'tong_tre_thieu_bhyt',
            'so_tre_thieu_dinh_duong': 'tong_tre_thieu_dinh_duong',
            'so_tre_thieu_di_hoc': 'tong_tre_thieu_di_hoc',
        }
        expression, alias = (
            f'COALESCE(SUM({plan.target_col}), 0)',
            sum_aliases.get(plan.target_col, f'sum_{plan.target_col}'),
        )
    elif plan.metric == 'avg':
        expression, alias = (f'ROUND(AVG({plan.target_col}), 2)', f'avg_{plan.target_col}')
    else:
        expression, alias = (f'ROUND(AVG(CASE WHEN {plan.target_col} = 1 THEN 1.0 ELSE 0.0 END) * 100, 2)', 'ty_le_%')
    alias_sql = f'"{alias}"' if '%' in alias else alias
    if plan.task in {'group_aggregate', 'compare_years'}:
        compare_groups = list(dict.fromkeys([*plan.group_by, 'nam']))
        groups = ', '.join(compare_groups) if plan.task == 'compare_years' else ', '.join(plan.group_by)
        order_alias_sql = alias_sql

        if plan.task == 'compare_years' and plan.order_by is None:
            order_parts = ['nam ASC']
        else:
            if plan.order_by:
                order_parts = [f'{plan.order_by.col} {plan.order_by.direction.upper()}']
            else:
                order_parts = [f'{order_alias_sql} DESC']

            for col in plan.group_by:
                if col not in {plan.order_by.col if plan.order_by else None}:
                    order_parts.append(f'{col} ASC')

        order_sql = ', '.join(order_parts)

        limit_sql = f' LIMIT {int(plan.limit)}' if plan.limit and plan.task == 'group_aggregate' else ''
        sql = f'SELECT {groups}, {expression} AS {alias_sql} FROM {TABLE}{where} GROUP BY {groups} ORDER BY {order_sql}{limit_sql}'
        return (sql, tuple(params))
    if plan.metric in {'avg', 'sum'}:
        return (
            f'SELECT {expression} AS {alias_sql}, COUNT(DISTINCT id_ho) AS so_ho FROM {TABLE}{where}',
            tuple(params),
        )
    return (f'SELECT {expression} AS {alias_sql} FROM {TABLE}{where}', tuple(params))

def _safe_lookup_name(name: str | None) -> bool:
    key = vn_name_key(name or '')
    raw = str(name or '').strip()

    if re.fullmatch(r'\d{6,}', raw):
        return False

    parts = key.split()
    if len(parts) < 2:
        return False

    # Chỉ chặn placeholder quá rõ, không chặn họ tên có chữ A/B/C cuối.
    if key in {"ho ten", "ten chu ho", "nguyen van", "tran van"}:
        return False

    if len(parts) >= 3 and len(parts[-1]) == 1:
        return False
    return True

def _execute_lookup_person(plan: QueryPlan) -> pd.DataFrame:
    if not _safe_lookup_name(plan.person_name):
        return pd.DataFrame()

    sql, params = compile_plan(plan)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')
        direct_df = pd.read_sql_query(sql, conn, params=params)

    if not direct_df.empty:
        return direct_df
    plan_no_name = QueryPlan(task='list_records', metric=None, target_col=None, filters=list(plan.filters), group_by=[], select=plan.select or [*BASE_RECORD_COLUMNS], order_by=plan.order_by, limit=None, person_name=None)
    sql, params = compile_plan(plan_no_name)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')
        df = pd.read_sql_query(sql, conn, params=params)
    if df.empty or 'chu_ho' not in df.columns:
        return df
    name_key = vn_text_key_keep_accents(plan.person_name)
    mask = df['chu_ho'].apply(lambda x: name_key in vn_text_key_keep_accents(str(x)))
    result = df[mask].reset_index(drop=True)
    return result

def _flag_group_filter_columns() -> set[str]:
    return {col for group in FLAG_GROUPS.values() for col in group['columns'].values()}

def _base_where_from_filters(filters: list[Filter]) -> tuple[str, list[Any]]:
    clauses, params = ([], [])
    flag_group_cols = _flag_group_filter_columns()
    for item in filters:
        if item.col in flag_group_cols:
            continue
        if item.op == 'IN':
            values = list(item.value)
            clauses.append(f"{item.col} IN ({','.join(('?' for _ in values))})")
            params.extend(values)
        else:
            clauses.append(f'{item.col} {item.op} ?')
            params.append(item.value)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else '', params)


def _execute_child_deprivation_group(
    plan: QueryPlan,
    *,
    label_col: str,
    mapping: dict[str, str],
) -> pd.DataFrame | None:
    where, params = _base_where_from_filters(plan.filters)
    rows: list[dict[str, Any]] = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA query_only = ON")

        if plan.task == "compare_years":
            for label, flag_col in mapping.items():
                count_col = _child_deprivation_count_col(flag_col)
                if not count_col:
                    continue
                cursor = conn.execute(
                    f"""
                    SELECT
                        nam,
                        COALESCE(SUM({count_col}), 0) AS so_tre_thieu,
                        COUNT(DISTINCT CASE WHEN {flag_col} = 1 THEN id_ho END) AS so_ho_co_tre_thieu,
                        COALESCE(SUM(so_tre_em), 0) AS tong_tre
                    FROM {TABLE}
                    {where}
                    GROUP BY nam
                    ORDER BY nam ASC
                    """,
                    params,
                )
                for year, so_tre_thieu, so_ho_co_tre_thieu, tong_tre in cursor.fetchall():
                    so_tre = int(so_tre_thieu or 0)
                    total_children = int(tong_tre or 0)
                    ty_le = round(so_tre * 100.0 / total_children, 1) if total_children else 0.0
                    rows.append({
                        label_col: label,
                        "nam": int(year),
                        "so_tre_thieu": so_tre,
                        "so_ho_co_tre_thieu": int(so_ho_co_tre_thieu or 0),
                        "tong_tre": total_children,
                        "ty_le_%": ty_le,
                        "ty_le_pct": ty_le,
                    })
            return pd.DataFrame(
                rows,
                columns=[label_col, "nam", "so_tre_thieu", "so_ho_co_tre_thieu", "tong_tre", "ty_le_%", "ty_le_pct"],
            ).reset_index(drop=True)

        for label, flag_col in mapping.items():
            count_col = _child_deprivation_count_col(flag_col)
            if not count_col:
                continue
            so_tre_thieu, so_ho_co_tre_thieu, tong_tre = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM({count_col}), 0) AS so_tre_thieu,
                    COUNT(DISTINCT CASE WHEN {flag_col} = 1 THEN id_ho END) AS so_ho_co_tre_thieu,
                    COALESCE(SUM(so_tre_em), 0) AS tong_tre
                FROM {TABLE}
                {where}
                """,
                params,
            ).fetchone()
            so_tre = int(so_tre_thieu or 0)
            total_children = int(tong_tre or 0)
            ty_le = round(so_tre * 100.0 / total_children, 1) if total_children else 0.0
            rows.append({
                label_col: label,
                "so_tre_thieu": so_tre,
                "so_ho_co_tre_thieu": int(so_ho_co_tre_thieu or 0),
                "tong_tre": total_children,
                "ty_le_%": ty_le,
                "ty_le_pct": ty_le,
            })

    sort_col = "ty_le_%" if plan.metric == "ratio" else "so_tre_thieu"
    ascending = bool(plan.order_by is not None and plan.order_by.direction.lower() == "asc")
    if plan.order_by and plan.order_by.col in {"so_tre_thieu", "so_ho_co_tre_thieu", "tong_tre", "ty_le_%", "ty_le_pct"}:
        sort_col = "ty_le_%" if plan.order_by.col in {"ty_le_%", "ty_le_pct"} else plan.order_by.col
    df = pd.DataFrame(rows).sort_values(sort_col, ascending=ascending).reset_index(drop=True)
    if plan.limit is not None:
        df = df.head(plan.limit).reset_index(drop=True)
    return df

def _execute_flag_group(plan: QueryPlan) -> pd.DataFrame | None:
    if plan.task not in {'group_aggregate', 'compare_years'} or not plan.group_by:
        return None

    if plan.task == 'compare_years':
        group_names = [col for col in plan.group_by if col != 'nam']
        if len(group_names) != 1:
            return None
        group_name = group_names[0]
    else:
        if len(plan.group_by) != 1:
            return None
        group_name = plan.group_by[0]

    group = FLAG_GROUPS.get(group_name)
    if group is None:
        return None

    label_col = group['label_col']
    mapping = group['columns']

    requested_cols = {
        item.col
        for item in plan.filters
        if item.op == '=' and item.value == 1 and item.col in mapping.values()
    }
    if requested_cols:
        mapping = {
            label: col
            for label, col in mapping.items()
            if col in requested_cols
        }

    if group_name == "tre_em":
        return _execute_child_deprivation_group(plan, label_col=label_col, mapping=mapping)

    where, params = _base_where_from_filters(plan.filters)
    rows = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')

        if plan.task == 'compare_years':
            for label, col in mapping.items():
                cursor = conn.execute(
                    f"""
                    SELECT
                        nam,
                        COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END) AS so_ho
                    FROM {TABLE}
                    {where}
                    GROUP BY nam
                    ORDER BY nam ASC
                    """,
                    params,
                )

                for year, count in cursor.fetchall():
                    rows.append({
                        label_col: label,
                        'nam': int(year),
                        'so_ho': int(count or 0),
                    })

            return pd.DataFrame(
                rows,
                columns=[label_col, 'nam', 'so_ho'],
            ).reset_index(drop=True)

        if plan.metric == 'ratio':
            tong_ho = conn.execute(
                f"""
                SELECT COUNT(DISTINCT id_ho)
                FROM {TABLE}
                {where}
                """,
                params,
            ).fetchone()[0] or 0

            for label, col in mapping.items():
                so_ho = conn.execute(
                    f"""
                    SELECT COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END)
                    FROM {TABLE}
                    {where}
                    """,
                    params,
                ).fetchone()[0] or 0

                ty_le = round((int(so_ho) * 100.0 / int(tong_ho)), 1) if tong_ho else 0.0

                rows.append({
                    label_col: label,
                    'so_ho': int(so_ho),
                    'tong_ho': int(tong_ho),
                    'ty_le_%': ty_le,
                    'ty_le_pct': ty_le,
                })

            ascending = bool(
                plan.order_by is not None
                and plan.order_by.direction.lower() == 'asc'
            )
            df = pd.DataFrame(
                rows,
                columns=[label_col, 'so_ho', 'tong_ho', 'ty_le_%', 'ty_le_pct'],
            ).sort_values('ty_le_%', ascending=ascending).reset_index(drop=True)

            if plan.limit is not None:
                df = df.head(plan.limit).reset_index(drop=True)

            return df

        for label, col in mapping.items():
            count = conn.execute(
                f"""
                SELECT COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END)
                FROM {TABLE}
                {where}
                """,
                params,
            ).fetchone()[0] or 0

            rows.append({
                label_col: label,
                'so_ho': int(count),
            })

    df = pd.DataFrame(rows).sort_values('so_ho', ascending=False).reset_index(drop=True)

    if plan.limit is not None:
        df = df.head(plan.limit).reset_index(drop=True)

    return df

def _multi_metric_scope_class(question: str, filters: list[Filter]) -> str | None:
    q_key = vn_name_key(question or '')
    prefix = re.split('\\bgom\\b', q_key, maxsplit=1)[0]
    if 'ho khong ngheo' in prefix or 'khong ngheo' in prefix:
        return 'Hộ không nghèo'
    if 'ho can ngheo' in prefix or 'ho sat ngheo' in prefix or 'can ngheo' in prefix:
        return 'Hộ cận nghèo'
    if 'ho ngheo' in prefix or 'ho kho khan' in prefix or 'nhom ngheo' in prefix:
        return 'Hộ nghèo'
    return next((item.value for item in filters if item.col == 'phan_loai' and item.op == '='), None)


def _scope_total_alias(scope_class: str | None) -> str:
    key = vn_name_key(str(scope_class or ''))
    if key == 'ho ngheo':
        return 'tong_ho_ngheo'
    if key == 'ho can ngheo':
        return 'tong_ho_can_ngheo'
    if key == 'ho khong ngheo':
        return 'tong_ho_khong_ngheo'
    return 'tong_ho'

def _sql_lit(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"

def _metric_sql_for_col(col: str, scope_fn) -> tuple[str, str] | None:
    meta = FEATURE_CATALOG.get(col)
    if not meta:
        return None

    alias = meta.get('table_alias') or f'so_ho_{col}'
    alias = alias.replace('so_ho_ho_tro_', 'so_ho_htro_')
    value = meta.get('value', 1)
    condition = f'{col} = {int(value)}'
    return (alias, f'COUNT(DISTINCT CASE WHEN {scope_fn(condition)} THEN id_ho END) AS {alias}')

def _expand_overlap_metric_filter_cols(cols: set[str]) -> set[str]:
    expanded = set(cols)
    for col in list(cols):
        meta = FEATURE_CATALOG.get(col, {})
        expanded.update(meta.get('overlap_filter_cols', []))
    return expanded

def _execute_multi_metric_table(plan: QueryPlan, question: str | None=None) -> pd.DataFrame | None:
    if plan.task != 'multi_metric_table':
        return None
    q = (question or '').lower()
    q_key = vn_name_key(question or '')
    group_cols = list(plan.group_by or [])
    metric_cols = _multi_metric_filter_cols(question or '')
    support_context = any(x in q_key for x in ("ho tro", "duoc ho tro", "nhan ho tro"))

    # Nếu câu không nói hỗ trợ, không cho các htro_* lọt vào chỉ vì alias ngắn như "điện", "nước sạch".
    if not support_context:
        metric_cols = {col for col in metric_cols if not col.startswith("htro_")}

    support_metric_cols = set()
    if support_context:
        support_metric_cols = {
            col for col, aliases in SUPPORT_TERM_ALIASES.items()
            if any(re.search(rf"\b{re.escape(vn_name_key(alias))}\b", q_key) for alias in aliases)
        }

    metric_cols = metric_cols | support_metric_cols
    where_metric_filter_cols = _expand_overlap_metric_filter_cols(metric_cols)
    class_filter = next((item for item in plan.filters if item.col == "phan_loai"), None)
    scope_class = None

    if class_filter and class_filter.op == "IN":
        values_sql = ", ".join(_sql_lit(v) for v in class_filter.value)
        scope_condition = f"phan_loai IN ({values_sql})"
    elif class_filter and class_filter.op == "=":
        scope_class = str(class_filter.value)
        scope_condition = f"phan_loai = {_sql_lit(class_filter.value)}"
    elif any(item.col == "bien_dong_dau_ky" for item in plan.filters):
        # Nhãn biến động như "cận nghèo trở thành hộ nghèo" đã tự xác định
        # phạm vi nghiệp vụ; không suy thêm phan_loai từ chữ nghèo/cận nghèo
        # nằm bên trong nhãn, nếu không sẽ đếm lệch hoặc về 0.
        scope_class = None
        scope_condition = '1=1'
    else:
        scope_class = _multi_metric_scope_class(question or '', list(plan.filters))
        scope_condition = f'phan_loai = {_sql_lit(scope_class)}' if scope_class else '1=1'

    def scoped(condition: str) -> str:
        if scope_condition == '1=1':
            return condition
        return f'{scope_condition} AND {condition}'
    base_filters = [item for item in plan.filters if item.col not in where_metric_filter_cols and item.col != 'phan_loai']
    clauses, params = ([], [])
    for item in base_filters:
        if item.op == 'IN':
            values = list(item.value)
            clauses.append(f"{item.col} IN ({','.join(('?' for _ in values))})")
            params.extend(values)
        else:
            clauses.append(f'{item.col} {item.op} ?')
            params.append(item.value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    groups = ', '.join(group_cols)
    wants_total_poor = 'tổng hộ nghèo' in q or re.search('\\btong ho ngheo\\b', q_key)
    wants_total_near_poor = 'tổng hộ cận nghèo' in q or re.search('\\btong ho can ngheo\\b', q_key)
    wants_total_non_poor = 'tổng hộ không nghèo' in q or re.search('\\btong ho khong ngheo\\b', q_key)
    wants_total_all = re.search('\\btong ho\\b(?!\\s+(?:ngheo|can ngheo|khong ngheo))', q_key) is not None or re.search('\\btổng hộ\\b(?!\\s+(?:nghèo|cận nghèo|không nghèo))', q) is not None
    metrics: list[str] = []
    order_col: str | None = None
    
    added_total_metric = False
    if wants_total_all:
        if scope_condition != "1=1":
            metrics.append(f'COUNT(DISTINCT CASE WHEN {scope_condition} THEN id_ho END) AS tong_ho')
        else:
            metrics.append('COUNT(DISTINCT id_ho) AS tong_ho')
        added_total_metric = True
    if wants_total_poor:
        metrics.append("COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' THEN id_ho END) AS tong_ho_ngheo")
        added_total_metric = True
    if wants_total_near_poor:
        metrics.append("COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' THEN id_ho END) AS tong_ho_can_ngheo")
        added_total_metric = True
    if wants_total_non_poor:
        metrics.append("COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ không nghèo' THEN id_ho END) AS tong_ho_khong_ngheo")
        if not added_total_metric:
            order_col = 'tong_ho_khong_ngheo'
        added_total_metric = True
    if not added_total_metric:
        if scope_condition != '1=1':
            total_alias = _scope_total_alias(scope_class)
            metrics.append(f'COUNT(DISTINCT CASE WHEN {scope_condition} THEN id_ho END) AS {total_alias}')
        else:
            metrics.append('COUNT(DISTINCT id_ho) AS tong_ho')

    wants_population_sum = any(x in q_key for x in (
        "tong nhan khau",
        "nhan khau tuong ung",
        "so nhan khau tuong ung",
    ))
    if wants_population_sum:
        if scope_condition == '1=1':
            metrics.append('COALESCE(SUM(so_nhan_khau), 0) AS tong_nhan_khau')
        else:
            metrics.append(f'COALESCE(SUM(CASE WHEN {scope_condition} THEN so_nhan_khau ELSE 0 END), 0) AS tong_nhan_khau')
        if order_col is None:
            order_col = 'tong_ho'
        
    if 'tinh_trang_nha' in metric_cols:
        nha_o_kem_def = DERIVED_METRIC_DEFINITIONS['nha_o_kem']
        values_sql = ', '.join(_sql_lit(v) for v in nha_o_kem_def['values'])
        poor_house_condition = f"{nha_o_kem_def['source_col']} IN ({values_sql})"
        metrics.append(f"COUNT(DISTINCT CASE WHEN {scoped(poor_house_condition)} THEN id_ho END) AS {nha_o_kem_def['alias']}")
    if 'gioi_tinh' in metric_cols or 'nhom_chu_ho_nu' in metric_cols:
        female_condition = scoped("gioi_tinh = 'Nữ'")
        metrics.append(f'COUNT(DISTINCT CASE WHEN {female_condition} THEN id_ho END) AS so_ho_chu_ho_nu')
    numeric_cols = _multi_numeric_metric_cols(question or '')
    for col in sorted(numeric_cols):
        if scope_condition == '1=1':
            metrics.append(f'ROUND(AVG({col}), 2) AS avg_{col}')
        else:
            metrics.append(f'ROUND(AVG(CASE WHEN {scope_condition} THEN {col} END), 2) AS avg_{col}')
    special_metric_cols = {'tinh_trang_nha', 'gioi_tinh', 'nhom_chu_ho_nu'}
    for col in sorted(metric_cols):
        if col in special_metric_cols:
            continue
        item = _metric_sql_for_col(col, scoped)
        if item is None:
            continue
        alias, sql_expr = item
        metrics.append(sql_expr)
    if len(metrics) <= 1:
        return None
    if group_cols:
        groups = ', '.join(group_cols)
        sort_desc_signal = any(x in q_key for x in (
            "giam dan", "nhieu nhat", "cao nhat", "lon nhat", "sap xep theo so ho"
        ))
        if sort_desc_signal:
            if order_col is None:
                order_col = 'tong_ho'
            order_sql = f"{order_col} DESC, " + ', '.join(f"{col} ASC" for col in group_cols)
        else:
            order_sql = ', '.join(f"{col} ASC" for col in group_cols)
        sql = f"""
            SELECT {groups}, {', '.join(metrics)}
            FROM {TABLE}
            {where}
            GROUP BY {groups}
            ORDER BY {order_sql}
        """
    else:
        sql = f"""
            SELECT {', '.join(metrics)}
            FROM {TABLE}
            {where}
        """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')
        return _sanitize_public_result(pd.read_sql_query(sql, conn, params=params))

def _sanitize_public_result(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=['id_ho'], errors='ignore')

def _advanced_dtts_threshold_income(question: str | None) -> pd.DataFrame | None:
    q_key = vn_name_key(question or "")
    if not (
        "dan toc thieu so tai cho" in q_key
        or "dtts tai cho" in q_key
        or "dan toc tai cho" in q_key
    ):
        return None
    if not (
        "thu nhap binh quan" in q_key
        and "ho ngheo" in q_key
        and re.search(r'\btren\s+(\d+(?:\.\d+)?)\s*%?', q_key)
    ):
        return None

    year_match = re.search(r'\b20\d{2}\b', q_key)
    if not year_match:
        return None

    threshold = float(re.search(r'\btren\s+(\d+(?:\.\d+)?)\s*%?', q_key).group(1))
    year = int(year_match.group(0))
    ascending = "thap nhat" in q_key or "thap" in q_key

    sql = f"""
        WITH dtts AS (
            SELECT
                huyen,
                COUNT(DISTINCT CASE WHEN dan_toc_tai_cho = 'Có' THEN id_ho END) AS so_ho_dtts_tai_cho,
                COUNT(DISTINCT id_ho) AS tong_ho,
                ROUND(COUNT(DISTINCT CASE WHEN dan_toc_tai_cho = 'Có' THEN id_ho END) * 100.0
                    / NULLIF(COUNT(DISTINCT id_ho), 0), 1) AS ty_le_dtts_tai_cho
            FROM {TABLE}
            WHERE nam = ?
            GROUP BY huyen
        ),
        income AS (
            SELECT huyen, ROUND(AVG(thu_nhap_bq), 2) AS avg_thu_nhap_bq
            FROM {TABLE}
            WHERE nam = ? AND phan_loai = 'Hộ nghèo'
            GROUP BY huyen
        )
        SELECT
            dtts.huyen,
            dtts.ty_le_dtts_tai_cho,
            dtts.so_ho_dtts_tai_cho,
            dtts.tong_ho,
            income.avg_thu_nhap_bq
        FROM dtts
        LEFT JOIN income ON income.huyen = dtts.huyen
        WHERE dtts.ty_le_dtts_tai_cho > ?
        ORDER BY income.avg_thu_nhap_bq {'ASC' if ascending else 'DESC'}, dtts.huyen ASC
    """

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')
        df = pd.read_sql_query(sql, conn, params=(year, year, threshold))

        if not df.empty:
            return df.head(1).reset_index(drop=True)

        fallback_sql = f"""
            SELECT
                huyen,
                COUNT(DISTINCT CASE WHEN dan_toc_tai_cho = 'Có' THEN id_ho END) AS so_ho_dtts_tai_cho,
                COUNT(DISTINCT id_ho) AS tong_ho,
                ROUND(COUNT(DISTINCT CASE WHEN dan_toc_tai_cho = 'Có' THEN id_ho END) * 100.0
                    / NULLIF(COUNT(DISTINCT id_ho), 0), 1) AS ty_le_dtts_tai_cho
            FROM {TABLE}
            WHERE nam = ?
            GROUP BY huyen
            ORDER BY ty_le_dtts_tai_cho DESC, huyen ASC
            LIMIT 1
        """
        fallback = pd.read_sql_query(fallback_sql, conn, params=(year,))

    if fallback.empty:
        return pd.DataFrame([{
            "ly_do": f"Không có dữ liệu huyện nào để tính tỷ lệ DTTS tại chỗ năm {year}.",
            "nguong_ty_le": threshold,
        }])

    fallback["dat_nguong"] = False
    fallback["nguong_ty_le"] = threshold
    fallback["ly_do"] = (
        f"Không có huyện nào đạt > {threshold:g}% hộ DTTS tại chỗ năm {year}; "
        "huyện có tỷ lệ cao nhất được hiển thị để đối chiếu."
    )
    return fallback.reset_index(drop=True)

def _is_single_best_ranking(plan: QueryPlan) -> bool:
    return (
        plan.limit == 1
        and plan.order_by is not None
        and plan.task in {"group_aggregate", "list_records", "lookup_person"}
    )


def _expand_ties_for_single_best(plan: QueryPlan, question: str | None = None) -> pd.DataFrame | None:
    if not _is_single_best_ranking(plan):
        return None

    # chạy lại plan nhưng bỏ limit để không mất đồng hạng
    full_plan = QueryPlan(
        task=plan.task,
        metric=plan.metric,
        target_col=plan.target_col,
        filters=list(plan.filters),
        or_filters=list(plan.or_filters),
        group_by=list(plan.group_by),
        select=list(plan.select),
        order_by=plan.order_by,
        limit=None,
        person_name=plan.person_name,
        denominator_scope=getattr(plan, 'denominator_scope', None),
        numerator_filters=list(getattr(plan, 'numerator_filters', []) or []),
        denominator_filters=list(getattr(plan, 'denominator_filters', []) or []),
    )

    sql, params = compile_plan(full_plan)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA query_only = ON")
        df = pd.read_sql_query(sql, conn, params=params)

    if df.empty:
        return df

    order_col = plan.order_by.col
    if order_col not in df.columns:
        return df.head(1).reset_index(drop=True)

    best_value = df[order_col].min() if plan.order_by.direction == "asc" else df[order_col].max()
    return df[df[order_col] == best_value].reset_index(drop=True)

def _slice_explicit_rank_position(plan: QueryPlan, df: pd.DataFrame, question: str | None = None) -> pd.DataFrame:
    if df.empty or plan.task != "group_aggregate" or plan.order_by is None:
        return df

    q_key = vn_name_key(question or "")

    explicit_rank_signal = (
        re.search(r"\b(?:hang|xep hang|thu)\s*\d+\b", q_key) is not None
        or any(x in q_key for x in (
            "thu nhi", "thu hai", "thu ba", "thu tu", "thu nam",
            "thu sau", "thu bay", "thu tam", "thu chin", "thu muoi",
        ))
    )

    if not explicit_rank_signal:
        return df

    pos = _ranking_position(question or "")
    if pos is None or pos <= 1:
        return df

    idx = min(pos - 1, len(df) - 1)
    return df.iloc[[idx]].reset_index(drop=True)

def execute_query_plan(plan: QueryPlan, question: str | None = None) -> pd.DataFrame:
    advanced_df = _advanced_dtts_threshold_income(question)
    if advanced_df is not None:
        return _sanitize_public_result(advanced_df)

    multi_metric_df = _execute_multi_metric_table(plan, question)
    if multi_metric_df is not None:
        return _sanitize_public_result(multi_metric_df)

    flag_group_df = _execute_flag_group(plan)
    if flag_group_df is not None:
        return _sanitize_public_result(flag_group_df)

    if plan.task == 'lookup_person' and plan.person_name:
        tied = _expand_ties_for_single_best(plan, question)
        if tied is not None:
            return _sanitize_public_result(tied)
        return _sanitize_public_result(_execute_lookup_person(plan))

    q_key = vn_name_key(question or "")
    split_signal = ("lần lượt" in (question or "").lower()) or ("tương ứng" in (question or "").lower()) or ("lan luot" in q_key) or ("tuong ung" in q_key)
    multi_count_aliases = {col: (meta.get("table_alias") or f"so_ho_{col}") for col, meta in FEATURE_CATALOG.items() if meta.get("kind") == "flag"}
    requested_multi_counts = [item.col for item in plan.filters if item.op == "=" and item.value == 1 and item.col in multi_count_aliases]

    if split_signal and plan.task == "aggregate" and plan.metric == "count_households" and len(requested_multi_counts) >= 2:
        requested_set = set(requested_multi_counts)
        base_filters = [item for item in plan.filters if item.col not in requested_set]
        clauses, params = [], []
        for item in base_filters:
            if item.op == "IN":
                values = list(item.value); clauses.append(f"{item.col} IN ({','.join('?' for _ in values)})"); params.extend(values)
            else:
                clauses.append(f"{item.col} {item.op} ?"); params.append(item.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        select_exprs = [f"COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END) AS {multi_count_aliases[col]}" for col in requested_multi_counts]
        sql = f"SELECT {', '.join(select_exprs)} FROM {TABLE}{where}"
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA query_only = ON")
            return _sanitize_public_result(pd.read_sql_query(sql, conn, params=params))

    tied = _expand_ties_for_single_best(plan, question)
    if tied is not None:
        return _sanitize_public_result(tied)

    sql, params = compile_plan(plan, question)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA query_only = ON')
        df = pd.read_sql_query(sql, conn, params=params)
        df = _slice_explicit_rank_position(plan, df, question)

        if plan.task == 'list_records' and not df.empty:
            count_plan = QueryPlan(
                task='aggregate',
                metric='count_households',
                target_col=None,
                filters=list(plan.filters),
                or_filters=list(plan.or_filters),
                group_by=[],
                select=[],
                order_by=None,
                limit=None,
                person_name=None,
            )
            count_sql, count_params = compile_plan(count_plan)
            total_count = conn.execute(count_sql, count_params).fetchone()[0] or 0
            df['__total_count'] = int(total_count)

        return _sanitize_public_result(df)

def enrich_group_ratio_result(plan: QueryPlan, result: pd.DataFrame, question: str) -> pd.DataFrame:
    q = question.lower()
    if plan.task == 'compare_years' and 'nam' in result.columns and ('so_ho' in result.columns):
        index_cols = [col for col in plan.group_by if col != 'nam' and col in result.columns]
        if index_cols:
            pivot = result.pivot_table(index=index_cols, columns='nam', values='so_ho', fill_value=0).reset_index()
        else:
            pivot = result.set_index('nam')[['so_ho']].T.reset_index(drop=True)
        pivot.columns.name = None
        pivot = pivot.rename(columns={year: f'so_ho_{int(year)}' for year in pivot.columns if isinstance(year, (int, float))})
        if {'so_ho_2023', 'so_ho_2024'} <= set(pivot.columns):
            pivot['chenh_lech'] = pivot['so_ho_2024'] - pivot['so_ho_2023']
            pivot['bien_dong'] = pivot['chenh_lech']

            q_key = vn_name_key(question or "")

            if index_cols:
                if "tăng" in q or "tang" in q_key:
                    pivot = pivot.sort_values("chenh_lech", ascending=False)
                elif (
                    "giảm" in q
                    or "giam" in q_key
                    or "biến động" in q
                    or "bien dong" in q_key
                    or "chênh lệch" in q
                    or "chenh lech" in q_key
                ):
                    pivot = pivot.sort_values("chenh_lech", ascending=True)
            if plan.limit == 1 and any(x in q_key for x in (
                "huyen nao", "xa nao", "dia ban nao",
                "giam manh nhat", "giam nhieu nhat",
                "tang manh nhat", "tang nhieu nhat",
            )):
                pivot = pivot.head(1)
        return pivot.reset_index(drop=True)
    if plan.task != 'group_aggregate' or not any((term in q for term in ('tỷ lệ', 'phần trăm', 'chiếm bao nhiêu', '%'))):
        return result
    filter_cols = {item.col for item in plan.filters}
    focus_col = 'gioi_tinh' if 'gioi_tinh' in filter_cols else 'dan_toc_chi_tiet' if 'dan_toc_chi_tiet' in filter_cols else None
    if not focus_col or 'phan_loai' not in filter_cols:
        return result
    drop_cols = {focus_col}
    if focus_col == 'gioi_tinh':
        drop_cols.add('nhom_chu_ho_nu')
    denominator_plan = QueryPlan(task='group_aggregate', metric='count_households', target_col=None, filters=[item for item in plan.filters if item.col not in drop_cols], group_by=list(plan.group_by), select=[], order_by=None, limit=plan.limit)
    denominator = execute_query_plan(denominator_plan).rename(columns={'so_ho': 'tong_ho'})
    enriched = result.merge(denominator, on=plan.group_by, how='left')
    enriched['ty_le_%'] = (
        enriched['so_ho'] / enriched['tong_ho'].replace(0, pd.NA) * 100
    ).fillna(0).round(1)
    enriched['ty_le_pct'] = enriched['ty_le_%']
    return enriched.sort_values('ty_le_%', ascending=False).reset_index(drop=True)
