"""
build_db.py
-----------
Đọc tất cả file Excel trong data/enriched/ → convert sang SQLite (db/poverty.db)
Chạy 1 lần duy nhất, hoặc chạy lại khi có file mới.
"""

import os
import glob
import sqlite3
import pandas as pd
from pathlib import Path
from processing_data import recompute_dan_toc_tai_cho, recompute_nhom_ngheo_tong_hop

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "enriched"
DB_PATH  = BASE_DIR / "db" / "poverty.db"

# ── Mapping tên cột sang tên thân thiện (dùng cho query tool) ──────────────
COLUMN_RENAME = {
    "huyen":                              "huyen",
    "nam":                                "nam",
    "ma_ho":                              "ma_ho",
    "chu_ho":                             "chu_ho",
    "gioi_tinh":                          "gioi_tinh",
    "so_nhan_khau":                       "so_nhan_khau",
    "dan_toc_tai_cho":                    "dan_toc_tai_cho",
    "b1_diem":                            "b1_diem",
    "b2_diem":                            "b2_diem",
    "phieu_a":                            "phieu_a",
    "phan_loai":                          "phan_loai",
    "ngay_ra_soat":                       "ngay_ra_soat",
    "nguoi_ra_soat":                      "nguoi_ra_soat",
    "xa_phuong":                          "xa_phuong",
    "dan_toc_chi_tiet":                   "dan_toc_chi_tiet",
    "id_ho":                              "id_ho",
    "tinh":                               "tinh",
    "ma_tinh":                            "ma_tinh",
    "ten_huyen_day_du":                   "ten_huyen_day_du",
    "loai_xa_phuong":                     "loai_xa_phuong",
    "khu_vuc_xa":                         "khu_vuc_xa",
    "xa_dac_biet_kho_khan":               "xa_dac_biet_kho_khan",
    "vung_dia_ly":                        "vung_dia_ly",
    "tinh_bien_gioi":                     "tinh_bien_gioi",
    "so_nguoi_lao_dong":                  "so_nguoi_lao_dong",
    "so_nguoi_cao_tuoi":                  "so_nguoi_cao_tuoi",
    "ty_le_phu_thuoc":                    "ty_le_phu_thuoc",
    "trinh_do_hoc_van_chu_ho":            "trinh_do_hoc_van_chu_ho",
    "suc_khoe_chu_ho":                    "suc_khoe_chu_ho",
    "nghe_nghiep_chu_ho":                 "nghe_nghiep_chu_ho",
    "thu_nhap_bq_thang_nguoi_nghin_dong": "thu_nhap_bq",
    "dien_tich_dat_canh_tac_m2":          "dien_tich_dat",
    "cay_trong_chinh":                    "cay_trong_chinh",
    "co_trau_bo":                         "co_trau_bo",
    "co_lon":                             "co_lon",
    "co_ga_vit":                          "co_ga_vit",
    # Nguyên nhân nghèo
    "nn_khong_co_dat_sx":                 "nn_thieu_dat",
    "nn_khong_co_von":                    "nn_thieu_von",
    "nn_khong_co_lao_dong":               "nn_thieu_lao_dong",
    "nn_khong_co_cong_cu_pt_sx":          "nn_thieu_cong_cu",
    "nn_khong_co_kien_thuc_sx":           "nn_thieu_kien_thuc",
    "nn_khong_co_ky_nang_ld":             "nn_thieu_ky_nang",
    "nn_om_dau_benh_tai_nan":             "nn_om_dau",
    "nn_nguyen_nhan_khac":                "nn_khac",
    # Thiếu hụt DVXHCB
    "thieu_hut_viec_lam":                 "th_viec_lam",
    "thieu_hut_bao_hiem_xa_hoi":          "th_bhxh",
    "thieu_hut_bao_hiem_y_te":            "th_bhyt",
    "thieu_hut_dinh_duong":               "th_dinh_duong",
    "thieu_hut_trinh_do_giao_duc_nguoi_lon": "th_giao_duc_nguoi_lon",
    "thieu_hut_tinh_trang_di_hoc_tre_em": "th_di_hoc_tre_em",
    "thieu_hut_chat_luong_nha_o":         "th_chat_luong_nha",
    "thieu_hut_dien_tich_nha_o":          "th_dien_tich_nha",
    "thieu_hut_nuoc_sach":                "th_nuoc_sach",
    "thieu_hut_nha_tieu_hop_ve_sinh":     "th_nha_tieu",
    "thieu_hut_su_dung_dich_vu_vien_thong": "th_vien_thong",
    "thieu_hut_tai_san_phuc_vu_tiep_can_tt": "th_tai_san_tt",
    "tong_so_chieu_thieu_hut":            "tong_chieu_thieu_hut",
    # Trẻ em
    "co_tre_em_trong_ho":                 "co_tre_em",
    "so_tre_em":                          "so_tre_em",
    "tre_em_thieu_hut_bhyt":              "te_th_bhyt",
    "tre_em_thieu_hut_dinh_duong":        "te_th_dinh_duong",
    "tre_em_thieu_hut_di_hoc":            "te_th_di_hoc",
    "so_tre_thieu_bhyt":                  "so_tre_thieu_bhyt",
    "so_tre_thieu_dinh_duong":            "so_tre_thieu_dinh_duong",
    "so_tre_thieu_di_hoc":                "so_tre_thieu_di_hoc",
    # Nhóm đối tượng
    "nhom_ho_chinh_sach_co_cong":         "nhom_co_cong",
    "nhom_ho_khong_co_kha_nang_lao_dong": "nhom_khong_knld",
    "nhom_ho_dtts_tai_cho":               "nhom_dtts",
    "nhom_chu_ho_la_nu":                  "nhom_chu_ho_nu",
    "nhom_co_nguoi_khuyet_tat":           "nhom_khuyet_tat",
    "nhom_co_nguoi_cao_tuoi":             "nhom_cao_tuoi",
    "nhom_co_tre_em_duoi_6_tuoi":         "nhom_tre_em_duoi6",
    "nhom_co_tre_em_di_hoc":              "nhom_tre_em_di_hoc",
    "nhom_ho_don_than":                   "nhom_don_than",
    "nhom_thuong_binh_liet_si":           "nhom_thuong_binh",
    # Hỗ trợ
    "ho_tro_y_te":                        "htro_y_te",
    "ho_tro_giao_duc":                    "htro_giao_duc",
    "ho_tro_san_xuat":                    "htro_san_xuat",
    "ho_tro_vay_von_tin_dung":            "htro_vay_von",
    "ho_tro_nha_o":                       "htro_nha_o",
    "ho_tro_nuoc_sach_ve_sinh":           "htro_nuoc_sach",
    "ho_tro_dien":                        "htro_dien",
    "ho_tro_vien_thong":                  "htro_vien_thong",
    "ho_tro_dao_tao_nghe":                "htro_dao_tao_nghe",
    "tro_cap_xa_hoi_thuong_xuyen":        "tro_cap_thuong_xuyen",
    "tro_cap_dot_xuat":                   "tro_cap_dot_xuat",
    "chinh_sach_khac":                    "chinh_sach_khac",
    # Tình trạng cơ sở vật chất
    "tinh_trang_nha_o":                   "tinh_trang_nha",
    "nguon_nuoc_su_dung":                 "nguon_nuoc",
    "co_dien_sinh_hoat":                  "co_dien",
    "co_nha_tieu_hop_ve_sinh":            "co_nha_tieu_hvs",
    "co_internet":                        "co_internet",
    "bien_dong_so_dau_ky":                "bien_dong_dau_ky",
    "nhom_ngheo_tong_hop":                "nhom_ngheo_tong_hop",
    "muc_do_thieu_hut_label":             "muc_do_thieu_hut",
    "ky_ra_soat":                         "ky_ra_soat",
}

UNSAFE_WATER_SOURCES = {"Nước suối/khe chưa qua xử lý"}

# Không lưu các nhãn diễn biến "khác" trong DB cuối vì không có cột lý do
# chi tiết để giải thích. Build DB sẽ normalize cả enriched file cũ nếu còn nhãn.
DEPRECATED_MOVEMENT_OTHER_REPLACEMENTS = {
    'Tăng nghèo khác': 'Nghèo cũ (giữ nguyên)',
    'Tăng cận nghèo khác': 'Cận nghèo cũ (giữ nguyên)',
    'Giảm nghèo khác': 'Không thay đổi (không nghèo)',
    'Giảm cận nghèo khác': 'Không thay đổi (không nghèo)',
}


def _binary_from_positive(series):
    return (pd.to_numeric(series, errors="coerce").fillna(0) > 0).astype("int8")


def normalize_semantic_features(df):
    """Apply canonical feature definitions before persisting the database."""
    df = df.copy()
    if "bien_dong_dau_ky" in df.columns:
        df["bien_dong_dau_ky"] = df["bien_dong_dau_ky"].replace(DEPRECATED_MOVEMENT_OTHER_REPLACEMENTS)

    if "dan_toc_chi_tiet" in df.columns:
        def household_key(row):
            ma_ho = row.get("ma_ho")
            return ma_ho if pd.notna(ma_ho) else row.get("id_ho")

        df["dan_toc_tai_cho"] = df.apply(
            lambda row: recompute_dan_toc_tai_cho(
                row.get("dan_toc_chi_tiet"), row.get("huyen"),
                row.get("xa_phuong"), household_key(row),
            ),
            axis=1,
        )
        df["nhom_dtts"] = df["dan_toc_tai_cho"].eq("Có").astype("int8")
        if "phan_loai" in df.columns:
            df["nhom_ngheo_tong_hop"] = df.apply(
                lambda row: recompute_nhom_ngheo_tong_hop(
                    row.get("phan_loai"), row.get("dan_toc_tai_cho")
                ),
                axis=1,
            )
    demographic_cols = {
        "so_nhan_khau", "so_tre_em", "so_nguoi_lao_dong", "so_nguoi_cao_tuoi",
    }
    if demographic_cols.issubset(df.columns):
        df["so_nhan_khau"] = (
            pd.to_numeric(df["so_nhan_khau"], errors="coerce")
            .fillna(1).clip(lower=1).astype(int)
        )
        df["so_tre_em"] = (
            pd.to_numeric(df["so_tre_em"], errors="coerce")
            .fillna(0).clip(lower=0).astype(int)
        )
        df["so_tre_em"] = df[["so_tre_em", "so_nhan_khau"]].min(axis=1).astype(int)
        df["so_nguoi_cao_tuoi"] = (
            pd.to_numeric(df["so_nguoi_cao_tuoi"], errors="coerce")
            .fillna(0).clip(lower=0).astype(int)
        )
        remaining_after_children = df["so_nhan_khau"] - df["so_tre_em"]
        df["so_nguoi_cao_tuoi"] = pd.concat(
            [df["so_nguoi_cao_tuoi"], remaining_after_children], axis=1
        ).min(axis=1).astype(int)
        # Lao động là phần nhân khẩu còn lại để contract cấp hộ luôn khép kín.
        df["so_nguoi_lao_dong"] = (
            df["so_nhan_khau"] - df["so_tre_em"] - df["so_nguoi_cao_tuoi"]
        ).astype(int)

    if "so_tre_em" in df.columns:
        df["co_tre_em"] = _binary_from_positive(df["so_tre_em"])
        no_children = df["so_tre_em"].eq(0)
        child_deprivation_pairs = {
            "so_tre_thieu_bhyt": "te_th_bhyt",
            "so_tre_thieu_dinh_duong": "te_th_dinh_duong",
            "so_tre_thieu_di_hoc": "te_th_di_hoc",
        }
        for count_col, flag_col in child_deprivation_pairs.items():
            if count_col in df.columns:
                df[count_col] = (
                    pd.to_numeric(df[count_col], errors="coerce")
                    .fillna(0).clip(lower=0).astype(int)
                )
                df[count_col] = df[[count_col, "so_tre_em"]].min(axis=1).astype(int)
            elif flag_col in df.columns:
                # Compatibility path for old enriched files: flags remain household-level.
                # Use 0/1 as a conservative case count until the rebuilt DB provides true child counts.
                df[count_col] = (
                    pd.to_numeric(df[flag_col], errors="coerce")
                    .fillna(0).gt(0).astype(int)
                )
        for col in (
            "nhom_tre_em_duoi6", "nhom_tre_em_di_hoc",
            "te_th_bhyt", "te_th_dinh_duong", "te_th_di_hoc",
            "so_tre_thieu_bhyt", "so_tre_thieu_dinh_duong", "so_tre_thieu_di_hoc",
            "th_dinh_duong", "th_di_hoc_tre_em",
        ):
            if col in df.columns:
                df.loc[no_children, col] = 0

    if "so_nguoi_cao_tuoi" in df.columns:
        df["nhom_cao_tuoi"] = _binary_from_positive(df["so_nguoi_cao_tuoi"])

    # nhom_don_than: KHÔNG tính lại từ so_nhan_khau.
    # Đây là nhãn chính sách do cán bộ rà soát xác định ("chủ hộ đơn thân"),
    # không đồng nghĩa với so_nhan_khau == 1. Giữ nguyên giá trị từ file gốc.

    # nhom_khong_knld: KHÔNG tính lại từ so_nguoi_lao_dong.
    # Đây là nhóm được công nhận qua hồ sơ (bệnh án, giấy khuyết tật...).
    # Giữ nguyên giá trị từ file gốc.

    # ty_le_phu_thuoc: tính lại chính xác để tránh floating point drift
    if all(c in df.columns for c in ["so_tre_em", "so_nguoi_cao_tuoi", "so_nguoi_lao_dong"]):
        phu_thuoc = (
            pd.to_numeric(df["so_tre_em"], errors="coerce").fillna(0)
            + pd.to_numeric(df["so_nguoi_cao_tuoi"], errors="coerce").fillna(0)
        )
        lao_dong = pd.to_numeric(df["so_nguoi_lao_dong"], errors="coerce").fillna(1).clip(lower=1)
        df["ty_le_phu_thuoc"] = (phu_thuoc / lao_dong).round(2)

    if "co_nha_tieu_hvs" in df.columns:
        co_nha_tieu = pd.to_numeric(df["co_nha_tieu_hvs"], errors="coerce").fillna(0)
        df["th_nha_tieu"] = co_nha_tieu.eq(0).astype("int8")

    if "tinh_trang_nha" in df.columns:
        df["th_chat_luong_nha"] = df["tinh_trang_nha"].isin(
            {"Nhà tạm", "Nhà đơn sơ", "Không có nhà"}
        ).astype("int8")

    if "nguon_nuoc" in df.columns:
        df["th_nuoc_sach"] = df["nguon_nuoc"].isin(UNSAFE_WATER_SOURCES).astype("int8")

    dimension_pairs = (
        ("th_viec_lam", "th_bhxh"),
        ("th_bhyt", "th_dinh_duong"),
        ("th_giao_duc_nguoi_lon", "th_di_hoc_tre_em"),
        ("th_chat_luong_nha", "th_dien_tich_nha"),
        ("th_nuoc_sach", "th_nha_tieu"),
        ("th_vien_thong", "th_tai_san_tt"),
    )
    if all(col in df.columns for pair in dimension_pairs for col in pair):
        df["tong_chieu_thieu_hut"] = sum(
            (pd.to_numeric(df[left], errors="coerce").fillna(0).gt(0)
             | pd.to_numeric(df[right], errors="coerce").fillna(0).gt(0)).astype("int8")
            for left, right in dimension_pairs
        )

    return df


def build_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    excel_files = [
        path for path in glob.glob(str(DATA_DIR / "*.xlsx"))
        if Path(path).name.lower() != "combined_all.xlsx"
    ]
    if not excel_files:
        print(f"[ERROR] Không tìm thấy file Excel nào trong {DATA_DIR}")
        return False

    print(f"[INFO] Tìm thấy {len(excel_files)} file Excel. Bắt đầu convert...")

    all_dfs = []
    for fpath in sorted(excel_files):
        fname = os.path.basename(fpath)
        try:
            df = pd.read_excel(fpath, engine="openpyxl")
            df.columns = [c.strip().lower() for c in df.columns]
            # Rename theo mapping, giữ nguyên cột nào không có trong mapping
            df = df.rename(columns={k: v for k, v in COLUMN_RENAME.items() if k in df.columns})
            all_dfs.append(df)
            print(f"  ✓ {fname}: {len(df)} hàng, {len(df.columns)} cột")
        except Exception as e:
            print(f"  ✗ {fname}: {e}")

    if not all_dfs:
        print("[ERROR] Không load được file nào.")
        return False

    combined = pd.concat(all_dfs, ignore_index=True)

    # Chuẩn hóa cột phan_loai (nhãn mục tiêu)
    if "phan_loai" in combined.columns:
        combined["phan_loai"] = combined["phan_loai"].str.strip()

    # Chuẩn hóa năm thành integer
    if "nam" in combined.columns:
        combined["nam"] = pd.to_numeric(combined["nam"], errors="coerce").astype("Int64")

    combined = normalize_semantic_features(combined)
    combined = combined.drop(columns=["so_tre_em_trong_ho"], errors="ignore")

    print(f"\n[INFO] Tổng cộng: {len(combined):,} hàng — đang ghi vào {DB_PATH}...")

    conn = sqlite3.connect(DB_PATH)
    combined.to_sql("ho_ngheo", conn, if_exists="replace", index=False)

    # Tạo indexes để query nhanh
    cursor = conn.cursor()
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_huyen   ON ho_ngheo(huyen)",
        "CREATE INDEX IF NOT EXISTS idx_nam      ON ho_ngheo(nam)",
        "CREATE INDEX IF NOT EXISTS idx_phanloai ON ho_ngheo(phan_loai)",
        "CREATE INDEX IF NOT EXISTS idx_xa       ON ho_ngheo(xa_phuong)",
        "CREATE INDEX IF NOT EXISTS idx_dantoc   ON ho_ngheo(dan_toc_chi_tiet)",
    ]
    for idx_sql in indexes:
        cursor.execute(idx_sql)
    conn.commit()

    # Lưu metadata từ chính dữ liệu đã ghi, không dùng số đếm trước persist.
    cursor.execute("SELECT COUNT(*) FROM ho_ngheo")
    persisted_total_rows = int(cursor.fetchone()[0])
    meta = pd.DataFrame({
        "key": ["total_rows", "columns", "huyen_list", "nam_list", "phan_loai_list"],
        "value": [
            str(persisted_total_rows),
            str(list(combined.columns)),
            str(sorted(combined["huyen"].dropna().unique().tolist()) if "huyen" in combined.columns else []),
            str(sorted(combined["nam"].dropna().unique().tolist()) if "nam" in combined.columns else []),
            str(combined["phan_loai"].dropna().unique().tolist() if "phan_loai" in combined.columns else []),
        ]
    })
    meta.to_sql("metadata", conn, if_exists="replace", index=False)
    conn.close()

    print(f"[DONE] Database sẵn sàng: {DB_PATH}")
    print(f"       Tổng bản ghi: {persisted_total_rows:,}")
    return True


if __name__ == "__main__":
    build_database()
