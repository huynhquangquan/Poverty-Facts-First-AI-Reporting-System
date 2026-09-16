"""
report/template_excel_llm_exporter.py

Excel LLM-assisted mapping + Python validated fallback cho mẫu 1-12.
LLM chỉ hỗ trợ ánh xạ cột template -> fact_key và tự repair mapping.
Python vẫn validate mapping, truy vấn DB, tính số và ghi Excel.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from poverty_chatbot.config import DB_PATH, MODEL_NAME
except Exception:  # pragma: no cover
    DB_PATH = Path("poverty.db")
    MODEL_NAME = "qwen2.5:3b"

try:
    from poverty_chatbot.config import OLLAMA_URL, LLM_TIMEOUT
except Exception:  # pragma: no cover
    OLLAMA_URL = "http://localhost:11434/api/chat"
    LLM_TIMEOUT = 20

try:
    from report.template_excel_common import (
        DATA_SAMPLES_DIR,
        _extract_json_object,
        _find_template_sample_path,
        _relative_or_str,
        _short_text,
        _vn_key,
    )
except Exception:  # hỗ trợ chạy rời khi copy file để debug
    from template_excel_common import (  # type: ignore
        DATA_SAMPLES_DIR,
        _extract_json_object,
        _find_template_sample_path,
        _relative_or_str,
        _short_text,
        _vn_key,
    )

# Không ghi log riêng llm_excel_mau*.jsonl nữa.
# Debug Excel LLM vẫn được trả về cho app.py và được gộp vào report_task_*.jsonl
# khi người dùng bấm "Chuẩn bị file tải xuống".
write_jsonl_log = None  # type: ignore


def _set_workbook_demo_properties(wb: Any, *, title: str | None = None) -> None:
    """Xóa metadata cá nhân giữ lại từ file mẫu gốc trước khi xuất Excel demo."""
    try:
        props = wb.properties
        props.creator = "admin"
        props.lastModifiedBy = "admin"
        props.title = ""
        props.subject = ""
        props.keywords = ""
        props.description = ""
        props.category = ""
        props.contentStatus = ""
        # Không ghi dấu vết experimental dài vào metadata vì đây là bản demo.
        try:
            props.comments = ""
        except Exception:
            pass
    except Exception:
        pass


# ── Experimental: LLM-assisted REAL Excel export for mẫu 1 ───────────────────
# Mục tiêu: để Qwen/LLM tham gia thật vào bước điền số liệu, nhưng chỉ ở mức
# ánh xạ ngữ nghĩa cột -> fact_key. Python vẫn tính số, validate plan, ghi Excel.
# Luồng cũ export_template_xlsx(...) vẫn giữ nguyên và là default.

MAU1_ALLOWED_COLUMN_FACTS = {
    "reviewed_households",
    "reviewed_people",
    "poor_households",
    "poor_household_ratio",
    "near_poor_households",
    "near_poor_household_ratio",
    "living_standard_average_households",
    "living_standard_average_household_ratio",
    "poor_people",
    "poor_people_ratio",
    "near_poor_people",
    "near_poor_people_ratio",
    "living_standard_average_people",
    "living_standard_average_people_ratio",
}

MAU1_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "reviewed_households", "unit": "households", "reason": "Cột 'Tổng số hộ dân cư - Số hộ'"},
    {"column": "D", "fact_key": "reviewed_people", "unit": "persons", "reason": "Cột 'Tổng số hộ dân cư - Nhân khẩu'"},
    {"column": "E", "fact_key": "poor_households", "unit": "households", "reason": "Cột 'Tổng số hộ nghèo - Số hộ'"},
    {"column": "F", "fact_key": "poor_household_ratio", "unit": "percent", "reason": "Cột tỷ lệ hộ nghèo trên tổng hộ dân cư"},
    {"column": "G", "fact_key": "near_poor_households", "unit": "households", "reason": "Cột 'Tổng số hộ cận nghèo - Số hộ'"},
    {"column": "H", "fact_key": "near_poor_household_ratio", "unit": "percent", "reason": "Cột tỷ lệ hộ cận nghèo trên tổng hộ dân cư"},
    {"column": "I", "fact_key": "living_standard_average_households", "unit": "households", "reason": "Cột hộ nông/lâm/ngư nghiệp có mức sống trung bình - số hộ"},
    {"column": "J", "fact_key": "living_standard_average_household_ratio", "unit": "percent", "reason": "Cột tỷ lệ hộ mức sống trung bình trên tổng hộ dân cư"},
    {"column": "K", "fact_key": "poor_people", "unit": "persons", "reason": "Cột tổng số khẩu nghèo"},
    {"column": "L", "fact_key": "poor_people_ratio", "unit": "percent", "reason": "Cột tỷ lệ khẩu nghèo trên tổng nhân khẩu"},
    {"column": "M", "fact_key": "near_poor_people", "unit": "persons", "reason": "Cột tổng số khẩu cận nghèo"},
    {"column": "N", "fact_key": "near_poor_people_ratio", "unit": "percent", "reason": "Cột tỷ lệ khẩu cận nghèo trên tổng nhân khẩu"},
    {"column": "O", "fact_key": "living_standard_average_people", "unit": "persons", "reason": "Cột khẩu hộ mức sống trung bình"},
    {"column": "P", "fact_key": "living_standard_average_people_ratio", "unit": "percent", "reason": "Cột tỷ lệ khẩu hộ mức sống trung bình trên tổng nhân khẩu"},
]


NON_POOR = "Hộ không nghèo"

MOVEMENT_OTHER_REASON_COLUMNS = {
    "ly_do_bien_dong_khac",
    "khac_thay_doi_nhan_khau",
    "khac_chuyen_di",
    "khac_chuyen_den",
    "khac_tach_ho",
    "khac_nhap_ho",
    "khac_chu_ho_chet",
}

MOVEMENT_OTHER_NO_REASON_WARNING = (
    "DB chưa có cột lý do biến động chi tiết cho nhóm 'khác'; exporter LLM ghi 0 cho cột G/K "
    "và không dùng nhãn giảm/tăng khác để cân bằng công thức."
)
MEDIUM_LIVING_PROXY_WARNING = (
    "Mẫu 1: đang bật allow_demo_proxy_nlnn_mstb=True nên chỉ tiêu hộ nông, lâm, ngư nghiệp "
    "có mức sống trung bình được tính bằng proxy nghề nghiệp chủ hộ trong DB; không sử dụng như số chính thức nếu thiếu dữ liệu nghiệp vụ trực tiếp."
)
REVIEW_SCOPE_WARNING = (
    "DB không có bảng dân cư toàn địa bàn. Chỉ tiêu này được tính theo tổng số hộ/khẩu có trong dữ liệu "
    "rà soát/phân loại của hệ thống, gồm hộ nghèo, hộ cận nghèo và hộ không nghèo. Không sử dụng như "
    "tổng dân cư hoặc tỷ lệ hộ nghèo chính thức trên toàn bộ dân cư địa bàn."
)
ALLOW_DEMO_PROXY_NLNN_MSTB = str(os.getenv("ALLOW_DEMO_PROXY_NLNN_MSTB", "")).strip().lower() in {"1", "true", "yes", "co"}
NLNN_JOB_VALUES = ("Nông nghiệp", "Lâm nghiệp", "Ngư nghiệp")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _movement_other_reason_available() -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        return any(_column_exists(conn, "ho_ngheo", column) for column in MOVEMENT_OTHER_REASON_COLUMNS)


def _template_excel_norm(text: Any) -> str:
    # Dùng _vn_key sẵn có để so khớp tiếng Việt không dấu, sau đó bỏ khoảng trắng.
    return str(_vn_key(str(text or ""))).replace(" ", "").strip().lower()

def _add_comment(cell: Any, text: str, *, author: str = "admin") -> None:
    try:
        from openpyxl.comments import Comment  # type: ignore
        cell.comment = Comment(text, author)
    except Exception:
        pass


def _add_comments_to_matching_header_cells(
    ws: Any,
    *,
    keywords: tuple[str, ...],
    note: str,
    max_row: int = 12,
    max_col: int = 24,
) -> None:
    norm_keywords = tuple(_template_excel_norm(k) for k in keywords if str(k).strip())
    for row in range(1, min(ws.max_row, max_row) + 1):
        for col in range(1, min(ws.max_column, max_col) + 1):
            cell = ws.cell(row, col)
            value_key = _template_excel_norm(cell.value)
            if value_key and any(key and key in value_key for key in norm_keywords):
                _add_comment(cell, note)


def _add_review_scope_comments(ws: Any, template_id: int) -> None:
    if int(template_id) == 1:
        _add_comments_to_matching_header_cells(
            ws,
            keywords=("Tổng số hộ dân cư", "Tổng nhân khẩu", "dân cư"),
            note=REVIEW_SCOPE_WARNING,
            max_row=11,
            max_col=16,
        )
        _add_comments_to_matching_header_cells(
            ws,
            keywords=("mức sống trung bình", "nông, lâm, ngư nghiệp"),
            note=MEDIUM_LIVING_PROXY_WARNING if ALLOW_DEMO_PROXY_NLNN_MSTB else "Mẫu 1: DB chưa có trường dữ liệu trực tiếp cho hộ nông, lâm, ngư nghiệp có mức sống trung bình; các cột này ghi 0.",
            max_row=11,
            max_col=16,
        )
    elif int(template_id) == 8:
        _add_comments_to_matching_header_cells(ws, keywords=("Tổng số hộ dân cư", "dân cư"), note=REVIEW_SCOPE_WARNING, max_row=10, max_col=13)
    elif int(template_id) == 12:
        _add_comments_to_matching_header_cells(ws, keywords=("Tổng số hộ chung", "Tổng số khẩu chung", "Tỷ lệ hộ nghèo"), note=REVIEW_SCOPE_WARNING, max_row=10, max_col=24)


def _detect_medium_living_condition(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Dùng cùng ưu tiên với exporter mẫu gốc cho cột mức sống trung bình."""
    candidates = [
        "nlnndn_muc_song_trung_binh",
        "muc_song_trung_binh",
        "phan_loai",
        "nhom_ngheo_tong_hop",
        "ky_ra_soat",
    ]
    for col in candidates:
        if not _column_exists(conn, "ho_ngheo", col):
            continue
        rows = conn.execute(f"SELECT DISTINCT {col} FROM ho_ngheo WHERE {col} IS NOT NULL").fetchall()
        for (value,) in rows:
            key = _template_excel_norm(value)
            if key in {"1", "true", "co"} and col in {"nlnndn_muc_song_trung_binh", "muc_song_trung_binh"}:
                return col, str(value)
            if "trungbinh" in key or "mucsong" in key:
                return col, str(value)
    return None


def _template1_medium_living_expr(conn: sqlite3.Connection) -> tuple[str, str, list[Any]]:
    """SQL expression cho cột I/O của mẫu 1, đồng bộ với template_excel_exporter.

    Không dùng proxy nghề nghiệp; nếu chưa có field trực tiếp thì ghi 0.
    """
    medium_cond = _detect_medium_living_condition(conn)
    if medium_cond:
        medium_col, medium_value = medium_cond
        household_expr = f"COUNT(DISTINCT CASE WHEN {medium_col} = ? THEN id_ho END)"
        population_expr = f"COALESCE(SUM(CASE WHEN {medium_col} = ? THEN so_nhan_khau ELSE 0 END), 0)"
        return household_expr, population_expr, [medium_value, medium_value]

    if ALLOW_DEMO_PROXY_NLNN_MSTB and _column_exists(conn, "ho_ngheo", "nghe_nghiep_chu_ho"):
        placeholders = ",".join(["?"] * len(NLNN_JOB_VALUES))
        cond = f"phan_loai = ? AND nghe_nghiep_chu_ho IN ({placeholders})"
        household_expr = f"COUNT(DISTINCT CASE WHEN {cond} THEN id_ho END)"
        population_expr = f"COALESCE(SUM(CASE WHEN {cond} THEN so_nhan_khau ELSE 0 END), 0)"
        return household_expr, population_expr, ["Hộ không nghèo", *NLNN_JOB_VALUES, "Hộ không nghèo", *NLNN_JOB_VALUES]

    return "0", "0", []


def _restore_mau1_ratio_formulas(ws: Any, row: int) -> None:
    # Giữ đúng bài toán mẫu gốc: F/H/J/L/N/P là công thức tỷ lệ, không ghi đè bằng value tĩnh.
    formulas = {
        6: f"=IFERROR(E{row}/C{row}*100,0)",
        8: f"=IFERROR(G{row}/C{row}*100,0)",
        10: f"=IFERROR(I{row}/C{row}*100,0)",
        12: f"=IFERROR(K{row}/D{row}*100,0)",
        14: f"=IFERROR(M{row}/D{row}*100,0)",
        16: f"=IFERROR(O{row}/D{row}*100,0)",
    }
    for col, formula in formulas.items():
        cell = ws.cell(row, col)
        cell.value = formula
        cell.number_format = "0.00"


def _normalize_mau7_header(ws: Any) -> None:
    # Một số file nguồn mẫu 7 còn header "hộ nghèo" dù tiêu đề file/template là hộ cận nghèo.
    # Không tự sửa header mẫu bắt buộc; giữ hàm no-op để tránh phá import cũ.
    return
    try:
        c8 = str(ws.cell(8, 3).value or "")
        if "hộ nghèo" in c8.lower() and "cận nghèo" not in c8.lower():
            ws.cell(8, 3).value = "Tổng số hộ cận nghèo"
        d8 = str(ws.cell(8, 4).value or "")
        if "hộ nghèo" in d8.lower() and "cận nghèo" not in d8.lower():
            ws.cell(8, 4).value = d8.replace("hộ nghèo", "hộ cận nghèo").replace("Hộ nghèo", "Hộ cận nghèo")
    except Exception:
        pass


def _apply_template12_readable_widths(ws: Any, *, start_row: int | None = None) -> None:
    try:
        from openpyxl.utils import get_column_letter
    except Exception:
        return
    if start_row is None:
        start_row = 11
    min_width_by_col = {
        3: 10.2, 4: 9.4, 5: 9.4, 6: 9.8,
        7: 10.8, 8: 10.0, 9: 10.0, 10: 10.2,
        11: 9.8, 12: 9.4, 13: 9.4, 14: 9.8,
        15: 9.0, 16: 9.2, 17: 9.8, 18: 10.2,
        19: 9.8, 20: 9.8, 21: 9.8,
        22: 11.0, 23: 11.0, 24: 11.0,
    }
    for col_idx, min_width in min_width_by_col.items():
        col_letter = get_column_letter(col_idx)
        current = ws.column_dimensions[col_letter].width or 0
        ws.column_dimensions[col_letter].width = max(float(current or 0), min_width)
    for row in range(start_row, ws.max_row + 1):
        if not ws.cell(row, 2).value:
            continue
        for col in range(3, 25):
            cell = ws.cell(row, col)
            try:
                cell.alignment = cell.alignment.copy(
                    horizontal="center", vertical="center", wrap_text=False, shrink_to_fit=True
                )
            except Exception:
                pass


def _mau1_default_column_plan(reason: str = "fallback") -> dict[str, Any]:
    column_mappings = []
    for item in MAU1_DEFAULT_COLUMN_PLAN:
        mapped = dict(item)
        mapped["source"] = reason
        column_mappings.append(mapped)
    return {
        "template_id": 1,
        "plan_type": "mau1_column_fact_mapping",
        "source": reason,
        "validation_status": "fallback_all",
        "llm_match_count": 0,
        "fallback_count": len(MAU1_DEFAULT_COLUMN_PLAN),
        "column_mappings": column_mappings,
        "notes": "Fallback deterministic: Python dùng mapping cột cố định cho mẫu 1.",
    }


def _column_letter(col: int) -> str:
    try:
        from openpyxl.utils import get_column_letter  # type: ignore
        return get_column_letter(int(col))
    except Exception:
        letters = ""
        n = int(col)
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        return letters


def _extract_mau1_header_context_for_llm(samples_dir: Path | None = None) -> dict[str, Any]:
    """Trích context cột C:P của mẫu 1 để LLM ánh xạ cột -> fact_key.

    Đây là context nhỏ, rõ ràng hơn việc gửi cả sheet cho Qwen 3B.
    """
    template_id = 1
    path = _find_template_sample_path(template_id, samples_dir)
    if path is None:
        return {"ok": False, "template_id": 1, "error": "Không tìm thấy template mẫu 1."}
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        return {"ok": False, "template_id": 1, "template_path": str(path), "error": f"Không import được openpyxl: {exc}"}
    try:
        wb = load_workbook(path, read_only=False, data_only=False)
        ws = wb.active
        title_cells = []
        for r in range(1, 8):
            row_text = []
            for c in range(1, 17):
                v = ws.cell(r, c).value
                if v is not None:
                    row_text.append(_short_text(v, 220))
            if row_text:
                title_cells.append({"row": r, "text": " | ".join(row_text)})

        column_context = []
        for c in range(3, 17):  # C:P
            labels = []
            for r in range(8, 12):
                v = ws.cell(r, c).value
                if v is not None and str(v).strip():
                    labels.append({"row": r, "value": _short_text(v, 220)})
            # Lấy thêm header merged phía trên bằng cách đọc các ô hàng 8-10 bên trái/phải.
            nearby = []
            for r in range(8, 11):
                for cc in range(max(1, c - 2), min(16, c + 2) + 1):
                    v = ws.cell(r, cc).value
                    if v is not None and str(v).strip():
                        nearby.append({"cell": f"{_column_letter(cc)}{r}", "value": _short_text(v, 160)})
            column_context.append({
                "column": _column_letter(c),
                "column_index": c,
                "direct_labels": labels,
                "nearby_header_cells": nearby[:12],
            })

        sample_area_rows = []
        for r in range(12, min(ws.max_row or 12, 42) + 1):
            label = ws.cell(r, 2).value
            if label is not None and str(label).strip():
                sample_area_rows.append({
                    "row": r,
                    "tt": _short_text(ws.cell(r, 1).value, 40),
                    "area_label": _short_text(label, 120),
                })

        return {
            "ok": True,
            "template_id": 1,
            "template_path": _relative_or_str(path),
            "sheet_name": ws.title,
            "title_rows": title_cells,
            "column_context": column_context,
            "sample_area_rows": sample_area_rows,
            "allowed_fact_keys": sorted(MAU1_ALLOWED_COLUMN_FACTS),
        }
    except Exception as exc:
        return {"ok": False, "template_id": 1, "template_path": str(path), "error": f"Không đọc được template mẫu 1: {exc}"}


def _call_ollama_mau1_column_mapper(context: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    """LLM ánh xạ cột C:P sang fact_key được whitelist.

    Trả thêm prompt_payload để ghi debug/log.
    """
    prompt_payload = {
        "template_id": 1,
        "title_rows": context.get("title_rows", []),
        "column_context": context.get("column_context", []),
        "allowed_fact_keys": sorted(MAU1_ALLOWED_COLUMN_FACTS),
        "required_columns": [item["column"] for item in MAU1_DEFAULT_COLUMN_PLAN],
        # Cho LLM biết nghĩa của từng fact_key để giảm nhầm lẫn. Python vẫn validate lại.
        "fact_key_meanings": {item["fact_key"]: item["reason"] for item in MAU1_DEFAULT_COLUMN_PLAN},
        "unit_values_allowed": ["households", "persons", "percent"],
        "important_rule": "Không được trả literal 'households|persons|percent'; unit phải là một trong households/persons/percent.",
    }
    system = (
        "Bạn là AI ánh xạ cột Excel báo cáo hành chính sang fact_key. "
        "Bạn KHÔNG được sinh số liệu, KHÔNG được viết SQL, KHÔNG được sửa workbook. "
        "Bạn chỉ chọn fact_key từ allowed_fact_keys cho từng cột C:P của mẫu 1. "
        "Mỗi cột phải có đúng một mapping. Chỉ trả JSON hợp lệ, không markdown."
    )
    user = (
        "Hãy ánh xạ các cột C:P của mẫu 1 sang fact_key dùng để Python tính số liệu và điền Excel.\n"
        "Schema bắt buộc:\n"
        "{\n"
        '  "template_id": 1,\n'
        '  "plan_type": "mau1_column_fact_mapping",\n'
        '  "column_mappings": [\n'
        '    {"column":"C", "fact_key":"reviewed_households", "unit":"households", "reason":"..."}\n'
        "  ],\n"
        '  "notes": "..."\n'
        "}\n\n"
        "CONTEXT_JSON:\n" + json.dumps(prompt_payload, ensure_ascii=False, default=str)
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.7},
            },
            timeout=int(LLM_TIMEOUT or 20),
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = str((payload.get("message") or {}).get("content") or payload.get("response") or "")
        parsed = _extract_json_object(raw)
        if parsed is None:
            return None, raw, "LLM không trả JSON hợp lệ cho column mapping.", prompt_payload
        return parsed, raw, None, prompt_payload
    except Exception as exc:
        return None, "", f"Không gọi được Ollama/Qwen cho column mapping: {exc}", prompt_payload


def _call_ollama_mau1_column_mapper_repair(
    context: dict[str, Any],
    *,
    first_raw_text: str,
    first_validation_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    """Retry có kiểm soát để LLM tự sửa mapping mẫu 1.

    Prompt repair được làm rất nhỏ và rất cứng. Thay vì gửi lại toàn bộ
    schema dài khiến Qwen 3B hay trả "mô tả schema", Python chỉ đưa danh sách
    REQUIRED_MAPPINGS và yêu cầu LLM chép thành column_mappings đúng JSON.
    """
    required_mappings = []
    for item in MAU1_DEFAULT_COLUMN_PLAN:
        required_mappings.append({
            "column": item["column"],
            "fact_key": item["fact_key"],
            "unit": item["unit"],
            "reason": item["reason"],
        })

    # Vẫn lưu context lỗi vào debug, nhưng không nhồi quá nhiều vào prompt chính.
    compact_feedback = []
    for warning in first_validation_warnings:
        text = str(warning)
        if "LLM chọn" in text or "thiếu mapping" in text:
            compact_feedback.append(text)

    prompt_payload = {
        "template_id": 1,
        "task": "repair_mau1_column_fact_mapping_strict",
        "failed_feedback": compact_feedback[:12],
        "required_mappings": required_mappings,
        "allowed_fact_keys": sorted(MAU1_ALLOWED_COLUMN_FACTS),
        "required_output_schema": {
            "template_id": 1,
            "plan_type": "mau1_column_fact_mapping",
            "column_mappings": [
                {"column": "C", "fact_key": "reviewed_households", "unit": "households", "reason": "..."}
            ],
            "notes": "repaired_by_llm_strict_copy"
        },
        "hard_rules": [
            "Chỉ trả một JSON object hợp lệ, không markdown, không giải thích.",
            "Không trả allowedFactKeys, requiredColumns, canonicalColumnSchema hoặc hardRules trong output.",
            "Output bắt buộc có key column_mappings.",
            "column_mappings phải có đúng 14 object, theo đúng thứ tự C,D,E,F,G,H,I,J,K,L,M,N,O,P.",
            "Mỗi object trong column_mappings phải copy đúng column, fact_key, unit từ required_mappings.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là bộ sửa JSON. Nhiệm vụ duy nhất: tạo JSON output đúng schema từ required_mappings. "
        "Không giải thích, không markdown, không thêm khóa ngoài schema. "
        "Nếu thấy required_mappings thì phải copy chính xác vào column_mappings."
    )
    user = (
        "Tạo lại mapping cột C:P cho mẫu 1.\n"
        "Bạn PHẢI copy chính xác danh sách required_mappings dưới đây vào key column_mappings.\n"
        "Chỉ trả JSON object hợp lệ theo dạng:\n"
        '{"template_id":1,"plan_type":"mau1_column_fact_mapping","column_mappings":[...],"notes":"repaired_by_llm_strict_copy"}'
        "\n\nREPAIR_PAYLOAD_JSON:\n" + json.dumps(prompt_payload, ensure_ascii=False, default=str)
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.25,
                    "repeat_penalty": 1.05,
                },
            },
            timeout=int(LLM_TIMEOUT or 20),
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = str((payload.get("message") or {}).get("content") or payload.get("response") or "")
        parsed = _extract_json_object(raw)
        if parsed is None:
            return None, raw, "LLM repair không trả JSON hợp lệ cho column mapping.", prompt_payload
        if "column_mappings" not in parsed:
            return None, raw, "LLM repair trả JSON nhưng thiếu key column_mappings.", prompt_payload
        return parsed, raw, None, prompt_payload
    except Exception as exc:
        return None, "", f"Không gọi được Ollama/Qwen cho repair column mapping: {exc}", prompt_payload


def _mau1_required_mapping_for_columns(columns: list[str]) -> list[dict[str, Any]]:
    """Lấy schema bắt buộc của các cột mẫu 1 theo đúng thứ tự C:P."""
    wanted = {str(c).strip().upper() for c in columns}
    out: list[dict[str, Any]] = []
    for item in MAU1_DEFAULT_COLUMN_PLAN:
        col = str(item.get("column") or "").strip().upper()
        if col in wanted:
            out.append({
                "column": col,
                "fact_key": item["fact_key"],
                "unit": item["unit"],
                "reason": item["reason"],
            })
    return out


def _mau1_fallback_columns_from_validated_plan(plan: dict[str, Any]) -> list[str]:
    """Các cột hiện chưa được LLM map đúng, tức đang bị Python fallback."""
    cols: list[str] = []
    default_by_col = {item["column"]: item for item in MAU1_DEFAULT_COLUMN_PLAN}
    for item in plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if col not in default_by_col:
            continue
        expected = default_by_col[col]
        if (
            item.get("source") != "llm"
            or str(item.get("fact_key")) != str(expected.get("fact_key"))
            or str(item.get("unit")) != str(expected.get("unit"))
        ):
            cols.append(col)
    return cols


def _mau1_combine_llm_plan_with_patch(base_plan: dict[str, Any], patch_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ghép các cột LLM đã đúng từ base_plan với patch LLM cho cột còn sai.

    Không lấy các dòng fallback từ base_plan để tránh đếm nhầm fallback là LLM.
    Nếu patch sửa đúng các cột còn lại, validate sẽ cho ra 14/14 LLM match.
    """
    if not isinstance(base_plan, dict) or not isinstance(patch_plan, dict):
        return None
    raw_by_col: dict[str, dict[str, Any]] = {}
    for item in base_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if item.get("source") == "llm" and col:
            raw_by_col[col] = {
                "column": col,
                "fact_key": item.get("fact_key"),
                "unit": item.get("unit"),
                "reason": item.get("reason") or "LLM đề xuất",
            }
    for item in patch_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if col:
            raw_by_col[col] = {
                "column": col,
                "fact_key": item.get("fact_key"),
                "unit": item.get("unit"),
                "reason": item.get("reason") or "LLM targeted repair",
            }
    return {
        "template_id": 1,
        "plan_type": "mau1_column_fact_mapping",
        "column_mappings": [raw_by_col.get(item["column"], {}) for item in MAU1_DEFAULT_COLUMN_PLAN],
        "notes": "combined_llm_initial_plus_targeted_repair",
    }


def _call_ollama_mau1_column_mapper_targeted_repair(
    *,
    bad_columns: list[str],
    previous_raw_text: str,
    previous_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    """Sửa siêu hẹp cho những cột còn sai sau repair.

    Với Qwen 3B, yêu cầu sửa cả 14 cột đôi khi vẫn nhầm 1 cột. Hàm này chỉ đưa
    đúng các cột còn sai, ví dụ chỉ cột J, và bắt model trả lại patch rất nhỏ.
    """
    target_mappings = _mau1_required_mapping_for_columns(bad_columns)
    exact_output = {
        "template_id": 1,
        "plan_type": "mau1_column_fact_mapping_patch",
        "column_mappings": target_mappings,
        "notes": "targeted_column_patch",
    }
    prompt_payload = {
        "template_id": 1,
        "task": "targeted_repair_mau1_column_mapping",
        "bad_columns": [m["column"] for m in target_mappings],
        "target_mappings": target_mappings,
        "previous_warnings": previous_warnings[-8:],
        "exact_output_to_return": exact_output,
        "hard_rules": [
            "Chỉ trả JSON object hợp lệ, không markdown, không giải thích.",
            "Chỉ trả các cột trong bad_columns, không trả lại toàn bộ C:P.",
            "Mỗi object phải copy đúng column, fact_key, unit từ target_mappings.",
            "Không đổi household_ratio thành people, không đổi percent thành persons.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là bộ sửa JSON cực hẹp. Nhiệm vụ duy nhất: trả lại JSON patch y hệt exact_output_to_return. "
        "Không suy luận thêm, không giải thích, không markdown."
    )
    user = (
        "Một số cột còn sai. Hãy trả lại JSON patch cho đúng những cột này.\n"
        "Bạn PHẢI trả lại chính xác object trong exact_output_to_return.\n"
        "Đặc biệt chú ý: nếu cột là tỷ lệ hộ thì fact_key phải có chữ household_ratio, unit percent.\n"
        "TARGETED_REPAIR_PAYLOAD_JSON:\n"
        + json.dumps(prompt_payload, ensure_ascii=False, default=str)
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1,
                    "repeat_penalty": 1.02,
                },
            },
            timeout=int(LLM_TIMEOUT or 20),
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = str((payload.get("message") or {}).get("content") or payload.get("response") or "")
        parsed = _extract_json_object(raw)
        if parsed is None:
            return None, raw, "LLM targeted repair không trả JSON hợp lệ.", prompt_payload
        if "column_mappings" not in parsed:
            return None, raw, "LLM targeted repair trả JSON nhưng thiếu key column_mappings.", prompt_payload
        return parsed, raw, None, prompt_payload
    except Exception as exc:
        return None, "", f"Không gọi được Ollama/Qwen cho targeted repair: {exc}", prompt_payload

def _validate_mau1_column_mapping_plan(plan: dict[str, Any] | None, *, source: str, raw_error: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Validate cứng plan của LLM; thiếu/sai thì fallback từng cột.

    Mục tiêu an toàn: LLM có thể đề xuất sai, nhưng Python luôn ép về mapping đủ C:P.
    """
    warnings: list[str] = []
    default_by_col = {item["column"]: dict(item) for item in MAU1_DEFAULT_COLUMN_PLAN}
    fixed_by_col: dict[str, dict[str, Any]] = {}

    if not isinstance(plan, dict):
        warnings.append(raw_error or "Không có plan hợp lệ; dùng fallback deterministic cho toàn bộ cột.")
        fixed = _mau1_default_column_plan(reason=f"{source}_fallback_no_plan")
        fixed["validation_status"] = "fallback_all"
        return fixed, warnings

    if int(plan.get("template_id") or 0) != 1:
        warnings.append("LLM trả template_id không phải 1; ép về mẫu 1.")

    raw_mappings = plan.get("column_mappings") or []
    if not isinstance(raw_mappings, list):
        warnings.append("column_mappings không phải list; dùng fallback toàn bộ.")
        raw_mappings = []

    seen = set()
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        fact = str(item.get("fact_key") or "").strip()
        if col not in default_by_col:
            if col:
                warnings.append(f"Bỏ mapping cột ngoài C:P: {col}")
            continue
        expected_fact = str(default_by_col[col]["fact_key"])
        if fact not in MAU1_ALLOWED_COLUMN_FACTS:
            warnings.append(f"Cột {col}: fact_key ngoài whitelist ({fact}); dùng fallback {expected_fact}.")
            continue
        # Guard quan trọng: mẫu 1 có schema cột cố định. LLM chỉ được chấp nhận
        # khi chọn đúng fact_key mà schema/công thức mẫu yêu cầu. Nếu LLM chọn
        # fact_key khác nhưng vẫn nằm trong whitelist, vẫn phải fallback để tránh
        # điền nhầm số hợp lệ vào sai cột.
        if fact != expected_fact:
            warnings.append(
                f"Cột {col}: LLM chọn {fact} nhưng schema mẫu 1 yêu cầu {expected_fact}; "
                f"dùng fallback {expected_fact}."
            )
            continue
        if col in seen:
            warnings.append(f"Cột {col}: LLM trả trùng mapping; giữ mapping đầu tiên hợp lệ.")
            continue
        seen.add(col)
        unit = str(item.get("unit") or default_by_col[col].get("unit") or "")
        if unit not in {"households", "persons", "percent"}:
            warnings.append(
                f"Cột {col}: unit LLM trả không hợp lệ ({unit}); "
                f"dùng unit fallback {default_by_col[col].get('unit')}."
            )
            unit = str(default_by_col[col].get("unit") or "")
        fixed_by_col[col] = {
            "column": col,
            "fact_key": fact,
            "unit": unit,
            "reason": _short_text(item.get("reason") or "LLM đề xuất", 220),
            "source": "llm",
        }

    for col, fallback in default_by_col.items():
        if col not in fixed_by_col:
            fb = dict(fallback)
            fb["source"] = "fallback_for_missing_or_invalid_column"
            fixed_by_col[col] = fb
            warnings.append(f"Cột {col}: thiếu mapping hợp lệ từ LLM; dùng fallback {fb['fact_key']}.")

    column_mappings = [fixed_by_col[item["column"]] for item in MAU1_DEFAULT_COLUMN_PLAN]
    llm_match_count = sum(1 for m in column_mappings if m.get("source") == "llm")
    fallback_count = len(column_mappings) - llm_match_count
    status = "llm_validated_with_fallback" if fallback_count else "llm_validated"
    if source == "llm_repair" and not fallback_count:
        status = "llm_repair_validated"
    elif source == "llm_repair" and fallback_count:
        status = "llm_repair_validated_with_fallback"
    elif source == "llm_targeted_repair" and not fallback_count:
        status = "llm_targeted_repair_validated"
    elif source == "llm_targeted_repair" and fallback_count:
        status = "llm_targeted_repair_validated_with_fallback"
    fixed_plan = {
        "template_id": 1,
        "plan_type": "mau1_column_fact_mapping",
        "source": source,
        "validation_status": status,
        "llm_match_count": llm_match_count,
        "fallback_count": fallback_count,
        "column_mappings": column_mappings,
        "notes": _short_text(plan.get("notes") or "LLM mapping đã qua whitelist + guard schema; Python tính số và ghi Excel.", 300),
    }
    return fixed_plan, warnings


def _mau1_ratio(num: float, den: float) -> float:
    try:
        den = float(den or 0)
        if den == 0:
            return 0.0
        return round(float(num or 0) / den * 100, 2)
    except Exception:
        return 0.0


def _mau1_compute_metrics(year: int | None, huyen: str | None = None, xa_phuong: str | None = None) -> dict[str, Any]:
    """Tính fact cho một phạm vi địa bàn. Không dùng LLM."""
    clauses = []
    params: list[Any] = []
    if year:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if xa_phuong:
        clauses.append("xa_phuong = ?")
        params.append(xa_phuong)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with sqlite3.connect(DB_PATH) as conn:
        medium_household_expr, medium_population_expr, medium_params = _template1_medium_living_expr(conn)
        row = conn.execute(
            "SELECT "
            "COUNT(DISTINCT id_ho) AS reviewed_households, "
            "COALESCE(SUM(so_nhan_khau), 0) AS reviewed_people, "
            "COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' THEN id_ho END) AS poor_households, "
            "COALESCE(SUM(CASE WHEN phan_loai = 'Hộ nghèo' THEN so_nhan_khau ELSE 0 END), 0) AS poor_people, "
            "COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' THEN id_ho END) AS near_poor_households, "
            "COALESCE(SUM(CASE WHEN phan_loai = 'Hộ cận nghèo' THEN so_nhan_khau ELSE 0 END), 0) AS near_poor_people, "
            f"{medium_household_expr} AS living_standard_average_households, "
            f"{medium_population_expr} AS living_standard_average_people "
            f"FROM ho_ngheo{where}",
            [*medium_params, *params],
        ).fetchone()
    reviewed_households = int(row[0] or 0)
    reviewed_people = int(row[1] or 0)
    poor_households = int(row[2] or 0)
    poor_people = int(row[3] or 0)
    near_poor_households = int(row[4] or 0)
    near_poor_people = int(row[5] or 0)

    # Logic mẫu 1 đồng bộ với exporter mẫu gốc: chỉ dùng field/nhãn trực tiếp
    # về mức sống trung bình; nếu chưa có thì chỉ tiêu này bằng 0.
    living_hh = int(row[6] or 0)
    living_people = int(row[7] or 0)
    return {
        "reviewed_households": reviewed_households,
        "reviewed_people": reviewed_people,
        "poor_households": poor_households,
        "poor_household_ratio": _mau1_ratio(poor_households, reviewed_households),
        "near_poor_households": near_poor_households,
        "near_poor_household_ratio": _mau1_ratio(near_poor_households, reviewed_households),
        "living_standard_average_households": living_hh,
        "living_standard_average_household_ratio": _mau1_ratio(living_hh, reviewed_households),
        "poor_people": poor_people,
        "poor_people_ratio": _mau1_ratio(poor_people, reviewed_people),
        "near_poor_people": near_poor_people,
        "near_poor_people_ratio": _mau1_ratio(near_poor_people, reviewed_people),
        "living_standard_average_people": living_people,
        "living_standard_average_people_ratio": _mau1_ratio(living_people, reviewed_people),
    }


def _area_key(text: Any) -> str:
    """Key so khớp địa bàn mềm: bỏ tiền tố, dấu, ký tự lạ và khoảng trắng.

    Dùng để match các khác biệt nhỏ giữa template và DB như:
    - Ea TLing vs Ea T'ling
    - Đắk NDrót vs Đắk N'Drót
    - Đăk RMoan vs Đắk R'Moan
    """
    return _vn_key(_normalize_area_label(text)).replace(" ", "")


def _mau1_area_lookup(year: int | None) -> dict[str, Any]:
    """Danh sách huyện/xã trong DB để match row template.

    Trả cả raw set và normalized map để không bỏ sót xã/phường vì khác dấu nháy,
    khoảng trắng hoặc cách viết trong template.
    """
    clauses = []
    params: list[Any] = []
    if year:
        clauses.append("nam = ?")
        params.append(int(year))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with sqlite3.connect(DB_PATH) as conn:
        districts = [r[0] for r in conn.execute(
            f"SELECT DISTINCT huyen FROM ho_ngheo{where} AND huyen IS NOT NULL ORDER BY huyen" if where else
            "SELECT DISTINCT huyen FROM ho_ngheo WHERE huyen IS NOT NULL ORDER BY huyen",
            params,
        ).fetchall()]
        rows = conn.execute(
            f"SELECT DISTINCT huyen, xa_phuong FROM ho_ngheo{where} AND xa_phuong IS NOT NULL ORDER BY huyen, xa_phuong" if where else
            "SELECT DISTINCT huyen, xa_phuong FROM ho_ngheo WHERE xa_phuong IS NOT NULL ORDER BY huyen, xa_phuong",
            params,
        ).fetchall()
    district_set = set(map(str, districts))
    district_by_key = {_area_key(h): str(h) for h in districts}
    xa_by_huyen: dict[str, set[str]] = {}
    xa_by_huyen_key: dict[str, dict[str, str]] = {}
    for h, x in rows:
        hh = str(h)
        xx = str(x)
        xa_by_huyen.setdefault(hh, set()).add(xx)
        xa_by_huyen_key.setdefault(hh, {})[_area_key(xx)] = xx
    return {
        "districts": district_set,
        "district_by_key": district_by_key,
        "xa_by_huyen": xa_by_huyen,
        "xa_by_huyen_key": xa_by_huyen_key,
    }


def _normalize_area_label(text: Any) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    raw = re.sub(r"^(huyện|thành phố|tp\.?|xã|phường|thị trấn)\s+", "", raw, flags=re.I).strip()
    return raw


def _write_llm_excel_debug_log(debug: dict[str, Any]) -> str | None:
    if write_jsonl_log is None:
        return None
    return write_jsonl_log("llm_excel_mau1", debug)


def _export_mau1_xlsx_real_llm_assisted(
    *,
    year: int | None,
    huyen: str | None,
    use_llm: bool,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    """Xuất Excel mẫu 1 bằng plan cột do LLM đề xuất/validate.

    Đây là experimental path riêng. Không dùng export_template_xlsx(...).
    Chỉ chạy khi người dùng bật chế độ LLM-assisted mapping experimental/debug cho mẫu 1.
    """
    debug: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": "mau1_real_llm_excel_export",
        "template_id": 1,
        "year": year,
        "huyen": huyen,
        "use_llm": bool(use_llm),
        "llm_attempted": False,
        "llm_error": None,
        "raw_llm_text": "",
        "prompt_payload": None,
        "validated_plan": None,
        "validation_warnings": [],
        "filled_rows": [],
        "filled_cell_count": 0,
        "limitations": [],
        "data_mapping_notes": [
            "Mẫu 1: nhóm hộ nông/lâm/ngư nghiệp có mức sống trung bình chỉ dùng field/nhãn trực tiếp; nếu DB chưa có thì cột này bằng 0, trừ khi bật allow_demo_proxy_nlnn_mstb experimental."
        ],
    }
    warnings: list[str] = []
    warnings.append(REVIEW_SCOPE_WARNING)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if _detect_medium_living_condition(conn) is None:
                warnings.append(MEDIUM_LIVING_PROXY_WARNING if ALLOW_DEMO_PROXY_NLNN_MSTB else "Mẫu 1: DB chưa có trường dữ liệu trực tiếp cho hộ nông, lâm, ngư nghiệp có mức sống trung bình; exporter LLM ghi 0 cho các cột này.")
                debug["limitations"] = list(warnings)
    except Exception:
        pass

    # 1) LLM/Python lập mapping cột.
    samples_root = samples_dir or DATA_SAMPLES_DIR
    header_context = _extract_mau1_header_context_for_llm(samples_root)
    debug["header_context"] = header_context
    if not header_context.get("ok"):
        plan = _mau1_default_column_plan(reason="context_error_fallback")
        warnings.append(header_context.get("error") or "Không trích được context mẫu 1; dùng fallback.")
    elif use_llm:
        debug["llm_attempted"] = True
        parsed, raw, error, prompt_payload = _call_ollama_mau1_column_mapper(header_context)
        debug["prompt_payload"] = prompt_payload
        debug["raw_llm_text"] = raw
        debug["llm_error"] = error
        plan, plan_warnings = _validate_mau1_column_mapping_plan(parsed, source="llm", raw_error=error)
        warnings.extend(plan_warnings)

        # Nếu lần 1 chưa đúng hết, cho LLM tự sửa một lần bằng feedback của validator.
        # Excel vẫn an toàn vì dù repair lỗi, Python vẫn dùng plan đã fallback từng cột.
        debug["llm_first_raw_text"] = raw
        debug["llm_first_validated_plan"] = plan
        debug["llm_first_validation_warnings"] = list(plan_warnings)
        debug["llm_repair_attempted"] = False
        debug["llm_repair_error"] = None
        debug["llm_repair_raw_text"] = ""
        debug["llm_repair_prompt_payload"] = None
        debug["llm_repair_validated_plan"] = None
        debug["llm_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            debug["llm_repair_attempted"] = True
            repaired, repair_raw, repair_error, repair_payload = _call_ollama_mau1_column_mapper_repair(
                header_context,
                first_raw_text=raw,
                first_validation_warnings=list(plan_warnings),
            )
            debug["llm_repair_error"] = repair_error
            debug["llm_repair_raw_text"] = repair_raw
            debug["llm_repair_prompt_payload"] = repair_payload
            repaired_plan, repaired_warnings = _validate_mau1_column_mapping_plan(
                repaired,
                source="llm_repair",
                raw_error=repair_error,
            )
            debug["llm_repair_validated_plan"] = repaired_plan
            debug["llm_repair_validation_warnings"] = list(repaired_warnings)
            if int(repaired_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                # Dùng plan repair tốt hơn. Nếu repair đúng 14/14, fallback_count = 0.
                plan = repaired_plan
                warnings.append(
                    f"LLM repair cải thiện mapping: fallback_count "
                    f"{debug['llm_first_validated_plan'].get('fallback_count')} -> {plan.get('fallback_count')}."
                )
                warnings.extend(repaired_warnings)
                debug["raw_llm_text"] = repair_raw
                debug["prompt_payload"] = repair_payload
                debug["llm_error"] = repair_error
            else:
                warnings.append(
                    "LLM repair không cải thiện mapping; giữ plan lần 1 đã được Python fallback an toàn."
                )
                warnings.extend(repaired_warnings)

        # Nếu strict repair còn sót 1-2 cột sai, gọi thêm targeted repair rất hẹp.
        debug["llm_targeted_repair_attempted"] = False
        debug["llm_targeted_repair_columns"] = []
        debug["llm_targeted_repair_error"] = None
        debug["llm_targeted_repair_raw_text"] = ""
        debug["llm_targeted_repair_prompt_payload"] = None
        debug["llm_targeted_repair_validated_plan"] = None
        debug["llm_targeted_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            bad_cols = _mau1_fallback_columns_from_validated_plan(plan)
            if bad_cols:
                debug["llm_targeted_repair_attempted"] = True
                debug["llm_targeted_repair_columns"] = list(bad_cols)
                targeted, targeted_raw, targeted_error, targeted_payload = _call_ollama_mau1_column_mapper_targeted_repair(
                    bad_columns=bad_cols,
                    previous_raw_text=str(debug.get("raw_llm_text") or raw or ""),
                    previous_warnings=list(warnings),
                )
                debug["llm_targeted_repair_error"] = targeted_error
                debug["llm_targeted_repair_raw_text"] = targeted_raw
                debug["llm_targeted_repair_prompt_payload"] = targeted_payload
                combined = _mau1_combine_llm_plan_with_patch(plan, targeted)
                targeted_plan, targeted_warnings = _validate_mau1_column_mapping_plan(
                    combined,
                    source="llm_targeted_repair",
                    raw_error=targeted_error,
                )
                debug["llm_targeted_repair_validated_plan"] = targeted_plan
                debug["llm_targeted_repair_validation_warnings"] = list(targeted_warnings)
                if int(targeted_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                    old_fallback = int(plan.get("fallback_count") or 0)
                    plan = targeted_plan
                    warnings.append(
                        f"LLM targeted repair cải thiện mapping: fallback_count {old_fallback} -> {plan.get('fallback_count')}."
                    )
                    warnings.extend(targeted_warnings)
                    debug["raw_llm_text"] = targeted_raw
                    debug["prompt_payload"] = targeted_payload
                    debug["llm_error"] = targeted_error
                else:
                    warnings.append("LLM targeted repair không cải thiện mapping; giữ plan tốt nhất hiện có.")
                    warnings.extend(targeted_warnings)

        debug["llm_final_full_match"] = (
            str(plan.get("validation_status")) in {"llm_validated", "llm_repair_validated", "llm_targeted_repair_validated"}
            and int(plan.get("fallback_count") or 0) == 0
        )
        debug["final_mapping_correct_by_schema"] = all(
            str(m.get("fact_key")) == str(expected.get("fact_key"))
            and str(m.get("unit")) == str(expected.get("unit"))
            for m, expected in zip(plan.get("column_mappings", []), MAU1_DEFAULT_COLUMN_PLAN)
        )
        debug["final_mapping_source"] = plan.get("source")
        debug["final_mapping_validation_status"] = plan.get("validation_status")
    else:
        plan = _mau1_default_column_plan(reason="llm_disabled_export_path")
        warnings.append("Đang dùng exporter experimental mẫu 1 nhưng tắt LLM; mapping cột lấy từ fallback Python.")
    debug["validated_plan"] = plan
    debug["validation_warnings"] = list(warnings)

    # 2) Mở template mẫu 1 và điền số theo validated_plan.
    try:
        from openpyxl import load_workbook  # type: ignore
        from openpyxl.cell.cell import MergedCell  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Chưa import được openpyxl để xuất Excel mẫu 1 experimental: {exc}") from exc

    template_path = _find_template_sample_path(1, samples_root)
    if template_path is None:
        raise FileNotFoundError("Không tìm thấy file template Excel mẫu 1.")
    wb = load_workbook(template_path)
    ws = wb.active

    col_to_fact = {str(item["column"]): str(item["fact_key"]) for item in plan.get("column_mappings", [])}
    area = _mau1_area_lookup(year)
    current_huyen: str | None = None
    filled_cell_count = 0
    filled_rows: list[dict[str, Any]] = []

    # Nếu chọn một huyện, chỉ điền huyện đó và các xã thuộc huyện đó; hàng khác clear số để tránh hiểu nhầm phạm vi.
    selected_huyen = str(huyen).strip() if huyen else None

    for r in range(12, min(int(ws.max_row or 12), 350) + 1):
        label = ws.cell(r, 2).value
        if label is None or not str(label).strip():
            continue
        label_text = re.sub(r"\s+", " ", str(label)).strip()
        norm = _normalize_area_label(label_text)
        row_type = None
        row_huyen = None
        row_xa = None

        tt_text = re.sub(r"\s+", "", str(ws.cell(r, 1).value or ""))
        label_lower = label_text.lower()
        label_key = _area_key(label_text)
        is_commune_row = bool("." in tt_text or re.match(r"^(xã|phường|thị trấn)\s+", label_lower, flags=re.I))
        is_district_row = bool(re.fullmatch(r"\d+", tt_text) or re.match(r"^(huyện|thành phố|tp\.?)\s+", label_lower, flags=re.I))

        # Ưu tiên phân loại theo TT/prefix để tránh lỗi "Thị trấn Đắk Mil" bị hiểu nhầm
        # thành dòng huyện Đắk Mil.
        if is_commune_row and current_huyen:
            xa_map = area.get("xa_by_huyen_key", {}).get(current_huyen, {})
            matched_xa = xa_map.get(label_key)
            if matched_xa:
                row_type = "commune"
                row_huyen = current_huyen
                row_xa = matched_xa
        if row_type is None and is_district_row:
            matched_huyen = area.get("district_by_key", {}).get(label_key) or (norm if norm in area.get("districts", set()) else None)
            if matched_huyen:
                row_type = "district"
                row_huyen = matched_huyen
                current_huyen = matched_huyen
        if row_type is None and current_huyen:
            # Fallback mềm cho các dòng xã/phường không có prefix rõ.
            xa_map = area.get("xa_by_huyen_key", {}).get(current_huyen, {})
            matched_xa = xa_map.get(label_key)
            if matched_xa:
                row_type = "commune"
                row_huyen = current_huyen
                row_xa = matched_xa
        if row_type is None:
            matched_huyen = area.get("district_by_key", {}).get(label_key)
            if matched_huyen:
                row_type = "district"
                row_huyen = matched_huyen
                current_huyen = matched_huyen
        if row_type is None:
            # Có thể là dòng tổng/ký hiệu không match DB; bỏ qua.
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": str(ws.cell(r, 1).value or "")})
            continue

        in_scope = True
        if selected_huyen and row_huyen != selected_huyen:
            in_scope = False

        metrics = _mau1_compute_metrics(year, row_huyen, row_xa) if in_scope else {k: 0 for k in MAU1_ALLOWED_COLUMN_FACTS}
        sample_values: dict[str, Any] = {}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell):
                continue
            value = metrics.get(fact_key, 0)
            cell.value = value
            if str(fact_key).endswith("ratio"):
                cell.number_format = "0.00"
            else:
                cell.number_format = "#,##0"
            filled_cell_count += 1
            sample_values[col] = value

        # Sau khi LLM mapping ghi ô, khôi phục đúng công thức tỷ lệ của mẫu gốc.
        # Nhánh LLM chỉ được hỗ trợ mapping/fact, không thay đổi bài toán Excel mẫu.
        _restore_mau1_ratio_formulas(ws, r)

        filled_rows.append({
            "row": r,
            "label": label_text,
            "row_type": row_type,
            "huyen": row_huyen,
            "xa_phuong": row_xa,
            "in_scope": in_scope,
            "values_sample_C_to_H": {k: sample_values.get(k) for k in ["C", "D", "E", "F", "G", "H"]},
        })

    # Ghi dấu vết nhỏ ở properties để khi mở file biết đây là path experimental.
    try:
        _set_workbook_demo_properties(wb)
    except Exception:
        pass
    _add_review_scope_comments(ws, 1)

    bio = BytesIO()
    _set_workbook_demo_properties(wb)
    wb.save(bio)
    content = bio.getvalue()

    debug["filled_cell_count"] = filled_cell_count
    debug["filled_rows"] = filled_rows[:120]
    debug["filled_rows_total"] = len(filled_rows)
    debug["template_path"] = _relative_or_str(template_path)
    debug["output_bytes"] = len(content)
    log_path = _write_llm_excel_debug_log(debug)
    debug["log_path"] = log_path
    return {
        "content": content,
        "warnings": warnings,
        "debug": debug,
        "log_path": log_path,
        "plan": plan,
    }




def export_mau1_llm_excel(
    *,
    year: int | None = None,
    huyen: str | None = None,
    use_llm: bool = True,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    """Public API cho app.py.

    Giữ huyen optional để tương thích kỹ thuật, nhưng UI tuần 4+5 hiện chỉ truyền năm.
    """
    return _export_mau1_xlsx_real_llm_assisted(
        year=year,
        huyen=huyen,
        use_llm=use_llm,
        samples_dir=samples_dir,
    )


# ── Experimental: LLM-assisted REAL Excel export for mẫu 2 ───────────────────
# Mẫu 2: Tổng hợp diễn biến hộ nghèo.
# LLM chỉ ánh xạ cột D:L -> fact_key diễn biến. Python validate, tính số từ DB
# và ghi cả 2 dòng Hộ/Nhân khẩu cho từng địa bàn.

MAU2_ALLOWED_COLUMN_FACTS = {
    "begin_poor",
    "reduced_to_near_poor",
    "reduced_to_non_poor",
    "reduced_other",
    "increase_near_poor_to_poor",
    "increase_re_poor",
    "increase_new_poor",
    "increase_other",
    "end_poor",
}

MAU2_DEFAULT_COLUMN_PLAN = [
    {"column": "D", "fact_key": "begin_poor", "unit": "households_or_persons", "reason": "Tổng số hộ nghèo đầu kỳ"},
    {"column": "E", "fact_key": "reduced_to_near_poor", "unit": "households_or_persons", "reason": "Số hộ thoát nghèo trở thành hộ cận nghèo"},
    {"column": "F", "fact_key": "reduced_to_non_poor", "unit": "households_or_persons", "reason": "Số hộ thoát nghèo vượt chuẩn cận nghèo"},
    {"column": "G", "fact_key": "reduced_other", "unit": "households_or_persons", "reason": "Số hộ giảm nghèo do nguyên nhân khác"},
    {"column": "H", "fact_key": "increase_near_poor_to_poor", "unit": "households_or_persons", "reason": "Số hộ cận nghèo trở thành hộ nghèo"},
    {"column": "I", "fact_key": "increase_re_poor", "unit": "households_or_persons", "reason": "Số hộ tái nghèo"},
    {"column": "J", "fact_key": "increase_new_poor", "unit": "households_or_persons", "reason": "Số hộ nghèo phát sinh mới"},
    {"column": "K", "fact_key": "increase_other", "unit": "households_or_persons", "reason": "Số hộ tăng nghèo do nguyên nhân khác"},
    {"column": "L", "fact_key": "end_poor", "unit": "households_or_persons", "reason": "Tổng số hộ nghèo cuối kỳ"},
]

MAU2_MOVEMENT_LABELS = {
    "reduced_to_near_poor": "Thoát nghèo -> cận nghèo",
    "reduced_to_non_poor": "Thoát nghèo -> vượt chuẩn",
    "reduced_other": "Giảm nghèo khác",
    "increase_near_poor_to_poor": "Cận nghèo trở thành hộ nghèo",
    "increase_re_poor": "Tái nghèo",
    "increase_new_poor": "Nghèo mới phát sinh",
    "increase_other": "Tăng nghèo khác",
}


def _mau2_default_column_plan(reason: str = "fallback") -> dict[str, Any]:
    column_mappings = []
    for item in MAU2_DEFAULT_COLUMN_PLAN:
        mapped = dict(item)
        mapped["source"] = reason
        column_mappings.append(mapped)
    return {
        "template_id": 2,
        "plan_type": "mau2_column_fact_mapping",
        "source": reason,
        "validation_status": "fallback_all",
        "llm_match_count": 0,
        "fallback_count": len(MAU2_DEFAULT_COLUMN_PLAN),
        "column_mappings": column_mappings,
        "notes": "Fallback deterministic: Python dùng mapping cột cố định cho mẫu 2.",
    }


def _extract_mau2_header_context_for_llm(samples_dir: Path | None = None) -> dict[str, Any]:
    """Trích context cột D:L của mẫu 2 để LLM ánh xạ cột -> fact_key."""
    template_id = 2
    path = _find_template_sample_path(template_id, samples_dir)
    if path is None:
        return {"ok": False, "template_id": 2, "error": "Không tìm thấy template mẫu 2."}
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        return {"ok": False, "template_id": 2, "template_path": str(path), "error": f"Không import được openpyxl: {exc}"}
    try:
        wb = load_workbook(path, read_only=False, data_only=False)
        ws = wb.active
        title_cells = []
        for r in range(1, 6):
            row_text = []
            for c in range(1, 13):
                v = ws.cell(r, c).value
                if v is not None and str(v).strip():
                    row_text.append(_short_text(v, 220))
            if row_text:
                title_cells.append({"row": r, "text": " | ".join(row_text)})

        column_context = []
        for c in range(4, 13):  # D:L
            labels = []
            for r in range(6, 10):
                v = ws.cell(r, c).value
                if v is not None and str(v).strip():
                    labels.append({"row": r, "value": _short_text(v, 240)})
            nearby = []
            for r in range(6, 10):
                for cc in range(max(1, c - 2), min(12, c + 2) + 1):
                    v = ws.cell(r, cc).value
                    if v is not None and str(v).strip():
                        nearby.append({"cell": f"{_column_letter(cc)}{r}", "value": _short_text(v, 180)})
            column_context.append({
                "column": _column_letter(c),
                "column_index": c,
                "direct_labels": labels,
                "nearby_header_cells": nearby[:14],
            })

        sample_area_rows = []
        for r in range(10, min(ws.max_row or 10, 42) + 1):
            label = ws.cell(r, 2).value
            unit = ws.cell(r, 3).value
            if label is not None and str(label).strip():
                sample_area_rows.append({
                    "row": r,
                    "tt": _short_text(ws.cell(r, 1).value, 40),
                    "area_label": _short_text(label, 120),
                    "phan_to": _short_text(unit, 60),
                })

        return {
            "ok": True,
            "template_id": 2,
            "template_path": _relative_or_str(path),
            "sheet_name": ws.title,
            "title_rows": title_cells,
            "column_context": column_context,
            "sample_area_rows": sample_area_rows,
            "allowed_fact_keys": sorted(MAU2_ALLOWED_COLUMN_FACTS),
            "fact_key_meanings": {item["fact_key"]: item["reason"] for item in MAU2_DEFAULT_COLUMN_PLAN},
        }
    except Exception as exc:
        return {"ok": False, "template_id": 2, "template_path": str(path), "error": f"Không đọc được template mẫu 2: {exc}"}


def _call_ollama_mau2_column_mapper(context: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    prompt_payload = {
        "template_id": 2,
        "title_rows": context.get("title_rows", []),
        "column_context": context.get("column_context", []),
        "allowed_fact_keys": sorted(MAU2_ALLOWED_COLUMN_FACTS),
        "required_columns": [item["column"] for item in MAU2_DEFAULT_COLUMN_PLAN],
        "fact_key_meanings": {item["fact_key"]: item["reason"] for item in MAU2_DEFAULT_COLUMN_PLAN},
        "unit_values_allowed": ["households_or_persons"],
        "important_rule": (
            "Mẫu 2 có 2 dòng cho mỗi địa bàn: dòng Hộ và dòng Nhân khẩu. "
            "Vì vậy mỗi cột D:L chỉ map sang một fact_key diễn biến, unit luôn là households_or_persons."
        ),
    }
    system = (
        "Bạn là AI ánh xạ cột Excel báo cáo hành chính sang fact_key. "
        "Bạn KHÔNG được sinh số liệu, KHÔNG được viết SQL, KHÔNG được sửa workbook. "
        "Bạn chỉ chọn fact_key từ allowed_fact_keys cho từng cột D:L của mẫu 2. "
        "Mỗi cột phải có đúng một mapping. Chỉ trả JSON hợp lệ, không markdown."
    )
    user = (
        "Hãy đọc context template mẫu 2 và trả JSON theo schema:\n"
        "{\n"
        "  \"template_id\": 2,\n"
        "  \"plan_type\": \"mau2_column_fact_mapping\",\n"
        "  \"column_mappings\": [\n"
        "    {\"column\": \"D\", \"fact_key\": \"...\", \"unit\": \"households_or_persons\", \"reason\": \"...\"}\n"
        "  ],\n"
        "  \"notes\": \"...\"\n"
        "}\n\n"
        "Context JSON:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = str((data.get("message") or {}).get("content") or "").strip()
        return _extract_json_object(raw), raw, None, prompt_payload
    except Exception as exc:
        return None, "", str(exc), prompt_payload


def _call_ollama_mau2_column_mapper_repair(
    context: dict[str, Any],
    *,
    first_raw_text: str,
    first_validation_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    required = [dict(item) for item in MAU2_DEFAULT_COLUMN_PLAN]
    prompt_payload = {
        "template_id": 2,
        "task": "repair_mau2_column_fact_mapping_strict",
        "failed_feedback": first_validation_warnings,
        "required_mappings": required,
        "allowed_fact_keys": sorted(MAU2_ALLOWED_COLUMN_FACTS),
        "required_output_schema": {
            "template_id": 2,
            "plan_type": "mau2_column_fact_mapping",
            "column_mappings": [{"column": "D", "fact_key": "begin_poor", "unit": "households_or_persons", "reason": "..."}],
            "notes": "repaired_by_llm_strict_copy",
        },
        "hard_rules": [
            "Chỉ trả một JSON object hợp lệ, không markdown, không giải thích.",
            "Output bắt buộc có key column_mappings.",
            "column_mappings phải có đúng 9 object, theo đúng thứ tự D,E,F,G,H,I,J,K,L.",
            "Mỗi object trong column_mappings phải copy đúng column, fact_key, unit từ required_mappings.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là AI sửa lỗi JSON mapping cột Excel. "
        "Nhiệm vụ là copy đúng required_mappings vào output, không suy diễn thêm. "
        "Chỉ trả JSON object hợp lệ."
    )
    user = (
        "Mapping trước đó bị validator báo sai. Hãy sửa bằng cách copy đúng required_mappings.\n\n"
        f"OUTPUT_TRƯỚC:\n{first_raw_text}\n\n"
        f"PAYLOAD:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        raw = str(((resp.json().get("message") or {}).get("content") or "").strip())
        return _extract_json_object(raw), raw, None, prompt_payload
    except Exception as exc:
        return None, "", str(exc), prompt_payload


def _mau2_required_mapping_for_columns(columns: list[str]) -> list[dict[str, Any]]:
    wanted = {str(c).upper() for c in columns}
    return [dict(item) for item in MAU2_DEFAULT_COLUMN_PLAN if str(item.get("column")).upper() in wanted]


def _mau2_fallback_columns_from_validated_plan(plan: dict[str, Any]) -> list[str]:
    cols: list[str] = []
    for item in plan.get("column_mappings") or []:
        if str(item.get("source") or "").startswith("fallback"):
            cols.append(str(item.get("column") or "").upper())
    return [c for c in cols if c]


def _mau2_combine_llm_plan_with_patch(base_plan: dict[str, Any], patch_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(base_plan, dict) or not isinstance(patch_plan, dict):
        return None
    by_col: dict[str, dict[str, Any]] = {}
    for item in base_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").upper()
        if not col:
            continue
        if str(item.get("source") or "") == "llm":
            by_col[col] = {k: v for k, v in item.items() if k != "source"}
    for item in patch_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").upper()
        if not col:
            continue
        by_col[col] = {k: v for k, v in item.items() if k != "source"}
    return {
        "template_id": 2,
        "plan_type": "mau2_column_fact_mapping",
        "column_mappings": [by_col[c] for c in [item["column"] for item in MAU2_DEFAULT_COLUMN_PLAN] if c in by_col],
        "notes": "combined_llm_initial_plus_targeted_repair",
    }


def _call_ollama_mau2_column_mapper_targeted_repair(
    *,
    bad_columns: list[str],
    previous_raw_text: str,
    previous_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    target_mappings = _mau2_required_mapping_for_columns(bad_columns)
    exact_output = {
        "template_id": 2,
        "plan_type": "mau2_column_fact_mapping_patch",
        "column_mappings": target_mappings,
        "notes": "targeted_column_patch",
    }
    prompt_payload = {
        "template_id": 2,
        "task": "targeted_repair_mau2_column_mapping",
        "bad_columns": bad_columns,
        "target_mappings": target_mappings,
        "previous_warnings": previous_warnings[-12:],
        "exact_output_to_return": exact_output,
        "hard_rules": [
            "Chỉ trả JSON object hợp lệ, không markdown, không giải thích.",
            "Chỉ trả các cột trong bad_columns, không trả lại toàn bộ D:L.",
            "Mỗi object phải copy đúng column, fact_key, unit từ target_mappings.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là AI sửa đúng một vài cột mapping Excel. "
        "Hãy copy chính xác exact_output_to_return, không tự diễn giải. Chỉ trả JSON."
    )
    user = f"Trả đúng JSON exact_output_to_return sau đây:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        raw = str(((resp.json().get("message") or {}).get("content") or "").strip())
        return _extract_json_object(raw), raw, None, prompt_payload
    except Exception as exc:
        return None, "", str(exc), prompt_payload


def _validate_mau2_column_mapping_plan(
    plan: dict[str, Any] | None,
    *,
    source: str,
    raw_error: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    expected_by_col = {item["column"]: item for item in MAU2_DEFAULT_COLUMN_PLAN}
    if not isinstance(plan, dict):
        default = _mau2_default_column_plan(reason=f"{source}_parse_error_fallback")
        if raw_error:
            warnings.append(f"LLM mẫu 2 lỗi hoặc không trả JSON hợp lệ: {raw_error}; dùng fallback toàn bộ.")
        else:
            warnings.append("LLM mẫu 2 không trả JSON mapping hợp lệ; dùng fallback toàn bộ.")
        return default, warnings

    raw_mappings = plan.get("column_mappings") or []
    if not isinstance(raw_mappings, list):
        raw_mappings = []

    candidate_by_col: dict[str, dict[str, Any]] = {}
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if col in expected_by_col and col not in candidate_by_col:
            candidate_by_col[col] = item

    validated: list[dict[str, Any]] = []
    llm_match_count = 0
    fallback_count = 0
    for expected in MAU2_DEFAULT_COLUMN_PLAN:
        col = expected["column"]
        got = candidate_by_col.get(col)
        if got:
            got_fact = str(got.get("fact_key") or "").strip()
            got_unit = str(got.get("unit") or "").strip()
            if got_fact not in MAU2_ALLOWED_COLUMN_FACTS:
                warnings.append(f"Cột {col}: LLM chọn fact_key không hợp lệ {got_fact!r}; dùng fallback {expected['fact_key']}.")
            elif got_fact != expected["fact_key"]:
                warnings.append(f"Cột {col}: LLM chọn {got_fact} nhưng schema mẫu 2 yêu cầu {expected['fact_key']}; dùng fallback {expected['fact_key']}.")
            elif got_unit != expected["unit"]:
                warnings.append(f"Cột {col}: LLM chọn unit {got_unit!r} nhưng schema mẫu 2 yêu cầu {expected['unit']!r}; dùng fallback.")
            else:
                mapped = {
                    "column": col,
                    "fact_key": got_fact,
                    "unit": got_unit,
                    "reason": str(got.get("reason") or expected.get("reason") or "LLM đề xuất"),
                    "source": "llm",
                }
                validated.append(mapped)
                llm_match_count += 1
                continue
        fallback = dict(expected)
        fallback["source"] = "fallback_for_missing_or_invalid_column"
        validated.append(fallback)
        fallback_count += 1
        warnings.append(f"Cột {col}: thiếu mapping hợp lệ từ LLM; dùng fallback {expected['fact_key']}.")

    status = f"{source}_validated" if fallback_count == 0 else f"{source}_validated_with_fallback"
    return {
        "template_id": 2,
        "plan_type": "mau2_column_fact_mapping",
        "source": source,
        "validation_status": status,
        "llm_match_count": llm_match_count,
        "fallback_count": fallback_count,
        "column_mappings": validated,
        "notes": str(plan.get("notes") or "LLM mapping mẫu 2 đã qua whitelist + guard schema; Python tính số và ghi Excel."),
    }, warnings


def _mau2_count_people(
    *,
    year: int | None,
    huyen: str | None,
    xa_phuong: str | None,
    phan_loai: str | None = None,
    bien_dong: str | None = None,
) -> tuple[int, int]:
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if xa_phuong:
        clauses.append("xa_phuong = ?")
        params.append(xa_phuong)
    if phan_loai:
        clauses.append("phan_loai = ?")
        params.append(phan_loai)
    if bien_dong:
        clauses.append("bien_dong_dau_ky = ?")
        params.append(bien_dong)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT id_ho), COALESCE(SUM(so_nhan_khau), 0) "
            f"FROM ho_ngheo{where}",
            params,
        ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def _mau2_metric_pair(households: int, people: int) -> dict[str, int]:
    return {"households": int(households or 0), "people": int(people or 0)}


def _mau2_compute_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, dict[str, int]]:
    allow_other = _movement_other_reason_available()
    old_hh, old_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong="Nghèo cũ (giữ nguyên)")
    e_hh, e_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["reduced_to_near_poor"])
    f_hh, f_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["reduced_to_non_poor"])
    g_hh, g_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["reduced_other"]) if allow_other else (0, 0)
    h_hh, h_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["increase_near_poor_to_poor"])
    i_hh, i_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["increase_re_poor"])
    j_hh, j_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["increase_new_poor"])
    k_hh, k_people = _mau2_count_people(year=year, huyen=huyen, xa_phuong=xa_phuong, bien_dong=MAU2_MOVEMENT_LABELS["increase_other"]) if allow_other else (0, 0)

    begin_hh = old_hh + e_hh + f_hh + g_hh
    begin_people = old_people + e_people + f_people + g_people
    end_hh = begin_hh - e_hh - f_hh - g_hh + h_hh + i_hh + j_hh + k_hh
    end_people = begin_people - e_people - f_people - g_people + h_people + i_people + j_people + k_people

    return {
        "begin_poor": _mau2_metric_pair(begin_hh, begin_people),
        "reduced_to_near_poor": _mau2_metric_pair(e_hh, e_people),
        "reduced_to_non_poor": _mau2_metric_pair(f_hh, f_people),
        "reduced_other": _mau2_metric_pair(g_hh, g_people),
        "increase_near_poor_to_poor": _mau2_metric_pair(h_hh, h_people),
        "increase_re_poor": _mau2_metric_pair(i_hh, i_people),
        "increase_new_poor": _mau2_metric_pair(j_hh, j_people),
        "increase_other": _mau2_metric_pair(k_hh, k_people),
        "end_poor": _mau2_metric_pair(end_hh, end_people),
    }


def _mau2_zero_metrics() -> dict[str, dict[str, int]]:
    return {item["fact_key"]: _mau2_metric_pair(0, 0) for item in MAU2_DEFAULT_COLUMN_PLAN}


def _write_llm_excel_mau2_debug_log(debug: dict[str, Any]) -> str | None:
    if write_jsonl_log is None:
        return None
    return write_jsonl_log("llm_excel_mau2", debug)


def _resolve_template_area(label_text: str, tt_text: str, current_huyen: str | None, area: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Trả (row_type, huyen, xa_phuong) cho dòng template."""
    label_key = _area_key(label_text)
    is_commune_row = "." in str(tt_text or "")

    if not is_commune_row:
        matched_huyen = area.get("district_by_key", {}).get(label_key)
        if matched_huyen:
            return "district", matched_huyen, None

    if is_commune_row and current_huyen:
        xa_map = area.get("xa_by_huyen_key", {}).get(current_huyen, {})
        matched_xa = xa_map.get(label_key)
        if matched_xa:
            return "commune", current_huyen, matched_xa

    # Fallback mềm: đôi khi TT bị format lạ, thử match huyện trước rồi xã sau.
    matched_huyen = area.get("district_by_key", {}).get(label_key)
    if matched_huyen:
        return "district", matched_huyen, None
    if current_huyen:
        xa_map = area.get("xa_by_huyen_key", {}).get(current_huyen, {})
        matched_xa = xa_map.get(label_key)
        if matched_xa:
            return "commune", current_huyen, matched_xa
    return None, None, None


def _export_mau2_xlsx_real_llm_assisted(
    *,
    year: int | None,
    huyen: str | None,
    use_llm: bool,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": "mau2_real_llm_excel_export",
        "template_id": 2,
        "year": year,
        "huyen": huyen,
        "use_llm": bool(use_llm),
        "llm_attempted": False,
        "llm_error": None,
        "raw_llm_text": "",
        "prompt_payload": None,
        "validated_plan": None,
        "validation_warnings": [],
        "filled_rows": [],
        "filled_cell_count": 0,
        "limitations": [],
        "data_mapping_notes": [
            "Mẫu 2 dùng bien_dong_dau_ky để tính các cột diễn biến E/F/G/H/I/J/K.",
            "Cột D đầu kỳ = Nghèo cũ + các cột giảm E/F/G theo bien_dong_dau_ky.",
            "Cột G/K chỉ dùng khi DB có cột lý do biến động chi tiết.",
            "Cột L cuối kỳ = D - E - F - G + H + I + J + K.",
        ],
    }
    warnings: list[str] = []

    samples_root = samples_dir or DATA_SAMPLES_DIR
    header_context = _extract_mau2_header_context_for_llm(samples_root)
    debug["header_context"] = header_context
    if not header_context.get("ok"):
        plan = _mau2_default_column_plan(reason="context_error_fallback")
        warnings.append(header_context.get("error") or "Không trích được context mẫu 2; dùng fallback.")
    elif use_llm:
        debug["llm_attempted"] = True
        parsed, raw, error, prompt_payload = _call_ollama_mau2_column_mapper(header_context)
        debug["prompt_payload"] = prompt_payload
        debug["raw_llm_text"] = raw
        debug["llm_error"] = error
        plan, plan_warnings = _validate_mau2_column_mapping_plan(parsed, source="llm", raw_error=error)
        warnings.extend(plan_warnings)

        debug["llm_first_raw_text"] = raw
        debug["llm_first_validated_plan"] = plan
        debug["llm_first_validation_warnings"] = list(plan_warnings)
        debug["llm_repair_attempted"] = False
        debug["llm_repair_error"] = None
        debug["llm_repair_raw_text"] = ""
        debug["llm_repair_prompt_payload"] = None
        debug["llm_repair_validated_plan"] = None
        debug["llm_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            debug["llm_repair_attempted"] = True
            repaired, repair_raw, repair_error, repair_payload = _call_ollama_mau2_column_mapper_repair(
                header_context,
                first_raw_text=raw,
                first_validation_warnings=list(plan_warnings),
            )
            debug["llm_repair_error"] = repair_error
            debug["llm_repair_raw_text"] = repair_raw
            debug["llm_repair_prompt_payload"] = repair_payload
            repaired_plan, repaired_warnings = _validate_mau2_column_mapping_plan(
                repaired,
                source="llm_repair",
                raw_error=repair_error,
            )
            debug["llm_repair_validated_plan"] = repaired_plan
            debug["llm_repair_validation_warnings"] = list(repaired_warnings)
            if int(repaired_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                plan = repaired_plan
                warnings.append(
                    f"LLM repair mẫu 2 cải thiện mapping: fallback_count "
                    f"{debug['llm_first_validated_plan'].get('fallback_count')} -> {plan.get('fallback_count')}."
                )
                warnings.extend(repaired_warnings)
                debug["raw_llm_text"] = repair_raw
                debug["prompt_payload"] = repair_payload
                debug["llm_error"] = repair_error
            else:
                warnings.append("LLM repair mẫu 2 không cải thiện mapping; giữ plan lần 1 đã fallback an toàn.")
                warnings.extend(repaired_warnings)

        debug["llm_targeted_repair_attempted"] = False
        debug["llm_targeted_repair_columns"] = []
        debug["llm_targeted_repair_error"] = None
        debug["llm_targeted_repair_raw_text"] = ""
        debug["llm_targeted_repair_prompt_payload"] = None
        debug["llm_targeted_repair_validated_plan"] = None
        debug["llm_targeted_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            bad_cols = _mau2_fallback_columns_from_validated_plan(plan)
            if bad_cols:
                debug["llm_targeted_repair_attempted"] = True
                debug["llm_targeted_repair_columns"] = list(bad_cols)
                targeted, targeted_raw, targeted_error, targeted_payload = _call_ollama_mau2_column_mapper_targeted_repair(
                    bad_columns=bad_cols,
                    previous_raw_text=str(debug.get("raw_llm_text") or raw or ""),
                    previous_warnings=list(warnings),
                )
                debug["llm_targeted_repair_error"] = targeted_error
                debug["llm_targeted_repair_raw_text"] = targeted_raw
                debug["llm_targeted_repair_prompt_payload"] = targeted_payload
                combined = _mau2_combine_llm_plan_with_patch(plan, targeted)
                targeted_plan, targeted_warnings = _validate_mau2_column_mapping_plan(
                    combined,
                    source="llm_targeted_repair",
                    raw_error=targeted_error,
                )
                debug["llm_targeted_repair_validated_plan"] = targeted_plan
                debug["llm_targeted_repair_validation_warnings"] = list(targeted_warnings)
                if int(targeted_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                    old_fallback = int(plan.get("fallback_count") or 0)
                    plan = targeted_plan
                    warnings.append(f"LLM targeted repair mẫu 2 cải thiện mapping: fallback_count {old_fallback} -> {plan.get('fallback_count')}.")
                    warnings.extend(targeted_warnings)
                    debug["raw_llm_text"] = targeted_raw
                    debug["prompt_payload"] = targeted_payload
                    debug["llm_error"] = targeted_error
                else:
                    warnings.append("LLM targeted repair mẫu 2 không cải thiện mapping; giữ plan tốt nhất hiện có.")
                    warnings.extend(targeted_warnings)

        debug["llm_final_full_match"] = (
            str(plan.get("validation_status")) in {"llm_validated", "llm_repair_validated", "llm_targeted_repair_validated"}
            and int(plan.get("fallback_count") or 0) == 0
        )
    else:
        plan = _mau2_default_column_plan(reason="llm_disabled_fallback")
        warnings.append("LLM bị tắt; dùng mapping deterministic cho mẫu 2.")
        debug["llm_final_full_match"] = False

    other_reason_available = _movement_other_reason_available()
    debug["other_reason_available"] = other_reason_available
    debug["movement_other_policy"] = "use_explicit_reason_columns" if other_reason_available else "zero_without_explicit_reason"
    if not other_reason_available:
        warnings.append(MOVEMENT_OTHER_NO_REASON_WARNING)
        debug["limitations"] = [MOVEMENT_OTHER_NO_REASON_WARNING]

    debug["validated_plan"] = plan
    debug["validation_warnings"] = list(warnings)
    expected_by_col = {item["column"]: item for item in MAU2_DEFAULT_COLUMN_PLAN}
    debug["final_mapping_correct_by_schema"] = all(
        str(m.get("fact_key")) == str(expected_by_col.get(str(m.get("column")), {}).get("fact_key"))
        and str(m.get("unit")) == str(expected_by_col.get(str(m.get("column")), {}).get("unit"))
        for m in plan.get("column_mappings") or []
    )
    debug["final_mapping_source"] = plan.get("source")
    debug["final_mapping_validation_status"] = plan.get("validation_status")

    template_path = _find_template_sample_path(2, samples_root)
    if template_path is None:
        raise FileNotFoundError("Không tìm thấy file template mẫu 2 trong data/report_samples.")
    try:
        from openpyxl import load_workbook  # type: ignore
        from openpyxl.cell.cell import MergedCell  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Không import được openpyxl để ghi Excel mẫu 2: {exc}")

    wb = load_workbook(template_path)
    ws = wb.active
    area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in MAU2_DEFAULT_COLUMN_PLAN:
        col_to_fact.setdefault(item["column"], item["fact_key"])

    current_huyen: str | None = None
    current_area_info: dict[str, Any] | None = None
    filled_rows: list[dict[str, Any]] = []
    filled_cell_count = 0

    # Mẫu 2 bắt đầu dữ liệu từ dòng 10, mỗi địa bàn có 2 dòng: Hộ / Nhân khẩu.
    for r in range(10, (ws.max_row or 10) + 1):
        unit_text = str(ws.cell(r, 3).value or "").strip()
        unit_key = _vn_key(unit_text)
        if unit_key not in {"ho", "nhan khau"}:
            continue

        label_text = str(ws.cell(r, 2).value or "").strip()
        tt_text = str(ws.cell(r, 1).value or "").strip()
        if unit_key == "ho":
            row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
            if row_type == "district" and row_huyen:
                current_huyen = row_huyen
            current_area_info = {
                "row_type": row_type,
                "huyen": row_huyen,
                "xa_phuong": row_xa,
                "label": label_text,
                "tt": tt_text,
            }
        elif current_area_info:
            row_type = current_area_info.get("row_type")
            row_huyen = current_area_info.get("huyen")
            row_xa = current_area_info.get("xa_phuong")
            label_text = str(current_area_info.get("label") or label_text)
            tt_text = str(current_area_info.get("tt") or tt_text)
        else:
            row_type = row_huyen = row_xa = None

        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text, "phan_to": unit_text})
            continue

        in_scope = True
        if huyen and row_huyen != huyen:
            in_scope = False
        metrics = _mau2_compute_metrics(year, row_huyen, row_xa) if in_scope else _mau2_zero_metrics()
        metric_unit = "people" if unit_key == "nhan khau" else "households"

        sample_values: dict[str, Any] = {}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell):
                continue
            value = int((metrics.get(fact_key) or {}).get(metric_unit) or 0)
            cell.value = value
            cell.number_format = "#,##0"
            filled_cell_count += 1
            sample_values[col] = value

        filled_rows.append({
            "row": r,
            "label": label_text,
            "row_type": row_type,
            "huyen": row_huyen,
            "xa_phuong": row_xa,
            "phan_to": unit_text,
            "in_scope": in_scope,
            "values_sample_D_to_L": {k: sample_values.get(k) for k in ["D", "E", "F", "G", "H", "I", "J", "K", "L"]},
        })

    try:
        _set_workbook_demo_properties(wb)
    except Exception:
        pass

    bio = BytesIO()
    _set_workbook_demo_properties(wb)
    wb.save(bio)
    content = bio.getvalue()
    debug["filled_cell_count"] = filled_cell_count
    debug["filled_rows"] = filled_rows[:180]
    debug["filled_rows_total"] = len(filled_rows)
    debug["template_path"] = _relative_or_str(template_path)
    debug["output_bytes"] = len(content)
    log_path = _write_llm_excel_mau2_debug_log(debug)
    debug["log_path"] = log_path
    return {
        "content": content,
        "warnings": warnings,
        "debug": debug,
        "log_path": log_path,
        "plan": plan,
    }


def export_mau2_llm_excel(
    *,
    year: int | None = None,
    huyen: str | None = None,
    use_llm: bool = True,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    """Public API cho app.py: Excel LLM-assisted mapping cho mẫu 2."""
    return _export_mau2_xlsx_real_llm_assisted(
        year=year,
        huyen=huyen,
        use_llm=use_llm,
        samples_dir=samples_dir,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mẫu 3/4/5: LLM ánh xạ cột, Python validate + tính số + ghi Excel.
# Gói chung để không tách thêm folder con.


def _default_column_plan_generic(
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    reason: str = "fallback",
) -> dict[str, Any]:
    column_mappings = []
    for item in default_plan:
        mapped = dict(item)
        mapped["source"] = reason
        column_mappings.append(mapped)
    return {
        "template_id": template_id,
        "plan_type": plan_type,
        "source": reason,
        "validation_status": "fallback_all",
        "llm_match_count": 0,
        "fallback_count": len(default_plan),
        "column_mappings": column_mappings,
        "notes": f"Fallback deterministic: Python dùng mapping cột cố định cho mẫu {template_id}.",
    }


def _validate_column_mapping_plan_generic(
    parsed: dict[str, Any] | None,
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    allowed_facts: set[str],
    source: str,
    raw_error: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    expected_by_col = {str(item["column"]).upper(): item for item in default_plan}
    if raw_error:
        warnings.append(str(raw_error))
    if not isinstance(parsed, dict):
        default = _default_column_plan_generic(
            template_id=template_id,
            plan_type=plan_type,
            default_plan=default_plan,
            reason=f"{source}_parse_error_fallback",
        )
        warnings.append("LLM không trả JSON object hợp lệ; dùng fallback toàn bộ mapping.")
        return default, warnings

    raw_mappings = parsed.get("column_mappings")
    if not isinstance(raw_mappings, list):
        raw_mappings = []
        warnings.append("LLM không trả column_mappings dạng list; dùng fallback theo cột.")

    by_col: dict[str, dict[str, Any]] = {}
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if col:
            by_col[col] = item

    validated: list[dict[str, Any]] = []
    llm_match_count = 0
    fallback_count = 0
    for expected in default_plan:
        col = str(expected["column"]).upper()
        got = by_col.get(col)
        ok = False
        if got:
            got_fact = str(got.get("fact_key") or "").strip()
            got_unit = str(got.get("unit") or "").strip()
            if got_fact not in allowed_facts:
                warnings.append(f"Cột {col}: fact_key '{got_fact}' không nằm trong whitelist; dùng fallback {expected['fact_key']}.")
            elif got_fact != str(expected["fact_key"]):
                warnings.append(f"Cột {col}: LLM chọn {got_fact} nhưng schema mẫu {template_id} yêu cầu {expected['fact_key']}; dùng fallback.")
            elif got_unit != str(expected["unit"]):
                warnings.append(f"Cột {col}: LLM chọn unit '{got_unit}' nhưng schema mẫu {template_id} yêu cầu '{expected['unit']}'; dùng fallback.")
            else:
                ok = True
        if ok:
            validated.append({
                "column": col,
                "fact_key": str(expected["fact_key"]),
                "unit": str(expected["unit"]),
                "reason": str((got or {}).get("reason") or expected.get("reason") or "LLM đề xuất"),
                "source": "llm",
            })
            llm_match_count += 1
        else:
            item = dict(expected)
            item["source"] = "fallback_for_missing_or_invalid_column"
            validated.append(item)
            fallback_count += 1
            warnings.append(f"Cột {col}: thiếu mapping hợp lệ từ LLM; dùng fallback {expected['fact_key']}.")

    if fallback_count == 0:
        status = f"{source}_validated"
    else:
        status = f"{source}_validated_with_fallback"
    return {
        "template_id": template_id,
        "plan_type": plan_type,
        "source": source,
        "validation_status": status,
        "llm_match_count": llm_match_count,
        "fallback_count": fallback_count,
        "column_mappings": validated,
        "notes": f"LLM mapping mẫu {template_id} đã qua whitelist + guard schema; Python tính số và ghi Excel.",
    }, warnings


def _extract_header_context_for_llm_generic(
    *,
    template_id: int,
    start_col: int,
    end_col: int,
    title_row_max: int,
    header_row_start: int,
    header_row_end: int,
    data_row_start: int,
    data_row_max_preview: int,
    default_plan: list[dict[str, Any]],
    allowed_facts: set[str],
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    path = _find_template_sample_path(template_id, samples_dir)
    if path is None:
        return {"ok": False, "template_id": template_id, "error": f"Không tìm thấy template mẫu {template_id}."}
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        return {"ok": False, "template_id": template_id, "template_path": str(path), "error": f"Không import được openpyxl: {exc}"}
    try:
        wb = load_workbook(path, read_only=False, data_only=False)
        ws = wb.active
        title_cells = []
        for r in range(1, title_row_max + 1):
            row_text = []
            for c in range(1, min(ws.max_column or end_col, end_col) + 1):
                v = ws.cell(r, c).value
                if v is not None and str(v).strip():
                    row_text.append(_short_text(v, 220))
            if row_text:
                title_cells.append({"row": r, "text": " | ".join(row_text)})

        column_context = []
        for c in range(start_col, end_col + 1):
            labels = []
            for r in range(header_row_start, header_row_end + 1):
                v = ws.cell(r, c).value
                if v is not None and str(v).strip():
                    labels.append({"row": r, "value": _short_text(v, 260)})
            nearby = []
            for r in range(header_row_start, header_row_end + 1):
                for cc in range(max(1, c - 2), min(end_col, c + 2) + 1):
                    v = ws.cell(r, cc).value
                    if v is not None and str(v).strip():
                        nearby.append({"cell": f"{_column_letter(cc)}{r}", "value": _short_text(v, 180)})
            column_context.append({
                "column": _column_letter(c),
                "column_index": c,
                "direct_labels": labels,
                "nearby_header_cells": nearby[:14],
            })

        sample_area_rows = []
        max_preview = min(ws.max_row or data_row_start, data_row_max_preview)
        for r in range(data_row_start, max_preview + 1):
            label = ws.cell(r, 2).value
            if label is not None and str(label).strip():
                item = {
                    "row": r,
                    "tt": _short_text(ws.cell(r, 1).value, 40),
                    "area_label": _short_text(label, 120),
                }
                unit = ws.cell(r, 3).value
                if unit is not None and str(unit).strip():
                    item["phan_to"] = _short_text(unit, 60)
                sample_area_rows.append(item)

        return {
            "ok": True,
            "template_id": template_id,
            "template_path": _relative_or_str(path),
            "sheet_name": ws.title,
            "title_rows": title_cells,
            "column_context": column_context,
            "sample_area_rows": sample_area_rows,
            "allowed_fact_keys": sorted(allowed_facts),
            "fact_key_meanings": {item["fact_key"]: item.get("reason") for item in default_plan},
        }
    except Exception as exc:
        return {"ok": False, "template_id": template_id, "template_path": str(path), "error": f"Không đọc được template mẫu {template_id}: {exc}"}


def _call_ollama_column_mapper_generic(
    context: dict[str, Any],
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    allowed_facts: set[str],
    unit_values_allowed: list[str],
    extra_rule: str,
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    prompt_payload = {
        "template_id": template_id,
        "title_rows": context.get("title_rows", []),
        "column_context": context.get("column_context", []),
        "allowed_fact_keys": sorted(allowed_facts),
        "required_columns": [item["column"] for item in default_plan],
        "fact_key_meanings": {item["fact_key"]: item.get("reason") for item in default_plan},
        "unit_values_allowed": unit_values_allowed,
        "important_rule": extra_rule,
    }
    system = (
        "Bạn là AI ánh xạ cột Excel báo cáo hành chính sang fact_key. "
        "Bạn KHÔNG được sinh số liệu, KHÔNG được viết SQL, KHÔNG được sửa workbook. "
        "Mỗi cột phải có đúng một mapping. Chỉ trả JSON hợp lệ, không markdown."
    )
    first = default_plan[0]
    user = (
        f"Hãy đọc context template mẫu {template_id} và trả JSON theo schema:\n"
        "{\n"
        f"  \"template_id\": {template_id},\n"
        f"  \"plan_type\": \"{plan_type}\",\n"
        "  \"column_mappings\": [\n"
        f"    {{\"column\": \"{first['column']}\", \"fact_key\": \"...\", \"unit\": \"{first['unit']}\", \"reason\": \"...\"}}\n"
        "  ],\n"
        "  \"notes\": \"...\"\n"
        "}\n\n"
        "Context JSON:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = str((data.get("message") or {}).get("content") or data.get("response") or "").strip()
        return _extract_json_object(raw), raw, None, prompt_payload
    except Exception as exc:
        return None, "", str(exc), prompt_payload


def _call_ollama_column_mapper_repair_generic(
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    allowed_facts: set[str],
    first_raw_text: str,
    first_validation_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    required = [dict(item) for item in default_plan]
    prompt_payload = {
        "template_id": template_id,
        "task": f"repair_mau{template_id}_column_fact_mapping_strict",
        "failed_feedback": first_validation_warnings,
        "required_mappings": required,
        "allowed_fact_keys": sorted(allowed_facts),
        "required_output_schema": {
            "template_id": template_id,
            "plan_type": plan_type,
            "column_mappings": [required[0] if required else {}],
            "notes": "repaired_by_llm_strict_copy",
        },
        "hard_rules": [
            "Chỉ trả một JSON object hợp lệ, không markdown, không giải thích.",
            "Output bắt buộc có key column_mappings.",
            "Mỗi object trong column_mappings phải copy đúng column, fact_key, unit từ required_mappings.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là AI sửa lỗi JSON mapping cột Excel. "
        "Nhiệm vụ là copy đúng required_mappings vào output, không suy diễn thêm. "
        "Chỉ trả JSON object hợp lệ."
    )
    user = (
        "Mapping trước đó bị validator báo sai. Hãy sửa bằng cách copy đúng required_mappings.\n\n"
        f"OUTPUT_TRƯỚC:\n{first_raw_text}\n\n"
        f"PAYLOAD:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = str((data.get("message") or {}).get("content") or data.get("response") or "").strip()
        return _extract_json_object(raw), raw, None, prompt_payload
    except Exception as exc:
        return None, "", str(exc), prompt_payload


def _required_mapping_for_columns_generic(default_plan: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    """Lấy mapping chuẩn cho một vài cột cần targeted repair."""
    wanted = {str(c or "").strip().upper() for c in columns}
    return [dict(item) for item in default_plan if str(item.get("column") or "").strip().upper() in wanted]


def _fallback_columns_from_validated_plan_generic(plan: dict[str, Any]) -> list[str]:
    """Các cột hiện còn fallback sau validate.

    Bản cũ chỉ bắt source bắt đầu bằng ``fallback``. Với trường hợp LLM trả
    văn bản thay vì JSON, toàn bộ mapping dùng reason/source kiểu
    ``llm_parse_error_fallback`` nên targeted repair không chạy. Hàm này bắt
    rộng hơn: mọi source có chữ fallback, hoặc plan đang fallback_all, đều được
    xem là cột cần repair.
    """
    cols: list[str] = []
    fallback_all = str(plan.get("validation_status") or "") == "fallback_all"
    for item in plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        if fallback_all or "fallback" in source:
            col = str(item.get("column") or "").strip().upper()
            if col:
                cols.append(col)
    return cols


def _combine_column_mapping_plan_with_patch_generic(
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    base_plan: dict[str, Any],
    patch_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Ghép mapping LLM đã đúng từ plan hiện tại với patch LLM cho cột còn fallback.

    Không lấy các dòng fallback từ base_plan, vì cần validator phân biệt đúng phần nào thật sự do LLM trả.
    """
    if not isinstance(base_plan, dict) or not isinstance(patch_plan, dict):
        return None
    by_col: dict[str, dict[str, Any]] = {}
    for item in base_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if not col:
            continue
        if str(item.get("source") or "") == "llm":
            by_col[col] = {
                "column": col,
                "fact_key": item.get("fact_key"),
                "unit": item.get("unit"),
                "reason": item.get("reason") or "LLM đề xuất",
            }
    for item in patch_plan.get("column_mappings") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip().upper()
        if not col:
            continue
        by_col[col] = {
            "column": col,
            "fact_key": item.get("fact_key"),
            "unit": item.get("unit"),
            "reason": item.get("reason") or "LLM targeted repair",
        }
    return {
        "template_id": template_id,
        "plan_type": plan_type,
        "column_mappings": [by_col.get(str(item["column"]).upper(), {}) for item in default_plan],
        "notes": "combined_llm_plan_plus_targeted_repair",
    }


def _call_ollama_column_mapper_targeted_repair_generic(
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    bad_columns: list[str],
    previous_raw_text: str,
    previous_warnings: list[str],
) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    """Sửa hẹp các cột còn fallback sau vòng repair.

    Dùng cho mẫu 3: Qwen thường đảo G/K hoặc typo unit ở repair. Targeted repair chỉ đưa đúng các cột còn sai để model copy lại.
    """
    target_mappings = _required_mapping_for_columns_generic(default_plan, bad_columns)
    exact_output = {
        "template_id": template_id,
        "plan_type": f"mau{template_id}_column_fact_mapping_patch",
        "column_mappings": target_mappings,
        "notes": "targeted_column_patch",
    }
    prompt_payload = {
        "template_id": template_id,
        "task": f"targeted_repair_mau{template_id}_column_mapping",
        "bad_columns": [m["column"] for m in target_mappings],
        "target_mappings": target_mappings,
        "previous_warnings": previous_warnings[-12:],
        "exact_output_to_return": exact_output,
        "hard_rules": [
            "Chỉ trả JSON object hợp lệ, không markdown, không giải thích.",
            "Chỉ trả các cột trong bad_columns. Nếu bad_columns là toàn bộ cột của mẫu thì vẫn trả đủ toàn bộ các cột đó.",
            "Mỗi object phải copy đúng column, fact_key, unit từ target_mappings.",
            "Không tự đổi thứ tự cột, không tự đổi fact_key, không tự đổi unit.",
            "Không tự đổi reduced_other và increase_other.",
            "Không tự đổi households_or_persons thành households_or_personas.",
            "Không viết văn bản mô tả. Không tóm tắt mẫu. Không thêm nhận xét ngoài JSON.",
            "Không sinh số liệu, không viết SQL, không sửa workbook.",
        ],
    }
    system = (
        "Bạn là bộ máy trả JSON, không phải trợ lý viết văn. Nhiệm vụ duy nhất là copy chính xác "
        "exact_output_to_return thành JSON object hợp lệ. Không suy luận, không giải thích, không markdown, "
        "không tóm tắt mẫu."
    )
    user = (
        "Trả đúng JSON object trong exact_output_to_return. "
        "Không được trả văn bản mô tả. Không được giải thích.\n"
        + json.dumps(prompt_payload, ensure_ascii=False, default=str)
    )
    try:
        import requests  # type: ignore
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.1, "repeat_penalty": 1.02},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = str((data.get("message") or {}).get("content") or data.get("response") or "").strip()
        parsed = _extract_json_object(raw)
        if parsed is None:
            return None, raw, "LLM targeted repair không trả JSON hợp lệ.", prompt_payload
        if "column_mappings" not in parsed:
            return None, raw, "LLM targeted repair trả JSON nhưng thiếu key column_mappings.", prompt_payload
        return parsed, raw, None, prompt_payload
    except Exception as exc:
        return None, "", f"Không gọi được Ollama/Qwen cho targeted repair mẫu {template_id}: {exc}", prompt_payload


# ── Mẫu 3: Tổng hợp diễn biến hộ cận nghèo ──────────────────────────────────

MAU3_ALLOWED_COLUMN_FACTS = {
    "begin_near_poor",
    "reduced_to_non_poor",
    "reduced_to_poor",
    "reduced_other",
    "increase_poor_to_near_poor",
    "increase_re_near_poor",
    "increase_new_near_poor",
    "increase_other",
    "end_near_poor",
}

MAU3_DEFAULT_COLUMN_PLAN = [
    {"column": "D", "fact_key": "begin_near_poor", "unit": "households_or_persons", "reason": "Tổng số hộ cận nghèo đầu kỳ"},
    {"column": "E", "fact_key": "reduced_to_non_poor", "unit": "households_or_persons", "reason": "Số hộ thoát cận nghèo"},
    {"column": "F", "fact_key": "reduced_to_poor", "unit": "households_or_persons", "reason": "Số hộ cận nghèo trở thành hộ nghèo"},
    {"column": "G", "fact_key": "reduced_other", "unit": "households_or_persons", "reason": "Số hộ giảm cận nghèo do nguyên nhân khác"},
    {"column": "H", "fact_key": "increase_poor_to_near_poor", "unit": "households_or_persons", "reason": "Số hộ nghèo trở thành hộ cận nghèo"},
    {"column": "I", "fact_key": "increase_re_near_poor", "unit": "households_or_persons", "reason": "Số hộ tái cận nghèo"},
    {"column": "J", "fact_key": "increase_new_near_poor", "unit": "households_or_persons", "reason": "Số hộ cận nghèo phát sinh mới"},
    {"column": "K", "fact_key": "increase_other", "unit": "households_or_persons", "reason": "Số hộ tăng cận nghèo do nguyên nhân khác"},
    {"column": "L", "fact_key": "end_near_poor", "unit": "households_or_persons", "reason": "Tổng số hộ cận nghèo cuối kỳ"},
]

MAU3_MOVEMENT_LABELS = {
    "reduced_to_non_poor": "Thoát cận nghèo -> vượt chuẩn",
    "reduced_to_poor": "Cận nghèo trở thành hộ nghèo",
    "reduced_other": "Giảm cận nghèo khác",
    "increase_poor_to_near_poor": "Thoát nghèo -> cận nghèo",
    "increase_re_near_poor": "Tái cận nghèo",
    "increase_new_near_poor": "Cận nghèo mới phát sinh",
    "increase_other": "Tăng cận nghèo khác",
}


def _mau3_count_people(year: int | None, huyen: str | None, xa_phuong: str | None, *, phan_loai: str | None = None, bien_dong: str | None = None) -> tuple[int, int]:
    clauses = []
    params: list[Any] = []
    if year:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if xa_phuong:
        clauses.append("xa_phuong = ?")
        params.append(xa_phuong)
    if phan_loai:
        clauses.append("phan_loai = ?")
        params.append(phan_loai)
    if bien_dong:
        clauses.append("bien_dong_dau_ky = ?")
        params.append(bien_dong)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with sqlite3.connect(DB_PATH) as conn:
        hh, people = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(so_nhan_khau),0) FROM ho_ngheo{where}", params).fetchone()
    return int(hh or 0), int(people or 0)


def _mau3_compute_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, dict[str, int]]:
    allow_other = _movement_other_reason_available()
    old_hh, old_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong="Cận nghèo cũ (giữ nguyên)")
    e_hh, e_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["reduced_to_non_poor"])
    f_hh, f_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["reduced_to_poor"])
    g_hh, g_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["reduced_other"]) if allow_other else (0, 0)
    h_hh, h_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["increase_poor_to_near_poor"])
    i_hh, i_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["increase_re_near_poor"])
    j_hh, j_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["increase_new_near_poor"])
    k_hh, k_people = _mau3_count_people(year, huyen, xa_phuong, bien_dong=MAU3_MOVEMENT_LABELS["increase_other"]) if allow_other else (0, 0)
    begin_hh = old_hh + e_hh + f_hh + g_hh
    begin_people = old_people + e_people + f_people + g_people
    end_hh = begin_hh - e_hh - f_hh - g_hh + h_hh + i_hh + j_hh + k_hh
    end_people = begin_people - e_people - f_people - g_people + h_people + i_people + j_people + k_people
    pair = _mau2_metric_pair
    return {
        "begin_near_poor": pair(begin_hh, begin_people),
        "reduced_to_non_poor": pair(e_hh, e_people),
        "reduced_to_poor": pair(f_hh, f_people),
        "reduced_other": pair(g_hh, g_people),
        "increase_poor_to_near_poor": pair(h_hh, h_people),
        "increase_re_near_poor": pair(i_hh, i_people),
        "increase_new_near_poor": pair(j_hh, j_people),
        "increase_other": pair(k_hh, k_people),
        "end_near_poor": pair(end_hh, end_people),
    }


def _export_mau3_xlsx_real_llm_assisted(*, year: int | None, huyen: str | None, use_llm: bool, samples_dir: Path | None = None) -> dict[str, Any]:
    template_id = 3
    plan_type = "mau3_column_fact_mapping"
    samples_root = samples_dir or DATA_SAMPLES_DIR
    debug: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": "mau3_real_llm_excel_export",
        "template_id": template_id,
        "year": year,
        "huyen": huyen,
        "use_llm": bool(use_llm),
        "llm_attempted": False,
        "llm_error": None,
    }
    warnings: list[str] = []
    header_context = _extract_header_context_for_llm_generic(
        template_id=3, start_col=4, end_col=12, title_row_max=6, header_row_start=8, header_row_end=11,
        data_row_start=12, data_row_max_preview=44, default_plan=MAU3_DEFAULT_COLUMN_PLAN,
        allowed_facts=MAU3_ALLOWED_COLUMN_FACTS, samples_dir=samples_root,
    )
    debug["header_context"] = header_context
    if use_llm and header_context.get("ok"):
        debug["llm_attempted"] = True
        parsed, raw, error, payload = _call_ollama_column_mapper_generic(
            header_context, template_id=3, plan_type=plan_type, default_plan=MAU3_DEFAULT_COLUMN_PLAN,
            allowed_facts=MAU3_ALLOWED_COLUMN_FACTS, unit_values_allowed=["households_or_persons"],
            extra_rule="Mẫu 3 có 2 dòng cho mỗi địa bàn: Hộ và Nhân khẩu; unit luôn là households_or_persons.",
        )
        plan, plan_warnings = _validate_column_mapping_plan_generic(parsed, template_id=3, plan_type=plan_type, default_plan=MAU3_DEFAULT_COLUMN_PLAN, allowed_facts=MAU3_ALLOWED_COLUMN_FACTS, source="llm", raw_error=error)
        debug.update({"raw_llm_text": raw, "prompt_payload": payload, "llm_error": error, "llm_first_raw_text": raw, "llm_first_validated_plan": plan, "llm_first_validation_warnings": list(plan_warnings)})
        warnings.extend(plan_warnings)
        debug["llm_repair_attempted"] = False
        debug["llm_repair_error"] = None
        debug["llm_repair_raw_text"] = ""
        debug["llm_repair_prompt_payload"] = None
        debug["llm_repair_validated_plan"] = None
        debug["llm_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            debug["llm_repair_attempted"] = True
            repaired, repair_raw, repair_error, repair_payload = _call_ollama_column_mapper_repair_generic(
                template_id=3, plan_type=plan_type, default_plan=MAU3_DEFAULT_COLUMN_PLAN,
                allowed_facts=MAU3_ALLOWED_COLUMN_FACTS, first_raw_text=raw, first_validation_warnings=list(plan_warnings),
            )
            repaired_plan, repaired_warnings = _validate_column_mapping_plan_generic(repaired, template_id=3, plan_type=plan_type, default_plan=MAU3_DEFAULT_COLUMN_PLAN, allowed_facts=MAU3_ALLOWED_COLUMN_FACTS, source="llm_repair", raw_error=repair_error)
            debug.update({"llm_repair_error": repair_error, "llm_repair_raw_text": repair_raw, "llm_repair_prompt_payload": repair_payload, "llm_repair_validated_plan": repaired_plan, "llm_repair_validation_warnings": list(repaired_warnings)})
            if int(repaired_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                warnings.append(f"LLM repair mẫu 3 cải thiện mapping: fallback_count {plan.get('fallback_count')} -> {repaired_plan.get('fallback_count')}.")
                warnings.extend(repaired_warnings)
                plan = repaired_plan
                debug["raw_llm_text"] = repair_raw
                debug["prompt_payload"] = repair_payload
                debug["llm_error"] = repair_error
            else:
                warnings.append("LLM repair mẫu 3 không cải thiện mapping; giữ plan tốt nhất hiện có.")
                warnings.extend(repaired_warnings)
        debug["llm_targeted_repair_attempted"] = False
        debug["llm_targeted_repair_columns"] = []
        debug["llm_targeted_repair_error"] = None
        debug["llm_targeted_repair_raw_text"] = ""
        debug["llm_targeted_repair_prompt_payload"] = None
        debug["llm_targeted_repair_validated_plan"] = None
        debug["llm_targeted_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            bad_cols = _fallback_columns_from_validated_plan_generic(plan)
            if not bad_cols:
                # Safety net: nếu validator báo còn fallback nhưng không suy ra được cột
                # nào, targeted repair toàn bộ cột của mẫu. Trường hợp này xảy ra khi
                # LLM trả văn bản thay vì JSON và plan rơi vào fallback_all.
                bad_cols = [str(item.get("column") or "").strip().upper() for item in MAU3_DEFAULT_COLUMN_PLAN if item.get("column")]
            if bad_cols:
                debug["llm_targeted_repair_attempted"] = True
                debug["llm_targeted_repair_columns"] = list(bad_cols)
                targeted, targeted_raw, targeted_error, targeted_payload = _call_ollama_column_mapper_targeted_repair_generic(
                    template_id=3,
                    plan_type=plan_type,
                    default_plan=MAU3_DEFAULT_COLUMN_PLAN,
                    bad_columns=bad_cols,
                    previous_raw_text=str(debug.get("raw_llm_text") or raw or ""),
                    previous_warnings=list(warnings),
                )
                debug["llm_targeted_repair_error"] = targeted_error
                debug["llm_targeted_repair_raw_text"] = targeted_raw
                debug["llm_targeted_repair_prompt_payload"] = targeted_payload
                combined = _combine_column_mapping_plan_with_patch_generic(
                    template_id=3,
                    plan_type=plan_type,
                    default_plan=MAU3_DEFAULT_COLUMN_PLAN,
                    base_plan=plan,
                    patch_plan=targeted,
                )
                targeted_plan, targeted_warnings = _validate_column_mapping_plan_generic(
                    combined,
                    template_id=3,
                    plan_type=plan_type,
                    default_plan=MAU3_DEFAULT_COLUMN_PLAN,
                    allowed_facts=MAU3_ALLOWED_COLUMN_FACTS,
                    source="llm_targeted_repair",
                    raw_error=targeted_error,
                )
                debug["llm_targeted_repair_validated_plan"] = targeted_plan
                debug["llm_targeted_repair_validation_warnings"] = list(targeted_warnings)
                if int(targeted_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                    old_fallback = int(plan.get("fallback_count") or 0)
                    plan = targeted_plan
                    warnings.append(f"LLM targeted repair mẫu 3 cải thiện mapping: fallback_count {old_fallback} -> {plan.get('fallback_count')}.")
                    warnings.extend(targeted_warnings)
                    debug["raw_llm_text"] = targeted_raw
                    debug["prompt_payload"] = targeted_payload
                    debug["llm_error"] = targeted_error
                else:
                    warnings.append("LLM targeted repair mẫu 3 không cải thiện mapping; giữ plan tốt nhất hiện có.")
                    warnings.extend(targeted_warnings)
        debug["llm_final_full_match"] = int(plan.get("fallback_count") or 0) == 0 and str(plan.get("validation_status")) in {"llm_validated", "llm_repair_validated", "llm_targeted_repair_validated"}
    else:
        plan = _default_column_plan_generic(template_id=3, plan_type=plan_type, default_plan=MAU3_DEFAULT_COLUMN_PLAN, reason="llm_disabled_or_context_error_fallback")
        warnings.append("LLM bị tắt hoặc không đọc được context; dùng mapping deterministic cho mẫu 3.")
        debug["llm_final_full_match"] = False

    other_reason_available = _movement_other_reason_available()
    debug["other_reason_available"] = other_reason_available
    debug["movement_other_policy"] = "use_explicit_reason_columns" if other_reason_available else "zero_without_explicit_reason"
    if not other_reason_available:
        warnings.append(MOVEMENT_OTHER_NO_REASON_WARNING)

    debug["validated_plan"] = plan
    debug["validation_warnings"] = list(warnings)
    expected_by_col = {item["column"]: item for item in MAU3_DEFAULT_COLUMN_PLAN}
    debug["final_mapping_correct_by_schema"] = all(str(m.get("fact_key")) == str(expected_by_col.get(str(m.get("column")), {}).get("fact_key")) and str(m.get("unit")) == str(expected_by_col.get(str(m.get("column")), {}).get("unit")) for m in plan.get("column_mappings") or [])
    debug["final_mapping_source"] = plan.get("source")
    debug["final_mapping_validation_status"] = plan.get("validation_status")

    template_path = _find_template_sample_path(3, samples_root)
    if template_path is None:
        raise FileNotFoundError("Không tìm thấy file template mẫu 3 trong data/report_samples.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb = load_workbook(template_path)
    ws = wb.active
    area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in MAU3_DEFAULT_COLUMN_PLAN:
        col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen: str | None = None
    current_area_info: dict[str, Any] | None = None
    filled_rows: list[dict[str, Any]] = []
    filled_cell_count = 0
    for r in range(12, (ws.max_row or 12) + 1):
        unit_text = str(ws.cell(r, 3).value or "").strip()
        unit_key = _vn_key(unit_text)
        if unit_key not in {"ho", "nhan khau"}:
            continue
        label_text = str(ws.cell(r, 2).value or "").strip()
        tt_text = str(ws.cell(r, 1).value or "").strip()
        if unit_key == "ho":
            row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
            if row_type == "district" and row_huyen:
                current_huyen = row_huyen
            current_area_info = {"row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "label": label_text, "tt": tt_text}
        elif current_area_info:
            row_type = current_area_info.get("row_type")
            row_huyen = current_area_info.get("huyen")
            row_xa = current_area_info.get("xa_phuong")
            label_text = str(current_area_info.get("label") or label_text)
            tt_text = str(current_area_info.get("tt") or tt_text)
        else:
            row_type = row_huyen = row_xa = None
        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text, "phan_to": unit_text})
            continue
        in_scope = not (huyen and row_huyen != huyen)
        metrics = _mau3_compute_metrics(year, row_huyen, row_xa) if in_scope else {item["fact_key"]: _mau2_metric_pair(0, 0) for item in MAU3_DEFAULT_COLUMN_PLAN}
        metric_unit = "people" if unit_key == "nhan khau" else "households"
        sample_values: dict[str, Any] = {}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell):
                continue
            value = int((metrics.get(fact_key) or {}).get(metric_unit) or 0)
            cell.value = value
            cell.number_format = "#,##0"
            filled_cell_count += 1
            sample_values[col] = value
        filled_rows.append({"row": r, "label": label_text, "row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "phan_to": unit_text, "in_scope": in_scope, "values_sample_D_to_L": {k: sample_values.get(k) for k in ["D", "E", "F", "G", "H", "I", "J", "K", "L"]}})
    bio = BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content = bio.getvalue()
    debug["filled_cell_count"] = filled_cell_count
    debug["filled_rows"] = filled_rows[:220]
    debug["filled_rows_total"] = len(filled_rows)
    debug["template_path"] = _relative_or_str(template_path)
    debug["output_bytes"] = len(content)
    debug["limitations"] = [] if debug.get("other_reason_available") else [MOVEMENT_OTHER_NO_REASON_WARNING]
    debug["data_mapping_notes"] = ["Mẫu 3 dùng bien_dong_dau_ky để tính các cột diễn biến E/F/G/H/I/J/K.", "Cột G/K chỉ dùng khi DB có cột lý do biến động chi tiết.", "Cột L cuối kỳ được tính theo công thức D - E - F - G + H + I + J + K."]
    log_path = write_jsonl_log("llm_excel_mau3", debug) if write_jsonl_log is not None else None
    debug["log_path"] = log_path
    return {"content": content, "warnings": warnings, "debug": debug, "log_path": log_path, "plan": plan}


def export_mau3_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_mau3_xlsx_real_llm_assisted(year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir)


# ── Mẫu 4/5: Thiếu hụt DVXHCB hộ nghèo - số lượng/tỷ lệ ─────────────────────

DEPRIVATION_INDICATOR_PLAN = [
    ("th_viec_lam", "Thiếu hụt chỉ số 1 - việc làm"),
    ("th_bhxh", "Thiếu hụt chỉ số 2 - bảo hiểm xã hội"),
    ("th_bhyt", "Thiếu hụt chỉ số 3 - bảo hiểm y tế"),
    ("th_dinh_duong", "Thiếu hụt chỉ số 4 - dinh dưỡng"),
    ("th_giao_duc_nguoi_lon", "Thiếu hụt chỉ số 5 - giáo dục người lớn"),
    ("th_di_hoc_tre_em", "Thiếu hụt chỉ số 6 - tình trạng đi học của trẻ em"),
    ("th_chat_luong_nha", "Thiếu hụt chỉ số 7 - chất lượng nhà ở"),
    ("th_dien_tich_nha", "Thiếu hụt chỉ số 8 - diện tích nhà ở"),
    ("th_nuoc_sach", "Thiếu hụt chỉ số 9 - nước sinh hoạt"),
    ("th_nha_tieu", "Thiếu hụt chỉ số 10 - nhà tiêu hợp vệ sinh"),
    ("th_vien_thong", "Thiếu hụt chỉ số 11 - dịch vụ viễn thông"),
    ("th_tai_san_tt", "Thiếu hụt chỉ số 12 - phương tiện tiếp cận thông tin"),
]
DEPRIVATION_ALLOWED_FACTS = {"poor_households", "total_deprivations"} | {k for k, _ in DEPRIVATION_INDICATOR_PLAN} | {f"{k}_ratio" for k, _ in DEPRIVATION_INDICATOR_PLAN}

MAU4_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "poor_households", "unit": "households", "reason": "Tổng số hộ nghèo"},
    {"column": "D", "fact_key": "total_deprivations", "unit": "count", "reason": "Tổng số thiếu hụt của hộ nghèo"},
] + [
    {"column": col, "fact_key": key, "unit": "count", "reason": reason}
    for col, (key, reason) in zip(list("EFGHIJKLMNOP"), DEPRIVATION_INDICATOR_PLAN)
]

MAU5_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "poor_households", "unit": "households", "reason": "Tổng số hộ nghèo"},
] + [
    {"column": col, "fact_key": f"{key}_ratio", "unit": "percent", "reason": f"Tỷ lệ {reason.lower()} trên tổng số hộ nghèo"}
    for col, (key, reason) in zip(list("DEFGHIJKLMNO"), DEPRIVATION_INDICATOR_PLAN)
]


def _deprivation_sum_metrics(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str = "Hộ nghèo") -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if year:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if xa_phuong:
        clauses.append("xa_phuong = ?")
        params.append(xa_phuong)
    clauses.append("phan_loai = ?")
    params.append(phan_loai)
    where = " WHERE " + " AND ".join(clauses)
    fields = [key for key, _ in DEPRIVATION_INDICATOR_PLAN]
    select_expr = "COUNT(*), " + ", ".join([f"COALESCE(SUM({field}),0)" for field in fields])
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(f"SELECT {select_expr} FROM ho_ngheo{where}", params).fetchone()
    poor_households = int(row[0] or 0)
    values = {field: int(row[i + 1] or 0) for i, field in enumerate(fields)}
    total = sum(values.values())
    metrics: dict[str, Any] = {"poor_households": poor_households, "total_deprivations": total}
    metrics.update(values)
    for field in fields:
        metrics[f"{field}_ratio"] = round((values[field] / poor_households * 100), 2) if poor_households else 0.0
    return metrics


def _export_deprivation_xlsx_real_llm_assisted(*, template_id: int, year: int | None, huyen: str | None, use_llm: bool, samples_dir: Path | None = None) -> dict[str, Any]:
    if template_id == 4:
        default_plan = MAU4_DEFAULT_COLUMN_PLAN
        plan_type = "mau4_column_fact_mapping"
        start_col, end_col = 3, 16  # C:P
        title_row_max, header_start, header_end, data_start = 6, 8, 9, 10
        log_name = "llm_excel_mau4"
        event = "mau4_real_llm_excel_export"
        sample_key = "values_sample_C_to_P"
        sample_cols = list("CDEFGHIJKLMNOP")
    elif template_id == 5:
        default_plan = MAU5_DEFAULT_COLUMN_PLAN
        plan_type = "mau5_column_fact_mapping"
        start_col, end_col = 3, 15  # C:O
        title_row_max, header_start, header_end, data_start = 6, 8, 9, 10
        log_name = "llm_excel_mau5"
        event = "mau5_real_llm_excel_export"
        sample_key = "values_sample_C_to_O"
        sample_cols = list("CDEFGHIJKLMNO")
    else:
        raise ValueError("Chỉ hỗ trợ template_id 4 hoặc 5.")
    samples_root = samples_dir or DATA_SAMPLES_DIR
    debug: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": event,
        "template_id": template_id,
        "year": year,
        "huyen": huyen,
        "use_llm": bool(use_llm),
        "llm_attempted": False,
        "llm_error": None,
    }
    warnings: list[str] = []
    header_context = _extract_header_context_for_llm_generic(
        template_id=template_id, start_col=start_col, end_col=end_col, title_row_max=title_row_max,
        header_row_start=header_start, header_row_end=header_end, data_row_start=data_start, data_row_max_preview=42,
        default_plan=default_plan, allowed_facts=DEPRIVATION_ALLOWED_FACTS, samples_dir=samples_root,
    )
    debug["header_context"] = header_context
    if use_llm and header_context.get("ok"):
        debug["llm_attempted"] = True
        parsed, raw, error, payload = _call_ollama_column_mapper_generic(
            header_context, template_id=template_id, plan_type=plan_type, default_plan=default_plan,
            allowed_facts=DEPRIVATION_ALLOWED_FACTS, unit_values_allowed=sorted({item["unit"] for item in default_plan}),
            extra_rule="Mẫu thiếu hụt hộ nghèo: cột tổng hộ là households, cột số lượng là count, cột tỷ lệ là percent; không sinh số liệu.",
        )
        plan, plan_warnings = _validate_column_mapping_plan_generic(parsed, template_id=template_id, plan_type=plan_type, default_plan=default_plan, allowed_facts=DEPRIVATION_ALLOWED_FACTS, source="llm", raw_error=error)
        debug.update({"raw_llm_text": raw, "prompt_payload": payload, "llm_error": error, "llm_first_raw_text": raw, "llm_first_validated_plan": plan, "llm_first_validation_warnings": list(plan_warnings)})
        warnings.extend(plan_warnings)
        debug["llm_repair_attempted"] = False
        debug["llm_repair_error"] = None
        debug["llm_repair_raw_text"] = ""
        debug["llm_repair_prompt_payload"] = None
        debug["llm_repair_validated_plan"] = None
        debug["llm_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            debug["llm_repair_attempted"] = True
            repaired, repair_raw, repair_error, repair_payload = _call_ollama_column_mapper_repair_generic(
                template_id=template_id, plan_type=plan_type, default_plan=default_plan,
                allowed_facts=DEPRIVATION_ALLOWED_FACTS, first_raw_text=raw, first_validation_warnings=list(plan_warnings),
            )
            repaired_plan, repaired_warnings = _validate_column_mapping_plan_generic(repaired, template_id=template_id, plan_type=plan_type, default_plan=default_plan, allowed_facts=DEPRIVATION_ALLOWED_FACTS, source="llm_repair", raw_error=repair_error)
            debug.update({"llm_repair_error": repair_error, "llm_repair_raw_text": repair_raw, "llm_repair_prompt_payload": repair_payload, "llm_repair_validated_plan": repaired_plan, "llm_repair_validation_warnings": list(repaired_warnings)})
            if int(repaired_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                warnings.append(f"LLM repair mẫu {template_id} cải thiện mapping: fallback_count {plan.get('fallback_count')} -> {repaired_plan.get('fallback_count')}.")
                warnings.extend(repaired_warnings)
                plan = repaired_plan
                debug["raw_llm_text"] = repair_raw
                debug["prompt_payload"] = repair_payload
                debug["llm_error"] = repair_error
            else:
                warnings.append(f"LLM repair mẫu {template_id} không cải thiện mapping; giữ plan tốt nhất hiện có.")
                warnings.extend(repaired_warnings)
        debug["llm_targeted_repair_attempted"] = False
        debug["llm_targeted_repair_columns"] = []
        debug["llm_targeted_repair_error"] = None
        debug["llm_targeted_repair_raw_text"] = ""
        debug["llm_targeted_repair_prompt_payload"] = None
        debug["llm_targeted_repair_validated_plan"] = None
        debug["llm_targeted_repair_validation_warnings"] = []
        if int(plan.get("fallback_count") or 0) > 0:
            bad_cols = _fallback_columns_from_validated_plan_generic(plan)
            if not bad_cols:
                # Safety net: nếu validator báo còn fallback nhưng không suy ra được cột
                # nào, targeted repair toàn bộ cột của mẫu. Trường hợp này xảy ra khi
                # LLM trả văn bản thay vì JSON và plan rơi vào fallback_all.
                bad_cols = [str(item.get("column") or "").strip().upper() for item in default_plan if item.get("column")]
            if bad_cols:
                debug["llm_targeted_repair_attempted"] = True
                debug["llm_targeted_repair_columns"] = list(bad_cols)
                targeted, targeted_raw, targeted_error, targeted_payload = _call_ollama_column_mapper_targeted_repair_generic(
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    bad_columns=bad_cols,
                    previous_raw_text=str(debug.get("raw_llm_text") or raw or ""),
                    previous_warnings=list(warnings),
                )
                debug["llm_targeted_repair_error"] = targeted_error
                debug["llm_targeted_repair_raw_text"] = targeted_raw
                debug["llm_targeted_repair_prompt_payload"] = targeted_payload
                combined = _combine_column_mapping_plan_with_patch_generic(
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    base_plan=plan,
                    patch_plan=targeted,
                )
                targeted_plan, targeted_warnings = _validate_column_mapping_plan_generic(
                    combined,
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    allowed_facts=MAU3_ALLOWED_COLUMN_FACTS,
                    source="llm_targeted_repair",
                    raw_error=targeted_error,
                )
                debug["llm_targeted_repair_validated_plan"] = targeted_plan
                debug["llm_targeted_repair_validation_warnings"] = list(targeted_warnings)
                if int(targeted_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                    old_fallback = int(plan.get("fallback_count") or 0)
                    plan = targeted_plan
                    warnings.append(f"LLM targeted repair mẫu {template_id} cải thiện mapping: fallback_count {old_fallback} -> {plan.get('fallback_count')}.")
                    warnings.extend(targeted_warnings)
                    debug["raw_llm_text"] = targeted_raw
                    debug["prompt_payload"] = targeted_payload
                    debug["llm_error"] = targeted_error
                else:
                    warnings.append(f"LLM targeted repair mẫu {template_id} không cải thiện mapping; giữ plan tốt nhất hiện có.")
                    warnings.extend(targeted_warnings)
        debug["llm_final_full_match"] = int(plan.get("fallback_count") or 0) == 0 and str(plan.get("validation_status")) in {"llm_validated", "llm_repair_validated", "llm_targeted_repair_validated"}
    else:
        plan = _default_column_plan_generic(template_id=template_id, plan_type=plan_type, default_plan=default_plan, reason="llm_disabled_or_context_error_fallback")
        warnings.append(f"LLM bị tắt hoặc không đọc được context; dùng mapping deterministic cho mẫu {template_id}.")
        debug["llm_final_full_match"] = False

    debug["validated_plan"] = plan
    debug["validation_warnings"] = list(warnings)
    expected_by_col = {item["column"]: item for item in default_plan}
    debug["final_mapping_correct_by_schema"] = all(str(m.get("fact_key")) == str(expected_by_col.get(str(m.get("column")), {}).get("fact_key")) and str(m.get("unit")) == str(expected_by_col.get(str(m.get("column")), {}).get("unit")) for m in plan.get("column_mappings") or [])
    debug["final_mapping_source"] = plan.get("source")
    debug["final_mapping_validation_status"] = plan.get("validation_status")

    template_path = _find_template_sample_path(template_id, samples_root)
    if template_path is None:
        raise FileNotFoundError(f"Không tìm thấy file template mẫu {template_id} trong data/report_samples.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb = load_workbook(template_path)
    ws = wb.active
    area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in default_plan:
        col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen: str | None = None
    filled_rows: list[dict[str, Any]] = []
    filled_cell_count = 0
    for r in range(data_start, (ws.max_row or data_start) + 1):
        label_text = str(ws.cell(r, 2).value or "").strip()
        tt_text = str(ws.cell(r, 1).value or "").strip()
        if not label_text:
            continue
        row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
        if row_type == "district" and row_huyen:
            current_huyen = row_huyen
        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text})
            continue
        in_scope = not (huyen and row_huyen != huyen)
        metrics = _deprivation_sum_metrics(year, row_huyen, row_xa, phan_loai="Hộ nghèo") if in_scope else {item["fact_key"]: 0 for item in default_plan}
        sample_values: dict[str, Any] = {}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell):
                continue
            value = metrics.get(fact_key, 0)
            cell.value = value
            if str(fact_key).endswith("_ratio"):
                cell.number_format = "0.00"
            else:
                cell.number_format = "#,##0"
            filled_cell_count += 1
            sample_values[col] = value
        filled_rows.append({"row": r, "label": label_text, "row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "in_scope": in_scope, sample_key: {k: sample_values.get(k) for k in sample_cols}})
    bio = BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content = bio.getvalue()
    debug["filled_cell_count"] = filled_cell_count
    debug["filled_rows"] = filled_rows[:120]
    debug["filled_rows_total"] = len(filled_rows)
    debug["template_path"] = _relative_or_str(template_path)
    debug["output_bytes"] = len(content)
    debug["limitations"] = []
    debug["data_mapping_notes"] = ["Mẫu 4/5 dùng phan_loai = 'Hộ nghèo'.", "12 chỉ số thiếu hụt lấy từ các cột th_* trong DB.", "Mẫu 5 tính tỷ lệ = số hộ thiếu chỉ số / tổng số hộ nghèo * 100."]
    log_path = write_jsonl_log(log_name, debug) if write_jsonl_log is not None else None
    debug["log_path"] = log_path
    return {"content": content, "warnings": warnings, "debug": debug, "log_path": log_path, "plan": plan}


def export_mau4_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_deprivation_xlsx_real_llm_assisted(template_id=4, year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir)


def export_mau5_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_deprivation_xlsx_real_llm_assisted(template_id=5, year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Mẫu 6-12: bổ sung luồng LLM ánh xạ cột, Python validate + tính số + ghi Excel.
# Ghi chú: LLM chỉ làm mapping cột -> fact_key; số liệu luôn do Python tính từ DB.


def _run_llm_mapping_pipeline_generic(
    *,
    template_id: int,
    plan_type: str,
    default_plan: list[dict[str, Any]],
    allowed_facts: set[str],
    header_context: dict[str, Any],
    use_llm: bool,
    unit_values_allowed: list[str],
    extra_rule: str,
    debug: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    """Pipeline LLM chung cho các mẫu mới.

    Luồng: initial -> full repair -> targeted repair. Nếu LLM lỗi thì fallback deterministic.
    """
    if use_llm and header_context.get("ok"):
        debug["llm_attempted"] = True
        parsed, raw, error, payload = _call_ollama_column_mapper_generic(
            header_context,
            template_id=template_id,
            plan_type=plan_type,
            default_plan=default_plan,
            allowed_facts=allowed_facts,
            unit_values_allowed=unit_values_allowed,
            extra_rule=extra_rule,
        )
        plan, plan_warnings = _validate_column_mapping_plan_generic(
            parsed,
            template_id=template_id,
            plan_type=plan_type,
            default_plan=default_plan,
            allowed_facts=allowed_facts,
            source="llm",
            raw_error=error,
        )
        debug.update({
            "raw_llm_text": raw,
            "prompt_payload": payload,
            "llm_error": error,
            "llm_first_raw_text": raw,
            "llm_first_validated_plan": plan,
            "llm_first_validation_warnings": list(plan_warnings),
            "llm_repair_attempted": False,
            "llm_repair_error": None,
            "llm_repair_raw_text": "",
            "llm_repair_prompt_payload": None,
            "llm_repair_validated_plan": None,
            "llm_repair_validation_warnings": [],
            "llm_targeted_repair_attempted": False,
            "llm_targeted_repair_columns": [],
            "llm_targeted_repair_error": None,
            "llm_targeted_repair_raw_text": "",
            "llm_targeted_repair_prompt_payload": None,
            "llm_targeted_repair_validated_plan": None,
            "llm_targeted_repair_validation_warnings": [],
        })
        warnings.extend(plan_warnings)

        if int(plan.get("fallback_count") or 0) > 0:
            debug["llm_repair_attempted"] = True
            repaired, repair_raw, repair_error, repair_payload = _call_ollama_column_mapper_repair_generic(
                template_id=template_id,
                plan_type=plan_type,
                default_plan=default_plan,
                allowed_facts=allowed_facts,
                first_raw_text=raw,
                first_validation_warnings=list(plan_warnings),
            )
            repaired_plan, repaired_warnings = _validate_column_mapping_plan_generic(
                repaired,
                template_id=template_id,
                plan_type=plan_type,
                default_plan=default_plan,
                allowed_facts=allowed_facts,
                source="llm_repair",
                raw_error=repair_error,
            )
            debug.update({
                "llm_repair_error": repair_error,
                "llm_repair_raw_text": repair_raw,
                "llm_repair_prompt_payload": repair_payload,
                "llm_repair_validated_plan": repaired_plan,
                "llm_repair_validation_warnings": list(repaired_warnings),
            })
            if int(repaired_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                warnings.append(f"LLM repair mẫu {template_id} cải thiện mapping: fallback_count {plan.get('fallback_count')} -> {repaired_plan.get('fallback_count')}.")
                warnings.extend(repaired_warnings)
                plan = repaired_plan
                debug["raw_llm_text"] = repair_raw
                debug["prompt_payload"] = repair_payload
                debug["llm_error"] = repair_error
            else:
                warnings.append(f"LLM repair mẫu {template_id} không cải thiện mapping; giữ plan tốt nhất hiện có.")
                warnings.extend(repaired_warnings)

        if int(plan.get("fallback_count") or 0) > 0:
            bad_cols = _fallback_columns_from_validated_plan_generic(plan)
            if not bad_cols:
                # Safety net: nếu validator báo còn fallback nhưng không suy ra được cột
                # nào, targeted repair toàn bộ cột của mẫu. Trường hợp này xảy ra khi
                # LLM trả văn bản thay vì JSON và plan rơi vào fallback_all.
                bad_cols = [str(item.get("column") or "").strip().upper() for item in default_plan if item.get("column")]
            if bad_cols:
                debug["llm_targeted_repair_attempted"] = True
                debug["llm_targeted_repair_columns"] = list(bad_cols)
                targeted, targeted_raw, targeted_error, targeted_payload = _call_ollama_column_mapper_targeted_repair_generic(
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    bad_columns=bad_cols,
                    previous_raw_text=str(debug.get("raw_llm_text") or raw or ""),
                    previous_warnings=list(warnings),
                )
                combined = _combine_column_mapping_plan_with_patch_generic(
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    base_plan=plan,
                    patch_plan=targeted,
                )
                targeted_plan, targeted_warnings = _validate_column_mapping_plan_generic(
                    combined,
                    template_id=template_id,
                    plan_type=plan_type,
                    default_plan=default_plan,
                    allowed_facts=allowed_facts,
                    source="llm_targeted_repair",
                    raw_error=targeted_error,
                )
                debug.update({
                    "llm_targeted_repair_error": targeted_error,
                    "llm_targeted_repair_raw_text": targeted_raw,
                    "llm_targeted_repair_prompt_payload": targeted_payload,
                    "llm_targeted_repair_validated_plan": targeted_plan,
                    "llm_targeted_repair_validation_warnings": list(targeted_warnings),
                })
                if int(targeted_plan.get("fallback_count") or 0) < int(plan.get("fallback_count") or 0):
                    old_fallback = int(plan.get("fallback_count") or 0)
                    plan = targeted_plan
                    warnings.append(f"LLM targeted repair mẫu {template_id} cải thiện mapping: fallback_count {old_fallback} -> {plan.get('fallback_count')}.")
                    warnings.extend(targeted_warnings)
                    debug["raw_llm_text"] = targeted_raw
                    debug["prompt_payload"] = targeted_payload
                    debug["llm_error"] = targeted_error
                else:
                    warnings.append(f"LLM targeted repair mẫu {template_id} không cải thiện mapping; giữ plan tốt nhất hiện có.")
                    warnings.extend(targeted_warnings)
        debug["llm_final_full_match"] = int(plan.get("fallback_count") or 0) == 0 and str(plan.get("validation_status")) in {"llm_validated", "llm_repair_validated", "llm_targeted_repair_validated"}
        return plan

    plan = _default_column_plan_generic(template_id=template_id, plan_type=plan_type, default_plan=default_plan, reason="llm_disabled_or_context_error_fallback")
    warnings.append(f"LLM bị tắt hoặc không đọc được context; dùng mapping deterministic cho mẫu {template_id}.")
    debug["llm_final_full_match"] = False
    return plan


def _finish_plan_debug_generic(debug: dict[str, Any], warnings: list[str], plan: dict[str, Any], default_plan: list[dict[str, Any]]) -> None:
    debug["validated_plan"] = plan
    debug["validation_warnings"] = list(warnings)
    expected_by_col = {str(item["column"]): item for item in default_plan}
    debug["final_mapping_correct_by_schema"] = all(
        str(m.get("fact_key")) == str(expected_by_col.get(str(m.get("column")), {}).get("fact_key"))
        and str(m.get("unit")) == str(expected_by_col.get(str(m.get("column")), {}).get("unit"))
        for m in plan.get("column_mappings") or []
    )
    debug["final_mapping_source"] = plan.get("source")
    debug["final_mapping_validation_status"] = plan.get("validation_status")


def _sqlite_where(year: int | None, huyen: str | None, xa_phuong: str | None, extra: list[str] | None = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if year:
        clauses.append("nam = ?"); params.append(int(year))
    if huyen:
        clauses.append("huyen = ?"); params.append(huyen)
    if xa_phuong:
        clauses.append("xa_phuong = ?"); params.append(xa_phuong)
    for item in extra or []:
        clauses.append(item)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _count_and_people(year: int | None, huyen: str | None, xa_phuong: str | None, *, extra: list[str] | None = None) -> tuple[int, int]:
    where, params = _sqlite_where(year, huyen, xa_phuong, extra)
    with sqlite3.connect(DB_PATH) as conn:
        hh, people = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(so_nhan_khau),0) FROM ho_ngheo{where}", params).fetchone()
    return int(hh or 0), int(people or 0)


def _sum_children_fields(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str) -> dict[str, int]:
    where, params = _sqlite_where(year, huyen, xa_phuong, ["phan_loai = ?"])
    params.append(phan_loai)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(so_tre_em),0),
                   COALESCE(SUM(so_tre_thieu_bhyt),0),
                   COALESCE(SUM(so_tre_thieu_dinh_duong),0),
                   COALESCE(SUM(so_tre_thieu_di_hoc),0)
            FROM ho_ngheo{where}
            """,
            params,
        ).fetchone()
    return {
        "children_total": int(row[0] or 0),
        "children_bhyt": int(row[1] or 0),
        "children_dinh_duong": int(row[2] or 0),
        "children_di_hoc": int(row[3] or 0),
    }


# ── Mẫu 6/7: Thiếu hụt DVXHCB hộ cận nghèo - số lượng/tỷ lệ ────────────────

NEAR_POOR_DEPRIVATION_ALLOWED_FACTS = {"near_poor_households", "total_deprivations"} | {k for k, _ in DEPRIVATION_INDICATOR_PLAN} | {f"{k}_ratio" for k, _ in DEPRIVATION_INDICATOR_PLAN}

MAU6_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "near_poor_households", "unit": "households", "reason": "Tổng số hộ cận nghèo"},
    {"column": "D", "fact_key": "total_deprivations", "unit": "count", "reason": "Tổng số thiếu hụt của hộ cận nghèo"},
] + [
    {"column": col, "fact_key": key, "unit": "count", "reason": reason.replace("Thiếu hụt", "Thiếu hụt")}
    for col, (key, reason) in zip(list("EFGHIJKLMNOP"), DEPRIVATION_INDICATOR_PLAN)
]

MAU7_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "near_poor_households", "unit": "households", "reason": "Tổng số hộ cận nghèo"},
] + [
    {"column": col, "fact_key": f"{key}_ratio", "unit": "percent", "reason": f"Tỷ lệ {reason.lower()} trên tổng số hộ cận nghèo"}
    for col, (key, reason) in zip(list("DEFGHIJKLMNO"), DEPRIVATION_INDICATOR_PLAN)
]


def _near_poor_deprivation_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, Any]:
    raw = _deprivation_sum_metrics(year, huyen, xa_phuong, phan_loai="Hộ cận nghèo")
    raw["near_poor_households"] = raw.pop("poor_households", 0)
    return raw


def _export_deprivation_nearpoor_xlsx_real_llm_assisted(*, template_id: int, year: int | None, huyen: str | None, use_llm: bool, samples_dir: Path | None = None) -> dict[str, Any]:
    if template_id == 6:
        default_plan = MAU6_DEFAULT_COLUMN_PLAN; plan_type = "mau6_column_fact_mapping"
        start_col, end_col = 3, 16; data_start = 10; log_name = "llm_excel_mau6"; event = "mau6_real_llm_excel_export"; sample_key = "values_sample_C_to_P"; sample_cols = list("CDEFGHIJKLMNOP")
    elif template_id == 7:
        default_plan = MAU7_DEFAULT_COLUMN_PLAN; plan_type = "mau7_column_fact_mapping"
        start_col, end_col = 3, 15; data_start = 10; log_name = "llm_excel_mau7"; event = "mau7_real_llm_excel_export"; sample_key = "values_sample_C_to_O"; sample_cols = list("CDEFGHIJKLMNO")
    else:
        raise ValueError("Chỉ hỗ trợ template_id 6 hoặc 7.")
    samples_root = samples_dir or DATA_SAMPLES_DIR
    debug: dict[str, Any] = {"timestamp": datetime.now().astimezone().isoformat(), "event": event, "template_id": template_id, "year": year, "huyen": huyen, "use_llm": bool(use_llm), "llm_attempted": False, "llm_error": None}
    warnings: list[str] = []
    header_context = _extract_header_context_for_llm_generic(template_id=template_id, start_col=start_col, end_col=end_col, title_row_max=6, header_row_start=8, header_row_end=9, data_row_start=data_start, data_row_max_preview=42, default_plan=default_plan, allowed_facts=NEAR_POOR_DEPRIVATION_ALLOWED_FACTS, samples_dir=samples_root)
    debug["header_context"] = header_context
    plan = _run_llm_mapping_pipeline_generic(template_id=template_id, plan_type=plan_type, default_plan=default_plan, allowed_facts=NEAR_POOR_DEPRIVATION_ALLOWED_FACTS, header_context=header_context, use_llm=use_llm, unit_values_allowed=sorted({item["unit"] for item in default_plan}), extra_rule="Mẫu 6/7 dùng phan_loai = 'Hộ cận nghèo'; cột số lượng là count, cột tỷ lệ là percent.", debug=debug, warnings=warnings)
    _finish_plan_debug_generic(debug, warnings, plan, default_plan)
    template_path = _find_template_sample_path(template_id, samples_root)
    if template_path is None:
        raise FileNotFoundError(f"Không tìm thấy file template mẫu {template_id}.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb = load_workbook(template_path); ws = wb.active
    area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in default_plan: col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen = None; filled_rows = []; filled_cell_count = 0
    for r in range(data_start, (ws.max_row or data_start) + 1):
        label_text = str(ws.cell(r, 2).value or "").strip(); tt_text = str(ws.cell(r, 1).value or "").strip()
        if not label_text: continue
        row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
        if row_type == "district" and row_huyen: current_huyen = row_huyen
        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text}); continue
        in_scope = not (huyen and row_huyen != huyen)
        metrics = _near_poor_deprivation_metrics(year, row_huyen, row_xa) if in_scope else {item["fact_key"]: 0 for item in default_plan}
        sample_values = {}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell): continue
            value = metrics.get(fact_key, 0)
            cell.value = value
            cell.number_format = "0.00" if str(fact_key).endswith("_ratio") else "#,##0"
            filled_cell_count += 1; sample_values[col] = value
        filled_rows.append({"row": r, "label": label_text, "row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "in_scope": in_scope, sample_key: {k: sample_values.get(k) for k in sample_cols}})
    if template_id == 7:
        _normalize_mau7_header(ws)
    bio = BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content = bio.getvalue()
    debug.update({"filled_cell_count": filled_cell_count, "filled_rows": filled_rows[:140], "filled_rows_total": len(filled_rows), "template_path": _relative_or_str(template_path), "output_bytes": len(content), "limitations": [], "data_mapping_notes": ["Mẫu 6/7 dùng phan_loai = 'Hộ cận nghèo'.", "12 chỉ số thiếu hụt lấy từ các cột th_* trong DB.", "Mẫu 7 tính tỷ lệ = số hộ cận nghèo thiếu chỉ số / tổng số hộ cận nghèo * 100."]})
    log_path = write_jsonl_log(log_name, debug) if write_jsonl_log is not None else None; debug["log_path"] = log_path
    return {"content": content, "warnings": warnings, "debug": debug, "log_path": log_path, "plan": plan}


def export_mau6_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_deprivation_nearpoor_xlsx_real_llm_assisted(template_id=6, year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir)


def export_mau7_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_deprivation_nearpoor_xlsx_real_llm_assisted(template_id=7, year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir)


# ── Mẫu 8: Nhóm đối tượng ──────────────────────────────────────────────────

MAU8_ALLOWED_FACTS = {"total_households", "ethnic_minority_households", "poor_households", "near_poor_households", "poor_ethnic_minority", "near_poor_ethnic_minority", "poor_no_work_capacity", "near_poor_no_work_capacity", "poor_meritorious", "near_poor_meritorious"}
MAU8_DEFAULT_COLUMN_PLAN = [
    {"column": "D", "fact_key": "total_households", "unit": "households_or_persons", "reason": "Tổng số hộ dân cư / nhân khẩu"},
    {"column": "E", "fact_key": "ethnic_minority_households", "unit": "households_or_persons", "reason": "Số hộ/khẩu dân tộc thiểu số"},
    {"column": "F", "fact_key": "poor_households", "unit": "households_or_persons", "reason": "Tổng số hộ/khẩu nghèo"},
    {"column": "G", "fact_key": "near_poor_households", "unit": "households_or_persons", "reason": "Tổng số hộ/khẩu cận nghèo"},
    {"column": "H", "fact_key": "poor_ethnic_minority", "unit": "households_or_persons", "reason": "Hộ/khẩu nghèo dân tộc thiểu số"},
    {"column": "I", "fact_key": "near_poor_ethnic_minority", "unit": "households_or_persons", "reason": "Hộ/khẩu cận nghèo dân tộc thiểu số"},
    {"column": "J", "fact_key": "poor_no_work_capacity", "unit": "households_or_persons", "reason": "Hộ/khẩu nghèo không có khả năng lao động"},
    {"column": "K", "fact_key": "near_poor_no_work_capacity", "unit": "households_or_persons", "reason": "Hộ/khẩu cận nghèo không có khả năng lao động"},
    {"column": "L", "fact_key": "poor_meritorious", "unit": "households_or_persons", "reason": "Hộ/khẩu nghèo có người có công"},
    {"column": "M", "fact_key": "near_poor_meritorious", "unit": "households_or_persons", "reason": "Hộ/khẩu cận nghèo có người có công"},
]


def _mau8_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, dict[str, int]]:
    return {
        "total_households": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong)),
        "ethnic_minority_households": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["dan_toc_chi_tiet <> 'Kinh'"])),
        "poor_households": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ nghèo'"])),
        "near_poor_households": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ cận nghèo'"])),
        "poor_ethnic_minority": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ nghèo'", "dan_toc_chi_tiet <> 'Kinh'"])),
        "near_poor_ethnic_minority": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ cận nghèo'", "dan_toc_chi_tiet <> 'Kinh'"])),
        "poor_no_work_capacity": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ nghèo'", "nhom_khong_knld = 1"])),
        "near_poor_no_work_capacity": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ cận nghèo'", "nhom_khong_knld = 1"])),
        "poor_meritorious": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ nghèo'", "nhom_co_cong = 1"])),
        "near_poor_meritorious": _mau2_metric_pair(*_count_and_people(year, huyen, xa_phuong, extra=["phan_loai = 'Hộ cận nghèo'", "nhom_co_cong = 1"])),
    }


def export_mau8_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    template_id = 8; plan_type = "mau8_column_fact_mapping"; samples_root = samples_dir or DATA_SAMPLES_DIR
    debug = {"timestamp": datetime.now().astimezone().isoformat(), "event": "mau8_real_llm_excel_export", "template_id": template_id, "year": year, "huyen": huyen, "use_llm": bool(use_llm), "llm_attempted": False, "llm_error": None}
    warnings: list[str] = []
    header_context = _extract_header_context_for_llm_generic(template_id=8, start_col=4, end_col=13, title_row_max=6, header_row_start=8, header_row_end=10, data_row_start=11, data_row_max_preview=44, default_plan=MAU8_DEFAULT_COLUMN_PLAN, allowed_facts=MAU8_ALLOWED_FACTS, samples_dir=samples_root)
    debug["header_context"] = header_context
    plan = _run_llm_mapping_pipeline_generic(template_id=8, plan_type=plan_type, default_plan=MAU8_DEFAULT_COLUMN_PLAN, allowed_facts=MAU8_ALLOWED_FACTS, header_context=header_context, use_llm=use_llm, unit_values_allowed=["households_or_persons"], extra_rule="Mẫu 8 có 2 dòng cho mỗi địa bàn: Hộ và Nhân khẩu; unit luôn là households_or_persons.", debug=debug, warnings=warnings)
    _finish_plan_debug_generic(debug, warnings, plan, MAU8_DEFAULT_COLUMN_PLAN)
    template_path = _find_template_sample_path(8, samples_root)
    if template_path is None: raise FileNotFoundError("Không tìm thấy file template mẫu 8.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb = load_workbook(template_path); ws = wb.active; area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in MAU8_DEFAULT_COLUMN_PLAN: col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen = None; current_area = None; filled_rows=[]; filled_cell_count=0
    for r in range(11, (ws.max_row or 11) + 1):
        unit_text = str(ws.cell(r, 3).value or "").strip(); unit_key = _vn_key(unit_text)
        if unit_key not in {"ho", "nhan khau"}: continue
        label_text = str(ws.cell(r, 2).value or "").strip(); tt_text = str(ws.cell(r, 1).value or "").strip()
        if unit_key == "ho":
            row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
            if row_type == "district" and row_huyen: current_huyen = row_huyen
            current_area = {"row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "label": label_text, "tt": tt_text}
        elif current_area:
            row_type = current_area.get("row_type"); row_huyen = current_area.get("huyen"); row_xa = current_area.get("xa_phuong"); label_text = str(current_area.get("label") or label_text); tt_text = str(current_area.get("tt") or tt_text)
        else:
            row_type = row_huyen = row_xa = None
        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text, "phan_to": unit_text}); continue
        in_scope = not (huyen and row_huyen != huyen)
        metrics = _mau8_metrics(year, row_huyen, row_xa) if in_scope else {item["fact_key"]: _mau2_metric_pair(0, 0) for item in MAU8_DEFAULT_COLUMN_PLAN}
        metric_unit = "people" if unit_key == "nhan khau" else "households"; sample_values={}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell): continue
            value = int((metrics.get(fact_key) or {}).get(metric_unit) or 0); cell.value = value; cell.number_format = "#,##0"
            filled_cell_count += 1; sample_values[col] = value
        filled_rows.append({"row": r, "label": label_text, "row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "phan_to": unit_text, "in_scope": in_scope, "values_sample_D_to_M": {k: sample_values.get(k) for k in list("DEFGHIJKLM")}})
    warnings.append(REVIEW_SCOPE_WARNING)
    _add_review_scope_comments(ws, 8)
    bio = BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content = bio.getvalue()
    debug.update({"filled_cell_count": filled_cell_count, "filled_rows": filled_rows[:220], "filled_rows_total": len(filled_rows), "template_path": _relative_or_str(template_path), "output_bytes": len(content), "limitations": [REVIEW_SCOPE_WARNING], "data_mapping_notes": ["Mẫu 8 tính theo nhóm đối tượng từ các cột nhom_* và dân tộc trong DB.", "DTTS chung dùng dan_toc_chi_tiet != 'Kinh'; không dùng nhom_dtts cho DTTS chung.", "Dòng Hộ đếm số hộ; dòng Nhân khẩu cộng so_nhan_khau của các hộ tương ứng."]})
    log_path = write_jsonl_log("llm_excel_mau8", debug) if write_jsonl_log is not None else None; debug["log_path"] = log_path
    return {"content": content, "warnings": warnings, "debug": debug, "log_path": log_path, "plan": plan}


# ── Mẫu 9: Dân tộc ─────────────────────────────────────────────────────────

ETHNIC_DETAIL_ORDER = [("ede", "Ê-đê"), ("ma", "Mạ"), ("muong", "Mường"), ("thai", "Thái"), ("mnong", "M'Nông"), ("tay", "Tày"), ("nung", "Nùng"), ("mong", "Mông"), ("dao", "Dao"), ("other", "DT Khác")]
MAU9_ALLOWED_FACTS = {"poor_total", "poor_kinh", "poor_dtts", "near_poor_total", "near_poor_kinh", "near_poor_dtts"} | {f"poor_{k}" for k,_ in ETHNIC_DETAIL_ORDER} | {f"near_poor_{k}" for k,_ in ETHNIC_DETAIL_ORDER}
MAU9_DEFAULT_COLUMN_PLAN = [
    {"column": "C", "fact_key": "poor_total", "unit": "households", "reason": "Tổng số hộ nghèo"},
    {"column": "D", "fact_key": "poor_kinh", "unit": "households", "reason": "Hộ nghèo dân tộc Kinh"},
    {"column": "E", "fact_key": "poor_dtts", "unit": "households", "reason": "Hộ nghèo dân tộc thiểu số"},
] + [
    {"column": col, "fact_key": f"poor_{key}", "unit": "households", "reason": f"Hộ nghèo dân tộc {label}"}
    for col, (key, label) in zip(list("FGHIJKLMNO"), ETHNIC_DETAIL_ORDER)
] + [
    {"column": "P", "fact_key": "near_poor_total", "unit": "households", "reason": "Tổng số hộ cận nghèo"},
    {"column": "Q", "fact_key": "near_poor_kinh", "unit": "households", "reason": "Hộ cận nghèo dân tộc Kinh"},
    {"column": "R", "fact_key": "near_poor_dtts", "unit": "households", "reason": "Hộ cận nghèo dân tộc thiểu số"},
] + [
    {"column": col, "fact_key": f"near_poor_{key}", "unit": "households", "reason": f"Hộ cận nghèo dân tộc {label}"}
    for col, (key, label) in zip(["S","T","U","V","W","X","Y","Z","AA","AB"], ETHNIC_DETAIL_ORDER)
]


def _count_ethnic(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str, label_key: str | None) -> int:
    extra = ["phan_loai = ?"]
    where, params = _sqlite_where(year, huyen, xa_phuong, extra)
    params.append(phan_loai)
    if label_key == "kinh":
        where += " AND dan_toc_chi_tiet = ?"; params.append("Kinh")
    elif label_key == "dtts":
        where += " AND dan_toc_chi_tiet <> ?"; params.append("Kinh")
    elif label_key == "other":
        known = [label for key, label in ETHNIC_DETAIL_ORDER if key != "other"] + ["Kinh"]
        where += " AND dan_toc_chi_tiet NOT IN (" + ",".join(["?"] * len(known)) + ")"; params.extend(known)
    elif label_key:
        label = dict(ETHNIC_DETAIL_ORDER).get(label_key)
        where += " AND dan_toc_chi_tiet = ?"; params.append(label)
    with sqlite3.connect(DB_PATH) as conn:
        v = conn.execute(f"SELECT COUNT(*) FROM ho_ngheo{where}", params).fetchone()[0]
    return int(v or 0)


def _mau9_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, int]:
    metrics = {
        "poor_total": _count_ethnic(year, huyen, xa_phuong, "Hộ nghèo", None),
        "poor_kinh": _count_ethnic(year, huyen, xa_phuong, "Hộ nghèo", "kinh"),
        "poor_dtts": _count_ethnic(year, huyen, xa_phuong, "Hộ nghèo", "dtts"),
        "near_poor_total": _count_ethnic(year, huyen, xa_phuong, "Hộ cận nghèo", None),
        "near_poor_kinh": _count_ethnic(year, huyen, xa_phuong, "Hộ cận nghèo", "kinh"),
        "near_poor_dtts": _count_ethnic(year, huyen, xa_phuong, "Hộ cận nghèo", "dtts"),
    }
    for key,_ in ETHNIC_DETAIL_ORDER:
        metrics[f"poor_{key}"] = _count_ethnic(year, huyen, xa_phuong, "Hộ nghèo", key)
        metrics[f"near_poor_{key}"] = _count_ethnic(year, huyen, xa_phuong, "Hộ cận nghèo", key)
    return metrics


def _export_single_area_rows_template(*, template_id: int, plan_type: str, default_plan: list[dict[str, Any]], allowed_facts: set[str], event: str, log_name: str, start_col: int, end_col: int, title_row_max: int, header_start: int, header_end: int, data_start: int, sample_cols: list[str], sample_key: str, year: int | None, huyen: str | None, use_llm: bool, samples_dir: Path | None, compute_metrics, data_mapping_notes: list[str], unit_values_allowed: list[str] | None = None, extra_rule: str = "") -> dict[str, Any]:
    samples_root = samples_dir or DATA_SAMPLES_DIR
    debug = {"timestamp": datetime.now().astimezone().isoformat(), "event": event, "template_id": template_id, "year": year, "huyen": huyen, "use_llm": bool(use_llm), "llm_attempted": False, "llm_error": None}
    warnings: list[str] = []
    header_context = _extract_header_context_for_llm_generic(template_id=template_id, start_col=start_col, end_col=end_col, title_row_max=title_row_max, header_row_start=header_start, header_row_end=header_end, data_row_start=data_start, data_row_max_preview=min(data_start+32, 60), default_plan=default_plan, allowed_facts=allowed_facts, samples_dir=samples_root)
    debug["header_context"] = header_context
    plan = _run_llm_mapping_pipeline_generic(template_id=template_id, plan_type=plan_type, default_plan=default_plan, allowed_facts=allowed_facts, header_context=header_context, use_llm=use_llm, unit_values_allowed=unit_values_allowed or sorted({item["unit"] for item in default_plan}), extra_rule=extra_rule, debug=debug, warnings=warnings)
    _finish_plan_debug_generic(debug, warnings, plan, default_plan)
    template_path = _find_template_sample_path(template_id, samples_root)
    if template_path is None: raise FileNotFoundError(f"Không tìm thấy file template mẫu {template_id}.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb = load_workbook(template_path); ws = wb.active; area = _mau1_area_lookup(year)
    col_to_fact = {str(m["column"]): str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in default_plan: col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen = None; filled_rows=[]; filled_cell_count=0
    for r in range(data_start, (ws.max_row or data_start) + 1):
        label_text = str(ws.cell(r, 2).value or "").strip(); tt_text = str(ws.cell(r, 1).value or "").strip()
        if not label_text: continue
        row_type, row_huyen, row_xa = _resolve_template_area(label_text, tt_text, current_huyen, area)
        if row_type == "district" and row_huyen: current_huyen = row_huyen
        if row_type is None:
            debug.setdefault("unmatched_area_rows", []).append({"row": r, "label": label_text, "tt": tt_text}); continue
        in_scope = not (huyen and row_huyen != huyen)
        metrics = compute_metrics(year, row_huyen, row_xa) if in_scope else {item["fact_key"]: 0 for item in default_plan}
        sample_values={}
        for col, fact_key in col_to_fact.items():
            cell = ws[f"{col}{r}"]
            if isinstance(cell, MergedCell): continue
            value = metrics.get(fact_key, 0); cell.value = value
            cell.number_format = "0.00" if str(fact_key).endswith("_ratio") or str(fact_key).startswith("ratio_") else "#,##0"
            filled_cell_count += 1; sample_values[col] = value
        filled_rows.append({"row": r, "label": label_text, "row_type": row_type, "huyen": row_huyen, "xa_phuong": row_xa, "in_scope": in_scope, sample_key: {k: sample_values.get(k) for k in sample_cols}})
    if template_id == 12:
        _apply_template12_readable_widths(ws, start_row=data_start)
        warnings.append(REVIEW_SCOPE_WARNING)
        _add_review_scope_comments(ws, 12)
    bio=BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content=bio.getvalue()
    debug.update({"filled_cell_count": filled_cell_count, "filled_rows": filled_rows[:160], "filled_rows_total": len(filled_rows), "template_path": _relative_or_str(template_path), "output_bytes": len(content), "limitations": [REVIEW_SCOPE_WARNING] if template_id == 12 else [], "data_mapping_notes": data_mapping_notes})
    log_path = write_jsonl_log(log_name, debug) if write_jsonl_log is not None else None; debug["log_path"] = log_path
    return {"content": content, "warnings": warnings, "debug": debug, "log_path": log_path, "plan": plan}


def export_mau9_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_single_area_rows_template(template_id=9, plan_type="mau9_column_fact_mapping", default_plan=MAU9_DEFAULT_COLUMN_PLAN, allowed_facts=MAU9_ALLOWED_FACTS, event="mau9_real_llm_excel_export", log_name="llm_excel_mau9", start_col=3, end_col=28, title_row_max=6, header_start=8, header_end=10, data_start=11, sample_cols=["C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z","AA","AB"], sample_key="values_sample_C_to_AB", year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir, compute_metrics=_mau9_metrics, data_mapping_notes=["Mẫu 9 phân tích hộ nghèo/cận nghèo theo dân tộc chi tiết.", "DT Khác gồm các dân tộc ngoài Kinh, Ê-đê, Mạ, Mường, Thái, M'Nông, Tày, Nùng, Mông, Dao."], extra_rule="Mẫu 9 chỉ đếm số hộ theo dân tộc; không tính nhân khẩu.")


# ── Mẫu 10: Nguyên nhân nghèo ──────────────────────────────────────────────

CAUSE_PLAN = [("nn_thieu_dat", "Không có đất sản xuất"), ("nn_thieu_von", "Không có vốn sản xuất, kinh doanh"), ("nn_thieu_lao_dong", "Không có lao động"), ("nn_thieu_cong_cu", "Không có công cụ/phương tiện sản xuất"), ("nn_thieu_kien_thuc", "Không có kiến thức về sản xuất"), ("nn_thieu_ky_nang", "Không có kỹ năng lao động sản xuất"), ("nn_om_dau", "Có người ốm đau, bệnh nặng, tai nạn"), ("nn_khac", "Nguyên nhân khác")]
MAU10_ALLOWED_FACTS = {k for k,_ in CAUSE_PLAN}
MAU10_DEFAULT_COLUMN_PLAN = [{"column": col, "fact_key": key, "unit": "households", "reason": reason} for col,(key,reason) in zip(list("CDEFGHIJ"), CAUSE_PLAN)]


def _mau10_metrics(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str | None) -> dict[str, int]:
    extra = []
    if phan_loai: extra.append("phan_loai = ?")
    where, params = _sqlite_where(year, huyen, xa_phuong, extra)
    if phan_loai: params.append(phan_loai)
    fields = [k for k,_ in CAUSE_PLAN]
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT " + ", ".join([f"COALESCE(SUM({f}),0)" for f in fields]) + f" FROM ho_ngheo{where}", params).fetchone()
    return {f: int(row[i] or 0) for i,f in enumerate(fields)}


def export_mau10_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    template_id=10; plan_type="mau10_column_fact_mapping"; samples_root=samples_dir or DATA_SAMPLES_DIR
    debug={"timestamp": datetime.now().astimezone().isoformat(), "event":"mau10_real_llm_excel_export", "template_id":template_id, "year":year, "huyen":huyen, "use_llm":bool(use_llm), "llm_attempted":False, "llm_error":None}
    warnings: list[str]=[]
    header_context=_extract_header_context_for_llm_generic(template_id=10, start_col=3, end_col=10, title_row_max=6, header_row_start=8, header_row_end=10, data_row_start=11, data_row_max_preview=35, default_plan=MAU10_DEFAULT_COLUMN_PLAN, allowed_facts=MAU10_ALLOWED_FACTS, samples_dir=samples_root)
    debug["header_context"]=header_context
    plan=_run_llm_mapping_pipeline_generic(template_id=10, plan_type=plan_type, default_plan=MAU10_DEFAULT_COLUMN_PLAN, allowed_facts=MAU10_ALLOWED_FACTS, header_context=header_context, use_llm=use_llm, unit_values_allowed=["households"], extra_rule="Mẫu 10 gồm 3 dòng mỗi địa bàn: tổng, Hộ nghèo, Hộ cận nghèo. Chỉ đếm hộ theo nguyên nhân nghèo.", debug=debug, warnings=warnings)
    _finish_plan_debug_generic(debug,warnings,plan,MAU10_DEFAULT_COLUMN_PLAN)
    template_path=_find_template_sample_path(10,samples_root)
    if template_path is None: raise FileNotFoundError("Không tìm thấy file template mẫu 10.")
    from openpyxl import load_workbook  # type: ignore
    from openpyxl.cell.cell import MergedCell  # type: ignore
    wb=load_workbook(template_path); ws=wb.active; area=_mau1_area_lookup(year)
    col_to_fact={str(m["column"]):str(m["fact_key"]) for m in plan.get("column_mappings") or []}
    for item in MAU10_DEFAULT_COLUMN_PLAN: col_to_fact.setdefault(item["column"], item["fact_key"])
    current_huyen=None; current_area=None; filled_rows=[]; filled_cell_count=0
    for r in range(11,(ws.max_row or 11)+1):
        b_text=str(ws.cell(r,2).value or "").strip(); a_text=str(ws.cell(r,1).value or "").strip(); b_key=_vn_key(b_text)
        if b_key in {"ho ngheo", "ho can ngheo"}:
            if not current_area: continue
            row_type=current_area.get("row_type"); row_huyen=current_area.get("huyen"); row_xa=current_area.get("xa_phuong"); label_text=current_area.get("label"); tt_text=current_area.get("tt")
            phan_loai = "Hộ nghèo" if b_key == "ho ngheo" else "Hộ cận nghèo"
            row_label=b_text
        elif b_text:
            label_text=b_text; tt_text=a_text
            row_type,row_huyen,row_xa=_resolve_template_area(label_text, tt_text, current_huyen, area)
            if row_type=="district" and row_huyen: current_huyen=row_huyen
            current_area={"row_type":row_type,"huyen":row_huyen,"xa_phuong":row_xa,"label":label_text,"tt":tt_text}
            phan_loai=None; row_label="Tổng"
        else:
            continue
        if row_type is None:
            debug.setdefault("unmatched_area_rows",[]).append({"row":r,"label":b_text,"tt":a_text}); continue
        in_scope=not (huyen and row_huyen!=huyen)
        metrics=_mau10_metrics(year,row_huyen,row_xa,phan_loai) if in_scope else {item["fact_key"]:0 for item in MAU10_DEFAULT_COLUMN_PLAN}
        sample_values={}
        for col,fact_key in col_to_fact.items():
            cell=ws[f"{col}{r}"]
            if isinstance(cell,MergedCell): continue
            value=metrics.get(fact_key,0); cell.value=value; cell.number_format="#,##0"; filled_cell_count+=1; sample_values[col]=value
        filled_rows.append({"row":r,"label":label_text,"row_label":row_label,"row_type":row_type,"huyen":row_huyen,"xa_phuong":row_xa,"in_scope":in_scope,"values_sample_C_to_J":{k:sample_values.get(k) for k in list("CDEFGHIJ")}})
    bio=BytesIO(); _set_workbook_demo_properties(wb); wb.save(bio); content=bio.getvalue()
    debug.update({"filled_cell_count":filled_cell_count,"filled_rows":filled_rows[:260],"filled_rows_total":len(filled_rows),"template_path":_relative_or_str(template_path),"output_bytes":len(content),"limitations":[],"data_mapping_notes":["Mẫu 10 dùng các cột nn_* trong DB.","Dòng tổng = hộ nghèo + hộ cận nghèo trong phạm vi địa bàn/năm."]})
    log_path=write_jsonl_log("llm_excel_mau10",debug) if write_jsonl_log is not None else None; debug["log_path"]=log_path
    return {"content":content,"warnings":warnings,"debug":debug,"log_path":log_path,"plan":plan}


# ── Mẫu 11: Thiếu hụt trẻ em ───────────────────────────────────────────────

MAU11_ALLOWED_FACTS = {"poor_children_total","poor_children_bhyt","poor_children_dinh_duong","poor_children_di_hoc","near_poor_children_total","near_poor_children_bhyt","near_poor_children_dinh_duong","near_poor_children_di_hoc"}
MAU11_DEFAULT_COLUMN_PLAN = [
    {"column":"C","fact_key":"poor_children_total","unit":"children","reason":"Tổng số trẻ em thuộc hộ nghèo"},
    {"column":"D","fact_key":"poor_children_bhyt","unit":"children","reason":"Trẻ em hộ nghèo thiếu BHYT"},
    {"column":"E","fact_key":"poor_children_dinh_duong","unit":"children","reason":"Trẻ em hộ nghèo thiếu dinh dưỡng"},
    {"column":"F","fact_key":"poor_children_di_hoc","unit":"children","reason":"Trẻ em hộ nghèo thiếu tình trạng đi học"},
    {"column":"G","fact_key":"near_poor_children_total","unit":"children","reason":"Tổng số trẻ em thuộc hộ cận nghèo"},
    {"column":"H","fact_key":"near_poor_children_bhyt","unit":"children","reason":"Trẻ em hộ cận nghèo thiếu BHYT"},
    {"column":"I","fact_key":"near_poor_children_dinh_duong","unit":"children","reason":"Trẻ em hộ cận nghèo thiếu dinh dưỡng"},
    {"column":"J","fact_key":"near_poor_children_di_hoc","unit":"children","reason":"Trẻ em hộ cận nghèo thiếu tình trạng đi học"},
]


def _mau11_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, int]:
    p=_sum_children_fields(year,huyen,xa_phuong,"Hộ nghèo"); n=_sum_children_fields(year,huyen,xa_phuong,"Hộ cận nghèo")
    return {"poor_children_total":p["children_total"],"poor_children_bhyt":p["children_bhyt"],"poor_children_dinh_duong":p["children_dinh_duong"],"poor_children_di_hoc":p["children_di_hoc"],"near_poor_children_total":n["children_total"],"near_poor_children_bhyt":n["children_bhyt"],"near_poor_children_dinh_duong":n["children_dinh_duong"],"near_poor_children_di_hoc":n["children_di_hoc"]}


def export_mau11_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_single_area_rows_template(template_id=11, plan_type="mau11_column_fact_mapping", default_plan=MAU11_DEFAULT_COLUMN_PLAN, allowed_facts=MAU11_ALLOWED_FACTS, event="mau11_real_llm_excel_export", log_name="llm_excel_mau11", start_col=3, end_col=10, title_row_max=5, header_start=7, header_end=11, data_start=12, sample_cols=list("CDEFGHIJ"), sample_key="values_sample_C_to_J", year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir, compute_metrics=_mau11_metrics, data_mapping_notes=["Mẫu 11 dùng so_tre_em và các cột so_tre_thieu_* trong DB.","Cột nghèo/cận nghèo tách theo phan_loai."], unit_values_allowed=["children"], extra_rule="Mẫu 11 chỉ tính số trẻ em; unit luôn là children.")


# ── Mẫu 12: Tổng hợp kết quả rà soát hộ nghèo đa chiều ─────────────────────

MAU12_ALLOWED_FACTS = {"all_households","all_kinh_households","all_dtts_households","all_dtts_local_households","all_people","all_kinh_people","all_dtts_people","all_dtts_local_people","poor_households_total","poor_kinh_households","poor_dtts_households","poor_dtts_local_households","poor_meritorious_households","poor_no_work_capacity_households","poor_female_head_households","poor_people_total","poor_kinh_people","poor_dtts_people","poor_dtts_local_people","poor_household_ratio","poor_dtts_ratio","poor_dtts_local_ratio"}
MAU12_DEFAULT_COLUMN_PLAN = [
    {"column":"C","fact_key":"all_households","unit":"households","reason":"Tổng số hộ chung"},
    {"column":"D","fact_key":"all_kinh_households","unit":"households","reason":"Tổng số hộ Kinh"},
    {"column":"E","fact_key":"all_dtts_households","unit":"households","reason":"Tổng số hộ DTTS chung"},
    {"column":"F","fact_key":"all_dtts_local_households","unit":"households","reason":"Tổng số hộ DTTS tại chỗ"},
    {"column":"G","fact_key":"all_people","unit":"persons","reason":"Tổng số khẩu chung"},
    {"column":"H","fact_key":"all_kinh_people","unit":"persons","reason":"Tổng số khẩu Kinh"},
    {"column":"I","fact_key":"all_dtts_people","unit":"persons","reason":"Tổng số khẩu DTTS chung"},
    {"column":"J","fact_key":"all_dtts_local_people","unit":"persons","reason":"Tổng số khẩu DTTS tại chỗ"},
    {"column":"K","fact_key":"poor_households_total","unit":"households","reason":"Tổng số hộ nghèo"},
    {"column":"L","fact_key":"poor_kinh_households","unit":"households","reason":"Hộ nghèo Kinh"},
    {"column":"M","fact_key":"poor_dtts_households","unit":"households","reason":"Hộ nghèo DTTS chung"},
    {"column":"N","fact_key":"poor_dtts_local_households","unit":"households","reason":"Hộ nghèo DTTS tại chỗ"},
    {"column":"O","fact_key":"poor_meritorious_households","unit":"households","reason":"Hộ nghèo chính sách/người có công"},
    {"column":"P","fact_key":"poor_no_work_capacity_households","unit":"households","reason":"Hộ nghèo không có khả năng lao động"},
    {"column":"Q","fact_key":"poor_female_head_households","unit":"households","reason":"Hộ nghèo chủ hộ là nữ"},
    {"column":"R","fact_key":"poor_people_total","unit":"persons","reason":"Tổng số khẩu hộ nghèo"},
    {"column":"S","fact_key":"poor_kinh_people","unit":"persons","reason":"Khẩu hộ nghèo Kinh"},
    {"column":"T","fact_key":"poor_dtts_people","unit":"persons","reason":"Khẩu hộ nghèo DTTS chung"},
    {"column":"U","fact_key":"poor_dtts_local_people","unit":"persons","reason":"Khẩu hộ nghèo DTTS tại chỗ"},
    {"column":"V","fact_key":"poor_household_ratio","unit":"percent","reason":"Tỷ lệ hộ nghèo trên tổng hộ chung"},
    {"column":"W","fact_key":"poor_dtts_ratio","unit":"percent","reason":"Tỷ lệ hộ nghèo DTTS trên tổng hộ DTTS chung"},
    {"column":"X","fact_key":"poor_dtts_local_ratio","unit":"percent","reason":"Tỷ lệ hộ nghèo DTTS tại chỗ trên tổng hộ DTTS tại chỗ"},
]


def _hh_people_by_condition(year: int | None, huyen: str | None, xa_phuong: str | None, conds: list[str]) -> tuple[int,int]:
    return _count_and_people(year,huyen,xa_phuong,extra=conds)


def _mau12_metrics(year: int | None, huyen: str | None, xa_phuong: str | None) -> dict[str, Any]:
    all_hh, all_people = _hh_people_by_condition(year,huyen,xa_phuong,[])
    all_kinh_hh, all_kinh_people = _hh_people_by_condition(year,huyen,xa_phuong,["dan_toc_chi_tiet = 'Kinh'"])
    all_dtts_hh, all_dtts_people = _hh_people_by_condition(year,huyen,xa_phuong,["dan_toc_chi_tiet <> 'Kinh'"])
    all_local_hh, all_local_people = _hh_people_by_condition(year,huyen,xa_phuong,["dan_toc_tai_cho = 'Có'"])
    poor = ["phan_loai = 'Hộ nghèo'"]
    poor_hh, poor_people = _hh_people_by_condition(year,huyen,xa_phuong,poor)
    poor_kinh_hh, poor_kinh_people = _hh_people_by_condition(year,huyen,xa_phuong,poor+["dan_toc_chi_tiet = 'Kinh'"])
    poor_dtts_hh, poor_dtts_people = _hh_people_by_condition(year,huyen,xa_phuong,poor+["dan_toc_chi_tiet <> 'Kinh'"])
    poor_local_hh, poor_local_people = _hh_people_by_condition(year,huyen,xa_phuong,poor+["dan_toc_tai_cho = 'Có'"])
    poor_mer_hh,_ = _hh_people_by_condition(year,huyen,xa_phuong,poor+["nhom_co_cong = 1"])
    poor_knld_hh,_ = _hh_people_by_condition(year,huyen,xa_phuong,poor+["nhom_khong_knld = 1"])
    poor_female_hh,_ = _hh_people_by_condition(year,huyen,xa_phuong,poor+["gioi_tinh = 'Nữ'"])
    return {
        "all_households": all_hh, "all_kinh_households": all_kinh_hh, "all_dtts_households": all_dtts_hh, "all_dtts_local_households": all_local_hh,
        "all_people": all_people, "all_kinh_people": all_kinh_people, "all_dtts_people": all_dtts_people, "all_dtts_local_people": all_local_people,
        "poor_households_total": poor_hh, "poor_kinh_households": poor_kinh_hh, "poor_dtts_households": poor_dtts_hh, "poor_dtts_local_households": poor_local_hh,
        "poor_meritorious_households": poor_mer_hh, "poor_no_work_capacity_households": poor_knld_hh, "poor_female_head_households": poor_female_hh,
        "poor_people_total": poor_people, "poor_kinh_people": poor_kinh_people, "poor_dtts_people": poor_dtts_people, "poor_dtts_local_people": poor_local_people,
        "poor_household_ratio": round(poor_hh / all_hh * 100, 2) if all_hh else 0.0,
        "poor_dtts_ratio": round(poor_dtts_hh / all_dtts_hh * 100, 2) if all_dtts_hh else 0.0,
        "poor_dtts_local_ratio": round(poor_local_hh / all_local_hh * 100, 2) if all_local_hh else 0.0,
    }


def export_mau12_llm_excel(*, year: int | None = None, huyen: str | None = None, use_llm: bool = True, samples_dir: Path | None = None) -> dict[str, Any]:
    return _export_single_area_rows_template(template_id=12, plan_type="mau12_column_fact_mapping", default_plan=MAU12_DEFAULT_COLUMN_PLAN, allowed_facts=MAU12_ALLOWED_FACTS, event="mau12_real_llm_excel_export", log_name="llm_excel_mau12", start_col=3, end_col=24, title_row_max=6, header_start=7, header_end=10, data_start=11, sample_cols=["C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X"], sample_key="values_sample_C_to_X", year=year, huyen=huyen, use_llm=use_llm, samples_dir=samples_dir, compute_metrics=_mau12_metrics, data_mapping_notes=["Mẫu 12 tính từ các hộ có trong dữ liệu rà soát/phân loại DB theo năm/phạm vi đã chọn; không phải bảng dân cư toàn địa bàn.","DTTS chung dùng dan_toc_chi_tiet != 'Kinh'; DTTS tại chỗ dùng dan_toc_tai_cho = 'Có'.","Tỷ lệ V = K/C*100, W = M/E*100, X = N/F*100."], unit_values_allowed=["households","persons","percent"], extra_rule="Mẫu 12 gồm household/person/percent; không sinh số liệu.")

# ── Cache nhẹ cho các mẫu 8-12: tránh mở SQLite quá nhiều lần khi xuất một mẫu ──
_COUNT_AND_PEOPLE_CACHE: dict[tuple[Any, ...], tuple[int, int]] = {}
_CHILDREN_FIELDS_CACHE: dict[tuple[Any, ...], dict[str, int]] = {}
_ETHNIC_COUNT_CACHE: dict[tuple[Any, ...], int] = {}


def _count_and_people(year: int | None, huyen: str | None, xa_phuong: str | None, *, extra: list[str] | None = None) -> tuple[int, int]:  # type: ignore[no-redef]
    key = (int(year) if year else None, huyen or "", xa_phuong or "", tuple(extra or []))
    if key in _COUNT_AND_PEOPLE_CACHE:
        return _COUNT_AND_PEOPLE_CACHE[key]
    where, params = _sqlite_where(year, huyen, xa_phuong, extra)
    with sqlite3.connect(DB_PATH) as conn:
        hh, people = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(so_nhan_khau),0) FROM ho_ngheo{where}", params).fetchone()
    value = (int(hh or 0), int(people or 0))
    _COUNT_AND_PEOPLE_CACHE[key] = value
    return value


def _sum_children_fields(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str) -> dict[str, int]:  # type: ignore[no-redef]
    key = (int(year) if year else None, huyen or "", xa_phuong or "", phan_loai)
    if key in _CHILDREN_FIELDS_CACHE:
        return _CHILDREN_FIELDS_CACHE[key]
    where, params = _sqlite_where(year, huyen, xa_phuong, ["phan_loai = ?"])
    params.append(phan_loai)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(so_tre_em),0),
                   COALESCE(SUM(so_tre_thieu_bhyt),0),
                   COALESCE(SUM(so_tre_thieu_dinh_duong),0),
                   COALESCE(SUM(so_tre_thieu_di_hoc),0)
            FROM ho_ngheo{where}
            """,
            params,
        ).fetchone()
    value = {
        "children_total": int(row[0] or 0),
        "children_bhyt": int(row[1] or 0),
        "children_dinh_duong": int(row[2] or 0),
        "children_di_hoc": int(row[3] or 0),
    }
    _CHILDREN_FIELDS_CACHE[key] = value
    return value


def _count_ethnic(year: int | None, huyen: str | None, xa_phuong: str | None, phan_loai: str, label_key: str | None) -> int:  # type: ignore[no-redef]
    key = (int(year) if year else None, huyen or "", xa_phuong or "", phan_loai, label_key or "")
    if key in _ETHNIC_COUNT_CACHE:
        return _ETHNIC_COUNT_CACHE[key]
    extra = ["phan_loai = ?"]
    where, params = _sqlite_where(year, huyen, xa_phuong, extra)
    params.append(phan_loai)
    if label_key == "kinh":
        where += " AND dan_toc_chi_tiet = ?"; params.append("Kinh")
    elif label_key == "dtts":
        where += " AND dan_toc_chi_tiet <> ?"; params.append("Kinh")
    elif label_key == "other":
        known = [label for key2, label in ETHNIC_DETAIL_ORDER if key2 != "other"] + ["Kinh"]
        where += " AND dan_toc_chi_tiet NOT IN (" + ",".join(["?"] * len(known)) + ")"; params.extend(known)
    elif label_key:
        label = dict(ETHNIC_DETAIL_ORDER).get(label_key)
        where += " AND dan_toc_chi_tiet = ?"; params.append(label)
    with sqlite3.connect(DB_PATH) as conn:
        v = conn.execute(f"SELECT COUNT(*) FROM ho_ngheo{where}", params).fetchone()[0]
    value = int(v or 0)
    _ETHNIC_COUNT_CACHE[key] = value
    return value


def _clear_template_export_caches() -> None:
    _COUNT_AND_PEOPLE_CACHE.clear()
    _CHILDREN_FIELDS_CACHE.clear()
    _ETHNIC_COUNT_CACHE.clear()
