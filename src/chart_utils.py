"""
chart_utils.py — Helper vẽ biểu đồ từ DataFrame kết quả Q&A.

Cung cấp:
  detect_chart_request() — phát hiện câu hỏi yêu cầu biểu đồ
  infer_chart_type()     — suy luận loại biểu đồ từ DataFrame
  is_chartable()         — kiểm tra DataFrame có thể vẽ biểu đồ
  make_chart()           — tạo Plotly figure từ DataFrame
  export_xlsx()          — xuất bảng XLSX
  export_chart_png()     — xuất biểu đồ PNG
  _safe_title()          — tạo tiêu đề biểu đồ an toàn
"""
from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Mapping
import pandas as pd

# ── Optional imports ─────────────────────────────────────────────────────────
try:
    import plotly.express as px
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

try:
    import openpyxl  # noqa: F401
    _OPENPYXL = True
except ImportError:
    _OPENPYXL = False

_CHART_KEYWORDS = (
    "biểu đồ", "bieu do", "vẽ", "ve ", "chart", "plot",
    "pie", "donut", "bánh", "banh",
    "cột", "col ", "bar", "histogram",
    "đường", "duong", "line", "trend", "xu hướng",
    "trực quan", "visual",
)

_CHART_TYPE_HINTS: dict[str, str] = {
    "pie": "pie", "donut": "pie", "bánh": "pie", "banh": "pie", "tròn": "pie", "tron": "pie",
    "bar": "bar", "cột": "bar", "cot": "bar",
    "line": "line", "đường": "line", "duong": "line", "xu hướng": "line", "trend": "line",
}

def detect_chart_request(question: str) -> tuple[bool, str | None]:
    """
    Trả về (is_chart_request, chart_type_hint).
    chart_type_hint: 'bar' | 'pie' | 'line' | None
    """
    q = question.lower()
    if not any(kw in q for kw in _CHART_KEYWORDS):
        return False, None
    for kw, ctype in _CHART_TYPE_HINTS.items():
        if kw in q:
            return True, ctype
    return True, None

_VN_LABELS: dict[str, str] = {
    "phan_loai": "Phân loại hộ",
    "bien_dong_dau_ky": "Biến động đầu kỳ",
    "nhom_ngheo_tong_hop": "Nhóm nghèo tổng hợp",
    "huyen": "Huyện",
    "xa_phuong": "Xã/Phường",
    "dan_toc_chi_tiet": "Dân tộc",
    "gioi_tinh": "Giới tính",
    "nam": "Năm",
    "chi_so": "Chỉ số",
    "chi_tieu": "Chỉ tiêu",
    "so_ho": "Số hộ",
    "muc_giam": "Mức giảm (hộ)",
    "muc_tang": "Mức tăng (hộ)",
    "muc_bien_dong": "Mức biến động (hộ)",
    "avg_thu_nhap_bq": "Thu nhập BQ (nghìn đ)",
    "ratio": "Tỷ lệ (%)",
    "ty_le_%": "Tỷ lệ (%)",
    "ty_le_pct": "Tỷ lệ (%)",
}

def vn_name_key(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("đ", "d")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _value_columns(df: pd.DataFrame) -> list[str]:
    label_candidates = ["huyen", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "nam", "chi_so", "chi_tieu"]
    label_cols = [c for c in label_candidates if c in df.columns]
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    return [c for c in numeric_cols if c not in label_cols and c not in {"__total_count"}]


def _main_value_col(df: pd.DataFrame) -> str | None:
    value_cols = _value_columns(df)
    for preferred in ("muc_giam", "muc_tang", "muc_bien_dong", "so_ho", "ty_le_%", "avg_thu_nhap_bq", "tb_thu_nhap_nghin_dong", "bien_dong"):
        if preferred in value_cols:
            return preferred
    return value_cols[0] if value_cols else None


def _has_composition_signal(question: str) -> bool:
    q = (question or "").lower()
    q_key = vn_name_key(question)
    return (
        any(x in q for x in ("cơ cấu", "tỷ trọng", "tỉ trọng", "phân bố", "phân bổ"))
        or any(x in q_key for x in ("co cau", "ty trong", "ti trong", "phan bo"))
    )


def _has_shared_total_signal(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return any(x in q_key for x in ("tren tong", "trong tong", "tong so", "tong ho"))


def _has_part_to_whole_signal(question: str) -> bool:
    q_key = vn_name_key(question or "")
    composition = _has_composition_signal(question) or any(
        x in q_key for x in ("chiem bao nhieu phan tram", "chiem ty le")
    )
    share_language = any(x in q_key for x in ("ty le", "ti le", "phan tram"))
    return composition or (share_language and _has_shared_total_signal(question))


def _has_same_population_total_signal(question: str) -> bool:
    """Detect a denominator that repeats the numerator household population."""
    q_key = vn_name_key(question or "")
    for population in ("ho ngheo", "ho can ngheo", "ho khong ngheo"):
        if population in q_key and re.search(
            rf"\b(?:tren|trong)\s+tong(?:\s+so)?\s+{population}\b",
            q_key,
        ):
            return True
    return False


def _has_independent_ratio_signal(question: str) -> bool:
    q_key = vn_name_key(question)
    return any(x in q_key for x in ("ty le", "ti le", "phan tram", "percentage", "ratio"))


def _has_time_series_signal(question: str) -> bool:
    q_key = vn_name_key(question or "")
    years = set(re.findall(r"\b20\d{2}\b", q_key))
    phrase_signal = any(x in q_key for x in (
        "qua cac nam", "theo nam", "tung nam", "giai doan", "xu huong",
        "bien dong", "tang giam", "tang", "giam", "trend", "bieu do duong", "line",
    ))
    range_signal = re.search(
        r"\btu(?: nam)?\s+20\d{2}\s+den(?: nam)?\s+20\d{2}\b",
        q_key,
    ) is not None
    return bool(phrase_signal or range_signal or len(years) >= 2)


def _has_ranking_signal(question: str) -> bool:
    q_key = vn_name_key(question or "")
    return bool(
        re.search(r"\btop\s*\d*\b", q_key)
        or any(x in q_key for x in (
            "xep hang", "cao nhat", "thap nhat", "nhieu nhat", "it nhat",
            "lon nhat", "nho nhat", "dung dau", "cuoi bang",
        ))
    )


def _has_change_word(question: str, direction: str | None = None) -> bool:
    q_key = vn_name_key(question or "")
    if direction == "decrease":
        return bool(re.search(r"(?<![a-z0-9_])giam(?![a-z0-9_])", q_key))
    if direction == "increase":
        return bool(re.search(r"(?<![a-z0-9_])tang(?![a-z0-9_])", q_key))
    return bool(re.search(r"(?<![a-z0-9_])(?:giam|tang|bien dong|chenh lech)(?![a-z0-9_])", q_key))


def _has_change_ranking_signal(question: str) -> bool:
    """Ranking theo mức tăng/giảm, ví dụ 'huyện nào giảm nhiều nhất'."""
    q_key = vn_name_key(question or "")
    if not _has_change_word(question):
        return False
    if _has_ranking_signal(question):
        return True
    return bool(re.search(r"\bhuyen\s+nao\b", q_key) and re.search(r"\b(?:giam|tang)\b", q_key))


def _explicit_line_or_pie_request(question: str) -> bool:
    is_request, hinted = detect_chart_request(question or "")
    return bool(is_request and hinted in {"line", "pie"})


def _change_col(df: pd.DataFrame) -> str | None:
    for col in ("bien_dong", "chenh_lech"):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            return col
    return None


def _change_ranking_label_col(df: pd.DataFrame) -> str | None:
    for col in (
        "huyen", "xa_phuong", "xa", "phan_loai", "bien_dong_dau_ky",
        "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "chi_so", "chi_tieu",
    ):
        if col in df.columns:
            return col
    return None


def _is_wide_year_compare_df(df: pd.DataFrame) -> bool:
    return bool(
        isinstance(df, pd.DataFrame)
        and {"so_ho_2023", "so_ho_2024"}.issubset(df.columns)
        and _change_col(df) is not None
        and _change_ranking_label_col(df) is not None
    )


def _should_use_change_ranking_chart(df: pd.DataFrame, question: str = "", plan=None) -> bool:
    """
    Với câu 'vẽ biểu đồ huyện nào giảm/tăng nhiều nhất', không melt 2023/2024
    thành line 2 điểm. Biểu đồ phù hợp hơn là bar theo mức biến động.

    Nếu caller truyền full ranking trước limit=1, chart sẽ hiển thị đủ các huyện.
    Nếu caller chỉ truyền top-1, chart vẫn là 1 cột mức giảm/tăng thay vì line 2 điểm.
    """
    if not _is_wide_year_compare_df(df):
        return False
    if _explicit_line_or_pie_request(question):
        return False
    task = _plan_task(plan)
    group_by = set(_plan_group_by(plan))
    has_group_context = bool(group_by & {"huyen", "xa", "xa_phuong", "phan_loai"}) or _change_ranking_label_col(df) is not None
    return bool(has_group_context and _has_change_ranking_signal(question))


def _change_ranking_value_name(question: str) -> str:
    if _has_change_word(question, "decrease"):
        return "muc_giam"
    if _has_change_word(question, "increase"):
        return "muc_tang"
    return "muc_bien_dong"


def _prepare_change_ranking_chart_df(df: pd.DataFrame, question: str = "") -> pd.DataFrame:
    label_col = _change_ranking_label_col(df)
    change_col = _change_col(df)
    if label_col is None or change_col is None:
        return df

    out = df.copy()
    delta = pd.to_numeric(out[change_col], errors="coerce")
    value_name = _change_ranking_value_name(question)
    if value_name == "muc_giam":
        out[value_name] = delta.where(delta < 0, 0).abs()
    elif value_name == "muc_tang":
        out[value_name] = delta.where(delta > 0, 0)
    else:
        out[value_name] = delta.abs()

    q_key = vn_name_key(question or "")
    ascending = any(token in q_key for token in ("it nhat", "nho nhat", "thap nhat", "cuoi bang"))
    out = out.sort_values(value_name, ascending=ascending, kind="stable")

    keep_cols = [label_col, value_name]
    # Giữ các số phụ để build_chart_answer có thể nói rõ 2023 -> 2024 nếu cần,
    # nhưng value chính của biểu đồ vẫn là muc_giam/muc_tang/muc_bien_dong.
    for col in ("so_ho_2023", "so_ho_2024", change_col):
        if col in out.columns and col not in keep_cols:
            keep_cols.append(col)
    return out[keep_cols].reset_index(drop=True)


def _plan_metric(plan) -> str | None:
    if isinstance(plan, Mapping):
        return plan.get("metric")
    return getattr(plan, "metric", None)


def _plan_task(plan) -> str | None:
    if isinstance(plan, Mapping):
        return plan.get("task")
    return getattr(plan, "task", None)


def _plan_group_by(plan) -> list[str]:
    if isinstance(plan, Mapping):
        value = plan.get("group_by")
    else:
        value = getattr(plan, "group_by", None)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _is_ratio_value_col(column: str) -> bool:
    key = vn_name_key(str(column))
    return (
        str(column) in {"ty_le_%", "ty_le_pct", "ratio", "percentage"}
        or any(x in key for x in ("ty le", "ti le", "ratio", "percentage", "phan tram"))
    )


def chart_semantics(df: pd.DataFrame, question: str = "", plan=None) -> str:
    """Phân loại semantic biểu đồ, không suy ra ratio chỉ vì có cột tỷ lệ phụ."""
    metric = _plan_metric(plan)
    value_cols = _value_columns(df) if isinstance(df, pd.DataFrame) else []
    has_count_value = any(
        col == "so_ho" or str(col).startswith(("so_", "sum_", "count_"))
        for col in value_cols
    )
    q_key = vn_name_key(question or "")
    overlapping_indicators = bool(
        (set(_plan_group_by(plan)) & {"chi_so", "chi_tieu"} or _plan_task(plan) == "multi_metric_table")
        and any(x in q_key for x in ("thieu hut", "dvxh", "dich vu xa hoi", "nguyen nhan"))
    )
    if metric == "ratio" and _has_part_to_whole_signal(question) and _has_same_population_total_signal(question):
        return "composition"
    if metric == "ratio":
        return "independent_ratio"
    if overlapping_indicators:
        return "comparison"
    if metric in {"count_households", "sum"} and _has_part_to_whole_signal(question):
        return "composition"
    if metric is None and _has_part_to_whole_signal(question) and has_count_value:
        return "composition"
    if _has_independent_ratio_signal(question) and any(_is_ratio_value_col(col) for col in value_cols):
        return "independent_ratio"
    main_value = _main_value_col(df) if isinstance(df, pd.DataFrame) else None
    if (main_value and _is_ratio_value_col(main_value)) or (
        value_cols and all(_is_ratio_value_col(col) for col in value_cols)
    ):
        return "independent_ratio"
    return "comparison"


def pie_block_reason(df: pd.DataFrame, question: str = "", plan=None) -> str | None:
    MAX_PIE_GROUPS = 8
    semantics = chart_semantics(df, question, plan)
    if semantics == "independent_ratio":
        return "independent_ratio"
    if df is not None and len(df) < 2:
        return "too_few_groups"
    if df is not None and len(df) > MAX_PIE_GROUPS:
        return "too_many_groups"
    if semantics != "composition":
        return "not_composition"
    return None


def _can_pie(df: pd.DataFrame, question: str = "", plan=None) -> bool:
    """Pie chỉ dùng cho cơ cấu một tổng, không dùng cho ranking/địa bàn/time-series/multi-metric."""
    if df is None or df.empty or len(df) < 2 or pie_block_reason(df, question, plan) is not None:
        return False
    if "nam" in df.columns:
        return False
    value_cols = _value_columns(df)
    count_value = "so_ho" if "so_ho" in value_cols else next(
        (col for col in value_cols if not _is_ratio_value_col(col)),
        None,
    )
    if count_value is None:
        return False

    label_cols = [
        c for c in (
            "huyen", "xa_phuong", "phan_loai", "gioi_tinh", "muc_do_thieu_hut",
            "tinh_trang_nha", "bien_dong_dau_ky", "nhom_ngheo_tong_hop",
            "dan_toc_chi_tiet", "chi_so", "chi_tieu",
        )
        if c in df.columns
    ]
    if not label_cols:
        return False

    if _has_ranking_signal(question):
        return False

    return True


def _can_line(df: pd.DataFrame, question: str = "") -> bool:
    """Line chỉ dùng khi trục X là thời gian/năm, không nối các huyện/xã/dân tộc."""
    if df is None or df.empty or "nam" not in df.columns:
        return False
    if _main_value_col(df) is None:
        return False
    return df["nam"].astype(str).nunique() >= 2


def allowed_chart_types(df: pd.DataFrame, question: str = "", plan=None) -> list[str]:
    if not is_chartable(df):
        return []

    allowed = ["bar"]

    # Hai mốc rời rạc dùng bar, bất kể có hay không có chiều danh mục. Line chỉ
    # dành cho yêu cầu trend rõ ràng hoặc chuỗi thời gian có trên hai mốc.
    if _can_line(df, question) and (
        _has_time_series_signal(question)
        or df["nam"].astype(str).nunique(dropna=True) > 2
    ):
        allowed.append("line")

    if _can_pie(df, question, plan):
        allowed.append("pie")

    return allowed

def resolve_requested_chart_type(requested: str | None, allowed: list[str]) -> tuple[str | None, bool]:
    """Chọn loại trực tiếp; nếu không hợp lệ thì ưu tiên bar làm fallback."""
    if requested in allowed:
        return requested, False
    if "bar" in allowed:
        return "bar", True
    return (allowed[0], True) if allowed else (None, True)


def determine_chart_type(
    question: str,
    df: pd.DataFrame,
    group_by=None,
    metric: str | None = None,
    requested_chart_type: str | None = None,
    plan=None,
) -> str:
    """Apply one semantic priority order for direct and recommended charts."""
    if plan is None:
        plan = {"group_by": group_by or [], "metric": metric}
    allowed = allowed_chart_types(df, question, plan)
    if not allowed:
        return "bar"

    detected_request, detected_type = detect_chart_request(question)
    requested = requested_chart_type or (detected_type if detected_request else None)
    if requested in allowed:
        return requested
    if "line" in allowed and _has_time_series_signal(question):
        return "line"
    if "pie" in allowed and chart_semantics(df, question, plan) == "composition":
        return "pie"
    return "bar" if "bar" in allowed else allowed[0]


def infer_chart_type(df: pd.DataFrame, question: str = "", plan=None) -> str:
    return determine_chart_type(question, df, plan=plan)


def _is_single_row_chartable_change_df(df: pd.DataFrame) -> bool:
    """Cho phép explicit chart top-1 tăng/giảm dùng một cột bar duy nhất.

    App hiện thường kiểm is_chartable(result_df) trước khi gọi prepare_chart_df().
    Với câu kiểu "vẽ biểu đồ huyện nào giảm nhiều nhất...", result_df chỉ còn
    1 dòng do limit=1 nhưng vẫn có đủ nhãn + so_ho_2023/2024 + biến động để
    dựng biểu đồ mức giảm/mức tăng.
    """
    if df is None or df.empty or len(df) != 1:
        return False
    if _is_wide_year_compare_df(df):
        return True
    label_candidates = [
        "huyen", "xa", "xa_phuong", "phan_loai", "bien_dong_dau_ky",
        "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh",
        "chi_so", "chi_tieu",
    ]
    label_cols = [c for c in label_candidates if c in df.columns]
    value_cols = [c for c in ("muc_giam", "muc_tang", "muc_bien_dong") if c in df.columns]
    return bool(label_cols) and bool(value_cols)


def is_chartable(df: pd.DataFrame) -> bool:
    """Kiểm tra DataFrame có nhãn + ít nhất một cột số để vẽ biểu đồ."""
    if df is None or df.empty:
        return False

    label_candidates = ["huyen", "xa", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "nam", "chi_so", "chi_tieu", "muc_do_thieu_hut", "tinh_trang_nha"]
    label_cols = [c for c in label_candidates if c in df.columns]
    value_cols = _value_columns(df)

    if bool(label_cols) and bool(value_cols) and len(df) >= 2:
        return True
    return _is_single_row_chartable_change_df(df)


def make_chart(
    df: pd.DataFrame,
    chart_type: str = "bar",
    title: str = "",
    question: str = "",
    plan=None,
):
    """
    Tạo Plotly figure từ DataFrame đã chuẩn hóa bởi prepare_chart_df().
    Nguyên tắc:
    - line: chỉ chạy theo nam
    - pie: chỉ chạy cho cơ cấu hợp lệ
    - bar: dùng màu để so sánh nam / phan_loai / chi_tieu khi có
    """
    if not _PLOTLY or df is None or df.empty:
        return None

    if chart_type not in allowed_chart_types(df, question, plan):
        chart_type = "bar"

    value_col = _main_value_col(df)
    if not value_col:
        return None

    y_label = _VN_LABELS.get(value_col, value_col.replace("_", " ").title())
    chart_meta = {
        "chart_type": chart_type,
        "x_col": None,
        "y_col": value_col,
        "color_col": None,
        "series_labels": [],
    }

    try:
        if chart_type == "pie":
            name_candidates = [
                "huyen",
                "xa_phuong",
                "phan_loai",
                "bien_dong_dau_ky",
                "nhom_ngheo_tong_hop",
                "gioi_tinh",
                "muc_do_thieu_hut",
                "tinh_trang_nha",
                "dan_toc_chi_tiet",
                "chi_so",
                "chi_tieu",
            ]
            name_col = next((c for c in name_candidates if c in df.columns), None)
            if not name_col:
                return None
            fig = px.pie(
                df,
                names=name_col,
                values=value_col,
                title="",
            )
            fig.update_traces(textinfo="label+percent+value")

        elif chart_type == "line":
            if "nam" not in df.columns:
                return None

            plot_df = df.copy()
            series_cols = [
                c for c in ["huyen", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "chi_so", "chi_tieu", "dan_toc_chi_tiet", "gioi_tinh"]
                if c in plot_df.columns
            ]
            if len(series_cols) >= 2:
                # Không để Plotly gộp các dimension độc lập vào cùng một
                # đường. Ví dụ huyen + phan_loai phải tạo đủ 2 x 2 series.
                plot_df["series_label"] = plot_df[series_cols].astype(str).agg(" - ".join, axis=1)
                color_col = "series_label"
            else:
                color_col = series_cols[0] if series_cols else None

            chart_meta.update({
                "x_col": "nam",
                "color_col": color_col,
                "series_labels": (
                    plot_df[color_col].dropna().astype(str).drop_duplicates().tolist()
                    if color_col else []
                ),
            })

            fig = px.line(
                plot_df.sort_values("nam"),
                x="nam",
                y=value_col,
                color=color_col,
                title="",
                markers=True,
                labels={"nam": _VN_LABELS.get("nam", "Năm"), value_col: y_label, "series_label": "Nhóm"},
            )

        else:
            # So sánh theo năm: x là nhóm địa bàn/loại, màu là năm.
            if "nam" in df.columns:
                x_col = next((c for c in ["huyen", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "chi_so", "chi_tieu"] if c in df.columns), "nam")
                color_col = "nam" if x_col != "nam" else None
            else:
                x_col = next((c for c in ["huyen", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "muc_do_thieu_hut", "tinh_trang_nha", "chi_so", "chi_tieu"] if c in df.columns), None)
                color_col = next((c for c in ["phan_loai", "chi_so", "chi_tieu"] if c in df.columns and c != x_col), None)
            if not x_col:
                return None

            x_label = _VN_LABELS.get(x_col, x_col.replace("_", " ").title())
            fig = px.bar(
                df,
                x=x_col,
                y=value_col,
                color=color_col,
                barmode="group",
                title="",
                text=value_col,
                labels={x_col: x_label, value_col: y_label},
            )
            fig.update_traces(texttemplate="%{text:,}", textposition="outside")
            fig.update_layout(showlegend=bool(color_col), xaxis_tickangle=-30)
            chart_meta.update({
                "x_col": x_col,
                "color_col": color_col,
                "series_labels": (
                    df[color_col].dropna().astype(str).drop_duplicates().tolist()
                    if color_col else []
                ),
            })

        fig.update_layout(
            title_text="",
            meta=chart_meta,
            margin=dict(t=20, b=80, l=40, r=20),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    except Exception:
        return None

def export_xlsx(df: pd.DataFrame, title: str = "Bảng thống kê") -> bytes:
    """Xuất DataFrame ra XLSX bytes."""
    buf = io.BytesIO()
    if not _OPENPYXL:
        df.to_csv(buf, index=False)
        return buf.getvalue()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Data", index=False)
        ws = writer.sheets["Data"]
        for col_cells in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col_cells), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 40)
    return buf.getvalue()

def prepare_chart_df(df: pd.DataFrame, question: str = "", plan=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()
    # Chuẩn hóa thứ tự thời gian ngay ở chart_df để dữ liệu vẽ và df_head
    # trong chart_debug cùng phản ánh thứ tự năm tăng dần.
    if "nam" in out.columns:
        out = out.assign(__nam_sort=pd.to_numeric(out["nam"], errors="coerce"))
        out = out.sort_values("__nam_sort", kind="stable").drop(columns="__nam_sort").reset_index(drop=True)

    # Ranking theo mức tăng/giảm: ưu tiên bar theo mức biến động, không melt
    # 2023/2024 thành line 2 điểm cho riêng top-1. Nếu app truyền full ranking
    # trước limit=1, chart này sẽ hiển thị đầy đủ các địa bàn.
    if _should_use_change_ranking_chart(out, question, plan):
        return _prepare_change_ranking_chart_df(out, question)

    # Bảng so sánh 2023/2024: chỉ đưa 2 cột số hộ vào chart.
    # Dùng value_name tạm để tránh lỗi pandas khi DataFrame gốc có sẵn cột so_ho.
    if {"so_ho_2023", "so_ho_2024"}.issubset(out.columns):
        id_vars = [
            c for c in ["huyen", "xa_phuong", "phan_loai", "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "gioi_tinh", "chi_so"]
            if c in out.columns
        ]
        chart_df = out[id_vars + ["so_ho_2023", "so_ho_2024"]].melt(
            id_vars=id_vars,
            value_vars=["so_ho_2023", "so_ho_2024"],
            var_name="nam",
            value_name="__value",
        )
        chart_df = chart_df.rename(columns={"__value": "so_ho"})
        chart_df["nam"] = chart_df["nam"].astype(str).str.extract(r"(20\d{2})", expand=False)
        return chart_df.sort_values("nam", kind="stable").reset_index(drop=True)

    label_candidates = [
        "huyen", "xa_phuong", "phan_loai", "dan_toc_chi_tiet", "gioi_tinh", "nam",
        "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "muc_do_thieu_hut", "tinh_trang_nha", "chi_so", "chi_tieu",
    ]
    label_cols = [c for c in label_candidates if c in out.columns]

    # Bảng cơ cấu có thể được enrich thêm ty_le_%; biểu đồ cơ cấu vẫn dùng một
    # metric số lượng duy nhất để pie/bar không bị hiểu thành multi-metric.
    # Context/denominator totals belong in the table, not in chart series.
    if _plan_task(plan) == "multi_metric_table":
        metric_vars = [
            c for c in _value_columns(out)
            if not (
                c == "tong_ho"
                or c.startswith("tong_ho_")
                or c in {"ty_le_%", "ty_le_pct", "__total_count"}
            )
        ]
        if label_cols and metric_vars:
            chart_df = out[label_cols + metric_vars].melt(
                id_vars=label_cols,
                value_vars=metric_vars,
                var_name="chi_tieu",
                value_name="__value",
            )
            return chart_df.rename(columns={"__value": "so_ho"})

    q_key = vn_name_key(question)
    semantics = chart_semantics(out, question, plan)
    if semantics == "composition" and "so_ho" in out.columns:
        composition_labels = [
            col for col in label_cols
            if col != "nam"
        ]
        if composition_labels:
            return out[[composition_labels[0], "so_ho"]]

    # Bảng tỷ lệ: vẽ đúng trục Y là tỷ lệ, không melt chung so_ho/tong_ho.
    if ("ty_le_%" in out.columns or "ty_le_pct" in out.columns) and semantics == "independent_ratio":
        ratio_col = "ty_le_%" if "ty_le_%" in out.columns else "ty_le_pct"
        ratio_labels = [col for col in label_cols if col != ratio_col]
        if ratio_labels:
            return out[ratio_labels + [ratio_col]].rename(columns={ratio_col: "ty_le_%"})

    # Quan trọng: không lấy nhãn dạng số như nam làm value_vars.
    value_vars = [c for c in _value_columns(out) if c not in {"ty_le_%", "ty_le_pct", "__total_count"}]

    if not label_cols or not value_vars:
        return out

    label_col = label_cols[0]

    # Multi-metric thật sự: chỉ melt khi còn từ 2 cột giá trị trở lên.
    # Bảng thường như [huyen, so_ho, ty_le_%] phải giữ nguyên, vì chỉ có 1 metric chính.
    if len(value_vars) >= 2:
        chart_df = out[[label_col] + value_vars].melt(
            id_vars=[label_col],
            value_vars=value_vars,
            var_name="chi_tieu",
            value_name="__value",
        )
        return chart_df.rename(columns={"__value": "so_ho"})

    return out


def build_chart_display_df(
    chart_df: pd.DataFrame,
    chart_debug: Mapping | None = None,
    result_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return exactly the chart dimensions/metrics plus factual auxiliary values."""
    if chart_df is None or chart_df.empty:
        return chart_df

    display = chart_df.copy()
    debug = dict(chart_debug or {})
    auxiliary_cols = [
        col for col in ("so_ho", "tong_ho", "tong_ho_ngheo", "tong_ho_can_ngheo", "ty_le_%", "ty_le_pct")
        if isinstance(result_df, pd.DataFrame) and col in result_df.columns and col not in display.columns
    ]
    if auxiliary_cols and isinstance(result_df, pd.DataFrame) and not result_df.empty:
        join_cols = [
            col for col in (
                "nam", "huyen", "xa_phuong", "phan_loai", "gioi_tinh",
                "bien_dong_dau_ky", "nhom_ngheo_tong_hop", "dan_toc_chi_tiet", "chi_so", "muc_do_thieu_hut", "tinh_trang_nha",
            )
            if col in display.columns and col in result_df.columns
        ]
        if join_cols:
            lookup = result_df[join_cols + auxiliary_cols].drop_duplicates(subset=join_cols)
            display = display.merge(lookup, on=join_cols, how="left")

    preferred = []
    for col in (debug.get("x_col"), debug.get("color_col"), debug.get("y_col")):
        if col and col in display.columns and col not in preferred:
            preferred.append(col)
    for col in chart_df.columns:
        if col in display.columns and col not in preferred and not str(col).startswith("__"):
            preferred.append(col)
    for col in ("so_ho", "tong_ho", "tong_ho_ngheo", "tong_ho_can_ngheo", "ty_le_%", "ty_le_pct"):
        if col in display.columns and col not in preferred:
            preferred.append(col)
    return display[preferred].copy()


def _chart_number(value, decimals: int = 1) -> str:
    if pd.isna(value):
        return "không xác định"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", ".")
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _chart_is_ratio_col(column: str | None) -> bool:
    return bool(column and _is_ratio_value_col(str(column)))


def _chart_value_text(value, column: str | None) -> str:
    if _chart_is_ratio_col(column):
        return f"{_chart_number(value, 1)}%"
    if column and (
        column == "so_ho"
        or str(column).startswith(("so_ho", "tong_ho"))
        or column in {"muc_giam", "muc_tang", "muc_bien_dong"}
    ):
        return f"{_chart_number(value, 1)} hộ"
    return _chart_number(value, 1)


def _chart_row_label(row: pd.Series, dimensions: list[str]) -> str:
    values = [str(row[col]) for col in dimensions if col in row.index and pd.notna(row[col])]
    return " - ".join(values) if values else "toàn bộ dữ liệu"


def _chart_change_text(delta: float, value_col: str) -> str:
    direction = "tăng" if delta > 0 else "giảm" if delta < 0 else "không đổi"
    magnitude = abs(delta)
    if _chart_is_ratio_col(value_col):
        return f"{direction} {_chart_number(magnitude, 1)} điểm phần trăm"
    if value_col == "so_ho" or value_col.startswith(("so_ho", "tong_ho")):
        return f"{direction} {_chart_number(magnitude, 1)} hộ"
    return f"{direction} {_chart_number(magnitude, 1)}"


def build_chart_answer(
    question: str,
    chart_df: pd.DataFrame,
    chart_debug: Mapping | None = None,
    plan=None,
    result_df: pd.DataFrame | None = None,
) -> str:
    """Build a short, deterministic chart interpretation using only supplied rows."""
    if chart_df is None or chart_df.empty:
        return "Biểu đồ đã được tạo, nhưng dữ liệu chưa đủ để rút ra nhận xét rõ ràng."

    debug = dict(chart_debug or {})
    display = build_chart_display_df(chart_df, debug, result_df)
    chart_type = str(debug.get("chart_type") or infer_chart_type(chart_df, question, plan))
    value_col = debug.get("y_col") if debug.get("y_col") in display.columns else _main_value_col(chart_df)
    if not value_col or value_col not in display.columns:
        return "Biểu đồ đã được tạo, nhưng dữ liệu chưa đủ để rút ra nhận xét rõ ràng."

    numeric = pd.to_numeric(display[value_col], errors="coerce")
    valid = display.loc[numeric.notna()].copy()
    if valid.empty:
        return "Biểu đồ đã được tạo, nhưng dữ liệu chưa đủ để rút ra nhận xét rõ ràng."
    valid["__chart_value"] = numeric.loc[numeric.notna()].astype(float)

    dimension_candidates = [
        col for col in valid.columns
        if col not in {value_col, "__chart_value", "so_ho", "tong_ho", "tong_ho_ngheo", "tong_ho_can_ngheo", "ty_le_%", "ty_le_pct"}
        and not pd.api.types.is_numeric_dtype(valid[col])
    ]

    if len(valid) < 2:
        row = valid.iloc[0]
        label = _chart_row_label(row, dimension_candidates)
        if str(value_col) in {"muc_giam", "muc_tang", "muc_bien_dong"}:
            action = {
                "muc_giam": "mức giảm",
                "muc_tang": "mức tăng",
                "muc_bien_dong": "mức biến động",
            }.get(str(value_col), "giá trị")
            extra = ""
            if {"so_ho_2023", "so_ho_2024"} <= set(valid.columns):
                extra = (
                    f", từ {_chart_number(row['so_ho_2023'])} hộ năm 2023 "
                    f"xuống còn {_chart_number(row['so_ho_2024'])} hộ năm 2024"
                    if str(value_col) == "muc_giam" else
                    f", từ {_chart_number(row['so_ho_2023'])} hộ năm 2023 "
                    f"lên {_chart_number(row['so_ho_2024'])} hộ năm 2024"
                    if str(value_col) == "muc_tang" else
                    ""
                )
            return f"Biểu đồ thể hiện {label} có {action} {_chart_value_text(row['__chart_value'], str(value_col))}{extra}."
        return "Biểu đồ đã được tạo, nhưng dữ liệu chưa đủ để rút ra nhận xét rõ ràng."

    dimension_candidates = [
        col for col in valid.columns
        if col not in {value_col, "__chart_value", "so_ho", "tong_ho", "tong_ho_ngheo", "tong_ho_can_ngheo", "ty_le_%", "ty_le_pct"}
        and not pd.api.types.is_numeric_dtype(valid[col])
    ]

    if chart_type == "pie":
        total = float(valid["__chart_value"].sum())
        if total <= 0:
            return "Biểu đồ đã được tạo, nhưng dữ liệu chưa đủ để rút ra nhận xét rõ ràng."
        highest = valid.loc[valid["__chart_value"].idxmax()]
        lowest = valid.loc[valid["__chart_value"].idxmin()]
        high_label = _chart_row_label(highest, dimension_candidates)
        low_label = _chart_row_label(lowest, dimension_candidates)
        high_share = float(highest["__chart_value"]) * 100.0 / total
        low_share = float(lowest["__chart_value"]) * 100.0 / total
        return (
            f"Biểu đồ cho thấy {high_label} chiếm tỷ trọng lớn nhất, "
            f"{_chart_value_text(highest['__chart_value'], value_col)} ({_chart_number(high_share, 1)}%); "
            f"{low_label} thấp nhất, {_chart_value_text(lowest['__chart_value'], value_col)} "
            f"({_chart_number(low_share, 1)}%). Tổng các phần là {_chart_value_text(total, value_col)}."
        )

    if "nam" in valid.columns and valid["nam"].astype(str).nunique() >= 2:
        valid["__year"] = pd.to_numeric(valid["nam"], errors="coerce")
        series_dims = [col for col in dimension_candidates if col != "nam"]
        groups = [(None, valid)] if not series_dims else list(valid.groupby(series_dims, dropna=False, sort=False))
        changes = []
        for group_key, group in groups:
            ordered = group.dropna(subset=["__year"]).sort_values("__year", kind="stable")
            if len(ordered) < 2:
                continue
            first, last = ordered.iloc[0], ordered.iloc[-1]
            label = _chart_row_label(first, series_dims)
            changes.append((abs(float(last["__chart_value"] - first["__chart_value"])), label, first, last))
        if changes:
            _, label, first, last = max(changes, key=lambda item: item[0])
            delta = float(last["__chart_value"] - first["__chart_value"])
            subject = f"Nhóm {label} biến động nổi bật nhất: " if series_dims else "Biểu đồ cho thấy "
            answer = (
                f"{subject}{_chart_value_text(first['__chart_value'], value_col)} năm {int(first['__year'])} "
                f"và {_chart_value_text(last['__chart_value'], value_col)} năm {int(last['__year'])}, "
                f"{_chart_change_text(delta, str(value_col))}."
            )
            if _chart_is_ratio_col(str(value_col)) and {"so_ho", "tong_ho"} <= set(valid.columns):
                if pd.notna(first.get("so_ho")) and pd.notna(last.get("so_ho")) and pd.notna(first.get("tong_ho")) and pd.notna(last.get("tong_ho")):
                    count_delta = float(last["so_ho"] - first["so_ho"])
                    answer += (
                        f" Số hộ tương ứng từ {_chart_number(first['so_ho'])} xuống {_chart_number(last['so_ho'])} hộ"
                        if count_delta < 0 else
                        f" Số hộ tương ứng từ {_chart_number(first['so_ho'])} lên {_chart_number(last['so_ho'])} hộ"
                    )
                    answer += (
                        f", trong khi tổng hộ từ {_chart_number(first['tong_ho'])} "
                        f"thành {_chart_number(last['tong_ho'])} hộ."
                    )
            return answer

    highest = valid.loc[valid["__chart_value"].idxmax()]
    lowest = valid.loc[valid["__chart_value"].idxmin()]
    high_label = _chart_row_label(highest, dimension_candidates)
    low_label = _chart_row_label(lowest, dimension_candidates)
    difference = float(highest["__chart_value"] - lowest["__chart_value"])
    if str(value_col) in {"muc_giam", "muc_tang", "muc_bien_dong"}:
        value_name = {
            "muc_giam": "mức giảm",
            "muc_tang": "mức tăng",
            "muc_bien_dong": "mức biến động",
        }.get(str(value_col), "giá trị")
        return (
            f"Biểu đồ cho thấy {high_label} có {value_name} lớn nhất với "
            f"{_chart_value_text(highest['__chart_value'], value_col)}, trong khi {low_label} "
            f"thấp nhất với {_chart_value_text(lowest['__chart_value'], value_col)}; "
            f"chênh lệch {_chart_number(difference, 1)} hộ."
        )

    difference_unit = "điểm phần trăm" if _chart_is_ratio_col(str(value_col)) else "hộ" if str(value_col).startswith(("so_ho", "tong_ho")) else "đơn vị"
    return (
        f"Biểu đồ cho thấy {high_label} cao nhất với {_chart_value_text(highest['__chart_value'], value_col)}, "
        f"trong khi {low_label} thấp nhất với {_chart_value_text(lowest['__chart_value'], value_col)}; "
        f"chênh lệch {_chart_number(difference, 1)} {difference_unit}."
    )

# ── Chart recommendation helpers ─────────────────────────────────────────────
# Dùng cho optional chart: app chỉ hiện một gợi ý biểu đồ phù hợp nhất,
# thay vì bắt người dùng chọn bar/pie/line thủ công.
_CHART_LABELS_DEFAULT = {
    "bar": "📊 Biểu đồ cột",
    "pie": "🥧 Biểu đồ tròn",
    "line": "📈 Biểu đồ đường",
}
_GEO_GROUPS = {"huyen", "xa_phuong", "xa"}
_GROUP_LABELS = {
    "huyen": "huyện",
    "xa": "xã/phường",
    "xa_phuong": "xã/phường",
    "phan_loai": "phân loại hộ",
    "bien_dong_dau_ky": "biến động đầu kỳ",
    "nhom_ngheo_tong_hop": "nhóm nghèo tổng hợp",
    "gioi_tinh": "giới tính chủ hộ",
    "muc_do_thieu_hut": "mức độ thiếu hụt",
    "tinh_trang_nha": "tình trạng nhà ở",
    "dan_toc_chi_tiet": "dân tộc",
    "nam": "năm",
    "chi_so": "chỉ số",
    "chi_tieu": "chỉ tiêu",
}
_VALUE_LABELS = {
    "so_ho": "số hộ",
    "muc_giam": "mức giảm",
    "muc_tang": "mức tăng",
    "muc_bien_dong": "mức biến động",
    "ty_le_%": "tỷ lệ",
    "avg_thu_nhap_bq": "thu nhập bình quân",
    "tb_thu_nhap_nghin_dong": "thu nhập bình quân",
    "bien_dong": "biến động",
}


def _as_group_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value if x]
    return []


def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    return next((col for col in candidates if col in df.columns), None)


def _recommended_value_col(df: pd.DataFrame) -> str | None:
    value_cols = _value_columns(df)
    for preferred in ("muc_giam", "muc_tang", "muc_bien_dong", "so_ho", "ty_le_%", "avg_thu_nhap_bq", "tb_thu_nhap_nghin_dong", "bien_dong"):
        if preferred in value_cols:
            return preferred
    return value_cols[0] if value_cols else None


def _chart_group_label(plan: dict, chart_df: pd.DataFrame) -> str:
    group_by = _as_group_list(plan.get("group_by"))
    group_col = next((col for col in group_by if col in _GROUP_LABELS), None)
    if not group_col:
        group_col = _first_existing_col(
            chart_df,
            [
                "huyen", "xa_phuong", "phan_loai", "gioi_tinh", "muc_do_thieu_hut",
                "tinh_trang_nha", "bien_dong_dau_ky", "nhom_ngheo_tong_hop",
                "dan_toc_chi_tiet", "nam", "chi_tieu",
            ],
        )
    return _GROUP_LABELS.get(group_col or "", "nhóm")


def build_chart_recommendation(
    debug: dict,
    chart_df: pd.DataFrame,
    question: str = "",
    chart_type_labels: dict[str, str] | None = None,
) -> dict | None:
    """
    Chọn đúng một biểu đồ đề xuất cho optional chart.

    Nguyên tắc:
    - Không đề xuất nếu DataFrame không vẽ được.
    - Không đề xuất loại nằm ngoài allowed_chart_types().
    - time-series hợp lệ -> line, kể cả metric tỷ lệ.
    - part-to-whole hợp lệ -> pie, kể cả nhóm địa bàn.
    - so sánh độc lập/ranking -> bar.
    """
    if chart_df is None or chart_df.empty or not is_chartable(chart_df):
        return None

    plan = debug.get("query_plan") or {}
    allowed = allowed_chart_types(chart_df, question, plan)
    if not allowed:
        return None

    # labels kept for backward compatibility with older callers, but optional
    # recommendation text intentionally does not reveal the concrete chart type.
    _ = chart_type_labels or _CHART_LABELS_DEFAULT
    semantics = chart_semantics(chart_df, question, plan)
    chart_type = determine_chart_type(question, chart_df, plan=plan)
    if chart_type == "line":
        reason = "time_series_signal + temporal_axis -> line"
    elif chart_type == "pie" and semantics == "composition":
        reason = "part_to_whole_composition -> pie"
    elif _has_ranking_signal(question):
        reason = "ranking_or_top -> bar"
    elif any(col in chart_df.columns for col in _GEO_GROUPS):
        reason = "independent_geographic_comparison -> bar"
    else:
        reason = "independent_group_comparison -> bar"

    group_label = _chart_group_label(plan, chart_df)
    value_col = _recommended_value_col(chart_df)
    value_label = _VALUE_LABELS.get(value_col or "", value_col or "giá trị")
    return {
        "source": "qa_result_df",
        "chart_type": chart_type,
        "allowed_chart_types": allowed,
        "reason": reason,
        "message": f"Bạn có muốn xem biểu đồ phù hợp nhất cho {value_label} theo {group_label} không?",
        "group_label": group_label,
        "value_col": value_col,
        "df_rows": int(len(chart_df)),
        "df_columns": list(chart_df.columns),
        "df_head": chart_df.head(5).to_dict(orient="records"),
    }

def export_chart_png(fig) -> tuple[bytes | None, str | None]:
    """Xuất Plotly figure ra PNG bytes. Trả (bytes, None) hoặc (None, error_msg)."""
    if fig is None:
        return None, "Không có biểu đồ"
    try:
        return fig.to_image(format="png", scale=2), None
    except Exception as e:
        return None, f"Không thể xuất PNG: {e} (cần kaleido: pip install kaleido)"

def _safe_title(question: str, max_len: int = 80) -> str:
    """Tạo tiêu đề biểu đồ từ câu hỏi."""
    title = re.sub(r"[\"'`]", "", question or "").strip()
    for kw in ("biểu đồ", "vẽ ", "chart ", "plot ", "pie ", "bar ", "line "):
        title = re.sub(rf"\b{re.escape(kw)}\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip().rstrip("?.,")
    return title[:max_len] if title else "Biểu đồ thống kê hộ nghèo"
