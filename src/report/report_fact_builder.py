from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import os
import sqlite3

import pandas as pd

try:
    from .report_pattern_catalog import ReportTemplate, get_report_template
except Exception:  # pragma: no cover - hỗ trợ chạy file rời khi debug
    from report_pattern_catalog import ReportTemplate, get_report_template  # type: ignore


HOUSEHOLD_COUNT = "COUNT(DISTINCT id_ho)"
POOR = "Hộ nghèo"
NEAR_POOR = "Hộ cận nghèo"
NOT_POOR = "Hộ không nghèo"

MEDIUM_LIVING_NO_DIRECT_DATA_WARNING = (
    "Mẫu 1: nguồn dữ liệu hiện có chưa có trường dữ liệu trực tiếp để xác định nhóm hộ nông, lâm, ngư nghiệp "
    "có mức sống trung bình; chỉ tiêu này được ghi 0 và không phân tích sâu."
)
MEDIUM_LIVING_PROXY_WARNING = (
    "Mẫu 1: đang bật allow_demo_proxy_nlnn_mstb=True nên chỉ tiêu hộ nông, lâm, ngư nghiệp "
    "có mức sống trung bình được tính bằng proxy nghề nghiệp chủ hộ; không sử dụng như số chính thức nếu thiếu dữ liệu nghiệp vụ trực tiếp."
)
REVIEW_SCOPE_WARNING = (
    "Nguồn dữ liệu hiện có không có bảng dân cư toàn địa bàn. Các chỉ tiêu tổng hộ/tổng khẩu chung hoặc tổng hộ dân cư "
    "được tính trong phạm vi dữ liệu rà soát/phân loại của hệ thống, không phải tổng dân cư chính thức toàn địa bàn."
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
    "Nguồn dữ liệu hiện có chưa có thông tin lý do biến động chi tiết cho nhóm 'khác' như thay đổi nhân khẩu, "
    "chuyển đi, chuyển đến, tách hộ, nhập hộ hoặc chủ hộ chết; phần giảm/tăng khác "
    "được ghi 0 và không dùng để cân bằng công thức."
)

DEPRIVATION_FLAGS: list[tuple[str, str]] = [
    ("Việc làm", "th_viec_lam"),
    ("Bảo hiểm xã hội", "th_bhxh"),
    ("Bảo hiểm y tế", "th_bhyt"),
    ("Dinh dưỡng", "th_dinh_duong"),
    ("Giáo dục người lớn", "th_giao_duc_nguoi_lon"),
    ("Đi học của trẻ em", "th_di_hoc_tre_em"),
    ("Chất lượng nhà ở", "th_chat_luong_nha"),
    ("Diện tích nhà ở", "th_dien_tich_nha"),
    ("Nước sinh hoạt", "th_nuoc_sach"),
    ("Nhà tiêu hợp vệ sinh", "th_nha_tieu"),
    ("Dịch vụ viễn thông", "th_vien_thong"),
    ("Tài sản tiếp cận thông tin", "th_tai_san_tt"),
]

CAUSE_FLAGS: list[tuple[str, str]] = [
    ("Thiếu đất sản xuất", "nn_thieu_dat"),
    ("Thiếu vốn sản xuất/kinh doanh", "nn_thieu_von"),
    ("Thiếu lao động", "nn_thieu_lao_dong"),
    ("Thiếu công cụ/phương tiện sản xuất", "nn_thieu_cong_cu"),
    ("Thiếu kiến thức sản xuất", "nn_thieu_kien_thuc"),
    ("Thiếu kỹ năng lao động", "nn_thieu_ky_nang"),
    ("Ốm đau, bệnh nặng, tai nạn", "nn_om_dau"),
    ("Nguyên nhân khác", "nn_khac"),
]

GROUP_FLAGS: list[tuple[str, str]] = [
    ("Hộ có người có công cách mạng", "nhom_co_cong"),
    ("Hộ dân tộc thiểu số", "__DTTS_CHUNG__"),
    ("Hộ có chủ hộ là nữ", "nhom_chu_ho_nu"),
    ("Hộ có người khuyết tật", "nhom_khuyet_tat"),
    ("Hộ có người cao tuổi", "nhom_cao_tuoi"),
    ("Hộ có trẻ em dưới 6 tuổi", "nhom_tre_em_duoi6"),
    ("Hộ có trẻ em đang đi học", "nhom_tre_em_di_hoc"),
    ("Hộ đơn thân", "nhom_don_than"),
    ("Hộ không có khả năng lao động", "nhom_khong_knld"),
    ("Hộ thương binh/liệt sĩ", "nhom_thuong_binh"),
]

CHILD_FLAGS: list[tuple[str, str]] = [
    ("Trẻ em thiếu bảo hiểm y tế", "te_th_bhyt"),
    ("Trẻ em thiếu dinh dưỡng", "te_th_dinh_duong"),
    ("Trẻ em thiếu tình trạng đi học", "te_th_di_hoc"),
]


def _default_db_path() -> Path:
    try:
        from poverty_chatbot.config import DB_PATH  # type: ignore
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "db" / "poverty.db"


def _df(conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _scalar(conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _column_exists(conn: sqlite3.Connection, column: str) -> bool:
    return any(row[1] == column for row in conn.execute("PRAGMA table_info(ho_ngheo)"))


def _movement_other_reason_available(conn: sqlite3.Connection) -> bool:
    return any(_column_exists(conn, column) for column in MOVEMENT_OTHER_REASON_COLUMNS)


def _text_key(text: Any) -> str:
    import re
    import unicodedata

    raw = unicodedata.normalize("NFD", str(text or "").strip())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.lower().replace("đ", "d")
    raw = re.sub(r"[^a-z0-9]+", "", raw)
    return raw


def _detect_medium_living_condition(conn: sqlite3.Connection) -> tuple[str, str] | None:
    candidates = [
        "nlnndn_muc_song_trung_binh",
        "muc_song_trung_binh",
        "nhom_ngheo_tong_hop",
        "ky_ra_soat",
    ]
    for col in candidates:
        if not _column_exists(conn, col):
            continue
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM ho_ngheo WHERE {col} IS NOT NULL LIMIT 50"
        ).fetchall()
        for (value,) in rows:
            key = _text_key(value)
            if key in {"1", "true", "co"} and col in {"nlnndn_muc_song_trung_binh", "muc_song_trung_binh"}:
                return col, str(value)
            if "trungbinh" in key or "mucsong" in key:
                return col, str(value)
    return None

def _medium_living_proxy_condition(conn: sqlite3.Connection) -> tuple[str, list[Any]] | None:
    if not ALLOW_DEMO_PROXY_NLNN_MSTB or not _column_exists(conn, "nghe_nghiep_chu_ho"):
        return None
    placeholders = ",".join(["?"] * len(NLNN_JOB_VALUES))
    return (
        f"phan_loai = ? AND nghe_nghiep_chu_ho IN ({placeholders})",
        [NOT_POOR, *NLNN_JOB_VALUES],
    )


def _dtts_chung_condition(conn: sqlite3.Connection) -> str:
    if _column_exists(conn, "dan_toc_chi_tiet"):
        return "dan_toc_chi_tiet IS NOT NULL AND TRIM(dan_toc_chi_tiet) <> '' AND dan_toc_chi_tiet <> 'Kinh'"
    return "0 = 1"


def _flag_condition(conn: sqlite3.Connection, col: str) -> str:
    if col == "__DTTS_CHUNG__":
        return _dtts_chung_condition(conn)
    return f"{col} = 1"


def _pct(n: Any, d: Any, digits: int = 2) -> float:
    n = float(n or 0)
    d = float(d or 0)
    return round(n / d * 100, digits) if d else 0.0


def _fmt_scope(year: int | None, huyen: str | None) -> str:
    parts = []
    if huyen:
        parts.append(f"địa bàn {huyen}")
    else:
        parts.append("toàn tỉnh")
    if year:
        parts.append(f"năm {year}")
    return " ".join(parts)


def _scope_where(year: int | None = None, huyen: str | None = None, phan_loai: str | None = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if phan_loai:
        clauses.append("phan_loai = ?")
        params.append(phan_loai)
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def available_years(db_path: str | Path | None = None) -> list[int]:
    db = Path(db_path) if db_path else _default_db_path()
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT DISTINCT nam FROM ho_ngheo WHERE nam IS NOT NULL ORDER BY nam DESC").fetchall()
    return [int(r[0]) for r in rows]


def available_districts(db_path: str | Path | None = None) -> list[str]:
    db = Path(db_path) if db_path else _default_db_path()
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT DISTINCT huyen FROM ho_ngheo WHERE huyen IS NOT NULL ORDER BY huyen").fetchall()
    return [str(r[0]) for r in rows]


@dataclass
class ReportFactsBundle:
    template: dict[str, Any]
    scope: dict[str, Any]
    summary: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    facts: dict[str, Any]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "scope": self.scope,
            "summary": self.summary,
            "tables": {
                name: df.where(pd.notna(df), None).to_dict(orient="records")
                for name, df in self.tables.items()
            },
            "facts": self.facts,
        }


def _basic_summary(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> dict[str, Any]:
    w, p = _scope_where(year, huyen)
    total = int(_scalar(conn, f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {w}", p) or 0)

    def cnt(pl: str) -> int:
        w2, p2 = _scope_where(year, huyen, pl)
        return int(_scalar(conn, f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {w2}", p2) or 0)

    poor = cnt(POOR)
    near = cnt(NEAR_POOR)
    not_poor = cnt(NOT_POOR)
    return {
        "scope_label": _fmt_scope(year, huyen),
        "tong_ho_ra_soat": total,
        "ho_ngheo": poor,
        "ho_can_ngheo": near,
        "ho_khong_ngheo": not_poor,
        "ty_le_ho_ngheo": _pct(poor, total),
        "ty_le_ho_can_ngheo": _pct(near, total),
        "ty_le_ho_khong_ngheo": _pct(not_poor, total),
    }


def _overview_table(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> pd.DataFrame:
    w, p = _scope_where(year, huyen)
    df = _df(
        conn,
        f"""
        SELECT
            COALESCE(phan_loai, 'Không xác định') AS phan_loai,
            COUNT(DISTINCT id_ho) AS so_ho,
            COALESCE(SUM(so_nhan_khau), 0) AS so_nhan_khau
        FROM ho_ngheo
        {w}
        GROUP BY phan_loai
        ORDER BY so_ho DESC
        """,
        p,
    )
    total = int(df["so_ho"].sum()) if not df.empty else 0
    df["ty_le_%"] = df["so_ho"].map(lambda x: _pct(x, total))
    return df


def _district_overview(conn: sqlite3.Connection, year: int | None, household_focus: str | None = None) -> pd.DataFrame:
    w, p = _scope_where(year, None, household_focus)
    df = _df(
        conn,
        f"""
        SELECT
            huyen,
            COUNT(DISTINCT id_ho) AS so_ho,
            COALESCE(SUM(so_nhan_khau), 0) AS so_nhan_khau
        FROM ho_ngheo
        {w}
        GROUP BY huyen
        ORDER BY so_ho DESC
        """,
        p,
    )
    total = int(df["so_ho"].sum()) if not df.empty else 0
    df["ty_le_%"] = df["so_ho"].map(lambda x: _pct(x, total))
    return df


def _movement_table(conn: sqlite3.Connection, phan_loai: str, huyen: str | None = None) -> pd.DataFrame:
    years = available_years_from_conn(conn)
    if len(years) < 2:
        latest = years[0] if years else None
        if latest is None:
            return pd.DataFrame(columns=["huyen", "so_ho_ky_truoc", "so_ho_ky_sau", "chenh_lech", "ty_le_bien_dong_%"])
        years = [latest, latest]
    year_after, year_before = years[0], years[1]
    district_clause = "AND huyen = ?" if huyen else ""
    params: list[Any] = [year_before, year_after, phan_loai]
    if huyen:
        params.append(huyen)
    df = _df(
        conn,
        f"""
        SELECT
            huyen,
            COUNT(DISTINCT CASE WHEN nam = ? THEN id_ho END) AS so_ho_ky_truoc,
            COUNT(DISTINCT CASE WHEN nam = ? THEN id_ho END) AS so_ho_ky_sau
        FROM ho_ngheo
        WHERE phan_loai = ? {district_clause}
        GROUP BY huyen
        ORDER BY huyen
        """,
        params,
    )
    if df.empty:
        return df
    df["nam_truoc"] = year_before
    df["nam_sau"] = year_after
    df["chenh_lech"] = df["so_ho_ky_sau"] - df["so_ho_ky_truoc"]
    df["ty_le_bien_dong_%"] = df.apply(lambda r: _pct(r["chenh_lech"], r["so_ho_ky_truoc"]), axis=1)
    return df.sort_values("chenh_lech")


# ───────────────────────────── movement template facts (mẫu 2/3) ─────────────────────────────
# Mẫu 2/3 là bài toán diễn biến D:L theo bien_dong_dau_ky, không phải bài toán
# so sánh trực tiếp phan_loai giữa 2023 và 2024. Hàm cũ _movement_table được giữ
# cho tương thích, còn report tuần 4/5 dùng bảng này để khớp Excel mẫu gốc.
MOVEMENT_REPORT_COLUMNS = [
    "so_ho_ky_truoc",
    "giam_1",
    "giam_2",
    "giam_khac",
    "tang_1",
    "tang_2",
    "tang_3",
    "tang_khac",
    "so_ho_ky_sau",
]

MOVEMENT_REPORT_LABELS: dict[int, dict[str, str]] = {
    2: {
        "old": "Nghèo cũ (giữ nguyên)",
        "giam_1": "Thoát nghèo -> cận nghèo",
        "giam_2": "Thoát nghèo -> vượt chuẩn",
        "giam_khac": "Giảm nghèo khác",
        "tang_1": "Cận nghèo trở thành hộ nghèo",
        "tang_2": "Tái nghèo",
        "tang_3": "Nghèo mới phát sinh",
        "tang_khac": "Tăng nghèo khác",
    },
    3: {
        "old": "Cận nghèo cũ (giữ nguyên)",
        "giam_1": "Thoát cận nghèo -> vượt chuẩn",
        "giam_2": "Cận nghèo trở thành hộ nghèo",
        "giam_khac": "Giảm cận nghèo khác",
        "tang_1": "Thoát nghèo -> cận nghèo",
        "tang_2": "Tái cận nghèo",
        "tang_3": "Cận nghèo mới phát sinh",
        "tang_khac": "Tăng cận nghèo khác",
    },
}


def _movement_label_count_df(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> pd.DataFrame:
    clauses: list[str] = []
    params: list[Any] = []
    if year is not None:
        clauses.append("nam = ?")
        params.append(int(year))
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return _df(
        conn,
        f"""
        SELECT
            huyen,
            COALESCE(bien_dong_dau_ky, '') AS bien_dong_dau_ky,
            COUNT(DISTINCT id_ho) AS so_ho,
            COALESCE(SUM(so_nhan_khau), 0) AS so_nhan_khau
        FROM ho_ngheo
        {where}
        GROUP BY huyen, bien_dong_dau_ky
        """,
        params,
    )


def _movement_excel_like_table(
    conn: sqlite3.Connection,
    *,
    template_id: int,
    year: int | None,
    huyen: str | None = None,
) -> pd.DataFrame:
    """Tạo bảng nhận định cho mẫu 2/3 theo đúng công thức D:L của Excel mẫu gốc.

    - D/so_ho_ky_truoc = nhóm cũ giữ nguyên + các nhóm giảm trong kỳ.
    - L/so_ho_ky_sau = D - E - F - G + H + I + J + K.
    - Không dùng trực tiếp phan_loai năm trước/năm sau để tránh lệch bài toán diễn biến.
    """
    if year is None:
        years = available_years_from_conn(conn)
        year = years[0] if years else None
    prev_year = None
    if year is not None:
        prev = conn.execute("SELECT MAX(nam) FROM ho_ngheo WHERE nam IS NOT NULL AND nam < ?", (int(year),)).fetchone()
        prev_year = int(prev[0]) if prev and prev[0] is not None else None
    labels = MOVEMENT_REPORT_LABELS.get(int(template_id))
    if not labels:
        return pd.DataFrame()
    raw = _movement_label_count_df(conn, year, huyen)
    if raw.empty:
        return pd.DataFrame(columns=["huyen", *MOVEMENT_REPORT_COLUMNS, "nam_truoc", "nam_sau", "chenh_lech", "ty_le_bien_dong_%"])
    allow_other = _movement_other_reason_available(conn)

    rows: list[dict[str, Any]] = []
    for district, grp in raw.groupby("huyen", dropna=False):
        by_label: dict[str, int] = {}
        for _, r in grp.iterrows():
            by_label[str(r.get("bien_dong_dau_ky") or "")] = int(r.get("so_ho") or 0)
        g1 = int(by_label.get(labels["giam_1"], 0))
        g2 = int(by_label.get(labels["giam_2"], 0))
        gk = int(by_label.get(labels.get("giam_khac", ""), 0)) if allow_other else 0
        t1 = int(by_label.get(labels["tang_1"], 0))
        t2 = int(by_label.get(labels["tang_2"], 0))
        t3 = int(by_label.get(labels["tang_3"], 0))
        tk = int(by_label.get(labels.get("tang_khac", ""), 0)) if allow_other else 0
        before = int(by_label.get(labels["old"], 0)) + g1 + g2 + gk
        after = before - g1 - g2 - gk + t1 + t2 + t3 + tk
        delta = after - before
        rows.append({
            "huyen": district,
            "so_ho_ky_truoc": before,
            "giam_1": g1,
            "giam_2": g2,
            "giam_khac": gk,
            "tang_1": t1,
            "tang_2": t2,
            "tang_3": t3,
            "tang_khac": tk,
            "so_ho_ky_sau": after,
            "nam_truoc": prev_year,
            "nam_sau": year,
            "chenh_lech": delta,
            "ty_le_bien_dong_%": _pct(delta, before),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        for c in [c for c in df.columns if c != "huyen"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("chenh_lech", ascending=True).reset_index(drop=True)
    return df


def available_years_from_conn(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT DISTINCT nam FROM ho_ngheo WHERE nam IS NOT NULL ORDER BY nam DESC").fetchall()
    return [int(r[0]) for r in rows]


def _flag_table(
    conn: sqlite3.Connection,
    flags: list[tuple[str, str]],
    year: int | None,
    huyen: str | None,
    household_focus: str | None,
    include_both_groups: bool = False,
    base_condition: str | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def denominator(pl: str | None) -> int:
        w, p = _scope_where(year, huyen, pl)
        if base_condition:
            w = (w + " AND " if w else "WHERE ") + base_condition
        return int(_scalar(conn, f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {w}", p) or 0)

    if include_both_groups:
        den_poor = denominator(POOR)
        den_near = denominator(NEAR_POOR)
        for label, col in flags:
            w, p = _scope_where(year, huyen)
            extra = _flag_condition(conn, col)
            if base_condition:
                extra = f"{extra} AND {base_condition}"
            w = (w + " AND " if w else "WHERE ") + extra
            poor_count = int(_scalar(conn, f"SELECT COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) FROM ho_ngheo {w}", [POOR] + p) or 0)
            near_count = int(_scalar(conn, f"SELECT COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) FROM ho_ngheo {w}", [NEAR_POOR] + p) or 0)
            rows.append({
                "chi_tieu": label,
                "so_ho_ngheo": poor_count,
                "ty_le_ho_ngheo_%": _pct(poor_count, den_poor),
                "so_ho_can_ngheo": near_count,
                "ty_le_ho_can_ngheo_%": _pct(near_count, den_near),
            })
        return pd.DataFrame(rows).sort_values(["so_ho_ngheo", "so_ho_can_ngheo"], ascending=False)

    den = denominator(household_focus)
    for label, col in flags:
        w, p = _scope_where(year, huyen, household_focus)
        extra = _flag_condition(conn, col)
        if base_condition:
            extra = f"{extra} AND {base_condition}"
        w = (w + " AND " if w else "WHERE ") + extra
        count = int(_scalar(conn, f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {w}", p) or 0)
        rows.append({"chi_tieu": label, "so_ho": count, "ty_le_%": _pct(count, den), "tong_nhom": den})
    return pd.DataFrame(rows).sort_values("so_ho", ascending=False)


TEMPLATE8_REPORT_COLUMNS = [
    "huyen",
    "tong_ho_dan_cu",
    "so_ho_dtts",
    "tong_ho_ngheo",
    "tong_ho_can_ngheo",
    "ho_ngheo_dtts",
    "ho_can_ngheo_dtts",
    "ho_ngheo_khong_knld",
    "ho_can_ngheo_khong_knld",
    "ho_ngheo_co_cong",
    "ho_can_ngheo_co_cong",
]


def _build_template8_report_table(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> pd.DataFrame:
    """Bảng facts nội bộ cho mẫu 8, bám cấu trúc Excel gốc theo địa bàn.

    Mẫu 8 không phải bảng 10 nhóm đối tượng phẳng. Bảng chính cần theo huyện/TP
    và chỉ có 3 nhóm đúng mẫu: DTTS, không có khả năng lao động, có công.
    """
    where, params = _scope_where(year, huyen)
    dtts_cond = _dtts_chung_condition(conn)
    df = _df(
        conn,
        f"""
        SELECT
            huyen,
            {HOUSEHOLD_COUNT} AS tong_ho_dan_cu,
            COUNT(DISTINCT CASE WHEN {dtts_cond} THEN id_ho END) AS so_ho_dtts,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' THEN id_ho END) AS tong_ho_ngheo,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' THEN id_ho END) AS tong_ho_can_ngheo,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' AND {dtts_cond} THEN id_ho END) AS ho_ngheo_dtts,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' AND {dtts_cond} THEN id_ho END) AS ho_can_ngheo_dtts,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' AND nhom_khong_knld = 1 THEN id_ho END) AS ho_ngheo_khong_knld,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' AND nhom_khong_knld = 1 THEN id_ho END) AS ho_can_ngheo_khong_knld,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' AND nhom_co_cong = 1 THEN id_ho END) AS ho_ngheo_co_cong,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' AND nhom_co_cong = 1 THEN id_ho END) AS ho_can_ngheo_co_cong
        FROM ho_ngheo
        {where}
        GROUP BY huyen
        ORDER BY tong_ho_ngheo DESC, tong_ho_can_ngheo DESC, tong_ho_dan_cu DESC
        """,
        params,
    )
    if not df.empty:
        for col in [c for c in TEMPLATE8_REPORT_COLUMNS if c != "huyen"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        if not huyen:
            totals = {col: int(df[col].sum()) for col in TEMPLATE8_REPORT_COLUMNS if col != "huyen"}
            total_row = {"huyen": "Toàn tỉnh", **totals}
            df = pd.concat([pd.DataFrame([total_row]), df], ignore_index=True)
        df = df[TEMPLATE8_REPORT_COLUMNS]
    return df


def _child_deprivation_table(
    conn: sqlite3.Connection,
    year: int | None,
    huyen: str | None,
) -> tuple[pd.DataFrame, str]:
    count_metrics = [
        ("Trẻ em thiếu bảo hiểm y tế", "so_tre_thieu_bhyt", "te_th_bhyt"),
        ("Trẻ em thiếu dinh dưỡng", "so_tre_thieu_dinh_duong", "te_th_dinh_duong"),
        ("Trẻ em thiếu tình trạng đi học", "so_tre_thieu_di_hoc", "te_th_di_hoc"),
    ]
    use_child_counts = all(_column_exists(conn, col) for _label, col, _fallback in count_metrics)
    rows: list[dict[str, Any]] = []

    def denominator(pl: str) -> int:
        w, p = _scope_where(year, huyen, pl)
        return int(_scalar(conn, f"SELECT COALESCE(SUM(so_tre_em), 0) FROM ho_ngheo {w}", p) or 0)

    den_poor = denominator(POOR)
    den_near = denominator(NEAR_POOR)

    for label, count_col, flag_col in count_metrics:
        w, p = _scope_where(year, huyen)
        if use_child_counts:
            poor_sql = f"SELECT COALESCE(SUM(CASE WHEN phan_loai = ? THEN {count_col} ELSE 0 END), 0) FROM ho_ngheo {w}"
            near_sql = f"SELECT COALESCE(SUM(CASE WHEN phan_loai = ? THEN {count_col} ELSE 0 END), 0) FROM ho_ngheo {w}"
        else:
            poor_sql = f"SELECT COUNT(DISTINCT CASE WHEN phan_loai = ? AND {flag_col} = 1 AND co_tre_em = 1 THEN id_ho END) FROM ho_ngheo {w}"
            near_sql = f"SELECT COUNT(DISTINCT CASE WHEN phan_loai = ? AND {flag_col} = 1 AND co_tre_em = 1 THEN id_ho END) FROM ho_ngheo {w}"

        poor_count = int(_scalar(conn, poor_sql, [POOR] + p) or 0)
        near_count = int(_scalar(conn, near_sql, [NEAR_POOR] + p) or 0)
        rows.append({
            "chi_tieu": label,
            "so_ho_ngheo": poor_count,
            "ty_le_ho_ngheo_%": _pct(poor_count, den_poor),
            "so_ho_can_ngheo": near_count,
            "ty_le_ho_can_ngheo_%": _pct(near_count, den_near),
        })

    df = pd.DataFrame(rows).sort_values(["so_ho_ngheo", "so_ho_can_ngheo"], ascending=False)
    return df, ("trẻ em" if use_child_counts else "hộ/case")


def _ethnicity_table(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> pd.DataFrame:
    w, p = _scope_where(year, huyen)
    df = _df(
        conn,
        f"""
        SELECT
            COALESCE(dan_toc_chi_tiet, 'Không xác định') AS dan_toc,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' THEN id_ho END) AS so_ho_ngheo,
            COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' THEN id_ho END) AS so_ho_can_ngheo,
            COUNT(DISTINCT id_ho) AS tong_ho
        FROM ho_ngheo
        {w}
        GROUP BY dan_toc_chi_tiet
        ORDER BY so_ho_ngheo DESC, so_ho_can_ngheo DESC
        """,
        p,
    )
    total_poor = int(df["so_ho_ngheo"].sum()) if not df.empty else 0
    total_near = int(df["so_ho_can_ngheo"].sum()) if not df.empty else 0
    if not df.empty:
        df["ty_le_ngheo_%"] = df["so_ho_ngheo"].map(lambda x: _pct(x, total_poor))
        df["ty_le_can_ngheo_%"] = df["so_ho_can_ngheo"].map(lambda x: _pct(x, total_near))
    return df


def _multidim_table(conn: sqlite3.Connection, year: int | None, huyen: str | None, household_focus: str) -> pd.DataFrame:
    where_year = "WHERE nam = ?" if year is not None else ""
    params: list[Any] = [int(year)] if year is not None else []
    if huyen:
        where_year = (where_year + " AND " if where_year else "WHERE ") + "huyen = ?"
        params.append(huyen)
    df = _df(
        conn,
        f"""
        SELECT
            huyen,
            COUNT(DISTINCT id_ho) AS tong_ho_ra_soat,
            COALESCE(SUM(so_nhan_khau), 0) AS tong_nhan_khau,
            COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS so_ho_muc_tieu,
            COALESCE(SUM(CASE WHEN phan_loai = ? THEN so_nhan_khau ELSE 0 END), 0) AS so_nhan_khau_muc_tieu,
            COUNT(DISTINCT CASE WHEN phan_loai = ? AND dan_toc_chi_tiet = 'Kinh' THEN id_ho END) AS so_ho_kinh,
            COUNT(DISTINCT CASE WHEN phan_loai = ? AND (dan_toc_chi_tiet IS NOT NULL AND dan_toc_chi_tiet <> 'Kinh') THEN id_ho END) AS so_ho_dtts,
            COUNT(DISTINCT CASE WHEN phan_loai = ? AND dan_toc_tai_cho = 'Có' THEN id_ho END) AS so_ho_dtts_tai_cho,
            COUNT(DISTINCT CASE WHEN dan_toc_chi_tiet IS NOT NULL AND dan_toc_chi_tiet <> 'Kinh' THEN id_ho END) AS tong_ho_dtts,
            COUNT(DISTINCT CASE WHEN dan_toc_tai_cho = 'Có' THEN id_ho END) AS tong_ho_dtts_tai_cho
        FROM ho_ngheo
        {where_year}
        GROUP BY huyen
        ORDER BY so_ho_muc_tieu DESC
        """,
        [household_focus, household_focus, household_focus, household_focus, household_focus] + params,
    )
    if not df.empty:
        df["ty_le_muc_tieu_%"] = df.apply(lambda r: _pct(r["so_ho_muc_tieu"], r["tong_ho_ra_soat"]), axis=1)
        df["ty_le_dtts_trong_nhom_%"] = df.apply(lambda r: _pct(r["so_ho_dtts"], r["so_ho_muc_tieu"]), axis=1)
        df["ty_le_ngheo_trong_dtts_%"] = df.apply(lambda r: _pct(r["so_ho_dtts"], r["tong_ho_dtts"]), axis=1)
        df["ty_le_ngheo_trong_dtts_tai_cho_%"] = df.apply(lambda r: _pct(r["so_ho_dtts_tai_cho"], r["tong_ho_dtts_tai_cho"]), axis=1)
    return df


def _top_records(df: pd.DataFrame, value_col: str, label_col: str, n: int = 3, ascending: bool = False) -> list[dict[str, Any]]:
    if df is None or df.empty or value_col not in df.columns:
        return []
    return df.sort_values(value_col, ascending=ascending).head(n).where(pd.notna(df), None).to_dict(orient="records")



# ───────────────────────── template table / insight helpers ─────────────────────────

def _records(df: pd.DataFrame | None, n: int = 5) -> list[dict[str, Any]]:
    """Trả records JSON-safe từ DataFrame để đưa vào report_facts/prompt."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    head = df.head(n).copy()
    return head.where(pd.notna(head), None).to_dict(orient="records")


def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    return [str(col) for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


def _template_label_col(df: pd.DataFrame, pattern: str) -> str | None:
    candidates_by_pattern = {
        "overview_result": ["huyen", "phan_loai", "nhom_chi_tieu", "xa_phuong"],
        "movement": ["huyen", "xa_phuong"],
        "deprivation_count": ["chi_tieu", "huyen", "xa_phuong"],
        "deprivation_ratio": ["chi_tieu", "huyen", "xa_phuong"],
        "vulnerable_groups": ["huyen", "chi_tieu", "nhom"],
        "ethnicity": ["dan_toc", "huyen"],
        "causes": ["chi_tieu", "nguyen_nhan", "huyen"],
        "child_deprivation": ["chi_tieu", "huyen"],
        "multidimensional_standard": ["huyen", "xa_phuong"],
    }
    col = _first_existing_col(df, candidates_by_pattern.get(pattern, []) + ["chi_tieu", "nhom_chi_tieu", "huyen", "phan_loai", "dan_toc", "xa_phuong"])
    if col:
        return col
    object_cols = [str(c) for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    return object_cols[0] if object_cols else (str(df.columns[0]) if len(df.columns) else None)


def _template_value_cols(df: pd.DataFrame, pattern: str) -> list[str]:
    candidates_by_pattern = {
        "overview_result": ["tong_ho_dan_cu", "so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "so_nhan_khau", "tong_nhan_khau", "ty_le_%"],
        "movement": ["so_ho_ky_truoc", "so_ho_ky_sau", "chenh_lech", "ty_le_bien_dong_%"],
        "deprivation_count": ["so_ho", "tong_nhom", "ty_le_%"],
        "deprivation_ratio": ["ty_le_%", "so_ho", "tong_nhom"],
        "vulnerable_groups": [
            "tong_ho_dan_cu", "so_ho_dtts", "tong_ho_ngheo", "tong_ho_can_ngheo",
            "ho_ngheo_dtts", "ho_can_ngheo_dtts", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld",
            "ho_ngheo_co_cong", "ho_can_ngheo_co_cong", "so_ho_ngheo", "so_ho_can_ngheo",
        ],
        "ethnicity": ["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho", "ty_le_ngheo_%", "ty_le_can_ngheo_%"],
        "causes": ["so_ho_ngheo", "so_ho_can_ngheo", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%"],
        "child_deprivation": ["so_ho_ngheo", "so_ho_can_ngheo", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%"],
        "multidimensional_standard": [
            "so_ho_muc_tieu", "so_nhan_khau_muc_tieu", "ty_le_muc_tieu_%", "tong_ho_ra_soat",
            "tong_ho_dtts", "so_ho_dtts", "ty_le_ngheo_trong_dtts_%",
            "tong_ho_dtts_tai_cho", "so_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_tai_cho_%",
        ],
    }
    numeric = set(_numeric_columns(df))
    ordered: list[str] = []
    for col in candidates_by_pattern.get(pattern, []):
        if col in df.columns and col in numeric and col not in ordered:
            ordered.append(col)
    for col in _numeric_columns(df):
        if col not in ordered:
            ordered.append(col)
    return ordered


def _top_bottom_records(df: pd.DataFrame, label_col: str | None, value_col: str | None, n: int = 5) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(df, pd.DataFrame) or df.empty or not label_col or not value_col or value_col not in df.columns:
        return [], []
    cols = [c for c in [label_col, value_col] if c in df.columns]
    sorted_desc = df.sort_values(value_col, ascending=False)[cols]
    top = sorted_desc.head(n)

    # Tránh câu ngược nghĩa kiểu: top đã gồm tất cả dòng nhưng bottom lại lặp cả top.
    # Với bảng ít dòng, chỉ cần top là đủ; bottom chỉ dùng khi còn nhóm thật sự ngoài top.
    top_labels = set(str(v) for v in top[label_col].tolist()) if label_col in top.columns else set()
    bottom_src = df.sort_values(value_col, ascending=True)[cols]
    if label_col in bottom_src.columns:
        bottom_src = bottom_src[~bottom_src[label_col].astype(str).isin(top_labels)]
    bottom = bottom_src.head(n)
    return _records(top, n), _records(bottom, n)


def _zero_records(df: pd.DataFrame, label_col: str | None, value_col: str | None, n: int = 8) -> list[dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty or not label_col or not value_col or value_col not in df.columns:
        return []
    try:
        z = df[pd.to_numeric(df[value_col], errors="coerce").fillna(0) == 0]
        cols = [c for c in [label_col, value_col] if c in z.columns]
        return _records(z[cols], n)
    except Exception:
        return []


def _pattern_interpretation_notes(pattern: str, household_focus: str | None = None) -> list[str]:
    focus = household_focus or "hộ nghèo, hộ cận nghèo"
    notes = {
        "overview_result": [
            "Bảng dùng để nhận định quy mô và cơ cấu các nhóm hộ trong phạm vi rà soát.",
            "Không suy diễn nguyên nhân nghèo nếu bảng không có cột nguyên nhân.",
        ],
        "movement": [
            "Bảng diễn biến chỉ đủ căn cứ mô tả biến động giữa các mốc năm có trong dữ liệu.",
            "Không viết thành xu hướng dài hạn nếu dữ liệu chỉ có hai kỳ rà soát.",
            "Cần tách rõ số đầu kỳ, số cuối kỳ, nhóm tăng và nhóm giảm nếu bảng mẫu có các cột này.",
        ],
        "deprivation_count": [
            f"Các chỉ số thiếu hụt của nhóm {focus} có thể chồng lấn trên cùng một hộ.",
            "Không cộng các chỉ số thiếu hụt thành cơ cấu 100% nếu bảng không quy định loại trừ nhau.",
        ],
        "deprivation_ratio": [
            f"Tỷ lệ thiếu hụt của nhóm {focus} cần giữ đúng đơn vị phần trăm và mẫu số.",
            "Không chuyển tỷ lệ thành số hộ nếu bảng không có số hộ tương ứng.",
        ],
        "vulnerable_groups": [
            "Các nhóm đối tượng có thể chồng lấn, vì một hộ có thể thuộc nhiều nhóm.",
            "Nhận định nên tập trung vào nhóm nổi bật và yêu cầu theo dõi, không cộng thành tổng loại trừ nhau.",
        ],
        "ethnicity": [
            "Cần phân biệt dân tộc chi tiết, dân tộc thiểu số và dân tộc thiểu số tại chỗ nếu dữ liệu có tách riêng.",
            "Không suy diễn nguyên nhân nghèo theo dân tộc nếu bảng chỉ là thống kê phân bố.",
        ],
        "causes": [
            "Nguyên nhân nghèo có thể đồng thời xuất hiện ở một hộ.",
            "Không kết luận nguyên nhân duy nhất nếu dữ liệu chỉ là các cờ đánh dấu nguyên nhân.",
        ],
        "child_deprivation": [
            "Cần nêu rõ đơn vị diễn giải là trẻ em hay hộ/case tùy dữ liệu có cột số trẻ thiếu cụ thể hay không.",
            "Không suy diễn tình trạng cá nhân của trẻ nếu bảng chỉ phản ánh số hộ hoặc số trường hợp.",
        ],
        "multidimensional_standard": [
            "Kết quả chuẩn nghèo đa chiều cần nêu rõ nhóm hộ, năm và phạm vi địa bàn.",
            "Không kết luận xu hướng dài hạn nếu bảng chỉ phản ánh một năm hoặc một thời điểm rà soát.",
        ],
    }
    return notes.get(pattern, ["Nhận định phải bám sát bảng số liệu và phạm vi lọc hiện có."])


def _build_template1_excel_like_tables(conn: sqlite3.Connection, year: int | None, huyen: str | None) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Tạo bảng trung gian sát mẫu 1 hơn bảng overview chung.

    Không xuất workbook và không đọc ngược Excel đã xuất. Bảng này chỉ là dữ liệu
    Python/DB đã tính theo các nhóm cột nghiệp vụ của mẫu 1: tổng hộ dân cư,
    hộ nghèo, hộ cận nghèo, và hộ nông/lâm/ngư nghiệp có mức sống trung bình.
    """
    warnings: list[str] = []
    where, params = _scope_where(year, huyen)

    medium_household_expr = "0"
    medium_population_expr = "0"
    medium_params: list[Any] = []
    medium_cond = _detect_medium_living_condition(conn)
    if medium_cond:
        medium_col, medium_value = medium_cond
        medium_household_expr = f"COUNT(DISTINCT CASE WHEN {medium_col} = ? THEN id_ho END)"
        medium_population_expr = f"COALESCE(SUM(CASE WHEN {medium_col} = ? THEN so_nhan_khau ELSE 0 END), 0)"
        medium_params = [medium_value, medium_value]
    else:
        proxy = _medium_living_proxy_condition(conn)
        if proxy:
            proxy_cond, proxy_params = proxy
            medium_household_expr = f"COUNT(DISTINCT CASE WHEN {proxy_cond} THEN id_ho END)"
            medium_population_expr = f"COALESCE(SUM(CASE WHEN {proxy_cond} THEN so_nhan_khau ELSE 0 END), 0)"
            medium_params = [*proxy_params, *proxy_params]
            warnings.append(MEDIUM_LIVING_PROXY_WARNING)
        else:
            warnings.append(MEDIUM_LIVING_NO_DIRECT_DATA_WARNING)
    warnings.append(REVIEW_SCOPE_WARNING)

    sql = f"""
        SELECT
            huyen,
            COUNT(DISTINCT id_ho) AS tong_ho_dan_cu,
            COALESCE(SUM(so_nhan_khau), 0) AS tong_nhan_khau,
            COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS so_ho_ngheo,
            COALESCE(SUM(CASE WHEN phan_loai = ? THEN so_nhan_khau ELSE 0 END), 0) AS so_khau_ngheo,
            COUNT(DISTINCT CASE WHEN phan_loai = ? THEN id_ho END) AS so_ho_can_ngheo,
            COALESCE(SUM(CASE WHEN phan_loai = ? THEN so_nhan_khau ELSE 0 END), 0) AS so_khau_can_ngheo,
            {medium_household_expr} AS so_ho_nlnndn_mstb,
            {medium_population_expr} AS so_khau_nlnndn_mstb
        FROM ho_ngheo
        {where}
        GROUP BY huyen
        ORDER BY so_ho_ngheo DESC, so_ho_can_ngheo DESC, tong_ho_dan_cu DESC
    """
    query_params: list[Any] = [POOR, POOR, NEAR_POOR, NEAR_POOR] + medium_params + params
    district_df = _df(conn, sql, query_params)
    for col in [
        "tong_ho_dan_cu", "tong_nhan_khau", "so_ho_ngheo", "so_khau_ngheo",
        "so_ho_can_ngheo", "so_khau_can_ngheo", "so_ho_nlnndn_mstb", "so_khau_nlnndn_mstb",
    ]:
        if col in district_df.columns:
            district_df[col] = pd.to_numeric(district_df[col], errors="coerce").fillna(0).astype(int)

    totals = {col: int(district_df[col].sum()) for col in district_df.columns if col != "huyen" and pd.api.types.is_numeric_dtype(district_df[col])}
    chart_df = pd.DataFrame([
        {"nhom_chi_tieu": "Hộ nghèo", "so_ho": totals.get("so_ho_ngheo", 0)},
        {"nhom_chi_tieu": "Hộ cận nghèo", "so_ho": totals.get("so_ho_can_ngheo", 0)},
        {"nhom_chi_tieu": "Hộ nông, lâm, ngư nghiệp có mức sống trung bình", "so_ho": totals.get("so_ho_nlnndn_mstb", 0)},
    ])
    chart_df = chart_df.sort_values("so_ho", ascending=False).reset_index(drop=True)
    return district_df, chart_df, warnings


def _build_table_insights(template: ReportTemplate, tables: dict[str, pd.DataFrame], facts: dict[str, Any]) -> dict[str, Any]:
    """Tạo nhận xét chi tiết từ bảng theo mẫu để report_writer không chỉ viết tổng quan."""
    pattern = str(template.pattern or "overview_result")
    df = tables.get("template_main") if isinstance(tables.get("template_main"), pd.DataFrame) else tables.get("main", pd.DataFrame())
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    label_col = _template_label_col(df, pattern) if not df.empty else None
    value_cols = _template_value_cols(df, pattern) if not df.empty else []
    primary_value_col = value_cols[0] if value_cols else None
    top, bottom = _top_bottom_records(df, label_col, primary_value_col, 5)
    zero = _zero_records(df, label_col, primary_value_col, 8)

    insights: dict[str, Any] = {
        "source": "ReportFactsBundle.tables.template_main",
        "template_id": int(template.id),
        "pattern": pattern,
        "row_count": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
        "columns": list(map(str, df.columns)) if isinstance(df, pd.DataFrame) else [],
        "label_col": label_col,
        "primary_value_col": primary_value_col,
        "numeric_columns": value_cols,
        "top_records": top,
        "bottom_records": bottom,
        "zero_records": zero,
        "interpretation_notes": _pattern_interpretation_notes(pattern, template.household_focus),
        "detail_focus": "Nhận định chi tiết cần bám vào bảng số liệu báo cáo, gồm nhóm/cột nổi bật, chênh lệch, tỷ lệ và giới hạn diễn giải.",
    }

    if isinstance(df, pd.DataFrame) and not df.empty:
        if primary_value_col:
            try:
                insights["primary_total"] = float(pd.to_numeric(df[primary_value_col], errors="coerce").fillna(0).sum())
            except Exception:
                insights["primary_total"] = None
        if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau", "chenh_lech"}.issubset(df.columns):
            before = int(pd.to_numeric(df["so_ho_ky_truoc"], errors="coerce").fillna(0).sum())
            after = int(pd.to_numeric(df["so_ho_ky_sau"], errors="coerce").fillna(0).sum())
            delta = after - before
            delta_numeric = pd.to_numeric(df["chenh_lech"], errors="coerce").fillna(0)
            decrease_df = df[delta_numeric < 0]
            increase_df = df[delta_numeric > 0]
            insights["movement_detail"] = {
                "tong_ky_truoc": before,
                "tong_ky_sau": after,
                "chenh_lech": delta,
                "ty_le_bien_dong_%": _pct(delta, before),
                "giam_nhieu_nhat": _top_records(decrease_df, "chenh_lech", label_col or "huyen", 5, ascending=True) if not decrease_df.empty else [],
                "tang_nhieu_nhat": _top_records(increase_df, "chenh_lech", label_col or "huyen", 5, ascending=False) if not increase_df.empty else [],
            }
        elif pattern in {"deprivation_count", "deprivation_ratio"}:
            insights["deprivation_detail"] = {
                "top_by_count": _top_records(df, "so_ho", label_col or "chi_tieu", 5) if "so_ho" in df.columns else [],
                "top_by_ratio": _top_records(df, "ty_le_%", label_col or "chi_tieu", 5) if "ty_le_%" in df.columns else [],
                "overlap_warning": "Các chỉ số thiếu hụt có thể chồng lấn, không cộng thành cơ cấu 100%.",
            }
        elif int(template.id) == 1 and {"so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"}.issubset(df.columns):
            insights["template1_detail"] = {
                "total_poor_households": int(pd.to_numeric(df["so_ho_ngheo"], errors="coerce").fillna(0).sum()),
                "total_near_poor_households": int(pd.to_numeric(df["so_ho_can_ngheo"], errors="coerce").fillna(0).sum()),
                "total_medium_living_households": int(pd.to_numeric(df["so_ho_nlnndn_mstb"], errors="coerce").fillna(0).sum()),
                "top_poor_districts": _top_records(df, "so_ho_ngheo", label_col or "huyen", 5),
                "top_near_poor_districts": _top_records(df, "so_ho_can_ngheo", label_col or "huyen", 5),
                "top_medium_living_districts": _top_records(df, "so_ho_nlnndn_mstb", label_col or "huyen", 5),
            }
        elif int(template.id) == 8 and {"tong_ho_dan_cu", "so_ho_dtts", "tong_ho_ngheo", "tong_ho_can_ngheo", "ho_ngheo_dtts", "ho_can_ngheo_dtts", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld", "ho_ngheo_co_cong", "ho_can_ngheo_co_cong"}.issubset(df.columns):
            district_df = df[df["huyen"].astype(str) != "Toàn tỉnh"].copy() if "huyen" in df.columns else df.copy()
            total_row = df[df["huyen"].astype(str) == "Toàn tỉnh"].head(1).to_dict(orient="records")
            insights["template8_detail"] = {
                "table_shape": "district_rows",
                "groups": ["DTTS", "Không có khả năng lao động", "Có người có công với cách mạng"],
                "total_row": total_row[0] if total_row else {},
                "top_by_poor_dtts": _top_records(district_df, "ho_ngheo_dtts", "huyen", 5),
                "top_by_near_poor_dtts": _top_records(district_df, "ho_can_ngheo_dtts", "huyen", 5),
                "top_by_poor_no_labor": _top_records(district_df, "ho_ngheo_khong_knld", "huyen", 5),
                "top_by_near_poor_no_labor": _top_records(district_df, "ho_can_ngheo_khong_knld", "huyen", 5),
                "top_by_poor_meritorious": _top_records(district_df, "ho_ngheo_co_cong", "huyen", 5),
                "top_by_near_poor_meritorious": _top_records(district_df, "ho_can_ngheo_co_cong", "huyen", 5),
            }
        elif {"so_ho_ngheo", "so_ho_can_ngheo"}.issubset(df.columns):
            insights["two_group_detail"] = {
                "top_poor": _top_records(df, "so_ho_ngheo", label_col or "chi_tieu", 5),
                "top_near_poor": _top_records(df, "so_ho_can_ngheo", label_col or "chi_tieu", 5),
            }
        elif pattern == "multidimensional_standard":
            insights["multidim_detail"] = {
                "top_by_target_households": _top_records(df, "so_ho_muc_tieu", label_col or "huyen", 5) if "so_ho_muc_tieu" in df.columns else [],
                "top_by_target_ratio": _top_records(df, "ty_le_muc_tieu_%", label_col or "huyen", 5) if "ty_le_muc_tieu_%" in df.columns else [],
                "top_by_dtts_poverty_rate": _top_records(df, "ty_le_ngheo_trong_dtts_%", label_col or "huyen", 5) if "ty_le_ngheo_trong_dtts_%" in df.columns else [],
                "top_by_local_dtts_poverty_rate": _top_records(df, "ty_le_ngheo_trong_dtts_tai_cho_%", label_col or "huyen", 5) if "ty_le_ngheo_trong_dtts_tai_cho_%" in df.columns else [],
                "internal_indicator_note": "ty_le_dtts_trong_nhom_% là tỷ trọng DTTS trong nhóm hộ nghèo, không phải cột W/X của mẫu 12.",
            }
    return insights


def _build_chart_insights(template: ReportTemplate, tables: dict[str, pd.DataFrame], table_insights: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa thông tin biểu đồ để cả UI và report_writer cùng hiểu một thông điệp."""
    pattern = str(template.pattern or "overview_result")
    chart_df = tables.get("template_chart") if isinstance(tables.get("template_chart"), pd.DataFrame) else None
    df = chart_df if isinstance(chart_df, pd.DataFrame) and not chart_df.empty else (
        tables.get("template_main") if isinstance(tables.get("template_main"), pd.DataFrame) else tables.get("main", pd.DataFrame())
    )
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {"available": False, "reason": "Không có bảng số liệu báo cáo để tạo biểu đồ."}

    label_col = _template_label_col(df, pattern)
    value_cols = _template_value_cols(df, pattern)

    if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(df.columns):
        return {
            "available": True,
            "chart_type": "bar" if "huyen" in df.columns and df["huyen"].nunique(dropna=True) > 1 else "line",
            "label_col": "huyen" if "huyen" in df.columns else label_col,
            "value_cols": ["so_ho_ky_truoc", "so_ho_ky_sau"],
            "message": "Biểu đồ so sánh số hộ kỳ trước và kỳ sau theo địa bàn hoặc theo năm.",
            "top_records": table_insights.get("movement_detail", {}).get("giam_nhieu_nhat") or table_insights.get("top_records") or [],
        }

    candidates_by_pattern = {
        "overview_result": ["so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "tong_ho_dan_cu"],
        "deprivation_ratio": ["ty_le_%", "so_ho"],
        "deprivation_count": ["so_ho", "ty_le_%"],
        "multidimensional_standard": ["so_ho_muc_tieu", "ty_le_muc_tieu_%", "tong_ho_ra_soat"],
        "vulnerable_groups": ["so_ho_ngheo", "so_ho_can_ngheo"],
        "ethnicity": ["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho"],
        "causes": ["so_ho_ngheo", "so_ho_can_ngheo"],
        "child_deprivation": ["so_ho_ngheo", "so_ho_can_ngheo"],
    }
    value_col = None
    for candidate in candidates_by_pattern.get(pattern, []) + value_cols:
        if candidate in df.columns and candidate in set(_numeric_columns(df)):
            value_col = candidate
            break

    top, bottom = _top_bottom_records(df, label_col, value_col, 5)
    return {
        "available": bool(label_col and value_col),
        "chart_type": str(template.recommended_chart or "bar"),
        "label_col": label_col,
        "value_col": value_col,
        "top_records": top,
        "bottom_records": bottom,
        "message": "Biểu đồ minh họa dùng cùng bộ số liệu báo cáo để đối chiếu với nhận định chi tiết.",
    }

def _template_context(template: ReportTemplate, table_insights: dict[str, Any]) -> dict[str, Any]:
    pattern = str(template.pattern or "overview_result")
    return {
        "template_id": int(template.id),
        "code": template.code,
        "title": template.title,
        "source_file": template.source_file,
        "pattern": pattern,
        "business_group": template.business_group,
        "household_focus": template.household_focus,
        "recommended_chart": template.recommended_chart,
        "week4_text_goal": template.week4_text_goal,
        "week5_output_goal": template.week5_output_goal,
        "interpretation_notes": table_insights.get("interpretation_notes") or _pattern_interpretation_notes(pattern, template.household_focus),
    }


def _attach_template_detail_context(template: ReportTemplate, tables: dict[str, pd.DataFrame], facts: dict[str, Any]) -> None:
    """Gắn bảng theo mẫu + insight vào ReportFactsBundle mà không tạo module mới.

    template_main là bảng trung gian cho UI/report_writer. Nó không phải file Excel đã xuất,
    nhưng có cùng nguồn số liệu Python/DB với Excel exporter nên dùng được để nhận định chi tiết.
    """
    main = tables.get("main")
    if isinstance(main, pd.DataFrame):
        tables.setdefault("template_main", main.copy())
    table_insights = _build_table_insights(template, tables, facts)
    chart_insights = _build_chart_insights(template, tables, table_insights)
    facts["template_context"] = _template_context(template, table_insights)
    facts["table_insights"] = table_insights
    facts["chart_insights"] = chart_insights

def build_report_bundle(
    template_id: int | str,
    db_path: str | Path | None = None,
    year: int | None = None,
    huyen: str | None = None,
) -> ReportFactsBundle:
    """Tạo fact pack chuẩn cho tuần 4/5 từ 13 option báo cáo.

    Đây là tầng Python/SQL kiểm soát số liệu. LLM/report_writer chỉ được diễn đạt lại
    các facts trong bundle này.
    """
    template: ReportTemplate = get_report_template(template_id)
    db = Path(db_path) if db_path else _default_db_path()
    if not db.exists():
        raise FileNotFoundError(f"Không tìm thấy database: {db}")

    with sqlite3.connect(db) as conn:
        if year is None:
            years = available_years_from_conn(conn)
            year = years[0] if years else None
        summary = _basic_summary(conn, year, huyen)
        tables: dict[str, pd.DataFrame] = {}
        facts: dict[str, Any] = {}

        if template.pattern == "overview_result":
            main = _overview_table(conn, year, huyen)
            district = _district_overview(conn, year, None) if not huyen else pd.DataFrame()
            tables["main"] = main
            if not district.empty:
                tables["by_district"] = district
            facts["top_groups"] = _top_records(main, "so_ho", "phan_loai", 3)
            facts["top_districts"] = _top_records(district, "so_ho", "huyen", 3) if not district.empty else []
            if int(template.id) == 1:
                template_main, template_chart, template_warnings = _build_template1_excel_like_tables(conn, year, huyen)
                if not template_main.empty:
                    tables["template_main"] = template_main
                if not template_chart.empty:
                    tables["template_chart"] = template_chart
                if template_warnings:
                    facts["template_data_warnings"] = template_warnings

        elif template.pattern == "movement":
            main = _movement_excel_like_table(conn, template_id=int(template.id), year=year, huyen=huyen)
            tables["main"] = main
            tables["template_main"] = main.copy() if isinstance(main, pd.DataFrame) else main
            total_before = int(pd.to_numeric(main["so_ho_ky_truoc"], errors="coerce").fillna(0).sum()) if isinstance(main, pd.DataFrame) and not main.empty else 0
            total_after = int(pd.to_numeric(main["so_ho_ky_sau"], errors="coerce").fillna(0).sum()) if isinstance(main, pd.DataFrame) and not main.empty else 0
            delta = total_after - total_before
            movement_warnings: list[str] = []
            other_reason_available = _movement_other_reason_available(conn)
            movement_other_policy = "use_explicit_reason_columns" if other_reason_available else "zero_without_explicit_reason"
            if not other_reason_available:
                movement_warnings.append(MOVEMENT_OTHER_NO_REASON_WARNING)
            final_class = POOR if int(template.id) == 2 else NEAR_POOR if int(template.id) == 3 else None
            actual_final_total = 0
            if final_class:
                final_where, final_params = _scope_where(year, huyen, final_class)
                actual_final_total = int(_scalar(conn, f"SELECT {HOUSEHOLD_COUNT} FROM ho_ngheo {final_where}", final_params) or 0)
            unexplained_delta = actual_final_total - total_after
            if unexplained_delta:
                movement_warnings.append(
                    "Tổng cuối kỳ theo công thức D - E - F - G + H + I + J + K không khớp hoàn toàn "
                    "với tổng phân loại hộ hiện tại; phần chênh lệch được ghi là chênh lệch chưa giải thích, "
                    "không tự gán vào nhóm 'khác'."
                )
            movement_components = {
                col: int(pd.to_numeric(main[col], errors="coerce").fillna(0).sum())
                for col in ["giam_1", "giam_2", "giam_khac", "tang_1", "tang_2", "tang_3", "tang_khac"]
                if isinstance(main, pd.DataFrame) and not main.empty and col in main.columns
            }
            labels = MOVEMENT_REPORT_LABELS.get(int(template.id), {})
            delta_direction = "tăng" if delta > 0 else ("giảm" if delta < 0 else "không biến động")
            delta_pct_text = f"{_pct(delta, total_before):.2f}".replace(".", ",") + "%"
            sentence_anchors = [
                (
                    f"{template.household_focus}: đầu kỳ {total_before} hộ, cuối kỳ theo công thức là {total_after} hộ, "
                    f"chênh lệch {abs(delta)} hộ theo chiều {delta_direction}, tương ứng {delta_pct_text}."
                ),
                (
                    f"Cấu phần giảm: {labels.get('giam_1', 'giảm nhóm 1')} {movement_components.get('giam_1', 0)} hộ; "
                    f"{labels.get('giam_2', 'giảm nhóm 2')} {movement_components.get('giam_2', 0)} hộ; "
                    f"giảm khác có căn cứ chi tiết {movement_components.get('giam_khac', 0)} hộ."
                ),
                (
                    f"Cấu phần tăng: {labels.get('tang_1', 'tăng nhóm 1')} {movement_components.get('tang_1', 0)} hộ; "
                    f"{labels.get('tang_2', 'tăng nhóm 2')} {movement_components.get('tang_2', 0)} hộ; "
                    f"{labels.get('tang_3', 'tăng nhóm 3')} {movement_components.get('tang_3', 0)} hộ; "
                    f"tăng khác có căn cứ chi tiết {movement_components.get('tang_khac', 0)} hộ."
                ),
            ]
            if final_class and unexplained_delta:
                sentence_anchors.append(
                    f"Tổng {final_class} theo phân loại hộ hiện tại là {actual_final_total} hộ; chênh lệch chưa giải thích {unexplained_delta} hộ, không coi phần này là nguyên nhân biến động."
                )
            elif final_class:
                sentence_anchors.append(
                    f"Tổng {final_class} theo phân loại hiện tại là {actual_final_total} hộ, khớp với cuối kỳ theo công thức."
                )
            decrease_df = main[pd.to_numeric(main.get("chenh_lech"), errors="coerce").fillna(0) < 0] if isinstance(main, pd.DataFrame) and not main.empty and "chenh_lech" in main else pd.DataFrame()
            increase_df = main[pd.to_numeric(main.get("chenh_lech"), errors="coerce").fillna(0) > 0] if isinstance(main, pd.DataFrame) and not main.empty and "chenh_lech" in main else pd.DataFrame()
            facts.update({
                "household_focus": template.household_focus,
                "nam_truoc": int(main["nam_truoc"].dropna().iloc[0]) if isinstance(main, pd.DataFrame) and not main.empty and "nam_truoc" in main and not main["nam_truoc"].dropna().empty else None,
                "nam_sau": int(main["nam_sau"].dropna().iloc[0]) if isinstance(main, pd.DataFrame) and not main.empty and "nam_sau" in main and not main["nam_sau"].dropna().empty else None,
                "tong_ky_truoc": total_before,
                "tong_ky_sau": total_after,
                "tong_cuoi_ky_phan_loai": actual_final_total,
                "chenh_lech": delta,
                "ty_le_bien_dong_%": _pct(delta, total_before),
                "movement_components": movement_components,
                "movement_other_policy": movement_other_policy,
                "other_reason_available": other_reason_available,
                "movement_warnings": movement_warnings,
                "unexplained_delta": unexplained_delta,
                "sentence_anchors": sentence_anchors,
                "giam_nhieu_nhat": _top_records(decrease_df, "chenh_lech", "huyen", 3, ascending=True) if isinstance(decrease_df, pd.DataFrame) and not decrease_df.empty else [],
                "tang_nhieu_nhat": _top_records(increase_df, "chenh_lech", "huyen", 3, ascending=False) if isinstance(increase_df, pd.DataFrame) and not increase_df.empty else [],
                "movement_source": "bien_dong_dau_ky_excel_template",
            })

        elif template.pattern in {"deprivation_count", "deprivation_ratio"}:
            main = _flag_table(conn, DEPRIVATION_FLAGS, year, huyen, template.household_focus, include_both_groups=False)
            tables["main"] = main
            facts.update({
                "household_focus": template.household_focus,
                "total_households_in_group": int(main["tong_nhom"].iloc[0]) if not main.empty else 0,
                "top_indicators_by_count": _top_records(main, "so_ho", "chi_tieu", 5),
                "top_indicators_by_ratio": _top_records(main, "ty_le_%", "chi_tieu", 5),
            })

        elif template.pattern == "vulnerable_groups":
            if int(template.id) == 8:
                main = _build_template8_report_table(conn, year, huyen)
            else:
                main = _flag_table(conn, GROUP_FLAGS, year, huyen, None, include_both_groups=True)
            tables["main"] = main
            if int(template.id) == 8:
                district_main = main[main["huyen"].astype(str) != "Toàn tỉnh"].copy() if isinstance(main, pd.DataFrame) and not main.empty and "huyen" in main.columns else main
                facts.update({
                    "template8_columns": [c for c in TEMPLATE8_REPORT_COLUMNS if c != "huyen"],
                    "template8_groups": ["DTTS", "Không có khả năng lao động", "Có người có công với cách mạng"],
                    "top_template8_poor_dtts_districts": _top_records(district_main, "ho_ngheo_dtts", "huyen", 5),
                    "top_template8_near_poor_dtts_districts": _top_records(district_main, "ho_can_ngheo_dtts", "huyen", 5),
                    "top_template8_poor_no_labor_districts": _top_records(district_main, "ho_ngheo_khong_knld", "huyen", 5),
                    "top_template8_near_poor_no_labor_districts": _top_records(district_main, "ho_can_ngheo_khong_knld", "huyen", 5),
                    "top_template8_poor_meritorious_districts": _top_records(district_main, "ho_ngheo_co_cong", "huyen", 5),
                    "top_template8_near_poor_meritorious_districts": _top_records(district_main, "ho_can_ngheo_co_cong", "huyen", 5),
                })
            else:
                facts.update({
                    "top_poor_groups": _top_records(main, "so_ho_ngheo", "chi_tieu", 5),
                    "top_near_poor_groups": _top_records(main, "so_ho_can_ngheo", "chi_tieu", 5),
                })
            facts.setdefault("template_data_warnings", []).append(REVIEW_SCOPE_WARNING)

        elif template.pattern == "ethnicity":
            main = _ethnicity_table(conn, year, huyen)
            tables["main"] = main
            facts.update({
                "top_poor_ethnicities": _top_records(main, "so_ho_ngheo", "dan_toc", 5),
                "top_near_poor_ethnicities": _top_records(main, "so_ho_can_ngheo", "dan_toc", 5),
            })

        elif template.pattern == "causes":
            main = _flag_table(conn, CAUSE_FLAGS, year, huyen, None, include_both_groups=True)
            tables["main"] = main
            facts.update({
                "top_poor_causes": _top_records(main, "so_ho_ngheo", "chi_tieu", 5),
                "top_near_poor_causes": _top_records(main, "so_ho_can_ngheo", "chi_tieu", 5),
            })

        elif template.pattern == "child_deprivation":
            main, child_value_unit = _child_deprivation_table(conn, year, huyen)
            tables["main"] = main
            facts.update({
                "child_deprivation_value_unit": child_value_unit,
                "top_poor_child_deprivations": _top_records(main, "so_ho_ngheo", "chi_tieu", 3),
                "top_near_poor_child_deprivations": _top_records(main, "so_ho_can_ngheo", "chi_tieu", 3),
            })

        elif template.pattern == "multidimensional_standard":
            focus = template.household_focus or POOR
            main = _multidim_table(conn, year, huyen, focus)
            tables["main"] = main
            facts.update({
                "household_focus": focus,
                "top_districts_by_target": _top_records(main, "so_ho_muc_tieu", "huyen", 5),
                "top_districts_by_ratio": _top_records(main, "ty_le_muc_tieu_%", "huyen", 5),
                "total_target_households": int(main["so_ho_muc_tieu"].sum()) if not main.empty else 0,
                "total_target_population": int(main["so_nhan_khau_muc_tieu"].sum()) if not main.empty else 0,
                "total_ethnic_minority_households": int(main["so_ho_dtts"].sum()) if not main.empty else 0,
                "total_local_ethnic_minority_households": int(main["so_ho_dtts_tai_cho"].sum()) if not main.empty else 0,
                "total_ethnic_minority_households_denominator": int(main["tong_ho_dtts"].sum()) if not main.empty and "tong_ho_dtts" in main.columns else 0,
                "total_local_ethnic_minority_households_denominator": int(main["tong_ho_dtts_tai_cho"].sum()) if not main.empty and "tong_ho_dtts_tai_cho" in main.columns else 0,
                "ty_le_ngheo_trong_dtts_%": _pct(int(main["so_ho_dtts"].sum()) if not main.empty else 0, int(main["tong_ho_dtts"].sum()) if not main.empty and "tong_ho_dtts" in main.columns else 0),
                "ty_le_ngheo_trong_dtts_tai_cho_%": _pct(int(main["so_ho_dtts_tai_cho"].sum()) if not main.empty else 0, int(main["tong_ho_dtts_tai_cho"].sum()) if not main.empty and "tong_ho_dtts_tai_cho" in main.columns else 0),
            })
            facts.setdefault("template_data_warnings", []).append(REVIEW_SCOPE_WARNING)
        else:
            main = _overview_table(conn, year, huyen)
            tables["main"] = main

    _attach_template_detail_context(template, tables, facts)

    scope = {"year": year, "huyen": huyen, "scope_label": _fmt_scope(year, huyen)}
    facts = {**summary, **facts}
    return ReportFactsBundle(
        template=template.to_dict(),
        scope=scope,
        summary=summary,
        tables=tables,
        facts=facts,
    )


def bundle_main_table(bundle: ReportFactsBundle) -> pd.DataFrame:
    return bundle.tables.get("main", pd.DataFrame()).copy()
