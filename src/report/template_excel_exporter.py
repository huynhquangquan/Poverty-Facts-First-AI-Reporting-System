from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
import os
import re
import sqlite3
import unicodedata


@dataclass
class TemplateExcelResult:
    """Kết quả xuất Excel theo đúng file mẫu.

    content: bytes của file .xlsx để đưa vào st.download_button.
    warnings: cảnh báo dữ liệu thiếu/không map được, hiển thị trong UI.
    filled_rows: số dòng dữ liệu đã ghi vào template.
    """

    content: bytes
    template_id: int
    source_template: str
    filled_rows: int = 0
    warnings: list[str] = field(default_factory=list)


SUPPORTED_TEMPLATE_IDS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

TEMPLATE_SOURCE_FILES: dict[int, str] = {
    1: "1. Tổng hợp kết quả rà soát HC,CN,NL,NN có mức sống trung bình.xlsx",
    2: "2. Tổng hợp diễn biến hộ nghèo.xlsx",
    3: "3. Tổng hợp diễn biến hộ cận nghèo.xlsx",
    4: "4. Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo.xlsx",
    5: "5. Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo.xlsx",
    6: "6. Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo.xlsx",
    7: "7. Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo.xlsx",
    8: "8. Phân tích hộ nghèo, hộ cận nghèo theo các nhóm đối tượng.xlsx",
    9: "9. Phân tích hộ nghèo, hộ cận nghèo theo dân tộc.xlsx",
    10: "10. Phân tích hộ nghèo, hộ cận nghèo theo nguyên nhân nghèo.xlsx",
    11: "11. Tổng hợp chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo, hộ cận nghèo.xlsx",
    12: "12. Tổng hợp kết quả rà soát hộ nghèo theo chuẩn đa chiều.xlsx",
}

POOR = "Hộ nghèo"
NEAR_POOR = "Hộ cận nghèo"
NON_POOR = "Hộ không nghèo"
HOUSEHOLD_COUNT = "COUNT(DISTINCT id_ho)"

MEDIUM_LIVING_NO_DIRECT_DATA_WARNING = (
    "Mẫu 1: DB chưa có trường dữ liệu trực tiếp để xác định nhóm hộ nông, lâm, ngư nghiệp "
    "có mức sống trung bình; các cột này ghi 0."
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
    "DB chưa có cột lý do biến động chi tiết cho nhóm 'khác'; exporter ghi 0 cho cột G/K "
    "và không dùng nhãn giảm/tăng khác để cân bằng công thức."
)

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
    except Exception:
        pass

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
    norm_keywords = tuple(_norm(k) for k in keywords if str(k).strip())
    if not norm_keywords:
        return
    for row in range(1, min(ws.max_row, max_row) + 1):
        for col in range(1, min(ws.max_column, max_col) + 1):
            cell = ws.cell(row, col)
            value_key = _norm(cell.value)
            if not value_key:
                continue
            if any(key and key in value_key for key in norm_keywords):
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
            note=MEDIUM_LIVING_PROXY_WARNING if ALLOW_DEMO_PROXY_NLNN_MSTB else MEDIUM_LIVING_NO_DIRECT_DATA_WARNING,
            max_row=11,
            max_col=16,
        )
    elif int(template_id) == 8:
        _add_comments_to_matching_header_cells(
            ws,
            keywords=("Tổng số hộ dân cư", "dân cư"),
            note=REVIEW_SCOPE_WARNING,
            max_row=10,
            max_col=13,
        )
    elif int(template_id) == 12:
        _add_comments_to_matching_header_cells(
            ws,
            keywords=("Tổng số hộ chung", "Tổng số khẩu chung", "Tỷ lệ hộ nghèo"),
            note=REVIEW_SCOPE_WARNING,
            max_row=10,
            max_col=24,
        )


# ───────────────────────────── helpers ─────────────────────────────

def _norm(text: Any) -> str:
    """Khóa so khớp địa bàn: bỏ dấu, hạ chữ, gộp khoảng trắng."""
    raw = "" if text is None else str(text).strip()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.lower().replace("đ", "d")
    raw = re.sub(r"[^a-z0-9\s]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _geo_key(text: Any) -> str:
    """Khóa địa bàn mạnh hơn _norm: bỏ tiền tố hành chính và bỏ khoảng trắng.

    Dùng để khớp tên trong template với tên trong DB khi có khác biệt nhỏ như
    'Huyện Cư Jút' vs 'Cư Jút', hoặc 'Ea TLing' vs 'Ea T Ling'.
    """
    key = _norm(text)
    for prefix in ("huyen ", "thanh pho ", "thi xa ", "xa ", "phuong ", "thi tran "):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    return key.replace(" ", "")


def _template_path(samples_dir: str | Path, template_id: int) -> Path:
    name = TEMPLATE_SOURCE_FILES.get(int(template_id))
    if not name:
        raise ValueError(f"Chưa khai báo source file cho template_id={template_id}")
    p = Path(samples_dir) / name
    if not p.exists():
        raise FileNotFoundError(f"Không tìm thấy file mẫu Excel: {p}")
    return p


def _latest_year(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(nam) FROM ho_ngheo WHERE nam IS NOT NULL").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _movement_other_reason_available(conn: sqlite3.Connection) -> bool:
    return any(_column_exists(conn, "ho_ngheo", column) for column in MOVEMENT_OTHER_REASON_COLUMNS)


def _sql_filter(year: int | None = None, huyen: str | None = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params

def _detect_medium_living_condition(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Tìm cột/giá trị biểu thị trực tiếp mức sống trung bình nếu DB có.

    Nếu DB chưa có trường/nhãn trực tiếp, mẫu 1 ghi 0 và cảnh báo; không dùng proxy nghề nghiệp.
    """
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
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM ho_ngheo WHERE {col} IS NOT NULL"
        ).fetchall()
        for (value,) in rows:
            key = _norm(value)
            if key in {"1", "true", "co"} and col in {"nlnndn_muc_song_trung_binh", "muc_song_trung_binh"}:
                return col, str(value)
            if "trung binh" in key or "muc song" in key:
                return col, str(value)
    return None


def _template1_medium_living_expr(conn: sqlite3.Connection) -> tuple[str, str, list[Any], list[str]]:
    """SQL expressions cho cột I/O của mẫu 1.

    Thứ tự ưu tiên:
    1) Nếu DB có trường/giá trị trực tiếp về mức sống trung bình thì dùng trực tiếp.
    2) Nếu chưa có bằng chứng trực tiếp, ghi 0 và cảnh báo; không dùng proxy nghề nghiệp.
    """
    warnings: list[str] = []
    medium_cond = _detect_medium_living_condition(conn)
    if medium_cond:
        medium_col, medium_value = medium_cond
        household_expr = f"COUNT(DISTINCT CASE WHEN {medium_col} = ? THEN id_ho END)"
        population_expr = f"COALESCE(SUM(CASE WHEN {medium_col} = ? THEN so_nhan_khau ELSE 0 END), 0)"
        return household_expr, population_expr, [medium_value, medium_value], warnings

    if ALLOW_DEMO_PROXY_NLNN_MSTB and _column_exists(conn, "ho_ngheo", "nghe_nghiep_chu_ho"):
        placeholders = ",".join(["?"] * len(NLNN_JOB_VALUES))
        cond = f"phan_loai = ? AND nghe_nghiep_chu_ho IN ({placeholders})"
        household_expr = f"COUNT(DISTINCT CASE WHEN {cond} THEN id_ho END)"
        population_expr = f"COALESCE(SUM(CASE WHEN {cond} THEN so_nhan_khau ELSE 0 END), 0)"
        warnings.append(MEDIUM_LIVING_PROXY_WARNING)
        return household_expr, population_expr, [NON_POOR, *NLNN_JOB_VALUES, NON_POOR, *NLNN_JOB_VALUES], warnings

    warnings.append(MEDIUM_LIVING_NO_DIRECT_DATA_WARNING)
    return "0", "0", [], warnings


def _build_template1_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính số liệu cho mẫu 1 theo cấp huyện và xã/phường."""
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    medium_household_expr, medium_population_expr, medium_params, medium_warnings = _template1_medium_living_expr(conn)
    warnings.extend(medium_warnings)
    warnings.append(REVIEW_SCOPE_WARNING)

    where, params = _sql_filter(year, huyen)
    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            {HOUSEHOLD_COUNT} AS tong_ho_dan_cu,
            COALESCE(SUM(so_nhan_khau), 0) AS tong_nhan_khau,
            COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS so_ho_ngheo,
            COALESCE(SUM(CASE WHEN phan_loai = ? THEN so_nhan_khau ELSE 0 END), 0) AS so_khau_ngheo,
            COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS so_ho_can_ngheo,
            COALESCE(SUM(CASE WHEN phan_loai = ? THEN so_nhan_khau ELSE 0 END), 0) AS so_khau_can_ngheo,
            {medium_household_expr} AS so_ho_nlnndn_mstb,
            {medium_population_expr} AS so_khau_nlnndn_mstb
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong
    """
    query_params: list[Any] = [POOR, POOR, NEAR_POOR, NEAR_POOR] + medium_params + params
    commune_rows = conn.execute(sql, query_params).fetchall()
    cols = [d[0] for d in conn.execute(sql, query_params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}
    numeric_keys = [
        "tong_ho_dan_cu",
        "tong_nhan_khau",
        "so_ho_ngheo",
        "so_khau_ngheo",
        "so_ho_can_ngheo",
        "so_khau_can_ngheo",
        "so_ho_nlnndn_mstb",
        "so_khau_nlnndn_mstb",
    ]

    for row in commune_rows:
        rec = dict(zip(cols, row))
        hk = _geo_key(rec.get("huyen"))
        xk = _geo_key(rec.get("xa_phuong"))
        if not hk or not xk:
            continue
        for k in numeric_keys:
            rec[k] = int(rec.get(k) or 0)
        by_commune[(hk, xk)] = rec
        district = by_district.setdefault(hk, {"huyen": rec.get("huyen")})
        for k in numeric_keys:
            district[k] = int(district.get(k) or 0) + int(rec.get(k) or 0)

    return by_district, by_commune, warnings


def _row_is_district(stt: Any, label: Any) -> bool:
    stt_text = "" if stt is None else str(stt).strip()
    label_key = _norm(label)
    return bool(stt_text and "." not in stt_text and (label_key.startswith("huyen ") or label_key.startswith("thanh pho ")))


def _write_template1_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
    start_row: int = 12,
) -> int:
    """Ghi dữ liệu vào đúng vùng của mẫu 1, giữ nguyên format/merge/header."""
    current_district_key = ""
    filled = 0
    max_row = ws.max_row

    for row in range(start_row, max_row + 1):
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        # Dòng 11 của mẫu 1 là dòng ký hiệu cột A/B/1/2/3..., không phải dòng dữ liệu.
        # Giữ rule này để nếu template đổi start_row nhầm thì vẫn không ghi đè header.
        if _norm(stt) == "a" and _norm(label) == "b":
            continue
        if not label:
            continue

        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        else:
            rec = by_commune.get((current_district_key, label_key))

        if not rec:
            # Xóa số cũ để không lẫn dữ liệu template/sample.
            values = [0, 0, 0, None, 0, None, 0, None, 0, None, 0, None, 0, None]
        else:
            values = [
                rec["tong_ho_dan_cu"],
                rec["tong_nhan_khau"],
                rec["so_ho_ngheo"],
                None,
                rec["so_ho_can_ngheo"],
                None,
                rec["so_ho_nlnndn_mstb"],
                None,
                rec["so_khau_ngheo"],
                None,
                rec["so_khau_can_ngheo"],
                None,
                rec["so_khau_nlnndn_mstb"],
                None,
            ]
            filled += 1

        # C:P = 14 cột. C, D, E, G, I, K, M, O là số; F/H/J/L/N/P là công thức tỷ lệ.
        for offset, value in enumerate(values, start=3):
            ws.cell(row, offset).value = value

        ws.cell(row, 6).value = f"=IFERROR(E{row}/C{row}*100,0)"
        ws.cell(row, 8).value = f"=IFERROR(G{row}/C{row}*100,0)"
        ws.cell(row, 10).value = f"=IFERROR(I{row}/C{row}*100,0)"
        ws.cell(row, 12).value = f"=IFERROR(K{row}/D{row}*100,0)"
        ws.cell(row, 14).value = f"=IFERROR(M{row}/D{row}*100,0)"
        ws.cell(row, 16).value = f"=IFERROR(O{row}/D{row}*100,0)"

        for col in range(3, 17):
            ws.cell(row, col).number_format = "0.00" if col in {6, 8, 10, 12, 14, 16} else "#,##0"

    return filled


# ───────────────────────────── template 2-3: movement helpers ─────────────────────────────

MOVEMENT_VALUE_COLUMNS = [
    "dau_ky",
    "giam_1",
    "giam_2",
    "giam_khac",
    "tang_1",
    "tang_2",
    "tang_3",
    "tang_khac",
    "cuoi_ky",
]

NEAR_POOR_TO_POOR_MOVEMENT_LABELS = {
    _norm("Cận nghèo trở thành hộ nghèo"),
    _norm("Hộ cận nghèo trở thành hộ nghèo"),
    _norm("Từ hộ cận nghèo thành hộ nghèo"),
    _norm("Từ hộ cận nghèo trở thành hộ nghèo"),
}


def _empty_movement_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for base in MOVEMENT_VALUE_COLUMNS:
        rec[f"{base}_ho"] = 0
        rec[f"{base}_khau"] = 0
    return rec


def _add_movement_value(rec: dict[str, Any], base: str, households: int, population: int) -> None:
    rec[f"{base}_ho"] = int(rec.get(f"{base}_ho") or 0) + int(households or 0)
    rec[f"{base}_khau"] = int(rec.get(f"{base}_khau") or 0) + int(population or 0)


def _add_to_movement_maps(
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
    *,
    huyen: Any,
    xa_phuong: Any,
    bases: list[str],
    households: int,
    population: int,
) -> None:
    hk = _geo_key(huyen)
    xk = _geo_key(xa_phuong)
    if not hk:
        return
    drec = by_district.setdefault(hk, _empty_movement_rec(huyen_name=huyen))
    crec = None
    if xk:
        crec = by_commune.setdefault((hk, xk), _empty_movement_rec(huyen_name=huyen, xa_name=xa_phuong))
    for base in bases:
        _add_movement_value(drec, base, households, population)
        if crec is not None:
            _add_movement_value(crec, base, households, population)


def _finalize_movement_rec(rec: dict[str, Any]) -> None:
    for suffix in ("ho", "khau"):
        rec[f"cuoi_ky_{suffix}"] = (
            int(rec.get(f"dau_ky_{suffix}") or 0)
            - int(rec.get(f"giam_1_{suffix}") or 0)
            - int(rec.get(f"giam_2_{suffix}") or 0)
            - int(rec.get(f"giam_khac_{suffix}") or 0)
            + int(rec.get(f"tang_1_{suffix}") or 0)
            + int(rec.get(f"tang_2_{suffix}") or 0)
            + int(rec.get(f"tang_3_{suffix}") or 0)
            + int(rec.get(f"tang_khac_{suffix}") or 0)
        )


def _movement_bases_for_template(template_id: int, label: Any, *, allow_other: bool = False) -> list[str]:
    """Map nhãn biến động trong DB sang các cột D:L của mẫu 2/3.

    Mẫu 2 - hộ nghèo:
      D đầu kỳ = nghèo cũ + các nhóm thoát nghèo trong năm.
      E/F/G = các nhóm giảm; H/I/J/K = các nhóm tăng; L = công thức cân đối.

    Mẫu 3 - hộ cận nghèo:
      D đầu kỳ = cận nghèo cũ + các nhóm giảm cận nghèo trong năm.
      E/F/G = các nhóm giảm; H/I/J/K = các nhóm tăng; L = công thức cân đối.
    """
    key = _norm(label)
    if not key:
        return []

    if int(template_id) == 2:
        if key == _norm("Nghèo cũ (giữ nguyên)"):
            return ["dau_ky"]
        if key == _norm("Thoát nghèo -> cận nghèo"):
            return ["dau_ky", "giam_1"]
        if key == _norm("Thoát nghèo -> vượt chuẩn"):
            return ["dau_ky", "giam_2"]
        if allow_other and key == _norm("Giảm nghèo khác"):
            return ["dau_ky", "giam_khac"]
        if key in NEAR_POOR_TO_POOR_MOVEMENT_LABELS:
            return ["tang_1"]
        if key == _norm("Tái nghèo"):
            return ["tang_2"]
        if key == _norm("Nghèo mới phát sinh"):
            return ["tang_3"]
        if allow_other and key == _norm("Tăng nghèo khác"):
            return ["tang_khac"]
        return []

    if int(template_id) == 3:
        if key == _norm("Cận nghèo cũ (giữ nguyên)"):
            return ["dau_ky"]
        if key == _norm("Thoát cận nghèo -> vượt chuẩn"):
            return ["dau_ky", "giam_1"]
        if key in NEAR_POOR_TO_POOR_MOVEMENT_LABELS:
            return ["dau_ky", "giam_2"]
        if key in {_norm("Thoát nghèo -> cận nghèo"), _norm("Từ hộ nghèo lên cận nghèo")}:
            return ["tang_1"]
        if key == _norm("Tái cận nghèo"):
            return ["tang_2"]
        if key == _norm("Cận nghèo mới phát sinh"):
            return ["tang_3"]
        if allow_other and key == _norm("Giảm cận nghèo khác"):
            return ["dau_ky", "giam_khac"]
        if allow_other and key == _norm("Tăng cận nghèo khác"):
            return ["tang_khac"]
        return []

    return []


def _build_movement_stats(
    conn: sqlite3.Connection,
    *,
    template_id: int,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính số liệu mẫu 2/3 theo huyện và xã/phường từ cột bien_dong_dau_ky."""
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    if not _column_exists(conn, "ho_ngheo", "bien_dong_dau_ky"):
        raise ValueError("DB thiếu cột bien_dong_dau_ky nên chưa thể xuất mẫu diễn biến 2/3.")

    allow_other = _movement_other_reason_available(conn)
    if not allow_other:
        warnings.append(MOVEMENT_OTHER_NO_REASON_WARNING)

    where, params = _sql_filter(year, huyen)
    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            bien_dong_dau_ky,
            {HOUSEHOLD_COUNT} AS so_ho,
            COALESCE(SUM(so_nhan_khau), 0) AS so_khau
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong, bien_dong_dau_ky
    """
    rows = conn.execute(sql, params).fetchall()

    by_district: dict[str, dict[str, Any]] = {}
    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    seen_labels: set[str] = set()

    for huyen_name, xa_name, movement_label, so_ho, so_khau in rows:
        bases = _movement_bases_for_template(template_id, movement_label, allow_other=allow_other)
        if not bases:
            continue
        seen_labels.add(_norm(movement_label))
        _add_to_movement_maps(
            by_district,
            by_commune,
            huyen=huyen_name,
            xa_phuong=xa_name,
            bases=bases,
            households=int(so_ho or 0),
            population=int(so_khau or 0),
        )

    # Chỉ dùng nhãn nghiệp vụ thật trong bien_dong_dau_ky; không tự dựng biến động
    # bằng đối chiếu id_ho giữa hai năm.
    has_near_poor_to_poor_label = bool(seen_labels & NEAR_POOR_TO_POOR_MOVEMENT_LABELS)

    if int(template_id) == 2:
        if not has_near_poor_to_poor_label:
            warnings.append(
                "Mẫu 2: DB chưa có nhãn 'Cận nghèo trở thành hộ nghèo'; cột H để 0/giữ theo nhãn hiện có, không tự suy diễn bằng đối chiếu 2 năm."
            )
    elif int(template_id) == 3:
        if not has_near_poor_to_poor_label:
            warnings.append(
                "Mẫu 3: DB chưa có nhãn 'Cận nghèo trở thành hộ nghèo'; cột F để 0/giữ theo nhãn hiện có, không tự suy diễn bằng đối chiếu 2 năm."
            )

    for rec in list(by_district.values()) + list(by_commune.values()):
        _finalize_movement_rec(rec)

    final_class = POOR if int(template_id) == 2 else NEAR_POOR if int(template_id) == 3 else None
    if final_class:
        final_where, final_params = _sql_filter(year, huyen)
        clause = "phan_loai = ?"
        if final_where:
            final_where = final_where + " AND " + clause
        else:
            final_where = "WHERE " + clause
        actual_final = int(conn.execute(f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {final_where}", [*final_params, final_class]).fetchone()[0] or 0)
        formula_final = sum(int(rec.get("cuoi_ky_ho") or 0) for rec in by_district.values())
        unexplained_delta = actual_final - formula_final
        if unexplained_delta:
            warnings.append(
                f"Mẫu {template_id}: tổng cuối kỳ theo công thức là {formula_final} hộ, "
                f"tổng {final_class} theo phan_loai hiện tại là {actual_final} hộ; "
                f"chênh lệch chưa giải thích {unexplained_delta} hộ không được tự gán vào cột khác."
            )

    return by_district, by_commune, warnings


def _find_first_movement_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        if _norm(ws.cell(row, 3).value) == "ho":
            return row
    return 10


def _movement_values_for_row(rec: dict[str, Any] | None, *, suffix: str) -> list[int]:
    if not rec:
        return [0] * 9
    return [int(rec.get(f"{base}_{suffix}") or 0) for base in MOVEMENT_VALUE_COLUMNS]


def _format_movement_number_cell(cell: Any) -> None:
    """Chuẩn hóa format ô số liệu D:L của mẫu diễn biến 2/3.

    Một số cột trong template gốc, đặc biệt G/K là cột "khác" thường toàn 0,
    có style alignment khác các cột số còn lại. Khi exporter ghi số vào các ô này,
    số vẫn đúng nhưng nhìn bị lệch. Hàm này áp cùng number format + alignment
    cho mọi ô số liệu D:L để không phụ thuộc style rỗng của template.
    """
    cell.number_format = "#,##0"
    try:
        cell.alignment = cell.alignment.copy(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )
    except Exception:
        pass


def _write_movement_template_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu vào vùng D:L của mẫu 2/3, giữ nguyên header/layout template."""
    current_district_key = ""
    filled = 0
    row = _find_first_movement_data_row(ws)

    while row <= ws.max_row:
        row_type = _norm(ws.cell(row, 3).value)
        if row_type != "ho":
            row += 1
            continue

        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None

        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        ho_values = _movement_values_for_row(rec, suffix="ho")
        khau_values = _movement_values_for_row(rec, suffix="khau")

        for offset, value in enumerate(ho_values, start=4):
            cell = ws.cell(row, offset)
            cell.value = value
            _format_movement_number_cell(cell)

        next_row = row + 1
        if next_row <= ws.max_row and _norm(ws.cell(next_row, 3).value) in {"nhan khau", "nhan_khau"}:
            for offset, value in enumerate(khau_values, start=4):
                cell = ws.cell(next_row, offset)
                cell.value = value
                _format_movement_number_cell(cell)

        if rec:
            filled += 1

        row += 2

    return filled




# ───────────────────────────── template 4: deprivation count helpers ─────────────────────────────

DEPRIVATION_INDICATOR_COLUMNS = [
    # Thứ tự 1-12 đúng theo header mẫu 4/5: việc làm, BHXH, BHYT, dinh dưỡng,
    # giáo dục người lớn, đi học trẻ em, chất lượng nhà ở, diện tích nhà ở,
    # nước sạch, nhà tiêu HVS, viễn thông, tài sản tiếp cận thông tin.
    "th_viec_lam",
    "th_bhxh",
    "th_bhyt",
    "th_dinh_duong",
    "th_giao_duc_nguoi_lon",
    "th_di_hoc_tre_em",
    "th_chat_luong_nha",
    "th_dien_tich_nha",
    "th_nuoc_sach",
    "th_nha_tieu",
    "th_vien_thong",
    "th_tai_san_tt",
]


def _empty_deprivation_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "huyen": huyen_name,
        "xa_phuong": xa_name,
        "tong_ho_ngheo": 0,
        "tong_so_thieu_hut": 0,
    }
    for idx in range(1, 13):
        rec[f"chi_so_{idx}"] = 0
    return rec


def _add_deprivation_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["tong_ho_ngheo"] = int(target.get("tong_ho_ngheo") or 0) + int(source.get("tong_ho_ngheo") or 0)
    for idx in range(1, 13):
        key = f"chi_so_{idx}"
        target[key] = int(target.get(key) or 0) + int(source.get(key) or 0)
    target["tong_so_thieu_hut"] = sum(int(target.get(f"chi_so_{idx}") or 0) for idx in range(1, 13))


def _build_deprivation_count_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
    phan_loai: str = POOR,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính số lượng hộ trong nhóm phan_loai thiếu từng chỉ số DVXHCB theo huyện/xã.

    Dùng cho mẫu 4 (hộ nghèo) và mẫu 6 (hộ cận nghèo):
    - Cột C = tổng số hộ của nhóm trong phạm vi dòng.
    - Cột D = tổng số lượt thiếu hụt = tổng 12 cột chỉ số E:P.
    - Cột E:P = số hộ trong nhóm có từng cờ thiếu hụt = 1.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    missing_cols = [col for col in DEPRIVATION_INDICATOR_COLUMNS if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError(
            "DB thiếu cột chỉ số thiếu hụt DVXHCB nên chưa thể xuất mẫu 4: "
            + ", ".join(missing_cols)
        )

    where, params = _sql_filter(year, huyen)
    if where:
        where += " AND phan_loai = ?"
    else:
        where = "WHERE phan_loai = ?"
    params = list(params) + [phan_loai]

    indicator_sql = ",\n            ".join(
        f"COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END) AS chi_so_{idx}"
        for idx, col in enumerate(DEPRIVATION_INDICATOR_COLUMNS, start=1)
    )
    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            {HOUSEHOLD_COUNT} AS tong_ho_ngheo,
            {indicator_sql}
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong
    """
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}

    for row in rows:
        rec = dict(zip(cols, row))
        hk = _geo_key(rec.get("huyen"))
        xk = _geo_key(rec.get("xa_phuong"))
        if not hk or not xk:
            continue
        clean = _empty_deprivation_rec(rec.get("huyen"), rec.get("xa_phuong"))
        clean["tong_ho_ngheo"] = int(rec.get("tong_ho_ngheo") or 0)
        for idx in range(1, 13):
            clean[f"chi_so_{idx}"] = int(rec.get(f"chi_so_{idx}") or 0)
        clean["tong_so_thieu_hut"] = sum(clean[f"chi_so_{idx}"] for idx in range(1, 13))
        by_commune[(hk, xk)] = clean

        drec = by_district.setdefault(hk, _empty_deprivation_rec(rec.get("huyen")))
        _add_deprivation_rec(drec, clean)

    return by_district, by_commune, warnings


def _find_first_deprivation_data_row(ws: Any) -> int:
    """Tìm dòng đầu tiên có dữ liệu địa bàn của mẫu 4.

    Template thường có header số thứ tự chỉ số ở dòng 9 và dòng dữ liệu đầu ở dòng 10.
    Dùng rule mềm để không phụ thuộc cứng vào số dòng.
    """
    for row in range(1, ws.max_row + 1):
        a_val = str(ws.cell(row, 1).value or "").strip()
        b_key = _norm(ws.cell(row, 2).value)
        if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
            return row
    return 10


def _deprivation_values_for_row(rec: dict[str, Any] | None) -> list[int]:
    if not rec:
        return [0] * 14
    indicators = [int(rec.get(f"chi_so_{idx}") or 0) for idx in range(1, 13)]
    return [
        int(rec.get("tong_ho_ngheo") or 0),
        sum(indicators),
        *indicators,
    ]


def _write_deprivation_count_template_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 4 vào vùng C:P, giữ nguyên layout/header template."""
    current_district_key = ""
    filled = 0
    start_row = _find_first_deprivation_data_row(ws)

    for row in range(start_row, ws.max_row + 1):
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        if not label:
            continue

        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        values = _deprivation_values_for_row(rec)
        # C:P = tổng hộ nghèo, tổng số thiếu hụt, 12 chỉ số thiếu hụt.
        for offset, value in enumerate(values, start=3):
            ws.cell(row, offset).value = value
            ws.cell(row, offset).number_format = "#,##0"
        if rec:
            filled += 1

    return filled


# ───────────────────────────── template 5/7: deprivation ratio helpers ─────────────────────────────

def _deprivation_ratio_values_for_row(rec: dict[str, Any] | None) -> list[Any]:
    """Trả về C:O cho mẫu 5/7.

    C = tổng số hộ trong nhóm (hộ nghèo với mẫu 5, hộ cận nghèo với mẫu 7).
    D:O = tỷ lệ (%) hộ trong nhóm thiếu từng chỉ số DVXHCB trên tổng số hộ của dòng.
    Nếu tổng hộ = 0 thì để trống 12 cột tỷ lệ, giống biểu mẫu gốc và tránh tạo tỷ lệ 0 giả.
    """
    if not rec:
        return [0] + [None] * 12
    total = int(rec.get("tong_ho_ngheo") or 0)
    if total <= 0:
        return [0] + [None] * 12
    ratios: list[float] = []
    for idx in range(1, 13):
        count = int(rec.get(f"chi_so_{idx}") or 0)
        ratios.append(round(count / total * 100, 2))
    return [total, *ratios]


def _write_deprivation_ratio_template_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 5/7 vào vùng C:O, giữ nguyên layout/header template.

    Mẫu 5 là bản tỷ lệ của mẫu 4; mẫu 7 là bản tỷ lệ của mẫu 6:
    - C: tổng số hộ trong nhóm.
    - D:O: tỷ lệ (%) của 12 chỉ số thiếu hụt DVXHCB.
    """
    current_district_key = ""
    filled = 0
    start_row = _find_first_deprivation_data_row(ws)

    for row in range(start_row, ws.max_row + 1):
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        if not label:
            continue

        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        values = _deprivation_ratio_values_for_row(rec)
        # C:O = tổng hộ nghèo + 12 tỷ lệ chỉ số thiếu hụt.
        for offset, value in enumerate(values, start=3):
            cell = ws.cell(row, offset)
            cell.value = value
            cell.number_format = "#,##0" if offset == 3 else "0.00"
        if rec:
            filled += 1

    return filled




# ───────────────────────────── template 8: vulnerable groups helpers ─────────────────────────────

TEMPLATE8_VALUE_COLUMNS = [
    "tong_ho_dan_cu",
    "so_ho_dtts",
    "so_ho_ngheo",
    "so_ho_can_ngheo",
    "so_ho_ngheo_dtts",
    "so_ho_can_ngheo_dtts",
    "so_ho_ngheo_khong_knld",
    "so_ho_can_ngheo_khong_knld",
    "so_ho_ngheo_co_cong",
    "so_ho_can_ngheo_co_cong",
]


def _empty_template8_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for base in TEMPLATE8_VALUE_COLUMNS:
        rec[f"{base}_ho"] = 0
        rec[f"{base}_khau"] = 0
    return rec


def _add_template8_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    for base in TEMPLATE8_VALUE_COLUMNS:
        target[f"{base}_ho"] = int(target.get(f"{base}_ho") or 0) + int(source.get(f"{base}_ho") or 0)
        target[f"{base}_khau"] = int(target.get(f"{base}_khau") or 0) + int(source.get(f"{base}_khau") or 0)


def _template8_ethnic_condition(conn: sqlite3.Connection) -> tuple[str, list[str], list[str]]:
    """Điều kiện hộ dân tộc thiểu số cho mẫu 8.

    Ưu tiên `dan_toc_chi_tiet <> 'Kinh'` vì mẫu 8 ghi "dân tộc thiểu số" nói chung.
    Nếu DB không có cột này mới fallback sang `nhom_dtts = 1`.
    """
    if _column_exists(conn, "ho_ngheo", "dan_toc_chi_tiet"):
        cond = "dan_toc_chi_tiet IS NOT NULL AND TRIM(dan_toc_chi_tiet) <> '' AND dan_toc_chi_tiet <> ?"
        return cond, ["Kinh"], []
    if _column_exists(conn, "ho_ngheo", "nhom_dtts"):
        return "nhom_dtts = 1", [], ["DB không có cột dan_toc_chi_tiet; mẫu 8 dùng nhom_dtts=1 để xác định hộ dân tộc thiểu số."]
    raise ValueError("DB thiếu cả cột dan_toc_chi_tiet và nhom_dtts nên chưa thể tính nhóm dân tộc thiểu số cho mẫu 8.")


def _build_template8_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính mẫu 8 theo huyện/xã và theo 2 dòng Hộ/Nhân khẩu.

    Cột D:M của template:
    - D: Tổng số hộ dân cư.
    - E: Số hộ dân tộc thiểu số.
    - F/G: Tổng số hộ nghèo / hộ cận nghèo.
    - H/I: Hộ nghèo / cận nghèo dân tộc thiểu số.
    - J/K: Hộ nghèo / cận nghèo không có khả năng lao động.
    - L/M: Hộ nghèo / cận nghèo có đối tượng người có công với cách mạng.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    required_cols = ["phan_loai", "so_nhan_khau", "nhom_khong_knld", "nhom_co_cong"]
    missing_cols = [col for col in required_cols if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError("DB thiếu cột để xuất mẫu 8: " + ", ".join(missing_cols))

    ethnic_cond, ethnic_params, ethnic_warnings = _template8_ethnic_condition(conn)
    warnings.extend(ethnic_warnings)

    where, params = _sql_filter(year, huyen)
    params = list(params)

    def count_case(cond: str) -> str:
        return f"COUNT(DISTINCT CASE WHEN {cond} THEN id_ho END)"

    def sum_case(cond: str) -> str:
        return f"COALESCE(SUM(CASE WHEN {cond} THEN so_nhan_khau ELSE 0 END), 0)"

    # Thứ tự params phải khớp đúng thứ tự placeholder xuất hiện trong SELECT.
    # ethnic_params thường là ["Kinh"] khi dùng điều kiện dan_toc_chi_tiet <> ?.
    query_params: list[Any] = []
    query_params.extend(ethnic_params)                  # so_ho_dtts_ho
    query_params.extend(ethnic_params)                  # so_ho_dtts_khau
    query_params.extend([POOR])                         # so_ho_ngheo_ho
    query_params.extend([POOR])                         # so_ho_ngheo_khau
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_ho
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_khau
    query_params.extend([POOR, *ethnic_params])         # so_ho_ngheo_dtts_ho
    query_params.extend([POOR, *ethnic_params])         # so_ho_ngheo_dtts_khau
    query_params.extend([NEAR_POOR, *ethnic_params])    # so_ho_can_ngheo_dtts_ho
    query_params.extend([NEAR_POOR, *ethnic_params])    # so_ho_can_ngheo_dtts_khau
    query_params.extend([POOR])                         # so_ho_ngheo_khong_knld_ho
    query_params.extend([POOR])                         # so_ho_ngheo_khong_knld_khau
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_khong_knld_ho
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_khong_knld_khau
    query_params.extend([POOR])                         # so_ho_ngheo_co_cong_ho
    query_params.extend([POOR])                         # so_ho_ngheo_co_cong_khau
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_co_cong_ho
    query_params.extend([NEAR_POOR])                    # so_ho_can_ngheo_co_cong_khau
    query_params.extend(params)

    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            {HOUSEHOLD_COUNT} AS tong_ho_dan_cu_ho,
            COALESCE(SUM(so_nhan_khau), 0) AS tong_ho_dan_cu_khau,
            {count_case(ethnic_cond)} AS so_ho_dtts_ho,
            {sum_case(ethnic_cond)} AS so_ho_dtts_khau,
            {count_case('phan_loai = ?')} AS so_ho_ngheo_ho,
            {sum_case('phan_loai = ?')} AS so_ho_ngheo_khau,
            {count_case('phan_loai = ?')} AS so_ho_can_ngheo_ho,
            {sum_case('phan_loai = ?')} AS so_ho_can_ngheo_khau,
            {count_case(f'phan_loai = ? AND {ethnic_cond}')} AS so_ho_ngheo_dtts_ho,
            {sum_case(f'phan_loai = ? AND {ethnic_cond}')} AS so_ho_ngheo_dtts_khau,
            {count_case(f'phan_loai = ? AND {ethnic_cond}')} AS so_ho_can_ngheo_dtts_ho,
            {sum_case(f'phan_loai = ? AND {ethnic_cond}')} AS so_ho_can_ngheo_dtts_khau,
            {count_case('phan_loai = ? AND nhom_khong_knld = 1')} AS so_ho_ngheo_khong_knld_ho,
            {sum_case('phan_loai = ? AND nhom_khong_knld = 1')} AS so_ho_ngheo_khong_knld_khau,
            {count_case('phan_loai = ? AND nhom_khong_knld = 1')} AS so_ho_can_ngheo_khong_knld_ho,
            {sum_case('phan_loai = ? AND nhom_khong_knld = 1')} AS so_ho_can_ngheo_khong_knld_khau,
            {count_case('phan_loai = ? AND nhom_co_cong = 1')} AS so_ho_ngheo_co_cong_ho,
            {sum_case('phan_loai = ? AND nhom_co_cong = 1')} AS so_ho_ngheo_co_cong_khau,
            {count_case('phan_loai = ? AND nhom_co_cong = 1')} AS so_ho_can_ngheo_co_cong_ho,
            {sum_case('phan_loai = ? AND nhom_co_cong = 1')} AS so_ho_can_ngheo_co_cong_khau
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong
    """
    rows = conn.execute(sql, query_params).fetchall()
    cols = [d[0] for d in conn.execute(sql, query_params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw = dict(zip(cols, row))
        hk = _geo_key(raw.get("huyen"))
        xk = _geo_key(raw.get("xa_phuong"))
        if not hk or not xk:
            continue
        rec = _empty_template8_rec(raw.get("huyen"), raw.get("xa_phuong"))
        for base in TEMPLATE8_VALUE_COLUMNS:
            rec[f"{base}_ho"] = int(raw.get(f"{base}_ho") or 0)
            rec[f"{base}_khau"] = int(raw.get(f"{base}_khau") or 0)
        by_commune[(hk, xk)] = rec
        drec = by_district.setdefault(hk, _empty_template8_rec(raw.get("huyen")))
        _add_template8_rec(drec, rec)

    return by_district, by_commune, warnings


def _find_first_template8_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        if _norm(ws.cell(row, 3).value) == "ho":
            a_val = str(ws.cell(row, 1).value or "").strip()
            b_key = _norm(ws.cell(row, 2).value)
            if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
                return row
    return 11


def _template8_values_for_row(rec: dict[str, Any] | None, *, suffix: str) -> list[int]:
    if not rec:
        return [0] * len(TEMPLATE8_VALUE_COLUMNS)
    return [int(rec.get(f"{base}_{suffix}") or 0) for base in TEMPLATE8_VALUE_COLUMNS]


def _write_template8_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 8 vào vùng D:M, mỗi địa bàn gồm 2 dòng Hộ/Nhân khẩu."""
    current_district_key = ""
    filled = 0
    row = _find_first_template8_data_row(ws)

    while row <= ws.max_row:
        row_type = _norm(ws.cell(row, 3).value)
        if row_type != "ho":
            row += 1
            continue

        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None

        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        ho_values = _template8_values_for_row(rec, suffix="ho")
        khau_values = _template8_values_for_row(rec, suffix="khau")

        for offset, value in enumerate(ho_values, start=4):
            cell = ws.cell(row, offset)
            cell.value = value
            _format_movement_number_cell(cell)

        next_row = row + 1
        if next_row <= ws.max_row and _norm(ws.cell(next_row, 3).value) in {"nhan khau", "nhan_khau"}:
            for offset, value in enumerate(khau_values, start=4):
                cell = ws.cell(next_row, offset)
                cell.value = value
                _format_movement_number_cell(cell)

        if rec:
            filled += 1
        row += 2

    return filled


# ───────────────────────────── template 9: ethnicity helpers ─────────────────────────────

TEMPLATE9_ETHNIC_COLUMNS = [
    "ede",
    "ma",
    "muong",
    "thai",
    "mnong",
    "tay",
    "nung",
    "mong",
    "dao",
    "khac",
]

TEMPLATE9_VALUE_COLUMNS = [
    "ngheo_tong",
    "ngheo_kinh",
    "ngheo_dtts",
    *[f"ngheo_{eth}" for eth in TEMPLATE9_ETHNIC_COLUMNS],
    "can_ngheo_tong",
    "can_ngheo_kinh",
    "can_ngheo_dtts",
    *[f"can_ngheo_{eth}" for eth in TEMPLATE9_ETHNIC_COLUMNS],
]

TEMPLATE9_ETHNIC_ALIASES: dict[str, str] = {
    _norm("Ê đê"): "ede",
    _norm("Ê-đê"): "ede",
    _norm("Ede"): "ede",
    _norm("Êđê"): "ede",
    _norm("Mạ"): "ma",
    _norm("Mường"): "muong",
    _norm("Thái"): "thai",
    _norm("M'Nông"): "mnong",
    _norm("Mnông"): "mnong",
    _norm("M Nông"): "mnong",
    _norm("M'Nong"): "mnong",
    _norm("Tày"): "tay",
    _norm("Nùng"): "nung",
    _norm("Mông"): "mong",
    _norm("H'Mông"): "mong",
    _norm("Hmong"): "mong",
    _norm("Dao"): "dao",
}


def _template9_ethnic_key(value: Any) -> str:
    """Map dân tộc chi tiết trong DB vào 10 cột chi tiết của mẫu 9."""
    key = _norm(value)
    if not key or key == _norm("Kinh"):
        return "kinh"
    return TEMPLATE9_ETHNIC_ALIASES.get(key, "khac")


def _empty_template9_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for col in TEMPLATE9_VALUE_COLUMNS:
        rec[col] = 0
    return rec


def _add_template9_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    for col in TEMPLATE9_VALUE_COLUMNS:
        target[col] = int(target.get(col) or 0) + int(source.get(col) or 0)


def _add_template9_value(rec: dict[str, Any], *, phan_loai: Any, dan_toc: Any, households: int) -> None:
    """Cộng số hộ vào nhóm nghèo/cận nghèo và cột dân tộc tương ứng."""
    households = int(households or 0)
    if households <= 0:
        return

    if phan_loai == POOR:
        prefix = "ngheo"
    elif phan_loai == NEAR_POOR:
        prefix = "can_ngheo"
    else:
        return

    ethnic_key = _template9_ethnic_key(dan_toc)
    rec[f"{prefix}_tong"] = int(rec.get(f"{prefix}_tong") or 0) + households
    if ethnic_key == "kinh":
        rec[f"{prefix}_kinh"] = int(rec.get(f"{prefix}_kinh") or 0) + households
    else:
        rec[f"{prefix}_dtts"] = int(rec.get(f"{prefix}_dtts") or 0) + households
        rec[f"{prefix}_{ethnic_key}"] = int(rec.get(f"{prefix}_{ethnic_key}") or 0) + households


def _build_template9_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính mẫu 9 theo huyện/xã: hộ nghèo và hộ cận nghèo theo dân tộc.

    Cell map template 9:
    - C: Tổng số hộ nghèo.
    - D: Hộ nghèo dân tộc Kinh.
    - E: Hộ nghèo DTTS.
    - F:O: chi tiết DTTS của hộ nghèo: Ê đê, Mạ, Mường, Thái, M'Nông, Tày, Nùng, Mông, Dao, DT khác.
    - P: Tổng số hộ cận nghèo.
    - Q: Hộ cận nghèo dân tộc Kinh.
    - R: Hộ cận nghèo DTTS.
    - S:AB: chi tiết DTTS của hộ cận nghèo theo cùng thứ tự.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    required_cols = ["phan_loai", "dan_toc_chi_tiet"]
    missing_cols = [col for col in required_cols if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError("DB thiếu cột để xuất mẫu 9: " + ", ".join(missing_cols))

    where, params = _sql_filter(year, huyen)
    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            phan_loai,
            dan_toc_chi_tiet,
            {HOUSEHOLD_COUNT} AS so_ho
        FROM ho_ngheo
        {where}
        AND phan_loai IN (?, ?) 
        GROUP BY huyen, xa_phuong, phan_loai, dan_toc_chi_tiet
    """ if where else f"""
        SELECT
            huyen,
            xa_phuong,
            phan_loai,
            dan_toc_chi_tiet,
            {HOUSEHOLD_COUNT} AS so_ho
        FROM ho_ngheo
        WHERE phan_loai IN (?, ?)
        GROUP BY huyen, xa_phuong, phan_loai, dan_toc_chi_tiet
    """
    query_params = list(params) + [POOR, NEAR_POOR] if where else [POOR, NEAR_POOR]
    rows = conn.execute(sql, query_params).fetchall()

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}
    seen_other_ethnic: set[str] = set()

    for huyen_name, xa_name, phan_loai, dan_toc, so_ho in rows:
        hk = _geo_key(huyen_name)
        xk = _geo_key(xa_name)
        if not hk or not xk:
            continue
        crec = by_commune.setdefault((hk, xk), _empty_template9_rec(huyen_name, xa_name))
        _add_template9_value(crec, phan_loai=phan_loai, dan_toc=dan_toc, households=int(so_ho or 0))
        ethnic_key = _template9_ethnic_key(dan_toc)
        if ethnic_key == "khac" and _norm(dan_toc) and _norm(dan_toc) != _norm("Kinh"):
            seen_other_ethnic.add(str(dan_toc))

    for (hk, _xk), crec in by_commune.items():
        drec = by_district.setdefault(hk, _empty_template9_rec(crec.get("huyen")))
        _add_template9_rec(drec, crec)

    if seen_other_ethnic:
        warnings.append(
            "Mẫu 9: các dân tộc ngoài danh sách cột cố định được cộng vào cột 'DT Khác': "
            + ", ".join(sorted(seen_other_ethnic))
            + "."
        )

    return by_district, by_commune, warnings


def _find_first_template9_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        a_val = str(ws.cell(row, 1).value or "").strip()
        b_key = _norm(ws.cell(row, 2).value)
        if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
            return row
    return 11


def _template9_values_for_row(rec: dict[str, Any] | None) -> list[int]:
    if not rec:
        return [0] * len(TEMPLATE9_VALUE_COLUMNS)
    return [int(rec.get(col) or 0) for col in TEMPLATE9_VALUE_COLUMNS]


def _write_template9_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 9 vào vùng C:AB, mỗi địa bàn một dòng."""
    current_district_key = ""
    filled = 0
    start_row = _find_first_template9_data_row(ws)

    for row in range(start_row, ws.max_row + 1):
        label = ws.cell(row, 2).value
        if not label:
            continue

        stt = ws.cell(row, 1).value
        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None

        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        values = _template9_values_for_row(rec)
        # C:AB = 26 cột: nhóm hộ nghèo C:O và hộ cận nghèo P:AB.
        for offset, value in enumerate(values, start=3):
            ws.cell(row, offset).value = value
            ws.cell(row, offset).number_format = "#,##0"

        if rec:
            filled += 1

    return filled




# ───────────────────────────── template 10: poverty causes helpers ─────────────────────────────

TEMPLATE10_CAUSE_COLUMNS: list[tuple[str, str]] = [
    ("nn_thieu_dat", "Không có đất sản xuất"),
    ("nn_thieu_von", "Không có vốn sản xuất, kinh doanh"),
    ("nn_thieu_lao_dong", "Không có lao động"),
    ("nn_thieu_cong_cu", "Không có công cụ/phương tiện sản xuất"),
    ("nn_thieu_kien_thuc", "Không có kiến thức về sản xuất"),
    ("nn_thieu_ky_nang", "Không có kỹ năng lao động sản xuất"),
    ("nn_om_dau", "Có người ốm đau, bệnh nặng, tai nạn"),
    ("nn_khac", "Nguyên nhân khác"),
]


def _empty_template10_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for col, _label in TEMPLATE10_CAUSE_COLUMNS:
        rec[f"poor_{col}"] = 0
        rec[f"near_{col}"] = 0
    return rec


def _add_template10_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    for col, _label in TEMPLATE10_CAUSE_COLUMNS:
        target[f"poor_{col}"] = int(target.get(f"poor_{col}") or 0) + int(source.get(f"poor_{col}") or 0)
        target[f"near_{col}"] = int(target.get(f"near_{col}") or 0) + int(source.get(f"near_{col}") or 0)


def _build_template10_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính mẫu 10 theo huyện/xã: hộ nghèo, hộ cận nghèo theo 8 nguyên nhân nghèo.

    Cell map template 10:
    - Mỗi địa bàn gồm 3 dòng: tổng hộ nghèo + cận nghèo, Hộ nghèo, Hộ cận nghèo.
    - C:J lần lượt là 8 nguyên nhân nghèo/cận nghèo.
    - Dòng tổng = dòng Hộ nghèo + dòng Hộ cận nghèo theo từng nguyên nhân.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    required_cols = ["phan_loai", *[col for col, _label in TEMPLATE10_CAUSE_COLUMNS]]
    missing_cols = [col for col in required_cols if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError("DB thiếu cột để xuất mẫu 10: " + ", ".join(missing_cols))

    where, params = _sql_filter(year, huyen)
    if where:
        where += " AND phan_loai IN (?, ?)"
    else:
        where = "WHERE phan_loai IN (?, ?)"
    params = list(params) + [POOR, NEAR_POOR]

    cause_sql = ",\n            ".join(
        f"COUNT(DISTINCT CASE WHEN {col} = 1 THEN id_ho END) AS {col}"
        for col, _label in TEMPLATE10_CAUSE_COLUMNS
    )
    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            phan_loai,
            {cause_sql}
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong, phan_loai
    """
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw = dict(zip(cols, row))
        hk = _geo_key(raw.get("huyen"))
        xk = _geo_key(raw.get("xa_phuong"))
        if not hk or not xk:
            continue
        crec = by_commune.setdefault((hk, xk), _empty_template10_rec(raw.get("huyen"), raw.get("xa_phuong")))
        prefix = "poor" if raw.get("phan_loai") == POOR else "near" if raw.get("phan_loai") == NEAR_POOR else ""
        if not prefix:
            continue
        for col, _label in TEMPLATE10_CAUSE_COLUMNS:
            crec[f"{prefix}_{col}"] = int(raw.get(col) or 0)

    for (hk, _xk), crec in by_commune.items():
        drec = by_district.setdefault(hk, _empty_template10_rec(crec.get("huyen")))
        _add_template10_rec(drec, crec)

    return by_district, by_commune, warnings


def _find_first_template10_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        a_val = str(ws.cell(row, 1).value or "").strip()
        b_key = _norm(ws.cell(row, 2).value)
        if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
            return row
    return 11


def _template10_values_for_row(rec: dict[str, Any] | None, group: str = "total") -> list[int]:
    if not rec:
        return [0] * len(TEMPLATE10_CAUSE_COLUMNS)
    values: list[int] = []
    for col, _label in TEMPLATE10_CAUSE_COLUMNS:
        poor = int(rec.get(f"poor_{col}") or 0)
        near = int(rec.get(f"near_{col}") or 0)
        if group == "poor":
            values.append(poor)
        elif group == "near":
            values.append(near)
        else:
            values.append(poor + near)
    return values


def _write_template10_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 10 vào vùng C:J, mỗi địa bàn 3 dòng: tổng, Hộ nghèo, Hộ cận nghèo."""
    current_district_key = ""
    filled = 0
    row = _find_first_template10_data_row(ws)

    while row <= ws.max_row:
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        label_key = _geo_key(label)
        if not label or _norm(label) in {_norm(POOR), _norm(NEAR_POOR)}:
            row += 1
            continue

        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        # Dòng địa bàn: tổng hộ nghèo + hộ cận nghèo.
        for offset, value in enumerate(_template10_values_for_row(rec, "total"), start=3):
            ws.cell(row, offset).value = value
            ws.cell(row, offset).number_format = "#,##0"

        # Hai dòng dưới: Hộ nghèo và Hộ cận nghèo.
        if row + 1 <= ws.max_row and _norm(ws.cell(row + 1, 2).value) == _norm(POOR):
            for offset, value in enumerate(_template10_values_for_row(rec, "poor"), start=3):
                ws.cell(row + 1, offset).value = value
                ws.cell(row + 1, offset).number_format = "#,##0"
        if row + 2 <= ws.max_row and _norm(ws.cell(row + 2, 2).value) == _norm(NEAR_POOR):
            for offset, value in enumerate(_template10_values_for_row(rec, "near"), start=3):
                ws.cell(row + 2, offset).value = value
                ws.cell(row + 2, offset).number_format = "#,##0"

        if rec:
            filled += 1
        row += 3

    return filled


# ───────────────────────────── template 11: child deprivation helpers ─────────────────────────────

TEMPLATE11_CHILD_VALUE_COLUMNS = [
    "poor_total_children",
    "poor_bhyt_children",
    "poor_nutrition_children",
    "poor_school_children",
    "near_total_children",
    "near_bhyt_children",
    "near_nutrition_children",
    "near_school_children",
]


def _child_total_column(conn: sqlite3.Connection) -> tuple[str, list[str]]:
    """Chọn cột tổng số trẻ em trong hộ.

    DB hiện có cả `so_tre_em` và `so_tre_em_trong_ho`, thường trùng nhau.
    Ưu tiên `so_tre_em` vì tên ngắn và đã được dùng trong các câu hỏi Q&A.
    """
    if _column_exists(conn, "ho_ngheo", "so_tre_em"):
        return "so_tre_em", []
    if _column_exists(conn, "ho_ngheo", "so_tre_em_trong_ho"):
        return "so_tre_em_trong_ho", [
            "DB không có cột so_tre_em; mẫu 11 dùng so_tre_em_trong_ho làm tổng số trẻ em."
        ]
    raise ValueError("DB thiếu cả cột so_tre_em và so_tre_em_trong_ho nên chưa thể xuất mẫu 11.")


def _child_deprivation_columns(conn: sqlite3.Connection) -> tuple[dict[str, str], list[str]]:
    preferred = {
        "bhyt": "so_tre_thieu_bhyt",
        "nutrition": "so_tre_thieu_dinh_duong",
        "school": "so_tre_thieu_di_hoc",
    }
    fallback = {
        "bhyt": "te_th_bhyt",
        "nutrition": "te_th_dinh_duong",
        "school": "te_th_di_hoc",
    }
    warnings: list[str] = []
    selected: dict[str, str] = {}
    for key, preferred_col in preferred.items():
        if _column_exists(conn, "ho_ngheo", preferred_col):
            selected[key] = preferred_col
            continue
        fallback_col = fallback[key]
        if _column_exists(conn, "ho_ngheo", fallback_col):
            selected[key] = fallback_col
            warnings.append(
                f"DB chua co cot {preferred_col}; mau 11 tam dung {fallback_col}, gia tri la so ho/case co tre thieu chi tieu chu khong phai so tre."
            )
            continue
        raise ValueError(f"DB thieu cot de xuat mau 11: {preferred_col} hoac {fallback_col}")
    return selected, warnings


def _empty_template11_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for col in TEMPLATE11_CHILD_VALUE_COLUMNS:
        rec[col] = 0
    return rec


def _add_template11_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    for col in TEMPLATE11_CHILD_VALUE_COLUMNS:
        target[col] = int(target.get(col) or 0) + int(source.get(col) or 0)


def _build_template11_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính mẫu 11 theo huyện/xã.

    Cell map C:J:
    - C:F: trẻ em thuộc hộ nghèo: tổng số trẻ em, thiếu BHYT, thiếu dinh dưỡng, thiếu đi học.
    - G:J: trẻ em thuộc hộ cận nghèo: tổng số trẻ em, thiếu BHYT, thiếu dinh dưỡng, thiếu đi học.

    Lưu ý dữ liệu DB hiện lưu các chỉ tiêu trẻ em ở các cột `te_th_*` cấp dòng hộ.
    Exporter dùng SUM trực tiếp các cột này; không nhân với tổng số trẻ em để tránh phóng đại khi
    cờ chỉ tiêu đang biểu thị hộ/trường hợp có thiếu hụt.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    child_total_col, total_warnings = _child_total_column(conn)
    warnings.extend(total_warnings)
    child_deprivation_cols, deprivation_warnings = _child_deprivation_columns(conn)
    warnings.extend(deprivation_warnings)

    required_cols = ["phan_loai", child_total_col, *child_deprivation_cols.values()]
    missing_cols = [col for col in required_cols if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError("DB thiếu cột để xuất mẫu 11: " + ", ".join(missing_cols))

    where, params = _sql_filter(year, huyen)
    if where:
        where += " AND phan_loai IN (?, ?)"
    else:
        where = "WHERE phan_loai IN (?, ?)"
    params = list(params) + [POOR, NEAR_POOR]

    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            phan_loai,
            COALESCE(SUM({child_total_col}), 0) AS total_children,
            COALESCE(SUM({child_deprivation_cols["bhyt"]}), 0) AS bhyt_children,
            COALESCE(SUM({child_deprivation_cols["nutrition"]}), 0) AS nutrition_children,
            COALESCE(SUM({child_deprivation_cols["school"]}), 0) AS school_children
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong, phan_loai
    """
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw = dict(zip(cols, row))
        hk = _geo_key(raw.get("huyen"))
        xk = _geo_key(raw.get("xa_phuong"))
        if not hk or not xk:
            continue
        rec = by_commune.setdefault((hk, xk), _empty_template11_rec(raw.get("huyen"), raw.get("xa_phuong")))
        prefix = "poor" if raw.get("phan_loai") == POOR else "near" if raw.get("phan_loai") == NEAR_POOR else ""
        if not prefix:
            continue
        rec[f"{prefix}_total_children"] = int(raw.get("total_children") or 0)
        rec[f"{prefix}_bhyt_children"] = int(raw.get("bhyt_children") or 0)
        rec[f"{prefix}_nutrition_children"] = int(raw.get("nutrition_children") or 0)
        rec[f"{prefix}_school_children"] = int(raw.get("school_children") or 0)

    for (hk, _xk), crec in by_commune.items():
        drec = by_district.setdefault(hk, _empty_template11_rec(crec.get("huyen")))
        _add_template11_rec(drec, crec)

    return by_district, by_commune, warnings


def _find_first_template11_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        a_val = str(ws.cell(row, 1).value or "").strip()
        b_key = _norm(ws.cell(row, 2).value)
        if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
            return row
    return 12


def _template11_values_for_row(rec: dict[str, Any] | None) -> list[int]:
    if not rec:
        return [0] * len(TEMPLATE11_CHILD_VALUE_COLUMNS)
    return [int(rec.get(col) or 0) for col in TEMPLATE11_CHILD_VALUE_COLUMNS]


def _write_template11_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 11 vào vùng C:J, giữ nguyên layout/header template."""
    current_district_key = ""
    filled = 0
    start_row = _find_first_template11_data_row(ws)

    for row in range(start_row, ws.max_row + 1):
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        if not label:
            continue

        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        values = _template11_values_for_row(rec)
        for offset, value in enumerate(values, start=3):
            ws.cell(row, offset).value = value
            ws.cell(row, offset).number_format = "#,##0"
        if rec:
            filled += 1

    return filled



# ───────────────────────────── template 12: multidimensional poverty summary helpers ─────────────────────────────

TEMPLATE12_VALUE_COLUMNS = [
    # C:J - Tổng số hộ/khẩu chung theo dân tộc
    "total_households",
    "total_kinh_households",
    "total_dtts_households",
    "total_dttc_households",
    "total_population",
    "total_kinh_population",
    "total_dtts_population",
    "total_dttc_population",
    # K:Q - Hộ nghèo theo chuẩn đa chiều và nhóm đặc thù
    "poor_households",
    "poor_kinh_households",
    "poor_dtts_households",
    "poor_dttc_households",
    "poor_policy_households",
    "poor_no_labor_households",
    "poor_female_head_households",
    # R:U - Khẩu hộ nghèo theo dân tộc
    "poor_population",
    "poor_kinh_population",
    "poor_dtts_population",
    "poor_dttc_population",
]


def _empty_template12_rec(huyen_name: Any = None, xa_name: Any = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"huyen": huyen_name, "xa_phuong": xa_name}
    for col in TEMPLATE12_VALUE_COLUMNS:
        rec[col] = 0
    return rec


def _add_template12_rec(target: dict[str, Any], source: dict[str, Any]) -> None:
    for col in TEMPLATE12_VALUE_COLUMNS:
        target[col] = int(target.get(col) or 0) + int(source.get(col) or 0)


def _template12_dttc_condition(conn: sqlite3.Connection) -> tuple[str, list[str]]:
    """Điều kiện dân tộc thiểu số tại chỗ cho mẫu 12.

    Ưu tiên cột `dan_toc_tai_cho = 'Có'` vì header mẫu ghi rõ DT tại chỗ.
    Nếu DB khác thiếu cột này thì fallback sang `nhom_dtts = 1` và báo warning.
    """
    if _column_exists(conn, "ho_ngheo", "dan_toc_tai_cho"):
        return "dan_toc_tai_cho = 'Có'", []
    if _column_exists(conn, "ho_ngheo", "nhom_dtts"):
        return "nhom_dtts = 1", [
            "DB không có cột dan_toc_tai_cho; mẫu 12 dùng nhom_dtts=1 để xác định DTTS tại chỗ."
        ]
    raise ValueError("DB thiếu cả cột dan_toc_tai_cho và nhom_dtts nên chưa thể tính DTTS tại chỗ cho mẫu 12.")


def _template12_female_head_condition(conn: sqlite3.Connection) -> tuple[str, list[str]]:
    """Điều kiện chủ hộ là nữ cho mẫu 12."""
    if _column_exists(conn, "ho_ngheo", "nhom_chu_ho_nu"):
        return "nhom_chu_ho_nu = 1", []
    if _column_exists(conn, "ho_ngheo", "gioi_tinh"):
        return "gioi_tinh = 'Nữ'", [
            "DB không có cột nhom_chu_ho_nu; mẫu 12 dùng gioi_tinh='Nữ' để tính chủ hộ là nữ."
        ]
    raise ValueError("DB thiếu cả cột nhom_chu_ho_nu và gioi_tinh nên chưa thể tính cột chủ hộ là nữ cho mẫu 12.")


def _build_template12_stats(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    huyen: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Tính mẫu 12 theo huyện/xã.

    Cell map C:X:
    - C:F: tổng số hộ chung, Kinh, DTTS chung, DTTS tại chỗ.
    - G:J: tổng số khẩu chung, Kinh, DTTS chung, DTTS tại chỗ.
    - K:Q: tổng số hộ nghèo, Kinh, DTTS chung, DTTS tại chỗ, hộ CSCC, hộ KCKNLĐ, chủ hộ là nữ.
    - R:U: tổng số khẩu hộ nghèo, Kinh, DTTS chung, DTTS tại chỗ.
    - V:X: tỷ lệ hộ nghèo = K/C, M/E, N/F nhân 100.
    """
    warnings: list[str] = []
    if year is None:
        year = _latest_year(conn)

    required_cols = [
        "phan_loai",
        "so_nhan_khau",
        "dan_toc_chi_tiet",
        "nhom_co_cong",
        "nhom_khong_knld",
    ]
    missing_cols = [col for col in required_cols if not _column_exists(conn, "ho_ngheo", col)]
    if missing_cols:
        raise ValueError("DB thiếu cột để xuất mẫu 12: " + ", ".join(missing_cols))

    dttc_cond, dttc_warnings = _template12_dttc_condition(conn)
    female_cond, female_warnings = _template12_female_head_condition(conn)
    warnings.extend(dttc_warnings)
    warnings.extend(female_warnings)

    dtts_cond = "dan_toc_chi_tiet IS NOT NULL AND TRIM(dan_toc_chi_tiet) <> '' AND dan_toc_chi_tiet <> 'Kinh'"
    kinh_cond = "dan_toc_chi_tiet = 'Kinh'"
    poor_cond = f"phan_loai = '{POOR}'"

    def count_case(cond: str) -> str:
        return f"COUNT(DISTINCT CASE WHEN {cond} THEN id_ho END)"

    def sum_case(cond: str) -> str:
        return f"COALESCE(SUM(CASE WHEN {cond} THEN so_nhan_khau ELSE 0 END), 0)"

    where, params = _sql_filter(year, huyen)

    sql = f"""
        SELECT
            huyen,
            xa_phuong,
            {HOUSEHOLD_COUNT} AS total_households,
            {count_case(kinh_cond)} AS total_kinh_households,
            {count_case(dtts_cond)} AS total_dtts_households,
            {count_case(dttc_cond)} AS total_dttc_households,
            COALESCE(SUM(so_nhan_khau), 0) AS total_population,
            {sum_case(kinh_cond)} AS total_kinh_population,
            {sum_case(dtts_cond)} AS total_dtts_population,
            {sum_case(dttc_cond)} AS total_dttc_population,
            {count_case(poor_cond)} AS poor_households,
            {count_case(f'{poor_cond} AND {kinh_cond}')} AS poor_kinh_households,
            {count_case(f'{poor_cond} AND {dtts_cond}')} AS poor_dtts_households,
            {count_case(f'{poor_cond} AND {dttc_cond}')} AS poor_dttc_households,
            {count_case(f'{poor_cond} AND nhom_co_cong = 1')} AS poor_policy_households,
            {count_case(f'{poor_cond} AND nhom_khong_knld = 1')} AS poor_no_labor_households,
            {count_case(f'{poor_cond} AND {female_cond}')} AS poor_female_head_households,
            {sum_case(poor_cond)} AS poor_population,
            {sum_case(f'{poor_cond} AND {kinh_cond}')} AS poor_kinh_population,
            {sum_case(f'{poor_cond} AND {dtts_cond}')} AS poor_dtts_population,
            {sum_case(f'{poor_cond} AND {dttc_cond}')} AS poor_dttc_population
        FROM ho_ngheo
        {where}
        GROUP BY huyen, xa_phuong
    """
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]

    by_commune: dict[tuple[str, str], dict[str, Any]] = {}
    by_district: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw = dict(zip(cols, row))
        hk = _geo_key(raw.get("huyen"))
        xk = _geo_key(raw.get("xa_phuong"))
        if not hk or not xk:
            continue
        rec = _empty_template12_rec(raw.get("huyen"), raw.get("xa_phuong"))
        for col in TEMPLATE12_VALUE_COLUMNS:
            rec[col] = int(raw.get(col) or 0)
        by_commune[(hk, xk)] = rec
        drec = by_district.setdefault(hk, _empty_template12_rec(raw.get("huyen")))
        _add_template12_rec(drec, rec)

    return by_district, by_commune, warnings


def _find_first_template12_data_row(ws: Any) -> int:
    for row in range(1, ws.max_row + 1):
        a_val = str(ws.cell(row, 1).value or "").strip()
        b_key = _norm(ws.cell(row, 2).value)
        if a_val == "1" and (b_key.startswith("huyen ") or b_key.startswith("thanh pho ")):
            return row
    return 11


def _template12_values_for_row(rec: dict[str, Any] | None) -> list[int]:
    if not rec:
        return [0] * len(TEMPLATE12_VALUE_COLUMNS)
    return [int(rec.get(col) or 0) for col in TEMPLATE12_VALUE_COLUMNS]


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "--":
            return None
        return float(value)
    except Exception:
        return None


def _clear_template12_invalid_denominators(ws: Any, row: int) -> int:
    """Xóa các ô mẫu số C:J nếu mâu thuẫn với số hộ/khẩu nghèo K:U.

    Không tự chế mẫu số mới từ DB. Nếu mẫu gốc có mẫu số bất khả thi, ví dụ
    tổng hộ dân cư nhỏ hơn số hộ nghèo, để trống ô đó và tỷ lệ tương ứng trả "--".

    Trả về số ô mẫu số đã bị xóa để caller có thể ghi warning tổng quát.
    """
    cleared = 0
    # (count_denominator_col, population_denominator_col, poor_count_col, poor_population_col)
    col_pairs = [
        (3, 7, 11, 18),   # tổng chung: C/G so với K/R
        (4, 8, 12, 19),   # Kinh: D/H so với L/S
        (5, 9, 13, 20),   # DTTS: E/I so với M/T
        (6, 10, 14, 21),  # DTTS tại chỗ: F/J so với N/U
    ]
    for count_col, population_col, poor_count_col, poor_population_col in col_pairs:
        den_count = _as_float_or_none(ws.cell(row, count_col).value)
        poor_count = _as_float_or_none(ws.cell(row, poor_count_col).value) or 0
        if den_count is not None and den_count < poor_count:
            ws.cell(row, count_col).value = None
            cleared += 1

        den_population = _as_float_or_none(ws.cell(row, population_col).value)
        poor_population = _as_float_or_none(ws.cell(row, poor_population_col).value) or 0
        if den_population is not None and den_population < poor_population:
            ws.cell(row, population_col).value = None
            cleared += 1
    return cleared


def _template12_ratio_or_dash(ws: Any, row: int, denominator_col: int, numerator_col: int) -> float | str:
    """Tính tỷ lệ mẫu 12 dạng static value để file không phụ thuộc Excel recalc.

    Trả "--" nếu mẫu số thiếu/không hợp lệ hoặc tử số lớn hơn mẫu số.
    Dùng static value thay vì công thức vì nhiều viewer/download pipeline không tính lại formula cache.
    """
    denominator = _as_float_or_none(ws.cell(row, denominator_col).value)
    numerator = _as_float_or_none(ws.cell(row, numerator_col).value) or 0
    if denominator is None or denominator <= 0 or numerator > denominator:
        return "--"
    return round(numerator / denominator * 100, 2)


def _write_template12_values(
    ws: Any,
    *,
    by_district: dict[str, dict[str, Any]],
    by_commune: dict[tuple[str, str], dict[str, Any]],
) -> int:
    """Ghi dữ liệu mẫu 12 theo phạm vi DB.

    Trong project này, bảng `ho_ngheo` đang chứa các hộ đã rà soát/phân loại
    gồm hộ nghèo, hộ cận nghèo và hộ không nghèo. Vì vậy C:J được hiểu là
    tổng hộ/khẩu chung trong phạm vi DB, không phải số mẫu còn lại trong file
    template gốc.

    Cell map:
    - C:J = toàn bộ hộ trong DB theo địa bàn, chia Kinh/DTTS/DTTS tại chỗ.
    - K:U = riêng hộ nghèo theo chuẩn đa chiều.
    - V:X = tỷ lệ hộ nghèo tính theo C, E, F tương ứng.
    """
    current_district_key = ""
    filled = 0
    start_row = _find_first_template12_data_row(ws)

    for row in range(start_row, ws.max_row + 1):
        stt = ws.cell(row, 1).value
        label = ws.cell(row, 2).value
        if not label:
            continue

        label_key = _geo_key(label)
        rec: dict[str, Any] | None = None
        if _row_is_district(stt, label):
            current_district_key = label_key
            rec = by_district.get(label_key)
        elif current_district_key and label_key:
            rec = by_commune.get((current_district_key, label_key))

        values = _template12_values_for_row(rec)

        # C:U = toàn bộ chỉ tiêu số lượng, ghi đè số mẫu gốc.
        for offset, value in enumerate(values, start=3):
            ws.cell(row, offset).value = value
            ws.cell(row, offset).number_format = "#,##0"

        # V:X = giá trị tỷ lệ tĩnh, không ghi công thức.
        # Lý do: nhiều viewer/download pipeline không tính formula cache, nên công thức
        # có thể hiện trắng nếu không mở bằng Excel. Ghi value giúp file luôn hiện số.
        ratio_values = [
            _template12_ratio_or_dash(ws, row, denominator_col=3, numerator_col=11),
            _template12_ratio_or_dash(ws, row, denominator_col=5, numerator_col=13),
            _template12_ratio_or_dash(ws, row, denominator_col=6, numerator_col=14),
        ]
        for offset, ratio_value in enumerate(ratio_values, start=22):
            cell = ws.cell(row, offset)
            cell.value = ratio_value
            cell.number_format = "0.00"

        if rec:
            filled += 1

    return filled


def _apply_template12_readable_widths(ws: Any, *, start_row: int | None = None) -> None:
    """Làm vùng số liệu mẫu 12 không hiện #### trong Excel.

    openpyxl không có AutoFit thật như Excel UI, nên dùng chiến lược an toàn:
    - giữ nguyên layout/template, chỉ nới tối thiểu các cột số C:X;
    - bật shrink_to_fit cho vùng dữ liệu để số dài tự co vừa ô;
    - đặt V:X rộng hơn một chút vì là tỷ lệ có 2 chữ số thập phân.
    """
    try:
        from openpyxl.utils import get_column_letter
    except Exception:
        return

    if start_row is None:
        start_row = _find_first_template12_data_row(ws)

    # Mẫu 12 có rất nhiều cột; không nên auto-fit quá rộng theo header dọc.
    # Các mức dưới đủ hiển thị số 4-5 chữ số và tỷ lệ 2 chữ số thập phân,
    # đồng thời vẫn giữ file tương đối gần layout mẫu gốc.
    # v20: tăng ngưỡng tối thiểu vì một số cột mẫu 12 đang hiển thị ###
    # khi mở trực tiếp bằng Excel/Windows. Giữ vừa đủ để không phá layout, nhưng
    # các số 4-6 chữ số và tỷ lệ 2 chữ số thập phân luôn nhìn được.
    min_width_by_col = {
        3: 10.2,   # C tổng hộ chung
        4: 9.4,
        5: 9.4,
        6: 9.8,
        7: 10.8,   # G tổng khẩu chung
        8: 10.0,
        9: 10.0,
        10: 10.2,
        11: 9.8,
        12: 9.4,
        13: 9.4,
        14: 9.8,
        15: 9.0,
        16: 9.2,
        17: 9.8,
        18: 10.2,
        19: 9.8,
        20: 9.8,
        21: 9.8,
        22: 11.0,  # V:X tỷ lệ
        23: 11.0,
        24: 11.0,
    }

    for col_idx, min_width in min_width_by_col.items():
        col_letter = get_column_letter(col_idx)
        current = ws.column_dimensions[col_letter].width or 0
        ws.column_dimensions[col_letter].width = max(float(current or 0), min_width)

    # Bật shrink-to-fit cho vùng dữ liệu; không đụng header vì header mẫu thường xoay dọc.
    for row in range(start_row, ws.max_row + 1):
        if not ws.cell(row, 2).value:
            continue
        for col in range(3, 25):
            cell = ws.cell(row, col)
            try:
                cell.alignment = cell.alignment.copy(
                    horizontal="center",
                    vertical="center",
                    wrap_text=False,
                    shrink_to_fit=True,
                )
            except Exception:
                pass

# ───────────────────────────── public API ─────────────────────────────

def export_template_xlsx(
    template_id: int | str,
    *,
    db_path: str | Path,
    samples_dir: str | Path,
    year: int | None = None,
    huyen: str | None = None,
) -> TemplateExcelResult:
    """Xuất Excel bám đúng file mẫu gốc.

    Hiện đã triển khai chắc cho mẫu 1-12 theo đúng layout file mẫu gốc.
    """
    template_id = int(template_id)
    if template_id not in SUPPORTED_TEMPLATE_IDS:
        raise NotImplementedError(
            f"Exporter theo đúng template hiện hỗ trợ mẫu 1-12. "
            f"Mẫu {template_id} chưa nằm trong danh sách hỗ trợ."
        )

    try:
        from openpyxl import load_workbook
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Chưa cài openpyxl. Cài bằng: pip install openpyxl") from exc

    source = _template_path(samples_dir, template_id)
    wb = load_workbook(source)
    ws = wb.active
    warnings: list[str] = []

    with sqlite3.connect(Path(db_path)) as conn:
        if year is None:
            year = _latest_year(conn)
        if template_id == 1:
            by_district, by_commune, warn = _build_template1_stats(conn, year=year, huyen=huyen)
            warnings.extend(warn)
            filled_rows = _write_template1_values(ws, by_district=by_district, by_commune=by_commune)
            _add_review_scope_comments(ws, template_id)
        elif template_id in {2, 3}:
            by_district, by_commune, warn = _build_movement_stats(
                conn,
                template_id=template_id,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_movement_template_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
        elif template_id in {4, 5, 6, 7}:
            # Mẫu 4/5 dùng hộ nghèo; mẫu 6/7 là cùng cấu trúc thiếu hụt
            # nhưng áp dụng cho hộ cận nghèo. Mẫu 4/6 là số lượng, mẫu 5/7 là tỷ lệ.
            deprivation_group = NEAR_POOR if template_id in {6, 7} else POOR
            by_district, by_commune, warn = _build_deprivation_count_stats(
                conn,
                year=year,
                huyen=huyen,
                phan_loai=deprivation_group,
            )
            warnings.extend(warn)
            if template_id in {4, 6}:
                filled_rows = _write_deprivation_count_template_values(
                    ws,
                    by_district=by_district,
                    by_commune=by_commune,
                )
            else:
                # Mẫu 5/7: C = tổng số hộ trong nhóm, D:O = tỷ lệ 12 chỉ số.
                filled_rows = _write_deprivation_ratio_template_values(
                    ws,
                    by_district=by_district,
                    by_commune=by_commune,
                )
        elif template_id == 8:
            by_district, by_commune, warn = _build_template8_stats(
                conn,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_template8_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
            warnings.append(REVIEW_SCOPE_WARNING)
            _add_review_scope_comments(ws, template_id)
        elif template_id == 9:
            by_district, by_commune, warn = _build_template9_stats(
                conn,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_template9_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
        elif template_id == 10:
            by_district, by_commune, warn = _build_template10_stats(
                conn,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_template10_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
        elif template_id == 11:
            by_district, by_commune, warn = _build_template11_stats(
                conn,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_template11_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
        elif template_id == 12:
            by_district, by_commune, warn = _build_template12_stats(
                conn,
                year=year,
                huyen=huyen,
            )
            warnings.extend(warn)
            filled_rows = _write_template12_values(
                ws,
                by_district=by_district,
                by_commune=by_commune,
            )
            _apply_template12_readable_widths(ws)
            warnings.append(REVIEW_SCOPE_WARNING)
            _add_review_scope_comments(ws, template_id)
        else:  # pragma: no cover - chặn ở trên
            filled_rows = 0

    # Buộc Excel tính lại công thức tỷ lệ khi mở file.
    try:
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
    except Exception:
        pass

    _set_workbook_demo_properties(wb, title=TEMPLATE_SOURCE_FILES.get(template_id, "Báo cáo demo"))
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return TemplateExcelResult(
        content=output.getvalue(),
        template_id=template_id,
        source_template=str(source),
        filled_rows=filled_rows,
        warnings=warnings,
    )


__all__ = ["TemplateExcelResult", "export_template_xlsx", "SUPPORTED_TEMPLATE_IDS", "TEMPLATE_SOURCE_FILES"]
