from __future__ import annotations
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict
from functools import lru_cache
from typing import Any
import pandas as pd
import requests
from .config import DB_PATH, MODEL_NAME, OLLAMA_URL, LLM_TIMEOUT
from core.schema import TABLE, TASKS, METRICS, OPERATORS, MAX_LIMIT, Filter, OrderBy, QueryPlan
from core.catalog import FLAG_GROUPS, FLAG_GROUP_COLUMNS, GROUP_COLUMNS, NUMERIC_COLUMNS, OUTPUT_COLUMNS, FLAG_COLUMNS, FILTER_COLUMNS, ALL_COLUMNS, ORDER_COLUMNS, TASK_ALIASES, METRIC_ALIASES, COLUMN_ALIASES, NUMERIC_FIELD_CATALOG, FEATURE_CATALOG, FEATURE_KEYWORDS, FEATURE_RULES, BASE_RECORD_COLUMNS, DETAIL_COLUMN_GROUPS, FILTER_DETAIL_COLUMNS, EQUIVALENT_FILTER_RULES, CATALOG_VALUE_ALIASES, SAME_COLUMN_CATALOG_CONTEXTS, FILTER_ANSWER_LABELS, TEXT_FILTER_LABELS, ANSWER_REQUIRED_COLUMN_RULES, SUPPORT_TERM_ALIASES, CLASSIFICATION_ALIASES, MULTI_METRIC_TERM_ALIASES, GROUP_BY_TERM_ALIASES, DERIVED_METRIC_DEFINITIONS, SPECIFIC_FILTER_OVERRIDES, DISTINCT_VALUE_TERMS


def _canonical_column(col: Any) -> Any:
    key = col.strip().lower() if isinstance(col, str) else col
    return COLUMN_ALIASES.get(key, key)

def _safe_canonical_columns(values: Any, allowed: set[str], schema: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    columns = []
    for item in values:
        if not isinstance(item, str):
            continue
        if any((token in item.lower() for token in (' as ', 'count(', 'sum(', 'avg(', 'case ', '*'))):
            continue
        col = _canonical_column(item)
        if isinstance(col, str) and col in allowed and (col in schema or col in FLAG_GROUP_COLUMNS) and (col not in columns):
            columns.append(col)
    return columns

def _safe_order_by(raw_order: Any, schema: set[str]) -> dict[str, str] | None:
    if not isinstance(raw_order, dict):
        return None
    raw_col = raw_order.get('col') or raw_order.get('column')
    if not isinstance(raw_col, str):
        return None
    col = _canonical_column(raw_col)
    direction = raw_order.get('direction') or raw_order.get('dir') or raw_order.get('order') or 'asc'
    direction = str(direction).lower()
    if raw_order.get('desc') is True:
        direction = 'desc'
    if direction in {'>', 'descending'}:
        direction = 'desc'
    if direction in {'<', 'ascending'}:
        direction = 'asc'
    aggregate_aliases = {'so_ho', 'ty_le_%'} | {f'avg_{col}' for col in NUMERIC_COLUMNS} | {f'sum_{col}' for col in NUMERIC_COLUMNS}
    if col in aggregate_aliases or (col in ORDER_COLUMNS and col in schema):
        if direction in {'asc', 'desc'}:
            return {'col': col, 'direction': direction}
    return None

def _feature_alias_keys(col: str) -> list[str]:
    item = FEATURE_CATALOG.get(col, {})
    aliases = item.get('aliases', [])
    label = item.get('label')
    keys = []
    if label:
        keys.append(vn_name_key(label))
    keys.extend((vn_name_key(alias) for alias in aliases))
    return list(dict.fromkeys((k for k in keys if k)))

def _mentioned_feature_cols(question: str) -> set[str]:
    q_key = vn_name_key(question)
    found = set()
    for col, meta in FEATURE_CATALOG.items():
        for alias in _feature_alias_keys(col):
            if re.search(f'\\b{re.escape(alias)}\\b', q_key):
                found.add(col)
                break
    return found

def _append_unique(columns: list[str], additions: list[str]) -> list[str]:
    return columns + [col for col in additions if col not in columns]

def _detail_columns_for_question(question: str) -> list[str]:
    q = question.lower()
    columns = []
    for keywords, group_columns in DETAIL_COLUMN_GROUPS.values():
        if any((keyword in q for keyword in keywords)):
            columns = _append_unique(columns, group_columns)
    return columns

def vn_name_key(text: str) -> str:
    text = unicodedata.normalize('NFD', text or '')
    text = ''.join((ch for ch in text if not unicodedata.combining(ch)))
    text = text.lower().replace('đ', 'd')
    text = re.sub('[^a-z0-9\\s]', ' ', text)
    return re.sub('\\s+', ' ', text).strip()

def vn_text_key_keep_accents(text: str) -> str:
    text = unicodedata.normalize('NFC', text or '')
    text = text.casefold()
    return re.sub('\\s+', ' ', text).strip()

DISTINCT_TEXT_GROUP_ALIASES = {
    "dan_toc_tai_cho": ("dan toc tai cho", "dtts tai cho"),
    "trinh_do_hoc_van_chu_ho": ("trinh do hoc van chu ho", "trinh do hoc van", "hoc van chu ho", "hoc van"),
    "nghe_nghiep_chu_ho": ("nghe nghiep chu ho", "nghe nghiep", "nghe chinh"),
    "suc_khoe_chu_ho": ("suc khoe chu ho", "tinh trang suc khoe", "suc khoe"),
    "tinh_trang_nha": ("tinh trang nha", "tinh trang nha o", "loai nha"),
    "muc_do_thieu_hut": ("muc do thieu hut", "muc thieu hut"),
    "dan_toc_chi_tiet": ("dan toc chi tiet", "cac dan toc", "dan toc", "toc nguoi"),
    "nguon_nuoc": ("cac nguon nuoc", "nguon nuoc", "nuoc sinh hoat"),
    "xa_phuong": ("xa phuong", "cac xa", "cac phuong", "xa", "phuong"),
    "huyen": ("cac huyen", "huyen"),
    "phan_loai": ("phan loai ho", "phan loai"),
    "gioi_tinh": ("gioi tinh",),
}


def _is_distinct_value_question(question: str, group_col: str | None = None) -> bool:
    q_key = vn_name_key(question or '')
    has_list_signal = any(x in q_key for x in ('liet ke', 'danh sach', 'cho biet', 'co nhung'))
    has_distinct_signal = any(vn_name_key(term) in q_key for term in DISTINCT_VALUE_TERMS)
    if not (has_list_signal and has_distinct_signal):
        return False
    if group_col == 'dan_toc_chi_tiet':
        return 'dan toc' in q_key or 'toc nguoi' in q_key
    return True


def _distinct_group_col_from_question(question: str) -> str | None:
    if not _is_distinct_value_question(question):
        return None

    q_key = vn_name_key(question or "")
    matches: list[tuple[int, str]] = []
    for col, aliases in DISTINCT_TEXT_GROUP_ALIASES.items():
        for alias in aliases:
            alias_key = vn_name_key(alias)
            if alias_key and re.search(rf"\b{re.escape(alias_key)}\b", q_key):
                matches.append((len(alias_key), col))
                break

    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]

@lru_cache(maxsize=1)
def _schema_columns() -> set[str]:
    with sqlite3.connect(DB_PATH) as conn:
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{TABLE}")')}

def _coerce_filter(item: Filter | dict) -> Filter:
    if isinstance(item, Filter):
        op = str(item.op).upper()
        value = item.value
        if op == "=" and isinstance(value, (list, tuple)):
            op = "IN"
        return Filter(_canonical_column(item.col), op, value)

    col = item.get('col', item.get('column'))
    op = item.get('op', item.get('operator', item.get('filter_op', '=')))
    value = item.get('value', item.get('val', item.get('filter_val', item.get('filter_value'))))

    col = _canonical_column(col)

    if col == 'phan_loai' and str(value).lower() in {'yes', 'true', '1', 'poor', 'ngheo', 'nghèo'}:
        value = 'Hộ nghèo'

    op = str(op).upper()

    if op == "=" and isinstance(value, (list, tuple)):
        op = "IN"

    return Filter(col=col, op=op, value=value)

def repair_plan(raw: QueryPlan | dict) -> QueryPlan:
    if isinstance(raw, QueryPlan):
        data = raw.to_dict()
    else:
        data = dict(raw)
    task = TASK_ALIASES.get(data.get('task'), data.get('task'))
    metric = METRIC_ALIASES.get(data.get('metric'), data.get('metric'))
    target_col = data.get('target_col', data.get('measure'))
    if isinstance(target_col, (list, dict)):
        target_col = None
    target_col = _canonical_column(target_col)
    if metric == 'count_households':
        target_col = None
    filters = [_coerce_filter(item) for item in data.get('filters') or [] if isinstance(item, Filter) or (isinstance(item, dict) and (item.get('value') is not None or item.get('val') is not None or item.get('filter_val') is not None))]
    or_filters = [_coerce_filter(item) for item in data.get('or_filters') or [] if isinstance(item, Filter) or (isinstance(item, dict) and (item.get('value') is not None or item.get('val') is not None or item.get('filter_val') is not None))]
    numerator_filters = [_coerce_filter(item) for item in data.get('numerator_filters') or [] if isinstance(item, Filter) or (isinstance(item, dict) and (item.get('value') is not None or item.get('val') is not None or item.get('filter_val') is not None))]
    denominator_filters = [_coerce_filter(item) for item in data.get('denominator_filters') or [] if isinstance(item, Filter) or (isinstance(item, dict) and (item.get('value') is not None or item.get('val') is not None or item.get('filter_val') is not None))]
    denominator_scope = data.get('denominator_scope') if data.get('denominator_scope') in {'per_group', 'global'} else None
    raw_order = data.get('order_by')
    if isinstance(raw_order, list):
        raw_order = raw_order[0] if raw_order and isinstance(raw_order[0], dict) else None
    if raw_order in (None, []):
        raw_order = None
    elif isinstance(raw_order, dict):
        order_col = raw_order.get('col') or raw_order.get('column')
        direction = raw_order.get('direction') or raw_order.get('dir') or raw_order.get('order') or 'asc'
        direction = str(direction).lower()
        if raw_order.get('desc') is True:
            direction = 'desc'
        if direction in {'>', 'descending'}:
            direction = 'desc'
        if direction in {'<', 'ascending'}:
            direction = 'asc'
        raw_order = OrderBy(_canonical_column(order_col), direction)
    elif isinstance(raw_order, OrderBy):
        pass
    else:
        raw_order = None
    raw_limit = data.get('limit')
    limit = None
    if isinstance(raw_limit, (int, float)) and (not isinstance(raw_limit, bool)):
        limit = max(1, min(int(raw_limit), MAX_LIMIT))
    plan = QueryPlan(
        task=task,
        metric=metric,
        target_col=target_col,
        filters=filters,
        or_filters=or_filters,
        group_by=[_canonical_column(col) for col in data.get('group_by') or [] if isinstance(col, str)],
        select=[_canonical_column(col) for col in data.get('select') or [] if isinstance(col, str)],
        order_by=raw_order,
        limit=limit,
        person_name=data.get('person_name'),
        denominator_scope=denominator_scope,
        numerator_filters=numerator_filters,
        denominator_filters=denominator_filters,
    )

    # Nếu có group_by mà task vẫn là aggregate thì đây là plan sai hình dạng.
    # Chuyển về group_aggregate để SQL không bỏ group_by.
    if plan.task == 'aggregate' and plan.group_by:
        plan.task = 'group_aggregate'

    return validate_plan(plan)

def _reject_conflicting_filters(filters: list[Filter]) -> None:
    by_col: dict[str, list[Filter]] = {}
    for item in filters:
        by_col.setdefault(item.col, []).append(item)
    for col, items in by_col.items():
        equals = {str(item.value) for item in items if item.op == '='}
        not_equals = {str(item.value) for item in items if item.op == '!='}
        if len(equals) > 1 or equals & not_equals:
            raise ValueError(f'filter mâu thuẫn tại cột {col}')
        in_sets = [set(map(str, item.value)) for item in items if item.op == 'IN']
        if in_sets and (not set.intersection(*in_sets)):
            raise ValueError(f'filter IN mâu thuẫn tại cột {col}')
        if equals and in_sets and (not all((equals <= values for values in in_sets))):
            raise ValueError(f'filter =/IN mâu thuẫn tại cột {col}')
        if in_sets and (not set.intersection(*in_sets) - not_equals):
            raise ValueError(f'filter IN/!= mâu thuẫn tại cột {col}')
        lower_items = [(float(item.value), item.op == '>') for item in items if item.op in {'>', '>='}]
        upper_items = [(float(item.value), item.op == '<') for item in items if item.op in {'<', '<='}]
        if lower_items and upper_items:
            lower_value = max((value for value, _ in lower_items))
            upper_value = min((value for value, _ in upper_items))
            lower_strict = any((strict for value, strict in lower_items if value == lower_value))
            upper_strict = any((strict for value, strict in upper_items if value == upper_value))
            if lower_value > upper_value or (lower_value == upper_value and (lower_strict or upper_strict)):
                raise ValueError(f'filter khoảng mâu thuẫn tại cột {col}')
        if equals and (lower_items or upper_items):
            try:
                equal_value = float(next(iter(equals)))
            except ValueError:
                raise ValueError(f'filter so sánh số không hợp lệ tại cột {col}')
            if any((equal_value < value or (equal_value == value and strict) for value, strict in lower_items)):
                raise ValueError(f'filter =/> mâu thuẫn tại cột {col}')
            if any((equal_value > value or (equal_value == value and strict) for value, strict in upper_items)):
                raise ValueError(f'filter =/< mâu thuẫn tại cột {col}')

def validate_plan(plan: QueryPlan) -> QueryPlan:
    if plan.task not in TASKS:
        raise ValueError(f'task không hợp lệ: {plan.task}')
    if plan.metric is not None and plan.metric not in METRICS:
        raise ValueError(f'metric không hợp lệ: {plan.metric}')
    schema = _schema_columns()
    ratio_control_filters = (
        list(getattr(plan, 'numerator_filters', []) or [])
        + list(getattr(plan, 'denominator_filters', []) or [])
    )
    for item in list(plan.filters) + list(plan.or_filters) + ratio_control_filters:
        if item.col not in FILTER_COLUMNS or item.col not in schema:
            raise ValueError(f'filter col không hợp lệ: {item.col}')
        if item.op not in OPERATORS:
            raise ValueError(f'operator không hợp lệ: {item.op}')
        if item.op == 'IN' and (not isinstance(item.value, (list, tuple)) or not item.value):
            raise ValueError('IN yêu cầu list/tuple không rỗng')
    if getattr(plan, 'denominator_scope', None) not in {None, 'per_group', 'global'}:
        raise ValueError('denominator_scope chỉ nhận None/per_group/global')
    _reject_conflicting_filters(plan.filters)
    for col in plan.group_by:
        if col not in GROUP_COLUMNS or (col not in schema and col not in FLAG_GROUP_COLUMNS):
            raise ValueError(f'group_by không hợp lệ: {col}')
    for col in plan.select:
        if col not in OUTPUT_COLUMNS or col not in schema:
            raise ValueError(f'select không hợp lệ: {col}')
    if plan.order_by:
        aggregate_aliases = (
            {'so_ho', 'ty_le_%', 'ty_le_pct', 'so_tre_thieu', 'so_ho_co_tre_thieu', 'tong_tre'}
            | {f'avg_{col}' for col in NUMERIC_COLUMNS}
            | {f'sum_{col}' for col in NUMERIC_COLUMNS}
            | {
                'tong_nhan_khau',
                'tong_tre_em',
                'tong_dien_tich_dat',
                'tong_tre_thieu_bhyt',
                'tong_tre_thieu_dinh_duong',
                'tong_tre_thieu_di_hoc',
            }
        )
        if plan.order_by.col not in aggregate_aliases and (plan.order_by.col not in ORDER_COLUMNS or plan.order_by.col not in schema):
            raise ValueError(f'order_by col không hợp lệ: {plan.order_by.col}')
        if plan.order_by.direction not in {'asc', 'desc'}:
            raise ValueError('order_by direction chỉ nhận asc/desc')
    if plan.target_col and (plan.target_col not in ALL_COLUMNS or plan.target_col not in schema):
        raise ValueError(f'target_col không hợp lệ: {plan.target_col}')
    if plan.metric == 'count_households' and plan.target_col is not None:
        raise ValueError('count_households bắt buộc target_col=null')
    if plan.metric in {'sum', 'avg'} and plan.target_col not in NUMERIC_COLUMNS:
        raise ValueError('sum/avg yêu cầu target_col là cột số')
    if plan.metric == 'ratio' and plan.task not in {'aggregate', 'group_aggregate', 'summary'}:
        raise ValueError('ratio không phù hợp với task')
    TEXT_RATIO_COLUMNS = {
        "bien_dong_dau_ky",
        "tinh_trang_nha",
        "nguon_nuoc",
        "suc_khoe_chu_ho",
        "trinh_do_hoc_van_chu_ho",
        "dan_toc_chi_tiet",
        "gioi_tinh",
        "phan_loai",
    }

    ratio_flag_group_without_target = (
        plan.metric == "ratio"
        and plan.task == "group_aggregate"
        and plan.target_col is None
        and len(plan.group_by or []) == 1
        and plan.group_by[0] in FLAG_GROUP_COLUMNS
    )

    if (
        plan.metric == 'ratio'
        and not ratio_flag_group_without_target
        and plan.target_col not in FLAG_COLUMNS
        and plan.target_col not in TEXT_RATIO_COLUMNS
    ):
        raise ValueError('ratio yêu cầu target_col là cột cờ nhị phân hoặc text-column có filter rõ ràng')
    if plan.task in {'aggregate', 'group_aggregate'} and plan.metric is None:
        raise ValueError('aggregate yêu cầu metric')
    if plan.task == 'group_aggregate' and (not plan.group_by):
        raise ValueError('group_aggregate yêu cầu group_by')
    if plan.task == 'multi_metric_table' and plan.group_by is None:
        raise ValueError('multi_metric_table yêu cầu group_by dạng list')
    if plan.task == 'compare_years' and plan.metric != 'count_households':
        raise ValueError('compare_years hiện chỉ hỗ trợ count_households')
    if plan.task == 'lookup_person' and (not plan.person_name):
        raise ValueError('lookup_person yêu cầu person_name')
    return plan

def _feature_rules_filters(question: str) -> list[Filter]:
    q = question.lower()
    q_key = vn_name_key(question)

    def hit(text: str) -> bool:
        return text in q or vn_name_key(text) in q_key

    found = []
    for rule in FEATURE_RULES:
        col = rule['col']
        blocked_by = rule.get('blocked_by', ())
        if any(hit(text) for text in blocked_by):
            continue

        value = None
        if any(hit(text) for text in rule.get('negative', ())):
            value = 0
        elif any(hit(text) for text in rule.get('positive', ())):
            value = rule.get('value', 1)

        if value is not None:
            found.append(Filter(col, '=', value))

    return found

def _support_filters(question: str) -> list[Filter]:
    q = question.lower()
    q_key = vn_name_key(question)
    has_support_context = 'hỗ trợ' in q or 'ho tro' in q_key
    if not has_support_context:
        return []
    support_tail = ''
    support_tail_key = ''
    m = re.search('(?:hỗ trợ|được\\s+hỗ trợ|nhận\\s+hỗ trợ)\\s+(.{0,120})', q)
    if m:
        support_tail = m.group(1)
    m_key = re.search('(?:ho tro|duoc\\s+ho tro|nhan\\s+ho tro)\\s+(.{0,120})', q_key)
    if m_key:
        support_tail_key = m_key.group(1)
    found = []
    for col, terms in SUPPORT_TERM_ALIASES.items():
        matched = False
        if col == 'htro_nha_o' and any((x in support_tail_key for x in ('nha o kem', 'nha tam', 'nha don so', 'khong vung chac'))):
            continue
        for term in terms:
            patterns = [f'hỗ trợ\\s+(?:về\\s+)?{re.escape(term)}', f'được\\s+hỗ trợ\\s+(?:về\\s+)?{re.escape(term)}', f'nhận\\s+hỗ trợ\\s+(?:về\\s+)?{re.escape(term)}']
            key_patterns = [f'ho tro\\s+(?:ve\\s+)?{re.escape(term)}', f'duoc\\s+ho tro\\s+(?:ve\\s+)?{re.escape(term)}', f'nhan\\s+ho tro\\s+(?:ve\\s+)?{re.escape(term)}']
            if any((re.search(p, q) for p in patterns)) or any((re.search(p, q_key) for p in key_patterns)) or term in support_tail or (term in support_tail_key):
                matched = True
                break
        if matched:
            found.append(Filter(col, '=', 1))
    return found

def _flag_group_label_filters(question: str, existing_cols: set[str] | None=None) -> list[Filter]:
    existing_cols = existing_cols or set()
    q_key = vn_name_key(question)
    found = []
    for group_name, group in FLAG_GROUPS.items():
        for label, col in group['columns'].items():
            if col in existing_cols:
                continue
            label_key = vn_name_key(label)
            alias_keys = [label_key]
            alias_keys.extend(_feature_alias_keys(col))
            alias_keys = list(dict.fromkeys(alias_keys))
            matched = False
            if group_name == 'nguyen_nhan':
                matched = any((re.search(f'\\b{re.escape(alias)}\\b', q_key) for alias in alias_keys))
            elif group_name == 'chi_so':
                allow_bare_alias_cols = {'th_bhyt', 'th_bhxh', 'th_tai_san_tt'}
                matched = any((re.search(f'\\b(?:thieu|thieu hut|khong co|chua co)\\s+{re.escape(alias)}\\b', q_key) or re.search(f'\\b{re.escape(alias)}\\s+(?:thieu|thieu hut)\\b', q_key) or (col in allow_bare_alias_cols and re.search(f'\\b{re.escape(alias)}\\b', q_key)) for alias in alias_keys))
                if col == 'th_bhyt' and any((x in q_key for x in ('thieu bhyt', 'khong co bhyt', 'thieu bao hiem y te'))):
                    matched = True
                if col == 'th_bhxh' and any((x in q_key for x in ('thieu bhxh', 'khong co bhxh', 'thieu bao hiem xa hoi'))):
                    matched = True
            elif group_name == 'ho_tro':
                matched = any((re.search(f'\\b{re.escape(alias)}\\b', q_key) or re.search(f'\\b(?:duoc|nhan)\\s+{re.escape(alias)}\\b', q_key) for alias in alias_keys))
            if matched:
                found.append(Filter(col, '=', 1))
                existing_cols.add(col)
    return found

def _feature_filters(question: str) -> list[Filter]:
    q = question.lower()
    q_key = vn_name_key(question)
    child_specific = []

    if re.search(r'\btre(?: em)?\b.{0,40}\b(?:thieu|khong co)\b.{0,20}\b(?:bhyt|bao hiem y te)\b', q_key):
        child_specific.append(Filter('te_th_bhyt', '=', 1))

    if re.search(r'\btre(?: em)?\b.{0,40}\bthieu\b.{0,20}\bdinh duong\b', q_key):
        child_specific.append(Filter('te_th_dinh_duong', '=', 1))

    if re.search(r'\btre(?: em)?\b.{0,40}\bthieu\b.{0,20}\b(?:di hoc|hoc tap|den truong)\b', q_key):
        child_specific.append(Filter('te_th_di_hoc', '=', 1))
    if re.search(r'\btre(?: em)?\b.{0,20}\b(?:khong|chua)(?:\s+co)?\s+(?:di hoc|hoc tap|den truong)\b', q_key):
        child_specific.append(Filter('te_th_di_hoc', '=', 1))
    found = _feature_rules_filters(question)
    found.extend(_support_filters(question))
    explicit_cols = {item.col for item in found}
    found.extend(_flag_group_label_filters(question, explicit_cols))
    explicit_cols = {item.col for item in found}
    for col, meta in FEATURE_CATALOG.items():
        if col in explicit_cols:
            continue

        if col == 'co_tre_em' and any(x in q_key for x in (
            'tre em duoi 6',
            'tre duoi 6',
        )):
            continue

        if meta.get('kind') != 'flag':
            continue

        aliases = []
        label = meta.get('label')
        if label:
            aliases.append(label)
        aliases.extend(meta.get('aliases', []))

        if any(
            alias_key and re.search(rf'\b{re.escape(alias_key)}\b', q_key)
            for alias_key in (vn_name_key(alias) for alias in aliases)
        ):
            found.append(Filter(col, '=', meta.get('value', 1)))
            explicit_cols.add(col)
    if child_specific:
        child_cols = {item.col for item in child_specific}
        generic_drop = {
            'co_tre_em',
            'th_bhyt' if 'te_th_bhyt' in child_cols else None,
            'th_dinh_duong' if 'te_th_dinh_duong' in child_cols else None,
            'th_di_hoc_tre_em' if 'te_th_di_hoc' in child_cols else None,
        }
        generic_drop.discard(None)

        found = [item for item in found if item.col not in generic_drop]
        existing_cols = {item.col for item in found}
        found.extend(item for item in child_specific if item.col not in existing_cols)
    # "chưa/không có nhà tiêu hợp vệ sinh" là thiếu nhà tiêu,
    # không phải co_nha_tieu_hvs = 1.
    if any(x in q_key for x in (
        'chua co nha tieu hop ve sinh',
        'khong co nha tieu hop ve sinh',
        'chua co nha ve sinh hop ve sinh',
        'khong co nha ve sinh hop ve sinh',
        'thieu nha tieu hop ve sinh',
        'thieu nha ve sinh hop ve sinh',
    )):
        found = [
            item for item in found
            if item.col not in {'co_nha_tieu_hvs', 'th_nha_tieu'}
        ]
        found.append(Filter('th_nha_tieu', '=', 1))
    return found

def _fix_child_bhyt_overlap(question: str, filters: list[Filter]) -> list[Filter]:
    q_key = vn_name_key(question)

    has_under6 = any(x in q_key for x in (
        "tre duoi 6",
        "tre em duoi 6",
        "duoi 6 tuoi",
    ))

    has_bhyt = any(x in q_key for x in (
        "thieu bhyt",
        "khong co bhyt",
        "thieu bao hiem y te",
        "khong co bao hiem y te",
    ))

    explicit_child_bhyt = any(x in q_key for x in (
        "tre em thieu bhyt",
        "tre thieu bhyt",
        "tre em thieu bao hiem y te",
        "tre thieu bao hiem y te",
    ))

    if has_under6 and has_bhyt and not explicit_child_bhyt:
        filters = [item for item in filters if item.col != "te_th_bhyt"]
        existing_cols = {item.col for item in filters}

        if "nhom_tre_em_duoi6" not in existing_cols:
            filters.append(Filter("nhom_tre_em_duoi6", "=", 1))

        if "th_bhyt" not in existing_cols:
            filters.append(Filter("th_bhyt", "=", 1))

    return filters

def _sanitize_filters_by_context(question: str, filters: list[Filter]) -> list[Filter]:
    q_key = vn_name_key(question)

    asks_head_disability = any(x in q_key for x in (
        'chu ho khuyet tat',
        'chu ho bi khuyet tat',
        'suc khoe chu ho khuyet tat',
        'chu ho la nguoi khuyet tat',
    ))

    has_household_disability = any(
        item.col == 'nhom_khuyet_tat' and item.op == '=' and item.value == 1
        for item in filters
    )

    if has_household_disability and not asks_head_disability:
        filters = [
            item for item in filters
            if not (
                item.col == 'suc_khoe_chu_ho'
                and vn_name_key(str(item.value)) == 'khuyet tat'
            )
        ]
     # Nếu đã hỏi rõ cột text "sức khỏe chủ hộ" thì không thêm flag ngữ nghĩa bên ngoài.
    # Ví dụ: "sức khỏe chủ hộ là ốm đau mãn tính hoặc khuyết tật"
    # chỉ được là suc_khoe_chu_ho IN (...), không thêm nn_om_dau OR nhom_khuyet_tat.
    has_head_health_text_filter = any(item.col == "suc_khoe_chu_ho" for item in filters)
    if has_head_health_text_filter:
        filters = [
            item for item in filters
            if item.col not in {"nn_om_dau", "nhom_khuyet_tat"}
        ]

    # Tránh bắt nhầm "diện tích" thành "có điện".
    if "dien tich" in q_key:
        filters = [item for item in filters if item.col != "co_dien"]

    if any(x in q_key for x in ("tre duoi 6", "tre em duoi 6", "duoi 6 tuoi")):
        filters = [
            item for item in filters
            if not (
                item.col in {"so_nhan_khau", "so_tre_em"}
                and item.op == "<"
                and item.value == 6
            )
        ]

    return filters

def _mentioned_gender_values(question: str) -> list[str]:
    """Nhận các giá trị giới tính, giữ nguyên dấu để không lẫn ``nam``/``năm``."""
    raw = re.sub(r"\s+", " ", (question or "").casefold()).strip()
    female_pattern = (
        r"\b(?:giới tính nữ|gioi tinh nu|nữ giới|nu gioi|"
        r"chủ hộ (?:là )?nữ|chu ho (?:la )?nu|là nữ|la nu)\b"
    )
    male_pattern = (
        r"\b(?:giới tính nam|gioi tinh nam|nam giới|nam gioi|"
        r"chủ hộ (?:là )?nam|chu ho (?:la )?nam|là nam|la nam)\b"
        r"(?!\s+(?:19|20)\d{2}\b)"
    )
    female = re.search(female_pattern, raw) is not None
    male = re.search(male_pattern, raw) is not None

    # Khi câu liệt kê trực tiếp "Nam và Nữ", token có dấu trong raw vẫn an
    # toàn: "năm 2024" không thể khớp với ``nam``.
    comparison_context = any(term in vn_name_key(question or "") for term in (
        "so sanh", "doi chieu", "giua", "va",
    ))
    if comparison_context:
        female = female or re.search(r"\bnữ\b|\bnu\b", raw) is not None
        male = male or re.search(r"\bnam\b(?!\s+(?:19|20)\d{2}\b)", raw) is not None

    values = []
    if male:
        values.append("Nam")
    if female:
        values.append("Nữ")
    return values


def _explicit_gender_value(question: str) -> str | None:
    values = _mentioned_gender_values(question)
    return values[0] if len(values) == 1 else None


def _explicit_classification_values(question: str) -> list[str]:
    """Chỉ nhận phân loại hộ khi câu hỏi nêu cụm đầy đủ.

    Không suy diễn từ chữ "nghèo" rời, "thiếu hụt", tên DB, hay ngữ cảnh
    thống kê đặc trưng. Điều này tránh thiên vị mọi câu "hộ" thành
    "hộ nghèo".
    """
    q_key = vn_name_key(question or "")
    patterns = (
        ("Hộ không nghèo", r"\bho khong ngheo\b"),
        ("Hộ cận nghèo", r"\bho can ngheo\b"),
        ("Hộ nghèo", r"\bho ngheo\b"),
    )
    return [value for value, pattern in patterns if re.search(pattern, q_key)]


def _base_filters(question: str) -> list[Filter]:
    entities = _extract_base_entities(question)
    filters = []
    for col, value in (('nam', entities.get('nam')), ('huyen', entities.get('huyen')), ('xa_phuong', entities.get('xa')), ('phan_loai', entities.get('phan_loai'))):
        if value is not None:
            filters.append(Filter(col, '=', value))
    q = question.lower()
    q_key = vn_name_key(question)
    # Chỉ nhận phân loại hộ khi người dùng nói rõ "hộ nghèo",
    # "hộ cận nghèo" hoặc "hộ không nghèo". Không default mọi câu
    # hỏi "hộ"/đặc trưng thành "Hộ nghèo".
    explicit_classes = _explicit_classification_values(question)
    filters = [item for item in filters if item.col != 'phan_loai']
    if len(explicit_classes) == 1:
        filters.append(Filter('phan_loai', '=', explicit_classes[0]))
    elif len(explicit_classes) > 1:
        filters.append(Filter('phan_loai', 'IN', explicit_classes))

    existing = {item.col for item in filters}
    if 'xa_phuong' in existing and 'huyen' not in existing:
        xa_value = next((item.value for item in filters if item.col == 'xa_phuong'))
        mapped_huyen = _catalog_values()[3].get(xa_value)
        if mapped_huyen:
            filters.append(Filter('huyen', '=', mapped_huyen))
            existing.add('huyen')
    if 'huyen' not in existing:
        for huyen in _catalog_values()[0]:
            if re.search(f'\\b{re.escape(vn_name_key(huyen))}\\b', q_key):
                filters.append(Filter('huyen', '=', huyen))
                break

    # Một câu có thể nêu nhiều địa bàn ("Gia Nghĩa và Tuy Đức"). Entity
    # extractor giữ một giá trị để tương thích các case cũ; tại đây nâng thành
    # IN theo catalog khi thực sự có từ hai huyện được nhắc đến.
    mentioned_huyens = [
        huyen for huyen in _catalog_values()[0]
        if re.search(rf'\b{re.escape(vn_name_key(huyen))}\b', q_key)
    ]
    if len(mentioned_huyens) >= 2:
        filters = [item for item in filters if item.col != 'huyen']
        filters.append(Filter('huyen', 'IN', mentioned_huyens))
    explicit_gender = _explicit_gender_value(question)
    if explicit_gender is not None:
        filters.append(Filter('gioi_tinh', '=', explicit_gender))
    # "các dân tộc khác nhau" hỏi miền giá trị, không phải nhãn dân tộc "Khác".
    if _is_distinct_value_question(question, 'dan_toc_chi_tiet'):
        return [item for item in filters if item.col != 'dan_toc_chi_tiet']
    for ethnicity in sorted(_catalog_values()[1], key=lambda value: len(vn_name_key(value)), reverse=True):
        ethnicity_key = vn_name_key(ethnicity)
        compact_key = ethnicity_key.replace(' ', '')

        # Không cho các dân tộc 1 âm tiết như "Mạ" match vào chữ nối tự nhiên "mà".
        # Chỉ nhận dân tộc khi người dùng nói rõ "dân tộc ...", "người ...", hoặc "tộc người ...".
        if len(ethnicity_key) <= 2:
            patterns = (
                f'\\bdan toc {re.escape(ethnicity_key)}\\b',
                f'\\bdan toc {re.escape(compact_key)}\\b',
                f'\\btoc nguoi {re.escape(ethnicity_key)}\\b',
                f'\\bnguoi {re.escape(ethnicity_key)}\\b',
            )
        else:
            patterns = (
                f'\\bdan toc {re.escape(ethnicity_key)}\\b',
                f'\\bdan toc {re.escape(compact_key)}\\b',
                f'\\btoc nguoi {re.escape(ethnicity_key)}\\b',
                f'\\bnguoi {re.escape(ethnicity_key)}\\b',
                f'\\bho (?:can )?ngheo {re.escape(ethnicity_key)}\\b',
                f'\\b{re.escape(ethnicity_key)} ngheo\\b',
                f'\\b{re.escape(compact_key)} ngheo\\b',
            )

        if any(re.search(pattern, q_key) for pattern in patterns):
            filters.append(Filter('dan_toc_chi_tiet', '=', ethnicity))
            break
    return filters

def _extract_base_entities(question: str) -> dict[str, Any]:
    q_key = vn_name_key(question)
    years = re.findall('\\b20\\d{2}\\b', question)
    entities: dict[str, Any] = {'nam': int(years[0]) if len(set(years)) == 1 else None, 'huyen': None, 'xa': None, 'phan_loai': None}
    for canonical, aliases in CLASSIFICATION_ALIASES:
        if any((re.search(f'\\b{re.escape(alias)}\\b', q_key) for alias in aliases)):
            entities['phan_loai'] = canonical
            break
    if not any((term in q_key for term in ('toan tinh', 'ca tinh'))):
        for district in sorted(_catalog_values()[0], key=lambda value: len(vn_name_key(value)), reverse=True):
            if re.search(f'\\b{re.escape(vn_name_key(district))}\\b', q_key):
                entities['huyen'] = district
                break
        with sqlite3.connect(DB_PATH) as conn:
            communes = conn.execute('SELECT DISTINCT xa_phuong FROM ho_ngheo WHERE xa_phuong IS NOT NULL').fetchall()
        matched_district_key = vn_name_key(entities['huyen']) if entities.get('huyen') else None
        has_commune_signal = any((x in q_key for x in ('xa ', 'phuong ', 'thi tran ', 'xã ', 'phường ', 'thị trấn ')))
        for commune, in sorted(communes, key=lambda row: len(vn_name_key(row[0])), reverse=True):
            commune_key = vn_name_key(commune)
            if matched_district_key and commune_key == matched_district_key:
                continue
            if entities.get('huyen') and (not has_commune_signal):
                continue
            if re.search(f'\\b{re.escape(commune_key)}\\b', q_key):
                entities['xa'] = commune
                break
    return entities

@lru_cache(maxsize=1)
def _catalog_values():
    with sqlite3.connect(DB_PATH) as conn:
        huyens = [row[0] for row in conn.execute('SELECT DISTINCT huyen FROM ho_ngheo WHERE huyen IS NOT NULL')]
        ethnicities = [row[0] for row in conn.execute('SELECT DISTINCT dan_toc_chi_tiet FROM ho_ngheo WHERE dan_toc_chi_tiet IS NOT NULL')]
        house_states = [row[0] for row in conn.execute('SELECT DISTINCT tinh_trang_nha FROM ho_ngheo WHERE tinh_trang_nha IS NOT NULL')]
        commune_to_district = dict(conn.execute('SELECT xa_phuong, huyen FROM ho_ngheo WHERE xa_phuong IS NOT NULL AND huyen IS NOT NULL GROUP BY xa_phuong HAVING COUNT(DISTINCT huyen) = 1'))
    return (huyens, ethnicities, house_states, commune_to_district)

def ambiguous_commune_in_question(question: str) -> tuple[str, list[str]] | None:
    q_key = vn_name_key(question)
    explicit_district = any((re.search(f'\\b{re.escape(vn_name_key(huyen))}\\b', q_key) for huyen in _catalog_values()[0]))
    if explicit_district:
        return None
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute('SELECT xa_phuong, huyen FROM ho_ngheo WHERE xa_phuong IS NOT NULL AND huyen IS NOT NULL GROUP BY xa_phuong, huyen ORDER BY xa_phuong, huyen').fetchall()
    districts_by_commune: dict[str, list[str]] = {}
    display_name: dict[str, str] = {}
    for commune, district in rows:
        key = vn_name_key(commune)
        districts_by_commune.setdefault(key, []).append(district)
        display_name[key] = commune
    for key in sorted(districts_by_commune, key=len, reverse=True):
        districts = sorted(set(districts_by_commune[key]))
        if len(districts) > 1 and re.search(f'\\b{re.escape(key)}\\b', q_key):
            return (display_name[key], districts)
    return None

def _lookup_name(question: str) -> str | None:
    q = re.sub(r"\s+", " ", question).strip()
    q_key = vn_name_key(q)

    lookup_context = (
        any(x in q_key for x in (
            "tra cuu ho",
            "tra cuu chu ho",
            "tra ho",
            "xem ho",
            "xem chu ho",
            "kiem tra ho",
            "kiem tra chu ho",
            "tim ho",
            "tim chu ho",
            "chu ho ten",
            "thong tin ho",
            "thong tin ho cua",
            "thong tin chu ho",
            "chi tiet ho",
            "cho biet ho",
            "cho biet chu ho",
            "thong tin co ban",
            "thong tin co ban cua chu ho",
            "cho biet thong tin co ban",
            "cho biet thong tin co ban cua chu ho",
        ))
        or re.match(r"^ho\s+(?!ngheo\b|can\b|khong\b)", q_key)
        or re.match(
            r"^[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ'\-]+(?:\s+[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ'\-]+){1,5}\s+(?:năm|nam)\s+20\d{2}\b",
            q,
        )
    )

    if not lookup_context:
        return None

    name_stop = r"(?=(?:\s+(?:năm|nam|trong|ở|o|tại|tai|thuộc|thuoc|gồm|gom|cho)\b|[:,.?!]|$))"
    name_part = r"([\wÀ-ỹĐđ][\wÀ-ỹĐđ .'-]{1,80}?)"

    patterns = [
        (
            r"(?:cho\s+biết|cho biet)?\s*"
            r"(?:thông\s+tin|thong tin)\s+"
            r"(?:cơ\s+bản|co ban)?\s*"
            r"(?:của|cua)?\s*"
            r"(?:chủ hộ|chu ho|hộ|ho)\s+"
            r"([\wÀ-ỹĐđ][\wÀ-ỹĐđ .'-]{2,80}?)"
            r"(?=\s+(?:năm|nam|ở|o|tại|tai|thuộc|thuoc|:|,|\.|\?|$))",
            re.IGNORECASE,
        ),
        (
            r"(?:tra\s+cứu|tra cuu|tra|xem|kiểm tra|kiem tra|tìm|tim)\s+"
            r"(?:chủ hộ|chu ho|hộ|ho)\s+"
            + name_part + name_stop,
            re.IGNORECASE,
        ),
        (
            r"(?:cho\s+biết|cho biet|xem)\s+"
            r"(?:chủ hộ|chu ho|hộ|ho)\s+"
            + name_part + name_stop,
            re.IGNORECASE,
        ),
        (
            r"(?:thông\s+tin|thong tin|chi\s+tiết|chi tiet)\s+"
            r"(?:hộ|ho|chủ hộ|chu ho)(?:\s+(?:của|cua))?\s+"
            + name_part + name_stop,
            re.IGNORECASE,
        ),
        (
            r"^(?:hộ|ho)\s+"
            r"(?!nghèo\b|ngheo\b|cận\b|can\b|không\b|khong\b)"
            + name_part + name_stop,
            re.IGNORECASE,
        ),
        (
            r"^([A-ZÀ-ỸĐ][A-ZÀ-ỸĐ'\-]+(?:\s+[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ'\-]+){1,5})"
            r"(?=\s+(?:năm|nam)\s+20\d{2}\b)",
            0,
        ),
    ]

    for pattern, flags in patterns:
        match = re.search(pattern, q, flags=flags)
        if not match:
            continue

        name = re.sub(r"\s+", " ", match.group(1)).strip()
        name = re.sub(r"^(?:của|cua)\s+", "", name, flags=re.IGNORECASE).strip()
        name = re.split(
            r"\s+trong dữ liệu\b|\s+năm\b|\s+nam\b",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        name = re.sub(r"^(?:hộ|ho|chủ hộ|chu ho)\s+", "", name, flags=re.IGNORECASE).strip()

        bad_names = {
            "toàn tỉnh", "toan tinh",
            "theo dân tộc", "theo dan toc",
            "có bao nhiêu hộ nghèo", "co bao nhieu ho ngheo",
            "có bao nhiêu hộ cận nghèo", "co bao nhieu ho can ngheo",
        }
        if vn_name_key(name) in {vn_name_key(x) for x in bad_names}:
            return None

        return name

    return None

def _has_explicit_year(question: str) -> bool:
    return re.search(r"\b20\d{2}\b", question or "") is not None


def _is_time_series_question(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return any(term in q_key for term in (
        "theo nam",
        "qua cac nam",
        "tung nam",
        "theo tung nam",
        "xu huong",
        "bien dong",
        "tang giam",
    ))


def _is_compare_years_request(question: str) -> bool:
    q_key = vn_name_key(question or "")
    years = set(re.findall(r"\b20\d{2}\b", question or ""))
    return len(years) >= 2 and any(term in q_key for term in (
        "so sanh", "doi chieu", "bien dong", "chenh lech", "tang", "giam",
    ))


def detect_ratio_intent(question: str) -> bool:
    q = (question or "").lower()
    q_key = vn_name_key(question or "")
    dependency_average = any(term in q_key for term in (
        "ty le phu thuoc",
        "ty le phu thuoc binh quan",
        "ty le phu thuoc trung binh",
    ))
    if dependency_average:
        return False
    return (
        any(term in q for term in ("tỷ lệ", "tỷ trọng", "phần trăm", "%", "chiếm bao nhiêu"))
        or any(term in q_key for term in ("ty le", "ty trong", "phan tram", "chiem bao nhieu"))
    )


def _plan_value(plan: Any, key: str, default: Any = None) -> Any:
    if isinstance(plan, dict):
        return plan.get(key, default)
    return getattr(plan, key, default)


def _is_group_by_year_plan(plan: Any) -> bool:
    return "nam" in (_plan_value(plan, "group_by", []) or [])


def _should_apply_default_year(question: str, plan: Any) -> bool:
    if _has_explicit_year(question):
        return False
    if _is_group_by_year_plan(plan):
        return False
    if _is_time_series_question(question):
        return False
    if _plan_value(plan, "task") == "compare_years":
        return False
    return True


def should_use_query_plan(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)
    feature_count = len(_feature_filters(question))
    value_catalog_cols = (
        (set(SAME_COLUMN_CATALOG_CONTEXTS) | set(TEXT_FILTER_LABELS))
        & set(GROUP_COLUMNS)
        & _schema_columns()
    )
    has_catalog_value = any(
        _mentioned_catalog_values(question, col)
        for col in value_catalog_cols
    )
    signals = feature_count
    signals += int(has_catalog_value)
    signals += int(bool(re.search('\\b(?:19|20)\\d{2}\\b', q)))
    signals += int(any((x in q_key for x in ('ho ngheo', 'ho can ngheo', 'ho kho khan', 'ho sat ngheo', 'nhom ngheo', 'nhom can ngheo'))))
    signals += int(any((re.search(f'\\b{re.escape(vn_name_key(huyen))}\\b', q_key) for huyen in _catalog_values()[0])))
    signals += int(any((x in q_key for x in ('dan toc', 'gioi tinh', 'tinh trang nha'))))
    numeric_record_rank_signal = (
        _mentioned_numeric_field(question) is not None
        and re.search(r'\b\d{1,3}\s+ho\b.{0,80}\b(?:co|nhieu|it|cao|thap|lon|nho)\b', q_key) is not None
    )
    numeric_aggregate_signal = (
        _mentioned_numeric_field(question) is not None
        and (_extract_avg_metric(question) is not None or _extract_sum_metric(question) is not None)
    )
    return (
        _is_general_policy_support_metrics_question(question)
        or
        numeric_record_rank_signal
        or numeric_aggregate_signal
        or (
            has_catalog_value
            and any(x in q_key for x in ("bao nhieu", "co may", "so luong", "liet ke", "danh sach"))
        )
        or _asks_all_social_deprivation_indicators(question)
        or _is_compare_years_request(question)
        or (_is_time_series_question(question) and signals >= 1)
        or any((word in q for word in (
            'liệt kê', 'danh sách', 'tra cứu', 'tìm chủ hộ', 'chủ hộ tên',
            'cho biết hộ', 'xem hộ', 'kiểm tra hộ', 'cho tôi thông tin',
            'thông tin hộ', 'chi tiết hộ', 'theo huyện', 'theo xã',
            'theo dân tộc', 'theo giới tính'
        )))
        or signals >= 2
    )

def _extract_avg_metric(question: str):
    q = question.lower()
    q_key = vn_name_key(question)

    average_signal = any(x in q_key for x in ("binh quan", "trung binh", " tb"))
    if average_signal:
        average_fields = (
            ("so_tre_em", ("so tre em", "tre em")),
            ("so_nguoi_lao_dong", ("so nguoi lao dong", "nguoi lao dong", "lao dong")),
            ("so_nguoi_cao_tuoi", ("so nguoi cao tuoi", "nguoi cao tuoi")),
        )
        for col, aliases in average_fields:
            if any(re.search(rf"\b{re.escape(alias)}\b", q_key) for alias in aliases):
                return ("avg", col)

    if (
        'tỷ lệ phụ thuộc bình quân' in q
        or 'tỷ lệ phụ thuộc trung bình' in q
        or 'ty le phu thuoc binh quan' in q_key
        or 'ty le phu thuoc trung binh' in q_key
    ):
        return ('avg', 'ty_le_phu_thuoc')

    if (
        any(x in q for x in (
            'thu nhập bình quân', 'thu nhập trung bình', 'thu nhập tb',
            'thu nhập/người', 'bình quân thu nhập', 'trung bình thu nhập',
            'thu nhập/tháng', 'tháng/người'
        ))
        or any(x in q_key for x in (
            'thu nhap binh quan', 'thu nhap trung binh', 'thu nhap tb',
            'thu nhap nguoi', 'binh quan thu nhap', 'trung binh thu nhap',
            'thu nhap thang'
        ))
        or re.search(r'\bthu nhap\b.{0,50}\b(?:binh quan|trung binh|tb)\b', q_key)
        or re.search(r'\b(?:binh quan|trung binh|tb)\b.{0,50}\bthu nhap\b', q_key)
    ):
        return ('avg', 'thu_nhap_bq')

    if (
        any(x in q for x in (
            'nhân khẩu trung bình', 'nhân khẩu bình quân',
            'bình quân nhân khẩu', 'trung bình nhân khẩu',
            'quy mô hộ', 'bao nhiêu nhân khẩu', 'mấy nhân khẩu', 'có mấy nhân khẩu'
        ))
        or any(x in q_key for x in (
            'nhan khau trung binh', 'nhan khau binh quan',
            'binh quan nhan khau', 'trung binh nhan khau',
            'quy mo ho', 'bao nhieu nhan khau', 'may nhan khau', 'co may nhan khau'
        ))
    ):
        return ('avg', 'so_nhan_khau')

    if (
        any(x in q for x in (
            'diện tích đất trung bình', 'diện tích đất bình quân',
            'diện tích trung bình', 'diện tích bình quân',
            'đất canh tác trung bình', 'đất canh tác bình quân',
            'đất sản xuất trung bình', 'đất sản xuất bình quân'
        ))
        or any(x in q_key for x in (
            'dien tich dat trung binh', 'dien tich dat binh quan',
            'dien tich trung binh', 'dien tich binh quan',
            'dat canh tac trung binh', 'dat canh tac binh quan',
            'dat san xuat trung binh', 'dat san xuat binh quan'
        ))
    ):
        return ('avg', 'dien_tich_dat')

    if (
        any(x in q for x in (
            'số chiều thiếu hụt bình quân',
            'số chiều thiếu hụt trung bình',
            'thiếu hụt bình quân',
            'thiếu hụt trung bình'
        ))
        or any(x in q_key for x in (
            'so chieu thieu hut binh quan',
            'so chieu thieu hut trung binh',
            'thieu hut binh quan',
            'thieu hut trung binh'
        ))
    ):
        return ('avg', 'tong_chieu_thieu_hut')

    return None

def _extract_sum_metric(question: str):
    q = question.lower()
    q_key = vn_name_key(question)

    if detect_ratio_intent(question):
        return None

    child_count_col = _child_deprivation_count_metric_col(question)
    if child_count_col:
        return ('sum', child_count_col)

    if any(x in q for x in ('tổng nhân khẩu', 'tổng số nhân khẩu')) or any(x in q_key for x in ('tong nhan khau', 'tong so nhan khau')):
        return ('sum', 'so_nhan_khau')

    if any(x in q for x in ('tổng số trẻ em', 'tổng trẻ em', 'tổng số trẻ')) or any(x in q_key for x in ('tong so tre em', 'tong tre em', 'tong so tre')):
        return ('sum', 'so_tre_em')

    if any(x in q_key for x in ('tong so nguoi lao dong', 'tong nguoi lao dong', 'tong so lao dong', 'tong lao dong')):
        return ('sum', 'so_nguoi_lao_dong')

    if any(x in q_key for x in ('tong so nguoi cao tuoi', 'tong nguoi cao tuoi')):
        return ('sum', 'so_nguoi_cao_tuoi')

    if any(x in q for x in ('tổng diện tích đất', 'tổng đất sản xuất', 'tổng đất canh tác')) or any(x in q_key for x in ('tong dien tich dat', 'tong dat san xuat', 'tong dat canh tac')):
        return ('sum', 'dien_tich_dat')

    return None

def _child_deprivation_count_metric_col(question: str | None) -> str | None:
    q_key = vn_name_key(question or '')
    if not re.search(r'\btre(?: em)?\b', q_key):
        return None

    household_count_signal = any(x in q_key for x in (
        'bao nhieu ho',
        'co may ho',
        'so ho',
        'tong so ho',
        'tong ho',
        'ho nao',
        'cac ho',
        'nhung ho',
        'ho co tre',
    ))
    child_count_signal = (
        any(x in q_key for x in (
            'bao nhieu tre',
            'co may tre',
            'so tre',
            'tong so tre',
            'tong tre',
        ))
        or re.search(r'\btre(?: em)?\b.{0,30}\bbao nhieu\b', q_key) is not None
    )
    child_ranking_signal = (
        _ranking_direction(question or '') is not None
        and re.search(r'\btre(?: em)?\b.{0,80}\b(?:thieu|khong co|khong|chua)\b', q_key) is not None
        and not household_count_signal
    )
    if household_count_signal and not child_count_signal:
        return None
    if not child_count_signal and not child_ranking_signal:
        return None

    if re.search(r'\btre(?: em)?\b.{0,50}\b(?:thieu|khong co)\b.{0,25}\b(?:bhyt|bao hiem y te)\b', q_key):
        return 'so_tre_thieu_bhyt'
    if re.search(r'\btre(?: em)?\b.{0,50}\bthieu\b.{0,25}\bdinh duong\b', q_key):
        return 'so_tre_thieu_dinh_duong'
    if (
        re.search(r'\btre(?: em)?\b.{0,50}\bthieu\b.{0,25}\b(?:di hoc|hoc tap|den truong)\b', q_key)
        or re.search(r'\btre(?: em)?\b.{0,30}\b(?:khong|chua)(?:\s+co)?\s+(?:di hoc|hoc tap|den truong)\b', q_key)
    ):
        return 'so_tre_thieu_di_hoc'
    return None

_DEFAULT_POLICY_SUPPORT_METRICS = {
    "htro_y_te",
    "htro_giao_duc",
    "htro_vay_von",
    "htro_nha_o",
}

_GENERAL_POLICY_SUPPORT_PHRASES = (
    "noi dung ho tro",
    "cac noi dung ho tro",
    "ho tro duoc ghi nhan",
    "noi dung ho tro duoc ghi nhan",
    "cac noi dung ho tro duoc ghi nhan",
)

def _is_general_policy_support_metrics_question(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return "ho tro" in q_key and any(
        phrase in q_key for phrase in _GENERAL_POLICY_SUPPORT_PHRASES
    )

def _multi_numeric_metric_cols(question: str) -> set[str]:
    q_key = vn_name_key(question or '')
    cols: set[str] = set()

    if any(x in q_key for x in (
        'thu nhap binh quan',
        'thu nhap trung binh',
        'binh quan thu nhap',
        'trung binh thu nhap',
    )):
        cols.add('thu_nhap_bq')

    if any(x in q_key for x in (
        'nhan khau binh quan',
        'nhan khau trung binh',
        'binh quan nhan khau',
        'trung binh nhan khau',
    )):
        cols.add('so_nhan_khau')

    if (
        any(x in q_key for x in (
            'dien tich dat binh quan',
            'dien tich dat trung binh',
            'dien tich binh quan',
            'dien tich trung binh',
            'dat binh quan',
            'dat trung binh',
        ))
        or re.search(r'\bbinh quan\b.{0,30}\bdat\b', q_key)
        or re.search(r'\bdat\b.{0,30}\bbinh quan\b', q_key)
    ):
        cols.add('dien_tich_dat')

    return cols

def _extract_list_select_columns(question: str, base_select: list) -> list:
    q = question.lower()
    select = list(base_select)
    if any((x in q for x in ('tình trạng nhà', 'nhà ở', 'loại nhà', 'loại gì', 'thuộc loại gì', 'chất lượng nhà'))):
        select = _append_unique(select, ['tinh_trang_nha'])
    if any((x in q for x in ('phân loại', 'nhóm hộ', 'loại hộ'))):
        select = _append_unique(select, ['phan_loai'])
    if any((x in q for x in ('dân tộc', 'tộc người'))):
        select = _append_unique(select, ['dan_toc_chi_tiet'])
    if any(x in q for x in ('giới tính', 'chủ hộ nữ', 'chủ hộ là nữ', 'chủ hộ nam', 'chủ hộ là nam')):
        select = _append_unique(select, ['gioi_tinh'])
    if 'thu nhập' in q:
        select = _append_unique(select, ['thu_nhap_bq'])
    if 'nhân khẩu' in q:
        select = _append_unique(select, ['so_nhan_khau'])
    if any((x in q for x in ('thiếu hụt', 'số chiều'))):
        select = _append_unique(select, ['tong_chieu_thieu_hut'])
    if any((x in q for x in ('bhyt', 'bảo hiểm y tế'))):
        select = _append_unique(select, ['th_bhyt'])
    if any((x in q for x in ('trẻ dưới 6', 'trẻ em dưới 6'))):
        select = _append_unique(select, ['so_tre_em', 'nhom_tre_em_duoi6'])
    elif any((x in q for x in ('trẻ em', 'trẻ nhỏ'))):
        select = _append_unique(select, ['so_tre_em', 'co_tre_em'])
    if 'internet' in q:
        select = _append_unique(select, ['co_internet'])
    if 'điện' in q:
        select = _append_unique(select, ['co_dien'])
    return select

def _auto_include_visible_filter_columns(select: list[str], filters: list[Filter]) -> list[str]:
    hidden_filter_cols = {'nam', 'huyen', 'xa_phuong', 'phan_loai'}

    visible_cols = [
        item.col
        for item in filters
        if item.col in OUTPUT_COLUMNS
        and item.col not in hidden_filter_cols
    ]

    return _append_unique(select, visible_cols)

def _suppress_parent_metrics_when_child_is_explicit(question: str, cols: set[str]) -> set[str]:
    q_key = vn_name_key(question or "")
    cleaned_cols = set(cols)

    for child_col in list(cols):
        spec = FEATURE_CATALOG.get(child_col) or {}
        parent_cols = spec.get("overlap_filter_cols") or []

        if not parent_cols:
            continue

        child_aliases = [child_col]
        child_aliases.extend(spec.get("aliases") or [])
        child_aliases.append(spec.get("label") or "")

        child_phrases = [
            vn_name_key(str(x))
            for x in child_aliases
            if str(x).strip()
        ]

        child_mentioned = any(phrase and phrase in q_key for phrase in child_phrases)
        if not child_mentioned:
            continue

        remaining = q_key
        for phrase in sorted(child_phrases, key=len, reverse=True):
            if phrase:
                remaining = remaining.replace(phrase, " ")

        for parent_col in parent_cols:
            parent_spec = FEATURE_CATALOG.get(parent_col) or {}
            parent_aliases = [parent_col]
            parent_aliases.extend(parent_spec.get("aliases") or [])
            parent_aliases.append(parent_spec.get("label") or "")

            parent_phrases = [
                vn_name_key(str(x))
                for x in parent_aliases
                if str(x).strip()
            ]

            parent_mentioned_independently = any(
                phrase and phrase in remaining
                for phrase in parent_phrases
            )

            if not parent_mentioned_independently:
                cleaned_cols.discard(parent_col)

    return cleaned_cols

def _multi_metric_filter_cols(question: str) -> set[str]:
    cols = _mentioned_feature_cols(question)
    q_key = vn_name_key(question)

    if _is_general_policy_support_metrics_question(question):
        # "Các nội dung hỗ trợ" là intent tổng hợp nhóm metric hỗ trợ,
        # không phải câu thiếu loại hỗ trợ cụ thể.
        cols.update(_DEFAULT_POLICY_SUPPORT_METRICS)

    if any(phrase in q_key for phrase in (
        "theo nhom doi tuong",
        "cac nhom doi tuong",
        "nhom doi tuong",
        "doi tuong ho ngheo",
        "nhom ho ngheo theo doi tuong",
        "nhom doi tuong ho ngheo",
    )):
        cols.update({
            "co_tre_em",
            "nhom_cao_tuoi",
            "nhom_khuyet_tat",
            "nhom_don_than",
            "nhom_chu_ho_nu",
            "nhom_khong_knld",
        })

    for col, aliases in MULTI_METRIC_TERM_ALIASES.items():
        if any(re.search(rf'\b{re.escape(vn_name_key(alias))}\b', q_key) for alias in aliases):
            cols.add(col)

    if any((x in q_key for x in ('chu ho nu', 'chu ho la nu'))):
        cols.update({'gioi_tinh', 'nhom_chu_ho_nu'})

    if any(x in q_key for x in (
        "nha o kem",
        "nha kem",
        "nha xau",
        "nha o khong dam bao",
        "nha khong dam bao",
        "nha tam bo",
        "khong vung chac",
    )):
        cols.add("tinh_trang_nha")
    if any(x in q_key for x in (
        "co nha tieu hop ve sinh",
        "co nha ve sinh hop ve sinh",
        "co nha tieu hvs",
        "co nha ve sinh hvs",
    )):
        cols.discard("th_nha_tieu")
        cols.add("co_nha_tieu_hvs")

    return _suppress_parent_metrics_when_child_is_explicit(question, cols)

def _looks_like_intersection_count_table(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)

    table_or_group_signal = any(x in q_key for x in (
        "bang",
        "thong ke",
        "theo huyen",
        "theo xa",
        "tung huyen",
        "tung xa",
    ))

    intersection_signal = (
        any(x in q for x in ("vừa", "đồng thời", "cùng lúc"))
        or any(x in q_key for x in ("vua", "dong thoi", "cung luc"))
        or (
            any(x in q_key for x in (" va ", " kem "))
            and not any(x in q_key for x in ("gom", "bao gom", "cac chi tieu", "lan luot", "tuong ung"))
        )
    )

    explicit_multi_metric_signal = any(x in q_key for x in (
        "gom",
        "bao gom",
        "cac chi tieu",
        "nhieu chi tieu",
        "lan luot",
        "tuong ung",
        "moi cot",
    ))
    

    return table_or_group_signal and intersection_signal and not explicit_multi_metric_signal

def _detect_multi_metric_table(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)

    if _is_general_policy_support_metrics_question(question):
        return True

    if _movement_count_and_population_table_signal(question):
        return True

    if any(phrase in q_key for phrase in (
        "theo nhom doi tuong",
        "cac nhom doi tuong",
        "nhom doi tuong",
        "doi tuong ho ngheo",
        "nhom ho ngheo theo doi tuong",
        "nhom doi tuong ho ngheo",
    )):
        return True
    support_metric_count = 0
    if any(x in q_key for x in ("ho tro", "duoc ho tro", "nhan ho tro")):
        support_metric_count = sum(
            1 for _, aliases in SUPPORT_TERM_ALIASES.items()
            if any(re.search(rf"\b{re.escape(vn_name_key(alias))}\b", q_key) for alias in aliases)
        )
        if support_metric_count >= 2:
            return True

    if _looks_like_intersection_count_table(question):
        return False
    multi_metric_signal = (
        any(x in q for x in (
            "gồm", "bao gồm", "các chỉ tiêu", "nhiều chỉ tiêu",
        ))
        or any(x in q_key for x in (
            "gom", "bao gom", "cac chi tieu", "nhieu chi tieu",
        ))
        or ":" in question
        or "," in question
    )

    explicit_multi_table_signal = (
        (
            any(x in q for x in ("bảng", "lập bảng"))
            or any(x in q_key for x in ("bang", "lap bang"))
        )
        and multi_metric_signal
    )

    metric_count = (
        len(_multi_metric_filter_cols(question))
        + len(_multi_numeric_metric_cols(question))
        + support_metric_count
    )

    wants_total = any((x in q_key for x in (
        "tong ho",
        "tong ho ngheo",
        "tong ho can ngheo",
        "tong ho khong ngheo",
    )))

    total_metric_signals = sum(1 for x in (
        "tong ho",
        "tong ho ngheo",
        "tong ho can ngheo",
        "tong ho khong ngheo",
    ) if x in q_key)

    if wants_total:
        metric_count += 1

    return explicit_multi_table_signal and (
        total_metric_signals >= 2
        or metric_count >= 2
    )

def _apply_specific_filter_overrides(filters: list[Filter]) -> list[Filter]:
    present_cols = {f.col for f in filters}
    suppress_cols = set()

    for specific_col, rule in SPECIFIC_FILTER_OVERRIDES.items():
        if specific_col in present_cols:
            suppress_cols.update(rule.get("suppresses", []))

    return [f for f in filters if f.col not in suppress_cols]

@lru_cache(maxsize=32)
def _catalog_distinct_values(col: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute(f'SELECT DISTINCT {col} FROM {TABLE} WHERE {col} IS NOT NULL').fetchall()]


@lru_cache(maxsize=1)
def _latest_data_year() -> int | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(f"SELECT MAX(nam) FROM {TABLE} WHERE nam IS NOT NULL").fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _mentioned_catalog_values(question: str, col: str) -> list[str]:
    q_key = vn_name_key(question)
    q_accented = vn_text_key_keep_accents(question)
    context_terms = SAME_COLUMN_CATALOG_CONTEXTS.get(col, ())
    if context_terms and (not any((term in q_key for term in context_terms))):
        return []
    found = []
    if col == "nguon_nuoc":
        if re.search(r"\bnước\s+mưa\b", q_accented):
            found.append("Nước mưa")
        elif re.search(r"\bnước\s+mua(?:\s+(?:bình|bể)(?:/bể)?)?\b", q_accented) or re.search(
            r"\bnuoc\s+mua(?:\s+(?:binh|be)(?:\s+be)?)?\b", q_key
        ):
            found.append("Nước mua bình/bể")
    distinct_values = sorted(
        _catalog_distinct_values(col),
        key=lambda x: len(vn_text_key_keep_accents(str(x))),
        reverse=True,
    )
    # Với trạng thái biến động, một nhãn ngắn có thể nằm trọn trong nhãn dài
    # ("nghèo mới phát sinh" / "cận nghèo mới phát sinh"). Nhánh alias dài
    # nhất bên dưới xử lý riêng để không lấy đồng thời cả hai.
    if col != "bien_dong_dau_ky":
        for value in distinct_values:
            value_accented = vn_text_key_keep_accents(str(value))
            if value_accented and re.search(rf"(?<!\w){re.escape(value_accented)}(?!\w)", q_accented):
                found.append(value)
    value_aliases = CATALOG_VALUE_ALIASES.get(col, {})
    if col == "bien_dong_dau_ky":
        # Nhãn biến động có nhiều cụm lồng nhau, ví dụ "nghèo mới phát sinh"
        # nằm trong "cận nghèo mới phát sinh". Vì vậy không lấy "alias dài
        # nhất toàn câu" nữa (sẽ làm mất các nhãn khác trong câu so sánh),
        # mà lấy các alias dài nhất theo từng vùng không chồng lấn.
        alias_matches: list[tuple[int, int, int, str]] = []
        for canonical_value, aliases in value_aliases.items():
            for alias in aliases:
                if not alias:
                    continue
                for match in re.finditer(rf"\b{re.escape(alias)}\b", q_key):
                    alias_matches.append((match.start(), match.end(), len(alias), canonical_value))

        selected_spans: list[tuple[int, int, str]] = []
        for start, end, _length, canonical_value in sorted(
            alias_matches,
            key=lambda item: (-(item[1] - item[0]), item[0], item[3]),
        ):
            if any(not (end <= s or start >= e) for s, e, _ in selected_spans):
                continue
            selected_spans.append((start, end, canonical_value))

        for _start, _end, canonical_value in sorted(selected_spans):
            found.append(canonical_value)
    else:
        for canonical_value, aliases in value_aliases.items():
            if any((re.search(f'\\b{re.escape(alias)}\\b', q_key) for alias in aliases)):
                found.append(canonical_value)
    normalized_values: dict[str, list[Any]] = {}
    for value in distinct_values:
        normalized_values.setdefault(vn_name_key(str(value)), []).append(value)
    for value in (
        [] if col == "bien_dong_dau_ky"
        else sorted(distinct_values, key=lambda x: len(vn_name_key(str(x))), reverse=True)
    ):
        if col == "nguon_nuoc" and str(value) in {"Nước mưa", "Nước mua bình/bể"}:
            # Hai giá trị này cùng thành "nuoc mua" sau khi bỏ dấu; chỉ nhận
            # diện bằng nhánh có dấu/cụm đầy đủ ở trên.
            continue
        value_key = vn_name_key(str(value))
        if not value_key:
            continue
        if value_key in {'khac'}:
            continue
        if len(normalized_values.get(value_key, [])) == 1 and re.search(f'\\b{re.escape(value_key)}\\b', q_key):
            found.append(value)
    return list(dict.fromkeys(found))


def _filter_values_for_col(filters: list[Filter], col: str) -> list[Any]:
    values: list[Any] = []
    for item in filters:
        if item.col != col:
            continue
        raw_values = item.value if item.op == "IN" and isinstance(item.value, (list, tuple, set)) else [item.value]
        values.extend(raw_values)
    return list(dict.fromkeys(values))


def _has_explicit_final_class_context(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return any(x in q_key for x in (
        "phan loai", "phan loai cuoi ky", "cuoi ky", "hien tai", "dang la",
        "thuoc nhom ho ngheo cuoi ky", "thuoc nhom ho can ngheo cuoi ky",
        "tong so ho ngheo", "tong ho ngheo", "tren tong so ho ngheo",
        "tong so ho can ngheo", "tong ho can ngheo", "tren tong so ho can ngheo",
    ))


def _suppress_class_filters_for_movement_context(question: str, filters: list[Filter]) -> list[Filter]:
    """Không để cụm nghèo/cận nghèo nằm trong nhãn biến động thành filter phan_loai.

    Ví dụ: "cận nghèo trở thành hộ nghèo" tự thân đã là một giá trị
    bien_dong_dau_ky. Nếu đồng thời ép phan_loai IN (Hộ nghèo, Hộ cận nghèo)
    hoặc phan_loai = Hộ cận nghèo, câu hỏi dễ bị hiểu sai thành lọc trạng thái
    cuối kỳ. Chỉ giữ phan_loai khi người dùng nói rõ đang hỏi phân loại/cuối kỳ.
    """
    movement_values = _filter_values_for_col(filters, "bien_dong_dau_ky")
    if not movement_values or _has_explicit_final_class_context(question):
        return filters

    movement_text = " ".join(vn_name_key(str(value)) for value in movement_values)
    if not any(x in movement_text for x in ("ngheo", "can ngheo", "khong ngheo")):
        return filters

    return [item for item in filters if item.col != "phan_loai"]


def _movement_count_and_population_table_signal(question: str) -> bool:
    q_key = vn_name_key(question or "")
    has_movement = bool(_mentioned_catalog_values(question, "bien_dong_dau_ky"))
    has_house_count = any(x in q_key for x in ("so ho", "tong ho", "bao nhieu ho", "co may ho"))
    has_population = any(x in q_key for x in ("tong nhan khau", "nhan khau tuong ung", "nhan khau tuong ung", "so nhan khau tuong ung"))
    has_table_or_group = any(x in q_key for x in ("lap bang", "bang", "theo huyen", "tung huyen", "theo xa", "tung xa", "theo dia ban"))
    return has_movement and has_house_count and has_population and has_table_or_group


def _movement_difference_question(question: str, filters: list[Filter]) -> bool:
    q_key = vn_name_key(question or "")
    movement_values = _filter_values_for_col(filters, "bien_dong_dau_ky")
    return (
        len(movement_values) >= 2
        and any(x in q_key for x in ("chenh", "chenh lech", "so voi", "co phai", "phai la", "nhom nao nhieu nhat"))
    )


def _collapse_or_same_column_filters(question: str, filters: list[Filter]) -> list[Filter]:
    q = question.lower()
    q_key = vn_name_key(question)
    class_values = []
    if 'ho ngheo' in q_key:
        class_values.append('Hộ nghèo')
    if 'ho can ngheo' in q_key or 'can ngheo' in q_key:
        class_values.append('Hộ cận nghèo')
    if 'ho khong ngheo' in q_key or 'khong ngheo' in q_key:
        class_values.append('Hộ không nghèo')
    if len(class_values) >= 2:
        filters = [f for f in filters if f.col != 'phan_loai']
        filters.append(Filter('phan_loai', 'IN', list(dict.fromkeys(class_values))))
    gender_values = _mentioned_gender_values(question)
    if len(gender_values) >= 2:
        filters = [f for f in filters if f.col != 'gioi_tinh']
        filters.append(Filter('gioi_tinh', 'IN', gender_values))
    house_values = []
    if 'nha tam' in q_key:
        house_values.append('Nhà tạm')
    if 'nha don so' in q_key or 'don so' in q_key:
        house_values.append('Nhà đơn sơ')
    if 'khong co nha' in q_key:
        house_values.append('Không có nhà')
    if 'ban kien co' in q_key:
        house_values.append('Bán kiên cố')
    if 'kien co' in q_key and 'ban kien co' not in q_key:
        house_values.append('Kiên cố')
    if len(house_values) >= 2:
        filters = [f for f in filters if f.col != 'tinh_trang_nha']
        filters.append(Filter('tinh_trang_nha', 'IN', list(dict.fromkeys(house_values))))
    ethnicity_values = []
    for ethnicity in sorted(_catalog_values()[1], key=lambda x: len(vn_name_key(x)), reverse=True):
        ethnicity_key = vn_name_key(ethnicity)
        compact_key = ethnicity_key.replace(' ', '')
        patterns = (f'\\bdan toc {re.escape(ethnicity_key)}\\b', f'\\bdan toc {re.escape(compact_key)}\\b', f'\\bnguoi {re.escape(ethnicity_key)}\\b', f'\\b{re.escape(ethnicity_key)}\\b', f'\\b{re.escape(compact_key)}\\b')
        if any((re.search(pattern, q_key) for pattern in patterns)):
            ethnicity_values.append(ethnicity)
    if len(ethnicity_values) >= 2:
        filters = [f for f in filters if f.col != 'dan_toc_chi_tiet']
        filters.append(Filter('dan_toc_chi_tiet', 'IN', list(dict.fromkeys(ethnicity_values))))
    catalog_value_cols = (
        (set(SAME_COLUMN_CATALOG_CONTEXTS) | set(TEXT_FILTER_LABELS))
        & set(GROUP_COLUMNS)
    ) - {
        'huyen', 'xa_phuong', 'phan_loai', 'gioi_tinh',
        'dan_toc_chi_tiet', 'nam',
    }
    for col in sorted(catalog_value_cols):
        # Khi người dùng hỏi "theo loại xã/phường" thì đây là group_by,
        # không phải filter loai_xa_phuong IN ('xa', 'phuong').
        if col == "loai_xa_phuong" and any(x in q_key for x in (
            "theo loai xa phuong",
            "theo loai xa",
            "thong ke theo loai xa",
            "phan bo theo loai xa",
            "co cau theo loai xa",
        )):
            continue

        values = _mentioned_catalog_values(question, col)
        if values:
            filters = [f for f in filters if f.col != col]
            if len(values) == 1:
                filters.append(Filter(col, '=', values[0]))
            else:
                filters.append(Filter(col, 'IN', values))
    return filters

def _terms_for_flag_col(col: str) -> list[str]:
    terms = []
    for keywords in FEATURE_KEYWORDS.get(col) or ():
        terms.append(vn_name_key(keywords))
    for rule in FEATURE_RULES:
        if rule.get('col') == col:
            for key in ('positive', 'negative', 'blocked_by'):
                for term in rule.get(key, ()) or ():
                    terms.append(vn_name_key(term))
    for group in FLAG_GROUPS.values():
        for label, label_col in group['columns'].items():
            if label_col == col:
                label_key = vn_name_key(label)
                terms.append(label_key)
                if not label_key.startswith('thieu '):
                    terms.append(f'thieu {label_key}')
                    terms.append(f'khong co {label_key}')
    col_key = col.replace('_', ' ')
    terms.append(vn_name_key(col_key))
    return list(dict.fromkeys((t for t in terms if t)))

def _or_connects_flag_candidates(question: str, candidates: list[Filter]) -> bool:
    q_key = vn_name_key(question)
    segments = re.split('\\bhoac\\b', q_key)
    if len(segments) < 2:
        return False
    candidate_cols = {item.col for item in candidates}
    segment_cols = []
    for segment in segments:
        cols = set()
        for col in candidate_cols:
            terms = _terms_for_flag_col(col)
            if any((re.search(f'\\b{re.escape(term)}\\b', segment) for term in terms)):
                cols.add(col)
        segment_cols.append(cols)
    cols_by_segment = [cols for cols in segment_cols if cols]
    if len(cols_by_segment) < 2:
        return False
    mentioned_cols = set().union(*cols_by_segment)
    return len(mentioned_cols & candidate_cols) >= 2

def _split_or_feature_filters(question: str, filters: list[Filter]) -> tuple[list[Filter], list[Filter]]:
    q = question.lower()
    q_key = vn_name_key(question)
    if ' hoặc ' not in q and ' hoac ' not in q_key:
        return (filters, [])
    or_candidate_cols = set(FLAG_COLUMNS)
    candidates = [item for item in filters if item.col in or_candidate_cols and item.op == '=' and (item.value in (0, 1))]
    if len(candidates) < 2:
        return (filters, [])
    same_column_cols = {'phan_loai', 'dan_toc_chi_tiet', 'tinh_trang_nha', *SAME_COLUMN_CATALOG_CONTEXTS.keys()}
    has_same_column_in_filter = any((item.op == 'IN' and item.col in same_column_cols for item in filters))
    feature_or_context = _or_connects_flag_candidates(question, candidates)
    if has_same_column_in_filter and (not feature_or_context):
        return (filters, [])
    # Xử lý dạng: A và B hoặc C  =>  A AND (B OR C)
    # Ví dụ: trẻ dưới 6 tuổi và thiếu BHYT hoặc thiếu BHXH.
    hoac_pos = q_key.find(" hoac ")
    if hoac_pos >= 0:
        and_pos = q_key.rfind(" va ", 0, hoac_pos)

        if and_pos >= 0:
            def _first_mention_pos(item: Filter) -> int:
                positions = []
                for term in _terms_for_flag_col(item.col):
                    if not term:
                        continue
                    m = re.search(rf"\b{re.escape(term)}\b", q_key)
                    if m:
                        positions.append(m.start())
                return min(positions) if positions else 10 ** 9

            left_and_candidates = [
                item for item in candidates
                if _first_mention_pos(item) < and_pos
            ]

            if left_and_candidates and len(candidates) - len(left_and_candidates) >= 2:
                candidates = [
                    item for item in candidates
                    if item not in left_and_candidates
                ]
    normal_filters = [item for item in filters if item not in candidates]
    or_cols = {item.col for item in candidates}
    if 'nhom_chu_ho_nu' in or_cols:
        normal_filters = [item for item in normal_filters if item.col != 'gioi_tinh']
    return (normal_filters, candidates)

def _mentioned_numeric_field(question: str) -> str | None:
    q_key = vn_name_key(question)
    matches = []
    for col, meta in NUMERIC_FIELD_CATALOG.items():
        aliases = meta.get('aliases', [])
        for alias in aliases:
            alias_key = vn_name_key(alias)
            if not alias_key:
                continue
            if re.search(f'\\b{re.escape(alias_key)}\\b', q_key):
                matches.append((len(alias_key), col))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]

def _numeric_filters(question: str) -> list[Filter]:
    q_raw = (question or "").lower()
    q_key = vn_name_key(question)
    if re.search(r'\b(?:trên|tren|dưới|duoi|lớn hơn|lon hon|nhỏ hơn|nho hon)\s+\d+(?:\.\d+)?\s*%', q_raw):
        return []
    col = _mentioned_numeric_field(question)
    shortage_dim = re.search(
        r'\b(?:it nhat|tu)\s+(\d+(?:\.\d+)?)\s+(?:chieu\s+)?thieu hut(?:\s+tro len)?\b',
        q_key,
    )
    if shortage_dim:
        value = float(shortage_dim.group(1))
        if value.is_integer():
            value = int(value)
        return [Filter("tong_chieu_thieu_hut", ">=", value)]

    # "trẻ dưới 6 tuổi" là nhóm tuổi, không phải điều kiện so_tre_em < 6.
    if col == "so_tre_em" and any(x in q_key for x in (
        "tre duoi 6", "tre em duoi 6", "duoi 6 tuoi",
    )):
        return []
    if not col:
        return []
    filters = []
    patterns = [('\\bbang\\s+(\\d+(?:\\.\\d+)?)\\b', '='), ('\\b=\\s*(\\d+(?:\\.\\d+)?)\\b', '='), ('\\btren\\s+(\\d+(?:\\.\\d+)?)\\b', '>'), ('\\blon hon\\s+(\\d+(?:\\.\\d+)?)\\b', '>'), ('\\bduoi\\s+(\\d+(?:\\.\\d+)?)\\b', '<'), ('\\bnho hon\\s+(\\d+(?:\\.\\d+)?)\\b', '<'), ('\\btu\\s+(\\d+(?:\\.\\d+)?)\\s+den\\s+(\\d+(?:\\.\\d+)?)\\b', 'BETWEEN')]
    for pattern, op in patterns:
        m = re.search(pattern, q_key)
        if not m:
            continue
        if op == 'BETWEEN':
            low = float(m.group(1))
            high = float(m.group(2))
            filters.append(Filter(col, '>=', low))
            filters.append(Filter(col, '<=', high))
        else:
            value = float(m.group(1))
            if value.is_integer():
                value = int(value)
            filters.append(Filter(col, op, value))
        break
    return filters

def _is_top_list_question(question: str | None) -> bool:
    q_key = vn_name_key(question or '')
    return re.search('\\btop\\s*\\d+\\b', q_key) is not None or re.search('\\b(?:lay|liet ke|danh sach|hien thi)\\s*\\d+\\s*(?:xa|huyen|dan toc|nhom|doi tuong|ket qua)\\b', q_key) is not None or re.search('\\b\\d+\\s*(?:xa|huyen|ho|dia ban|phuong|thi tran|dan toc|nhom|doi tuong|ket qua)\\s*(?:nao\\s*)?(?:co|nhieu|cao|lon|it|thap)', q_key) is not None or (re.search('\\b\\d+\\s*(?:xa|huyen|ho|dia ban|phuong|thi tran|dan toc|nhom|doi tuong|ket qua)\\s*(?:nao\\s*)?(?:dau|dau tien|hang dau)\\b', q_key) is not None) or ('nhom dan dau' in q_key)

def _ranking_position(question: str) -> int | None:
    q_key = vn_name_key(question)
    m = re.search('\\b(?:top|hang|thu|xep hang)\\s*(\\d+)\\b', q_key)
    if m:
        return max(1, int(m.group(1)))
    m = re.search('\\b(\\d+)\\s*(?:xa|huyen|ho|dia ban|phuong|thi tran|dan toc|nhom)\\s*nao\\b', q_key)
    if m:
        return max(1, int(m.group(1)))
    m = re.search('\\b(\\d+)\\s*(?:xa|huyen|ho|dia ban|phuong|thi tran|dan toc|nhom)\\s*(?:co|nhieu|cao|lon|it|thap)', q_key)
    if m:
        return max(1, int(m.group(1)))
    word_ranks = {'thu nhat': 1, 'dau tien': 1, 'thu nhi': 2, 'thu hai': 2, 'nhi': 2, 'thu ba': 3, 'thu bon': 4, 'thu tu': 4, 'thu nam': 5, 'thu sau': 6, 'thu bay': 7, 'thu tam': 8, 'thu chin': 9, 'thu muoi': 10}
    for phrase, rank in sorted(word_ranks.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(f'\\b{re.escape(phrase)}\\b', q_key):
            return rank
    return None

def _ranking_direction(question: str) -> str | None:
    q_key = vn_name_key(question)
    q_key = re.sub(
        r'\b(?:it nhat|tu)\s+\d+(?:\.\d+)?\s+(?:chieu\s+)?thieu hut(?:\s+tro len)?\b',
        ' ',
        q_key,
    )
    if (
        re.search(r'\b(?:it nhat|thap nhat|nho nhat|chot|bet|cuoi bang|cuoi cung)\b', q_key)
        or re.search(r'\b(?:it|thap|nho)\b.{0,80}\bnhat\b', q_key)
    ):
        return 'asc'

    if (
        re.search(r'\b(?:nhieu nhat|cao nhat|lon nhat|dong nhat|dung dau|dan dau|top)\b', q_key)
        or re.search(r'\b(?:nhieu|cao|lon|dong)\b.{0,80}\bnhat\b', q_key)
        or re.search(r'\b(?:hang|xep hang)\s+\d+\b', q_key)
    ):
        return 'desc'
    return None


def _asks_both_extremes(question: str | None) -> bool:
    """Detect questions asking for both max and min in one grouped result."""
    q_key = vn_name_key(question or "")
    highest = (
        any(x in q_key for x in ("cao nhat", "nhieu nhat", "lon nhat", "dung dau", "dan dau"))
        or re.search(r"\b(?:cao|nhieu|lon)\b.{0,80}\bnhat\b", q_key) is not None
    )
    lowest = (
        any(x in q_key for x in ("thap nhat", "it nhat", "nho nhat", "thap hon", "chot", "bet", "cuoi bang"))
        or re.search(r"\b(?:thap|it|nho)\b.{0,80}\bnhat\b", q_key) is not None
    )
    return bool(highest and lowest)

def _record_ranking_order(question: str) -> tuple[str, dict[str, str] | None, int | None]:
    q_key = vn_name_key(question)
    col = _mentioned_numeric_field(question)

    group_ranking_signal = any(x in q_key for x in (
        'huyen nao', 'xa nao', 'dan toc nao', 'nhom nao', 'loai nao',
        'dia ban nao', 'theo huyen', 'theo xa',
    ))
    if group_ranking_signal:
        return (col or '', None, None)

    if not col:
        return ('', None, None)

    wants_record = (
        any(x in q_key for x in (
            'chu ho nao', 'ho nao', 'chu ho co',
            'cac chu ho', 'nhung chu ho', 'nhung ho',
            'liet ke ho', 'danh sach ho',
        ))
        or re.search(r'\b(?:liet ke|danh sach|hien thi)\b.{0,30}\bho\b', q_key)
        or re.search(r'\b(?:chu ho|ho)\b.{0,50}\bnao\b', q_key)
        or re.search(r'\b\d{1,3}\s+ho\b.{0,80}\b(?:co|nhieu|it|cao|thap|lon|nho)\b', q_key)
    )

    if not wants_record:
        return (col, None, None)

    limit = None
    m = re.search(r'\b(?:liet ke|danh sach|hien thi)\s*(\d{1,3})\s*ho\b', q_key)
    if not m:
        m = re.search(r'\b(\d{1,3})\s*ho\b', q_key)
    if m:
        limit = max(1, min(int(m.group(1)), MAX_LIMIT))

    high_rank = (
        any(x in q_key for x in ('nhieu nhat', 'cao nhat', 'lon nhat', 'dong nhat'))
        or re.search(r'\b(?:nhieu|cao|lon|dong)\b.{0,80}\bnhat\b', q_key)
    )
    low_rank = (
        any(x in q_key for x in ('it nhat', 'thap nhat', 'nho nhat'))
        or re.search(r'\bit\b.{0,80}\bnhat\b', q_key)
        or re.search(r'\bthap\b.{0,80}\bnhat\b', q_key)
        or re.search(r'\bnho\b.{0,80}\bnhat\b', q_key)
    )

    if high_rank:
        return (col, {'col': col, 'direction': 'desc'}, limit or 1)
    if low_rank:
        return (col, {'col': col, 'direction': 'asc'}, limit or 1)

    return (col, None, limit)

def _same_filter_value(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return vn_name_key(a) == vn_name_key(b)
    return a == b

def _filter_matches(item: Filter, spec: tuple[str, str, object]) -> bool:
    col, op, value = spec
    return item.col == col and item.op == op and _same_filter_value(item.value, value)

def _dedupe_equivalent_filters(filters: list[Filter]) -> list[Filter]:
    result = list(filters)
    for rule in EQUIVALENT_FILTER_RULES:
        keep_spec = rule['keep']
        drop_specs = rule['drop']
        has_keep = any((_filter_matches(item, keep_spec) for item in result))
        if not has_keep:
                continue
        result = [item for item in result if not any((_filter_matches(item, drop_spec) for drop_spec in drop_specs))]
    return result

def _asks_all_social_deprivation_indicators(question: str | None) -> bool:
    q_key = vn_name_key(question or "")
    return (
        any(x in q_key for x in (
            "cac chieu thieu hut",
            "nhung chieu thieu hut",
            "cac chi so thieu hut",
            "nhung chi so thieu hut",
            "cac chi so dich vu xa hoi",
            "nhung chi so dich vu xa hoi",
        ))
        or (
            any(x in q_key for x in ("cac chi so", "nhung chi so"))
            and any(x in q_key for x in ("thieu hut", "dich vu xa hoi", "dvxh"))
        )
        or (
            any(x in q_key for x in ("cac chieu", "nhung chieu"))
            and any(x in q_key for x in ("thieu hut", "dich vu xa hoi", "dvxh"))
        )
    )


def _asks_ranked_social_deprivation_indicator(question: str | None) -> bool:
    q_key = vn_name_key(question or "")
    deprivation_signal = any(x in q_key for x in (
        "chi so thieu hut",
        "chi tieu thieu hut",
        "thieu hut dich vu xa hoi co ban",
        "thieu hut dvxhcb",
        "dvxhcb",
    ))
    ranking_signal = any(x in q_key for x in (
        "nhieu nhat", "cao nhat", "it nhat", "thap nhat",
        "lon nhat", "nho nhat", "dung dau",
    ))
    return deprivation_signal and ranking_signal


def _is_child_deficiency_indicator_question(question: str | None) -> bool:
    """Nhận diện câu hỏi về *chỉ tiêu thiếu hụt* của trẻ em.

    Giữ pattern hẹp: chỉ từ khóa trẻ em không đủ để chuyển sang nhóm te_th_*.
    """
    q_key = vn_name_key(question or "")
    child_context = re.search(r"\btre\s+(?:em|nho)\b", q_key) is not None
    if not child_context:
        return False

    deficiency_indicator_context = (
        any(x in q_key for x in (
            "thieu chi tieu",
            "chi tieu thieu",
            "thieu hut chi tieu",
            "thieu chi so",
            "chi so thieu",
            "thieu hut chi so",
            "thieu hut cua tre em",
            "thieu hut cua tre nho",
        ))
        or re.search(
            r"\bthieu(?:\s+hut)?\s+(?:cac\s+)?(?:chi\s+tieu|chi\s+so)(?:\s+nao)?\b",
            q_key,
        ) is not None
    )
    return deficiency_indicator_context


def _asks_child_deprivation_group(question: str | None) -> bool:
    q_key = vn_name_key(question or "")
    return _is_child_deficiency_indicator_question(question) or any(x in q_key for x in (
        "thieu hut tre em",
        "tre em thieu chi tieu",
        "tre em thieu chi so",
        "chi tieu tre em",
        "cac chi tieu thieu hut tre em",
    ))


def _is_child_count_record_ranking_question(question: str | None) -> bool:
    """Xếp hạng từng hộ theo số trẻ em, không lẫn với xếp hạng chỉ tiêu te_th_* ."""
    q_key = vn_name_key(question or "")
    if _is_child_deficiency_indicator_question(question):
        return False
    household_scope = any(x in q_key for x in ("ho ngheo", "ho can ngheo", "ho nao"))
    child_count_context = any(x in q_key for x in ("co tre em", "nhieu tre em", "it tre em"))
    ranking_context = _ranking_direction(question or "") is not None
    return household_scope and child_count_context and ranking_context


def _is_total_count_over_text_values(question: str, filters: list[Filter]) -> bool:
    """Narrow exception: count the union of A/B text values, do not group it."""
    q_key = vn_name_key(question or "")
    count_signal = any(x in q_key for x in ("co bao nhieu", "so luong", "tong so"))
    if not count_signal or not re.search(r"\bhoac\b", q_key):
        return False

    group_signals = (
        re.search(r"\btheo\b", q_key) is not None
        or any(x in q_key for x in (
            "phan bo", "co cau", "ty trong", "so sanh", "xep hang",
            "top", "bieu do tron",
        ))
    )
    if group_signals:
        return False

    return any(
        item.op == "IN"
        and isinstance(item.value, (list, tuple))
        and len(item.value) >= 2
        and all(isinstance(value, str) for value in item.value)
        and item.col not in {"nam", "huyen", "xa_phuong"}
        and item.col not in FLAG_COLUMNS
        for item in filters
    )

def _infer_group_by_from_question(question: str, filters: list[Filter] | None = None) -> list[str]:
    q = question.lower()
    q_key = vn_name_key(question)
    filters = filters or []

    has_huyen_filter = any(item.col == "huyen" for item in filters)

    # Cụm cụ thể phải thắng "dân tộc" chung.
    if any(x in q_key for x in ("theo dan toc tai cho", "theo dtts tai cho")):
        return ["dan_toc_tai_cho"]

    # Với top-N hộ theo một chỉ tiêu số, huyện/xã chỉ là phạm vi lọc.
    if re.search(r'\btop\s*\d+\s+ho\b', q_key) and _mentioned_numeric_field(question):
        return []

    if _asks_child_deprivation_group(question):
        return ["tre_em"]

    if _asks_all_social_deprivation_indicators(question) or _asks_ranked_social_deprivation_indicator(question):
        return ["chi_so"]

    wants_commune_inside_district = (
        any(x in q for x in ("xã nào", "những xã", "các xã", "từng xã", "theo xã", "top xã"))
        or any(x in q_key for x in ("xa nao", "nhung xa", "cac xa", "tung xa", "theo xa", "top xa"))
        or re.search(r'\btop\s*\d+\s*xa\b', q_key)
        or re.search(r'\b\d+\s*xa\b', q_key)
        or re.search(r'\bxa\b.{0,40}\bhuyen\b', q_key)
    )

    if has_huyen_filter and wants_commune_inside_district:
        return ["xa_phuong"]

    group_patterns = [
        (
            ("huyện", "huyen"),
            ["theo huyện", "từng huyện", "chia theo huyện", "mỗi huyện", "huyện nào", "các huyện", "xếp hạng huyện", "xếp hạng các huyện"],
            ["theo huyen", "tung huyen", "chia theo huyen", "moi huyen", "huyen nao", "cac huyen", "xep hang huyen", "xep hang cac huyen"],
            ["huyen"],
        ),
        (
            ("xã", "xa", "phường", "phuong", "thị trấn", "thi tran"),
            ["theo xã", "từng xã", "chia theo xã", "xã nào", "những xã", "các xã", "mỗi xã", "top xã"],
            ["theo xa", "tung xa", "chia theo xa", "xa nao", "nhung xa", "cac xa", "moi xa", "top xa"],
            ["xa_phuong"],
        ),
        (
            ("phân loại hộ", "phan loai ho", "phân loại", "phan loai"),
            ["theo phân loại hộ", "theo phân loại", "so sánh phân loại hộ"],
            ["theo phan loai ho", "theo phan loai", "so sanh phan loai ho"],
            ["phan_loai"],
        ),
        (
            ("dân tộc", "dan toc"),
            ["theo dân tộc", "dân tộc nào", "các dân tộc", "top dân tộc"],
            ["theo dan toc", "dan toc nao", "cac dan toc", "top dan toc"],
            ["dan_toc_chi_tiet"],
        ),
        (
            ("giới tính", "gioi tinh"),
            ["theo giới tính", "giới tính nào", "cơ cấu giới tính", "phân bố giới tính"],
            ["theo gioi tinh", "gioi tinh nao", "co cau gioi tinh", "phan bo gioi tinh"],
            ["gioi_tinh"],
        ),
        (
            ("học vấn", "hoc van", "trình độ", "trinh do"),
            [
                "theo học vấn",
                "học vấn",
                "học vấn chủ hộ",
                "trình độ học vấn",
                "trình độ học vấn chủ hộ",
                "phân bố học vấn",
                "thống kê học vấn",
            ],
            [
                "theo hoc van",
                "hoc van",
                "hoc van chu ho",
                "trinh do hoc van",
                "trinh do hoc van chu ho",
                "phan bo hoc van",
                "thong ke hoc van",
            ],
            ["trinh_do_hoc_van_chu_ho"],
        ),
        (
            ("sức khỏe", "suc khoe"),
            ["theo sức khỏe", "tình trạng sức khỏe"],
            ["theo suc khoe", "tinh trang suc khoe"],
            ["suc_khoe_chu_ho"],
        ),
        (
            ("nghề nghiệp", "nghe nghiep", "việc làm", "viec lam"),
            ["theo nghề nghiệp", "nghề nghiệp", "nghề chính", "việc làm chính"],
            ["theo nghe nghiep", "nghe nghiep", "nghe chinh", "viec lam chinh"],
            ["nghe_nghiep_chu_ho"],
        ),
        (
            ("nguồn nước", "nguon nuoc", "nước sinh hoạt", "nuoc sinh hoat"),
            [
                "theo nguồn nước",
                "theo nguồn nước sinh hoạt",
                "phân bố nguồn nước",
                "thống kê theo nguồn nước",
                "nguồn nước nào",
                "loại nước nào",
            ],
            [
                "theo nguon nuoc",
                "theo nguon nuoc sinh hoat",
                "phan bo nguon nuoc",
                "thong ke theo nguon nuoc",
                "nguon nuoc nao",
                "loai nuoc nao",
            ],
            ["nguon_nuoc"],
        ),
        (
            ("tình trạng nhà", "tinh trang nha", "nhà ở", "nha o"),
            ["theo tình trạng nhà", "tình trạng nhà ở", "phân bố nhà ở"],
            ["theo tinh trang nha", "tinh trang nha o", "phan bo nha o"],
            ["tinh_trang_nha"],
        ),
        (
            ("mức độ thiếu hụt", "muc do thieu hut"),
            ["theo mức độ thiếu hụt", "mức độ thiếu hụt"],
            ["theo muc do thieu hut", "muc do thieu hut"],
            ["muc_do_thieu_hut"],
        ),
        (
            ("nguyên nhân", "nguyen nhan"),
            ["nguyên nhân nghèo", "lý do nghèo", "vì sao nghèo"],
            ["nguyen nhan ngheo", "ly do ngheo", "vi sao ngheo"],
            ["nguyen_nhan"],
        ),
        (
            ("thiếu hụt", "thieu hut", "dvxhcb"),
            ["dịch vụ xã hội cơ bản", "chỉ số thiếu hụt", "thiếu hụt dvxhcb"],
            ["dich vu xa hoi co ban", "chi so thieu hut", "thieu hut dvxhcb"],
            ["chi_so"],
        ),
        (
            ("hỗ trợ", "ho tro", "loại hỗ trợ", "loai ho tro"),
            ["theo loại hỗ trợ", "thống kê hỗ trợ", "loại hỗ trợ nào"],
            ["theo loai ho tro", "thong ke ho tro", "loai ho tro nao"],
            ["ho_tro"],
        ),
    ]

    is_top_query = re.search(r"\btop\s*\d+\b", q_key) is not None
    is_rank_query = any(x in q_key for x in (
        "nao", "nhieu nhat", "it nhat", "cao nhat", "thap nhat",
        "lon nhat", "nho nhat", "dung dau", "dan dau", "xep hang"
    ))

    for subject_terms, raw_terms, key_terms, group_cols in group_patterns:
        raw_hit = any(term in q for term in raw_terms)
        key_hit = any(term in q_key for term in key_terms)

        top_hit = is_top_query and any(re.search(rf"\b{re.escape(vn_name_key(term))}\b", q_key) for term in subject_terms)
        rank_hit = is_rank_query and any(re.search(rf"\b{re.escape(vn_name_key(term))}\b", q_key) for term in subject_terms)

        if raw_hit or key_hit or top_hit or rank_hit:
            return group_cols
        
    table_signal = any(x in q_key for x in (
        'bang',
        'thong ke',
        'phan bo',
        'co cau',
        'kieu gi',
        'ra sao',
    ))

    if table_signal:
        for col, aliases in GROUP_BY_TERM_ALIASES.items():
            if any(vn_name_key(alias) in q_key for alias in aliases):
                return [col]

    return []


def _dimension_alias_catalog() -> dict[str, tuple[str, ...]]:
    """Gộp alias chiều phân tích từ các catalog hiện có."""
    aliases: dict[str, set[str]] = {
        col: {col.replace("_", " ")}
        for col in GROUP_COLUMNS
        if col not in {"nam", "tre_em"}
    }
    for col, label in TEXT_FILTER_LABELS.items():
        if col in aliases:
            aliases[col].add(str(label))
    for source in (GROUP_BY_TERM_ALIASES, DISTINCT_TEXT_GROUP_ALIASES):
        for col, terms in source.items():
            if col in aliases:
                aliases[col].update(str(term) for term in terms)
    for group_name, meta in FLAG_GROUPS.items():
        if group_name == "tre_em":
            # "trẻ em" còn là metric số lượng; chỉ group chỉ tiêu trẻ em khi
            # helper intent thiếu hụt trẻ em đã xác nhận ngữ cảnh.
            continue
        aliases.setdefault(group_name, set()).update((
            group_name.replace("_", " "),
            str(meta.get("label_col", group_name)).replace("_", " "),
        ))

    # Alias nghiệp vụ của các chiều tổng hợp không phải giá trị dữ liệu vật lý.
    aliases.setdefault("chi_so", set()).update((
        "chỉ số thiếu hụt", "chỉ tiêu thiếu hụt",
        "thiếu hụt dịch vụ xã hội cơ bản", "dịch vụ xã hội cơ bản", "DVXHCB",
    ))
    aliases.setdefault("nguyen_nhan", set()).update(("nguyên nhân", "lý do"))
    aliases.setdefault("huyen", set()).update(("huyện", "địa phương", "địa bàn"))
    aliases.setdefault("xa_phuong", set()).update(("xã/phường", "xã phường", "xã", "phường", "thị trấn"))

    return {
        col: tuple(dict.fromkeys(vn_name_key(term) for term in terms if vn_name_key(term)))
        for col, terms in aliases.items()
    }


def _dimension_value_count(
    dimension: str,
    filters: list[Filter],
    or_filters: list[Filter],
) -> int:
    if dimension in FLAG_GROUPS:
        value_cols = set(FLAG_GROUPS[dimension]["columns"].values())
        relevant = [item for item in [*filters, *or_filters] if item.col in value_cols]
        return len({item.col for item in relevant})

    relevant = [item for item in [*filters, *or_filters] if item.col == dimension]
    values: set[str] = set()
    for item in relevant:
        raw_values = item.value if item.op == "IN" and isinstance(item.value, (list, tuple, set)) else [item.value]
        values.update(repr(value) for value in raw_values)
    return len(values)


def _infer_catalog_dimension(
    question: str,
    filters: list[Filter] | None = None,
    or_filters: list[Filter] | None = None,
) -> str | None:
    """Resolve theo nguyên tắc: tên chiều / một giá trị / nhiều giá trị."""
    q_key = vn_name_key(question or "")
    filters = filters or []
    or_filters = or_filters or []
    alias_catalog = _dimension_alias_catalog()

    # Hai giá trị của nhóm nghèo tổng hợp phải thắng alias phụ "DTTS tại
    # chỗ" nằm bên trong một tên giá trị. Không áp dụng rộng cho mọi cột vì
    # câu đếm A hoặc B không đồng nghĩa với yêu cầu phân tổ.
    if _dimension_value_count("nhom_ngheo_tong_hop", filters, or_filters) >= 2:
        return "nhom_ngheo_tong_hop"

    mentioned: list[tuple[int, str]] = []
    for dimension, aliases in alias_catalog.items():
        matched_lengths = [
            len(alias)
            for alias in aliases
            if re.search(rf"\b{re.escape(alias)}\b", q_key)
        ]
        if matched_lengths:
            mentioned.append((max(matched_lengths), dimension))

    # Cụm dài/cụ thể thắng cụm rộng. Một giá trị cụ thể là filter; từ hai
    # giá trị trở lên vừa giới hạn tập so sánh vừa giữ chiều group_by.
    for _, dimension in sorted(mentioned, reverse=True):
        value_count = _dimension_value_count(dimension, filters, or_filters)
        if value_count == 1:
            return None
        return dimension

    # Câu có thể chỉ liệt kê nhiều giá trị mà không gọi tên chiều.
    multi_value_dimensions = [
        dimension
        for dimension in alias_catalog
        if _dimension_value_count(dimension, filters, or_filters) >= 2
    ]
    return multi_value_dimensions[0] if len(multi_value_dimensions) == 1 else None

def _is_multi_metric_table_question(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)

    if _movement_count_and_population_table_signal(question):
        return True

    if any(phrase in q_key for phrase in (
        "theo nhom doi tuong",
        "cac nhom doi tuong",
        "nhom doi tuong",
        "doi tuong ho ngheo",
        "nhom ho ngheo theo doi tuong",
        "nhom doi tuong ho ngheo",
    )):
        return True
    support_metric_count = 0
    if any(x in q_key for x in ("ho tro", "duoc ho tro", "nhan ho tro")):
        support_metric_count = sum(
            1 for _, aliases in SUPPORT_TERM_ALIASES.items()
            if any(re.search(rf"\b{re.escape(vn_name_key(alias))}\b", q_key) for alias in aliases)
        )
        if support_metric_count >= 2:
            return True

    if _looks_like_intersection_count_table(question):
        return False

    explicit_table_signal = any(x in q_key for x in (
        "bang",
        "lap bang",
    ))

    explicit_group_signal = any(x in q_key for x in (
        "theo huyen",
        "tung huyen",
        "theo xa",
        "tung xa",
        "theo dan toc",
        "theo gioi tinh",
    ))
    explicit_scope_signal = explicit_group_signal or any(x in q_key for x in ("toan tinh", "ca tinh"))

    multi_metric_signal = any(x in q_key for x in (
        "gom",
        "bao gom",
        "cac chi tieu",
        "nhieu chi tieu",
    ))

    has_metric_list_shape = (
        ":" in question
        or "," in question
        or "gồm" in q
        or "bao gồm" in q
        or "gom" in q_key
        or "bao gom" in q_key
    )

    metric_cols = _multi_metric_filter_cols(question)
    metric_count = len(metric_cols) + len(_multi_numeric_metric_cols(question)) + support_metric_count

    wants_total = any(x in q_key for x in (
        "tong ho",
        "tong ho ngheo",
        "tong ho can ngheo",
        "tong ho khong ngheo",
    ))

    if wants_total:
        metric_count += 1

    return (
        (explicit_table_signal or explicit_scope_signal)
        and (multi_metric_signal or has_metric_list_shape)
        and metric_count >= 2
    )

def _ratio_target_from_question(question: str, filters: list[Filter]) -> str | None:
    q_key = vn_name_key(question)
    classification_ratio = re.search(
        r"\bty le\s+(?:so\s+)?ho\s+(?:ngheo|can ngheo|khong ngheo)\b",
        q_key,
    )
    matches: list[tuple[int, str]] = []

    for col, meta in FEATURE_CATALOG.items():
        aliases = []
        label = meta.get("label")
        if label:
            aliases.append(label)
        aliases.extend(meta.get("aliases", []))

        for alias in aliases:
            alias_key = vn_name_key(alias)
            if alias_key and re.search(rf"\b{re.escape(alias_key)}\b", q_key):
                matches.append((len(alias_key), col))

    conditional_classification_share = (
        classification_ratio
        and re.search(r"\b(?:tren|so voi)\s+tong(?:\s+so)?\s+ho\s+co\b", q_key)
        is not None
    )

    # "Tỷ lệ hộ cận nghèo trên tổng số hộ có ..." thì target chính là
    # phân loại hộ; các đặc trưng phía sau là điều kiện mẫu số/tử số.
    if conditional_classification_share:
        return "phan_loai"

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    # Text categorical cụ thể là target tử số; phân loại hộ chỉ là scope nền.
    text_ratio_cols = {
        "bien_dong_dau_ky",
        "tinh_trang_nha",
        "nguon_nuoc",
        "suc_khoe_chu_ho",
        "trinh_do_hoc_van_chu_ho",
        "dan_toc_chi_tiet",
        "gioi_tinh",
    }
    for item in filters:
        if item.col in text_ratio_cols and item.op in {"=", "IN"}:
            return item.col

    # Nếu không có chỉ tiêu/feature cụ thể đứng sau nhóm hộ thì đây mới là
    # tỷ trọng phân loại hộ trên tổng hộ rà soát trong cùng phạm vi.
    if classification_ratio:
        return "phan_loai"

    for item in filters:
        if item.op == "=" and item.value in (0, 1) and item.col in FLAG_COLUMNS:
            return item.col
    return None


def _is_shared_total_composition(question: str, group_by: list[str]) -> bool:
    """Nhận diện các lát group cùng chia sẻ một tổng, không phải ratio riêng từng group."""
    if not group_by:
        return False
    q_key = vn_name_key(question or "")
    composition_signal = any(x in q_key for x in (
        "co cau", "phan bo", "ty trong", "ti trong",
    ))
    shared_total_signal = re.search(
        r"\b(?:tren|trong)\s+tong(?:\s+so)?\s+ho\s+(?:ngheo|can ngheo|khong ngheo)\b",
        q_key,
    ) is not None
    return composition_signal or shared_total_signal

def _is_conditional_classification_ratio(question: str, ratio_target: str | None) -> bool:
    """Tỷ lệ một phân loại hộ trên mẫu số có điều kiện đặc trưng.

    Ví dụ: "Tỷ lệ số hộ cận nghèo trên tổng số hộ có giới tính nam, thiếu vốn".
    Ở đây phan_loai là tử số; các feature là phạm vi mẫu số, không phải target tỷ lệ.
    """
    if ratio_target != "phan_loai":
        return False
    q_key = vn_name_key(question or "")
    return (
        re.search(r"\bty le\s+(?:so\s+)?ho\s+(?:ngheo|can ngheo|khong ngheo)\b", q_key)
        is not None
        and re.search(r"\b(?:tren|so voi)\s+tong(?:\s+so)?\s+ho\s+co\b", q_key)
        is not None
    )


def _build_explicit_ratio_filters(
    question: str,
    metric_out: str | None,
    target_col_out: str | None,
    filters: list[Filter],
) -> tuple[str | None, list[Filter], list[Filter]]:
    """Tạo numerator/denominator rõ ràng cho các mẫu tỷ lệ dễ nhập nhằng."""
    if metric_out != "ratio":
        return None, [], []

    if _is_conditional_classification_ratio(question, target_col_out):
        numerator_filters = list(filters)
        denominator_filters = [item for item in filters if item.col != "phan_loai"]
        return "per_group", numerator_filters, denominator_filters

    return None, [], []

def _is_dtts_threshold_income_question(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return (
        (
            "dan toc thieu so tai cho" in q_key
            or "dtts tai cho" in q_key
            or "dan toc tai cho" in q_key
        )
        and "thu nhap binh quan" in q_key
        and "ho ngheo" in q_key
        and re.search(r'\btren\s+\d+(?:\.\d+)?\b', q_key) is not None
    )

def _default_poor_for_feature_stats(question: str, filters: list[Filter], task: str | None) -> list[Filter]:
    # Không default câu hỏi đặc trưng/thống kê về "Hộ nghèo".
    # phan_loai chỉ được thêm khi người dùng nêu rõ phân loại hộ.
    return filters


def _upsert_exact_filter(filters: list[Filter], col: str, value: Any) -> list[Filter]:
    """Giữ một filter '=' duy nhất cho col, dùng cho các diễn đạt đảo nghĩa rõ ràng."""
    cleaned = [item for item in filters if not (item.col == col and item.op == '=')]
    cleaned.append(Filter(col, '=', value))
    return cleaned


def _has_key_phrase(q_key: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(phrase)}\b", q_key) for phrase in phrases)


def _apply_explicit_presence_filters(question: str, filters: list[Filter]) -> list[Filter]:
    """Chuẩn hóa các câu 'có X' khi cột DB đang lưu dạng 'thiếu X'.

    Ví dụ: th_bhyt=1 nghĩa là thiếu BHYT, nên 'có BHYT' phải là th_bhyt=0.
    Hàm này không hardcode theo một câu hỏi cụ thể; nó xử lý pattern đảo nghĩa
    cho mọi câu có điều kiện kết hợp / tỷ lệ / danh sách.
    """
    q_key = vn_name_key(question or '')

    positive_presence_rules = {
        'th_bhyt': (
            ('co bhyt', 'co bao hiem y te', 'khong thieu bhyt', 'khong thieu bao hiem y te'),
            ('thieu bhyt', 'thieu bao hiem y te', 'khong co bhyt', 'khong co bao hiem y te', 'chua co bhyt', 'chua co bao hiem y te'),
        ),
        'th_bhxh': (
            ('co bhxh', 'co bao hiem xa hoi', 'khong thieu bhxh', 'khong thieu bao hiem xa hoi'),
            ('thieu bhxh', 'thieu bao hiem xa hoi', 'khong co bhxh', 'khong co bao hiem xa hoi', 'chua co bhxh', 'chua co bao hiem xa hoi'),
        ),
        'th_nuoc_sach': (
            ('co nuoc sach', 'co nuoc sinh hoat hop ve sinh', 'khong thieu nuoc sach'),
            ('thieu nuoc sach', 'khong co nuoc sach', 'chua co nuoc sach'),
        ),
    }

    for col, (positive_phrases, negative_phrases) in positive_presence_rules.items():
        # Nếu câu có cả dạng phủ định rõ ràng như 'không có BHYT' thì không đảo về 0.
        if _has_key_phrase(q_key, positive_phrases) and not _has_key_phrase(q_key, negative_phrases):
            filters = _upsert_exact_filter(filters, col, 0)
    # Đảo nghĩa tổng quát cho các cột dạng "thiếu ..."
    # Ví dụ: "không thiếu kỹ năng lao động" => nn_thieu_ky_nang = 0
    #        "không thiếu vốn" => nn_thieu_von = 0
    #        "không thiếu BHXH" => th_bhxh = 0
    absence_cols = [
        col for col, meta in FEATURE_CATALOG.items()
        if meta.get("kind") == "flag"
        and (col.startswith("th_") or col.startswith("nn_thieu_"))
    ]

    for col in absence_cols:
        meta = FEATURE_CATALOG.get(col, {})
        terms = []

        label = meta.get("label")
        if label:
            terms.append(label)

        terms.extend(meta.get("aliases", []))

        negative_terms = []
        for term in terms:
            term_key = vn_name_key(str(term))
            if not term_key:
                continue

            if term_key.startswith("thieu "):
                negative_terms.append(f"khong {term_key}")
                negative_terms.append(f"khong bi {term_key}")

        if negative_terms and _has_key_phrase(q_key, tuple(negative_terms)):
            filters = _upsert_exact_filter(filters, col, 0)

    # Cột hỗ trợ lưu 1 = được hỗ trợ; phủ định rõ phải thắng alias dương.
    for col, aliases in SUPPORT_TERM_ALIASES.items():
        alias_keys = {vn_name_key(str(alias)) for alias in aliases}
        alias_keys.update(
            vn_name_key(str(alias)).removeprefix('duoc ').removeprefix('nhan ')
            for alias in aliases
        )
        negative_patterns = tuple(
            phrase
            for alias in alias_keys
            if alias
            for phrase in (
                f'khong duoc ho tro {alias}', f'chua duoc ho tro {alias}',
                f'khong nhan ho tro {alias}', f'chua nhan ho tro {alias}',
            )
        )
        if negative_patterns and _has_key_phrase(q_key, negative_patterns):
            filters = _upsert_exact_filter(filters, col, 0)

    explicit_gender = _explicit_gender_value(question)
    if explicit_gender is not None:
        filters = _upsert_exact_filter(filters, 'gioi_tinh', explicit_gender)

    return filters

def extract_rule_plan(question: str) -> dict[str, Any]:
    filters = _base_filters(question) + _feature_filters(question)
    filters = _fix_child_bhyt_overlap(question, filters)
    filters = _apply_explicit_presence_filters(question, filters)
    filters.extend(_numeric_filters(question))

    filters = _sanitize_filters_by_context(question, filters)
    filters = _collapse_or_same_column_filters(question, filters)
    filters = _suppress_class_filters_for_movement_context(question, filters)
    filters = _sanitize_filters_by_context(question, filters)
    filters = _apply_specific_filter_overrides(filters)
    filters, or_filters = _split_or_feature_filters(question, filters)
    filters = _dedupe_equivalent_filters(filters)

    q = question.lower()
    q_key = vn_name_key(question)
    all_social_deprivation_indicators = (
        _asks_all_social_deprivation_indicators(question)
        or _asks_ranked_social_deprivation_indicator(question)
    )
    child_deprivation_group = _asks_child_deprivation_group(question)
    distinct_group_col = _distinct_group_col_from_question(question)
    local_ethnicity_group_signal = any(
        x in q_key for x in ("theo dan toc tai cho", "theo dtts tai cho")
    )

    group_by = []
    task = None
    order_by = None
    limit = None

    classification_structure_signal = (
        any(x in q_key for x in ("co cau", "ty trong", "phan bo"))
        and "ho ngheo" in q_key
        and ("ho can ngheo" in q_key or "can ngheo" in q_key)
        and ("ho khong ngheo" in q_key or "khong ngheo" in q_key)
    )

    if classification_structure_signal:
        filters = [item for item in filters if item.col != "phan_loai"]
        filters.append(Filter(
            "phan_loai",
            "IN",
            ["Hộ nghèo", "Hộ cận nghèo", "Hộ không nghèo"],
        ))
        task = "group_aggregate"
        group_by = ["phan_loai"]

    has_nha_tam = 'nha tam' in q_key or 'tam bo' in q_key
    has_don_so = 'nha don so' in q_key or 'don so' in q_key
    has_khong_co_nha = 'khong co nha' in q_key
    has_house_catalog_filter = any(item.col == 'tinh_trang_nha' for item in filters)
    if (has_nha_tam or has_don_so or has_khong_co_nha) and not has_house_catalog_filter:
        house_values = []
        if has_nha_tam:
            house_values.append('Nhà tạm')
        if has_don_so:
            house_values.append('Nhà đơn sơ')
        if has_khong_co_nha:
            house_values.append('Không có nhà')
        filters = [f for f in filters if f.col != 'tinh_trang_nha']
        if len(house_values) == 1:
            filters.append(Filter('tinh_trang_nha', '=', house_values[0]))
        else:
            filters.append(Filter('tinh_trang_nha', 'IN', list(dict.fromkeys(house_values))))
    elif (not has_house_catalog_filter) and ('nha o kem' in q_key or 'nha kem' in q_key or 'nha xau' in q_key or ('nha o khong dam bao' in q_key) or ('nha khong dam bao' in q_key) or ('khong vung chac' in q_key)):
        filters = [f for f in filters if f.col != 'tinh_trang_nha']
        filters.append(Filter('tinh_trang_nha', 'IN', ['Nhà tạm', 'Nhà đơn sơ']))
    hoc_van_value = None
    if any((x in q_key for x in ('chua biet doc viet', 'chua biet doc', 'chua biet viet', 'mu chu'))):
        hoc_van_value = 'Chưa biết đọc/viết'
    elif any((x in q_key for x in ('tot nghiep thpt', 'tn thpt', 'trung hoc pho thong', 'bang thpt'))):
        hoc_van_value = 'Tốt nghiệp THPT'
    elif any((x in q_key for x in ('dai hoc tro len', 'bang dai hoc', 'co bang dai hoc', 'dai hoc', 'cao hoc'))):
        hoc_van_value = 'Đại học trở lên'
    elif any((x in q_key for x in ('tot nghiep thcs', 'tn thcs', 'trung hoc co so'))):
        hoc_van_value = 'Tốt nghiệp THCS'
    elif any((x in q_key for x in ('chua tot nghiep tieu hoc', 'chua tn tieu hoc'))):
        hoc_van_value = 'Chưa tốt nghiệp tiểu học'
    elif any((x in q_key for x in ('tot nghiep tieu hoc', 'tn tieu hoc'))):
        hoc_van_value = 'Tốt nghiệp tiểu học'
    has_hoc_van_in_filter = any((f.col == 'trinh_do_hoc_van_chu_ho' and f.op == 'IN' for f in filters))
    if hoc_van_value and (not has_hoc_van_in_filter):
        filters = [f for f in filters if f.col != 'trinh_do_hoc_van_chu_ho']
        filters.append(Filter('trinh_do_hoc_van_chu_ho', '=', hoc_van_value))
    name = _lookup_name(question)
    avg_info = _extract_avg_metric(question)
    sum_info = _extract_sum_metric(question)
    if task is None and (_detect_multi_metric_table(question) or _is_multi_metric_table_question(question)):
        task = 'multi_metric_table'
    if task == "multi_metric_table":
        name = None
    list_record_signal = any((x in q for x in ('liệt kê', 'danh sách', 'những hộ nào', 'các hộ nào', 'cho tôi thông tin', 'thông tin hộ', 'chi tiết hộ', 'vài hộ'))) or any((x in q_key for x in ('liet ke', 'danh sach', 'nhung ho nao', 'cac ho nao', 'cho toi thong tin', 'thong tin ho', 'chi tiet ho', 'vai ho'))) or re.search(r'\b(?:lay\s*)?\d{1,3}\s*dong\b', q_key) is not None
    # "thống kê theo huyện/xã" là thống kê nhóm, không phải liệt kê từng hộ.
    stat_count_signal = (
        ("thống kê hộ" in q and not any(x in q for x in ("liệt kê", "danh sách", "chi tiết", "thông tin hộ")))
        or ("thong ke ho" in q_key and not any(x in q_key for x in ("liet ke", "danh sach", "chi tiet", "thong tin ho")))
    )
    if stat_count_signal:
        list_record_signal = False
    stat_group_signal = (
        any(x in q for x in ("thống kê theo huyện", "thống kê theo xã", "theo huyện", "theo xã"))
        or any(x in q_key for x in ("thong ke theo huyen", "thong ke theo xa", "theo huyen", "theo xa"))
        or re.search(r"\b\d{1,3}\s+(?:xa|huyen|phuong|thi tran)\b", q_key) is not None
        or re.search(r"\b(?:top|lay|liet ke|danh sach)\s*\d{1,3}\s+(?:xa|huyen|phuong|thi tran)\b", q_key) is not None
    )
    
    explicit_list_signal = any(x in q for x in ("chi tiết hộ", "thông tin hộ", "vài hộ")) or any(x in q_key for x in ("chi tiet ho", "thong tin ho", "vai ho")) or re.search(r"\b(?:lay\s*)?\d{1,3}\s*dong\b", q_key) is not None or ((any(x in q for x in ("liệt kê", "danh sách")) or any(x in q_key for x in ("liet ke", "danh sach"))) and re.search(r"\b(?:ho|chu ho)\b", q_key) is not None and re.search(r"\b(?:xa|huyen|phuong|thi tran)\b", q_key) is None)

    if stat_group_signal and not explicit_list_signal:
        list_record_signal = False
    count_question_signal = any((x in q for x in ('bao nhiêu', 'số lượng', 'tổng số', 'có mấy', 'số hộ', 'tổng hộ', 'tỷ lệ', 'tỷ trọng', 'phần trăm'))) or any((x in q_key for x in ('bao nhieu', 'so luong', 'tong so', 'co may', 'so ho', 'tong ho', 'ty le', 'ty trong', 'phan tram')))
    numeric_col, numeric_order, numeric_limit = _record_ranking_order(question)
    group_stat_signal = bool(_infer_group_by_from_question(question, filters))

    child_count_record_ranking = _is_child_count_record_ranking_question(question)
    if child_count_record_ranking and numeric_col:
        numeric_order = {
            "col": numeric_col,
            "direction": _ranking_direction(question) or "desc",
        }
        numeric_limit = 1
    record_numeric_signal = (
        numeric_col
        and not group_stat_signal
        and (
            child_count_record_ranking
            or numeric_order is not None
            or numeric_limit is not None
            or any(x in q_key for x in (
                "chu ho nao", "ho nao", "chu ho co",
                "cac chu ho", "nhung chu ho", "nhung ho",
                "liet ke ho", "danh sach ho",
            ))
            or re.search(r"\btop\s*\d+\s+ho\b", q_key) is not None
            or re.search(r"\b\d{1,3}\s+ho\b.{0,80}\b(?:co|nhieu|it|cao|thap|lon|nho)\b", q_key) is not None
        )
    )

    if task is None and record_numeric_signal:
        task = "list_records"
    group_topic_signal = any(x in q_key for x in (
        "hoc van",
        "trinh do hoc van",
        "suc khoe",
        "nghe nghiep",
        "tinh trang nha",
        "muc do thieu hut",
    ))

    if (
        not list_record_signal
        and "chủ hộ" in q
        and "thống kê" in q
        and not count_question_signal
        and not group_topic_signal
    ):
        list_record_signal = True
    lookup_person_signal = bool(name) and (
        any(x in q for x in (
            'tra cứu', 'tra hộ', 'tìm chủ hộ', 'tìm giúp chủ hộ',
            'chủ hộ tên', 'thông tin hộ', 'thông tin cơ bản',
            'cho biết thông tin', 'chi tiết hộ', 'cho biết hộ',
            'xem hộ', 'kiểm tra hộ'
        ))
        or any(x in q_key for x in (
            'tra cuu', 'tra ho', 'tim chu ho', 'tim giup chu ho',
            'chu ho ten', 'thong tin ho', 'thong tin co ban',
            'cho biet thong tin', 'chi tiet ho', 'cho biet ho',
            'xem ho', 'kiem tra ho',
            'thuoc xa nao', 'o xa nao', 'nha loai gi',
            'nha o', 'dan toc'
        ))
    )
    if distinct_group_col:
        list_record_signal = False
        filters = [item for item in filters if item.col != distinct_group_col]
        task = 'group_aggregate'
        group_by = [distinct_group_col]
    if local_ethnicity_group_signal:
        list_record_signal = False
        filters = [item for item in filters if item.col != 'dan_toc_tai_cho']
        task = 'group_aggregate'
        group_by = ['dan_toc_tai_cho']
    if child_deprivation_group:
        child_overlap_cols = {
            "co_tre_em",
            "te_th_bhyt", "te_th_dinh_duong", "te_th_di_hoc",
            "th_bhyt", "th_dinh_duong", "th_di_hoc_tre_em",
        }
        filters = [item for item in filters if item.col not in child_overlap_cols]
        list_record_signal = False
        task = "group_aggregate"
        group_by = ["tre_em"]
    if task is None and list_record_signal:
        task = 'list_records'

    if lookup_person_signal and task in {None, 'list_records'}:
        task = 'lookup_person'

    years_in_question = sorted(set((int(y) for y in re.findall('\\b20\\d{2}\\b', q))))
    compare_signal = any((x in q for x in ('so sánh', 'đối chiếu', 'biến động', 'chênh lệch'))) or any((x in q_key for x in ('so sanh', 'doi chieu', 'bien dong', 'chenh lech'))) or (any((x in q for x in ('tăng', 'giảm'))) or any((x in q_key for x in ('tang', 'giam')))) or (len(years_in_question) >= 2)

    if compare_signal and len(years_in_question) >= 2 and detect_ratio_intent(question):
        # Tỷ lệ qua nhiều năm là group_aggregate ratio theo chiều thời gian,
        # không phải compare_years count_households.
        task = 'group_aggregate'
        filters = [item for item in filters if item.col != 'nam']
        filters.append(Filter('nam', 'IN', years_in_question))

        inferred_groups = [
            col for col in _infer_group_by_from_question(question, filters)
            if col != 'nam'
        ]
        compare_dimension = (
            'chi_so'
            if all_social_deprivation_indicators
            else _infer_catalog_dimension(question, filters, or_filters)
        )
        if compare_dimension and compare_dimension != 'nam' and compare_dimension not in inferred_groups:
            inferred_groups.append(compare_dimension)

        group_by = list(dict.fromkeys([*inferred_groups, 'nam']))
        if group_by == ['nam'] and any(x in q_key for x in ('theo huyen', 'tung huyen', 'huyen nao')):
            group_by = ['huyen', 'nam']
        limit = None

    elif compare_signal and len(years_in_question) >= 2:
        task = 'compare_years'
        filters = [item for item in filters if item.col != 'nam']
        filters.append(Filter('nam', 'IN', years_in_question))
        compare_dimension = (
            'chi_so'
            if all_social_deprivation_indicators
            else _infer_catalog_dimension(question, filters, or_filters)
        )
        group_by = [compare_dimension, 'nam'] if compare_dimension else ['nam']
        if any(x in q_key for x in ("huyen nao", "xa nao", "dia ban nao")) and any(x in q_key for x in (
            "giam manh nhat", "giam nhieu nhat", "tang manh nhat", "tang nhieu nhat",
            "giam", "tang",
        )):
            limit = 1

    classification_values = next(
        (
            list(item.value)
            for item in filters
            if item.col == "phan_loai" and item.op == "IN" and isinstance(item.value, (list, tuple))
        ),
        [],
    )
    movement_values_for_group = _filter_values_for_col(filters, "bien_dong_dau_ky")
    if (
        len(movement_values_for_group) >= 2
        and len(years_in_question) <= 1
        and any(x in q_key for x in (
            "so sanh", "giua", "nhom nao", "nhieu nhat", "chenh", "co phai", "phai la"
        ))
    ):
        task = "group_aggregate"
        group_by = ["bien_dong_dau_ky"]

    classification_comparison = (
        compare_signal
        and len(years_in_question) <= 1
        and len(classification_values) >= 2
        and not movement_values_for_group
    )
    if classification_comparison:
        task = "group_aggregate"
        group_by = ["phan_loai"]

    # Tỷ lệ một phân loại hộ qua nhiều năm là tỷ lệ phân loại / tổng hộ rà
    # soát theo từng năm, không phải compare_years của số lượng tuyệt đối.
    classification_ratio_over_time = (
        len(years_in_question) >= 2
        and re.search(r'\bty le\s+ho\s+(?:ngheo|can ngheo|khong ngheo)\b', q_key)
        is not None
    )
    if classification_ratio_over_time:
        task = 'group_aggregate'
        group_by = ['nam']
    summary_signal = any(x in q for x in ('tổng quan', 'tóm tắt', 'báo cáo nhanh', 'khái quát', 'summary', 'tổng kết', 'bức tranh chung', 'thông tin chung', 'tóm lược'))

    if task is None and summary_signal:
        task = 'summary'
        filters = [item for item in filters if item.col != 'phan_loai']
    if task not in {'list_records', 'lookup_person', 'summary'}:
        if any((x in q for x in ('theo năm', 'từng năm', 'theo từng năm', 'qua các năm'))) or any((x in q_key for x in ('theo nam', 'tung nam', 'theo tung nam', 'qua cac nam'))):
            if not (task == 'compare_years' and all_social_deprivation_indicators):
                existing_compare_groups = (
                    [col for col in group_by if col != 'nam']
                    if task == 'compare_years'
                    else []
                )
                catalog_dimension = _infer_catalog_dimension(question, filters, or_filters)
                if catalog_dimension and catalog_dimension != 'nam':
                    existing_compare_groups.append(catalog_dimension)
                series_groups = [
                    item.col for item in filters
                    if item.col in {'huyen', 'phan_loai'}
                    and item.op == 'IN'
                    and isinstance(item.value, (list, tuple))
                    and len(item.value) > 1
                ]
                group_by = list(dict.fromkeys([*existing_compare_groups, *series_groups, 'nam']))
        else:
            inferred_group_by = _infer_group_by_from_question(question, filters)
            if not inferred_group_by:
                catalog_dimension = _infer_catalog_dimension(question, filters, or_filters)
                if catalog_dimension:
                    inferred_group_by = [catalog_dimension]

            if inferred_group_by:
                if task == "compare_years":
                    inferred_no_year = [col for col in inferred_group_by if col != "nam"]
                    if inferred_no_year:
                        group_by = list(dict.fromkeys([*inferred_no_year, "nam"]))
                elif task not in {"list_records", "lookup_person", "multi_metric_table"}:
                    # Nếu nhánh tỷ lệ + nhiều năm đã tạo group_by có nam, không
                    # để inference theo câu hỏi ghi đè mất chiều thời gian.
                    if not (task == "group_aggregate" and "nam" in group_by):
                        task = "group_aggregate"
                        if classification_comparison and group_by:
                            # Ví dụ: "so sánh hộ nghèo và hộ cận nghèo theo huyện"
                            # phải giữ cả huyen + phan_loai, không để inference ghi đè mất phan_loai.
                            group_by = list(dict.fromkeys([*inferred_group_by, *group_by]))
                        else:
                            group_by = inferred_group_by

            ranking_signal = (
                re.search(r'\btop\s*\d+\b', q_key) is not None
                or any(x in q_key for x in (
                    'huyen nao',
                    'cho nao',
                    'dia ban nao',
                    'nhieu nhat',
                    'it nhat',
                    'cao nhat',
                    'thap nhat',
                    'dung dau',
                    'dan dau',
                    'cuoi bang',
                    'xep hang',
                    'may huyen',
                ))
            )

            explicit_non_huyen_group = any(x in q_key for x in (
                'xa nao',
                'xa co',
                'may xa',
                'top xa',
                'theo xa',
                'tung xa',
                'cac xa',
                'nhung xa',
                'phuong nao',
                'thi tran nao',
                'dan toc nao',
                'theo dan toc',
                'theo gioi tinh',
                'theo hoc van',
                'theo suc khoe',
                'theo nghe nghiep',
                'theo tinh trang nha',
            ))

            if ranking_signal and not group_by and any(x in q_key for x in ('top xa', 'xa co', 'may xa', 'cac xa', 'nhung xa')):
                group_by = ['xa_phuong']
            if ranking_signal and not group_by and not explicit_non_huyen_group:
                group_by = ['huyen']
    if task not in {'list_records', 'lookup_person', 'summary'}:
        is_dtts_question = 'dân tộc thiểu số' in q or 'dtts' in q_key or 'dan toc thieu so' in q_key
        has_specific_ethnicity_filter = any((item.col == 'dan_toc_chi_tiet' for item in filters))
        if not local_ethnicity_group_signal and not is_dtts_question and (not has_specific_ethnicity_filter) and ('dân tộc' in q or 'dan toc' in q_key) and ('dan_toc_chi_tiet' not in group_by):
            group_by.append('dan_toc_chi_tiet')
    if task == 'multi_metric_table':
        filters = [
            item for item in filters
            if not (
                item.col in {"huyen", "xa_phuong"}
                and str(item.value).strip().lower() in {"huyện a", "huyen a", "xã a", "xa a"}
            )
        ]

        group_object_metrics = any(phrase in q_key for phrase in (
            "theo nhom doi tuong",
            "cac nhom doi tuong",
            "nhom doi tuong",
            "doi tuong ho ngheo",
            "nhom ho ngheo theo doi tuong",
            "nhom doi tuong ho ngheo",
        ))
        support_context = any(x in q_key for x in ("ho tro", "duoc ho tro", "nhan ho tro"))
        generic_support_metrics = _is_general_policy_support_metrics_question(question)
        support_metric_cols = set()
        if support_context:
            support_metric_cols = {
                col for col, aliases in SUPPORT_TERM_ALIASES.items()
                if any(re.search(rf"\b{re.escape(vn_name_key(alias))}\b", q_key) for alias in aliases)
            }
        support_multi_metrics = support_context and (
            len(support_metric_cols) >= 2 or generic_support_metrics
        )
        if group_object_metrics or support_multi_metrics:
            # "Nhóm đối tượng" là một bộ cột cờ chồng lấn, không phải một cột
            # phân tổ vật lý. Trả một hàng nhiều metric thay vì giả thành tổng hộ.
            # Câu liệt kê nhiều nội dung hỗ trợ cũng là nhiều metric riêng,
            # không phải mặc định phân tổ theo huyện hay điều kiện AND giao.
            group_by = []
        elif not group_by:
            if any((x in q for x in ('theo xã', 'từng xã'))) or any((x in q_key for x in ('theo xa', 'tung xa'))):
                group_by = ['xa_phuong']
            elif any((x in q for x in ('theo huyện', 'từng huyện'))) or any((x in q_key for x in ('theo huyen', 'tung huyen'))):
                group_by = ['huyen']
            elif any(x in q_key for x in ('toan tinh', 'ca tinh')):
                group_by = []
            else:
                group_by = ['huyen']

        metric_filter_cols = _multi_metric_filter_cols(question)

        metric_filter_cols = metric_filter_cols | support_metric_cols
        filter_removal_cols = _expand_overlap_metric_filter_cols(metric_filter_cols)

        # Trong câu multi-metric, các cột metric không phải điều kiện WHERE.
        # Ví dụ: thiếu BHYT, thiếu BHXH, có trẻ em là các cột đếm riêng,
        # không phải AND th_bhyt=1 AND th_bhxh=1 AND co_tre_em=1.
        filters = [item for item in filters if item.col not in filter_removal_cols]
    if task not in {'list_records', 'lookup_person', 'summary'} and ('mức độ thiếu hụt' in q or 'mức thiếu hụt' in q or 'muc do thieu hut' in q_key or ('muc thieu hut' in q_key) or ('gom' in q_key and 'thieu hut' in q_key)):
        if not avg_info:
            group_by = ['muc_do_thieu_hut', 'nam'] if task == 'compare_years' else ['muc_do_thieu_hut']
    if _is_total_count_over_text_values(question, filters):
        task = 'aggregate'
        group_by = []
    if group_by and task not in {'compare_years', 'list_records', 'lookup_person', 'summary', 'multi_metric_table'}:
        task = 'group_aggregate'
    if task is None:
        task = 'aggregate'
    top = re.search('(?:top|hạng|xếp hạng)\\s*(\\d+)', q)
    if not top:
        top = re.search('(?:liệt kê|danh sách|hiển thị|show)\\s*(\\d+)\\s*(?:hộ|dòng|bản ghi|kết quả)', q)
    if not top:
        top = re.search('(\\d+)\\s*(?:hộ|dòng|bản ghi|kết quả)\\s*(?:đầu tiên|đầu|trước tiên)', q)
    if not top:
        top = re.search('(?:lấy|lay)\\s*(\\d+)\\s*(?:xã|xa|huyện|huyen|dân tộc|dan toc|nhóm|nhom|kết quả|ket qua)\\s*(?:đầu|dau|đầu tiên|dau tien)', q_key)
    if not top:
        top = re.search('\\b(\\d+)\\s*(?:xã|xa|huyện|huyen|dân tộc|dan toc|nhóm|nhom)\\s*(?:nào|nao)?\\s*(?:có|co)?\\s*(?:nhiều|nhieu|cao|lớn|lon|ít|it|thấp|thap)', q_key)
    requested_limit = int(top.group(1)) if top else None
    if requested_limit is not None and re.search(rf'\b{requested_limit}\s*%', q):
        requested_limit = None
    if requested_limit is not None:
        requested_limit = max(1, min(requested_limit, MAX_LIMIT))

    if task != "compare_years":
        limit = None

    ratio_terms = ('tỷ lệ', 'tỷ trọng', 'phần trăm', '%', 'chiếm bao nhiêu')
    is_dependency_average = 'tỷ lệ phụ thuộc' in q or 'ty le phu thuoc' in q_key
    ratio_language = not is_dependency_average and (
        any((x in q for x in ratio_terms))
        or any((x in q_key for x in ('ty le', 'ty trong', 'phan tram', 'chiem bao nhieu')))
    )
    composition_share = ratio_language and _is_shared_total_composition(question, group_by)
    wants_ratio = ratio_language and not composition_share

    if (
        all_social_deprivation_indicators
        and wants_ratio
        and task not in {'list_records', 'lookup_person', 'summary', 'compare_years'}
    ):
        task = "group_aggregate"
        group_by = ["chi_so"]

    ratio_target = None
    if (
        wants_ratio
        and not all_social_deprivation_indicators
        and task not in {'list_records', 'lookup_person', 'summary', 'compare_years'}
    ):
        ratio_target = _ratio_target_from_question(question, filters)

        if ratio_target:
            # Chỉ bỏ filter target nếu target là flag nhị phân.
            # Với text-column ratio như tinh_trang_nha IN (...), phải giữ lại
            # để executor biết tử số là giá trị nào.
            pass
    if ratio_target:
        has_fixed_huyen = any(item.col == 'huyen' for item in filters)
        has_fixed_xa = any(item.col == 'xa_phuong' for item in filters)

        explicit_group_ratio = any(x in q_key for x in (
            'theo huyen',
            'tung huyen',
            'theo xa',
            'tung xa',
            'theo dan toc',
            'theo gioi tinh',
            'theo nam',
            'tung nam',
            'qua cac nam',
            'giai doan',
            'xu huong',
            'bien dong',
        )) or classification_ratio_over_time or 'nam' in (group_by or [])

        if has_fixed_huyen or has_fixed_xa:
            if not explicit_group_ratio:
                task = 'aggregate'
                group_by = []
        elif group_by:
            task = 'group_aggregate'
        else:
            task = 'aggregate'

        order_by = None
        limit = None
    grouped_flag_ratio = wants_ratio and len(group_by) == 1 and group_by[0] in FLAG_GROUPS
    if grouped_flag_ratio:
        task = 'group_aggregate'
        ratio_target = None
    filters = _default_poor_for_feature_stats(question, filters, task)
    if all_social_deprivation_indicators:
        chi_so_cols = set(FLAG_GROUPS["chi_so"]["columns"].values())
        filters = [item for item in filters if item.col not in chi_so_cols]
        or_filters = [item for item in or_filters if item.col not in chi_so_cols]
    if task in {'list_records', 'lookup_person', 'summary'}:
        metric_out = None
        target_col_out = None
    elif task == 'compare_years':
        metric_out = 'count_households'
        target_col_out = None
    elif all_social_deprivation_indicators and wants_ratio:
        metric_out = 'ratio'
        target_col_out = None
    elif avg_info:
        metric_out = avg_info[0]
        target_col_out = avg_info[1]
    elif sum_info:
        metric_out = sum_info[0]
        target_col_out = sum_info[1]
    elif ratio_target or grouped_flag_ratio:
        metric_out = 'ratio'
        target_col_out = ratio_target
    else:
        metric_out = 'count_households'
        target_col_out = None
    select = []
    order_by = None

    plural_ranking_signal = any(x in q_key for x in (
        "may huyen",
        "may xa",
        "cac huyen",
        "nhung huyen",
        "cac xa",
        "nhung xa",
        "cuoi bang",
    ))

    rank_pos = _ranking_position(question)
    rank_dir = _ranking_direction(question)
    ask_both_extremes = _asks_both_extremes(question)

    if group_by and task not in {'list_records', 'lookup_person', 'summary', 'multi_metric_table'}:
        if rank_dir:
            if metric_out == 'avg' and target_col_out:
                order_col = f'avg_{target_col_out}'
            elif metric_out == 'sum' and target_col_out:
                order_col = {
                    'so_nhan_khau': 'tong_nhan_khau',
                    'so_tre_em': 'tong_tre_em',
                    'dien_tich_dat': 'tong_dien_tich_dat',
                    'so_tre_thieu_bhyt': 'tong_tre_thieu_bhyt',
                    'so_tre_thieu_dinh_duong': 'tong_tre_thieu_dinh_duong',
                    'so_tre_thieu_di_hoc': 'tong_tre_thieu_di_hoc',
                }.get(target_col_out, f'sum_{target_col_out}')
            elif metric_out == 'ratio':
                order_col = 'ty_le_%'
            else:
                order_col = 'so_ho'

            order_by = {'col': order_col, 'direction': 'desc' if ask_both_extremes else rank_dir}

            if ask_both_extremes:
                # Câu hỏi cần cả hai cực trị; không cắt LIMIT 1 khiến mất max/min.
                limit = None
            elif plural_ranking_signal and requested_limit is None and rank_pos is None:
                limit = 5
            else:
                limit = rank_pos or 1
    if task in {'list_records', 'lookup_person'}:
        if task == "list_records":
            identity_cols = ['chu_ho', 'nam', 'huyen', 'xa_phuong']
            detail_cols = _extract_list_select_columns(question, [])
            select = _append_unique(identity_cols, detail_cols)
            select = _append_unique(select, ['phan_loai'])
        else:
            select = list(BASE_RECORD_COLUMNS)

        select = _extract_list_select_columns(question, select)
        if task == "list_records":
            select = _auto_include_visible_filter_columns(select, filters)
            feature_filter_count = sum(
                1 for item in list(filters) + list(or_filters)
                if item.col not in {'nam', 'huyen', 'xa_phuong', 'phan_loai'}
            )
            if feature_filter_count >= 1:
                select = _append_unique(select, ['tinh_trang_nha'])

        if numeric_col:
            select = _append_unique(select, [numeric_col])

        detail_source_filters = list(filters) + list(or_filters)
        filter_detail_cols = [
            item.col for item in detail_source_filters
            if item.col in OUTPUT_COLUMNS
            and item.col not in {'nam', 'huyen', 'xa_phuong', 'phan_loai', 'dan_toc_chi_tiet', 'gioi_tinh'}
        ]
        select = _append_unique(select, filter_detail_cols)

        detail_request = any((x in q for x in ('bao nhiêu', 'thông tin về', 'cho biết', 'chi tiết về', 'thế nào')))
        if detail_request:
            select = _append_unique(select, _detail_columns_for_question(question))
            if task == 'lookup_person':
                filters = [item for item in filters if item.col not in FILTER_DETAIL_COLUMNS]

        if task == "list_records":
            identity_cols = ["chu_ho", "nam", "huyen", "xa_phuong"]
            tail_cols = ["phan_loai"]

            ordered_select = []
            for col in identity_cols:
                if col in select and col not in ordered_select:
                    ordered_select.append(col)

            for col in select:
                if col not in ordered_select and col not in tail_cols:
                    ordered_select.append(col)

            for col in tail_cols:
                if col in select and col not in ordered_select:
                    ordered_select.append(col)

            select = ordered_select

        if numeric_order:
            order_by = numeric_order
            limit = numeric_limit or requested_limit
        else:
            if order_by is None:
                order_by = {'col': 'chu_ho', 'direction': 'asc'}

            if requested_limit is not None:
                limit = requested_limit
            else:
                m_rows = re.search(r'\b(?:lay\s*)?(\d{1,3})\s*dong\b', q_key)
                limit = max(1, min(int(m_rows.group(1)), MAX_LIMIT)) if m_rows else None
    tinh_trang_vals = [f.value for f in filters if f.col == 'tinh_trang_nha' and f.op == '=']
    has_house_in_filter = any((f.col == 'tinh_trang_nha' and f.op == 'IN' for f in filters))
    if not has_house_in_filter and len(tinh_trang_vals) >= 2:
        filters = [f for f in filters if f.col != 'tinh_trang_nha']
        filters.append(Filter('tinh_trang_nha', 'IN', list(dict.fromkeys(tinh_trang_vals))))
    split_count_cols = {col for col, meta in FEATURE_CATALOG.items() if meta.get("kind") == "flag"} | set(FLAG_COLUMNS)
    split_filter_count = sum(1 for item in filters if item.op == "=" and item.value == 1 and item.col in split_count_cols)
    if task != "multi_metric_table" and split_filter_count >= 2 and ("tương ứng" in q or "lần lượt" in q or "tuong ung" in q_key or "lan luot" in q_key):
        task = "aggregate"; group_by = []; limit = None; metric_out = "count_households"; target_col_out = None
    # Chuẩn hóa limit cho câu ranking single-best.
    # Tránh bắt nhầm năm 2024 thành limit.
    if task == "group_aggregate":
        top_match = re.search(r"\btop\s*(\d{1,2})\b", q_key)
        if not top_match:
            top_match = re.search(
                r"\b(\d{1,2})\s+(?:xa|huyen|ho|dia ban|phuong|thi tran|dan toc|nhom|ket qua)\b",
                q_key,
            )

        if top_match:
            limit = min(int(top_match.group(1)), MAX_LIMIT)
        else:
            explicit_rank_pos = _ranking_position(question)

            if explicit_rank_pos and any(x in q_key for x in (
                'hang',
                'xep hang',
                'thu nhi',
                'thu hai',
                'thu ba',
                'thu tu',
                'thu nam',
                'thu sau',
                'thu bay',
                'thu tam',
            )):
                limit = explicit_rank_pos
            else:
                single_best = (
                    any(x in q_key for x in (
                        "huyen nao", "xa nao", "dia ban nao", "nhom nao",
                        "dan toc nao", "theo huyen", "chia theo huyen",
                        "theo xa", "chia theo xa",
                    ))
                    and (
                        any(x in q_key for x in (
                            "cao nhat", "thap nhat", "nhieu nhat", "it nhat",
                            "lon nhat", "nho nhat", "dung dau", "dan dau",
                        ))
                        or re.search(r"\bnhieu\b.{0,80}\bnhat\b", q_key)
                        or re.search(r"\bcao\b.{0,80}\bnhat\b", q_key)
                        or re.search(r"\bit\b.{0,80}\bnhat\b", q_key)
                        or re.search(r"\bthap\b.{0,80}\bnhat\b", q_key)
                    )
                )
                if single_best and not plural_ranking_signal and not ask_both_extremes:
                    limit = 1

    if task == "group_aggregate" and "bien_dong_dau_ky" in (group_by or []) and _movement_difference_question(question, filters):
        limit = None
        if order_by is None:
            order_by = {"col": "so_ho", "direction": "desc"}

    filters = _sanitize_filters_by_context(question, filters)
    filters = _suppress_class_filters_for_movement_context(question, filters)
    if metric_out == "ratio":
        # Năm không phải fixed-scope địa bàn. Nếu tính "xã nào/huyện nào"
        # thì vẫn phải giữ group_by.
        has_fixed_scope = any(item.col in {"huyen", "xa_phuong"} for item in filters)
        explicit_group_ratio = any(x in q_key for x in (
            "huyen nao", "xa nao", "dia ban nao",
            "theo huyen", "tung huyen",
            "theo xa", "tung xa",
            "theo dan toc", "theo gioi tinh",
            "theo nam", "tung nam", "qua cac nam",
        )) or classification_ratio_over_time

        if has_fixed_scope and not explicit_group_ratio:
            task = "aggregate"
            group_by = []
            order_by = None
            limit = None
    distribution_signal = any(x in q_key for x in (
        "buc tranh",
        "ra sao",
        "phan bo",
        "co cau",
        "nhom theo",
        "thong ke",
    ))

    if (
        task == "group_aggregate"
        and distribution_signal
        and group_by
        and task not in {"list_records", "lookup_person", "summary"}
    ):
        limit = None
    if _is_dtts_threshold_income_question(question):
        task = "group_aggregate"
        metric_out = "avg"
        target_col_out = "thu_nhap_bq"
        group_by = ["huyen"]
        filters = [item for item in filters if item.col in {"nam", "phan_loai"}]
        if not any(item.col == "phan_loai" for item in filters):
            filters.append(Filter("phan_loai", "=", "Hộ nghèo"))
        order_by = {"col": "avg_thu_nhap_bq", "direction": "asc" if "thap" in q_key else "desc"}
        limit = 1

    # "Theo năm" là một chiều phân tích, không phải yêu cầu lấy riêng năm mới
    # nhất. Dọn cả filter năm có thể đã được thêm ở nhánh rule trước đó.
    if "nam" in (group_by or []) and not _has_explicit_year(question):
        filters = [item for item in filters if item.col != "nam"]

    # "Theo/cơ cấu/phân bố giới tính" là chiều nhóm. Chỉ giữ filter giới tính
    # khi câu hỏi đồng thời nêu rõ Nam hoặc Nữ bằng một cụm không nhập nhằng.
    if (
        "gioi_tinh" in (group_by or [])
        and _explicit_gender_value(question) is None
        and len(_mentioned_gender_values(question)) < 2
    ):
        filters = [item for item in filters if item.col != "gioi_tinh"]

    has_year_filter = any(item.col == "nam" for item in filters)
    all_time_scope = any(x in q_key for x in (
        "toan bo du lieu", "tat ca cac nam", "toan bo cac nam", "qua cac nam",
    ))
    should_default_latest_year = (
        task in {"aggregate", "group_aggregate", "multi_metric_table", "summary"}
        and not has_year_filter
        and not distinct_group_col
        and not all_time_scope
        and _should_apply_default_year(
            question,
            {"task": task, "group_by": group_by},
        )
    )
    if should_default_latest_year:
        latest_year = _latest_data_year()
        if latest_year is not None:
            filters.append(Filter("nam", "=", latest_year))

    denominator_scope_out, numerator_filters_out, denominator_filters_out = _build_explicit_ratio_filters(
        question, metric_out, target_col_out, filters
    )

    return {
        'task': task,
        'metric': metric_out,
        'target_col': target_col_out,
        'filters': [asdict(item) for item in filters],
        'or_filters': [asdict(item) for item in or_filters],
        'group_by': group_by,
        'select': select,
        'order_by': order_by,
        'limit': limit,
        'person_name': name if task == 'lookup_person' else None,
        'denominator_scope': denominator_scope_out,
        'numerator_filters': [asdict(item) for item in numerator_filters_out],
        'denominator_filters': [asdict(item) for item in denominator_filters_out],
        '__question__': question,
    }

QUERY_PLAN_SYSTEM_PROMPT = 'Bạn chỉ trả về một JSON object Query Plan, không markdown, không SQL.\nSchema bắt buộc: task, metric, target_col, filters, or_filters, group_by, select, order_by, limit, person_name.\nDùng filters cho điều kiện AND. Dùng or_filters cho các điều kiện nối bằng "hoặc" giữa các cột cờ nhị phân.\ntask: aggregate|group_aggregate|list_records|lookup_person|compare_years|summary|multi_metric_table.\nmetric: count_households|avg|sum|ratio|null.\nfilter op: =|!=|>|>=|<|<=|IN|LIKE.\nKhông tạo cột ngoài dữ liệu đã nêu trong câu hỏi. Không sinh SQL hoặc pandas code.'

def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub('^```(?:json)?\\s*|\\s*```$', '', text, flags=re.IGNORECASE)
    start, end = (text.find('{'), text.rfind('}'))
    if start < 0 or end < start:
        raise ValueError('LLM không trả JSON object')
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('Query Plan JSON phải là object')
    return data

def parse_llm_query_plan(question: str) -> dict[str, Any]:
    payload = {'model': MODEL_NAME, 'messages': [{'role': 'system', 'content': QUERY_PLAN_SYSTEM_PROMPT}, {'role': 'user', 'content': question}], 'stream': False, 'options': {'temperature': 0.0, 'num_predict': 500}}
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
        response.raise_for_status()
        raw = response.json()['message']['content'].strip()
    except requests.exceptions.ConnectionError as exc:
        raise ConnectionError('Ollama chưa chạy') from exc
    except Exception as exc:
        raise RuntimeError(f'Ollama error: {exc}') from exc
    return _extract_json_object(raw)

def _looks_like_person_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    non_names = {'nam', 'nữ', 'nu', 'male', 'female', 'yes', 'no', 'true', 'false', 'hộ nghèo', 'hộ cận nghèo'}
    if v.lower() in non_names:
        return False
    return len(v.split()) >= 2

def _is_bad_commune_equal_district_filter(item: Filter, existing_filters: list[Filter]) -> bool:
    if item.col != 'xa_phuong':
        return False
    value_key = vn_name_key(str(item.value))
    return any((f.col == 'huyen' and vn_name_key(str(f.value)) == value_key for f in existing_filters))

def _is_placeholder_value(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        values = [v for v in value if v is not None]
        return bool(values) and all(_is_placeholder_value(v) for v in values)

    if not isinstance(value, str):
        return False

    raw = value.strip().lower()
    key = vn_name_key(value)
    compact = key.replace(" ", "")

    vietnamese_placeholders = {
        "huyện cần cụ thể", "xã cần cụ thể", "địa bàn cần cụ thể",
        "tỉnh cần cụ thể", "cần nêu rõ huyện", "cần nêu rõ xã",
        "không xác định", "chưa xác định",
        "huyện x", "huyen x", "xã x", "xa x",
        "huyện a", "huyen a", "xã a", "xa a",
        "huyện b", "huyen b", "xã b", "xa b",
    }

    placeholder_keys = {vn_name_key(x).replace(" ", "") for x in vietnamese_placeholders}

    return (
        compact in {
            "yourdistrictname", "districtname",
            "yourcommunename", "yourcommune",
            "commune", "district",
            "huyencancuthe", "xacancuthe",
            "diabancancuthe",
            "khongxacdinh", "chuaxacdinh",
            "huyenx", "xax", "huyena", "xaa", "huyenb", "xab",
            "x", "a", "b",
        }
        or raw in vietnamese_placeholders
        or compact in placeholder_keys
    )

def _fix_local_ratio_merged_plan(raw_plan: dict[str, Any], question: str) -> dict[str, Any]:
    q_key = vn_name_key(question)

    if raw_plan.get("metric") != "ratio":
        return raw_plan

    filters = raw_plan.get("filters") or []
    has_fixed_scope = any(
        isinstance(item, dict) and item.get("col") in {"nam", "huyen", "xa_phuong"}
        for item in filters
    )

    explicit_group_ratio = any(x in q_key for x in (
        "theo huyen",
        "tung huyen",
        "theo xa",
        "tung xa",
        "theo dan toc",
        "theo gioi tinh",
        "theo nam",
        "tung nam",
        "qua cac nam",
    ))

    if has_fixed_scope and not explicit_group_ratio:
        raw_plan["task"] = "aggregate"
        raw_plan["group_by"] = []
        raw_plan["order_by"] = None
        raw_plan["limit"] = None

    return raw_plan

def _normalize_compare_year_filters(question: str, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    years = sorted({int(y) for y in re.findall(r'\b20\d{2}\b', question or '')})
    cleaned = [f for f in filters if f.get("col") != "nam"]

    if len(years) >= 2:
        cleaned.append({"col": "nam", "op": "IN", "value": years})

    return cleaned

def merge_rule_llm_plan(rule_plan: dict[str, Any], llm_plan: dict[str, Any]) -> dict[str, Any]:
    schema = _schema_columns()
    llm_plan = llm_plan if isinstance(llm_plan, dict) else {}
    merged = {}
    raw_llm_task = llm_plan.get('task')
    raw_llm_metric = llm_plan.get('metric')
    llm_task = TASK_ALIASES.get(raw_llm_task, raw_llm_task) if isinstance(raw_llm_task, str) else None
    llm_metric = METRIC_ALIASES.get(raw_llm_metric, raw_llm_metric) if isinstance(raw_llm_metric, str) else None
    if llm_task in TASKS:
        merged['task'] = llm_task
    if llm_metric in METRICS or llm_metric is None:
        merged['metric'] = llm_metric
    raw_target_col = llm_plan.get('target_col')
    target_col = _canonical_column(raw_target_col) if isinstance(raw_target_col, str) else None
    if target_col in ALL_COLUMNS and target_col in schema and (llm_metric != 'count_households'):
        merged['target_col'] = target_col
    merged['group_by'] = _safe_canonical_columns(llm_plan.get('group_by') or [], GROUP_COLUMNS, schema)
    merged['select'] = _safe_canonical_columns(llm_plan.get('select') or [], OUTPUT_COLUMNS, schema)
    safe_order = _safe_order_by(llm_plan.get('order_by'), schema)
    if safe_order:
        merged['order_by'] = safe_order
    raw_limit = llm_plan.get('limit')
    if isinstance(raw_limit, (int, float)) and (not isinstance(raw_limit, bool)):
        merged['limit'] = max(1, min(int(raw_limit), MAX_LIMIT))
    if isinstance(llm_plan.get('person_name'), str):
        merged['person_name'] = llm_plan['person_name'].strip() or None
    # Rule giữ vai trò neo dữ liệu chắc chắn: năm, huyện, xã, phân loại, feature rõ ràng.
    # Nhưng không khóa task/group/order/limit nếu LLM đưa ra cấu trúc hợp lệ hơn.
    for key in (
        'task', 'metric', 'target_col', 'group_by', 'select', 'order_by', 'limit', 'person_name',
        'denominator_scope', 'numerator_filters', 'denominator_filters',
    ):
        rule_value = rule_plan.get(key)
        llm_value = merged.get(key)

        if rule_value in (None, [], ''):
            continue

        # Các task nhạy cảm về quyền riêng tư/tra cứu cá nhân thì rule được ưu tiên.
        if key == 'task' and rule_value in {'list_records', 'lookup_person'}:
            merged[key] = rule_value
            continue

        # Nếu rule nhận ra task có hình dạng dữ liệu rõ ràng thì giữ.
        # Không để LLM đổi group_aggregate/compare_years thành aggregate.
        if key == 'task' and rule_value in {'multi_metric_table', 'group_aggregate', 'compare_years'}:
            merged[key] = rule_value
            continue

        # Nếu LLM không có giá trị hợp lệ thì dùng rule.
        if llm_value in (None, [], ''):
            merged[key] = rule_value
            continue
        # group_by/order_by là phần rule bắt từ câu hỏi và schema thật, không để LLM ghi đè.
        # limit chỉ ưu tiên rule khi người dùng hỏi top-N rõ ràng.
        if key == 'limit':
            if isinstance(rule_value, int) and rule_value > 1:
                merged[key] = rule_value
            continue

        if key == 'group_by':
            if rule_value:
                merged[key] = rule_value
            continue

        if key == 'order_by':
            if rule_value:
                merged[key] = rule_value
            continue

        # metric/target_col vẫn ưu tiên rule khi rule bắt được avg/sum/ratio rõ ràng.
        if key in {'metric', 'target_col'}:
            merged[key] = rule_value
    rule_filters = [_coerce_filter(item) for item in rule_plan.get('filters') or []]
    source_question = rule_plan.get('__question__', '') or llm_plan.get('__question__', '')
    explicit_classifications = set(_explicit_classification_values(source_question))
    llm_filters = []
    for raw_filter in llm_plan.get('filters') or []:
        if not isinstance(raw_filter, dict):
            continue
        if raw_filter.get('value') is None and raw_filter.get('val') is None and (raw_filter.get('filter_val') is None):
            continue
        try:
            item = _coerce_filter(raw_filter)
            if item.col in {'chu_ho', 'ma_ho', 'id_ho'}:
                if llm_task != 'lookup_person':
                    continue
                if item.col == 'chu_ho' and (not _looks_like_person_name(item.value)):
                    continue
        except Exception:
            continue
        if _is_placeholder_value(item.value):
            continue
        if _is_bad_commune_equal_district_filter(item, rule_filters):
            continue
        if item.col == 'phan_loai':
            if item.value not in {'Hộ nghèo', 'Hộ cận nghèo', 'Hộ không nghèo'}:
                continue
            if item.value not in explicit_classifications:
                continue
        if item.col in FILTER_COLUMNS and item.col in schema and (item.op in OPERATORS):
            if item.op != 'IN' or (isinstance(item.value, (list, tuple)) and item.value):
                llm_filters.append(item)
    rule_filter_cols = {item.col for item in rule_filters}
    combined: dict[tuple[str, str, str], Filter] = {}
    for item in [item for item in llm_filters if item.col not in rule_filter_cols] + rule_filters:
        key = (item.col, item.op, json.dumps(item.value, ensure_ascii=False, sort_keys=True))
        combined[key] = item
    combined_filters = list(combined.values())

    combined_filters = _sanitize_filters_by_context(
        rule_plan.get('__question__', '') or llm_plan.get('__question__', ''),
        combined_filters,
    )
    merged['filters'] = [asdict(item) for item in combined_filters]
    if merged.get("task") == "lookup_person":
        person_from_filter = next(
            (
                f.get("value")
                for f in merged.get("filters", [])
                if f.get("col") == "chu_ho" and _looks_like_person_name(f.get("value"))
            ),
            None,
        )

        if not merged.get("person_name") and person_from_filter:
            merged["person_name"] = person_from_filter

        merged["filters"] = [
            f for f in merged.get("filters", [])
            if f.get("col") not in {"chu_ho", "ma_ho", "id_ho"}
        ]
    group_by_cols = set(merged.get('group_by') or [])
    merged['filters'] = [f for f in merged.get('filters', []) if not (f.get('col') in {'huyen', 'xa_phuong'} and _is_placeholder_value(f.get('value')))]
    if 'huyen' in group_by_cols:
        merged['filters'] = [f for f in merged['filters'] if not (f.get('col') == 'huyen' and _is_placeholder_value(f.get('value')))]
    if 'xa_phuong' in group_by_cols:
        merged['filters'] = [f for f in merged['filters'] if not (f.get('col') == 'xa_phuong' and _is_placeholder_value(f.get('value')))]
    rule_or_filters = [_coerce_filter(item) for item in rule_plan.get('or_filters') or []]
    llm_or_filters = []
    for raw_filter in llm_plan.get('or_filters') or []:
        if not isinstance(raw_filter, dict):
            continue
        if raw_filter.get('value') is None and raw_filter.get('val') is None and (raw_filter.get('filter_val') is None):
            continue
        try:
            item = _coerce_filter(raw_filter)
        except Exception:
            continue
        if _is_placeholder_value(item.value):
            continue
        if _is_bad_commune_equal_district_filter(item, rule_filters):
            continue
        if item.col in FILTER_COLUMNS and item.col in schema and (item.op in OPERATORS):
            if item.op != 'IN' or (isinstance(item.value, (list, tuple)) and item.value):
                llm_or_filters.append(item)
    if rule_or_filters:
        safe_or_filters = rule_or_filters
    else:
        safe_or_filters = [
            item for item in llm_or_filters
            if item.col in FLAG_COLUMNS
            and item.op == "="
            and item.value in (0, 1)
        ]

    merged["or_filters"] = [asdict(item) for item in safe_or_filters]
    for f in merged.get('filters') or []:
        col = f.get('col')
        value = f.get('value')
        if col == 'chu_ho' and _looks_like_person_name(value):
            merged['task'] = 'lookup_person'
            merged['metric'] = None
            merged['target_col'] = None
            merged['group_by'] = []
            merged['person_name'] = value
            merged['select'] = ['chu_ho', 'nam', 'huyen', 'xa_phuong', 'phan_loai', 'so_nhan_khau', 'tinh_trang_nha', 'dan_toc_chi_tiet', 'so_tre_em', 'so_nguoi_lao_dong', 'so_nguoi_cao_tuoi', 'ty_le_phu_thuoc', 'th_chat_luong_nha', 'th_dien_tich_nha']
            merged['order_by'] = {'col': 'chu_ho', 'direction': 'asc'}
            merged['limit'] = 20
            break
    for key in ('task', 'metric', 'target_col', 'filters', 'or_filters', 'group_by', 'select', 'order_by', 'limit', 'person_name'):
        merged.setdefault(key, [] if key in {'filters', 'or_filters', 'group_by', 'select'} else None)
    if merged.get('metric') == 'count_households':
        merged['target_col'] = None
        if merged.get('task') not in {'list_records', 'lookup_person'}:
            merged['select'] = []
    if merged.get('order_by') == []:
        merged['order_by'] = None
    if merged.get('limit') == []:
        merged['limit'] = None
    if rule_plan.get('task') in {'list_records', 'lookup_person'} and rule_plan.get('select'):
        merged['select'] = list(rule_plan['select'])
    question = rule_plan.get('__question__', '') or llm_plan.get('__question__', '')
    merged = _fix_local_ratio_merged_plan(merged, question)

    if merged.get("task") == "compare_years":
        merged["metric"] = "count_households"
        merged["target_col"] = None
        if _asks_all_social_deprivation_indicators(question):
            chi_so_cols = set(FLAG_GROUPS["chi_so"]["columns"].values())
            merged["group_by"] = ["chi_so", "nam"]
            merged["filters"] = [
                f for f in (merged.get("filters") or [])
                if f.get("col") not in chi_so_cols
            ]
            merged["or_filters"] = [
                f for f in (merged.get("or_filters") or [])
                if f.get("col") not in chi_so_cols
            ]
        merged["filters"] = _normalize_compare_year_filters(question, merged.get("filters") or [])

    merged.pop('__question__', None)
    return merged
VALUE_ALIASES = {'hộ ngheo': 'Hộ nghèo', 'ho ngheo': 'Hộ nghèo', 'nghèo': 'Hộ nghèo', 'hộ cận ngheo': 'Hộ cận nghèo', 'ho can ngheo': 'Hộ cận nghèo', 'cận nghèo': 'Hộ cận nghèo', 'nam': 'Nam', 'nữ': 'Nữ', 'nu': 'Nữ'}

def canonicalize_plan(raw: QueryPlan | dict) -> QueryPlan:
    data = raw.to_dict() if isinstance(raw, QueryPlan) else dict(raw)
    canonical_filters = []
    for raw_filter in data.get('filters', []):
        item = _coerce_filter(raw_filter)
        value = item.value
        if isinstance(value, str):
            value = VALUE_ALIASES.get(value.strip().lower(), value.strip())
            if item.col == 'dan_toc_chi_tiet':
                ethnicity_key = vn_name_key(value).replace(' ', '')
                value = next((ethnicity for ethnicity in _catalog_values()[1] if vn_name_key(ethnicity).replace(' ', '') == ethnicity_key), value)
        canonical_filters.append({'col': item.col, 'op': item.op.upper(), 'value': value})
    data['filters'] = canonical_filters
    canonical_or_filters = []
    for raw_filter in data.get('or_filters', []):
        item = _coerce_filter(raw_filter)
        value = item.value
        if isinstance(value, str):
            value = VALUE_ALIASES.get(value.strip().lower(), value.strip())
        canonical_or_filters.append({'col': item.col, 'op': item.op.upper(), 'value': value})
    data['or_filters'] = canonical_or_filters

    for ratio_key in ('numerator_filters', 'denominator_filters'):
        canonical_ratio_filters = []
        for raw_filter in data.get(ratio_key, []) or []:
            item = _coerce_filter(raw_filter)
            value = item.value
            if isinstance(value, str):
                value = VALUE_ALIASES.get(value.strip().lower(), value.strip())
            canonical_ratio_filters.append({'col': item.col, 'op': item.op.upper(), 'value': value})
        data[ratio_key] = canonical_ratio_filters

    return repair_plan(data)

def parse_query_plan(question: str) -> QueryPlan | None:
    if not should_use_query_plan(question):
        return None
    return canonicalize_plan(extract_rule_plan(question))

# Giữ helper này ở planner vì extract_rule_plan() cần metadata overlap.
def _expand_overlap_metric_filter_cols(cols: set[str]) -> set[str]:
    expanded = set(cols)
    for col in list(cols):
        meta = FEATURE_CATALOG.get(col, {})
        expanded.update(meta.get('overlap_filter_cols', []))
    return expanded
