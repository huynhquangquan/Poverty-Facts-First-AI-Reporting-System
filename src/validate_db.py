from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "db" / "poverty.db"
REPORT_SAMPLES_DIR = PROJECT_ROOT / "data" / "report_samples"

REQUIRED_COLUMNS = {
    "nam",
    "huyen",
    "xa_phuong",
    "phan_loai",
    "so_nhan_khau",
    "bien_dong_dau_ky",
}


def _fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _validate_db() -> list[str]:
    errors: list[str] = []
    if not DB_PATH.exists():
        return [f"Khong tim thay database: {DB_PATH}"]

    with sqlite3.connect(DB_PATH) as conn:
        if not _table_exists(conn, "ho_ngheo"):
            return ["Database thieu bang ho_ngheo."]

        columns = {row[1] for row in conn.execute("PRAGMA table_info(ho_ngheo)").fetchall()}
        missing_columns = sorted(REQUIRED_COLUMNS - columns)
        if missing_columns:
            errors.append("Bang ho_ngheo thieu cot: " + ", ".join(missing_columns))

        row_count = int(conn.execute("SELECT COUNT(*) FROM ho_ngheo").fetchone()[0] or 0)
        if row_count <= 0:
            errors.append("Bang ho_ngheo khong co du lieu.")

        years = [row[0] for row in conn.execute("SELECT DISTINCT nam FROM ho_ngheo ORDER BY nam").fetchall()]
        if not years:
            errors.append("Khong tim thay nam du lieu trong ho_ngheo.")

        if not missing_columns:
            pattern = "%Thoát nghèo%"
            bad_movement = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM ho_ngheo
                    WHERE phan_loai = ? AND bien_dong_dau_ky LIKE ?
                    """,
                    ("Hộ nghèo", pattern),
                ).fetchone()[0]
                or 0
            )
            if bad_movement:
                errors.append(
                    "Con dong phan_loai='Ho ngheo' nhung bien_dong_dau_ky chua 'Thoat ngheo': "
                    f"{bad_movement}"
                )

        print(f"[OK] DB: {DB_PATH}")
        print(f"[OK] ho_ngheo rows: {row_count:,}".replace(",", "."))
        print(f"[OK] years: {', '.join(map(str, years)) if years else 'none'}")
        print(f"[OK] columns: {len(columns)}")

    return errors


def _validate_report_samples() -> list[str]:
    errors: list[str] = []
    if not REPORT_SAMPLES_DIR.exists():
        return [f"Khong tim thay folder mau report: {REPORT_SAMPLES_DIR}"]

    for template_id in range(1, 13):
        matches = sorted(REPORT_SAMPLES_DIR.glob(f"{template_id}. *.xlsx"))
        if not matches:
            errors.append(f"Thieu file Excel mau {template_id}.")

    md_path = REPORT_SAMPLES_DIR / "report_style_examples.md"
    if not md_path.exists():
        errors.append("Thieu report_style_examples.md.")

    xlsx_count = len(list(REPORT_SAMPLES_DIR.glob("*.xlsx")))
    print(f"[OK] report sample xlsx files: {xlsx_count}")
    print(f"[OK] report_style_examples.md: {md_path.exists()}")
    return errors


def main() -> int:
    errors = []
    errors.extend(_validate_db())
    errors.extend(_validate_report_samples())

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return _fail("Validation khong dat.")

    print("[DONE] Validation dat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
