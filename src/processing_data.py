"""
processing_data.py
==================

Chạy: python processing_data.py
"""

import hashlib
import os
import random
import re
import unicodedata
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

random.seed(42)
np.random.seed(42)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(BASE_DIR, "data", "raw")
DEFAULT_OUT = os.path.join(BASE_DIR, "data", "cleaned")
AUDIT_DIR   = os.path.join(BASE_DIR, "data", "audit")
SRC = DEFAULT_SRC
OUT = DEFAULT_OUT
os.makedirs(SRC, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
os.makedirs(AUDIT_DIR, exist_ok=True)

CLEANED_REQUIRED_COLUMNS = [
    'huyen', 'nam', 'ma_ho', 'chu_ho', 'gioi_tinh', 'so_nhan_khau',
    'dan_toc_tai_cho', 'b1_diem', 'b2_diem', 'phieu_a', 'phan_loai',
    'ngay_ra_soat', 'nguoi_ra_soat', 'xa_phuong', 'dan_toc_chi_tiet',
]
VALID_PHAN_LOAI = {'Hộ nghèo', 'Hộ cận nghèo', 'Hộ không nghèo'}

# Các cột dùng cho Bước A — xóa trùng tuyệt đối
# Một dòng bị coi là trùng tuyệt đối khi TẤT CẢ các cột này giống hệt nhau.
EXACT_DEDUP_COLS = [
    'ngay_ra_soat', 'chu_ho', 'ma_ho', 'dan_toc_tai_cho', 'gioi_tinh',
    'so_nhan_khau', 'phieu_a', 'b1_diem', 'b2_diem', 'phan_loai', 'nguoi_ra_soat',
]

# Các cột "nghi ngờ" — trùng những cột này nhưng khác b1/b2/ngày/reviewer
# → đưa vào audit thay vì xóa
SUSPECT_COLS = ['chu_ho', 'gioi_tinh', 'so_nhan_khau', 'phan_loai']


# ═══════════════════════════════════════════════════════════════
# A. QUY TẮC DÂN TỘC (tích hợp từ ethnicity_rules.py)
# ═══════════════════════════════════════════════════════════════

LOCAL_ETHNICITIES = {"M'Nông", "Mạ", "S'tiêng"}
NON_LOCAL_ETHNICITIES = {
    "Kinh", "Tày", "Nùng", "Dao", "Mông", "Thái", "Mường", "Khác",
}


def _normalized(value) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def recompute_dan_toc_tai_cho(
    dan_toc_chi_tiet,
    huyen=None,
    xa_phuong=None,
    household_key=None,
) -> str:
    """Derive local-ethnicity status; never consult the previous status value."""
    ethnicity = _normalized(dan_toc_chi_tiet)
    if ethnicity in LOCAL_ETHNICITIES:
        return "Có"
    if ethnicity in NON_LOCAL_ETHNICITIES:
        return "Không"
    if ethnicity == "Ê-đê":
        stable_key = "|".join(_normalized(v) for v in (
            huyen, xa_phuong, household_key, ethnicity,
        ))
        bucket = int(hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:8], 16) % 100
        return "Có" if bucket < 80 else "Không"
    return "Không"


def recompute_nhom_ngheo_tong_hop(phan_loai, dan_toc_tai_cho) -> str:
    if _normalized(phan_loai) == "Hộ không nghèo":
        return "Không nghèo"
    return "Nghèo DTTS tại chỗ" if _normalized(dan_toc_tai_cho) == "Có" else "Nghèo kinh tế thuần"


# Wrapper giữ nguyên tên cũ để không phá code bên dưới
def get_dan_toc_tai_cho(dan_toc_chi_tiet, huyen=None, xa_phuong=None, household_key=None):
    return recompute_dan_toc_tai_cho(dan_toc_chi_tiet, huyen, xa_phuong, household_key)


# ═══════════════════════════════════════════════════════════════
# B. SCHEMA CONTRACT
# ═══════════════════════════════════════════════════════════════

def normalize_cleaned_schema(df, huyen_name, year):
    """Enforce the base-data contract consumed by feature_engineering.py."""
    df = df.copy()
    df['huyen'] = huyen_name
    df['nam'] = int(year)
    df['ma_ho'] = df['ma_ho'].astype(str).str.strip()
    df['chu_ho'] = df['chu_ho'].fillna('').astype(str).str.strip()
    df['phan_loai'] = df['phan_loai'].astype(str).str.strip()

    missing_phan_loai = (
        df['phan_loai'].isna()
        | df['phan_loai'].astype(str).str.strip().isin(['', 'nan', 'NaN', '--'])
    )

    df.loc[missing_phan_loai, 'phan_loai'] = 'Hộ không nghèo'
    df['so_nhan_khau'] = (
        pd.to_numeric(df['so_nhan_khau'], errors='coerce')
        .fillna(1).clip(lower=1).astype(int)
    )
    df['b1_diem'] = pd.to_numeric(df['b1_diem'], errors='coerce').fillna(0).clip(lower=0)
    df['b2_diem'] = pd.to_numeric(df['b2_diem'], errors='coerce').fillna(0).clip(lower=0)
    return df


def validate_cleaned_schema(df):
    missing = [col for col in CLEANED_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Thiếu cột cleaned bắt buộc: {missing}")
    if (df['so_nhan_khau'] < 1).any():
        raise ValueError("so_nhan_khau phải >= 1")
    invalid_phan_loai = sorted(set(df['phan_loai'].dropna()) - VALID_PHAN_LOAI)
    if invalid_phan_loai:
        raise ValueError(f"phan_loai có giá trị không hợp lệ, cần kiểm tra raw: {invalid_phan_loai}")


# ═══════════════════════════════════════════════════════════════
# C. TÌM FILE ĐẦU VÀO
# ═══════════════════════════════════════════════════════════════

def normalize_filename(fn):
    fn = fn or ""
    fn = fn.replace("_", " ").replace("-", " ").strip().lower()
    fn = unicodedata.normalize("NFKD", fn)
    fn = "".join(ch for ch in fn if not unicodedata.combining(ch))
    fn = re.sub(r"[^a-z0-9\s]", " ", fn)
    fn = re.sub(r"\s+", " ", fn).strip()
    return fn


def find_input_file(fname, huyen, year):
    candidate_path = os.path.join(SRC, fname)
    if os.path.exists(candidate_path):
        return candidate_path, fname

    year_str   = str(year)
    huyen_norm = normalize_filename(huyen)
    candidates = [c for c in os.listdir(SRC) if os.path.isfile(os.path.join(SRC, c))]

    for c in candidates:
        cand_norm = normalize_filename(c)
        if huyen_norm in cand_norm and year_str in cand_norm:
            return os.path.join(SRC, c), c

    target_tokens = normalize_filename(fname).split()
    best_match, best_score = None, 0
    for c in candidates:
        cand_norm = normalize_filename(c)
        score = sum(1 for token in target_tokens if token and token in cand_norm)
        if score > best_score:
            best_score = score
            best_match = c

    if best_match and best_score >= max(1, len(target_tokens) // 2):
        return os.path.join(SRC, best_match), best_match

    return None, None


# ═══════════════════════════════════════════════════════════════
# D. CẤU HÌNH ĐỊA LÝ & DÂN SỐ
# ═══════════════════════════════════════════════════════════════

# 1. Danh sách xã/phường và trọng số phân bổ
XA_PHUONG_MAP = {
    'Cư Jút': {
        'xa_list': ["Thị trấn Ea T'ling", 'Xã Ea Pô', 'Xã Nam Dong', 'Xã Đắk DRông',
                    'Xã Tâm Thắng', 'Xã Cư Knia', 'Xã Trúc Sơn', 'Xã Đắk Wil'],
        'weights': [0.16, 0.12, 0.12, 0.13, 0.12, 0.12, 0.11, 0.12],
        'type': 'huyen',
    },
    'Đăk Glong': {
        'xa_list': ['Xã Đắk Ha', 'Xã Đắk Plao', "Xã Đắk R'Măng", 'Xã Đắk Som',
                    'Xã Quảng Hoà', 'Xã Quảng Khê', 'Xã Quảng Sơn'],
        'weights': [0.17, 0.15, 0.15, 0.14, 0.14, 0.13, 0.12],
        'type': 'huyen',
    },
    'Đắk Mil': {
        'xa_list': ['Thị trấn Đắk Mil', 'Xã Đắk Lao', "Xã Đắk R'La", 'Xã Đắk Gằn',
                    "Xã Đắk N'Drót", 'Xã Đắk Sắk', 'Xã Đức Mạnh', 'Xã Đức Minh',
                    'Xã Long Sơn', 'Xã Thuận An'],
        'weights': [0.15, 0.11, 0.10, 0.10, 0.09, 0.09, 0.09, 0.09, 0.09, 0.09],
        'type': 'huyen',
    },
    'Đắk RLấp': {
        'xa_list': ['Thị trấn Kiến Đức', 'Xã Nhân Cơ', 'Xã Kiến Thành', 'Xã Nghĩa Thắng',
                    'Xã Đạo Nghĩa', 'Xã Đắk Ru', 'Xã Hưng Bình', 'Xã Đắk Sin',
                    'Xã Quảng Tín', 'Xã Đắk Wer', 'Xã Nhân Đạo'],
        'weights': [0.13, 0.10, 0.10, 0.09, 0.09, 0.09, 0.08, 0.07, 0.07, 0.07, 0.11],
        'type': 'huyen',
    },
    'Đắk Song': {
        'xa_list': ['Thị trấn Đức An', 'Xã Đắk Môl', 'Xã Đắk Hòa', 'Xã Nam Bình',
                    'Xã Thuận Hà', 'Xã Thuận Hạnh', "Xã Đắk N'Drung",
                    "Xã Nâm N'Jang", 'Xã Trường Xuân'],
        'weights': [0.17, 0.13, 0.13, 0.12, 0.11, 0.10, 0.09, 0.08, 0.07],
        'type': 'huyen',
    },
    'Krông Nô': {
        'xa_list': ['Thị trấn Đắk Mâm', 'Xã Đắk Sôr', 'Xã Nam Xuân', 'Xã Buôn Choah',
                    'Xã Nam Đà', 'Xã Tân Thành', 'Xã Đắk Drô', 'Xã Nâm Nung',
                    'Xã Đức Xuyên', 'Xã Đắk Nang', 'Xã Quảng Phú', "Xã Nâm N'Đir"],
        'weights': [0.13, 0.10, 0.09, 0.09, 0.08, 0.08, 0.08, 0.08, 0.08, 0.07, 0.07, 0.05],
        'type': 'huyen',
    },
    'Tuy Đức': {
        'xa_list': ['Xã Quảng Trực', 'Xã Đắk Buk So', 'Xã Quảng Tâm',
                    "Xã Đắk R'Tíh", 'Xã Đắk Ngo', 'Xã Quảng Tân'],
        'weights': [0.20, 0.18, 0.17, 0.17, 0.15, 0.13],
        'type': 'huyen',
    },
    'Gia Nghĩa': {
        'xa_list': ['Phường Nghĩa Đức', 'Phường Nghĩa Thành', 'Phường Nghĩa Phú',
                    'Phường Nghĩa Tân', 'Phường Nghĩa Trung',
                    "Xã Đắk R'Moan", 'Phường Quảng Thành', 'Xã Đắk Nia'],
        'weights': [0.18, 0.16, 0.14, 0.14, 0.12, 0.10, 0.08, 0.08],
        'type': 'tp',
    },
}

# 2. Phân bố dân tộc theo huyện
DAN_TOC_MAP = {
    'Cư Jút': {
        'dan_toc': ['Kinh', 'Ê-đê', 'Tày', 'Nùng', "M'Nông", 'Mông', 'Thái', 'Dao', 'Mường', 'Khác'],
        'weights': [0.50, 0.15, 0.09, 0.07, 0.05, 0.04, 0.03, 0.03, 0.02, 0.02],
    },
    'Đăk Glong': {
        'dan_toc': ['Kinh', 'Mông', 'Dao', 'Tày', 'Nùng', "M'Nông", 'Mạ', 'Thái', 'Ê-đê', 'Khác'],
        'weights': [0.38, 0.18, 0.12, 0.09, 0.07, 0.05, 0.04, 0.03, 0.02, 0.02],
    },
    'Đắk Mil': {
        'dan_toc': ['Kinh', 'Ê-đê', 'Tày', 'Nùng', "M'Nông", 'Mông', 'Thái', 'Mường', 'Dao', 'Khác'],
        'weights': [0.52, 0.14, 0.09, 0.07, 0.06, 0.04, 0.03, 0.02, 0.02, 0.01],
    },
    'Đắk RLấp': {
        'dan_toc': ['Kinh', "S'tiêng", "M'Nông", 'Tày', 'Nùng', 'Ê-đê', 'Mông', 'Dao', 'Mạ', 'Khác'],
        'weights': [0.50, 0.13, 0.10, 0.08, 0.06, 0.05, 0.04, 0.02, 0.01, 0.01],
    },
    'Đắk Song': {
        'dan_toc': ['Kinh', "M'Nông", 'Ê-đê', 'Tày', 'Nùng', 'Mạ', 'Mông', 'Dao', 'Thái', 'Khác'],
        'weights': [0.44, 0.18, 0.12, 0.08, 0.06, 0.04, 0.03, 0.02, 0.02, 0.01],
    },
    'Krông Nô': {
        'dan_toc': ['Kinh', "M'Nông", 'Ê-đê', 'Tày', 'Nùng', 'Mạ', 'Thái', 'Dao', 'Mông', 'Khác'],
        'weights': [0.45, 0.20, 0.10, 0.08, 0.06, 0.03, 0.03, 0.02, 0.02, 0.01],
    },
    'Tuy Đức': {
        'dan_toc': ['Kinh', "M'Nông", 'Mạ', 'Ê-đê', 'Mông', 'Dao', 'Tày', 'Nùng', "S'tiêng", 'Khác'],
        'weights': [0.38, 0.22, 0.14, 0.08, 0.06, 0.04, 0.03, 0.02, 0.02, 0.01],
    },
    'Gia Nghĩa': {
        'dan_toc': ['Kinh', "M'Nông", 'Tày', 'Nùng', 'Mạ', 'Ê-đê', 'Mông', 'Dao', 'Mường', 'Khác'],
        'weights': [0.55, 0.15, 0.08, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.01],
    },
}

# 3. Reviewer theo huyện
REVIEWERS_MAP = {
    'Cư Jút':    ['BÙI KIM LOAN', 'TRẦN CÔNG KHÁ', 'TRẦN VĂN CƯỜNG', 'Y TAIH PRIÊNG',
                  'ĐOÀN THỊ HUỆ', 'TRẦN VIỆT HÙNG', 'VŨ ĐÌNH BÁCH', 'Y BA ÊBAN'],
    'Đăk Glong': ['Nông Ngọc Nam', 'Hoàng Văn Hải', 'Giàng Văn Tu', 'Hoàng Văn Dẩu',
                  'Nông Thái Dương', 'Tào Văn Huy', 'Lục Văn Cương', 'Hoàng A Tú'],
    'Đắk Mil':   ['Nguyễn Như Chinh', 'Đỗ Ngọc Sơn', 'Nguyễn Hữu Nhật', 'Võ Đình Kính',
                  'Y Gơn', 'Hà Quang Đạo', 'Lầu Văn Sình', 'Triệu Văn Lâm'],
    'Đắk RLấp':  ['Dương Mạnh Hùng', 'Vũ Văn Khuyến', 'Phan Văn Sức', 'Nguyễn Văn Thạnh',
                  'Nguyễn Văn Đậm', 'Voong Sơn Dương', 'K Bang', 'Bùi Minh Thuận'],
    'Đắk Song':  ['Đinh Xôm Xốp', 'Nguyễn Huy Cường', 'Triệu Văn Tuất', 'Nguyễn Ngọc Tần',
                  'Nguyễn Văn Trình', 'Hoàng Văn Tuyên', 'Lê Thị Liên', 'H El'],
    'Krông Nô':  ['Đặng Văn Nguyên', 'Lương Văn Thành', 'Y Krang', 'Hoàng Văn Tiến',
                  'Nguyễn Văn Vịnh', 'Hoàng Văn Trung', 'Hà Văn Nhàn', 'Y Chêm'],
    'Tuy Đức':   ['Cao Bá Lực', 'Điểu Tình', 'Điểu Hùng', 'Bùi Trọng Quyên',
                  'Mạc Đức Hải', 'Điểu Ntơnh', 'Hoàng Văn Vinh', 'Lầu A Mãn'],
    'Gia Nghĩa': ['Hoàng Trung Hiếu', 'K Krá', 'Nguyễn Văn Hồi',
                  'Trần Thị Minh', 'Lê Văn Phúc', 'Nguyễn Thị Lan'],
}


# ═══════════════════════════════════════════════════════════════
# E. SINH DỮ LIỆU PHỤ TRỢ
# ═══════════════════════════════════════════════════════════════

def get_b1_b2_params(xa_phuong, dan_toc, phan_loai, huyen_xa_list):
    """Tính tham số phân phối B1/B2 dựa trên địa bàn và dân tộc."""
    is_urban = xa_phuong.startswith('Thị trấn') or xa_phuong.startswith('Phường')
    is_kho_khan = any(kk in xa_phuong for kk in [
        'Đắk DRông', 'Nam Dong', 'Đắk Nang', "Đắk R'Măng",
        'Đắk Plao', 'Đắk Som', 'Đắk Ngo', 'Quảng Trực', 'Nâm Nung',
    ])
    is_kinh          = (dan_toc == 'Kinh')
    is_dtts_kho_khan = dan_toc in ['Mông', 'Dao', "M'Nông", 'Mạ']

    b1_offset = b2_offset = 0
    if is_urban:          b1_offset += 8;  b2_offset -= 3
    if is_kho_khan:       b1_offset -= 8;  b2_offset += 5
    if is_kinh:           b1_offset += 5;  b2_offset -= 3
    if is_dtts_kho_khan:  b1_offset -= 5;  b2_offset += 4

    if phan_loai == 'Hộ không nghèo':
        return min(185, 155 + b1_offset), 18, max(2, 8 + b2_offset), 5
    elif phan_loai == 'Hộ cận nghèo':
        return min(145, 122 + b1_offset), 15, max(5, 20 + b2_offset), 7
    else:  # Hộ nghèo
        return min(125, 88 + b1_offset), 18, max(10, 38 + b2_offset), 10


def gen_b1_b2(xa_phuong, dan_toc, phan_loai, huyen_xa_list):
    b1_mean, b1_std, b2_mean, b2_std = get_b1_b2_params(xa_phuong, dan_toc, phan_loai, huyen_xa_list)
    b1 = round(int(np.clip(np.random.normal(b1_mean, b1_std), 30, 200)) / 5) * 5
    b2 = round(int(np.clip(np.random.normal(b2_mean, b2_std), 0, 70)) / 5) * 5
    return max(0, b1), max(0, b2)


def gen_date(year):
    """Sinh ngày rà soát ngẫu nhiên trong Quý IV (tháng 10–11)."""
    base  = datetime(year, 10, 1)
    delta = timedelta(days=int(np.random.uniform(0, 60)))
    return (base + delta).strftime('%d/%m/%Y')


# ═══════════════════════════════════════════════════════════════
# F. DEDUP LOGIC — theo note nghiệp vụ
# ═══════════════════════════════════════════════════════════════

def _normalize_dedup_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hóa nhẹ các cột dùng để so sánh trùng (không thay đổi df gốc)."""
    d = df.copy()
    for col in ['chu_ho', 'ma_ho', 'gioi_tinh', 'phan_loai', 'phieu_a',
                'dan_toc_tai_cho', 'nguoi_ra_soat', 'ngay_ra_soat']:
        if col in d.columns:
            d[col] = d[col].fillna('').astype(str).str.strip()
    for col in ['so_nhan_khau', 'b1_diem', 'b2_diem']:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors='coerce').fillna(0)
    return d


def dedup_and_audit(df: pd.DataFrame, huyen_name: str, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Thực hiện dedup 2 bước theo note nghiệp vụ.

    Bước A — Xóa trùng tuyệt đối:
        Chỉ drop khi TẤT CẢ các cột trong EXACT_DEDUP_COLS giống hệt nhau.
        Giữ lại dòng đầu tiên (ưu tiên dòng có ngày + b1 đầy đủ nhất).

    Bước B — Đổi mã hộ trùng:
        Sau bước A, nếu còn nhiều dòng cùng ma_ho nhưng thông tin khác nhau:
        → giữ tất cả, đổi mã: 123, 123a, 123b …

    Audit:
        Các nhóm nghi ngờ (cùng chu_ho + gioi_tinh + so_nhan_khau + phan_loai
        nhưng b1/b2/ngày/reviewer khác nhau) được ghi ra file audit để kiểm tra thủ công.
        Những hộ này KHÔNG bị xóa.

    Returns:
        (df_clean, df_audit)
    """
    d = _normalize_dedup_cols(df)

    # ── Bước A: xóa trùng tuyệt đối ─────────────────────────────
    # Sắp xếp ưu tiên: dòng có ngày + b1 đầy đủ lên trên
    existing_exact = [c for c in EXACT_DEDUP_COLS if c in d.columns]
    d['_has_date'] = (d['ngay_ra_soat'].astype(str).str.strip() != '') & (d['ngay_ra_soat'] != 'nan')
    d['_has_b1']   = (pd.to_numeric(df.get('b1_diem', pd.Series(dtype=float)), errors='coerce') > 0)
    d = d.sort_values(by=['_has_date', '_has_b1'], ascending=[False, False])
    df = df.loc[d.index]       # áp thứ tự sắp xếp lên df gốc

    before_a = len(df)
    dup_mask_exact = d.duplicated(subset=existing_exact, keep='first')
    df_clean = df[~dup_mask_exact].copy()
    n_dropped_exact = before_a - len(df_clean)
    if n_dropped_exact:
        print(f"    [Bước A] Xóa {n_dropped_exact} dòng trùng tuyệt đối.")

    # Cập nhật d tương ứng
    d_clean = _normalize_dedup_cols(df_clean)

    # ── Bước B: đổi mã hộ trùng (giữ tất cả dòng) ───────────────
    dup_rank = d_clean.groupby('ma_ho').cumcount()
    df_clean['ma_ho'] = df_clean['ma_ho'].astype(str).str.strip()
    def suffix_alpha(rank: int) -> str:
        # rank: 0,1,2 -> a,b,c
        letters = "abcdefghijklmnopqrstuvwxyz"
        if rank < len(letters):
            return letters[rank]

        # phòng trường hợp trùng > 26 hộ cùng mã
        n = rank
        out = ""
        while True:
            out = letters[n % 26] + out
            n = n // 26 - 1
            if n < 0:
                break
        return out
    df_clean['ma_ho'] = [
        row if rank == 0 else f"{row}{suffix_alpha(rank - 1)}"
        for row, rank in zip(df_clean['ma_ho'].tolist(), dup_rank.tolist())
    ]
    n_renamed = int((dup_rank > 0).sum())
    if n_renamed:
        print(f"    [Bước B] Đổi mã cho {n_renamed} dòng có ma_ho trùng (giữ nguyên hộ, chỉ đổi mã).")

    # ── Audit: nhóm nghi ngờ ────────────────────────────────────
    # Cùng chu_ho + gioi_tinh + so_nhan_khau + phan_loai → nghi trùng
    # Nhưng khác b1/b2/ngày/reviewer → KHÔNG xóa, chỉ ghi audit
    suspect_cols_existing = [c for c in SUSPECT_COLS if c in d_clean.columns]
    suspect_mask = d_clean.duplicated(subset=suspect_cols_existing, keep=False)
    df_audit = df_clean[suspect_mask].copy() if suspect_mask.any() else pd.DataFrame()
    if not df_audit.empty:
        df_audit['_audit_note'] = (
            f"Nghi trùng hộ ({huyen_name} {year}): "
            "cùng chu_ho+gioi_tinh+so_nhan_khau+phan_loai nhưng khác b1/b2/ngày/reviewer. "
            "Không xóa — cần kiểm tra thủ công."
        )
        n_suspect = len(df_audit)
        print(f"    [Audit] {n_suspect} dòng nghi trùng → ghi vào audit file (KHÔNG xóa).")

    # Xóa cột phụ trợ
    for col in ['_has_date', '_has_b1']:
        df_clean.drop(columns=[col], errors='ignore', inplace=True)
        if col in df_audit.columns:
            df_audit.drop(columns=[col], errors='ignore', inplace=True)

    return df_clean.reset_index(drop=True), df_audit


# ═══════════════════════════════════════════════════════════════
# G. HÀM CHÍNH: CLEAN MỘT FILE
# ═══════════════════════════════════════════════════════════════

def clean_file(filepath, huyen_name, year, output_path):
    df = pd.read_excel(filepath, sheet_name='data')
    # Bỏ hàng tiêu đề thứ 2
    df = df[df['date'] != 'Thời gian rà soát'].reset_index(drop=True)

    # Đổi tên cột
    df = df.rename(columns={
        'date':                    'ngay_ra_soat',
        'family.hostName':         'chu_ho',
        'family.code':             'ma_ho',
        'family.coDanTocTaiCho':   'dan_toc_tai_cho',
        'family.hostGender':       'gioi_tinh',
        'family.numberOfMembers':  'so_nhan_khau',
        'quickReview.result':      'phieu_a',
        'b1Point':                 'b1_diem',
        'b2Point':                 'b2_diem',
        'classify':                'phan_loai',
        'reviewer':                'nguoi_ra_soat',
    })

    df['huyen'] = huyen_name
    df['nam']   = year
    df['ma_ho'] = df['ma_ho'].astype(str).str.strip()

    print(f"    Số dòng gốc từ file: {len(df)}")

    # ── Bước 1: Dedup theo note nghiệp vụ ─────────────────────────
    df, df_audit = dedup_and_audit(df, huyen_name, year)

    # Lưu audit nếu có
    if not df_audit.empty:
        audit_path = os.path.join(
            AUDIT_DIR,
            f"audit_{huyen_name.replace(' ', '_')}_{year}.xlsx",
        )
        df_audit.to_excel(audit_path, index=False)
        print(f"    [Audit] Đã lưu: {audit_path}")

    # ── Bước 2: Xã/phường ────────────────────────────────────────
    xa_cfg     = XA_PHUONG_MAP[huyen_name]
    xa_list    = xa_cfg['xa_list']
    xa_weights = xa_cfg['weights']

    if 'xa_phuong' not in df.columns:
        df['xa_phuong'] = pd.NA

    missing_xa = (
        df['xa_phuong'].isna()
        | df['xa_phuong'].astype(str).str.strip().isin(['', 'nan', 'NaN', '--'])
    )

    df.loc[missing_xa, 'xa_phuong'] = np.random.choice(
        xa_list,
        size=int(missing_xa.sum()),
        p=xa_weights
    )

    # ── Bước 3: Dân tộc chi tiết ─────────────────────────────────
    dt_cfg = DAN_TOC_MAP[huyen_name]

    if 'dan_toc_chi_tiet' not in df.columns:
        df['dan_toc_chi_tiet'] = pd.NA

    missing_dt = (
        df['dan_toc_chi_tiet'].isna()
        | df['dan_toc_chi_tiet'].astype(str).str.strip().isin(['', 'nan', 'NaN', '--'])
    )

    df.loc[missing_dt, 'dan_toc_chi_tiet'] = np.random.choice(
        dt_cfg['dan_toc'],
        size=int(missing_dt.sum()),
        p=dt_cfg['weights']
    )

    # ── Bước 4: Tính lại dan_toc_tai_cho từ dân tộc chi tiết ─────
    if 'dan_toc_tai_cho' not in df.columns:
        df['dan_toc_tai_cho'] = pd.NA

    missing_tai_cho = (
        df['dan_toc_tai_cho'].isna()
        | df['dan_toc_tai_cho'].astype(str).str.strip().isin(['', 'nan', 'NaN', '--'])
    )

    df.loc[missing_tai_cho, 'dan_toc_tai_cho'] = df.loc[missing_tai_cho].apply(
        lambda row: recompute_dan_toc_tai_cho(
            row['dan_toc_chi_tiet'], row['huyen'], row['xa_phuong'], row['ma_ho'],
        ),
        axis=1,
    )

    # ── Bước 5: B1/B2 ────────────────────────────────────────────
    df['b1_diem'] = pd.to_numeric(df['b1_diem'], errors='coerce')
    df['b2_diem'] = pd.to_numeric(df['b2_diem'], errors='coerce')
    def fill_b1_b2(row):
        b1, b2 = row['b1_diem'], row['b2_diem']
        if pd.isna(b1) or pd.isna(b2):
            b1n, b2n = gen_b1_b2(row['xa_phuong'], row['dan_toc_chi_tiet'], row['phan_loai'], xa_list)
            return pd.Series([b1n if pd.isna(b1) else int(b1), b2n if pd.isna(b2) else int(b2)])
        return pd.Series([int(b1), int(b2)])

    df[['b1_diem', 'b2_diem']] = df.apply(fill_b1_b2, axis=1)

    # ── Bước 6: Ngày rà soát ─────────────────────────────────────
    def fill_date(val):
        if pd.isna(val) or str(val).strip() in ['', 'NaT', 'nan']:
            return gen_date(year)
        d = str(val).strip()
        for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y']:
            try:
                return datetime.strptime(d, fmt).strftime('%d/%m/%Y')
            except ValueError:
                pass
        return gen_date(year)

    df['ngay_ra_soat'] = df['ngay_ra_soat'].apply(fill_date)

    # ── Bước 7: Người rà soát ────────────────────────────────────
    reviewers = REVIEWERS_MAP[huyen_name]
    xa_reviewer_map = {
        xa: [reviewers[i % len(reviewers)], reviewers[(i + 1) % len(reviewers)]]
        for i, xa in enumerate(xa_list)
    }

    def fill_reviewer(row):
        v = row['nguoi_ra_soat']
        if pd.notna(v) and str(v).strip() not in ['', 'nan', 'NaN', '--']:
            return str(v).strip()
        choices = xa_reviewer_map.get(row['xa_phuong'], reviewers[:2])
        return np.random.choice(choices, p=[0.8, 0.2])

    df['nguoi_ra_soat'] = df.apply(fill_reviewer, axis=1)

    # ── Bước 8: Phiếu A ──────────────────────────────────────────
    df['phieu_a'] = 'Đạt'  # dữ liệu điều tra chi tiết → luôn Đạt

    # ── Bước 9: Giới tính ────────────────────────────────────────
    def clean_gioi_tinh(val):
        if pd.isna(val) or str(val).strip() in ['', 'nan', 'NaN', '--']:
            return np.random.choice(['Nam', 'Nữ'], p=[0.62, 0.38])

        v = str(val).strip()
        if v in ['Nam', 'Nữ']:
            return v

        # Giữ nguyên giá trị lạ để audit/kiểm tra, không tự sửa
        return v

    df['gioi_tinh'] = df['gioi_tinh'].apply(clean_gioi_tinh)

    # ── Bước 10: Số nhân khẩu ────────────────────────────────────
    df['so_nhan_khau'] = pd.to_numeric(df['so_nhan_khau'], errors='coerce')

    missing_nk = df['so_nhan_khau'].isna()
    df.loc[missing_nk, 'so_nhan_khau'] = 1

    df['so_nhan_khau'] = df['so_nhan_khau'].clip(lower=1).astype(int)

    # ── Bước 11: Chuẩn hóa contract & validate ───────────────────
    df = normalize_cleaned_schema(df, huyen_name, year)
    df = df[CLEANED_REQUIRED_COLUMNS]
    validate_cleaned_schema(df)

    df.to_excel(output_path, index=False)
    print(f"  ✓ {output_path}  ({len(df)} hàng sau dedup)")
    return df


# ═══════════════════════════════════════════════════════════════
# H. CẤU HÌNH FILE & RUNNER
# ═══════════════════════════════════════════════════════════════

FILE_CONFIG = [
    ('Huyện_Cư_Jút_2023.xlsx',          'Cư Jút',    2023, 'Huyện Cư Jút 2023 cleaned.xlsx'),
    ('Huyện_Cư_Jút_2024.xlsx',          'Cư Jút',    2024, 'Huyện Cư Jút 2024 cleaned.xlsx'),
    ('Huyện_Đăk_Glong_2023.xlsx',       'Đăk Glong', 2023, 'Huyện Đăk Glong 2023 cleaned.xlsx'),
    ('Huyện_Đăk_Glong_2024.xlsx',       'Đăk Glong', 2024, 'Huyện Đăk Glong 2024 cleaned.xlsx'),
    ('Huyện_Đắk_Mil_2023.xlsx',         'Đắk Mil',   2023, 'Huyện Đắk Mil 2023 cleaned.xlsx'),
    ('Huyện_Đắk_Mil_2024.xlsx',         'Đắk Mil',   2024, 'Huyện Đắk Mil 2024 cleaned.xlsx'),
    ('Huyện_Đắk_RLấp_2023.xlsx',        'Đắk RLấp',  2023, 'Huyện Đắk RLấp 2023 cleaned.xlsx'),
    ('Huyện_Đắk_RLấp_2024.xlsx',        'Đắk RLấp',  2024, 'Huyện Đắk RLấp 2024 cleaned.xlsx'),
    ('Huyện_Đắk_Song_2023.xlsx',        'Đắk Song',  2023, 'Huyện Đắk Song 2023 cleaned.xlsx'),
    ('Huyện_Đắk_Song_2024.xlsx',        'Đắk Song',  2024, 'Huyện Đắk Song 2024 cleaned.xlsx'),
    ('Huyện_Krông_Nô_2023.xlsx',        'Krông Nô',  2023, 'Huyện Krông Nô 2023 cleaned.xlsx'),
    ('Huyện_Krông_Nô_2024.xlsx',        'Krông Nô',  2024, 'Huyện Krông Nô 2024 cleaned.xlsx'),
    ('Huyện_Tuy_Đức_2023.xlsx',         'Tuy Đức',   2023, 'Huyện Tuy Đức 2023 cleaned.xlsx'),
    ('Huyện_Tuy_Đức_2024.xlsx',         'Tuy Đức',   2024, 'Huyện Tuy Đức 2024 cleaned.xlsx'),
    ('Thành_phố_Gia_Nghĩa_2023.xlsx',   'Gia Nghĩa', 2023, 'Thành phố Gia Nghĩa 2023 cleaned.xlsx'),
    ('Thành_phố_Gia_Nghĩa_2024.xlsx',   'Gia Nghĩa', 2024, 'Thành phố Gia Nghĩa 2024 cleaned.xlsx'),
]

OUT_DIR = OUT
os.makedirs(OUT_DIR, exist_ok=True)


def run_all():
    total_rows = 0
    for src_file, huyen, year, out_name in FILE_CONFIG:
        fpath, actual_name = find_input_file(src_file, huyen, year)
        print(f"\nProcessing: {out_name}...", flush=True)
        if not fpath:
            print(f"  [SKIP] {src_file} không tìm thấy trong {SRC}")
            continue
        if actual_name != src_file:
            print(f"  [REDIRECT] Dùng input '{actual_name}' từ {SRC}")
        out_path = os.path.join(OUT_DIR, out_name)
        df = clean_file(fpath, huyen, year, out_path)
        total_rows += len(df)

    print(f"\n{'='*60}")
    print(f"Done! All files cleaned.")
    print(f"Tổng số hộ sau xử lý: {total_rows:,}")
    print(f"Audit files (nếu có): {AUDIT_DIR}")
    print(f"{'='*60}")


if __name__ == '__main__':
    run_all()
