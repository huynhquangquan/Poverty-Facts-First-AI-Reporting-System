from __future__ import annotations

"""
report/report_ui_llm_planner.py

Planner nhẹ cho tab Bảng số liệu và Biểu đồ của UI báo cáo.
LLM chỉ lập kế hoạch chọn bảng hiển thị; Python vẫn validate và render dữ liệu từ ReportFactsBundle.
Biểu đồ không dùng LLM planner riêng: chart được tạo tất định từ bảng đã chọn để luôn bám đúng bảng.
"""

from dataclasses import dataclass
from typing import Any
import json
import re

import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


DEFAULT_TABLE_LABELS = {
    "template_main": "Bảng số liệu báo cáo",
    "template_chart": "Dữ liệu biểu đồ minh họa",
    "main": "Bảng số liệu tổng hợp",
    "by_district": "Bảng tổng hợp theo địa bàn",
}

DEFAULT_COLUMN_LABELS = {
    "huyen": "Huyện/TP",
    "xa_phuong": "Xã/phường",
    "nam": "Năm",
    "phan_loai": "Phân loại hộ",
    "chi_tieu": "Chỉ tiêu",
    "dan_toc": "Dân tộc",
    "nhom_chi_tieu": "Nhóm chỉ tiêu",
    "so_ho": "Số hộ",
    "so_nhan_khau": "Số nhân khẩu",
    "so_ho_ngheo": "Số hộ nghèo",
    "so_ho_can_ngheo": "Số hộ cận nghèo",
    "ty_le_%": "Tỷ lệ (%)",
    "ty_le_ho_ngheo_%": "Tỷ lệ hộ nghèo (%)",
    "ty_le_ho_can_ngheo_%": "Tỷ lệ hộ cận nghèo (%)",
    "so_ho_ky_truoc": "Số hộ đầu kỳ",
    "so_ho_ky_sau": "Số hộ cuối kỳ",
    "chenh_lech": "Chênh lệch",
    "ty_le_bien_dong_%": "Tỷ lệ biến động (%)",
}


# Nhãn hiển thị riêng cho UI Báo cáo.
# Mục tiêu: bảng trong tab Báo cáo dùng nhãn nghiệp vụ theo 12 mẫu, không dùng
# nhãn kỹ thuật chung kiểu giam_1/tang_1 hoặc "giảm nhóm 1" gây hiểu sai.
# Hàm này chỉ phục vụ hiển thị UI; không đổi DataFrame gốc, không ảnh hưởng Excel,
# Word/exporter, report_writer, hay pipeline Q&A/chart tuần 2+3.
GENERAL_REPORT_COLUMN_LABELS = {
    **DEFAULT_COLUMN_LABELS,
    "tong_nhom": "Tổng số hộ trong nhóm",
    "tong_ho": "Tổng số hộ",
    "tong_ho_dan_cu": "Tổng số hộ dân cư",
    "tong_ho_ra_soat": "Tổng hộ đã rà soát/phân loại",
    "tong_nhan_khau": "Tổng số nhân khẩu",
    "so_khau_ngheo": "Số nhân khẩu hộ nghèo",
    "so_khau_can_ngheo": "Số nhân khẩu hộ cận nghèo",
    "so_ho_nlnndn_mstb": "Số hộ NLNN mức sống trung bình",
    "so_khau_nlnndn_mstb": "Số nhân khẩu NLNN mức sống trung bình",
    "so_nhan_khau_muc_tieu": "Nhân khẩu thuộc hộ mục tiêu",
    "so_ho_muc_tieu": "Số hộ nhóm mục tiêu",
    "so_ho_kinh": "Số hộ dân tộc Kinh",
    "so_ho_dtts": "Số hộ dân tộc thiểu số",
    "so_ho_dtts_tai_cho": "Số hộ DTTS tại chỗ",
    "ty_le_muc_tieu_%": "Tỷ lệ hộ mục tiêu (%)",
    "tong_ho_dtts": "Tổng số hộ DTTS",
    "tong_ho_dtts_tai_cho": "Tổng số hộ DTTS tại chỗ",
    "ty_le_dtts_trong_nhom_%": "Tỷ trọng DTTS trong nhóm hộ nghèo (%)",
    "ty_le_ngheo_trong_dtts_%": "Tỷ lệ hộ nghèo trong nhóm DTTS (%)",
    "ty_le_ngheo_trong_dtts_tai_cho_%": "Tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ (%)",
    "tong_ho_ngheo": "Tổng số hộ nghèo",
    "tong_ho_can_ngheo": "Tổng số hộ cận nghèo",
    "ho_ngheo_dtts": "Hộ nghèo DTTS",
    "ho_can_ngheo_dtts": "Hộ cận nghèo DTTS",
    "ho_ngheo_khong_knld": "Hộ nghèo không có khả năng lao động",
    "ho_can_ngheo_khong_knld": "Hộ cận nghèo không có khả năng lao động",
    "ho_ngheo_co_cong": "Hộ nghèo có người có công",
    "ho_can_ngheo_co_cong": "Hộ cận nghèo có người có công",
    "ty_le_ngheo_%": "Tỷ lệ hộ nghèo (%)",
    "ty_le_can_ngheo_%": "Tỷ lệ hộ cận nghèo (%)",
}

MOVEMENT_COLUMN_LABELS_BY_TEMPLATE = {
    2: {
        "so_ho_ky_truoc": "Số hộ nghèo đầu kỳ",
        "giam_1": "Thoát nghèo chuyển sang cận nghèo",
        "giam_2": "Thoát nghèo vượt chuẩn",
        "giam_khac": "Giảm nghèo khác có căn cứ chi tiết",
        "tang_1": "Cận nghèo chuyển thành nghèo",
        "tang_2": "Tái nghèo",
        "tang_3": "Nghèo mới phát sinh",
        "tang_khac": "Tăng nghèo khác có căn cứ chi tiết",
        "so_ho_ky_sau": "Số hộ nghèo cuối kỳ",
        "chenh_lech": "Tăng/giảm hộ nghèo",
        "ty_le_bien_dong_%": "Tỷ lệ biến động hộ nghèo (%)",
    },
    3: {
        "so_ho_ky_truoc": "Số hộ cận nghèo đầu kỳ",
        "giam_1": "Thoát cận nghèo vượt chuẩn",
        "giam_2": "Cận nghèo chuyển thành nghèo",
        "giam_khac": "Giảm cận nghèo khác có căn cứ chi tiết",
        "tang_1": "Hộ nghèo chuyển lên cận nghèo",
        "tang_2": "Tái cận nghèo",
        "tang_3": "Cận nghèo mới phát sinh",
        "tang_khac": "Tăng cận nghèo khác có căn cứ chi tiết",
        "so_ho_ky_sau": "Số hộ cận nghèo cuối kỳ",
        "chenh_lech": "Tăng/giảm hộ cận nghèo",
        "ty_le_bien_dong_%": "Tỷ lệ biến động hộ cận nghèo (%)",
    },
}

PATTERN_COLUMN_LABEL_OVERRIDES = {
    "deprivation_count": {
        "chi_tieu": "Chỉ số thiếu hụt",
        "so_ho": "Số hộ thiếu hụt",
        "ty_le_%": "Tỷ lệ thiếu hụt (%)",
        "tong_nhom": "Tổng số hộ trong nhóm",
    },
    "deprivation_ratio": {
        "chi_tieu": "Chỉ số thiếu hụt",
        "so_ho": "Số hộ thiếu hụt",
        "ty_le_%": "Tỷ lệ thiếu hụt (%)",
        "tong_nhom": "Tổng số hộ trong nhóm",
    },
    "vulnerable_groups": {
        "huyen": "Huyện/TP",
        "tong_ho_dan_cu": "Tổng số hộ dân cư",
        "so_ho_dtts": "Số hộ DTTS",
        "tong_ho_ngheo": "Tổng số hộ nghèo",
        "tong_ho_can_ngheo": "Tổng số hộ cận nghèo",
        "ho_ngheo_dtts": "Hộ nghèo DTTS",
        "ho_can_ngheo_dtts": "Hộ cận nghèo DTTS",
        "ho_ngheo_khong_knld": "Hộ nghèo không có khả năng lao động",
        "ho_can_ngheo_khong_knld": "Hộ cận nghèo không có khả năng lao động",
        "ho_ngheo_co_cong": "Hộ nghèo có người có công",
        "ho_can_ngheo_co_cong": "Hộ cận nghèo có người có công",
    },
    "ethnicity": {
        "dan_toc": "Dân tộc",
        "so_ho_ngheo": "Số hộ nghèo",
        "so_ho_can_ngheo": "Số hộ cận nghèo",
        "tong_ho": "Tổng số hộ",
        "ty_le_ngheo_%": "Tỷ lệ hộ nghèo (%)",
        "ty_le_can_ngheo_%": "Tỷ lệ hộ cận nghèo (%)",
    },
    "causes": {
        "chi_tieu": "Nguyên nhân nghèo/cận nghèo",
        "so_ho_ngheo": "Số hộ nghèo",
        "ty_le_ho_ngheo_%": "Tỷ lệ trong hộ nghèo (%)",
        "so_ho_can_ngheo": "Số hộ cận nghèo",
        "ty_le_ho_can_ngheo_%": "Tỷ lệ trong hộ cận nghèo (%)",
    },
    "child_deprivation": {
        "chi_tieu": "Chỉ tiêu thiếu hụt của trẻ em",
        "so_ho_ngheo": "Số trẻ thuộc hộ nghèo",
        "ty_le_ho_ngheo_%": "Tỷ lệ trên tổng trẻ hộ nghèo (%)",
        "so_ho_can_ngheo": "Số trẻ thuộc hộ cận nghèo",
        "ty_le_ho_can_ngheo_%": "Tỷ lệ trên tổng trẻ hộ cận nghèo (%)",
    },
    "multidimensional_standard": {
        "huyen": "Huyện/TP",
        "tong_ho_ra_soat": "Tổng hộ đã rà soát/phân loại",
        "tong_nhan_khau": "Tổng số nhân khẩu",
        "so_ho_muc_tieu": "Số hộ nghèo đa chiều",
        "so_nhan_khau_muc_tieu": "Số nhân khẩu hộ nghèo",
        "so_ho_kinh": "Số hộ nghèo dân tộc Kinh",
        "so_ho_dtts": "Số hộ nghèo DTTS",
        "so_ho_dtts_tai_cho": "Số hộ nghèo DTTS tại chỗ",
        "ty_le_muc_tieu_%": "Tỷ lệ hộ nghèo (%)",
        "tong_ho_dtts": "Tổng số hộ DTTS",
        "tong_ho_dtts_tai_cho": "Tổng số hộ DTTS tại chỗ",
        "ty_le_ngheo_trong_dtts_%": "Tỷ lệ hộ nghèo trong nhóm DTTS (%)",
        "ty_le_ngheo_trong_dtts_tai_cho_%": "Tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ (%)",
        "ty_le_dtts_trong_nhom_%": "Tỷ trọng DTTS trong nhóm hộ nghèo (%)",
    },
}

TEMPLATE_COLUMN_LABEL_OVERRIDES = {
    1: {
        "nhom_chi_tieu": "Nhóm hộ",
        "so_ho": "Số hộ",
        "ty_le_%": "Tỷ lệ (%)",
        "tong_ho_dan_cu": "Tổng số hộ dân cư",
        "tong_nhan_khau": "Tổng số nhân khẩu",
        "so_ho_ngheo": "Số hộ nghèo",
        "so_khau_ngheo": "Số nhân khẩu hộ nghèo",
        "so_ho_can_ngheo": "Số hộ cận nghèo",
        "so_khau_can_ngheo": "Số nhân khẩu hộ cận nghèo",
        "so_ho_nlnndn_mstb": "Số hộ NLNN mức sống trung bình",
        "so_khau_nlnndn_mstb": "Số nhân khẩu NLNN mức sống trung bình",
    },
}


def _template_id(bundle: Any = None, template_id: int | str | None = None) -> int | None:
    if template_id is not None:
        try:
            return int(template_id)
        except Exception:
            return None
    template = _bundle_template(bundle) if bundle is not None else {}
    try:
        return int(template.get("id"))
    except Exception:
        return None


def _template_pattern(bundle: Any = None, pattern: str | None = None) -> str:
    if pattern:
        return str(pattern)
    template = _bundle_template(bundle) if bundle is not None else {}
    return str(template.get("pattern") or "")


def report_column_labels(
    bundle: Any = None,
    *,
    template_id: int | str | None = None,
    pattern: str | None = None,
    table_name: str | None = None,
) -> dict[str, str]:
    """Trả về nhãn cột tiếng Việt cho bảng UI báo cáo.

    Đây là helper dùng chung cho UI hiển thị, không dùng cho tính toán. Các nhãn
    movement được tách theo mẫu 2/3 vì cùng một cột kỹ thuật giam_1/tang_1 có
    nghĩa nghiệp vụ khác nhau.
    """
    tid = _template_id(bundle, template_id)
    pat = _template_pattern(bundle, pattern)
    labels = dict(GENERAL_REPORT_COLUMN_LABELS)
    labels.update(PATTERN_COLUMN_LABEL_OVERRIDES.get(pat, {}))
    if tid in MOVEMENT_COLUMN_LABELS_BY_TEMPLATE:
        labels.update(MOVEMENT_COLUMN_LABELS_BY_TEMPLATE[tid])
    labels.update(TEMPLATE_COLUMN_LABEL_OVERRIDES.get(tid, {}))
    return labels


def _preferred_display_columns(
    df: pd.DataFrame,
    bundle: Any = None,
    *,
    template_id: int | str | None = None,
    pattern: str | None = None,
    table_name: str | None = None,
) -> list[str]:
    """Chọn cột hiển thị cho UI Báo cáo theo đúng ý nghĩa từng mẫu.

    Bảng trong fact bundle có thể giữ cả số hộ và tỷ lệ để phục vụ kiểm tra/Excel,
    nhưng UI báo cáo cần tách rõ mẫu "chỉ số/số lượng" và mẫu "tỷ lệ" để người đọc
    không thấy hai mẫu lặp y hệt nhau.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return list(df.columns) if isinstance(df, pd.DataFrame) else []
    tid = _template_id(bundle, template_id)
    pat = _template_pattern(bundle, pattern)
    cols = [str(c) for c in df.columns]

    def keep(candidates: list[str]) -> list[str]:
        return [c for c in candidates if c in cols]

    # Mẫu 4/6: bảng phân tích chỉ số = số hộ thiếu hụt. Tỷ lệ nếu có chỉ là dữ liệu
    # phụ trong fact bundle, không đưa lên bảng chính để tránh trùng mẫu 5/7.
    if pat == "deprivation_count" or tid in {4, 6}:
        out = keep(["chi_tieu", "so_ho", "tong_nhom"])
        return out or cols

    # Mẫu 5/7: bảng phân tích tỷ lệ = tỷ lệ thiếu hụt (%). Số hộ nếu có chỉ dùng
    # để kiểm chứng/Excel, không đưa lên bảng chính.
    if pat == "deprivation_ratio" or tid in {5, 7}:
        out = keep(["chi_tieu", "ty_le_%", "tong_nhom"])
        return out or cols

    # Mẫu 11 đang có cả số lượng và tỷ lệ cho 2 nhóm. Giữ cả hai nhưng xếp theo cặp
    # rõ ràng để tránh LLM/UI lẫn số hộ nghèo với hộ cận nghèo.
    if pat == "child_deprivation" or tid == 11:
        out = keep([
            "chi_tieu",
            "so_ho_ngheo",
            "ty_le_ho_ngheo_%",
            "so_ho_can_ngheo",
            "ty_le_ho_can_ngheo_%",
        ])
        return out or cols

    # Mẫu 12: đặt các cột theo 3 khối: mẫu số rà soát, kết quả hộ mục tiêu,
    # và cơ cấu dân tộc trong nhóm mục tiêu.
    if pat == "multidimensional_standard" or tid == 12:
        out = keep([
            "huyen",
            "tong_ho_ra_soat",
            "tong_nhan_khau",
            "so_ho_muc_tieu",
            "so_nhan_khau_muc_tieu",
            "ty_le_muc_tieu_%",
            "so_ho_kinh",
            "tong_ho_dtts",
            "so_ho_dtts",
            "ty_le_ngheo_trong_dtts_%",
            "tong_ho_dtts_tai_cho",
            "so_ho_dtts_tai_cho",
            "ty_le_ngheo_trong_dtts_tai_cho_%",
        ])
        return out or cols

    return cols


def rename_report_display_df(
    df: pd.DataFrame,
    bundle: Any = None,
    *,
    template_id: int | str | None = None,
    pattern: str | None = None,
    table_name: str | None = None,
) -> pd.DataFrame:
    """Chuẩn hóa bảng hiển thị trong UI Báo cáo.

    Không mutate df gốc và không đổi dữ liệu nguồn. Hàm này chỉ chọn/đổi nhãn cột
    cho UI, giúp các mẫu số lượng và mẫu tỷ lệ không bị nhìn như cùng một bảng.
    """
    if not isinstance(df, pd.DataFrame):
        return df
    labels = report_column_labels(bundle, template_id=template_id, pattern=pattern, table_name=table_name)
    display_cols = _preferred_display_columns(
        df,
        bundle,
        template_id=template_id,
        pattern=pattern,
        table_name=table_name,
    )
    out = df[[c for c in display_cols if c in df.columns]].copy() if display_cols else df.copy()
    return out.rename(columns={col: labels.get(str(col), str(col)) for col in out.columns})


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {
            "columns": list(value.columns),
            "rows": value.head(10).where(pd.notna(value.head(10)), None).to_dict(orient="records"),
            "row_count": int(len(value)),
        }
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _bundle_template(bundle: Any) -> dict[str, Any]:
    return getattr(bundle, "template", {}) or {}


def _bundle_facts(bundle: Any) -> dict[str, Any]:
    return getattr(bundle, "facts", {}) or {}


def _nonempty_tables(bundle: Any) -> dict[str, pd.DataFrame]:
    tables = getattr(bundle, "tables", {}) or {}
    out: dict[str, pd.DataFrame] = {}
    for name, df in tables.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            out[str(name)] = df.copy()
    return out


def _df_summary(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "row_count": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "numeric_columns": [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])],
        "sample_rows": df.head(5).where(pd.notna(df.head(5)), None).to_dict(orient="records"),
    }


def _table_context(bundle: Any) -> dict[str, Any]:
    tables = _nonempty_tables(bundle)
    template = _bundle_template(bundle)
    facts = _bundle_facts(bundle)
    return {
        "template": {
            "id": template.get("id"),
            "title": template.get("title"),
            "pattern": template.get("pattern"),
            "recommended_chart": template.get("recommended_chart"),
        },
        "available_tables": {name: _df_summary(df) for name, df in tables.items()},
        "table_insights": facts.get("table_insights"),
        "chart_insights": facts.get("chart_insights"),
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract exactly one JSON object from an LLM response.

    Qwen/Ollama đôi khi bọc JSON trong ```json ... ``` hoặc thêm vài dòng
    giải thích trước/sau. Hàm này vẫn cố bóc object hợp lệ, nhưng không chấp
    nhận mảng/string hay văn bản không có JSON.
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    def _try_load(candidate: str) -> dict[str, Any] | None:
        try:
            obj = json.loads(candidate.strip())
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    direct = _try_load(raw)
    if direct is not None:
        return direct

    # Ưu tiên code block JSON nếu LLM bọc bằng markdown.
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE):
        obj = _try_load(match.group(1))
        if obj is not None:
            return obj

    # Bóc object cân bằng ngoặc thay vì dùng regex greedy "{.*}" dễ nuốt quá tay.
    starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(raw)):
            ch = raw[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    obj = _try_load(raw[start:idx + 1])
                    if obj is not None:
                        return obj
                    break
    return None


def _call_ollama_json(prompt: str, *, model_name: str | None, ollama_url: str | None, timeout: int | float | None) -> tuple[str, dict[str, Any] | None, str | None]:
    if requests is None:
        return "", None, "requests chưa khả dụng"
    url = ollama_url or "http://localhost:11434/api/chat"
    payload = {
        "model": model_name or "qwen2.5:3b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là JSON planner. Chỉ trả về đúng một JSON object hợp lệ. "
                    "Không markdown, không ```json, không giải thích, không thêm chữ ngoài JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "top_p": 0.8, "num_predict": 700},
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout or 20)
        resp.raise_for_status()
        data = resp.json()
        raw = (data.get("message") or {}).get("content") or data.get("response") or ""
        return raw, _extract_json_object(raw), None
    except Exception as exc:
        return "", None, str(exc)


def _table_signature(df: pd.DataFrame | None) -> tuple[tuple[str, ...], int] | None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    return (tuple(str(c) for c in df.columns), int(len(df)))


def _is_same_table(df1: pd.DataFrame | None, df2: pd.DataFrame | None) -> bool:
    return _table_signature(df1) is not None and _table_signature(df1) == _table_signature(df2)


def _default_table_selection(bundle: Any) -> list[dict[str, Any]]:
    """Chọn bảng hiển thị mặc định cho UI Báo cáo, tránh bảng trùng.

    - Mẫu 1: giữ đúng 2 bảng nghiệp vụ chính: tổng hợp nhóm hộ và chi tiết địa bàn.
    - Mẫu khác: ưu tiên template_main; chỉ thêm bảng địa bàn khi nó khác bảng chính.
    """
    tables = _nonempty_tables(bundle)
    tid = _template_id(bundle)
    selected: list[dict[str, Any]] = []

    def add(name: str, reason: str | None = None) -> None:
        if name not in tables or name in {x["name"] for x in selected}:
            return
        df = tables.get(name)
        for item in selected:
            if _is_same_table(df, tables.get(str(item.get("name") or ""))):
                return
        selected.append({"name": name, "reason": reason or DEFAULT_TABLE_LABELS.get(name, name)})

    if tid == 1:
        add("template_chart", "Bảng tổng hợp nhóm hộ")
        add("template_main", "Bảng chi tiết theo địa bàn")
        if selected:
            return selected

    if "template_main" in tables:
        add("template_main", DEFAULT_TABLE_LABELS.get("template_main"))
    elif "main" in tables:
        add("main", DEFAULT_TABLE_LABELS.get("main"))

    add("by_district", DEFAULT_TABLE_LABELS.get("by_district"))

    if not selected:
        for name in ["template_chart", "main", "by_district"]:
            add(name, DEFAULT_TABLE_LABELS.get(name, name))
    return selected


def _table_role_for_excel(bundle: Any, table_name: str, df: pd.DataFrame | None = None) -> str:
    """Mô tả vai trò bảng theo ngôn ngữ template Excel.

    LLM UI không tự tạo số liệu. Nó chỉ chọn preset bảng đã được Python dựng sẵn
    từ ReportFactsBundle theo cấu trúc nghiệp vụ/template Excel.
    """
    tid = _template_id(bundle)
    pat = _template_pattern(bundle)
    name = str(table_name or "")
    if tid == 1 and name == "template_chart":
        return "bảng tổng hợp nhóm hộ trong mẫu Excel 1"
    if tid == 1 and name == "template_main":
        return "bảng chi tiết địa bàn trong mẫu Excel 1"
    if tid in {2, 3} and name == "template_main":
        return "bảng diễn biến đầu kỳ, giảm, tăng và cuối kỳ theo địa bàn"
    if tid in {4, 6}:
        return "bảng chỉ số thiếu hụt, trọng tâm là số hộ thiếu hụt"
    if tid in {5, 7}:
        return "bảng tỷ lệ thiếu hụt, trọng tâm là tỷ lệ phần trăm"
    if tid in {8, 9, 10}:
        return "bảng phân tích hộ nghèo/cận nghèo theo nhóm phân loại"
    if tid == 11:
        return "bảng chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo/cận nghèo"
    if tid == 12:
        return "bảng chuẩn nghèo đa chiều theo địa bàn"
    if name == "template_main":
        return "bảng chính bám cấu trúc mẫu Excel"
    if name == "template_chart":
        return "bảng tổng hợp phục vụ biểu đồ/tóm tắt trong mẫu Excel"
    if name == "by_district":
        return "bảng tổng hợp theo địa bàn"
    return DEFAULT_TABLE_LABELS.get(name, name)


def _excel_aligned_table_presets(
    bundle: Any,
    tables: dict[str, pd.DataFrame],
    default_selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tạo whitelist preset bảng cho LLM chọn, lấy cảm hứng từ Excel LLM mapping.

    Khác Excel exporter: UI table planner không đọc/ghi file Excel và không để LLM map
    từng cột dữ liệu. Python đã dựng sẵn các bảng hợp lệ theo mẫu; LLM chỉ chọn
    preset bảng nào nên hiển thị và viết lý do.
    """
    template = _bundle_template(bundle)
    default_names = [str(x.get("name") or "") for x in default_selected if str(x.get("name") or "") in tables]
    ordered_names: list[str] = []
    for name in default_names + [n for n in tables if n not in default_names]:
        if name in tables and name not in ordered_names:
            ordered_names.append(name)

    presets: list[dict[str, Any]] = []
    for name in ordered_names:
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        display_cols = _preferred_display_columns(df, bundle, table_name=name)
        labels = report_column_labels(bundle, table_name=name)
        presets.append({
            "preset_id": name,
            "table_name": name,
            "title": DEFAULT_TABLE_LABELS.get(name, name),
            "excel_template_source": template.get("source_file"),
            "excel_aligned_role": _table_role_for_excel(bundle, name, df),
            "recommended_default": name in default_names,
            "row_count": int(len(df)),
            "display_columns": [labels.get(str(c), str(c)) for c in display_cols if str(c) in [str(x) for x in df.columns]][:12],
            "technical_columns": [str(c) for c in display_cols if str(c) in [str(x) for x in df.columns]][:12],
        })
    return presets


def _compact_table_planner_context(
    bundle: Any,
    tables: dict[str, pd.DataFrame],
    default_selected: list[dict[str, Any]],
) -> dict[str, Any]:
    template = _bundle_template(bundle)
    presets = _excel_aligned_table_presets(bundle, tables, default_selected)
    return {
        "template": {
            "id": template.get("id"),
            "title": template.get("title"),
            "pattern": template.get("pattern"),
            "source_file": template.get("source_file"),
        },
        "planner_mode": "excel_aligned_supervised_table_selection",
        "rule": (
            "LLM chỉ chọn preset bảng từ whitelist đã bám cấu trúc mẫu Excel; "
            "LLM không sinh dữ liệu, không đổi cột, không tính số. Python validate và render từ ReportFactsBundle."
        ),
        "allowed_preset_ids": [p["preset_id"] for p in presets],
        "recommended_default_preset_ids": [p["preset_id"] for p in presets if p.get("recommended_default")],
        "table_presets": presets,
    }


def _validate_table_selection_obj(
    obj: dict[str, Any] | None,
    *,
    tables: dict[str, pd.DataFrame],
    default_selected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[Any], list[str]]:
    """Validate output LLM table planner. Trả selected, display_limit, notes, warnings."""
    warnings: list[str] = []
    if not isinstance(obj, dict):
        return [], 50, [], ["LLM table planner không trả JSON object hợp lệ."]

    # Schema mới: preset_id; schema cũ: table name. Cả hai đều là whitelist tên bảng.
    selected_raw = obj.get("selected_preset_ids")
    if selected_raw is None:
        selected_raw = obj.get("selected_table_names")
    if selected_raw is None:
        selected_raw = obj.get("selected_tables")

    reason_map = obj.get("preset_reasons") if isinstance(obj.get("preset_reasons"), dict) else {}
    if not reason_map:
        reason_map = obj.get("table_reasons") if isinstance(obj.get("table_reasons"), dict) else {}

    selected: list[dict[str, Any]] = []
    if isinstance(selected_raw, list):
        for item in selected_raw:
            if isinstance(item, dict):
                name = str(item.get("preset_id") or item.get("name") or item.get("table_name") or "")
                raw_reason = item.get("reason")
            else:
                name = str(item or "")
                raw_reason = reason_map.get(name) if isinstance(reason_map, dict) else ""
            if name in tables and name not in {x["name"] for x in selected}:
                reason = str(raw_reason or DEFAULT_TABLE_LABELS.get(name, name))
                selected.append({"name": name, "reason": reason[:300]})

    if not selected:
        return [], 50, [], ["LLM table planner không chọn được preset/bảng hợp lệ."]

    try:
        display_limit = int(obj.get("display_limit") or 50)
    except Exception:
        display_limit = 50
    display_limit = max(10, min(display_limit, 200))
    notes = obj.get("notes") if isinstance(obj.get("notes"), list) else []
    return selected, display_limit, notes, warnings


def build_report_table_plan(bundle: Any, *, use_llm: bool, model_name: str | None = None, ollama_url: str | None = None, timeout: int | float | None = None, regenerate_nonce: int = 0) -> dict[str, Any]:
    tables = _nonempty_tables(bundle)
    default_selected = _default_table_selection(bundle)
    full_context = _table_context(bundle)
    compact_context = _compact_table_planner_context(bundle, tables, default_selected)
    debug: dict[str, Any] = {
        "kind": "table_plan",
        "mode": "llm" if use_llm else "no_llm",
        "llm_attempted": False,
        "llm_success": False,
        "source": "python_default",
        "planner_scope": "excel_aligned_supervised_table_selection",
        "llm_role": "select_excel_aligned_table_presets_from_whitelist_and_write_reasons",
        "chart_policy": "charts_are_derived_from_validated_visible_tables_by_python",
        "data_policy": "LLM không sinh bảng/số liệu; Python render từ ReportFactsBundle theo preset bám mẫu Excel.",
        "validated_plan": {"selected_tables": default_selected, "display_limit": 50},
        "warnings": [],
        "context": compact_context,
        "full_context_debug": full_context,
        "regenerate_nonce": regenerate_nonce,
        "execution": "python_render_from_ReportFactsBundle",
    }
    if not use_llm:
        debug["warnings"].append("Chế độ không LLM: bảng hiển thị theo thứ tự mặc định của Python.")
        return debug
    if not tables:
        debug["warnings"].append("Không có bảng dữ liệu trong ReportFactsBundle.")
        return debug

    allowed = compact_context.get("allowed_preset_ids") or []
    recommended = compact_context.get("recommended_default_preset_ids") or []
    prompt = (
        "Bạn là planner BẢNG cho UI báo cáo hành chính.\n"
        "Nhiệm vụ: chọn preset bảng từ whitelist đã bám cấu trúc mẫu Excel.\n"
        "Không tạo bảng, không tạo cột, không sinh số liệu. Python sẽ validate và render dữ liệu.\n"
        "Trả về đúng JSON object, không markdown, không giải thích ngoài JSON.\n"
        "Schema bắt buộc:\n"
        '{"selected_preset_ids":["template_main"],"preset_reasons":{"template_main":"lý do ngắn"},"display_limit":50,"notes":["ghi chú ngắn"]}\n'
        f"allowed_preset_ids={json.dumps(allowed, ensure_ascii=False)}\n"
        f"recommended_default_preset_ids={json.dumps(recommended, ensure_ascii=False)}\n"
        f"table_presets={json.dumps(_json_safe(compact_context.get('table_presets') or []), ensure_ascii=False, default=str)}\n"
        "Nếu recommended_default_preset_ids hợp lý thì giữ chúng và viết lý do. "
        "Chỉ được chọn id có trong allowed_preset_ids."
    )
    attempts: list[dict[str, Any]] = []
    debug["llm_attempted"] = True
    debug["prompt"] = prompt

    raw, obj, err = _call_ollama_json(prompt, model_name=model_name, ollama_url=ollama_url, timeout=timeout)
    debug["raw_llm_text"] = raw
    selected, display_limit, notes, plan_warnings = _validate_table_selection_obj(
        obj, tables=tables, default_selected=default_selected
    )
    attempts.append({
        "attempt": 1,
        "raw_llm_text": raw,
        "parsed": obj,
        "error": err,
        "selected_count": len(selected),
        "warnings": list(plan_warnings),
    })

    if (err or not selected) and allowed:
        retry_prompt = (
            "Lần trước chưa chọn được preset hợp lệ. Trả về JSON tối giản, không thêm chữ.\n"
            f"allowed_preset_ids={json.dumps(allowed, ensure_ascii=False)}\n"
            f"recommended_default_preset_ids={json.dumps(recommended, ensure_ascii=False)}\n"
            "Hãy chọn recommended_default_preset_ids nếu không có lý do loại bỏ.\n"
            "JSON duy nhất:\n"
            '{"selected_preset_ids":REPLACE_WITH_ARRAY,"preset_reasons":{},"display_limit":50,"notes":[]}'
        )
        debug["retry_prompt"] = retry_prompt
        raw2, obj2, err2 = _call_ollama_json(retry_prompt, model_name=model_name, ollama_url=ollama_url, timeout=timeout)
        selected2, display_limit2, notes2, plan_warnings2 = _validate_table_selection_obj(
            obj2, tables=tables, default_selected=default_selected
        )
        attempts.append({
            "attempt": 2,
            "raw_llm_text": raw2,
            "parsed": obj2,
            "error": err2,
            "selected_count": len(selected2),
            "warnings": list(plan_warnings2),
        })
        if selected2:
            raw, obj, err = raw2, obj2, err2
            selected, display_limit, notes, plan_warnings = selected2, display_limit2, notes2, plan_warnings2
            debug["raw_llm_text"] = raw2
            debug["retry_used"] = True

    debug["llm_attempt_results"] = attempts
    if err and not selected:
        debug["warnings"].append(f"LLM table planner lỗi: {err}; dùng Python default.")
        return debug
    if not selected:
        debug["warnings"].extend(plan_warnings or ["LLM table planner không chọn được preset/bảng hợp lệ; dùng Python default."])
        return debug

    # Mẫu 1 phải giữ đúng hai bảng bám biểu mẫu: template_chart và template_main.
    # LLM planner nhỏ đôi khi chọn by_district hoặc main vì thấy cũng hợp lệ, nhưng các bảng đó
    # có thể lôi thêm tổng quan/hộ không nghèo hoặc làm biểu đồ sai trọng tâm mẫu 1.
    if _template_id(bundle) == 1:
        default_names = [str(x.get("name") or "") for x in default_selected]
        selected_names = [str(x.get("name") or "") for x in selected]
        if default_names and selected_names != default_names:
            debug["warnings"].append(
                "Mẫu 1: ghi đè lựa chọn bảng của LLM về preset mặc định template_chart + template_main để giữ đúng biểu mẫu."
            )
            selected = list(default_selected)
            display_limit = 50
            notes = list(notes or []) + ["Mẫu 1 dùng preset mặc định để tránh lẫn bảng tổng quan ngoài biểu mẫu."]

    debug.update({
        "llm_success": True,
        "source": "llm_excel_aligned_table_preset_validated_python_executed",
        "planner_scope": "excel_aligned_supervised_table_selection",
        "chart_policy": "charts_are_derived_from_validated_visible_tables_by_python",
        "validated_plan": {
            "selected_tables": selected,
            "display_limit": display_limit,
            "notes": notes,
            "selected_preset_ids": [x["name"] for x in selected],
        },
    })
    return debug


def apply_report_table_plan(bundle: Any, table_plan: dict[str, Any] | None, default_items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    tables = _nonempty_tables(bundle)
    by_name: dict[str, dict[str, Any]] = {}
    for item in default_items or []:
        name = str(item.get("name") or "")
        if name:
            by_name[name] = dict(item)
    for name, df in tables.items():
        if name not in by_name:
            by_name[name] = {"name": name, "title": DEFAULT_TABLE_LABELS.get(name, name), "df": df}
    plan_items = ((table_plan or {}).get("validated_plan") or {}).get("selected_tables") or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in plan_items:
        name = str((item or {}).get("name") or "")
        if name in by_name and name not in seen:
            x = dict(by_name[name])
            if (item or {}).get("reason"):
                x["planner_reason"] = str((item or {}).get("reason"))
            out.append(x)
            seen.add(name)
    if out:
        return out
    return list(by_name.values())



def _safe_int_len(df: pd.DataFrame) -> int:
    try:
        return int(len(df))
    except Exception:
        return 0


def _col_key(col: str | None) -> str:
    return str(col or "").strip().lower()


def _is_ratio_col(col: str | None) -> bool:
    key = _col_key(col)
    return key.startswith("ty_le") or key.startswith("tỷ_lệ") or key in {"ratio", "percentage"} or key.endswith("_%")


def _is_overlap_indicator_pattern(pattern: str) -> bool:
    # Các mẫu này có chỉ tiêu/nguyên nhân/nhóm có thể chồng lặp; không coi là cơ cấu 100%.
    return pattern in {
        "deprivation_count",
        "deprivation_ratio",
        "vulnerable_groups",
        "causes",
        "child_deprivation",
    }


def _is_report_composition_candidate(
    *,
    pattern: str,
    table_name: str,
    label_col: str,
    value_col: str | None,
    value_cols: list[str],
    row_count: int,
) -> bool:
    if value_cols and len(value_cols) > 1:
        return False
    if row_count < 2 or row_count > 8:
        return False
    label = _col_key(label_col)
    value = _col_key(value_col)
    if _is_overlap_indicator_pattern(pattern):
        return False
    if label in {"huyen", "xa_phuong", "chi_tieu", "dan_toc"}:
        return False
    if pattern == "overview_result" and label in {"phan_loai", "nhom_chi_tieu", "nhom", "loai", "group"}:
        return bool(value and not value.startswith("so_khau"))
    if table_name == "template_chart" and label in {"phan_loai", "nhom_chi_tieu"}:
        return True
    return False


def _ratio_sums_to_100(df: pd.DataFrame, value_col: str | None, *, tolerance: float = 1.0) -> bool:
    if not value_col or value_col not in df.columns:
        return False
    values = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if values.empty:
        return False
    total = float(values.sum())
    return (100.0 - tolerance) <= total <= (100.0 + tolerance)


def _multi_value_candidates(cols: list[str], pattern: str) -> list[str]:
    colset = set(cols)
    if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(colset):
        return ["so_ho_ky_truoc", "so_ho_ky_sau"]
    if {"so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"}.issubset(colset):
        return ["so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"]
    if pattern in {"vulnerable_groups", "ethnicity", "causes", "child_deprivation"} and {"so_ho_ngheo", "so_ho_can_ngheo"}.issubset(colset):
        return ["so_ho_ngheo", "so_ho_can_ngheo"]
    return []


def _single_value_candidates(pattern: str) -> list[str]:
    if pattern == "movement":
        return ["chenh_lech", "so_ho_ky_sau", "so_ho_ky_truoc", "ty_le_bien_dong_%"]
    if pattern == "deprivation_ratio":
        return ["ty_le_%", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "so_ho"]
    if pattern in {"deprivation_count", "basic_service_deprivation"}:
        return ["so_ho", "tong_ho", "so_ho_ngheo", "so_ho_can_ngheo"]
    if pattern in {"vulnerable_groups", "ethnicity", "causes", "child_deprivation"}:
        return ["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho", "so_ho", "so_tre_thieu"]
    if pattern == "multidimensional_standard":
        return ["so_ho_muc_tieu", "ty_le_muc_tieu_%", "tong_ho_ra_soat", "so_ho"]
    return ["so_ho", "tong_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "so_ho_muc_tieu"]


def _infer_chart_shape(
    *,
    pattern: str,
    table_name: str,
    label_col: str,
    value_col: str | None,
    value_cols: list[str],
    row_count: int,
    df: pd.DataFrame | None = None,
) -> tuple[str, str, str, int, str]:
    """Chọn loại biểu đồ theo rule riêng của UI báo cáo.

    Không dùng pipeline Q&A tuần 2+3. Rule ở đây chỉ đọc bảng trong
    ReportFactsBundle và chọn chart để đối chiếu với từng bảng báo cáo.

    Return: chart_type, orientation, sort, top_n, reason_suffix.
    orientation chỉ áp dụng cho bar: v = cột dọc, h = thanh ngang.
    """
    pattern = str(pattern or "")
    table_name = str(table_name or "")
    label = _col_key(label_col)
    values = [_col_key(v) for v in (value_cols or ([value_col] if value_col else []))]
    value = values[0] if values else ""

    # Cơ cấu một tổng: pie chỉ dùng khi ít nhóm, loại trừ nhau và không phải mẫu chồng lặp.
    if _is_report_composition_candidate(
        pattern=pattern,
        table_name=table_name,
        label_col=label_col,
        value_col=value_col,
        value_cols=value_cols,
        row_count=row_count,
    ):
        if not _is_ratio_col(value_col) or df is None or _ratio_sums_to_100(df, value_col):
            return "pie", "v", "desc", 8, "Bảng là cơ cấu một tổng ít nhóm nên dùng pie."

    # Time-series: dùng line khi trục nhãn là năm/kỳ/thời gian.
    if label in {"nam", "năm", "year", "ky", "kỳ", "thoi_gian", "thời_gian"} or label.startswith("nam"):
        return "line", "v", "none", max(3, min(row_count or 15, 30)), "Trục nhãn là thời gian nên dùng line."

    # Mẫu diễn biến có hai cột đầu/cuối kỳ theo địa bàn: grouped bar là phù hợp nhất.
    if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(set(values)):
        orientation = "h" if row_count >= 6 or label in {"huyen", "xa_phuong"} else "v"
        return "bar", orientation, "desc", 12, "So sánh đầu kỳ/cuối kỳ; nhiều địa bàn thì dùng thanh ngang để dễ đọc."

    # Chênh lệch/ranking theo địa bàn.
    if pattern == "movement" or value in {"chenh_lech", "ty_le_bien_dong_%"}:
        return "bar", "h", "asc" if value == "chenh_lech" else "desc", 15, "Biến động/ranking theo địa bàn nên dùng bar ngang."

    # Tỷ lệ độc lập/thiếu hụt không phải cơ cấu tổng.
    if pattern == "deprivation_ratio" or (_is_ratio_col(value_col) and not _is_report_composition_candidate(
        pattern=pattern,
        table_name=table_name,
        label_col=label_col,
        value_col=value_col,
        value_cols=value_cols,
        row_count=row_count,
    )):
        return "bar", "h", "desc", 15, "Tỷ lệ theo chỉ tiêu độc lập nên dùng bar ngang, không dùng pie."

    # Chỉ tiêu/nguyên nhân/trẻ em/nhóm đối tượng có thể chồng lặp: không dùng pie.
    if _is_overlap_indicator_pattern(pattern):
        return "bar", "h", "desc", 15, "Các nhóm/chỉ tiêu có thể chồng lặp nên dùng bar ngang, không dùng pie."

    # Nhiều hạng mục/dân tộc/địa bàn/chỉ tiêu: bar ngang để dễ đọc nhãn.
    if row_count >= 6 or label in {"huyen", "xa_phuong", "dan_toc", "chi_tieu", "nhom_chi_tieu"}:
        return "bar", "h", "desc", 15, "Nhiều nhãn phân loại nên dùng bar ngang để dễ đọc."

    return "bar", "v", "desc", 15, "So sánh nhóm ít mục nên dùng bar."

def _choose_default_chart_plan(bundle: Any) -> dict[str, Any] | None:
    tables = _nonempty_tables(bundle)
    facts = _bundle_facts(bundle)
    template = _bundle_template(bundle)
    chart_hint = facts.get("chart_insights") if isinstance(facts, dict) else {}
    hinted_label = chart_hint.get("label_col") if isinstance(chart_hint, dict) else None
    hinted_value = chart_hint.get("value_col") if isinstance(chart_hint, dict) else None
    preferred_table_names = ["template_chart", "template_main", "main", "by_district"]
    for name in preferred_table_names + [n for n in tables if n not in preferred_table_names]:
        df = tables.get(name)
        if df is None or df.empty:
            continue
        cols = [str(c) for c in df.columns]
        numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        label_candidates = [c for c in cols if c not in numeric]
        label_col = hinted_label if hinted_label in cols else None
        value_col = hinted_value if hinted_value in numeric else None
        if not label_col:
            for c in ["huyen", "chi_tieu", "dan_toc", "nhom_chi_tieu", "Năm", "nam"]:
                if c in cols:
                    label_col = c
                    break
        if not value_col:
            for c in ["so_ho", "ty_le_%", "chenh_lech", "so_ho_ngheo", "so_ho_can_ngheo", "so_tre_thieu"]:
                if c in numeric:
                    value_col = c
                    break
        if not label_col and label_candidates:
            label_col = label_candidates[0]
        if not value_col and numeric:
            value_col = numeric[0]
        if label_col and value_col and label_col != value_col:
            chart_type, orientation, sort, top_n, shape_reason = _infer_chart_shape(
                pattern=str(template.get("pattern") or ""),
                table_name=str(name),
                label_col=str(label_col),
                value_col=str(value_col),
                value_cols=[],
                row_count=_safe_int_len(df),
                df=df,
            )
            return {
                "source_table": name,
                "label_col": label_col,
                "value_col": value_col,
                "value_cols": [value_col],
                "chart_type": chart_type,
                "orientation": orientation,
                "sort": sort,
                "top_n": top_n,
                "reason": "Kế hoạch mặc định từ Python/chart_insights. " + shape_reason,
            }
    return None


def _validate_chart_plan(bundle: Any, obj: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    tables = _nonempty_tables(bundle)
    if not isinstance(obj, dict):
        return None, ["Không có JSON plan hợp lệ."]
    source_table = str(obj.get("source_table") or "")
    if source_table not in tables:
        return None, [f"source_table không hợp lệ: {source_table!r}"]
    df = tables[source_table]
    canonical_plan, canonical_warnings = _canonical_chart_plan_for_table(bundle, source_table)
    if canonical_plan is not None:
        warnings.extend(canonical_warnings)
        warnings.append("Điều chỉnh plan LLM theo plan nghiệp vụ bắt buộc của mẫu để biểu đồ không thiếu cột/dòng quan trọng.")
        return canonical_plan, warnings
    cols = [str(c) for c in df.columns]
    label_col = str(obj.get("label_col") or "")
    if label_col not in cols:
        return None, [f"label_col không có trong bảng: {label_col!r}"]

    raw_value_cols = obj.get("value_cols")
    value_cols: list[str] = []
    if isinstance(raw_value_cols, list):
        for c in raw_value_cols:
            cc = str(c)
            if cc in cols and cc not in value_cols:
                value_cols.append(cc)
    value_col = str(obj.get("value_col") or (value_cols[0] if value_cols else ""))
    if value_col and value_col not in cols:
        return None, [f"value_col không có trong bảng: {value_col!r}"]
    if not value_cols and value_col:
        value_cols = [value_col]
    if not value_cols:
        return None, ["Không có value_col/value_cols hợp lệ."]

    checked_value_cols: list[str] = []
    for c in value_cols:
        if c not in cols:
            warnings.append(f"Bỏ value_cols không có trong bảng: {c!r}")
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            parsed = pd.to_numeric(df[c], errors="coerce")
            if parsed.notna().sum() == 0:
                warnings.append(f"Bỏ value_cols không parse được số: {c!r}")
                continue
            warnings.append(f"value_col {c!r} được ép kiểu số khi render.")
        checked_value_cols.append(c)
    if not checked_value_cols:
        return None, ["Không còn cột số hợp lệ sau validate."]

    chart_type = str(obj.get("chart_type") or "bar").lower()
    if chart_type not in {"bar", "line", "pie"}:
        warnings.append(f"chart_type {chart_type!r} không hỗ trợ; dùng bar.")
        chart_type = "bar"
    if chart_type == "pie" and len(checked_value_cols) > 1:
        warnings.append("Pie không hỗ trợ nhiều value_cols; dùng bar grouped.")
        chart_type = "bar"

    orientation = str(obj.get("orientation") or obj.get("layout") or "v").lower()
    if orientation in {"horizontal", "h", "ngang"}:
        orientation = "h"
    else:
        orientation = "v"
    if chart_type != "bar":
        orientation = "v"

    # Guardrail: kể cả LLM planner chọn bar dọc theo thói quen, Python vẫn kéo về
    # nguyên tắc chart riêng của UI báo cáo khi có tín hiệu rõ ràng.
    template = _bundle_template(bundle)
    inferred_chart, inferred_orientation, inferred_sort, inferred_top_n, inferred_reason = _infer_chart_shape(
        pattern=str(template.get("pattern") or ""),
        table_name=source_table,
        label_col=label_col,
        value_col=checked_value_cols[0],
        value_cols=checked_value_cols if len(checked_value_cols) > 1 else [],
        row_count=_safe_int_len(df),
        df=df,
    )
    if inferred_chart in {"line", "pie"} and chart_type == "bar" and len(checked_value_cols) == 1:
        warnings.append(f"Điều chỉnh chart_type theo nguyên tắc chọn chart: bar → {inferred_chart}. {inferred_reason}")
        chart_type = inferred_chart
        orientation = "v"
    elif chart_type == "pie" and inferred_chart == "bar":
        warnings.append("Điều chỉnh pie → bar vì dữ liệu là tỷ lệ/ranking hoặc quá nhiều nhóm, không phải cơ cấu tổng.")
        chart_type = "bar"
        orientation = inferred_orientation
    elif chart_type == "bar" and inferred_orientation == "h" and orientation != "h":
        warnings.append("Điều chỉnh bar dọc → bar ngang để dễ đọc nhãn và tránh toàn biểu đồ cột.")
        orientation = "h"

    sort = str(obj.get("sort") or inferred_sort or "desc").lower()
    if sort not in {"desc", "asc", "none"}:
        sort = inferred_sort if inferred_sort in {"desc", "asc", "none"} else "desc"
    try:
        top_n = int(obj.get("top_n") or 15)
    except Exception:
        top_n = 15
    top_n = max(3, min(top_n, 30))

    return {
        "source_table": source_table,
        "label_col": label_col,
        "value_col": checked_value_cols[0],
        "value_cols": checked_value_cols,
        "chart_type": chart_type,
        "orientation": orientation,
        "sort": sort,
        "top_n": top_n,
        "reason": str(obj.get("reason") or "")[:500],
    }, warnings

def build_report_chart_plan(bundle: Any, *, use_llm: bool, model_name: str | None = None, ollama_url: str | None = None, timeout: int | float | None = None, regenerate_nonce: int = 0) -> dict[str, Any]:
    """Lập một biểu đồ mặc định từ bảng dữ liệu.

    Biểu đồ không còn dùng LLM planner riêng. LLM chỉ có vai trò chọn bảng
    ở build_report_table_plan(...). Chart được Python suy ra từ bảng/facts đã được
    validate để luôn bám đúng bảng dữ liệu và tránh debug kiểu chart LLM fail.
    """
    default_plan = _choose_default_chart_plan(bundle)
    context = _table_context(bundle)
    debug: dict[str, Any] = {
        "kind": "chart_plan",
        "mode": "derived_from_table_plan" if use_llm else "no_llm",
        "planner_scope": "chart_derived_from_validated_table",
        "llm_attempted": False,
        "llm_success": None,
        "source": "python_chart_derived_from_table_plan",
        "validated_plan": default_plan,
        "warnings": [],
        "context": context,
        "regenerate_nonce": regenerate_nonce,
        "execution": "python_render_from_validated_table_and_ReportFactsBundle",
        "note": "Biểu đồ không gọi LLM riêng; chart được tạo từ bảng đã chọn để luôn phản ánh đúng bảng.",
    }
    if default_plan is None:
        debug["warnings"].append("Không tìm được cặp cột phù hợp để vẽ biểu đồ mặc định.")
    return debug



# ───────────────────────────── chart color helpers ─────────────────────────────
# Ép màu Plotly trước khi xuất PNG/Word.
# Lỗi quan sát được: DOCX vẫn nhúng được ảnh, nhưng PNG chart đã là grayscale.
# Vì vậy sửa ở bước render chart, không sửa exporter Word.
REPORT_CHART_COLORS = [
    "#2563EB",  # blue
    "#DC2626",  # red
    "#16A34A",  # green
    "#F59E0B",  # amber
    "#7C3AED",  # purple
    "#0891B2",  # cyan
    "#DB2777",  # pink
    "#65A30D",  # lime
    "#EA580C",  # orange
    "#4F46E5",  # indigo
]


def _apply_report_chart_colors(fig: Any, chart_type: str = "bar") -> None:
    """Ép palette màu cho biểu đồ báo cáo trước khi export PNG/Word.

    Word/exporter chỉ nhúng ảnh PNG đã có. Nếu PNG đầu vào là grayscale, Word
    sẽ giữ nguyên grayscale. Hàm này bảo đảm Plotly figure có màu rõ ràng ở
    cả UI, PNG và DOCX.
    """
    if fig is None:
        return

    chart_type_key = str(chart_type or "bar").lower()

    try:
        fig.update_layout(
            template="plotly_white",
            colorway=REPORT_CHART_COLORS,
            paper_bgcolor="white",
            plot_bgcolor="white",
            font=dict(family="Times New Roman", color="#111827"),
            legend=dict(
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#E5E7EB",
                borderwidth=1,
            ),
        )
    except Exception:
        pass

    try:
        traces = list(getattr(fig, "data", []) or [])
        for idx, trace in enumerate(traces):
            color = REPORT_CHART_COLORS[idx % len(REPORT_CHART_COLORS)]

            if chart_type_key == "pie":
                labels = list(getattr(trace, "labels", []) or [])
                n = max(1, len(labels))
                trace.update(
                    marker=dict(
                        colors=[REPORT_CHART_COLORS[i % len(REPORT_CHART_COLORS)] for i in range(n)],
                        line=dict(color="white", width=1),
                    )
                )
                continue

            # Multi-series bar/line: mỗi trace một màu.
            trace.update(marker=dict(color=color))
            if hasattr(trace, "line"):
                trace.update(line=dict(color=color, width=2.5))

        # Single-series bar: nếu chỉ có một trace, cho từng cột một màu để Word dễ nhìn.
        if chart_type_key == "bar" and len(traces) == 1:
            trace = traces[0]
            y_values = list(getattr(trace, "y", []) or [])
            x_values = list(getattr(trace, "x", []) or [])
            n = max(len(y_values), len(x_values), 1)
            trace.update(
                marker=dict(
                    color=[REPORT_CHART_COLORS[i % len(REPORT_CHART_COLORS)] for i in range(n)],
                    line=dict(color="white", width=0.7),
                )
            )
    except Exception:
        pass

def _display_col(col: str) -> str:
    return DEFAULT_COLUMN_LABELS.get(str(col), str(col).replace("_", " ").title())


def execute_report_chart_plan(bundle: Any, chart_plan: dict[str, Any] | None, px_module: Any, *, title: str | None = None) -> dict[str, Any] | None:
    if px_module is None:
        return None
    plan = ((chart_plan or {}).get("validated_plan") or {})
    if not isinstance(plan, dict) or not plan:
        return None
    tables = _nonempty_tables(bundle)
    source = str(plan.get("source_table") or "")
    df = tables.get(source)
    if df is None or df.empty:
        return None
    label_col = str(plan.get("label_col") or "")
    special_chart = str(plan.get("special_chart") or "")

    if special_chart == "movement_total_trend":
        inline_rows = plan.get("inline_data") if isinstance(plan.get("inline_data"), list) else []
        display = pd.DataFrame(inline_rows)
        if display.empty or not {"period", "value"}.issubset(set(display.columns)):
            facts = _bundle_facts(bundle)
            try:
                nam_truoc = int(facts.get("nam_truoc") or pd.to_numeric(df.get("nam_truoc"), errors="coerce").dropna().iloc[0])
            except Exception:
                nam_truoc = "Đầu kỳ"
            try:
                nam_sau = int(facts.get("nam_sau") or pd.to_numeric(df.get("nam_sau"), errors="coerce").dropna().iloc[0])
            except Exception:
                nam_sau = "Cuối kỳ"
            try:
                tong_truoc = float(facts.get("tong_ky_truoc") or pd.to_numeric(df.get("so_ho_ky_truoc"), errors="coerce").sum())
                tong_sau = float(facts.get("tong_ky_sau") or pd.to_numeric(df.get("so_ho_ky_sau"), errors="coerce").sum())
            except Exception:
                return None
            display = pd.DataFrame([{"period": str(nam_truoc), "value": tong_truoc}, {"period": str(nam_sau), "value": tong_sau}])
        display = display.rename(columns={"period": "Mốc kỳ", "value": "Số hộ"})
        chart_title = title or "Biểu đồ đường tổng số hộ đầu kỳ và cuối kỳ"
        try:
            fig = px_module.line(display, x="Mốc kỳ", y="Số hộ", markers=True, title=chart_title)
            fig.update_layout(title_text="")
            _apply_report_chart_colors(fig, chart_type="line")
        except Exception:
            return None
        return {
            "source_table": source,
            "title": chart_title,
            "description": str((chart_plan or {}).get("table_title") or DEFAULT_TABLE_LABELS.get(source, source)),
            "fig": fig,
            "chart_df": display,
            "planner_reason": plan.get("reason"),
            "chart_debug": {
                "plan_source": (chart_plan or {}).get("source"),
                "validated_plan": plan,
                "warnings": (chart_plan or {}).get("warnings") or [],
                "fallback_notice": None,
                "input_rows": int(len(df)),
                "render_rows": int(len(display)),
                "chart_type": "line",
                "orientation": "v",
                "value_cols": ["__so_ho"],
                "special_chart": special_chart,
            },
        }

    raw_value_cols = plan.get("value_cols")
    value_cols: list[str] = []
    if isinstance(raw_value_cols, list):
        value_cols = [str(c) for c in raw_value_cols if str(c) in df.columns]
    value_col = str(plan.get("value_col") or (value_cols[0] if value_cols else ""))
    if not value_cols and value_col in df.columns:
        value_cols = [value_col]
    if label_col not in df.columns or not value_cols:
        return None

    sort = str(plan.get("sort") or "desc")
    top_n = int(plan.get("top_n") or 15)
    chart_type = str(plan.get("chart_type") or "bar")
    orientation = str(plan.get("orientation") or "v")
    display_labels = report_column_labels(bundle)

    def disp_col(col: str) -> str:
        return display_labels.get(str(col), _display_col(str(col)))

    chart_title = title or f"Biểu đồ {disp_col(value_cols[0]).lower()} theo {disp_col(label_col).lower()}"
    fallback_notice = None

    try:
        work = df[[label_col] + value_cols].copy()
        for c in value_cols:
            work[c] = pd.to_numeric(work[c], errors="coerce")
        work = work.dropna(subset=[label_col])
        if len(value_cols) == 1:
            work = work.dropna(subset=[value_cols[0]])
        else:
            work = work.dropna(subset=value_cols, how="all").fillna(0)
        if work.empty:
            return None

        if len(value_cols) > 1:
            work["__sort_total"] = work[value_cols].abs().sum(axis=1)
            if sort == "desc":
                work = work.sort_values("__sort_total", ascending=False)
            elif sort == "asc":
                work = work.sort_values("__sort_total", ascending=True)
            work = work.head(top_n)
            series_name = "Nhóm số liệu"
            long_df = work[[label_col] + value_cols].melt(id_vars=[label_col], var_name=series_name, value_name="Giá trị")
            long_df[series_name] = long_df[series_name].map(disp_col)
            display = long_df.rename(columns={label_col: disp_col(label_col)})
            x_label = disp_col(label_col)
            if chart_type == "line":
                fig = px_module.line(display, x=x_label, y="Giá trị", color=series_name, markers=True, title=chart_title)
            else:
                if orientation == "h":
                    fig = px_module.bar(display, x="Giá trị", y=x_label, color=series_name, orientation="h", barmode="group", title=chart_title)
                else:
                    fig = px_module.bar(display, x=x_label, y="Giá trị", color=series_name, barmode="group", title=chart_title)
            chart_df = display
        else:
            value_col = value_cols[0]
            work = work[[label_col, value_col]].copy()
            if sort == "desc":
                work = work.sort_values(value_col, ascending=False)
            elif sort == "asc":
                work = work.sort_values(value_col, ascending=True)
            work = work.head(top_n)
            display = work.rename(columns={label_col: disp_col(label_col), value_col: disp_col(value_col)})
            x_col = disp_col(label_col)
            y_col = disp_col(value_col)
            if chart_type == "pie" and len(display) > 8:
                fallback_notice = "Pie có quá nhiều nhóm; Python chuyển sang bar ngang."
                chart_type = "bar"
                orientation = "h"
            if chart_type == "pie":
                fig = px_module.pie(display, names=x_col, values=y_col, title=chart_title)
            elif chart_type == "line":
                fig = px_module.line(display, x=x_col, y=y_col, markers=True, title=chart_title)
            else:
                if orientation == "h":
                    fig = px_module.bar(display, x=y_col, y=x_col, orientation="h", title=chart_title)
                else:
                    fig = px_module.bar(display, x=x_col, y=y_col, title=chart_title)
            chart_df = display
        try:
            fig.update_layout(title_text="")
        except Exception:
            pass
        _apply_report_chart_colors(fig, chart_type=chart_type)
    except Exception:
        return None

    return {
        "source_table": source,
        "title": chart_title,
        "description": str((chart_plan or {}).get("table_title") or DEFAULT_TABLE_LABELS.get(source, source)),
        "fig": fig,
        "chart_df": chart_df,
        "planner_reason": plan.get("reason"),
        "chart_debug": {
            "plan_source": (chart_plan or {}).get("source"),
            "validated_plan": plan,
            "warnings": (chart_plan or {}).get("warnings") or [],
            "fallback_notice": fallback_notice,
            "input_rows": int(len(df)),
            "render_rows": int(len(chart_df)) if isinstance(chart_df, pd.DataFrame) else None,
            "chart_type": chart_type,
            "orientation": orientation,
            "value_cols": value_cols,
        },
    }


def _chart_all_rows(df: pd.DataFrame, *, cap: int = 30) -> int:
    """Số dòng nên đưa vào biểu đồ báo cáo.

    UI báo cáo ưu tiên phản ánh đúng bảng đang hiển thị. Vì vậy với các bảng
    biểu mẫu hành chính có số dòng vừa phải (8 huyện, 12 chỉ tiêu...), không
    tự cắt top 5 như planner LLM thường làm.
    """
    try:
        n = int(len(df))
    except Exception:
        n = 15
    if n <= 0:
        return 15
    return max(3, min(n, cap))


def _canonical_chart_plan_for_table(bundle: Any, table_name: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Plan nghiệp vụ bắt buộc cho các mẫu báo cáo 1-12.

    LLM planner có thể đề xuất thiếu cột hoặc top_n quá nhỏ. Hàm này kéo chart
    về đúng trọng tâm biểu mẫu để cả chế độ LLM và không LLM đều phản ánh cùng
    bảng dữ liệu trong UI Báo cáo.
    """
    warnings: list[str] = []
    tables = _nonempty_tables(bundle)
    template = _bundle_template(bundle)
    pattern = str(template.get("pattern") or "")
    try:
        template_id = int(template.get("id") or 0)
    except Exception:
        template_id = 0

    name = str(table_name)
    df = tables.get(name)
    if df is None or df.empty:
        return None, [f"Bảng {table_name!r} rỗng hoặc không tồn tại."]
    cols = [str(c) for c in df.columns]
    colset = set(cols)
    top_all = _chart_all_rows(df)

    def make(label: str, values: list[str], chart_type: str = "bar", orientation: str = "h", sort: str = "none", reason: str = "") -> dict[str, Any] | None:
        values = [v for v in values if v in colset]
        if label not in colset or not values:
            return None
        plan = {
            "source_table": name,
            "label_col": label,
            "value_col": values[0],
            "value_cols": values,
            "chart_type": chart_type,
            "orientation": orientation,
            "sort": sort,
            "top_n": top_all,
            "reason": reason or "Plan nghiệp vụ bắt buộc theo mẫu báo cáo, dùng toàn bộ dòng phù hợp trong bảng.",
        }
        return plan

    # Mẫu 1: bảng tổng hợp là cơ cấu nhóm hộ; bảng địa bàn phải so sánh đủ ba nhóm hộ.
    if template_id == 1 or pattern == "overview_result":
        if name == "template_chart":
            plan = make("nhom_chi_tieu", ["so_ho"], chart_type="pie", orientation="v", sort="desc", reason="Mẫu 1 - bảng tổng hợp nhóm hộ là cơ cấu một tổng nên dùng pie.")
            if plan:
                return plan, warnings
        if name == "template_main":
            plan = make("huyen", ["so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"], chart_type="bar", orientation="h", sort="none", reason="Mẫu 1 - bảng địa bàn cần so sánh đủ hộ nghèo, hộ cận nghèo và NLNN mức sống trung bình.")
            if plan:
                return plan, warnings

    # Mẫu 2-3: diễn biến phải thể hiện cả đầu kỳ và cuối kỳ, không chỉ top cuối kỳ.
    if template_id in {2, 3} or pattern == "movement":
        plan = make("huyen", ["so_ho_ky_truoc", "so_ho_ky_sau"], chart_type="bar", orientation="h", sort="none", reason="Mẫu diễn biến phải đối chiếu số hộ đầu kỳ và cuối kỳ cho toàn bộ địa bàn trong bảng.")
        if plan:
            return plan, warnings

    # Mẫu 4/6: số lượng thiếu hụt; Mẫu 5/7: tỷ lệ thiếu hụt. Hiển thị toàn bộ chỉ tiêu.
    if template_id in {4, 6} or pattern == "deprivation_count":
        plan = make("chi_tieu", ["so_ho"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu chỉ số thiếu hụt theo số lượng: biểu đồ dùng số hộ thiếu hụt và hiển thị đủ các chỉ tiêu.")
        if plan:
            return plan, warnings
    if template_id in {5, 7} or pattern == "deprivation_ratio":
        plan = make("chi_tieu", ["ty_le_%"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu tỷ lệ thiếu hụt: biểu đồ dùng tỷ lệ thiếu hụt (%) và hiển thị đủ các chỉ tiêu.")
        if plan:
            return plan, warnings

    # Mẫu 8: bảng chính theo địa bàn, chỉ so sánh các cặp hộ nghèo/cận nghèo của 3 nhóm đúng mẫu.
    if template_id == 8 or pattern == "vulnerable_groups":
        if {"huyen", "ho_ngheo_dtts", "ho_can_ngheo_dtts"}.issubset(colset):
            plan = make("huyen", ["ho_ngheo_dtts", "ho_can_ngheo_dtts"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu 8 theo địa bàn; biểu đồ ưu tiên cặp hộ nghèo/cận nghèo DTTS, không dùng nhom_doi_tuong.")
            if plan:
                return plan, warnings
        if {"huyen", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld"}.issubset(colset):
            plan = make("huyen", ["ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu 8 theo địa bàn; biểu đồ dùng cặp không có khả năng lao động.")
            if plan:
                return plan, warnings

    # Mẫu 9/10: thường cần so sánh hộ nghèo và hộ cận nghèo cùng lúc.
    if pattern in {"ethnicity", "causes"} or template_id in {9, 10}:
        label = "nhom_doi_tuong" if "nhom_doi_tuong" in colset else ("dan_toc" if "dan_toc" in colset else ("nguyen_nhan" if "nguyen_nhan" in colset else ("chi_tieu" if "chi_tieu" in colset else "huyen")))
        plan = make(label, ["so_ho_ngheo", "so_ho_can_ngheo"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu nhóm/dân tộc/nguyên nhân cần thể hiện đồng thời hộ nghèo và hộ cận nghèo, không chỉ một cột.")
        if plan:
            return plan, warnings

    # Mẫu 11: bảng có hai nhóm đối tượng, chart cũ thiếu cận nghèo; dùng grouped bar.
    if template_id == 11 or pattern == "child_deprivation":
        plan = make("chi_tieu", ["so_ho_ngheo", "so_ho_can_ngheo"], chart_type="bar", orientation="h", sort="desc", reason="Mẫu 11 phải so sánh cùng lúc trẻ thuộc hộ nghèo và trẻ thuộc hộ cận nghèo theo từng chỉ tiêu.")
        if plan:
            return plan, warnings

    # Mẫu 12: không chỉ vẽ số hộ mục tiêu; cần cho thấy mẫu số theo hộ và số hộ nghèo đa chiều.
    if template_id == 12 or pattern == "multidimensional_standard":
        plan = make("huyen", ["tong_ho_ra_soat", "so_ho_muc_tieu"], chart_type="bar", orientation="h", sort="none", reason="Mẫu 12 cần đối chiếu tổng hộ đã rà soát/phân loại với số hộ nghèo đa chiều để tránh lẫn hộ và nhân khẩu.")
        if plan:
            return plan, warnings

    return None, warnings

def _choose_default_chart_plan_for_table(bundle: Any, table_name: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Chọn plan mặc định cho một bảng cụ thể.

    Python sinh đủ chart hợp lý: pie cho cơ cấu, line cho diễn biến tổng, bar/thanh cho so sánh
    theo rule riêng của UI báo cáo: thời gian = line, cơ cấu một tổng = pie,
    tỷ lệ độc lập/chỉ tiêu/địa bàn = bar ngang.
    """
    warnings: list[str] = []
    tables = _nonempty_tables(bundle)
    facts = _bundle_facts(bundle)
    template = _bundle_template(bundle)
    df = tables.get(str(table_name))
    if df is None or df.empty:
        return None, [f"Bảng {table_name!r} rỗng hoặc không tồn tại."]

    canonical_plan, canonical_warnings = _canonical_chart_plan_for_table(bundle, str(table_name))
    if canonical_plan is not None:
        return canonical_plan, canonical_warnings

    cols = [str(c) for c in df.columns]
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    label_candidates = [c for c in cols if c not in numeric]
    chart_hint = facts.get("chart_insights") if isinstance(facts, dict) else {}
    hinted_label = chart_hint.get("label_col") if isinstance(chart_hint, dict) else None
    hinted_value = chart_hint.get("value_col") if isinstance(chart_hint, dict) else None

    pattern = str(template.get("pattern") or "")
    label_col = hinted_label if hinted_label in cols else None
    if not label_col:
        for c in ["nam", "Năm", "huyen", "xa_phuong", "chi_tieu", "dan_toc", "nhom_chi_tieu", "phan_loai"]:
            if c in cols:
                label_col = c
                break
    if not label_col and label_candidates:
        label_col = label_candidates[0]

    value_cols: list[str] = []
    multi = _multi_value_candidates(cols, pattern)
    if multi and all(c in numeric for c in multi):
        value_cols = multi

    value_col = hinted_value if hinted_value in numeric else None
    if not value_col and not value_cols:
        for c in _single_value_candidates(pattern):
            if c in numeric:
                value_col = c
                break
    if not value_col and not value_cols and numeric:
        value_col = numeric[0]

    if not label_col:
        return None, [f"Bảng {table_name!r} không có cột nhãn phù hợp để vẽ biểu đồ."]
    if not value_col and not value_cols:
        return None, [f"Bảng {table_name!r} không có cột số phù hợp để vẽ biểu đồ."]
    if value_col and label_col == value_col:
        return None, [f"Bảng {table_name!r} không tách được cột nhãn và cột giá trị."]

    first_value = value_cols[0] if value_cols else str(value_col)
    chart_type, orientation, sort, top_n, shape_reason = _infer_chart_shape(
        pattern=pattern,
        table_name=str(table_name),
        label_col=str(label_col),
        value_col=str(first_value),
        value_cols=value_cols,
        row_count=_safe_int_len(df),
        df=df,
    )
    if chart_type == "pie" and int(len(df)) > 8:
        warnings.append("Bảng có nhiều nhóm; không dùng pie, chuyển sang bar ngang để dễ đọc.")
        chart_type = "bar"
        orientation = "h"

    plan = {
        "source_table": str(table_name),
        "label_col": str(label_col),
        "value_col": str(first_value),
        "chart_type": chart_type,
        "orientation": orientation,
        "sort": sort,
        "top_n": top_n,
        "reason": f"Kế hoạch mặc định cho từng bảng từ Python. {shape_reason}",
    }
    if value_cols:
        plan["value_cols"] = [str(c) for c in value_cols]
    return plan, warnings

def _table_item_names(table_items: list[dict[str, Any]] | None, bundle: Any) -> list[dict[str, Any]]:
    tables = _nonempty_tables(bundle)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in table_items or []:
        name = str((item or {}).get("name") or "")
        if name in tables and name not in seen:
            out.append({
                "name": name,
                "title": str((item or {}).get("title") or DEFAULT_TABLE_LABELS.get(name, name)),
                "reason": str((item or {}).get("planner_reason") or (item or {}).get("reason") or ""),
            })
            seen.add(name)
    if out:
        return out
    for item in _default_table_selection(bundle):
        name = str(item.get("name") or "")
        if name in tables and name not in seen:
            out.append({"name": name, "title": DEFAULT_TABLE_LABELS.get(name, name), "reason": str(item.get("reason") or "")})
            seen.add(name)
    return out



def _append_auxiliary_semantic_chart_plans(debug: dict[str, Any], bundle: Any, table_refs: list[dict[str, Any]] | None = None) -> None:
    """Thêm biểu đồ phụ khi một bảng có nhiều nhóm đơn vị không nên trộn chung.

    Quy tắc cũ là một bảng một biểu đồ. Với các mẫu hành chính như 1/11/12,
    cùng một bảng chứa cả hộ, nhân khẩu, tỷ lệ hoặc cơ cấu dân tộc. Nếu nhồi
    chung một chart sẽ sai đơn vị; nếu chỉ chọn một cột thì thiếu thông tin.
    Vì vậy thêm chart phụ, nhưng vẫn render từ cùng bảng và ghi rõ source.
    """
    try:
        template = _bundle_template(bundle)
        tid = int(template.get("id") or 0)
        pattern = str(template.get("pattern") or "")
    except Exception:
        tid, pattern = 0, ""
    existing = debug.get("chart_plans") or []
    existing_keys = set()
    for e in existing:
        plan = (e or {}).get("validated_plan") or {}
        key = (plan.get("source_table"), plan.get("label_col"), tuple(plan.get("value_cols") or []))
        existing_keys.add(key)

    def add(
        table_name: str,
        title: str,
        values: list[str],
        *,
        label: str,
        reason: str,
        sort: str = "none",
        chart_type: str = "bar",
        orientation: str = "h",
    ) -> None:
        tables = _nonempty_tables(bundle)
        df = tables.get(table_name)
        if df is None or df.empty or label not in df.columns:
            return
        checked_values: list[str] = []
        for v in values:
            if v in df.columns:
                try:
                    series = pd.to_numeric(df[v], errors="coerce")
                    if not series.dropna().empty:
                        checked_values.append(v)
                except Exception:
                    continue
        if not checked_values:
            return
        try:
            top_n = _chart_all_rows(df)
        except Exception:
            top_n = 30
        plan = {
            "source_table": table_name,
            "label_col": label,
            "value_col": checked_values[0],
            "value_cols": checked_values,
            "chart_type": chart_type,
            "orientation": orientation if chart_type == "bar" else "v",
            "sort": sort,
            "top_n": top_n,
            "reason": reason,
        }
        key = (plan.get("source_table"), plan.get("label_col"), tuple(plan.get("value_cols") or []))
        if key in existing_keys:
            return
        existing_keys.add(key)
        existing.append({
            "table_name": table_name,
            "table_title": title,
            "chart_generated": True,
            "reason_if_skipped": None,
            "llm_attempted": False,
            "llm_success": None,
            "source": "python_auxiliary_chart_derived_from_table",
            "validated_plan": plan,
            "warnings": ["Biểu đồ phụ được Python tạo từ bảng đã chọn vì bảng có nhiều nhóm đơn vị; không trộn hộ, nhân khẩu và tỷ lệ trong cùng một chart."],
        })

    def add_movement_total_line() -> None:
        """Thêm biểu đồ đường tổng toàn phạm vi cho mẫu diễn biến 2/3.

        Bảng diễn biến chính theo huyện vẫn dùng grouped bar. Biểu đồ đường chỉ
        dùng 2 mốc tổng toàn tỉnh/phạm vi để thể hiện hướng thay đổi đầu kỳ → cuối kỳ.
        """
        tables = _nonempty_tables(bundle)
        table_name = "template_main" if "template_main" in tables else ("main" if "main" in tables else "")
        if not table_name:
            return
        df = tables.get(table_name)
        if df is None or df.empty:
            return
        facts = _bundle_facts(bundle)
        try:
            nam_truoc = int(facts.get("nam_truoc") or pd.to_numeric(df.get("nam_truoc"), errors="coerce").dropna().iloc[0])
        except Exception:
            nam_truoc = 0
        try:
            nam_sau = int(facts.get("nam_sau") or pd.to_numeric(df.get("nam_sau"), errors="coerce").dropna().iloc[0])
        except Exception:
            nam_sau = 0
        try:
            tong_truoc = float(facts.get("tong_ky_truoc") or pd.to_numeric(df.get("so_ho_ky_truoc"), errors="coerce").sum())
            tong_sau = float(facts.get("tong_ky_sau") or pd.to_numeric(df.get("so_ho_ky_sau"), errors="coerce").sum())
        except Exception:
            return
        if not (tong_truoc or tong_sau):
            return
        plan = {
            "source_table": table_name,
            "label_col": "__period",
            "value_col": "__so_ho",
            "value_cols": ["__so_ho"],
            "chart_type": "line",
            "orientation": "v",
            "sort": "none",
            "top_n": 2,
            "special_chart": "movement_total_trend",
            "inline_data": [
                {"period": str(nam_truoc or "Đầu kỳ"), "value": int(tong_truoc) if float(tong_truoc).is_integer() else tong_truoc},
                {"period": str(nam_sau or "Cuối kỳ"), "value": int(tong_sau) if float(tong_sau).is_integer() else tong_sau},
            ],
            "reason": "Mẫu diễn biến có hai mốc thời gian tổng toàn phạm vi nên thêm biểu đồ đường đầu kỳ → cuối kỳ; bảng theo địa bàn vẫn dùng biểu đồ cột/thanh để so sánh chi tiết.",
        }
        key = (plan.get("source_table"), plan.get("special_chart"), tuple(plan.get("value_cols") or []))
        if key in existing_keys:
            return
        existing_keys.add(key)
        existing.append({
            "table_name": table_name,
            "table_title": "Tổng diễn biến toàn phạm vi",
            "chart_generated": True,
            "reason_if_skipped": None,
            "llm_attempted": False,
            "llm_success": None,
            "source": "python_auxiliary_line_chart_from_movement_totals",
            "validated_plan": plan,
            "warnings": ["Biểu đồ đường phụ được Python tạo từ tổng đầu kỳ/cuối kỳ; không thay thế biểu đồ so sánh theo địa bàn."],
        })

    table_titles = {str(x.get("name") or ""): str(x.get("title") or DEFAULT_TABLE_LABELS.get(str(x.get("name") or ""), str(x.get("name") or ""))) for x in (table_refs or []) if isinstance(x, dict)}
    title_main = table_titles.get("template_main") or DEFAULT_TABLE_LABELS.get("template_main", "Bảng số liệu báo cáo")
    title_chart = table_titles.get("template_chart") or DEFAULT_TABLE_LABELS.get("template_chart", "Bảng tổng hợp phục vụ biểu đồ")

    if tid == 1 or pattern == "overview_result":
        add("template_chart", title_chart, ["so_ho"], label="nhom_chi_tieu", chart_type="pie", orientation="v", sort="desc", reason="Mẫu 1 có bảng tổng hợp nhóm hộ loại trừ nhau nên thêm biểu đồ tròn cơ cấu nhóm hộ; không dùng pie cho bảng địa bàn.")
        add("template_main", title_main, ["so_khau_ngheo", "so_khau_can_ngheo", "so_khau_nlnndn_mstb"], label="huyen", sort="none", reason="Mẫu 1 có cả số hộ và số nhân khẩu; thêm biểu đồ nhân khẩu để không bỏ thông tin trong bảng địa bàn.")
    if tid in {2, 3} or pattern == "movement":
        add_movement_total_line()
        add("template_main", title_main, ["giam_1", "giam_2", "giam_khac", "tang_1", "tang_2", "tang_3", "tang_khac"], label="huyen", sort="none", reason="Mẫu diễn biến ngoài đầu kỳ/cuối kỳ còn có cấu phần tăng/giảm; thêm biểu đồ cấu phần để đối chiếu bảng.")
    if tid == 11 or pattern == "child_deprivation":
        add("template_main", title_main, ["ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%"], label="chi_tieu", sort="desc", reason="Mẫu 11 có cả số trẻ và tỷ lệ; thêm biểu đồ tỷ lệ riêng để không bỏ cột tỷ lệ trong bảng.")
    if tid == 8 or pattern == "vulnerable_groups":
        add("template_main", title_main, ["ho_ngheo_dtts", "ho_can_ngheo_dtts"], label="huyen", sort="desc", reason="Mẫu 8 theo địa bàn; biểu đồ so sánh hộ nghèo/cận nghèo DTTS.")
        add("template_main", title_main, ["ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld", "ho_ngheo_co_cong", "ho_can_ngheo_co_cong"], label="huyen", sort="desc", reason="Mẫu 8 chỉ dùng hai nhóm còn lại của biểu mẫu: không có khả năng lao động và có người có công.")
    if tid == 12 or pattern == "multidimensional_standard":
        add("template_main", title_main, ["ty_le_muc_tieu_%"], label="huyen", sort="desc", reason="Mẫu 12 có cột tỷ lệ hộ nghèo đa chiều; thêm biểu đồ tỷ lệ riêng thay vì trộn với số hộ.")
        add("template_main", title_main, ["ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%"], label="huyen", sort="desc", reason="Mẫu 12 có W/X: tỷ lệ hộ nghèo trong nhóm DTTS và trong nhóm DTTS tại chỗ.")
        add("template_main", title_main, ["so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho"], label="huyen", sort="none", reason="Mẫu 12 có cơ cấu hộ nghèo đa chiều theo dân tộc; thêm biểu đồ số hộ theo nhóm dân tộc để phản ánh các cột còn lại.")
    debug["chart_plans"] = existing
    if len(existing) > 0:
        debug["execution"] = "chart_per_visible_table_plus_auxiliary_when_table_has_multiple_units"

def build_report_chart_plans(
    bundle: Any,
    *,
    table_items: list[dict[str, Any]] | None = None,
    use_llm: bool,
    model_name: str | None = None,
    ollama_url: str | None = None,
    timeout: int | float | None = None,
    regenerate_nonce: int = 0,
) -> dict[str, Any]:
    """Lập kế hoạch biểu đồ theo từng bảng đã được chọn.

    LLM chỉ planner BẢNG. Biểu đồ được Python suy ra từ chính các bảng
    hiển thị đã qua validate. Cách này giúp chart luôn bám bảng, không còn tình
    trạng LLM chọn sai cột/loại biểu đồ rồi bị fallback.
    """
    context = _table_context(bundle)
    tables = _nonempty_tables(bundle)
    table_refs = _table_item_names(table_items, bundle)
    debug: dict[str, Any] = {
        "kind": "multi_chart_plan",
        "mode": "derived_from_table_plan" if use_llm else "no_llm",
        "planner_scope": "chart_derived_from_validated_visible_tables",
        "llm_attempted": False,
        "llm_success": None,
        "source": "python_chart_derived_from_table_plan_per_table",
        "warnings": [],
        "context": context,
        "regenerate_nonce": regenerate_nonce,
        "execution": "one_chart_per_visible_table_python_derived_from_table_plan",
        "chart_plans": [],
        "note": "LLM chỉ chọn bảng ở table_plan; biểu đồ được Python tạo từ bảng đã chọn để phản ánh đúng bảng.",
    }
    if not tables:
        debug["warnings"].append("Không có bảng dữ liệu trong ReportFactsBundle.")
        return debug
    if not table_refs:
        debug["warnings"].append("Không có bảng hiển thị hợp lệ để lập biểu đồ.")
        return debug

    for ref in table_refs:
        name = str(ref.get("name") or "")
        title = str(ref.get("title") or DEFAULT_TABLE_LABELS.get(name, name))
        default_plan, default_warnings = _choose_default_chart_plan_for_table(bundle, name)
        entry: dict[str, Any] = {
            "table_name": name,
            "table_title": title,
            "chart_generated": False,
            "reason_if_skipped": None,
            "planner_scope": "chart_derived_from_table",
            "llm_attempted": False,
            "llm_success": None,
            "source": "python_chart_derived_from_validated_table",
            "validated_plan": default_plan,
            "warnings": list(default_warnings),
            "table_planner_reason": ref.get("reason"),
        }
        if default_plan is None:
            entry["reason_if_skipped"] = "; ".join(default_warnings) or "Không tạo được plan biểu đồ từ bảng."
            debug["chart_plans"].append(entry)
            continue
        entry["chart_generated"] = True
        entry["warnings"].append("Chart được Python tạo từ bảng đã chọn; không gọi LLM chart planner riêng.")
        debug["chart_plans"].append(entry)

    _append_auxiliary_semantic_chart_plans(debug, bundle, table_refs)
    return debug



def _template_id_for_chart_title(bundle: Any) -> int:
    try:
        return int(((getattr(bundle, "template", {}) or {}).get("id")) or 0)
    except Exception:
        return 0


def _chart_title_description_for_plan(bundle: Any, table_title: str, plan: dict[str, Any]) -> tuple[str, str]:
    """Tiêu đề/diễn giải biểu đồ theo nghiệp vụ, tránh cảm giác thiếu thông tin."""
    tid = _template_id_for_chart_title(bundle)
    value_cols = [str(c) for c in (plan.get("value_cols") or [])]
    value_col = str(plan.get("value_col") or (value_cols[0] if value_cols else ""))
    if tid in {2, 3}:
        if str(plan.get("special_chart") or "") == "movement_total_trend":
            return (
                "Biểu đồ đường tổng số hộ đầu kỳ và cuối kỳ",
                "Biểu đồ thể hiện hai mốc tổng toàn phạm vi để nhìn nhanh chiều biến động chung; so sánh chi tiết từng địa bàn vẫn dùng biểu đồ cột/thanh."
            )
        component_cols = {"giam_1", "giam_2", "giam_khac", "tang_1", "tang_2", "tang_3", "tang_khac"}
        if any(v in component_cols for v in value_cols + [value_col]):
            return (
                "Biểu đồ cấu phần tăng, giảm trong kỳ theo địa bàn",
                "Biểu đồ thể hiện các nhóm giảm và tăng trong bảng diễn biến; số hộ đầu kỳ/cuối kỳ được thể hiện ở biểu đồ mốc kỳ riêng."
            )
        return (
            "Biểu đồ so sánh số hộ đầu kỳ và cuối kỳ theo địa bàn",
            "Biểu đồ dùng cùng bảng diễn biến, thể hiện hai mốc đầu kỳ và cuối kỳ; phần chênh lệch/tỷ lệ vẫn xem trong bảng."
        )
    if tid in {4, 6}:
        return (
            "Biểu đồ số hộ thiếu hụt theo chỉ tiêu",
            "Biểu đồ hiển thị đủ các chỉ tiêu thiếu hụt theo số hộ, không cộng thành cơ cấu 100%."
        )
    if tid in {5, 7}:
        return (
            "Biểu đồ tỷ lệ thiếu hụt theo chỉ tiêu",
            "Biểu đồ hiển thị đủ các chỉ tiêu theo tỷ lệ thiếu hụt (%); số hộ là thông tin đối chiếu trong bảng."
        )
    if tid == 11:
        if any("ty_le" in v or v.endswith("_%") for v in value_cols + [value_col]):
            return (
                "Biểu đồ tỷ lệ thiếu hụt của trẻ em theo nhóm hộ",
                "Biểu đồ so sánh tỷ lệ trẻ em thiếu chỉ tiêu giữa hộ nghèo và hộ cận nghèo; số trẻ được thể hiện ở biểu đồ số lượng riêng."
            )
        return (
            "Biểu đồ số trẻ em thiếu chỉ tiêu theo nhóm hộ",
            "Biểu đồ so sánh số trẻ em thuộc hộ nghèo và hộ cận nghèo theo từng chỉ tiêu thiếu hụt."
        )
    if tid == 12:
        if value_cols == ["ty_le_muc_tieu_%"] or value_col == "ty_le_muc_tieu_%":
            return (
                "Biểu đồ tỷ lệ hộ nghèo đa chiều theo địa bàn",
                "Biểu đồ dùng riêng cột tỷ lệ hộ nghèo đa chiều (%), không trộn với số hộ hoặc nhân khẩu."
            )
        if any(v in {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho"} for v in value_cols + [value_col]):
            return (
                "Biểu đồ cơ cấu hộ nghèo đa chiều theo dân tộc",
                "Biểu đồ thể hiện số hộ Kinh, DTTS và DTTS tại chỗ trong nhóm hộ nghèo đa chiều theo địa bàn."
            )
        return (
            "Biểu đồ tổng hộ rà soát và số hộ nghèo đa chiều theo địa bàn",
            "Biểu đồ đối chiếu mẫu số theo hộ với số hộ nghèo đa chiều; tỷ lệ và cơ cấu dân tộc được tách thành biểu đồ riêng để tránh trộn đơn vị."
        )
    if tid == 1 and "nhom_chi_tieu" in {str(plan.get("label_col") or "")}:
        return (
            "Biểu đồ cơ cấu các nhóm hộ theo kết quả rà soát",
            "Biểu đồ thể hiện cơ cấu nhóm hộ tổng hợp; bảng địa bàn dùng biểu đồ riêng để so sánh quy mô theo huyện/thành phố."
        )
    if tid == 1:
        if any(v.startswith("so_khau") for v in value_cols + [value_col]):
            return (
                "Biểu đồ quy mô nhân khẩu theo nhóm hộ và địa bàn",
                "Biểu đồ dùng các cột nhân khẩu của bảng địa bàn; số hộ được thể hiện ở biểu đồ nhóm hộ riêng."
            )
        return (
            "Biểu đồ quy mô nhóm hộ theo địa bàn",
            "Biểu đồ so sánh các nhóm hộ chính theo từng huyện/thành phố từ bảng báo cáo."
        )
    title = f"Biểu đồ {str(table_title or 'bảng số liệu').lower()}"
    return title, str((plan or {}).get("reason") or table_title or "Biểu đồ đối chiếu với bảng số liệu báo cáo.")


def execute_report_chart_plans(bundle: Any, chart_plans_debug: dict[str, Any] | None, px_module: Any) -> list[dict[str, Any]]:
    """Render danh sách biểu đồ từ multi-chart debug plan."""
    out: list[dict[str, Any]] = []
    if px_module is None:
        return out
    for idx, entry in enumerate(((chart_plans_debug or {}).get("chart_plans") or []), start=1):
        if not isinstance(entry, dict) or not entry.get("chart_generated"):
            continue
        plan = entry.get("validated_plan")
        if not isinstance(plan, dict) or not plan:
            continue
        single_debug = {
            "kind": "chart_plan",
            "source": entry.get("source"),
            "validated_plan": plan,
            "warnings": entry.get("warnings") or [],
        }
        table_title = str(entry.get("table_title") or entry.get("table_name") or idx)
        title, description = _chart_title_description_for_plan(bundle, table_title, plan)
        rendered = execute_report_chart_plan(bundle, single_debug, px_module, title=title)
        if rendered is None:
            continue
        rendered["table_name"] = entry.get("table_name")
        rendered["table_title"] = entry.get("table_title")
        rendered["title"] = title
        rendered["description"] = description
        rendered["planner_reason"] = (plan or {}).get("reason") or entry.get("reason_if_skipped")
        rendered["chart_debug"] = {
            **(rendered.get("chart_debug") or {}),
            "multi_chart_index": idx,
            "table_name": entry.get("table_name"),
            "table_title": entry.get("table_title"),
            "llm_attempted": entry.get("llm_attempted"),
            "llm_success": entry.get("llm_success"),
            "source": entry.get("source"),
            "raw_llm_text": entry.get("raw_llm_text"),
            "warnings": entry.get("warnings") or [],
        }
        out.append(rendered)
    return out
