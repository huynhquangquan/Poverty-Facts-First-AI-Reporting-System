from __future__ import annotations

import re
from typing import Any

import pandas as pd

from core.schema import Filter, QueryPlan
from core.catalog import (
    FLAG_GROUPS,
    FILTER_ANSWER_LABELS,
    TEXT_FILTER_LABELS,
    ANSWER_REQUIRED_COLUMN_RULES,
    FEATURE_CATALOG,
    NUMERIC_FIELD_CATALOG,
    DISTINCT_VALUE_TERMS,
    MISSING_TEXT_LABEL,
)
from poverty_chatbot.query_plan import vn_name_key, _is_top_list_question
from core.executor import execute_query_plan


def _format_vi_number(value: Any, decimals: int | None = None) -> str:
    number = float(value)
    if decimals is None:
        decimals = 0 if number.is_integer() else 2
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _numeric_answer_meta(target_col: str | None) -> tuple[str, str]:
    meta = NUMERIC_FIELD_CATALOG.get(target_col or "", {})
    label = str(meta.get("label") or (target_col or "giá trị")).removeprefix("số ")
    units = {
        "so_tre_em": "trẻ em/hộ",
        "so_tre_thieu_bhyt": "trẻ em",
        "so_tre_thieu_dinh_duong": "trẻ em",
        "so_tre_thieu_di_hoc": "trẻ em",
        "so_nhan_khau": "nhân khẩu/hộ",
        "so_nguoi_lao_dong": "người lao động/hộ",
        "so_nguoi_cao_tuoi": "người cao tuổi/hộ",
        "thu_nhap_bq": "nghìn đồng/người/tháng",
        "dien_tich_dat": "m²/hộ",
        "tong_chieu_thieu_hut": "chiều/hộ",
        "ty_le_phu_thuoc": "%",
    }
    return label, units.get(target_col or "", label)

def _filter_phrase(item: Filter) -> str | None:
    if item.col == "gioi_tinh" and item.op == "=":
        value = str(item.value).strip().lower()
        if value == "nữ":
            return "chủ hộ là nữ"
        if value == "nam":
            return "chủ hộ là nam"
        return f"giới tính chủ hộ là {value}"

    labels = FILTER_ANSWER_LABELS.get(item.col)
    if item.op == '=' and labels:
        value_key = vn_name_key(str(item.value))

        if item.value in (0, 1, True, False) or value_key in {"co", "khong", "yes", "no", "true", "false", "1", "0"}:
            positive = item.value in (1, True) or value_key in {"co", "yes", "true", "1"}
            return labels[0] if positive else labels[1]

    label = TEXT_FILTER_LABELS.get(item.col)
    if label:
        if item.op == '=':
            return f'{label} là {str(item.value).lower()}'
        if item.op == 'IN' and isinstance(item.value, (list, tuple)):
            values = ' hoặc '.join((str(v).lower() for v in item.value))
            return f'{label} là {values}'

    return None

def _join_vietnamese_phrases(phrases: list[str]) -> str:
    phrases = [p for p in phrases if p]
    if not phrases:
        return ''
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f'{phrases[0]} và {phrases[1]}'
    return ', '.join(phrases[:-1]) + f' và {phrases[-1]}'

def _important_filter_phrases(plan: QueryPlan, exclude: set[str] | None=None) -> list[str]:
    exclude = exclude or set()
    phrases = []
    for item in plan.filters:
        if item.col in exclude:
            continue
        phrase = _filter_phrase(item)
        if phrase:
            phrases.append(phrase)
    return phrases


def _child_deprivation_household_phrase(plan: QueryPlan) -> str | None:
    labels = {
        "te_th_bhyt": "trẻ em thiếu BHYT",
        "te_th_dinh_duong": "trẻ em thiếu dinh dưỡng",
        "te_th_di_hoc": "trẻ em thiếu đi học",
    }
    found = [
        labels[item.col]
        for item in plan.filters
        if item.col in labels and item.op == "=" and item.value == 1
    ]
    if not found:
        return None
    return _join_vietnamese_phrases(found)


def _or_filter_phrases(plan: QueryPlan) -> list[str]:
    phrases = []
    for item in plan.or_filters:
        phrase = _filter_phrase(item)
        if phrase:
            phrases.append(phrase)
    return phrases

def _required_answer_columns(question: str | None, result: pd.DataFrame) -> list[str]:
    if not question:
        return []
    q = question.lower()
    columns = []
    for rule in ANSWER_REQUIRED_COLUMN_RULES:
        if any((keyword in q for keyword in rule['keywords'])):
            for col in rule['columns']:
                if col in result.columns and col not in columns:
                    columns.append(col)
    return columns

def _format_answer_value(col: str, value: Any) -> str:
    if pd.isna(value):
        return MISSING_TEXT_LABEL
    if col == 'thu_nhap_bq':
        return f'{_format_vi_number(value)} nghìn đồng/người/tháng'
    if col in {'dien_tich_dat'}:
        return f'{_format_vi_number(value, 2)} m²'
    if col in {'th_bhyt', 'nhom_tre_em_duoi6', 'co_internet', 'co_dien'}:
        labels = FILTER_ANSWER_LABELS.get(col)
        if labels and value in (0, 1):
            return labels[0] if int(value) == 1 else labels[1]
    return str(value)

def _format_rank_numeric_value(col: str, value: Any) -> str:
    """Format giá trị numeric ranking kèm đơn vị đúng một lần."""
    if pd.isna(value):
        return MISSING_TEXT_LABEL

    # Các cột này đã có đơn vị trong _format_answer_value(); không nối thêm label.
    if col in {'thu_nhap_bq', 'dien_tich_dat'}:
        return _format_answer_value(col, value)

    try:
        number = float(value)
        value_text = _format_vi_number(number, 0 if number.is_integer() else 2)
    except Exception:
        value_text = str(value)

    units = {
        'so_nhan_khau': 'nhân khẩu',
        'so_tre_em': 'trẻ em',
        'so_tre_thieu_bhyt': 'trẻ em',
        'so_tre_thieu_dinh_duong': 'trẻ em',
        'so_tre_thieu_di_hoc': 'trẻ em',
        'so_nguoi_lao_dong': 'người lao động',
        'so_nguoi_cao_tuoi': 'người cao tuổi',
        'tong_chieu_thieu_hut': 'chiều',
        'ty_le_phu_thuoc': '%',
    }
    unit = units.get(col)
    return f'{value_text} {unit}' if unit else value_text

def _ordered_support_cols(question: str, result: pd.DataFrame, support_answer_labels: dict[str, str]) -> list[str]:
    q_key = vn_name_key(question or '')
    alias_map = {
        'so_ho_ho_tro_y_te': ('y te',),
        'so_ho_ho_tro_giao_duc': ('giao duc',),
        'so_ho_ho_tro_nha_o': ('nha o',),
        'so_ho_ho_tro_vay_von': ('vay von',),
        'so_ho_ho_tro_san_xuat': ('san xuat',),
        'so_ho_ho_tro_nuoc_sach': ('nuoc sach',),
        'so_ho_ho_tro_dien': ('dien',),
        'so_ho_ho_tro_vien_thong': ('vien thong',),
        'so_ho_ho_tro_dao_tao_nghe': ('dao tao nghe',),
        'so_ho_htro_y_te': ('y te',),
        'so_ho_htro_giao_duc': ('giao duc',),
        'so_ho_htro_nha_o': ('nha o',),
        'so_ho_htro_vay_von': ('vay von',),
        'so_ho_htro_san_xuat': ('san xuat',),
        'so_ho_htro_nuoc_sach': ('nuoc sach',),
        'so_ho_htro_dien': ('dien',),
        'so_ho_htro_vien_thong': ('vien thong',),
        'so_ho_htro_dao_tao_nghe': ('dao tao nghe',),

        # alias cũ, giữ để không phá log cũ nếu còn
        'ho_ho_tro_y_te': ('y te',),
        'ho_ho_tro_giao_duc': ('giao duc',),
        'ho_ho_tro_nha_o': ('nha o',),
        'ho_ho_tro_vay_von': ('vay von',),
        'ho_ho_tro_san_xuat': ('san xuat',),
        'ho_ho_tro_nuoc_sach': ('nuoc sach',),
        'ho_ho_tro_dien': ('dien',),
        'ho_ho_tro_vien_thong': ('vien thong',),
        'ho_ho_tro_dao_tao_nghe': ('dao tao nghe',),
    }

    found = []
    for col, aliases in alias_map.items():
        if col not in result.columns:
            continue
        pos = min((q_key.find(alias) for alias in aliases if alias in q_key), default=10 ** 9)
        if pos < 10 ** 9:
            found.append((pos, col))

    ordered = [col for _, col in sorted(found)]
    rest = [col for col in support_answer_labels if col in result.columns and col not in ordered]
    return ordered + rest

def _wants_table(question: str | None, result: pd.DataFrame) -> bool:
    q = (question or '').lower()
    q_key = vn_name_key(question or '')
    strong_table_signal = 'bảng' in q or 'bang' in q_key or 'thống kê' in q or ('thong ke' in q_key) or ('lập bảng' in q) or ('lap bang' in q_key) or ('phân bố' in q) or ('phan bo' in q_key) or ('cơ cấu' in q) or ('co cau' in q_key)
    weak_group_table_signal = any(x in q_key for x in (
        'theo huyen', 'tung huyen', 'theo xa', 'tung xa',
        'theo dan toc', 'theo gioi tinh', 'theo tinh trang nha',
        'theo nghe nghiep', 'theo nguon nuoc', 'theo cay trong',
    ))
    ranking_signal = 'huyện nào' in q or 'xã nào' in q or 'nhiều nhất' in q or ('ít nhất' in q) or ('cao nhất' in q) or ('thấp nhất' in q) or ('đứng đầu' in q) or ('top' in q) or ('huyen nao' in q_key) or ('xa nao' in q_key) or ('nhieu nhat' in q_key) or ('it nhat' in q_key) or ('cao nhat' in q_key) or ('thap nhat' in q_key) or ('dung dau' in q_key)
    rich_result = result is not None and (not result.empty) and (len(result.columns) >= 3 or len(result) >= 3)
    if strong_table_signal and result is not None and (not result.empty) and len(result) >= 2:
        return True
    if not rich_result:
        return False
    if ranking_signal and (not strong_table_signal):
        return False
    return strong_table_signal or weak_group_table_signal

def _table_rename_map() -> dict[str, str]:
    base = {'avg_thu_nhap_bq': 'Thu nhập bình quân (nghìn đồng/người/tháng)', 'avg_so_nhan_khau': 'Nhân khẩu bình quân (người/hộ)', 'avg_dien_tich_dat': 'Diện tích đất bình quân (m²/hộ)', 'avg_ty_le_phu_thuoc': 'Tỷ lệ phụ thuộc bình quân', 'huyen': 'Huyện', 'xa_phuong': 'Xã/phường', 'nam': 'Năm', 'phan_loai': 'Phân loại', 'tinh_trang_nha': 'Tình trạng nhà', 'dan_toc_chi_tiet': 'Dân tộc', 'nghe_nghiep_chu_ho': 'Nghề nghiệp chủ hộ', 'nguon_nuoc': 'Nguồn nước', 'so_ho': 'Số hộ', 'tong_ho': 'Tổng hộ', 'ty_le_%': 'Tỷ lệ (%)', 'so_tre_thieu': 'Số trẻ thiếu', 'so_ho_co_tre_thieu': 'Số hộ có trẻ thiếu', 'tong_tre': 'Tổng số trẻ', 'so_ho_2023': 'Số hộ 2023', 'so_ho_2024': 'Số hộ 2024', 'chenh_lech': 'Chênh lệch', 'bien_dong': 'Biến động', 'tong_ho_ngheo': 'Tổng hộ nghèo', 'tong_ho_can_ngheo': 'Tổng hộ cận nghèo', 'tong_ho_khong_ngheo': 'Tổng hộ không nghèo', 'so_ho_nha_o_kem': 'Số hộ nhà ở kém', 'so_ho_chu_ho_nu': 'Số hộ chủ hộ nữ'}
    base.update({
        "b1_diem": "Điểm B1",
        "b2_diem": "Điểm B2",
        "phieu_a": "Phiếu A",
        "nguoi_ra_soat": "Người rà soát",
        "nhom_ngheo_tong_hop": "Nhóm nghèo tổng hợp",
        "cay_trong_chinh": "Cây trồng chính",
        "bien_dong_dau_ky": "Biến động đầu kỳ",
        "khu_vuc_xa": "Khu vực xã",
        "loai_xa_phuong": "Loại xã/phường",
        'ty_le_pct': 'Tỷ lệ (%)',
        'so_ho_htro_y_te': 'Số hộ hỗ trợ y tế',
        'so_ho_htro_giao_duc': 'Số hộ hỗ trợ giáo dục',
        'so_ho_htro_san_xuat': 'Số hộ hỗ trợ sản xuất',
        'so_ho_htro_vay_von': 'Số hộ hỗ trợ vay vốn',
        'so_ho_htro_nha_o': 'Số hộ hỗ trợ nhà ở',
        'so_ho_htro_nuoc_sach': 'Số hộ hỗ trợ nước sạch',
        'so_ho_htro_dien': 'Số hộ hỗ trợ điện',
        'so_ho_htro_vien_thong': 'Số hộ hỗ trợ viễn thông',
        'so_ho_htro_dao_tao_nghe': 'Số hộ hỗ trợ đào tạo nghề',
    })
    for meta in FEATURE_CATALOG.values():
        alias = meta.get('table_alias')
        label = meta.get('table_label')
        if alias and label:
            base[alias] = label
    return base

def _format_markdown_table(result: pd.DataFrame, max_rows: int=20) -> str:
    df = result.copy()
    df = df.fillna(MISSING_TEXT_LABEL)
    hidden_cols = {'id_ho', '__total_count'}
    df = df[[col for col in df.columns if col not in hidden_cols]]
    df = df.head(max_rows)
    rename_map = _table_rename_map()
    df = df.rename(columns={col: rename_map.get(col, col) for col in df.columns})
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            if col == 'Năm':
                df[col] = df[col].apply(lambda x: str(int(x)) if pd.notna(x) else '')
            else:
                df[col] = df[col].apply(lambda x: _format_vi_number(x, 0 if float(x).is_integer() else 1) if pd.notna(x) else '')
    headers = list(df.columns)
    rows = df.astype(str).values.tolist()

    def esc(x):
        return str(x).replace('|', '\\|')
    header_line = '| ' + ' | '.join((esc(h) for h in headers)) + ' |'
    sep_line = '| ' + ' | '.join(('---' for _ in headers)) + ' |'
    body_lines = ['| ' + ' | '.join((esc(v) for v in row)) + ' |' for row in rows]
    return '\n'.join([header_line, sep_line] + body_lines)

def _numeric_rank_phrase(col: str, direction: str) -> str:
    phrases = {'thu_nhap_bq': ('cao nhất', 'thấp nhất'), 'dien_tich_dat': ('lớn nhất', 'nhỏ nhất'), 'ty_le_phu_thuoc': ('cao nhất', 'thấp nhất'), 'tong_chieu_thieu_hut': ('cao nhất', 'thấp nhất'), 'so_tre_em': ('nhiều nhất', 'ít nhất'), 'so_tre_thieu_bhyt': ('nhiều nhất', 'ít nhất'), 'so_tre_thieu_dinh_duong': ('nhiều nhất', 'ít nhất'), 'so_tre_thieu_di_hoc': ('nhiều nhất', 'ít nhất'), 'so_nhan_khau': ('nhiều nhất', 'ít nhất'), 'so_nguoi_lao_dong': ('nhiều nhất', 'ít nhất'), 'so_nguoi_cao_tuoi': ('nhiều nhất', 'ít nhất')}
    high, low = phrases.get(col, ('cao nhất', 'thấp nhất'))
    return high if direction == 'desc' else low


def _is_unscoped_deprivation_question(plan: QueryPlan, question: str | None) -> bool:
    if any(item.col == 'phan_loai' for item in plan.filters):
        return False
    q_key = vn_name_key(question or '')
    return bool(
        re.search(r'\bthieu(?:\s+hut)?\b', q_key)
        or any(x in q_key for x in ('dvxh', 'dich vu xa hoi', 'nguyen nhan'))
    )


def _deprivation_compare_table_answer(
    plan: QueryPlan,
    result: pd.DataFrame,
    question: str | None,
) -> str | None:
    q_key = vn_name_key(question or '')
    is_deprivation = bool(
        re.search(r'\bthieu(?:\s+hut)?\b', q_key)
        or any(x in q_key for x in ('dvxh', 'dich vu xa hoi'))
    )
    if plan.task != 'compare_years' or not is_deprivation:
        return None
    if 'chi_so' not in set(plan.group_by or []) and 'chi_so' not in result.columns:
        return None

    years: set[int] = set()
    for item in plan.filters:
        if item.col != 'nam':
            continue
        values = item.value if item.op == 'IN' and isinstance(item.value, (list, tuple, set)) else [item.value]
        years.update(int(value) for value in values if str(value).isdigit())
    if 'nam' in result.columns:
        years.update(int(value) for value in result['nam'].dropna().unique() if str(value).isdigit())
    years.update(
        int(match.group(1))
        for column in result.columns
        if (match := re.fullmatch(r'so_ho_(20\d{2})', str(column)))
    )
    ordered_years = sorted(years)
    time_text = (
        f' giữa năm {ordered_years[0]} và {ordered_years[-1]}'
        if len(ordered_years) >= 2 else ''
    )
    scope_text = (
        ' trên toàn bộ các phân loại hộ'
        if not any(item.col == 'phan_loai' for item in plan.filters)
        else ''
    )
    return (
        f'Đã lập bảng so sánh các chỉ số thiếu hụt dịch vụ xã hội{time_text}{scope_text}. '
        'Xem chi tiết từng chỉ số trong bảng kết quả bên dưới.'
    )


def _movement_label_from_question(q_key: str, labels: list[str]) -> str | None:
    alias_map = {
        "Tái nghèo": ("tai ngheo",),
        "Cận nghèo trở thành hộ nghèo": (
            "can ngheo tro thanh ho ngheo", "ho can ngheo tro thanh ho ngheo",
            "tu ho can ngheo thanh ho ngheo", "tu ho can ngheo tro thanh ho ngheo",
            "can ngheo xuong ngheo", "can ngheo chuyen sang ngheo",
        ),
        "Nghèo mới phát sinh": ("ngheo moi phat sinh",),
        "Tái cận nghèo": ("tai can ngheo",),
        "Cận nghèo mới phát sinh": ("can ngheo moi phat sinh",),
        "Thoát nghèo -> cận nghèo": ("thoat ngheo len can ngheo", "thoat ngheo sang can ngheo", "tu ho ngheo len can ngheo"),
        "Thoát nghèo -> vượt chuẩn": ("thoat ngheo vuot chuan",),
        "Thoát cận nghèo -> vượt chuẩn": ("thoat can ngheo vuot chuan",),
    }
    available = {str(label): str(label) for label in labels}
    for canonical, aliases in alias_map.items():
        if canonical not in available:
            continue
        if any(re.search(rf"\b{re.escape(alias)}\b", q_key) for alias in aliases):
            return canonical
    return None


def _movement_comparison_answer(plan: QueryPlan, result: pd.DataFrame, question: str | None) -> str | None:
    if result.empty or "bien_dong_dau_ky" not in result.columns or "so_ho" not in result.columns:
        return None

    q_key = vn_name_key(question or "")
    labels = [str(value) for value in result["bien_dong_dau_ky"].dropna().tolist()]
    values = {
        str(row["bien_dong_dau_ky"]): int(row["so_ho"] or 0)
        for _, row in result.iterrows()
        if pd.notna(row.get("bien_dong_dau_ky"))
    }
    if not values:
        return None

    year = next((item.value for item in plan.filters if item.col == "nam" and item.op == "="), None)
    year_prefix = f"Năm {year}, " if year else "Theo dữ liệu hiện có, "

    if any(x in q_key for x in ("co phai", "phai la", "co dung la")) and len(values) >= 2:
        primary = _movement_label_from_question(q_key, labels)
        if primary is None:
            primary = labels[0]
        # Tìm nhãn còn lại được nhắc đến trong câu, ưu tiên khác primary.
        other = None
        for label in labels:
            if label != primary and vn_name_key(label) in q_key:
                other = label
                break
        if other is None:
            other = next((label for label in labels if label != primary), None)
        if other:
            same = values.get(primary) == values.get(other)
            verdict = "Có" if same else "Không"
            return (
                f"{year_prefix}{primary.lower()} có {_format_vi_number(values.get(primary, 0))} hộ; "
                f"{other.lower()} có {_format_vi_number(values.get(other, 0))} hộ. "
                f"{verdict}, đây là hai nhãn biến động khác nhau."
            )

    if any(x in q_key for x in ("nhom nao", "nhieu nhat", "cao nhat", "chenh", "so voi")):
        top_label, top_value = max(values.items(), key=lambda item: item[1])
        comparator = _movement_label_from_question(q_key, [label for label in labels if label != top_label])
        if comparator and comparator in values:
            diff = top_value - values[comparator]
            relation = "nhiều hơn" if diff >= 0 else "ít hơn"
            return (
                f"{year_prefix}nhóm {top_label.lower()} nhiều nhất với {_format_vi_number(top_value)} hộ, "
                f"{relation} {comparator.lower()} {_format_vi_number(abs(diff))} hộ."
            )
        return f"{year_prefix}nhóm {top_label.lower()} nhiều nhất với {_format_vi_number(top_value)} hộ."

    return None

def format_query_plan_answer(plan: QueryPlan, result: pd.DataFrame, question: str | None=None) -> str:
    if "ly_do" in result.columns and not result.empty:
        return str(result["ly_do"].iloc[0])
    if result.empty:
        return 'Không tìm thấy dữ liệu phù hợp với các điều kiện đã nêu.'
    movement_answer = _movement_comparison_answer(plan, result, question)
    if movement_answer:
        return movement_answer
    deprivation_compare_answer = _deprivation_compare_table_answer(plan, result, question)
    if deprivation_compare_answer:
        return deprivation_compare_answer
    if plan.task == 'list_records':
        if plan.limit and plan.limit > 1 and plan.order_by and plan.order_by.col in NUMERIC_FIELD_CATALOG and 'chu_ho' in result.columns:
            label = NUMERIC_FIELD_CATALOG[plan.order_by.col].get('label', plan.order_by.col)
            lines = []
            for idx, (_, row) in enumerate(result.head(plan.limit).iterrows(), start=1):
                value = _format_rank_numeric_value(plan.order_by.col, row[plan.order_by.col])
                lines.append(f'- {idx}. {row["chu_ho"]}: {value}')
            return f'Top {_format_vi_number(len(lines))} hộ theo {label}:\n' + '\n'.join(lines)
        if plan.limit == 1 and plan.order_by and (plan.order_by.col in NUMERIC_FIELD_CATALOG) and (plan.order_by.col in result.columns) and ('chu_ho' in result.columns):
            meta = NUMERIC_FIELD_CATALOG.get(plan.order_by.col, {})
            label = meta.get('label', plan.order_by.col)
            direction_text = _numeric_rank_phrase(plan.order_by.col, plan.order_by.direction)
            value = result.iloc[0][plan.order_by.col]

            value_text = _format_rank_numeric_value(plan.order_by.col, value)

            names = result['chu_ho'].astype(str).head(5).tolist()
            name_text = ', '.join(names)
            extra = f' và còn {len(result) - 5} hộ khác' if len(result) > 5 else ''

            return f"Có {_format_vi_number(len(result))} hộ cùng có {label} {direction_text}: {value_text}. Một số hộ gồm: {name_text}{extra}. Xem chi tiết trong bảng kết quả."
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        parts = [subject]
        if values.get('dan_toc_chi_tiet'):
            parts.append(f"dân tộc {values['dan_toc_chi_tiet']}")
        if values.get('huyen'):
            parts.append(f"tại {values['huyen']}")
        if values.get('xa_phuong'):
            parts.append(f"ở {values['xa_phuong']}")
        if values.get('nam'):
            parts.append(f"năm {values['nam']}")
        conditions = _important_filter_phrases(plan, {'phan_loai', 'dan_toc_chi_tiet', 'huyen', 'xa_phuong', 'nam'})
        or_conditions = _or_filter_phrases(plan)
        condition_text = ''
        if conditions:
            condition_text += ' ' + _join_vietnamese_phrases(conditions)
        if or_conditions:
            condition_text += ' có ít nhất một trong các đặc trưng: ' + ' hoặc '.join(or_conditions)
        total_found = int(result['__total_count'].iloc[0]) if '__total_count' in result.columns and (not result.empty) else len(result)
        return f"Tìm thấy {_format_vi_number(total_found)} {' '.join(parts)}{condition_text}. Hiển thị danh sách phù hợp trong bảng kết quả."
    if plan.task == 'multi_metric_table':
        support_answer_labels = {
            'so_ho_ho_tro_giao_duc': 'Hỗ trợ giáo dục',
            'so_ho_ho_tro_y_te': 'Hỗ trợ y tế',
            'so_ho_ho_tro_nha_o': 'Hỗ trợ nhà ở',
            'so_ho_ho_tro_vay_von': 'Hỗ trợ vay vốn',
            'so_ho_ho_tro_san_xuat': 'Hỗ trợ sản xuất',
            'so_ho_ho_tro_nuoc_sach': 'Hỗ trợ nước sạch',
            'so_ho_ho_tro_dien': 'Hỗ trợ điện',
            'so_ho_ho_tro_vien_thong': 'Hỗ trợ viễn thông',
            'so_ho_ho_tro_dao_tao_nghe': 'Hỗ trợ đào tạo nghề',
            'so_ho_htro_giao_duc': 'Hỗ trợ giáo dục',
            'so_ho_htro_y_te': 'Hỗ trợ y tế',
            'so_ho_htro_nha_o': 'Hỗ trợ nhà ở',
            'so_ho_htro_vay_von': 'Hỗ trợ vay vốn',
            'so_ho_htro_san_xuat': 'Hỗ trợ sản xuất',
            'so_ho_htro_nuoc_sach': 'Hỗ trợ nước sạch',
            'so_ho_htro_dien': 'Hỗ trợ điện',
            'so_ho_htro_vien_thong': 'Hỗ trợ viễn thông',
            'so_ho_htro_dao_tao_nghe': 'Hỗ trợ đào tạo nghề',
        }
        support_cols = _ordered_support_cols(question or '', result, support_answer_labels)
        if len(support_cols) >= 2 and not result.empty:
            row = result.iloc[0]
            support_cols = sorted(
                support_cols,
                key=lambda col: float(row[col]) if col in result.columns and pd.notna(row[col]) else -1,
                reverse=True,
            )
            values = {item.col: item.value for item in plan.filters if item.op == '='}
            subject = str(values.get('phan_loai', 'hộ')).lower()
            year = values.get('nam')
            parts = [
                f'{support_answer_labels[col]} {_format_vi_number(row[col])} hộ'
                for col in support_cols
                if col in result.columns
            ]
            prefix = (
                f"Năm {year}, trong nhóm {subject}, "
                if year
                else f"Trong nhóm {subject}, "
            )
            return prefix + "các nội dung hỗ trợ được ghi nhận gồm: " + ", ".join(parts) + "."
        scope_note = ' trên toàn bộ các phân loại hộ' if _is_unscoped_deprivation_question(plan, question) else ''
        return f'Đã lập bảng theo yêu cầu{scope_note}. Xem bảng kết quả bên dưới.'
    if plan.task == 'compare_years' and _wants_table(question, result):
        return 'Đã lập bảng theo yêu cầu. Xem bảng kết quả bên dưới.'
    if _wants_table(question, result) and plan.task not in {"group_aggregate", "lookup_person"}:
        return 'Đã thống kê dữ liệu theo yêu cầu. Xem bảng kết quả bên dưới.'
    q = (question or '').lower()
    q_key = vn_name_key(question or '')
    is_distribution = any((x in q for x in ('thống kê', 'phân bố', 'cơ cấu', 'theo từng', 'lần lượt', 'tương ứng'))) or any((x in q_key for x in ('thong ke', 'phan bo', 'co cau', 'theo tung', 'lan luot', 'tuong ung')))
    is_ranking = any((x in q for x in ('huyện nào', 'xã nào', 'dân tộc nào', 'nhóm nào', 'loại nào', 'nhiều nhất', 'ít nhất', 'cao nhất', 'thấp nhất', 'đứng đầu', 'top', 'hạng', 'xếp hạng', 'thứ nhì', 'thứ hai', 'thứ ba', 'thứ tư', 'thứ năm', 'chót', 'bét', 'cuối bảng'))) or any((x in q_key for x in ('huyen nao', 'xa nao', 'dan toc nao', 'nhom nao', 'loai nao', 'nhieu nhat', 'it nhat', 'cao nhat', 'thap nhat', 'dung dau', 'top', 'hang', 'xep hang', 'thu nhi', 'thu hai', 'thu ba', 'thu tu', 'thu nam', 'chot', 'bet', 'cuoi bang')))
    if plan.task == 'lookup_person':
        rows = []
        for _, row in result.head(3).iterrows():
            scope = ', '.join((str(row[col]) for col in ('xa_phuong', 'huyen', 'nam') if col in result.columns and pd.notna(row.get(col))))
            facts = []
            labels = {'phan_loai': 'phân loại hộ', 'gioi_tinh': 'giới tính', 'dan_toc_chi_tiet': 'dân tộc', 'so_nhan_khau': 'số nhân khẩu', 'tinh_trang_nha': 'tình trạng nhà ở', 'thu_nhap_bq': 'thu nhập bình quân', 'th_bhyt': 'BHYT', 'so_tre_em': 'số trẻ em', 'nhom_tre_em_duoi6': 'trẻ dưới 6 tuổi'}
            base_cols = ['phan_loai', 'gioi_tinh', 'dan_toc_chi_tiet', 'so_nhan_khau', 'tinh_trang_nha']
            required_cols = _required_answer_columns(question, result)
            answer_cols = []
            for col in base_cols + required_cols:
                if col not in answer_cols:
                    answer_cols.append(col)
            for col in answer_cols:
                if col in result.columns and pd.notna(row.get(col)):
                    value = _format_answer_value(col, row[col])
                    label = labels.get(col, col)
                    facts.append(f'{label}: {value}')
            if facts:
                rows.append(f"{row.get('chu_ho', plan.person_name)} ({scope}): " + '; '.join(facts))
        if rows:
            suffix = f' Có thêm {len(result) - 3} kết quả phù hợp.' if len(result) > 3 else ''
            return ' '.join(rows) + suffix
        labels = {'phan_loai': 'phân loại', 'gioi_tinh': 'giới tính', 'dan_toc_chi_tiet': 'dân tộc', 'so_nhan_khau': 'số nhân khẩu', 'thu_nhap_bq': 'thu nhập bình quân', 'dien_tich_dat': 'diện tích đất', 'so_tre_em': 'số trẻ em', 'so_tre_thieu_bhyt': 'số trẻ thiếu BHYT', 'so_tre_thieu_dinh_duong': 'số trẻ thiếu dinh dưỡng', 'so_tre_thieu_di_hoc': 'số trẻ thiếu đi học', 'so_nguoi_lao_dong': 'số người lao động', 'so_nguoi_cao_tuoi': 'số người cao tuổi', 'ty_le_phu_thuoc': 'tỷ lệ phụ thuộc', 'nghe_nghiep_chu_ho': 'nghề nghiệp chủ hộ', 'trinh_do_hoc_van_chu_ho': 'trình độ học vấn', 'suc_khoe_chu_ho': 'sức khỏe chủ hộ', 'tinh_trang_nha': 'tình trạng nhà ở', 'nguon_nuoc': 'nguồn nước', 'co_nha_tieu_hvs': 'nhà tiêu hợp vệ sinh', 'th_nuoc_sach': 'thiếu nước sạch', 'th_nha_tieu': 'thiếu nhà tiêu hợp vệ sinh', 'th_chat_luong_nha': 'thiếu chất lượng nhà ở', 'th_dien_tich_nha': 'thiếu diện tích nhà ở', 'th_viec_lam': 'thiếu việc làm', 'nn_thieu_lao_dong': 'nguyên nhân thiếu lao động', 'nhom_khong_knld': 'thuộc nhóm không có khả năng lao động', 'nhom_cao_tuoi': 'có người cao tuổi', 'co_tre_em': 'có trẻ em', 'nhom_tre_em_duoi6': 'có trẻ em dưới 6 tuổi', 'nhom_tre_em_di_hoc': 'có trẻ em đi học', 'te_th_bhyt': 'trẻ em thiếu BHYT', 'te_th_dinh_duong': 'trẻ em thiếu dinh dưỡng', 'te_th_di_hoc': 'trẻ em thiếu đi học'}
        binary_columns = {'co_nha_tieu_hvs', 'th_nuoc_sach', 'th_nha_tieu', 'th_chat_luong_nha', 'th_dien_tich_nha', 'th_viec_lam', 'nn_thieu_lao_dong', 'nhom_khong_knld', 'nhom_cao_tuoi', 'co_tre_em', 'nhom_tre_em_duoi6', 'nhom_tre_em_di_hoc', 'te_th_bhyt', 'te_th_dinh_duong', 'te_th_di_hoc'}
        preferred_order = ['phan_loai', 'gioi_tinh', 'dan_toc_chi_tiet', 'so_nhan_khau', 'thu_nhap_bq', 'dien_tich_dat', 'trinh_do_hoc_van_chu_ho', 'suc_khoe_chu_ho', 'nghe_nghiep_chu_ho', 'tinh_trang_nha', 'so_tre_em', 'so_tre_thieu_bhyt', 'so_tre_thieu_dinh_duong', 'so_tre_thieu_di_hoc', 'so_nguoi_lao_dong', 'so_nguoi_cao_tuoi', 'ty_le_phu_thuoc', 'th_chat_luong_nha', 'th_dien_tich_nha', 'co_tre_em', 'nhom_tre_em_duoi6']
        detail_columns = [col for col in preferred_order if col in result.columns]
        answers = []
        for _, row in result.head(3).iterrows():
            scope = ', '.join((str(row[col]) for col in ('xa_phuong', 'huyen', 'nam') if col in row and pd.notna(row[col])))
            facts = []
            for col in detail_columns:
                value = row.get(col)
                if pd.isna(value):
                    continue
                display = ('có' if int(value) == 1 else 'không') if col in binary_columns else value
                facts.append(f'{labels.get(col, col)}: {display}')
            fact_text = '; '.join(facts) if facts else 'đã tìm thấy thông tin hộ'
            answers.append(f"{row.get('chu_ho', plan.person_name)} ({scope}): {fact_text}")
        suffix = f' Có thêm {len(result) - 3} kết quả phù hợp.' if len(result) > 3 else ''
        return ' '.join(answers) + suffix
    if plan.task == 'summary':
        row = result.iloc[0]
        parts = [
            f"{_format_vi_number(row['ho_ngheo'])} hộ nghèo",
            f"{_format_vi_number(row['ho_can_ngheo'])} hộ cận nghèo",
        ]
        if 'ho_khong_ngheo' in result.columns:
            parts.append(f"{_format_vi_number(row['ho_khong_ngheo'])} hộ không nghèo")
        return f"Tổng cộng {_format_vi_number(row['tong_ho'])} hộ, gồm {_join_vietnamese_phrases(parts)}."
    if plan.task == 'aggregate' and plan.metric == 'sum':
        first = result.iloc[0]
        alias_map = {
            'so_nhan_khau': ('tong_nhan_khau', 'nhân khẩu'),
            'so_tre_em': ('tong_tre_em', 'trẻ em'),
            'so_tre_thieu_bhyt': ('tong_tre_thieu_bhyt', 'trẻ em thiếu BHYT'),
            'so_tre_thieu_dinh_duong': ('tong_tre_thieu_dinh_duong', 'trẻ em thiếu dinh dưỡng'),
            'so_tre_thieu_di_hoc': ('tong_tre_thieu_di_hoc', 'trẻ em thiếu đi học'),
            'so_nguoi_lao_dong': ('sum_so_nguoi_lao_dong', 'người lao động'),
            'so_nguoi_cao_tuoi': ('sum_so_nguoi_cao_tuoi', 'người cao tuổi'),
            'dien_tich_dat': ('tong_dien_tich_dat', 'm² đất'),
        }
        alias, label = alias_map.get(
            plan.target_col,
            (f'sum_{plan.target_col}', plan.target_col or 'giá trị')
        )

        if alias in result.columns:
            value = first[alias]
            value_text = (
                _format_vi_number(value)
                if pd.notna(value) and float(value).is_integer()
                else _format_vi_number(value, 2)
            )

            values = {item.col: item.value for item in plan.filters if item.op == '='}
            subject = str(values.get('phan_loai', 'hộ')).lower()
            if plan.target_col in {'so_tre_thieu_bhyt', 'so_tre_thieu_dinh_duong', 'so_tre_thieu_di_hoc'} and 'phan_loai' not in values:
                subject = 'các hộ'
            scope = ' '.join(
                part for part in (
                    f"tại {values['huyen']}" if values.get('huyen') else '',
                    f"năm {values['nam']}" if values.get('nam') else '',
                )
                if part
            )

            house_text = ''
            if 'so_ho' in result.columns and pd.notna(first.get('so_ho')):
                house_text = f' trên {_format_vi_number(first["so_ho"])} hộ'

            return f'Tổng {label} của {subject}{(" " + scope) if scope else ""} là {value_text}{house_text}.'
    if plan.task == 'compare_years' and {'so_ho_2023', 'so_ho_2024'} <= set(result.columns):
        first = result.iloc[0]
        extra_conditions = _important_filter_phrases(plan, {'phan_loai', 'huyen', 'xa_phuong', 'nam'})
        or_conditions = _or_filter_phrases(plan)
        condition_text = ''
        if extra_conditions:
            condition_text += ' ' + _join_vietnamese_phrases(extra_conditions)
        if or_conditions:
            condition_text += ' có ít nhất một trong các đặc trưng: ' + ' hoặc '.join(or_conditions)
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        classification = str(values.get('phan_loai', 'hộ')).lower()
        scope_parts = []
        if 'huyen' in result.columns and pd.notna(first.get('huyen')):
            scope_parts.append(str(first['huyen']))
        elif values.get('huyen'):
            scope_parts.append(f"tại {values['huyen']}")
        if values.get('xa_phuong'):
            scope_parts.append(f"ở {values['xa_phuong']}")
        scope = ' '.join(scope_parts)
        y2023 = int(first['so_ho_2023'])
        y2024 = int(first['so_ho_2024'])
        change = int(first.get('chenh_lech', first.get('bien_dong', y2024 - y2023)))
        def format_vi_integer(value):
            return _format_vi_number(value)

        prefix = f'{classification.capitalize()}{condition_text}'
        if scope:
            prefix += f' tại {scope}' if not scope.startswith('tại ') else f' {scope}'
        if change > 0:
            return (
                f'{prefix} năm 2023 có {format_vi_integer(y2023)} hộ; '
                f'năm 2024 có {format_vi_integer(y2024)} hộ, tăng '
                f'{format_vi_integer(change)} hộ so với năm 2023.'
            )
        if change < 0:
            return (
                f'{prefix} năm 2023 có {format_vi_integer(y2023)} hộ; '
                f'năm 2024 còn {format_vi_integer(y2024)} hộ, giảm '
                f'{format_vi_integer(abs(change))} hộ so với năm 2023.'
            )
        return (
            f'{prefix} năm 2023 có {format_vi_integer(y2023)} hộ; '
            f'năm 2024 có {format_vi_integer(y2024)} hộ, không thay đổi so với năm 2023.'
        )
    ratio_col = 'ty_le_pct' if 'ty_le_pct' in result.columns else 'ty_le_%'

    if plan.task == 'aggregate' and plan.metric == 'ratio' and {'so_tre_thieu', 'so_ho_co_tre_thieu', 'tong_tre', ratio_col} <= set(result.columns):
        row = result.iloc[0]
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        scope = ' '.join((part for part in (
            f"tại {values['huyen']}" if values.get('huyen') else '',
            f"ở {values['xa_phuong']}" if values.get('xa_phuong') else '',
            f"năm {values['nam']}" if values.get('nam') else '',
        ) if part))
        labels = FILTER_ANSWER_LABELS.get(plan.target_col)
        target_text = labels[0] if labels else "trẻ em thiếu chỉ tiêu"
        return (
            f"Tỷ lệ {target_text}{(' ' + scope if scope else '')} là "
            f"{_format_vi_number(row[ratio_col], 1)}%, tương ứng "
            f"{_format_vi_number(row['so_tre_thieu'])}/{_format_vi_number(row['tong_tre'])} trẻ em; "
            f"ghi nhận tại {_format_vi_number(row['so_ho_co_tre_thieu'])} hộ có trẻ thiếu chỉ tiêu."
        )

    if plan.task == 'aggregate' and plan.metric == 'ratio' and {'so_ho', 'tong_ho', ratio_col} <= set(result.columns):
        row = result.iloc[0]
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        year = f"năm {values['nam']}" if values.get('nam') else 'Theo dữ liệu hiện có'
        district = f" tại {values['huyen']}" if values.get('huyen') else ''
        commune = f" ở {values['xa_phuong']}" if values.get('xa_phuong') else ''

        # Ratio có thể có tử số là tổ hợp nhiều điều kiện:
        #   hộ cận nghèo + nam + có BHYT + thiếu vốn + thiếu việc làm
        # trên mẫu số base:
        #   tổng hộ cận nghèo / tổng hộ theo năm / huyện / xã.
        # Vì vậy không chỉ mô tả target_col, mà mô tả toàn bộ điều kiện ngoài mẫu số.
        numerator_conditions = _important_filter_phrases(
            plan,
            {'phan_loai', 'huyen', 'xa_phuong', 'nam'},
        )
        condition_text = ''
        if numerator_conditions:
            condition_text = ' ' + _join_vietnamese_phrases(numerator_conditions)

        q_key = vn_name_key(question or "")

        denominator_scope = f'tổng số {subject}{district}{commune} ({_format_vi_number(row["tong_ho"])} hộ)'

        if plan.target_col == "phan_loai":
            if re.search(r"\btong(?: so)?\s+ho\s+ra soat\b", q_key):
                denominator_scope = f'tổng số hộ rà soát{district}{commune} ({_format_vi_number(row["tong_ho"])} hộ)'
            elif not re.search(r"\btong(?: so)?\s+ho\s+(?:ngheo|can ngheo|khong ngheo)\b", q_key):
                denominator_conditions = _important_filter_phrases(
                    plan,
                    {'phan_loai', 'huyen', 'xa_phuong', 'nam'},
                )
                if denominator_conditions:
                    denominator_scope = (
                        f'tổng số hộ {_join_vietnamese_phrases(denominator_conditions)}'
                        f'{district}{commune} ({_format_vi_number(row["tong_ho"])} hộ)'
                    )
                else:
                    denominator_scope = f'tổng số hộ{district}{commune} ({_format_vi_number(row["tong_ho"])} hộ)'
        return (
            f"{year.capitalize()}, có {_format_vi_number(row['so_ho'])} {subject}{condition_text}"
            f"{district}{commune}, chiếm {_format_vi_number(row[ratio_col], 1)}% trên {denominator_scope}."
        )
    if plan.task == 'aggregate' and plan.metric == 'ratio':
        row = result.iloc[0]
        ratio_value = float(row['ty_le_%'])
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        scope = ' '.join((part for part in (f"tại {values['huyen']}" if values.get('huyen') else '', f"năm {values['nam']}" if values.get('nam') else '') if part))
        labels = FILTER_ANSWER_LABELS.get(plan.target_col)
        target_text = labels[0] if labels else str(plan.target_col)
        return f"Tỷ lệ {subject} {target_text}{(' ' + scope if scope else '')} là {_format_vi_number(ratio_value, 1)}%."
    feature_alias_to_label = {}
    for _col, _meta in FEATURE_CATALOG.items():
        _alias = _meta.get("table_alias")
        if _alias:
            feature_alias_to_label[_alias] = FILTER_ANSWER_LABELS.get(_col, (_meta.get("label", _col), ""))[0]

    feature_count_cols = [col for col in result.columns if col in feature_alias_to_label]
    if len(feature_count_cols) >= 2:
        row = result.iloc[0]
        values = {item.col: item.value for item in plan.filters if item.op == "="}
        subject = str(values.get("phan_loai", "hộ")).lower()
        year = f" năm {values['nam']}" if values.get("nam") else ""
        parts = [f"{_format_vi_number(row[col])} {subject} {feature_alias_to_label[col]}" for col in feature_count_cols]
        return f"Có {_join_vietnamese_phrases(parts)}{year}."
    support_answer_labels = {
        'so_ho_ho_tro_giao_duc': 'được hỗ trợ giáo dục',
        'so_ho_ho_tro_y_te': 'được hỗ trợ y tế',
        'so_ho_ho_tro_nha_o': 'được hỗ trợ nhà ở',
        'so_ho_ho_tro_vay_von': 'được hỗ trợ vay vốn',
        'so_ho_ho_tro_san_xuat': 'được hỗ trợ sản xuất',
        'so_ho_ho_tro_nuoc_sach': 'được hỗ trợ nước sạch',
        'so_ho_ho_tro_dien': 'được hỗ trợ điện',
        'so_ho_ho_tro_vien_thong': 'được hỗ trợ viễn thông',
        'so_ho_ho_tro_dao_tao_nghe': 'được hỗ trợ đào tạo nghề',

        # alias cũ
        'ho_ho_tro_giao_duc': 'được hỗ trợ giáo dục',
        'ho_ho_tro_y_te': 'được hỗ trợ y tế',
        'ho_ho_tro_nha_o': 'được hỗ trợ nhà ở',
        'ho_ho_tro_vay_von': 'được hỗ trợ vay vốn',
        'ho_ho_tro_san_xuat': 'được hỗ trợ sản xuất',
        'ho_ho_tro_nuoc_sach': 'được hỗ trợ nước sạch',
        'ho_ho_tro_dien': 'được hỗ trợ điện',
        'ho_ho_tro_vien_thong': 'được hỗ trợ viễn thông',
        'ho_ho_tro_dao_tao_nghe': 'được hỗ trợ đào tạo nghề',
    }
    support_cols = _ordered_support_cols(question or '', result, support_answer_labels)
    if len(support_cols) >= 2:
        row = result.iloc[0]
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        year = f" năm {values['nam']}" if values.get('nam') else ''
        parts = [f'{_format_vi_number(row[col])} {subject} {support_answer_labels[col]}' for col in support_cols]
        return f'Có {_join_vietnamese_phrases(parts)}{year}.'
    if plan.task == 'aggregate' and plan.metric == 'count_households':
        row_value = int(result.iloc[0, 0])
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        child_household_phrase = _child_deprivation_household_phrase(plan)
        if child_household_phrase:
            parts = [f"Có {_format_vi_number(row_value)} hộ có {child_household_phrase}"]
            if values.get('phan_loai'):
                parts.append(f"thuộc {str(values['phan_loai']).lower()}")
            if values.get('xa_phuong'):
                parts.append(f"tại {values['xa_phuong']}")
            elif values.get('huyen'):
                parts.append(f"tại {values['huyen']}")
            if values.get('nam'):
                parts.append(f"năm {values['nam']}")
            return " ".join(parts) + "."
        subject = str(values.get('phan_loai', 'hộ')).lower()
        ethnicity = values.get('dan_toc_chi_tiet')
        if ethnicity:
            subject += f' dân tộc {ethnicity}'
        if values.get('gioi_tinh'):
            subject += f" có chủ hộ là {str(values['gioi_tinh']).lower()}"
        extras = _important_filter_phrases(plan, {'phan_loai', 'dan_toc_chi_tiet', 'gioi_tinh', 'huyen', 'xa_phuong', 'nam'})
        or_extras = _or_filter_phrases(plan)
        if extras and or_extras:
            subject += ' đồng thời ' + _join_vietnamese_phrases(extras)
            subject += ' và có ít nhất một trong các đặc trưng: ' + ' hoặc '.join(or_extras)
        elif extras:
            subject += ' đồng thời ' + _join_vietnamese_phrases(extras)
        elif or_extras:
            subject += ' có ít nhất một trong các đặc trưng: ' + ' hoặc '.join(or_extras)
        scope = ' '.join((part for part in (f"tại {values['xa_phuong']}" if values.get('xa_phuong') else f"tại {values['huyen']}" if values.get('huyen') else '', f"năm {values['nam']}" if values.get('nam') else '') if part))
        return f"Có {_format_vi_number(row_value)} {subject}{(' ' + scope if scope else '')}."
    first = result.iloc[0]
    if plan.task == 'compare_years':
        return 'Đã lập bảng theo yêu cầu. Xem bảng kết quả bên dưới.'
    else:
        groups = []
        for col in plan.group_by:
            if col in result.columns:
                groups.append(col)
            elif col in FLAG_GROUPS:
                label_col = FLAG_GROUPS[col]['label_col']
                if label_col in result.columns:
                    groups.append(label_col)
    labels = ', '.join((str(first[col]) for col in groups))
    metric_col = f'avg_{plan.target_col}' if plan.metric == 'avg' else result.columns[-1]
    metric_value = first[metric_col]
    if plan.metric == 'avg' and (not plan.group_by):
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        if any((item.col in {'gioi_tinh', 'nhom_chu_ho_nu'} and item.value in ('Nữ', 1) for item in plan.filters)):
            subject += ' có chủ hộ nữ'
        district = f" tại {values['huyen']}" if values.get('huyen') else ''
        prefix = f"Năm {values['nam']}, " if values.get('nam') else "Theo dữ liệu hiện có, "
        _, unit = _numeric_answer_meta(plan.target_col)
        count_text = ''
        if 'so_ho' in result.columns:
            count_subject = subject if subject != "hộ" else "hộ"
            count_text = f", tính trên {_format_vi_number(first['so_ho'])} {count_subject}"
        return f'{prefix}{subject}{district} có bình quân {_format_vi_number(metric_value, 2)} {unit}{count_text}.'
    if plan.metric == 'avg':
        filter_context = ' '.join(_important_filter_phrases(plan, {'phan_loai', 'huyen', 'xa_phuong', 'nam', 'gioi_tinh', 'nhom_chu_ho_nu'}))
        if any((item.col in {'gioi_tinh', 'nhom_chu_ho_nu'} and item.value in ('Nữ', 1) for item in plan.filters)):
            filter_context = ('chủ hộ nữ ' + filter_context).strip()
        filter_context = f' trong nhóm {filter_context}' if filter_context else ''
        _, unit = _numeric_answer_meta(plan.target_col)
        return f'Cao nhất là {labels} với {_format_vi_number(metric_value, 2)} {unit}{filter_context}.'
    rank_label = 'ít nhất' if plan.order_by and plan.order_by.direction == 'asc' else 'đứng đầu'
    if plan.task == 'group_aggregate' and {'so_tre_thieu', 'so_ho_co_tre_thieu', 'tong_tre', ratio_col} <= set(result.columns):
        display_result = result.head(plan.limit) if plan.limit else result.head(10)
        label_cols = groups or [col for col in ('chi_tieu', 'huyen', 'xa_phuong', 'nam') if col in result.columns]
        lines = []
        for _, row in display_result.iterrows():
            group_label = ', '.join(
                MISSING_TEXT_LABEL if pd.isna(row[col]) else str(row[col])
                for col in label_cols
            )
            lines.append(
                f"- {group_label}: {_format_vi_number(row['so_tre_thieu'])} trẻ em thiếu, "
                f"{_format_vi_number(row['so_ho_co_tre_thieu'])} hộ có trẻ thiếu, "
                f"mẫu số {_format_vi_number(row['tong_tre'])} trẻ em, "
                f"{_format_vi_number(row[ratio_col], 1)}%"
            )
        if plan.group_by == ['tre_em'] or 'chi_tieu' in result.columns:
            return "Thiếu hụt của trẻ em theo từng chỉ tiêu:\n" + '\n'.join(lines)
        return "Kết quả theo từng nhóm:\n" + '\n'.join(lines)
    if plan.task == 'group_aggregate' and plan.metric == 'sum':
        metric_col = result.columns[-1]
        unit = 'trẻ em' if plan.target_col in {'so_tre_thieu_bhyt', 'so_tre_thieu_dinh_duong', 'so_tre_thieu_di_hoc', 'so_tre_em'} else ''
        display_group_cols = groups
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        year = f"năm {values['nam']}" if values.get('nam') else 'theo dữ liệu hiện có'
        if plan.limit == 1 and len(result) == 1:
            group_label = ', '.join(str(result.iloc[0][col]) for col in display_group_cols)
            value_text = _format_vi_number(result.iloc[0][metric_col])
            suffix = f" {unit}" if unit else ""
            prefix = 'huyện ' if plan.group_by == ['huyen'] else ''
            return f"{year.capitalize()}, {prefix}{group_label} đứng đầu với {value_text}{suffix}."
        lines = []
        for _, row in result.head(plan.limit or 10).iterrows():
            group_label = ', '.join(str(row[col]) for col in display_group_cols)
            suffix = f" {unit}" if unit else ""
            lines.append(f"- {group_label}: {_format_vi_number(row[metric_col])}{suffix}")
        return f"{year.capitalize()}, kết quả theo từng nhóm:\n" + '\n'.join(lines)
    if plan.task == 'group_aggregate' and plan.metric == 'ratio':
        ratio_col = 'ty_le_pct' if 'ty_le_pct' in result.columns else 'ty_le_%'
        display_result = result.head(plan.limit) if plan.limit else result
        lines = []
        varying_denominators = (
            'tong_ho' in display_result.columns
            and display_result['tong_ho'].nunique(dropna=True) > 1
        )
        for _, row in display_result.iterrows():
            group_label = ', '.join(
                MISSING_TEXT_LABEL if pd.isna(row[col]) else str(row[col])
                for col in groups
            )
            if varying_denominators:
                lines.append(
                    f'- {group_label}: {_format_vi_number(row["so_ho"])}/'
                    f'{_format_vi_number(row["tong_ho"])} hộ, {_format_vi_number(row[ratio_col], 1)}%'
                )
            else:
                lines.append(
                    f'- {group_label}: {_format_vi_number(row["so_ho"])} hộ, '
                    f'{_format_vi_number(row[ratio_col], 1)}%'
                )
        denominator = int(result['tong_ho'].iloc[0]) if 'tong_ho' in result.columns else 0
        denominator_text = f' (mẫu số: {_format_vi_number(denominator)} hộ)' if denominator and not varying_denominators else ''
        scope_note = ' trên toàn bộ các phân loại hộ' if _is_unscoped_deprivation_question(plan, question) else ''
        return f'Tỷ lệ theo từng nhóm{scope_note}{denominator_text}:\n' + '\n'.join(lines)
    if plan.task == 'group_aggregate' and plan.metric == 'count_households':
        metric_col = 'so_ho' if 'so_ho' in result.columns else result.columns[-1]
        display_group_cols = groups
        count_unit = 'trẻ em' if metric_col in {'so_tre_em', 'tong_tre_em', 'count_children', 'tong_tre_thieu_bhyt', 'tong_tre_thieu_dinh_duong', 'tong_tre_thieu_di_hoc'} else 'hộ'
        values = {item.col: item.value for item in plan.filters if item.op == '='}
        subject = str(values.get('phan_loai', 'hộ')).lower()
        year = f"năm {values['nam']}" if values.get('nam') else 'theo dữ liệu hiện có'
        conditions = _important_filter_phrases(plan, {'phan_loai', 'huyen', 'xa_phuong', 'nam'})
        condition_text = ''
        if conditions:
            condition_text = ' ' + _join_vietnamese_phrases(conditions)

        # Chuỗi theo năm là trình tự thời gian, không phải bảng xếp hạng.
        if plan.group_by == ['nam'] and 'nam' in result.columns:
            chronological = result.sort_values(
                'nam',
                key=lambda series: pd.to_numeric(series, errors='coerce'),
            )
            if values.get('xa_phuong'):
                scope = f" tại {values['xa_phuong']}"
            elif values.get('huyen'):
                scope = f" tại {values['huyen']}"
            elif any(term in q_key for term in ('toan tinh', 'ca tinh')):
                scope = ' của toàn tỉnh'
            else:
                scope = ''
            lines = [
                f"- Năm {row['nam']}: {_format_vi_number(row[metric_col])} hộ"
                for _, row in chronological.iterrows()
            ]
            return f"Số {subject} theo năm{scope}:\n" + '\n'.join(lines)

        q_distinct = any(vn_name_key(term) in q_key for term in DISTINCT_VALUE_TERMS)
        open_ended_group_list = any(x in q_key for x in (
            'cac huyen', 'nhung huyen', 'liet ke huyen',
            'cac xa', 'nhung xa', 'liet ke xa',
            'cac dan toc', 'nhung dan toc', 'liet ke dan toc',
        ))
        share_output = (
            'ty_le_%' in result.columns
            and plan.group_by
            and any(x in q_key for x in (
                'ty le',
                'ti le',
                'phan tram',
                'ty trong',
                'ti trong',
                'co cau',
                'phan bo',
                'tren tong',
                'trong tong',
            ))
        )

        if share_output and plan.limit is None:
            display_result = result
        elif 'loai_ho_tro' in result.columns:
            display_result = result.head(10)
        else:
            display_result = result if (q_distinct or open_ended_group_list) and plan.limit is None else result.head(5)

        lines = []
        for _, row in display_result.iterrows():
            group_label = ', '.join(
                MISSING_TEXT_LABEL if pd.isna(row[col]) else str(row[col])
                for col in display_group_cols
            )

            if share_output:
                lines.append(
                    f'- {group_label}: {_format_vi_number(row[metric_col])} hộ, '
                    f'{_format_vi_number(row["ty_le_%"], 1)}%'
                )
            else:
                lines.append(f'- {group_label}: {_format_vi_number(row[metric_col])} {count_unit}')
        if q_distinct and display_group_cols:
            values_text = ', '.join(
                MISSING_TEXT_LABEL if pd.isna(value) else str(value)
                for value in result[display_group_cols[0]].tolist()
            )
            return f'Có {_format_vi_number(len(result))} giá trị khác nhau: {values_text}.'
        if share_output and not is_ranking:
            return f'{year.capitalize()}, cơ cấu trong nhóm {subject}{condition_text}:\n' + '\n'.join(lines)
        if 'loai_ho_tro' in result.columns:
            return f'{year.capitalize()}, trong nhóm {subject}{condition_text}, các nội dung hỗ trợ được ghi nhận:\n' + '\n'.join(lines)
        if is_distribution and (not is_ranking):
            return f'{year.capitalize()}, thống kê trong nhóm {subject}{condition_text}:\n' + '\n'.join(lines)
        if plan.limit and plan.limit > 1 and _is_top_list_question(question):
            actual_limit = min(plan.limit, len(result))
            display_rows = result.head(actual_limit)

            top_lines = []
            for idx, (_, row) in enumerate(display_rows.iterrows(), start=1):
                group_label = ', '.join((str(row[col]) for col in display_group_cols))
                top_lines.append(f'- Hạng {idx}: {group_label}: {_format_vi_number(row[metric_col])} {count_unit}')

            note = ''
            if actual_limit < plan.limit:
                note = f'\n\nLưu ý: Dữ liệu chỉ có {_format_vi_number(actual_limit)} kết quả phù hợp, nên không đủ top {plan.limit}.'

            return (
                f'{year.capitalize()}, top {actual_limit} trong nhóm {subject}{condition_text}:\n'
                + '\n'.join(top_lines)
                + note
            )
        explicit_rank_match = re.search(
            r'\b(hạng|hang)\s*(\d+)\b|'
            r'\b(thứ|thu)\s*(nhì|hai|ba|tư|tu|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)\b',
            q_key,
        )

        rank_word_map = {
            'nhì': 2, 'hai': 2,
            'ba': 3,
            'tư': 4, 'tu': 4,
            'năm': 5, 'nam': 5,
            'sáu': 6, 'sau': 6,
            'bảy': 7, 'bay': 7,
            'tám': 8, 'tam': 8,
            'chín': 9, 'chin': 9,
            'mười': 10, 'muoi': 10,
        }

        if explicit_rank_match:
            if explicit_rank_match.group(2):
                rank_pos = int(explicit_rank_match.group(2))
            else:
                rank_pos = rank_word_map.get(explicit_rank_match.group(4), 1)
        else:
            rank_pos = 1

        rank_idx = min(rank_pos - 1, len(result) - 1)
        rank_row = result.iloc[rank_idx]
        rank_value = int(rank_row[metric_col])

        rank_labels = {1: 'đứng đầu', 2: 'đứng thứ nhì', 3: 'đứng thứ ba', 4: 'đứng thứ tư', 5: 'đứng thứ năm'}
        if plan.order_by and plan.order_by.direction == 'asc':
            rank_text = 'ít nhất' if rank_pos == 1 else rank_labels.get(rank_pos, f'đứng thứ {rank_pos} từ dưới lên')
        else:
            rank_text = rank_labels.get(rank_pos, f'đứng thứ {rank_pos}')

        group_prefix = 'huyện ' if plan.group_by == ['huyen'] else ''

        # Nếu _expand_ties_for_single_best đã trả nhiều dòng đồng hạng
        if plan.limit == 1 and plan.order_by and len(result) > 1:
            tied_lines = []
            for _, row in result.head(10).iterrows():
                group_label = ', '.join((str(row[col]) for col in display_group_cols))
                tied_lines.append(f'- {group_prefix}{group_label}: {_format_vi_number(row[metric_col])} {count_unit}')

            extra = f'\n... và còn {len(result) - 10} kết quả đồng hạng khác.' if len(result) > 10 else ''
            return (
                f'{year.capitalize()}, trong nhóm {subject}{condition_text}, '
                f'có {_format_vi_number(len(result))} kết quả cùng {rank_text} với {_format_vi_number(rank_value)} {count_unit}:\n'
                + '\n'.join(tied_lines)
                + extra
            )

        rank_group_label = ', '.join((str(rank_row[col]) for col in display_group_cols))
        first_line = f'{year.capitalize()}, trong nhóm {subject}{condition_text}, {group_prefix}{rank_group_label} {rank_text} với {_format_vi_number(rank_value)} {count_unit}.'
        highest_signal = any(x in q_key for x in ('cao nhat', 'nhieu nhat', 'lon nhat', 'dung dau', 'dan dau', 'top'))
        lowest_signal = any(x in q_key for x in ('thap nhat', 'it nhat', 'nho nhat', 'thap hon', 'chot', 'bet', 'cuoi bang'))
        if highest_signal and lowest_signal and len(result) >= 2 and metric_col in result.columns:
            max_row = result.loc[result[metric_col].idxmax()]
            min_row = result.loc[result[metric_col].idxmin()]
            max_label = ', '.join((str(max_row[col]) for col in display_group_cols))
            min_label = ', '.join((str(min_row[col]) for col in display_group_cols))
            return (
                f'{year.capitalize()}, trong nhóm {subject}{condition_text}, '
                f'{group_prefix}{max_label} cao nhất với {_format_vi_number(max_row[metric_col])} {count_unit}; '
                f'{group_prefix}{min_label} thấp nhất với {_format_vi_number(min_row[metric_col])} {count_unit}.'
            )
        if is_ranking:
            return first_line
        return first_line + '\n' + '\n'.join(lines)
    return f'{rank_label} {labels} với {_format_vi_number(metric_value)} hộ.'
