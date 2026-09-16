"""
feature_engineering.py
=======================
Chạy SAU processing_data.py. Đọc các file cleaned từ data/cleaned/, bổ sung ~50+ trường
đặc trưng phục vụ báo cáo thống kê, biểu đồ, chatbot truy vấn LLM.

Đầu vào : data/cleaned/* cleaned.xlsx  (output của processing_data.py)
Đầu ra  : data/enriched/  — mỗi huyện/năm 1 file enriched
           data/enriched/combined_all.xlsx — toàn tỉnh gộp lại

Usage:
    python feature_engineering.py
"""

import pandas as pd
import numpy as np
import os
import re
from datetime import datetime, date
import warnings
from processing_data import (
    DAN_TOC_MAP,
    REVIEWERS_MAP,
    XA_PHUONG_MAP,
    gen_b1_b2,
    gen_date,
    recompute_dan_toc_tai_cho,
    recompute_nhom_ngheo_tong_hop,
)
warnings.filterwarnings('ignore')

# ── Seed cố định để kết quả tái lập ──────────────────────────
random_seed = 42
np.random.seed(random_seed)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IN_DIR   = os.path.join(BASE_DIR, "data", "cleaned")
OUT_DIR  = os.path.join(BASE_DIR, "data", "enriched")
os.makedirs(OUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# A. BẢNG TRA CỨU (LOOKUP TABLES)
# ═══════════════════════════════════════════════════════════════

# ── A1. Danh mục xã/phường + metadata ────────────────────────
XA_META = {
    # huyen -> xa -> {loai, khu_vuc, dac_biet_kho_khan}
    'Cư Jút': {
        'Thị trấn Ea T\'ling': {'loai': 'thi_tran', 'khu_vuc': 'III', 'dkk': False},
        'Xã Ea Pô':            {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Nam Dong':         {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk DRông':        {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Tâm Thắng':        {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Cư Knia':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Trúc Sơn':         {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk Wil':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
    },
    'Đăk Glong': {
        'Xã Đắk Ha':           {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk Plao':         {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk R\'Măng':      {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk Som':          {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Hoà':        {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Khê':        {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Sơn':        {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
    },
    'Đắk Mil': {
        'Thị trấn Đắk Mil':    {'loai': 'thi_tran', 'khu_vuc': 'I',   'dkk': False},
        'Xã Đắk Lao':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk R\'La':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk Gằn':          {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk N\'Drót':      {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk Sắk':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đức Mạnh':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đức Minh':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Long Sơn':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Thuận An':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
    },
    'Đắk RLấp': {
        'Thị trấn Kiến Đức':   {'loai': 'thi_tran', 'khu_vuc': 'I',   'dkk': False},
        'Xã Nhân Cơ':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Kiến Thành':       {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nghĩa Thắng':      {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đạo Nghĩa':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk Ru':           {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Hưng Bình':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk Sin':          {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Tín':        {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk Wer':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nhân Đạo':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
    },
    'Đắk Song': {
        'Thị trấn Đức An':     {'loai': 'thi_tran', 'khu_vuc': 'I',   'dkk': False},
        'Xã Đắk Môl':          {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Đắk Hòa':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nam Bình':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Thuận Hà':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Thuận Hạnh':       {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk N\'Drung':     {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Nâm N\'Jang':      {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Trường Xuân':      {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
    },
    'Krông Nô': {
        'Thị trấn Đắk Mâm':   {'loai': 'thi_tran', 'khu_vuc': 'I',   'dkk': False},
        'Xã Đắk Sôr':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nam Xuân':         {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Buôn Choah':       {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
        'Xã Nam Đà':           {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Tân Thành':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk Drô':          {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nâm Nung':         {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Đức Xuyên':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Đắk Nang':         {'loai': 'xa',        'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Phú':        {'loai': 'xa',        'khu_vuc': 'II',  'dkk': False},
        'Xã Nâm N\'Đir':       {'loai': 'xa',        'khu_vuc': 'III', 'dkk': False},
    },
    'Tuy Đức': {
        'Xã Quảng Trực':       {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk Buk So':       {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Tâm':        {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk R\'Tíh':       {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Đắk Ngo':          {'loai': 'xa', 'khu_vuc': 'III', 'dkk': True},
        'Xã Quảng Tân':        {'loai': 'xa', 'khu_vuc': 'III', 'dkk': False},
    },
    'Gia Nghĩa': {
        'Phường Nghĩa Đức':    {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Phường Nghĩa Thành':  {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Phường Nghĩa Phú':    {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Phường Nghĩa Tân':    {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Phường Nghĩa Trung':  {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Xã Đắk R\'Moan':      {'loai': 'xa',     'khu_vuc': 'II','dkk': False},
        'Phường Quảng Thành':  {'loai': 'phuong', 'khu_vuc': 'I', 'dkk': False},
        'Xã Đắk Nia':          {'loai': 'xa',     'khu_vuc': 'II','dkk': False},
    },
}

# ── A2. Nguyên nhân nghèo — 8 cột flag 0/1 (theo file 10) ───
# Tên cột tương ứng với từng nguyên nhân
NGUYEN_NHAN_COLS = [
    'nn_khong_co_dat_sx',           # Không có đất sản xuất
    'nn_khong_co_von',              # Không có vốn sản xuất, kinh doanh
    'nn_khong_co_lao_dong',         # Không có lao động
    'nn_khong_co_cong_cu_pt_sx',    # Không có công cụ/phương tiện SX
    'nn_khong_co_kien_thuc_sx',     # Không có kiến thức về sản xuất
    'nn_khong_co_ky_nang_ld',       # Không có kỹ năng lao động SX
    'nn_om_dau_benh_tai_nan',       # Có người ốm đau, bệnh nặng, tai nạn
    'nn_nguyen_nhan_khac',          # Nguyên nhân khác
]

# Xác suất cơ sở theo phan_loai — mỗi cột độc lập (Bernoulli)
# Thứ tự: đất, vốn, lao_động, công_cụ, kiến_thức, kỹ_năng, ốm_đau, khác
_NN_BASE_PROBS = {
    'Hộ nghèo':     [0.38, 0.52, 0.32, 0.22, 0.24, 0.22, 0.32, 0.06],
    'Hộ cận nghèo': [0.28, 0.45, 0.20, 0.18, 0.16, 0.22, 0.28, 0.08],
}

# ── A3. Chỉ số thiếu hụt DVXHCB (12 chỉ số theo Nghị định 07/2021) ──
CHI_SO_DVXHCB = [
    # Chiều 1: Việc làm
    'thieu_hut_viec_lam',                    # 1
    'thieu_hut_bao_hiem_xa_hoi',             # 2
    # Chiều 2: Y tế
    'thieu_hut_bao_hiem_y_te',               # 3
    'thieu_hut_dinh_duong',                  # 4 (trẻ em <16t)
    # Chiều 3: Giáo dục
    'thieu_hut_trinh_do_giao_duc_nguoi_lon', # 5
    'thieu_hut_tinh_trang_di_hoc_tre_em',    # 6
    # Chiều 4: Nhà ở
    'thieu_hut_chat_luong_nha_o',            # 7
    'thieu_hut_dien_tich_nha_o',             # 8
    # Chiều 5: Nước sạch & vệ sinh
    'thieu_hut_nuoc_sach',                   # 9
    'thieu_hut_nha_tieu_hop_ve_sinh',        # 10
    # Chiều 6: Thông tin
    'thieu_hut_su_dung_dich_vu_vien_thong',  # 11
    'thieu_hut_tai_san_phuc_vu_tiep_can_tt', # 12
]

# Xác suất thiếu hụt từng chỉ số theo phan_loai x dan_toc_tai_cho
# (nghèo tại chỗ thiếu hụt nhiều hơn, đặc biệt nhà ở + nước)
THIEU_HUT_PROBS = {
    # (phan_loai, tai_cho) -> list 12 xác suất
    ('Hộ nghèo',     'Có'):  [0.55,0.82,0.40,0.30,0.60,0.45,0.70,0.65,0.75,0.80,0.70,0.60],
    ('Hộ nghèo',     'Không'):[0.50,0.75,0.35,0.22,0.50,0.38,0.55,0.50,0.55,0.60,0.55,0.45],
    ('Hộ cận nghèo', 'Có'):  [0.35,0.60,0.25,0.18,0.40,0.28,0.50,0.45,0.55,0.60,0.50,0.40],
    ('Hộ cận nghèo', 'Không'):[0.28,0.50,0.18,0.12,0.30,0.20,0.35,0.30,0.35,0.40,0.38,0.28],
    ('Hộ không nghèo','Có'): [0.10,0.20,0.08,0.05,0.12,0.08,0.15,0.12,0.18,0.20,0.15,0.10],
    ('Hộ không nghèo','Không'):[0.05,0.12,0.04,0.02,0.06,0.03,0.08,0.06,0.08,0.10,0.08,0.05],
}

# ── A4. Chỉ số thiếu hụt trẻ em (file 11) ────────────────────
CHI_SO_TRE_EM = [
    'tre_em_thieu_hut_bhyt',
    'tre_em_thieu_hut_dinh_duong',
    'tre_em_thieu_hut_di_hoc',
]

CHILD_DEPRIVATION_COUNT_COLS = {
    'tre_em_thieu_hut_bhyt': 'so_tre_thieu_bhyt',
    'tre_em_thieu_hut_dinh_duong': 'so_tre_thieu_dinh_duong',
    'tre_em_thieu_hut_di_hoc': 'so_tre_thieu_di_hoc',
}

# ── A5. Nhóm đối tượng chính sách ────────────────────────────
NHOM_DOI_TUONG = [
    'Ho_chinh_sach_co_cong',          # hộ người có công CM
    'Ho_khong_co_kha_nang_lao_dong',  # hộ KCKN lao động
    'Ho_dan_toc_thieu_so_tai_cho',    # DTTS tại chỗ
    'Ho_co_chu_ho_la_nu',             # chủ hộ là nữ
    'Ho_co_nguoi_khuyet_tat',         # có người khuyết tật
    'Ho_co_nguoi_cao_tuoi',           # có người >= 60t
    'Ho_co_tre_em_duoi_6_tuoi',       # có trẻ < 6t
    'Ho_co_tre_em_di_hoc',            # có trẻ đang đi học
    'Ho_don_than',                    # hộ đơn thân
    'Ho_thuong_binh_liet_si',         # TB-LS
]

# ── A6. Chính sách hỗ trợ ─────────────────────────────────────
CHINH_SACH_HO_TRO = [
    'ho_tro_y_te',                    # BHYT, khám chữa bệnh
    'ho_tro_giao_duc',                # miễn giảm học phí, sách vở
    'ho_tro_san_xuat',                # giống, phân, kỹ thuật
    'ho_tro_vay_von_tin_dung',        # vay NHCSXH
    'ho_tro_nha_o',                   # hỗ trợ xây/sửa nhà
    'ho_tro_nuoc_sach_ve_sinh',       # nước sạch
    'ho_tro_dien',                    # điện sinh hoạt
    'ho_tro_vien_thong',              # điện thoại/internet
    'ho_tro_dao_tao_nghe',            # đào tạo nghề
    'tro_cap_xa_hoi_thuong_xuyen',    # TCXH thường xuyên
    'tro_cap_dot_xuat',               # TCXH đột xuất
    'chinh_sach_khac',                # CS khác
]

# Xác suất nhận chính sách theo phan_loai
CHINH_SACH_PROBS = {
    'Hộ nghèo':      [0.98,0.85,0.70,0.75,0.45,0.55,0.60,0.30,0.50,0.40,0.15,0.10],
    'Hộ cận nghèo':  [0.92,0.70,0.50,0.65,0.25,0.35,0.45,0.20,0.35,0.15,0.08,0.06],
    'Hộ không nghèo':[0.60,0.20,0.10,0.20,0.05,0.10,0.20,0.05,0.10,0.02,0.03,0.02],
}

# ── A7. Sinh kế / nghề nghiệp ─────────────────────────────────
NGHE_NGHIEP_CHU_HO = [
    'Làm nông nghiệp',
    'Làm rẫy/nương',
    'Chăn nuôi',
    'Lao động tự do',
    'Làm thuê/công nhân',
    'Buôn bán nhỏ lẻ',
    'Nghề thủ công',
    'Không có việc làm',
    'Tàn tật/bệnh tật không lao động được',
    'Già yếu không lao động được',
    'Khác',
]

NGHE_NGHIEP_PROBS = {
    'Hộ nghèo':      [0.22,0.20,0.05,0.12,0.08,0.04,0.02,0.10,0.08,0.06,0.03],
    'Hộ cận nghèo':  [0.28,0.18,0.07,0.14,0.10,0.06,0.03,0.06,0.04,0.03,0.01],
    'Hộ không nghèo':[0.30,0.15,0.10,0.15,0.12,0.08,0.04,0.02,0.01,0.01,0.02],
}

# ── A8. Tình trạng nhà ở ──────────────────────────────────────
TINH_TRANG_NHA_O = ['Kiên cố', 'Bán kiên cố', 'Nhà đơn sơ', 'Nhà tạm', 'Không có nhà']
NHA_O_PROBS = {
    # (phan_loai, dkk) -> probs
    ('Hộ nghèo',      True):  [0.03,0.12,0.30,0.45,0.10],
    ('Hộ nghèo',      False): [0.05,0.20,0.38,0.32,0.05],
    ('Hộ cận nghèo',  True):  [0.05,0.22,0.40,0.28,0.05],
    ('Hộ cận nghèo',  False): [0.10,0.35,0.38,0.15,0.02],
    ('Hộ không nghèo',True):  [0.15,0.40,0.30,0.13,0.02],
    ('Hộ không nghèo',False): [0.30,0.45,0.18,0.06,0.01],
}

# ── A9. Nguồn nước sử dụng ────────────────────────────────────
NGUON_NUOC = [
    'Nước máy/nước sạch tập trung',
    'Giếng khoan hợp vệ sinh',
    'Giếng đào hợp vệ sinh',
    'Nước suối/khe chưa qua xử lý',
    'Nước mưa',
    'Nước mua bình/bể',
]
NGUON_NUOC_KHONG_SACH = {'Nước suối/khe chưa qua xử lý'}
NUOC_PROBS = {
    ('Hộ nghèo',      True):  [0.08,0.15,0.22,0.35,0.12,0.08],
    ('Hộ nghèo',      False): [0.18,0.25,0.28,0.15,0.08,0.06],
    ('Hộ cận nghèo',  True):  [0.12,0.22,0.28,0.22,0.10,0.06],
    ('Hộ cận nghèo',  False): [0.25,0.30,0.25,0.10,0.05,0.05],
    ('Hộ không nghèo',True):  [0.22,0.30,0.28,0.12,0.05,0.03],
    ('Hộ không nghèo',False): [0.42,0.30,0.18,0.05,0.02,0.03],
}

# ── A10. Diện tích đất canh tác ──────────────────────────────
# (m² - phân phối theo phan_loai và vùng)
DAT_CANH_TAC_PARAMS = {
    # (phan_loai, is_urban) -> (mean, std, min, max)
    ('Hộ nghèo',      False): (3200, 2500, 0, 15000),
    ('Hộ nghèo',      True):  (800,  900,  0, 5000),
    ('Hộ cận nghèo',  False): (5500, 3500, 0, 20000),
    ('Hộ cận nghèo',  True):  (1200, 1000, 0, 6000),
    ('Hộ không nghèo',False): (8000, 5000, 0, 30000),
    ('Hộ không nghèo',True):  (1500, 1500, 0, 8000),
}

# ── A11. Vật nuôi / gia súc ────────────────────────────────────
VAT_NUOI_PROBS = {
    # có trâu/bò
    'Hộ nghèo':      {'trau_bo': 0.25, 'lon': 0.35, 'ga_vit': 0.50},
    'Hộ cận nghèo':  {'trau_bo': 0.32, 'lon': 0.45, 'ga_vit': 0.60},
    'Hộ không nghèo':{'trau_bo': 0.40, 'lon': 0.55, 'ga_vit': 0.65},
}

# ── A12. Biến động nghèo (diễn biến) ─────────────────────────
CAN_NGHEO_THANH_NGHEO_LABEL = 'Cận nghèo trở thành hộ nghèo'
THOAT_NGHEO_THANH_CAN_NGHEO_LABEL = 'Thoát nghèo -> cận nghèo'
THOAT_NGHEO_VUOT_CHUAN_LABEL = 'Thoát nghèo -> vượt chuẩn'
THOAT_CAN_NGHEO_VUOT_CHUAN_LABEL = 'Thoát cận nghèo -> vượt chuẩn'
# Các nhãn biến động "khác" bị loại bỏ vì DB không có cột lý do chi tiết
# để giải thích chúng. Nếu dữ liệu enriched cũ còn các nhãn này, chuẩn hóa về
# nhãn giữ nguyên tương ứng thay vì tiếp tục đưa vào DB/báo cáo.
DEPRECATED_MOVEMENT_OTHER_REPLACEMENTS = {
    'Tăng nghèo khác': 'Nghèo cũ (giữ nguyên)',
    'Tăng cận nghèo khác': 'Cận nghèo cũ (giữ nguyên)',
    'Giảm nghèo khác': 'Không thay đổi (không nghèo)',
    'Giảm cận nghèo khác': 'Không thay đổi (không nghèo)',
}

BIEN_DONG_NGHEO = [
    'Nghèo cũ (giữ nguyên)',
    CAN_NGHEO_THANH_NGHEO_LABEL,
    'Tái nghèo',
    'Nghèo mới phát sinh',
]
BIEN_DONG_PROBS_NGHEO = {
    # Không sinh nhãn "Tăng nghèo khác" vì không có cột lý do chi tiết.
    # Phần xác suất cũ của nhãn này được đưa về "Nghèo cũ (giữ nguyên)".
    2023: [0.64, 0.10, 0.14, 0.12],
    2024: [0.78, 0.00, 0.12, 0.10],
}

# Tỷ lệ cận nghèo năm trước được giả lập chuyển thành nghèo ở năm báo cáo
# khi không có mã hộ ổn định thật. Count được giới hạn bởi số hộ cận nghèo
# năm trước và số hộ nghèo năm hiện tại trong cùng địa bàn.
CAN_NGHEO_THANH_NGHEO_RATE_BY_YEAR = {
    2024: 0.15,
}
DEFAULT_CAN_NGHEO_THANH_NGHEO_RATE = 0.12

BIEN_DONG_CAN_NGHEO = [
    'Cận nghèo cũ (giữ nguyên)',
    'Tái cận nghèo',
    'Cận nghèo mới phát sinh',
    THOAT_NGHEO_THANH_CAN_NGHEO_LABEL,
]
BIEN_DONG_PROBS_CAN_NGHEO = {
    # Không sinh nhãn "Tăng cận nghèo khác" vì không có cột lý do chi tiết.
    2023: [0.60, 0.14, 0.14, 0.12],
    2024: [0.58, 0.12, 0.12, 0.18],
}

BIEN_DONG_KHONG_NGHEO = [
    'Không thay đổi (không nghèo)',
    THOAT_NGHEO_VUOT_CHUAN_LABEL,
    THOAT_CAN_NGHEO_VUOT_CHUAN_LABEL,
]
BIEN_DONG_PROBS_KHONG_NGHEO = {
    # Không sinh nhãn "Giảm nghèo/cận nghèo khác" vì không có cột lý do chi tiết.
    2023: [0.86, 0.06, 0.08],
    2024: [0.82, 0.08, 0.10],
}

# ── A13. Trình độ học vấn chủ hộ ─────────────────────────────
TRINH_DO_HOC_VAN = [
    'Chưa biết đọc/viết',
    'Chưa tốt nghiệp tiểu học',
    'Tốt nghiệp tiểu học',
    'Tốt nghiệp THCS',
    'Tốt nghiệp THPT',
    'Trung cấp/CĐ',
    'Đại học trở lên',
]
HOCVAN_PROBS = {
    # (phan_loai, dan_toc_tai_cho)
    ('Hộ nghèo',     'Có'):  [0.25,0.28,0.22,0.15,0.07,0.02,0.01],
    ('Hộ nghèo',     'Không'):[0.08,0.18,0.28,0.25,0.14,0.05,0.02],
    ('Hộ cận nghèo', 'Có'):  [0.12,0.22,0.28,0.22,0.12,0.03,0.01],
    ('Hộ cận nghèo', 'Không'):[0.04,0.10,0.25,0.30,0.20,0.07,0.04],
    ('Hộ không nghèo','Có'): [0.05,0.12,0.25,0.28,0.20,0.06,0.04],
    ('Hộ không nghèo','Không'):[0.01,0.04,0.15,0.30,0.28,0.12,0.10],
}

# ── A14. Tình trạng sức khỏe chủ hộ ─────────────────────────
SUC_KHOE = ['Bình thường', 'Ốm đau mãn tính', 'Khuyết tật', 'Tàn tật nặng']
SUC_KHOE_PROBS = {
    'Hộ nghèo':      [0.45, 0.30, 0.15, 0.10],
    'Hộ cận nghèo':  [0.58, 0.25, 0.12, 0.05],
    'Hộ không nghèo':[0.75, 0.17, 0.06, 0.02],
}

# ── A15. Mức thu nhập BQ/tháng/người (VNĐ) ───────────────────
THU_NHAP_PARAMS = {
    # (phan_loai, nam) -> (mean, std) — đơn vị: nghìn đồng/người/tháng
    # Chuẩn nghèo 2022-2025: nông thôn 1.500k, thành thị 2.000k
    ('Hộ nghèo',      2023): (900,  280),
    ('Hộ nghèo',      2024): (950,  300),
    ('Hộ cận nghèo',  2023): (1650, 350),
    ('Hộ cận nghèo',  2024): (1700, 380),
    ('Hộ không nghèo',2023): (3200, 1200),
    ('Hộ không nghèo',2024): (3500, 1300),
}

# ── A16. Cây trồng chính ──────────────────────────────────────
CAY_TRONG_CHINH = {
    'Cư Jút':    ['Lúa', 'Ngô', 'Cà phê', 'Điều', 'Hồ tiêu', 'Sắn'],
    'Đăk Glong': ['Lúa nương', 'Ngô', 'Cà phê', 'Sắn', 'Bơ', 'Mắc ca'],
    'Đắk Mil':   ['Cà phê', 'Hồ tiêu', 'Ngô', 'Lúa', 'Sầu riêng', 'Điều'],
    'Đắk RLấp':  ['Điều', 'Cà phê', 'Cao su', 'Ngô', 'Lúa', 'Hồ tiêu'],
    'Đắk Song':  ['Hồ tiêu', 'Cà phê', 'Sầu riêng', 'Ngô', 'Điều', 'Sắn'],
    'Krông Nô':  ['Ngô', 'Lúa', 'Cà phê', 'Điều', 'Mía', 'Sắn'],
    'Tuy Đức':   ['Điều', 'Sắn', 'Ngô', 'Cà phê', 'Đậu', 'Lúa nương'],
    'Gia Nghĩa': ['Cà phê', 'Rau màu', 'Cây ăn quả', 'Ngô', 'Lúa', 'Hoa'],
}


# ═══════════════════════════════════════════════════════════════
# B. HÀM SINH ĐẶC TRƯNG
# ═══════════════════════════════════════════════════════════════

def safe_choice(options, probs, size=1):
    """
    np.random.choice an toàn với string tiếng Việt.
    np.random.choice(list_of_unicode_str) trả về numpy str_ → khi join
    bị tách ký tự. Fix: dùng index rồi map lại list Python thuần.
    """
    options = list(options)           # đảm bảo là list Python
    probs   = np.array(probs, dtype=float)
    probs   = probs / probs.sum()
    indices = np.random.choice(len(options), size=size, p=probs, replace=False if size > 1 and size <= len(options) else True)
    if size == 1:
        return options[int(indices[0])]
    return [options[int(i)] for i in indices]


def gen_xa_meta(row):
    """Trả về metadata của xã/phường."""
    huyen = row.get('huyen', '')
    xa    = row.get('xa_phuong', '')
    huyen_map = XA_META.get(huyen, {})
    meta = huyen_map.get(xa, {'loai': 'xa', 'khu_vuc': 'II', 'dkk': False})
    return meta


def gen_nguyen_nhan(row, kinh_te_ctx=None):
    """
    Sinh 8 cột flag nguyên nhân nghèo (0/1) có ràng buộc nhất quán
    với nghề nghiệp, đất, sức khỏe, thu nhập.

    kinh_te_ctx: dict chứa các trường đã sinh (nghe_nghiep, dat, suc_khoe, thu_nhap)
    Trả về: dict {col: 0/1}
    """
    pl = row['phan_loai']

    # Hộ không nghèo: tất cả = 0
    if pl == 'Hộ không nghèo':
        return {col: 0 for col in NGUYEN_NHAN_COLS}

    base_probs = list(_NN_BASE_PROBS.get(pl, _NN_BASE_PROBS['Hộ nghèo']))
    # base_probs index: [đất(0), vốn(1), lao_động(2), công_cụ(3),
    #                    kiến_thức(4), kỹ_năng(5), ốm_đau(6), khác(7)]

    # ── Ràng buộc theo context kinh tế ──────────────────────────
    if kinh_te_ctx:
        nghe  = kinh_te_ctx.get('nghe_nghiep_chu_ho', '')
        dat   = kinh_te_ctx.get('dien_tich_dat_canh_tac_m2', 5000)
        sk    = kinh_te_ctx.get('suc_khoe_chu_ho', 'Bình thường')
        tn    = kinh_te_ctx.get('thu_nhap_bq_thang_nguoi_nghin_dong', 1500)

        # Đất ít (<1000m²) → tăng xác suất "không có đất"
        if dat < 500:
            base_probs[0] = min(0.95, base_probs[0] + 0.45)
        elif dat < 1500:
            base_probs[0] = min(0.80, base_probs[0] + 0.25)
        elif dat >= 5000:
            base_probs[0] = max(0.02, base_probs[0] - 0.25)  # có đất → ít khả năng thiếu đất

        # Thu nhập rất thấp → tăng xác suất "không có vốn"
        if tn < 600:
            base_probs[1] = min(0.92, base_probs[1] + 0.30)
        elif tn > 1400:
            base_probs[1] = max(0.05, base_probs[1] - 0.20)

        # Nghề không cần đất/vốn → giảm các nguyên nhân nông nghiệp
        if nghe in ('Lao động tự do', 'Làm thuê/công nhân', 'Buôn bán nhỏ lẻ'):
            base_probs[0] = max(0.03, base_probs[0] - 0.20)  # đất ít liên quan
            base_probs[3] = max(0.03, base_probs[3] - 0.10)  # công cụ nông nghiệp ít liên quan
            base_probs[4] = max(0.03, base_probs[4] - 0.08)  # kiến thức SX ít liên quan

        # Sức khỏe kém → tăng ốm đau + không có lao động
        if sk in ('Khuyết tật', 'Tàn tật nặng'):
            base_probs[6] = min(0.95, base_probs[6] + 0.50)  # ốm đau/tai nạn
            base_probs[2] = min(0.90, base_probs[2] + 0.40)  # không có lao động
        elif sk == 'Ốm đau mãn tính':
            base_probs[6] = min(0.85, base_probs[6] + 0.30)
            base_probs[2] = min(0.70, base_probs[2] + 0.20)
        elif sk == 'Bình thường':
            base_probs[6] = max(0.05, base_probs[6] - 0.15)  # khỏe → ít khả năng ốm đau

        # Hộ đơn thân (nk=1) → tăng không có lao động
        nk = int(row.get('so_nhan_khau', 3))
        if nk == 1:
            base_probs[2] = min(0.80, base_probs[2] + 0.20)

    # ── Đảm bảo ít nhất 1 nguyên nhân với hộ nghèo/cận nghèo ───
    result = {col: int(np.random.random() < p)
              for col, p in zip(NGUYEN_NHAN_COLS, base_probs)}

    if sum(result.values()) == 0:
        # Chọn nguyên nhân có xác suất cao nhất làm fallback
        top_col = NGUYEN_NHAN_COLS[int(np.argmax(base_probs))]
        result[top_col] = 1

    return result


def gen_thieu_hut_dvxhcb(row):
    """Sinh 12 cột thiếu hụt DVXHCB (0/1)."""
    pl  = row['phan_loai']
    tc  = str(row.get('dan_toc_tai_cho', 'Không')).strip()
    key = (pl, tc) if (pl, tc) in THIEU_HUT_PROBS else (pl, 'Không')
    probs = THIEU_HUT_PROBS[key]
    return {cs: int(np.random.random() < p) for cs, p in zip(CHI_SO_DVXHCB, probs)}


def gen_tong_chieu_thieu_hut(row_dict):
    """Đếm số chiều thiếu hụt (nhóm 2 chỉ số/chiều)."""
    chieu = [
        ('thieu_hut_viec_lam',                    'thieu_hut_bao_hiem_xa_hoi'),
        ('thieu_hut_bao_hiem_y_te',               'thieu_hut_dinh_duong'),
        ('thieu_hut_trinh_do_giao_duc_nguoi_lon', 'thieu_hut_tinh_trang_di_hoc_tre_em'),
        ('thieu_hut_chat_luong_nha_o',            'thieu_hut_dien_tich_nha_o'),
        ('thieu_hut_nuoc_sach',                   'thieu_hut_nha_tieu_hop_ve_sinh'),
        ('thieu_hut_su_dung_dich_vu_vien_thong',  'thieu_hut_tai_san_phuc_vu_tiep_can_tt'),
    ]
    count = sum(1 for c1, c2 in chieu if row_dict.get(c1, 0) or row_dict.get(c2, 0))
    return count


def gen_thieu_hut_tre_em(row, so_tre_em):
    """Sinh chỉ số thiếu hụt trẻ em."""
    pl  = row['phan_loai']
    so_tre_em = max(0, int(so_tre_em or 0))
    result = {}
    if so_tre_em == 0:
        result['co_tre_em_trong_ho'] = 0
        result['so_tre_em'] = 0
        for cs in CHI_SO_TRE_EM:
            result[cs] = 0
            result[CHILD_DEPRIVATION_COUNT_COLS[cs]] = 0
    else:
        result['co_tre_em_trong_ho'] = 1
        result['so_tre_em'] = so_tre_em
        if pl == 'Hộ nghèo':
            p_bhyt, p_dd, p_hoc = 0.28, 0.25, 0.30
        elif pl == 'Hộ cận nghèo':
            p_bhyt, p_dd, p_hoc = 0.15, 0.14, 0.18
        else:
            p_bhyt, p_dd, p_hoc = 0.04, 0.04, 0.05
        result['tre_em_thieu_hut_bhyt']      = int(np.random.random() < p_bhyt)
        result['tre_em_thieu_hut_dinh_duong']= int(np.random.random() < p_dd)
        result['tre_em_thieu_hut_di_hoc']    = int(np.random.random() < p_hoc)
        for flag_col, count_col in CHILD_DEPRIVATION_COUNT_COLS.items():
            result[count_col] = int(np.random.randint(1, so_tre_em + 1)) if result[flag_col] else 0
    return result


def gen_nhom_doi_tuong(row, demographics, generated_features=None):
    """Sinh các flag nhóm đối tượng chính sách."""
    pl  = row['phan_loai']
    gt  = str(row.get('gioi_tinh', 'Nam')).strip()
    tc  = str(row.get('dan_toc_tai_cho', 'Không')).strip()
    nk  = int(row.get('so_nhan_khau', 3))
    so_tre_em = max(0, int(demographics.get('so_tre_em', 0) or 0))
    so_cao_tuoi = max(0, int(demographics.get('so_nguoi_cao_tuoi', 0) or 0))
    so_lao_dong = max(0, int(demographics.get('so_nguoi_lao_dong', 0) or 0))
    co_vo_chong = int(demographics.get('co_vo_chong_chu_ho', 0) or 0)
    generated_features = generated_features or {}
    suc_khoe = str(generated_features.get('suc_khoe_chu_ho', 'Bình thường'))

    # Xác suất phụ thuộc vào phan_loai
    base = 1.0 if pl == 'Hộ nghèo' else (0.7 if pl == 'Hộ cận nghèo' else 0.3)

    result = {}
    result['nhom_ho_chinh_sach_co_cong']         = int(np.random.random() < 0.04 * base)
    result['nhom_ho_dtts_tai_cho']               = 1 if tc == 'Có' else 0
    result['nhom_chu_ho_la_nu']                  = 1 if gt == 'Nữ' else 0
    result['nhom_co_nguoi_khuyet_tat']           = int(
        suc_khoe in ('Khuyết tật', 'Tàn tật nặng')
        or np.random.random() < 0.08 * base
    )
    result['nhom_co_nguoi_cao_tuoi']             = int(so_cao_tuoi > 0)
    result['nhom_co_tre_em_duoi_6_tuoi']         = int(
        so_tre_em > 0 and np.random.random() < min(0.85, 0.35 * so_tre_em)
    )
    result['nhom_co_tre_em_di_hoc']              = int(
        so_tre_em > 0 and np.random.random() < min(0.95, 0.55 * so_tre_em)
    )
    # Chủ hộ không có vợ/chồng vẫn có thể sống cùng con hoặc cha mẹ.
    result['nhom_ho_don_than']                   = int(co_vo_chong == 0)

    # Không có KNLĐ là nhãn chính sách có điều kiện, không phải random độc lập.
    if so_lao_dong == 0:
        khong_knld_probability = 0.55
        if so_cao_tuoi == nk:
            khong_knld_probability = 0.85
        if suc_khoe == 'Ốm đau mãn tính':
            khong_knld_probability = max(khong_knld_probability, 0.70)
        elif suc_khoe in ('Khuyết tật', 'Tàn tật nặng'):
            khong_knld_probability = max(khong_knld_probability, 0.90)
    elif so_lao_dong == 1 and suc_khoe in ('Khuyết tật', 'Tàn tật nặng'):
        khong_knld_probability = 0.35
    else:
        khong_knld_probability = 0.01 * base
    result['nhom_ho_khong_co_kha_nang_lao_dong'] = int(
        np.random.random() < khong_knld_probability
    )
    result['nhom_thuong_binh_liet_si']           = int(np.random.random() < 0.02)
    return result


def gen_chinh_sach_ho_tro(row):
    """Sinh các flag chính sách hỗ trợ đang thụ hưởng."""
    pl    = row['phan_loai']
    probs = CHINH_SACH_PROBS.get(pl, CHINH_SACH_PROBS['Hộ không nghèo'])
    return {cs: int(np.random.random() < p) for cs, p in zip(CHINH_SACH_HO_TRO, probs)}


def gen_kinh_te_ho(row, huyen, xa_meta):
    """Sinh các đặc trưng kinh tế hộ. Trả về dict kết quả."""
    pl     = row['phan_loai']
    nam    = int(row.get('nam', 2023))
    is_urb = xa_meta['loai'] in ('thi_tran', 'phuong')
    dkk    = xa_meta['dkk']

    result = {}

    # Nghề nghiệp — điều chỉnh theo vùng đô thị/nông thôn
    probs_nn = list(NGHE_NGHIEP_PROBS.get(pl, NGHE_NGHIEP_PROBS['Hộ không nghèo']))
    if is_urb:
        # Đô thị: ít làm nông/rẫy, nhiều lao động tự do/buôn bán
        probs_nn[0] *= 0.4   # Làm nông nghiệp
        probs_nn[1] *= 0.2   # Làm rẫy/nương
        probs_nn[3] *= 1.8   # Lao động tự do
        probs_nn[4] *= 1.6   # Làm thuê/công nhân
        probs_nn[5] *= 1.5   # Buôn bán nhỏ lẻ
    result['nghe_nghiep_chu_ho'] = safe_choice(NGHE_NGHIEP_CHU_HO, probs_nn)

    # Thu nhập BQ/tháng/người (nghìn đồng)
    mean_tn, std_tn = THU_NHAP_PARAMS.get((pl, nam), (2000, 800))
    # Đô thị thu nhập cao hơn ~20%
    if is_urb:
        mean_tn = int(mean_tn * 1.2)
    tn = int(np.clip(np.random.normal(mean_tn, std_tn), 200, 12000))
    result['thu_nhap_bq_thang_nguoi_nghin_dong'] = tn

    # Diện tích đất canh tác (m²)
    key_dat = (pl, is_urb)
    dt_mean, dt_std, dt_min, dt_max = DAT_CANH_TAC_PARAMS.get(key_dat, (3000, 2000, 0, 12000))
    result['dien_tich_dat_canh_tac_m2'] = int(np.clip(np.random.normal(dt_mean, dt_std), dt_min, dt_max))

    # Cây trồng chính (chỉ hộ nông nghiệp)
    nghe = result['nghe_nghiep_chu_ho']
    if 'nông' in nghe.lower() or 'rẫy' in nghe.lower() or 'chăn nuôi' in nghe.lower():
        cay_list = CAY_TRONG_CHINH.get(huyen, ['Ngô', 'Lúa', 'Cà phê'])
        n_cay = np.random.choice([1, 2], p=[0.55, 0.45])
        chosen_cay = safe_choice(cay_list, [1/len(cay_list)]*len(cay_list), size=int(n_cay))
        result['cay_trong_chinh'] = '; '.join(chosen_cay) if isinstance(chosen_cay, list) else chosen_cay
    else:
        result['cay_trong_chinh'] = ''

    # Vật nuôi
    vp = VAT_NUOI_PROBS.get(pl, VAT_NUOI_PROBS['Hộ không nghèo'])
    result['co_trau_bo'] = int(np.random.random() < vp['trau_bo'])
    result['co_lon']     = int(np.random.random() < vp['lon'])
    result['co_ga_vit']  = int(np.random.random() < vp['ga_vit'])

    return result


def gen_cuoc_song(row, xa_meta):
    """Sinh điều kiện sống: nhà ở, nước, điện, vệ sinh."""
    pl  = row['phan_loai']
    dkk = xa_meta['dkk']
    tc  = str(row.get('dan_toc_tai_cho', 'Không')).strip()

    result = {}

    # Nhà ở
    key_nha = (pl, dkk)
    if key_nha not in NHA_O_PROBS:
        key_nha = (pl, False)
    result['tinh_trang_nha_o'] = safe_choice(TINH_TRANG_NHA_O, NHA_O_PROBS[key_nha])

    # Nguồn nước
    key_nuoc = (pl, dkk)
    if key_nuoc not in NUOC_PROBS:
        key_nuoc = (pl, False)
    result['nguon_nuoc_su_dung'] = safe_choice(NGUON_NUOC, NUOC_PROBS[key_nuoc])

    # Điện
    if pl == 'Hộ không nghèo':
        p_dien = 0.97
    elif dkk:
        p_dien = 0.72 if pl == 'Hộ nghèo' else 0.82
    else:
        p_dien = 0.88 if pl == 'Hộ nghèo' else 0.93
    result['co_dien_sinh_hoat'] = int(np.random.random() < p_dien)

    # Nhà tiêu hợp vệ sinh
    p_nt = 0.30 if pl == 'Hộ nghèo' else (0.50 if pl == 'Hộ cận nghèo' else 0.75)
    if dkk:
        p_nt *= 0.7
    result['co_nha_tieu_hop_ve_sinh'] = int(np.random.random() < p_nt)

    # Internet
    p_net = 0.20 if pl == 'Hộ nghèo' else (0.40 if pl == 'Hộ cận nghèo' else 0.70)
    result['co_internet'] = int(np.random.random() < p_net)

    return result


def normalize_semantic_features(features):
    """Canonicalize overlapping features after all generators have run."""
    so_tre_em = max(0, int(features.get('so_tre_em', 0) or 0))
    features['so_tre_em'] = so_tre_em
    features['co_tre_em_trong_ho'] = int(so_tre_em > 0)
    for count_col in CHILD_DEPRIVATION_COUNT_COLS.values():
        features[count_col] = min(
            max(0, int(features.get(count_col, 0) or 0)),
            so_tre_em,
        )
    if so_tre_em == 0:
        for col in (
            'nhom_co_tre_em_duoi_6_tuoi', 'nhom_co_tre_em_di_hoc',
            'tre_em_thieu_hut_bhyt', 'tre_em_thieu_hut_dinh_duong',
            'tre_em_thieu_hut_di_hoc', 'thieu_hut_dinh_duong',
            'thieu_hut_tinh_trang_di_hoc_tre_em',
            'so_tre_thieu_bhyt', 'so_tre_thieu_dinh_duong',
            'so_tre_thieu_di_hoc',
        ):
            features[col] = 0

    so_cao_tuoi = max(0, int(features.get('so_nguoi_cao_tuoi', 0) or 0))
    features['nhom_co_nguoi_cao_tuoi'] = int(so_cao_tuoi > 0)

    co_nha_tieu = int(features.get('co_nha_tieu_hop_ve_sinh', 0) or 0)
    features['thieu_hut_nha_tieu_hop_ve_sinh'] = int(co_nha_tieu == 0)

    features['thieu_hut_chat_luong_nha_o'] = int(
        features.get('tinh_trang_nha_o') in {'Nhà tạm', 'Nhà đơn sơ', 'Không có nhà'}
    )
    features['thieu_hut_nuoc_sach'] = int(
        features.get('nguon_nuoc_su_dung') in NGUON_NUOC_KHONG_SACH
    )
    return features


def gen_hoc_van_suc_khoe(row):
    """Sinh trình độ học vấn và sức khỏe chủ hộ."""
    pl = row['phan_loai']
    tc = str(row.get('dan_toc_tai_cho', 'Không')).strip()

    result = {}
    key_hv = (pl, tc) if (pl, tc) in HOCVAN_PROBS else (pl, 'Không')
    result['trinh_do_hoc_van_chu_ho'] = safe_choice(TRINH_DO_HOC_VAN, HOCVAN_PROBS[key_hv])

    probs_sk = SUC_KHOE_PROBS.get(pl, SUC_KHOE_PROBS['Hộ không nghèo'])
    result['suc_khoe_chu_ho'] = safe_choice(SUC_KHOE, probs_sk)

    return result


def gen_bien_dong(row):
    """Sinh diễn biến nghèo so với đầu kỳ."""
    pl  = row['phan_loai']
    nam = int(row.get('nam', 2023))

    if pl == 'Hộ nghèo':
        opts  = BIEN_DONG_NGHEO
        probs = BIEN_DONG_PROBS_NGHEO.get(nam, BIEN_DONG_PROBS_NGHEO[2023])
    elif pl == 'Hộ cận nghèo':
        opts  = BIEN_DONG_CAN_NGHEO
        probs = BIEN_DONG_PROBS_CAN_NGHEO.get(nam, BIEN_DONG_PROBS_CAN_NGHEO[2023])
    else:
        opts  = BIEN_DONG_KHONG_NGHEO
        probs = BIEN_DONG_PROBS_KHONG_NGHEO.get(nam, BIEN_DONG_PROBS_KHONG_NGHEO[2023])
    return {'bien_dong_so_dau_ky': safe_choice(opts, probs)}


def _drop_deprecated_movement_other_labels(df):
    """Chuẩn hóa các nhãn biến động 'khác' cũ ra khỏi dữ liệu đầu ra."""
    col = 'bien_dong_so_dau_ky' if 'bien_dong_so_dau_ky' in df.columns else 'bien_dong_dau_ky'
    if col not in df.columns:
        return df
    df = df.copy()
    df[col] = df[col].replace(DEPRECATED_MOVEMENT_OTHER_REPLACEMENTS)
    return df



def _movement_match_key(row, columns):
    """Tạo khóa so sánh hộ giữa 2 năm từ các cột đang có.

    Khóa này chỉ dùng để ưu tiên các case match chắc. Nếu dữ liệu không giữ
    được mã hộ ổn định qua năm, bước hậu xử lý sẽ fallback bằng phân bổ theo
    địa bàn, có giới hạn bởi số hộ cận nghèo năm trước.
    """
    parts = []
    for col in columns:
        value = row.get(col, '')
        if pd.isna(value):
            value = ''
        value = str(value).strip().lower()
        value = re.sub(r"\s+", " ", value)
        parts.append(value)
    return '|'.join(parts)


def _apply_can_ngheo_thanh_ngheo_from_previous_year(df_all):
    """Gán nhãn 'Cận nghèo trở thành hộ nghèo' cho dữ liệu diễn biến.

    Quy tắc:
    - Năm đầu tiên trong DB: giữ nhãn đã sinh ngẫu nhiên trong gen_bien_dong.
    - Các năm có năm trước: chọn trong nhóm Hộ nghèo của năm hiện tại.
      Ưu tiên hộ match được với Hộ cận nghèo năm trước bằng khóa chặt
      huyen + xa_phuong + ma_ho + chu_ho.
    - Nếu khóa chặt không đủ vì dữ liệu không có mã hộ ổn định thật, bổ sung
      bằng phân bổ theo huyen + xa_phuong. Số lượng không vượt số Hộ cận nghèo
      năm trước và không vượt số Hộ nghèo hiện tại trong cùng địa bàn.

    Đây là dữ liệu mô phỏng để phục vụ biểu mẫu diễn biến 2/3; không dùng
    id_ho bỏ năm để tránh match nhầm hộ khác xã/khác chủ hộ.
    """
    required = {'nam', 'phan_loai', 'huyen', 'xa_phuong', 'ma_ho', 'chu_ho', 'bien_dong_so_dau_ky'}
    if not required.issubset(df_all.columns):
        missing = sorted(required - set(df_all.columns))
        print(f"[WARN] Bỏ qua hậu xử lý '{CAN_NGHEO_THANH_NGHEO_LABEL}' vì thiếu cột: {missing}")
        return df_all

    df_all = df_all.copy()
    years = sorted(pd.to_numeric(df_all['nam'], errors='coerce').dropna().astype(int).unique().tolist())
    if not years:
        return df_all

    summaries = []
    key_cols = ['huyen', 'xa_phuong', 'ma_ho', 'chu_ho']

    for year in years:
        prev_candidates = [y for y in years if y < year]
        if not prev_candidates:
            # Không có năm trước: giữ random đã sinh cho năm đầu kỳ.
            continue

        prev_year = max(prev_candidates)
        prev_mask = (df_all['nam'].astype(int) == prev_year) & (df_all['phan_loai'] == 'Hộ cận nghèo')
        curr_mask = (df_all['nam'].astype(int) == year) & (df_all['phan_loai'] == 'Hộ nghèo')
        if not prev_mask.any() or not curr_mask.any():
            continue

        # Với năm có dữ liệu năm trước, nhãn này phải đến từ logic 2 năm,
        # nên xóa nhãn ngẫu nhiên cũ nếu có.
        reset_mask = curr_mask & (df_all['bien_dong_so_dau_ky'] == CAN_NGHEO_THANH_NGHEO_LABEL)
        df_all.loc[reset_mask, 'bien_dong_so_dau_ky'] = 'Nghèo cũ (giữ nguyên)'

        prev = df_all.loc[prev_mask].copy()
        curr = df_all.loc[curr_mask].copy()
        prev_keys = set(prev.apply(lambda row: _movement_match_key(row, key_cols), axis=1))
        curr_keys = curr.apply(lambda row: _movement_match_key(row, key_cols), axis=1)
        selected_idx = set(curr.index[curr_keys.isin(prev_keys)].tolist())

        rng = np.random.default_rng(random_seed + int(year) * 1009)
        rate = CAN_NGHEO_THANH_NGHEO_RATE_BY_YEAR.get(int(year), DEFAULT_CAN_NGHEO_THANH_NGHEO_RATE)

        area_cols = ['huyen', 'xa_phuong']
        prev_counts = prev.groupby(area_cols).size().to_dict()
        curr_groups = curr.groupby(area_cols).groups

        for area, curr_indices in curr_groups.items():
            prev_count = int(prev_counts.get(area, 0))
            if prev_count <= 0:
                continue
            curr_indices = list(curr_indices)
            existing_in_area = [idx for idx in curr_indices if idx in selected_idx]
            desired = int(round(prev_count * rate))
            desired = max(desired, len(existing_in_area))
            desired = min(desired, prev_count, len(curr_indices))
            need = desired - len(existing_in_area)
            if need <= 0:
                continue
            candidates = [idx for idx in curr_indices if idx not in selected_idx]
            if not candidates:
                continue
            chosen = rng.choice(candidates, size=min(need, len(candidates)), replace=False).tolist()
            selected_idx.update(int(idx) for idx in chosen)

        if selected_idx:
            df_all.loc[list(selected_idx), 'bien_dong_so_dau_ky'] = CAN_NGHEO_THANH_NGHEO_LABEL

        summaries.append((prev_year, year, int(len(selected_idx))))

    for prev_year, year, count in summaries:
        print(
            f"[INFO] {year}: gán {count:,} hộ '{CAN_NGHEO_THANH_NGHEO_LABEL}' "
            f"dựa trên Hộ cận nghèo năm {prev_year}."
        )

    return df_all


def gen_thanh_vien_ho(row):
    """
    Sinh danh sách thành viên hộ (dạng JSON string) dựa trên so_nhan_khau.
    Trả về: số trẻ em, số lao động, số người cao tuổi.
    """
    nk     = int(row.get('so_nhan_khau', 3))
    dt     = str(row.get('dan_toc_chi_tiet', 'Kinh'))
    gt_chu = str(row.get('gioi_tinh', 'Nam'))
    pl     = str(row.get('phan_loai', 'Hộ không nghèo'))

    # Hộ nhiều người không mặc nhiên có vợ/chồng chủ hộ. Xác suất thấp hơn
    # ở nhóm nghèo và chủ hộ nữ để có cả hộ góa, ly thân, cha/mẹ đơn thân.
    spouse_probability = 0.86
    if pl == 'Hộ nghèo':
        spouse_probability -= 0.04
    elif pl == 'Hộ cận nghèo':
        spouse_probability -= 0.02
    if gt_chu == 'Nữ':
        spouse_probability -= 0.05
    co_vo_chong = nk >= 2 and np.random.random() < spouse_probability

    # Phân bổ tuổi thành viên
    so_tre_em    = 0
    so_lao_dong  = 0
    so_cao_tuoi  = 0

    thanh_vien = []
    for i in range(nk):
        if i == 0:
            # Chủ hộ: tuổi 25-70
            tuoi = int(np.clip(np.random.normal(45, 12), 25, 75))
            gt   = gt_chu
            qhe  = 'Chủ hộ'
        elif i == 1 and co_vo_chong:
            tuoi = int(np.clip(np.random.normal(42, 12), 20, 72))
            gt   = 'Nữ' if gt_chu == 'Nam' else 'Nam'
            qhe  = 'Vợ/chồng chủ hộ'
        else:
            r = np.random.random()
            if r < 0.45:  # con
                tuoi = int(np.clip(np.random.normal(12, 8), 0, 28))
                gt   = np.random.choice(['Nam', 'Nữ'])
                qhe  = 'Con'
            elif r < 0.60:  # bố/mẹ
                tuoi = int(np.clip(np.random.normal(68, 8), 55, 90))
                gt   = np.random.choice(['Nam', 'Nữ'])
                qhe  = 'Bố/mẹ'
            else:  # thành viên khác
                tuoi = int(np.clip(np.random.normal(30, 15), 1, 80))
                gt   = np.random.choice(['Nam', 'Nữ'])
                qhe  = 'Khác'

        nam_sinh = 2023 - tuoi
        thanh_vien.append({
            'stt': i + 1,
            'quan_he': qhe,
            'gioi_tinh': gt,
            'nam_sinh': nam_sinh,
            'tuoi': tuoi,
            'dan_toc': dt,
        })

        if tuoi < 16:
            so_tre_em += 1
        elif tuoi <= 59:
            so_lao_dong += 1
        else:
            so_cao_tuoi += 1

    import json
    return {
        'so_tre_em':              so_tre_em,
        'so_nguoi_lao_dong':      so_lao_dong,
        'so_nguoi_cao_tuoi':      so_cao_tuoi,
        'ty_le_phu_thuoc':        round((so_tre_em + so_cao_tuoi) / max(1, so_lao_dong), 2),
        'co_vo_chong_chu_ho':      int(co_vo_chong),
    }


def gen_dinh_danh_dia_ly(row, huyen):
    """Thêm các trường định danh địa lý đầy đủ."""
    xa  = str(row.get('xa_phuong', ''))
    meta = XA_META.get(huyen, {}).get(xa, {'loai': 'xa', 'khu_vuc': 'II', 'dkk': False})
    return {
        'tinh':             'Đắk Nông',
        'ma_tinh':          'DNO',
        'ten_huyen_day_du': ('Thành phố ' if huyen == 'Gia Nghĩa' else 'Huyện ') + huyen,
        'loai_xa_phuong':   meta['loai'],
        'khu_vuc_xa':       meta['khu_vuc'],
        'xa_dac_biet_kho_khan': int(meta['dkk']),
        'vung_dia_ly':      'Tây Nguyên',
        'tinh_bien_gioi':   int(huyen in ['Tuy Đức', 'Đắk RLấp']),  # giáp Campuchia/Bình Phước
    }


def gen_ma_dinh_danh(row, huyen):
    """Sinh mã định danh duy nhất cho hộ."""
    ma_huyen_map = {
        'Cư Jút': 'CJ', 'Đăk Glong': 'GL', 'Đắk Mil': 'DM',
        'Đắk RLấp': 'RL', 'Đắk Song': 'DS', 'Krông Nô': 'KN',
        'Tuy Đức': 'TD', 'Gia Nghĩa': 'GN',
    }
    prefix = ma_huyen_map.get(huyen, 'XX')
    nam    = int(row.get('nam', 2023))
    ma_ho  = str(row.get('ma_ho', '0')).strip()
    return {'id_ho': f"DNO-{prefix}-{nam}-{ma_ho}"}


# ═══════════════════════════════════════════════════════════════
# C. HÀM CHÍNH: XỬ LÝ MỘT FILE
# ═══════════════════════════════════════════════════════════════

def enrich_file(filepath, huyen_name, year, out_path):
    print(f"  → Enriching: {os.path.basename(filepath)} ...")
    df = pd.read_excel(filepath)

    if df.empty:
        print(f"    [SKIP] File rỗng.")
        return None

    # Chuẩn hoá tên cột
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

    # Đảm bảo có cột huyen, nam
    if 'huyen' not in df.columns:
        df['huyen'] = huyen_name
    if 'nam' not in df.columns:
        df['nam'] = year
    df['huyen'] = df['huyen'].fillna(huyen_name)
    df['nam']   = df['nam'].fillna(year).astype(int)

    # Chuẩn hoá phan_loai
    if 'phan_loai' not in df.columns:
        df['phan_loai'] = 'Hộ không nghèo'
    df['phan_loai'] = df['phan_loai'].fillna('Hộ không nghèo')

    # Chuẩn hoá so_nhan_khau
    if 'so_nhan_khau' not in df.columns:
        df['so_nhan_khau'] = 3
    df['so_nhan_khau'] = pd.to_numeric(df['so_nhan_khau'], errors='coerce').fillna(3).astype(int)

    # Sinh các trường còn thiếu ở bước feature engineering, không ghi ngược vào cleaned.
    xa_cfg = XA_PHUONG_MAP[huyen_name]
    xa_list = xa_cfg['xa_list']
    xa_weights = xa_cfg['weights']
    if 'xa_phuong' not in df.columns:
        df['xa_phuong'] = pd.NA
    missing_xa = df['xa_phuong'].isna() | df['xa_phuong'].astype(str).str.strip().isin(['', 'nan'])
    df.loc[missing_xa, 'xa_phuong'] = np.random.choice(
        xa_list, size=int(missing_xa.sum()), p=xa_weights
    )

    dan_toc_cfg = DAN_TOC_MAP[huyen_name]
    if 'dan_toc_chi_tiet' not in df.columns:
        df['dan_toc_chi_tiet'] = pd.NA
    missing_dan_toc = (
        df['dan_toc_chi_tiet'].isna()
        | df['dan_toc_chi_tiet'].astype(str).str.strip().isin(['', 'nan'])
    )
    df.loc[missing_dan_toc, 'dan_toc_chi_tiet'] = np.random.choice(
        dan_toc_cfg['dan_toc'], size=int(missing_dan_toc.sum()), p=dan_toc_cfg['weights']
    )

    if 'b1_diem' not in df.columns:
        df['b1_diem'] = np.nan
    if 'b2_diem' not in df.columns:
        df['b2_diem'] = np.nan
    df['b1_diem'] = pd.to_numeric(df['b1_diem'], errors='coerce')
    df['b2_diem'] = pd.to_numeric(df['b2_diem'], errors='coerce')

    def fill_b1_b2(row):
        b1, b2 = row['b1_diem'], row['b2_diem']
        if pd.isna(b1) or pd.isna(b2):
            generated_b1, generated_b2 = gen_b1_b2(
                row['xa_phuong'], row['dan_toc_chi_tiet'], row['phan_loai'], xa_list
            )
            b1 = generated_b1 if pd.isna(b1) else b1
            b2 = generated_b2 if pd.isna(b2) else b2
        return pd.Series([int(b1), int(b2)])

    df[['b1_diem', 'b2_diem']] = df.apply(fill_b1_b2, axis=1)

    if 'ngay_ra_soat' not in df.columns:
        df['ngay_ra_soat'] = pd.NA

    def fill_date(value):
        if pd.isna(value) or str(value).strip() in ['', 'NaT', 'nan']:
            return gen_date(year)
        parsed = pd.to_datetime(value, errors='coerce', dayfirst=True)
        return parsed.strftime('%d/%m/%Y') if pd.notna(parsed) else gen_date(year)

    df['ngay_ra_soat'] = df['ngay_ra_soat'].apply(fill_date)

    reviewers = REVIEWERS_MAP[huyen_name]
    xa_reviewer_map = {
        xa: [reviewers[i % len(reviewers)], reviewers[(i + 1) % len(reviewers)]]
        for i, xa in enumerate(xa_list)
    }
    if 'nguoi_ra_soat' not in df.columns:
        df['nguoi_ra_soat'] = pd.NA

    def fill_reviewer(row):
        value = row['nguoi_ra_soat']
        if pd.notna(value) and str(value).strip() not in ['', 'nan']:
            return str(value).strip().title()
        choices = xa_reviewer_map.get(row['xa_phuong'], reviewers[:2])
        return np.random.choice(choices, p=[0.8, 0.2])

    df['nguoi_ra_soat'] = df.apply(fill_reviewer, axis=1)
    if 'phieu_a' not in df.columns:
        df['phieu_a'] = pd.NA
    df['phieu_a'] = df['phieu_a'].fillna('Đạt').replace('', 'Đạt')

    if 'gioi_tinh' not in df.columns:
        df['gioi_tinh'] = pd.NA
    invalid_gender = ~df['gioi_tinh'].isin(['Nam', 'Nữ'])
    df.loc[invalid_gender, 'gioi_tinh'] = np.random.choice(
        ['Nam', 'Nữ'], size=int(invalid_gender.sum()), p=[0.62, 0.38]
    )

    # Tính lại từ dân tộc chi tiết; tuyệt đối không giữ nhãn cũ mâu thuẫn.
    df['dan_toc_tai_cho'] = df.apply(
        lambda row: recompute_dan_toc_tai_cho(
            row.get('dan_toc_chi_tiet'), row.get('huyen', huyen_name),
            row.get('xa_phuong'), row.get('ma_ho'),
        ),
        axis=1,
    )

    # ── Sinh đặc trưng từng dòng ──
    new_cols = []
    for _, row in df.iterrows():
        r = {}

        # 1. Mã định danh
        r.update(gen_ma_dinh_danh(row, huyen_name))

        # 2. Địa lý
        r.update(gen_dinh_danh_dia_ly(row, huyen_name))
        xa_meta = gen_xa_meta(row)

        # 3. Thành viên hộ
        demographics = gen_thanh_vien_ho(row)
        r.update(demographics)

        # 4. Học vấn + sức khỏe (sinh trước để dùng trong nguyên nhân)
        r.update(gen_hoc_van_suc_khoe(row))

        # 5. Kinh tế hộ (sinh trước để dùng context cho nguyên nhân)
        kt = gen_kinh_te_ho(row, huyen_name, xa_meta)
        r.update(kt)

        # 6. Nguyên nhân nghèo — 8 cột flag 0/1, ràng buộc context
        kinh_te_ctx = {
            'nghe_nghiep_chu_ho':                  r.get('nghe_nghiep_chu_ho', ''),
            'dien_tich_dat_canh_tac_m2':           r.get('dien_tich_dat_canh_tac_m2', 5000),
            'suc_khoe_chu_ho':                     r.get('suc_khoe_chu_ho', 'Bình thường'),
            'thu_nhap_bq_thang_nguoi_nghin_dong':  r.get('thu_nhap_bq_thang_nguoi_nghin_dong', 1500),
        }
        r.update(gen_nguyen_nhan(row, kinh_te_ctx))

        # 7. Thiếu hụt DVXHCB (12 chỉ số)
        th = gen_thieu_hut_dvxhcb(row)
        r.update(th)
        r['tong_so_chieu_thieu_hut'] = gen_tong_chieu_thieu_hut(th)

        # 7. Thiếu hụt trẻ em
        r.update(gen_thieu_hut_tre_em(row, demographics['so_tre_em']))

        # 8. Nhóm đối tượng
        r.update(gen_nhom_doi_tuong(row, demographics, r))

        # 9. Chính sách hỗ trợ
        r.update(gen_chinh_sach_ho_tro(row))

        # 10. Điều kiện sống
        r.update(gen_cuoc_song(row, xa_meta))

        # 11. Diễn biến nghèo
        r.update(gen_bien_dong(row))

        # Chuẩn hóa các feature trùng nghĩa sau khi mọi nguồn đã được sinh.
        normalize_semantic_features(r)
        r['tong_so_chieu_thieu_hut'] = gen_tong_chieu_thieu_hut(r)

        # 12. Phân loại tổng hợp nhanh (cho chatbot)
        r['nhom_ho_dtts_tai_cho'] = int(str(row['dan_toc_tai_cho']).strip() == 'Có')
        r['nhom_ngheo_tong_hop'] = recompute_nhom_ngheo_tong_hop(
            row['phan_loai'], row['dan_toc_tai_cho']
        )

        # 14. Mức độ thiếu hụt tổng hợp (label)
        tc_thieu_hut = r['tong_so_chieu_thieu_hut']
        if row['phan_loai'] == 'Hộ không nghèo':
            r['muc_do_thieu_hut_label'] = 'Không thiếu hụt' if tc_thieu_hut == 0 else 'Thiếu hụt nhẹ'
        elif tc_thieu_hut <= 2:
            r['muc_do_thieu_hut_label'] = 'Thiếu hụt ít (1-2 chiều)'
        elif tc_thieu_hut <= 4:
            r['muc_do_thieu_hut_label'] = 'Thiếu hụt trung bình (3-4 chiều)'
        else:
            r['muc_do_thieu_hut_label'] = 'Thiếu hụt nhiều (5-6 chiều)'

        # 15. Kỳ rà soát
        r['ky_ra_soat'] = f"Rà soát cuối năm {int(row.get('nam', year))}"

        new_cols.append(r)

    df_new = pd.DataFrame(new_cols)
    df_out = pd.concat([df.reset_index(drop=True), df_new.reset_index(drop=True)], axis=1)

    # Loại bỏ cột trùng nếu có
    df_out = df_out.loc[:, ~df_out.columns.duplicated()]

    # Không để các nhãn biến động "khác" đi vào enriched output.
    df_out = _drop_deprecated_movement_other_labels(df_out)

    # Bảo vệ cuối: đảm bảo id_ho unique trong từng file enriched
    if 'id_ho' in df_out.columns:
        dup_rank = df_out.groupby('id_ho').cumcount()

        def suffix_alpha(rank: int) -> str:
            letters = "abcdefghijklmnopqrstuvwxyz"
            if rank < len(letters):
                return letters[rank]

            n = rank
            out = ""
            while True:
                out = letters[n % 26] + out
                n = n // 26 - 1
                if n < 0:
                    break
            return out

        df_out['id_ho'] = [
            value if rank == 0 else f"{value}{suffix_alpha(rank - 1)}"
            for value, rank in zip(df_out['id_ho'].astype(str), dup_rank)
        ]
    df_out.to_excel(out_path, index=False)
    print(f"    ✓ {len(df_out)} rows × {len(df_out.columns)} cols → {out_path}")
    return df_out


# ═══════════════════════════════════════════════════════════════
# D. FILE CONFIG & RUNNER
# ═══════════════════════════════════════════════════════════════

FILE_CONFIG = [
    ('Huyện Cư Jút 2023 cleaned.xlsx',          'Cư Jút',    2023),
    ('Huyện Cư Jút 2024 cleaned.xlsx',          'Cư Jút',    2024),
    ('Huyện Đăk Glong 2023 cleaned.xlsx',       'Đăk Glong', 2023),
    ('Huyện Đăk Glong 2024 cleaned.xlsx',       'Đăk Glong', 2024),
    ('Huyện Đắk Mil 2023 cleaned.xlsx',         'Đắk Mil',   2023),
    ('Huyện Đắk Mil 2024 cleaned.xlsx',         'Đắk Mil',   2024),
    ('Huyện Đắk RLấp 2023 cleaned.xlsx',        'Đắk RLấp',  2023),
    ('Huyện Đắk RLấp 2024 cleaned.xlsx',        'Đắk RLấp',  2024),
    ('Huyện Đắk Song 2023 cleaned.xlsx',        'Đắk Song',  2023),
    ('Huyện Đắk Song 2024 cleaned.xlsx',        'Đắk Song',  2024),
    ('Huyện Krông Nô 2023 cleaned.xlsx',        'Krông Nô',  2023),
    ('Huyện Krông Nô 2024 cleaned.xlsx',        'Krông Nô',  2024),
    ('Huyện Tuy Đức 2023 cleaned.xlsx',         'Tuy Đức',   2023),
    ('Huyện Tuy Đức 2024 cleaned.xlsx',         'Tuy Đức',   2024),
    ('Thành phố Gia Nghĩa 2023 cleaned.xlsx',   'Gia Nghĩa', 2023),
    ('Thành phố Gia Nghĩa 2024 cleaned.xlsx',   'Gia Nghĩa', 2024),
]


def run_all():
    print("=" * 60)
    print("FEATURE ENGINEERING — Tỉnh Đắk Nông")
    print("=" * 60)

    all_dfs = []

    for fname, huyen, year in FILE_CONFIG:
        fpath = os.path.join(IN_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  [SKIP] Không tìm thấy: {fpath}")
            continue

        out_name = fname.replace(' cleaned.xlsx', ' enriched.xlsx')
        out_path = os.path.join(OUT_DIR, out_name)
        df = enrich_file(fpath, huyen, year, out_path)
        if df is not None:
            all_dfs.append(df)

    # ── Gộp toàn tỉnh ──
    if all_dfs:
        print("\nGộp toàn tỉnh...")
        df_all = pd.concat(all_dfs, ignore_index=True)
        df_all = _drop_deprecated_movement_other_labels(df_all)

        # Hậu xử lý diễn biến phụ thuộc 2 năm. Bước này phải chạy sau khi đã có
        # cả năm trước và năm báo cáo trong cùng dataframe. Sau đó ghi lại cả
        # combined_all.xlsx lẫn từng file enriched, vì build_db.py đọc các file
        # huyện/năm trong data/enriched/.
        df_all = _apply_can_ngheo_thanh_ngheo_from_previous_year(df_all)

        for fname, huyen, year in FILE_CONFIG:
            part = df_all[(df_all['huyen'] == huyen) & (df_all['nam'].astype(int) == int(year))]
            if part.empty:
                continue
            out_name = fname.replace(' cleaned.xlsx', ' enriched.xlsx')
            out_path = os.path.join(OUT_DIR, out_name)
            part.to_excel(out_path, index=False)

        combined_path = os.path.join(OUT_DIR, 'combined_all.xlsx')
        df_all.to_excel(combined_path, index=False)
        print(f"✓ combined_all.xlsx: {len(df_all)} rows × {len(df_all.columns)} cols")

        # ── In thống kê tóm tắt ──
        print("\n── Thống kê nhanh ──")
        if 'phan_loai' in df_all.columns:
            print(df_all.groupby(['huyen', 'nam', 'phan_loai']).size().to_string())
        if 'bien_dong_so_dau_ky' in df_all.columns:
            print("\n── Diễn biến cận nghèo trở thành hộ nghèo ──")
            print(
                df_all[df_all['bien_dong_so_dau_ky'] == CAN_NGHEO_THANH_NGHEO_LABEL]
                .groupby(['nam', 'huyen']).size().to_string()
            )

    print("\nDone! Kết quả tại:", OUT_DIR)


if __name__ == '__main__':
    run_all()
