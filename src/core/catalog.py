from __future__ import annotations

FLAG_GROUPS = {'nguyen_nhan': {'label_col': 'nguyen_nhan', 'columns': {'Thiếu đất sản xuất': 'nn_thieu_dat', 'Thiếu vốn': 'nn_thieu_von', 'Thiếu lao động': 'nn_thieu_lao_dong', 'Thiếu công cụ/PTSX': 'nn_thieu_cong_cu', 'Thiếu kiến thức SX': 'nn_thieu_kien_thuc', 'Thiếu kỹ năng LĐ': 'nn_thieu_ky_nang', 'Ốm đau/bệnh/tai nạn': 'nn_om_dau', 'Nguyên nhân khác': 'nn_khac'}}, 'chi_so': {'label_col': 'chi_so', 'columns': {'Việc làm': 'th_viec_lam', 'BHXH': 'th_bhxh', 'BHYT': 'th_bhyt', 'Dinh dưỡng': 'th_dinh_duong', 'GD người lớn': 'th_giao_duc_nguoi_lon', 'Đi học trẻ em': 'th_di_hoc_tre_em', 'Chất lượng nhà ở': 'th_chat_luong_nha', 'Diện tích nhà ở': 'th_dien_tich_nha', 'Nước sạch': 'th_nuoc_sach', 'Nhà tiêu HVS': 'th_nha_tieu', 'Viễn thông': 'th_vien_thong', 'Tài sản thông tin': 'th_tai_san_tt'}}, 'tre_em': {'label_col': 'chi_tieu', 'columns': {'Đi học trẻ em': 'te_th_di_hoc', 'Dinh dưỡng trẻ em': 'te_th_dinh_duong', 'BHYT trẻ em': 'te_th_bhyt'}}, 'ho_tro': {'label_col': 'loai_ho_tro', 'columns': {'Hỗ trợ y tế': 'htro_y_te', 'Hỗ trợ giáo dục': 'htro_giao_duc', 'Hỗ trợ sản xuất': 'htro_san_xuat', 'Hỗ trợ vay vốn': 'htro_vay_von', 'Hỗ trợ nhà ở': 'htro_nha_o', 'Hỗ trợ nước sạch': 'htro_nuoc_sach', 'Hỗ trợ điện': 'htro_dien', 'Hỗ trợ viễn thông': 'htro_vien_thong', 'Hỗ trợ đào tạo nghề': 'htro_dao_tao_nghe'}}}
FLAG_GROUP_COLUMNS = set(FLAG_GROUPS)
GROUP_COLUMNS = {'huyen', 'xa_phuong', 'dan_toc_chi_tiet', 'gioi_tinh', 'phan_loai', 'nam', 'trinh_do_hoc_van_chu_ho', 'suc_khoe_chu_ho', 'nghe_nghiep_chu_ho', 'tinh_trang_nha', 'muc_do_thieu_hut', 'nguon_nuoc', *FLAG_GROUP_COLUMNS}
NUMERIC_COLUMNS = {'nam', 'so_nhan_khau', 'thu_nhap_bq', 'dien_tich_dat', 'tong_chieu_thieu_hut', 'so_tre_em', 'so_nguoi_lao_dong', 'so_nguoi_cao_tuoi', 'ty_le_phu_thuoc'}
OUTPUT_COLUMNS = {'id_ho', 'ma_ho', 'chu_ho', 'nam', 'huyen', 'xa_phuong', 'phan_loai', 'gioi_tinh', 'dan_toc_chi_tiet', 'trinh_do_hoc_van_chu_ho', 'suc_khoe_chu_ho', 'nghe_nghiep_chu_ho', 'so_nhan_khau', 'so_tre_em', 'so_tre_em_trong_ho', 'co_tre_em', 'so_nguoi_lao_dong', 'so_nguoi_cao_tuoi', 'ty_le_phu_thuoc', 'nhom_cao_tuoi', 'nhom_tre_em_duoi6', 'nhom_tre_em_di_hoc', 'nhom_khong_knld', 'thu_nhap_bq', 'dien_tich_dat', 'tong_chieu_thieu_hut', 'muc_do_thieu_hut', 'tinh_trang_nha', 'nguon_nuoc', 'co_nha_tieu_hvs', 'co_dien', 'co_internet', 'th_viec_lam', 'th_bhxh', 'th_bhyt', 'th_dinh_duong', 'th_giao_duc_nguoi_lon', 'th_di_hoc_tre_em', 'th_chat_luong_nha', 'th_dien_tich_nha', 'th_nuoc_sach', 'th_nha_tieu', 'th_vien_thong', 'th_tai_san_tt', 'te_th_bhyt', 'te_th_dinh_duong', 'te_th_di_hoc', 'nn_thieu_dat', 'nn_thieu_von', 'nn_thieu_lao_dong', 'nn_thieu_cong_cu', 'nn_thieu_kien_thuc', 'nn_thieu_ky_nang', 'nn_om_dau', 'nn_khac', 'nhom_khuyet_tat', 'nhom_don_than', 'nhom_dtts', 'nhom_chu_ho_nu', 'nhom_co_cong', 'nhom_thuong_binh', 'co_trau_bo', 'co_lon', 'co_ga_vit', 'htro_y_te', 'htro_giao_duc', 'htro_san_xuat', 'htro_vay_von', 'htro_nha_o', 'htro_nuoc_sach', 'htro_dien', 'htro_vien_thong', 'htro_dao_tao_nghe', 'tro_cap_thuong_xuyen', 'tro_cap_dot_xuat', 'xa_dac_biet_kho_khan', 'dan_toc_tai_cho'}
FLAG_COLUMNS = {'co_trau_bo', 'co_lon', 'co_ga_vit', 'nn_thieu_dat', 'nn_thieu_von', 'nn_thieu_lao_dong', 'nn_thieu_cong_cu', 'nn_thieu_kien_thuc', 'nn_thieu_ky_nang', 'nn_om_dau', 'nn_khac', 'th_viec_lam', 'th_bhxh', 'th_bhyt', 'th_dinh_duong', 'th_giao_duc_nguoi_lon', 'th_di_hoc_tre_em', 'th_chat_luong_nha', 'th_dien_tich_nha', 'th_nuoc_sach', 'th_nha_tieu', 'th_vien_thong', 'th_tai_san_tt', 'nhom_tre_em_duoi6', 'co_tre_em', 'nhom_khuyet_tat', 'nhom_cao_tuoi', 'nhom_don_than', 'nhom_dtts', 'nhom_chu_ho_nu', 'nhom_co_cong', 'nhom_khong_knld', 'nhom_thuong_binh', 'htro_y_te', 'htro_giao_duc', 'htro_san_xuat', 'htro_vay_von', 'htro_nha_o', 'htro_nuoc_sach', 'htro_dien', 'htro_vien_thong', 'htro_dao_tao_nghe', 'tro_cap_thuong_xuyen', 'tro_cap_dot_xuat', 'co_dien', 'co_internet'}
FILTER_COLUMNS = OUTPUT_COLUMNS | FLAG_COLUMNS | {'xa_dac_biet_kho_khan', 'dan_toc_tai_cho', 'muc_do_thieu_hut', 'nguon_nuoc'}
ALL_COLUMNS = FILTER_COLUMNS | GROUP_COLUMNS
ORDER_COLUMNS = ALL_COLUMNS
TASK_ALIASES = {'list': 'list_records', 'lookup': 'lookup_person', 'ranking': 'group_aggregate'}
METRIC_ALIASES = {'count': 'count_households'}
COLUMN_ALIASES = {'person_name': 'chu_ho', 'head_name': 'chu_ho', 'household_head': 'chu_ho', 'village_name': 'xa_phuong', 'district_name': 'huyen', 'house_type': 'tinh_trang_nha', 'house_status': 'tinh_trang_nha', 'year': 'nam', 'year': 'nam', 'years': 'nam', 'district': 'huyen', 'district_name': 'huyen', 'commune': 'xa_phuong', 'commune_name': 'xa_phuong', 'village': 'xa_phuong', 'village_name': 'xa_phuong', 'ethnicity': 'dan_toc_chi_tiet', 'dan_toc': 'dan_toc_chi_tiet', 'household_ethnicity': 'dan_toc_chi_tiet', 'classification': 'phan_loai', 'household_classification': 'phan_loai', 'household_type': 'phan_loai', 'is_poor': 'phan_loai', 'person_name': 'chu_ho', 'householder_name': 'chu_ho', 'household_head': 'chu_ho', 'house_type': 'tinh_trang_nha', 'housing_type': 'tinh_trang_nha', 'home_type': 'tinh_trang_nha', 'num_households': 'so_ho'}
CATALOG_VALUE_ALIASES = {'nghe_nghiep_chu_ho': {'Làm nông nghiệp': ('lam nong nghiep', 'lam nong'), 'Làm thuê/công nhân': ('lam thue', 'cong nhan', 'lam thue cong nhan'), 'Làm rẫy/nương': ('lam ray', 'lam nuong', 'ray nuong'), 'Lao động tự do': ('lao dong tu do',), 'Chăn nuôi': ('chan nuoi',), 'Buôn bán nhỏ lẻ': ('buon ban', 'buon ban nho le'), 'Không có việc làm': ('khong co viec lam', 'that nghiep')}}
SAME_COLUMN_CATALOG_CONTEXTS = {'trinh_do_hoc_van_chu_ho': ('hoc van', 'trinh do', 'tot nghiep', 'dai hoc', 'thpt', 'thcs', 'tieu hoc', 'doc viet'), 'suc_khoe_chu_ho': ('suc khoe', 'khuyet tat', 'tan tat', 'om dau', 'man tinh'), 'nghe_nghiep_chu_ho': ('nghe nghiep', 'viec lam', 'lam nong', 'lam thue', 'chan nuoi', 'buon ban'), 'muc_do_thieu_hut': ('muc do thieu hut', 'thieu hut nhieu', 'thieu hut nhe', 'thieu hut trung binh'), 'nguon_nuoc': ('nguon nuoc', 'nuoc may', 'nuoc mua', 'gieng', 'nuoc suoi')}
FILTER_ANSWER_LABELS = {'nhom_khuyet_tat': ('có người khuyết tật', 'không có người khuyết tật'), 'nhom_cao_tuoi': ('có người cao tuổi', 'không có người cao tuổi'), 'nhom_tre_em_duoi6': ('có trẻ em dưới 6 tuổi', 'không có trẻ em dưới 6 tuổi'), 'co_tre_em': ('có trẻ em', 'không có trẻ em'), 'nhom_chu_ho_nu': ('có chủ hộ là nữ', 'không có chủ hộ là nữ'), 'nhom_dtts': ('thuộc dân tộc thiểu số', 'không thuộc dân tộc thiểu số'), 'nhom_khong_knld': ('thuộc nhóm không có khả năng lao động', 'không thuộc nhóm không có khả năng lao động'), 'nn_thieu_dat': ('thiếu đất sản xuất', 'không thiếu đất sản xuất'), 'nn_thieu_von': ('thiếu vốn', 'không thiếu vốn'), 'nn_thieu_lao_dong': ('thiếu lao động', 'không thiếu lao động'), 'th_bhyt': ('thiếu BHYT', 'không thiếu BHYT'), 'th_bhxh': ('thiếu BHXH', 'không thiếu BHXH'), 'th_nuoc_sach': ('thiếu nước sạch', 'có nước sạch'), 'th_nha_tieu': ('thiếu nhà tiêu hợp vệ sinh', 'có nhà tiêu hợp vệ sinh'), 'co_nha_tieu_hvs': ('có nhà tiêu hợp vệ sinh', 'không có nhà tiêu hợp vệ sinh'), 'th_viec_lam': ('thiếu việc làm', 'không thiếu việc làm'), 'th_chat_luong_nha': ('thiếu chất lượng nhà ở', 'không thiếu chất lượng nhà ở'), 'co_trau_bo': ('nuôi trâu/bò', 'không nuôi trâu/bò'), 'co_lon': ('nuôi lợn/heo', 'không nuôi lợn/heo'), 'co_ga_vit': ('nuôi gà/vịt', 'không nuôi gà/vịt'), 'htro_nha_o': ('được hỗ trợ về nhà ở', 'không được hỗ trợ về nhà ở'), 'htro_vay_von': ('được hỗ trợ vay vốn', 'không được hỗ trợ vay vốn'), 'htro_y_te': ('được hỗ trợ y tế', 'không được hỗ trợ y tế'), 'co_dien': ('có điện sinh hoạt', 'chưa có điện sinh hoạt'), 'co_internet': ('có internet', 'chưa có internet'), 'htro_giao_duc': ('được hỗ trợ giáo dục', 'không được hỗ trợ giáo dục'), 'th_dinh_duong': ('thiếu hụt dinh dưỡng', 'không thiếu hụt dinh dưỡng'), 'th_giao_duc_nguoi_lon': ('thiếu hụt giáo dục người lớn', 'không thiếu hụt giáo dục người lớn'), 'th_di_hoc_tre_em': ('thiếu hụt đi học trẻ em', 'không thiếu hụt đi học trẻ em'), 'th_dien_tich_nha': ('thiếu diện tích nhà ở', 'không thiếu diện tích nhà ở'), 'th_vien_thong': ('thiếu dịch vụ viễn thông', 'không thiếu dịch vụ viễn thông'), 'th_tai_san_tt': ('thiếu tài sản thông tin', 'không thiếu tài sản thông tin'), 'te_th_bhyt': ('trẻ em thiếu BHYT', 'trẻ em không thiếu BHYT'), 'te_th_dinh_duong': ('trẻ em thiếu dinh dưỡng', 'trẻ em không thiếu dinh dưỡng'), 'te_th_di_hoc': ('trẻ em thiếu đi học', 'trẻ em không thiếu đi học'), 'htro_san_xuat': ('được hỗ trợ sản xuất', 'không được hỗ trợ sản xuất'), 'htro_nuoc_sach': ('được hỗ trợ nước sạch', 'không được hỗ trợ nước sạch'), 'htro_dien': ('được hỗ trợ điện', 'không được hỗ trợ điện'), 'htro_vien_thong': ('được hỗ trợ viễn thông', 'không được hỗ trợ viễn thông'), 'htro_dao_tao_nghe': ('được hỗ trợ đào tạo nghề', 'không được hỗ trợ đào tạo nghề'), 'nn_thieu_cong_cu': ('thiếu công cụ/phương tiện sản xuất', 'không thiếu công cụ/phương tiện sản xuất'), 'nn_thieu_kien_thuc': ('thiếu kiến thức sản xuất', 'không thiếu kiến thức sản xuất'), 'nn_thieu_ky_nang': ('thiếu kỹ năng lao động', 'không thiếu kỹ năng lao động'), 'nn_om_dau': ('có nguyên nhân ốm đau/bệnh/tai nạn', 'không do ốm đau/bệnh/tai nạn'), 'nn_khac': ('có nguyên nhân khác', 'không do nguyên nhân khác'), 'nhom_co_cong': ('thuộc nhóm người có công', 'không thuộc nhóm người có công'), 'nhom_thuong_binh': ('thuộc nhóm thương binh', 'không thuộc nhóm thương binh'), 'tro_cap_thuong_xuyen': ('có trợ cấp thường xuyên', 'không có trợ cấp thường xuyên'), 'tro_cap_dot_xuat': ('có trợ cấp đột xuất', 'không có trợ cấp đột xuất'), 'nhom_don_than': ('thuộc hộ đơn thân/độc thân', 'không thuộc hộ đơn thân/độc thân')}
TEXT_FILTER_LABELS = {'tinh_trang_nha': 'tình trạng nhà', 'nghe_nghiep_chu_ho': 'nghề nghiệp chủ hộ', 'trinh_do_hoc_van_chu_ho': 'trình độ học vấn chủ hộ', 'suc_khoe_chu_ho': 'sức khỏe chủ hộ', 'muc_do_thieu_hut': 'mức độ thiếu hụt', 'nguon_nuoc': 'nguồn nước', 'dan_toc_chi_tiet': 'dân tộc', 'phan_loai': 'phân loại hộ', 'gioi_tinh': 'giới tính chủ hộ'}
ANSWER_REQUIRED_COLUMN_RULES = [{'keywords': ('thu nhập', 'thu nhập bình quân', 'thu nhập trung bình'), 'columns': ['thu_nhap_bq']}, {'keywords': ('dân tộc', 'tộc người'), 'columns': ['dan_toc_chi_tiet']}, {'keywords': ('nhân khẩu', 'số người'), 'columns': ['so_nhan_khau']}, {'keywords': ('tình trạng nhà', 'nhà ở', 'loại nhà', 'nhà loại nào'), 'columns': ['tinh_trang_nha']}, {'keywords': ('bhyt', 'bảo hiểm y tế'), 'columns': ['th_bhyt']}, {'keywords': ('trẻ dưới 6', 'trẻ em dưới 6'), 'columns': ['so_tre_em', 'nhom_tre_em_duoi6']}]
SUPPORT_TERM_ALIASES = {'htro_y_te': ('y tế', 'y te'), 'htro_giao_duc': ('giáo dục', 'giao duc'), 'htro_nha_o': ('nhà ở', 'nha o'), 'htro_vay_von': ('vay vốn', 'vay von'), 'htro_san_xuat': ('sản xuất', 'san xuat'), 'htro_nuoc_sach': ('nước sạch', 'nuoc sach'), 'htro_dien': ('điện', 'dien'), 'htro_vien_thong': ('viễn thông', 'vien thong'), 'htro_dao_tao_nghe': ('đào tạo nghề', 'dao tao nghe')}
HOUSE_STATE_ALIASES = (('Không có nhà', ('khong co nha(?!\\s+(?:tieu|ve sinh))',)), ('Bán kiên cố', ('ban kien co',)), ('Nhà đơn sơ', ('nha don so', 'don so')), ('Nhà tạm', ('nha tam',)), ('Kiên cố', ('kien co',)))
CLASSIFICATION_ALIASES = (('Hộ không nghèo', ('ho khong ngheo', 'nhom khong ngheo', 'khong ngheo')), ('Hộ cận nghèo', ('ho can ngheo', 'ho sat ngheo', 'nhom can ngheo', 'can ngheo')), ('Hộ nghèo', ('ho ngheo', 'ho kho khan', 'nhom ngheo')))
EQUIVALENT_FILTER_RULES = [
    {"keep": ("gioi_tinh", "=", "Nữ"), "drop": [("nhom_chu_ho_nu", "=", 1)]},
]
DISABILITY_CONTEXT_ALIASES = {
    'household': ('có người khuyết tật', 'người khuyết tật', 'hộ có người khuyết tật'),
    'head': ('sức khỏe chủ hộ', 'tình trạng sức khỏe chủ hộ', 'chủ hộ khuyết tật', 'chủ hộ bị khuyết tật', 'chủ hộ tàn tật', 'chủ hộ bị tàn tật'),
}

MULTI_METRIC_TERM_ALIASES = {
    'th_bhyt': ('bhyt', 'bảo hiểm y tế', 'thiếu bhyt', 'không có bhyt', 'thiếu bảo hiểm y tế', 'không có bảo hiểm y tế'),
    'th_bhxh': ('bhxh', 'bảo hiểm xã hội', 'thiếu bhxh', 'không có bhxh', 'thiếu bảo hiểm xã hội', 'không có bảo hiểm xã hội'),
    'th_nuoc_sach': ('nước sạch', 'thiếu nước sạch', 'không có nước sạch'),
    'th_nha_tieu': ('nhà tiêu', 'nhà vệ sinh', 'thiếu nhà tiêu', 'thiếu nhà vệ sinh', 'nhà tiêu hợp vệ sinh', 'nhà vệ sinh hợp vệ sinh'),
    'tinh_trang_nha': ('nhà kém', 'nhà ở kém', 'nhà xấu', 'nhà tạm', 'nhà đơn sơ', 'tạm bợ'),
}

GROUP_BY_TERM_ALIASES = {
    'tinh_trang_nha': ('nhà cửa', 'nhà ở', 'tình trạng nhà', 'loại nhà', 'chất lượng nhà'),
    'trinh_do_hoc_van_chu_ho': (
        'học vấn',
        'trình độ học vấn',
        'học vấn chủ hộ',
        'trình độ học vấn chủ hộ',
        'kiểu học vấn',
    ),
    'nguon_nuoc': ('nguồn nước', 'nguon nuoc', 'nước sinh hoạt', 'nuoc sinh hoat', 'loại nước', 'loai nuoc'),
}

# Tín hiệu dùng chung khi người dùng hỏi miền giá trị của một cột.
DISTINCT_VALUE_TERMS = (
    'khác nhau', 'riêng biệt', 'không trùng', 'duy nhất', 'distinct', 'unique',
)

MISSING_TEXT_LABEL = 'Không ghi nhận'

DERIVED_METRIC_DEFINITIONS = {
    'nha_o_kem': {
        'source_col': 'tinh_trang_nha',
        'values': ('Nhà tạm', 'Nhà đơn sơ'),
        'alias': 'so_ho_nha_o_kem',
        'label': 'Số hộ nhà ở kém',
    },
}
NUMERIC_FIELD_CATALOG = {
    "so_tre_em": {"label": "số trẻ em", "aliases": ["số trẻ em", "trẻ em", "con nhỏ", "trẻ nhỏ"]},
    "so_nhan_khau": {"label": "số nhân khẩu", "aliases": ["số nhân khẩu", "nhân khẩu", "số người", "số người trong hộ"]},
    "thu_nhap_bq": {"label": "thu nhập bình quân", "aliases": ["thu nhập", "thu nhập bình quân", "thu nhập bq", "thu nhập trung bình", "thu nhập/người", "thu nhập tháng", "thu nhập bình quân tháng"]},
    "dien_tich_dat": {"label": "diện tích đất", "aliases": ["diện tích đất", "đất sản xuất", "đất canh tác", "đất nông nghiệp"]},
    "tong_chieu_thieu_hut": {"label": "tổng chiều thiếu hụt", "aliases": ["số chiều thiếu hụt", "tổng chiều thiếu hụt", "chiều thiếu hụt", "mức thiếu hụt"]},
    "so_nguoi_lao_dong": {"label": "số người lao động", "aliases": ["số người lao động", "lao động", "người lao động", "lao động trong hộ"]},
    "so_nguoi_cao_tuoi": {"label": "số người cao tuổi", "aliases": ["số người cao tuổi", "người cao tuổi", "người già", "trên 60 tuổi"]},
    "ty_le_phu_thuoc": {"label": "tỷ lệ phụ thuộc", "aliases": ["tỷ lệ phụ thuộc", "phụ thuộc", "hệ số phụ thuộc"]},
}
FEATURE_CATALOG = {
    "th_dinh_duong": {"label": "thiếu dinh dưỡng", "aliases": ["thiếu dinh dưỡng", "thiếu hụt dinh dưỡng", "không đảm bảo dinh dưỡng", "thiếu ăn"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_dinh_duong", "table_label": "Số hộ thiếu dinh dưỡng"},
    "th_giao_duc_nguoi_lon": {"label": "thiếu giáo dục người lớn", "aliases": ["thiếu giáo dục người lớn", "thiếu hụt giáo dục người lớn", "giáo dục người lớn", "trình độ giáo dục người lớn"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_giao_duc_nguoi_lon", "table_label": "Số hộ thiếu giáo dục người lớn"},
    "th_di_hoc_tre_em": {"label": "thiếu đi học trẻ em", "aliases": ["thiếu đi học trẻ em", "thiếu hụt đi học trẻ em", "trẻ em không đi học", "tình trạng đi học trẻ em"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_di_hoc_tre_em", "table_label": "Số hộ thiếu đi học trẻ em"},
    "th_vien_thong": {"label": "thiếu viễn thông", "aliases": ["thiếu viễn thông", "thiếu hụt viễn thông", "không có viễn thông", "thiếu dịch vụ viễn thông"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_vien_thong", "table_label": "Số hộ thiếu viễn thông"},
    "th_tai_san_tt": {"label": "thiếu tài sản thông tin", "aliases": ["thiếu tài sản thông tin", "thiếu hụt tài sản thông tin", "thiếu tài sản tiếp cận thông tin", "không có tài sản thông tin"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_tai_san_thong_tin", "table_label": "Số hộ thiếu tài sản thông tin"},
    "th_nha_tieu": {"label": "thiếu nhà tiêu hợp vệ sinh", "aliases": ["thiếu nhà tiêu", "thiếu nhà tiêu hợp vệ sinh", "không có nhà tiêu", "không có nhà tiêu hợp vệ sinh", "chưa có nhà tiêu", "chưa có nhà tiêu hợp vệ sinh", "thiếu nhà vệ sinh", "thiếu nhà vệ sinh hợp vệ sinh"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_nha_tieu", "table_label": "Số hộ thiếu nhà tiêu hợp vệ sinh"},
    "th_bhyt": {"label": "thiếu BHYT", "aliases": ["thiếu bhyt", "không có bhyt", "thiếu bảo hiểm y tế", "không có bảo hiểm y tế", "thiếu hụt bảo hiểm y tế"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_bhyt", "table_label": "Số hộ thiếu BHYT"},
    "th_bhxh": {"label": "thiếu BHXH", "aliases": ["thiếu bhxh", "không có bhxh", "thiếu bảo hiểm xã hội", "thiếu hụt bảo hiểm xã hội"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_bhxh", "table_label": "Số hộ thiếu BHXH"},
    "th_nuoc_sach": {"label": "thiếu nước sạch", "aliases": ["thiếu nước sạch", "thiếu hụt nước sạch", "không có nước sạch"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_nuoc_sach", "table_label": "Số hộ thiếu nước sạch"},
    "th_viec_lam": {"label": "thiếu việc làm", "aliases": ["thiếu việc làm", "thiếu hụt việc làm", "không có việc làm", "chưa có việc làm"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_viec_lam", "table_label": "Số hộ thiếu việc làm"},
    "th_chat_luong_nha": {"label": "thiếu chất lượng nhà ở", "aliases": ["thiếu chất lượng nhà ở", "thiếu hụt chất lượng nhà ở", "nhà ở kém chất lượng", "chất lượng nhà ở kém"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_chat_luong_nha", "table_label": "Số hộ thiếu chất lượng nhà ở"},
    "th_dien_tich_nha": {"label": "thiếu diện tích nhà ở", "aliases": ["thiếu diện tích nhà ở", "thiếu hụt diện tích nhà ở", "diện tích nhà ở thiếu", "nhà ở thiếu diện tích"], "kind": "flag", "value": 1, "group": "chi_so", "table_alias": "so_ho_thieu_dien_tich_nha", "table_label": "Số hộ thiếu diện tích nhà ở"},

    "nn_thieu_cong_cu": {
        "label": "thiếu công cụ sản xuất",
        "aliases": [
            "thiếu công cụ",
            "thiếu công cụ sản xuất",
            "thiếu công cụ phương tiện sản xuất",
            "thiếu phương tiện sản xuất",
            "thiếu công cụ/ptxs",
        ],
        "kind": "flag",
        "value": 1,
        "group": "nguyen_nhan",
        "table_alias": "so_ho_thieu_cong_cu",
        "table_label": "Số hộ thiếu công cụ",
    },
    "nn_thieu_kien_thuc": {
        "label": "thiếu kiến thức sản xuất",
        "aliases": [
            "thiếu kiến thức",
            "thiếu kiến thức sản xuất",
            "thiếu kiến thức sx",
            "thiếu kiến thức làm ăn",
            "thiếu kỹ thuật sản xuất",
        ],
        "kind": "flag",
        "value": 1,
        "group": "nguyen_nhan",
        "table_alias": "so_ho_thieu_kien_thuc",
        "table_label": "Số hộ thiếu kiến thức",
    },
    "nn_thieu_ky_nang": {
        "label": "thiếu kỹ năng lao động",
        "aliases": [
            "thiếu kỹ năng",
            "thiếu kỹ năng lao động",
            "thiếu kỹ năng làm việc",
            "thiếu tay nghề",
            "không có tay nghề",
        ],
        "kind": "flag",
        "value": 1,
        "group": "nguyen_nhan",
        "table_alias": "so_ho_thieu_ky_nang",
        "table_label": "Số hộ thiếu kỹ năng",
    },
    "nn_khac": {"label": "nguyên nhân khác", "aliases": ["nguyên nhân khác", "lý do khác", "nguyên nhân nghèo khác"], "kind": "flag", "value": 1, "group": "nguyen_nhan", "table_alias": "so_ho_nguyen_nhan_khac", "table_label": "Số hộ có nguyên nhân khác"},
    "nn_thieu_von": {"label": "thiếu vốn", "aliases": ["thiếu vốn", "không có vốn", "thiếu vốn sản xuất", "thiếu vốn làm ăn"], "kind": "flag", "value": 1, "group": "nguyen_nhan", "table_alias": "so_ho_thieu_von", "table_label": "Số hộ thiếu vốn"},
    "nn_thieu_dat": {"label": "thiếu đất sản xuất", "aliases": ["thiếu đất", "thiếu đất sản xuất", "không có đất sản xuất", "thiếu đất canh tác", "không có đất canh tác"], "kind": "flag", "value": 1, "group": "nguyen_nhan", "table_alias": "so_ho_thieu_dat", "table_label": "Số hộ thiếu đất sản xuất"},
    "nn_thieu_lao_dong": {"label": "thiếu lao động", "aliases": ["thiếu lao động", "thiếu nhân công", "không có lao động", "thiếu người lao động"], "kind": "flag", "value": 1, "group": "nguyen_nhan", "table_alias": "so_ho_thieu_lao_dong", "table_label": "Số hộ thiếu lao động"},
    "nn_om_dau": {"label": "ốm đau/bệnh/tai nạn", "aliases": ["ốm đau", "bệnh nặng", "bệnh tật", "tai nạn", "ốm đau bệnh tật"], "kind": "flag", "value": 1, "group": "nguyen_nhan", "table_alias": "so_ho_om_dau_benh_tat", "table_label": "Số hộ do ốm đau/bệnh/tai nạn"},

    "co_trau_bo": {
        "label": "có nuôi trâu/bò",
        "kind": "flag",
        "value": 1,
        "group": "tai_san_san_xuat",
        "table_alias": "so_ho_nuoi_trau_bo",
        "table_label": "Số hộ nuôi trâu/bò",
        "aliases": [
            "có trâu bò",
            "có trâu/bò",
            "nuôi trâu bò",
            "nuôi trâu",
            "nuôi bò",
            "có nuôi trâu",
            "có nuôi bò",
            "có bò",
            "có trâu",
            "trâu bò",
        ],
    },
    "co_lon": {"label": "nuôi lợn", "aliases": ["nuôi lợn", "nuôi heo", "có lợn", "có heo", "có nuôi lợn", "có nuôi heo"], "kind": "flag", "value": 1, "group": "tai_san_san_xuat", "table_alias": "so_ho_nuoi_lon", "table_label": "Số hộ nuôi lợn/heo"},
    "co_ga_vit": {"label": "nuôi gà vịt", "aliases": ["nuôi gà vịt", "nuôi gà", "nuôi vịt", "có gà vịt", "có nuôi gà vịt", "gia cầm"], "kind": "flag", "value": 1, "group": "tai_san_san_xuat", "table_alias": "so_ho_nuoi_ga_vit", "table_label": "Số hộ nuôi gà/vịt"},

    "htro_vien_thong": {"label": "hỗ trợ viễn thông", "aliases": ["hỗ trợ viễn thông", "được hỗ trợ viễn thông", "nhận hỗ trợ viễn thông", "hỗ trợ dịch vụ viễn thông"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_vien_thong", "table_label": "Số hộ hỗ trợ viễn thông"},
    "htro_dao_tao_nghe": {"label": "hỗ trợ đào tạo nghề", "aliases": ["hỗ trợ đào tạo nghề", "được hỗ trợ đào tạo nghề", "nhận hỗ trợ đào tạo nghề", "đào tạo nghề", "học nghề"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_dao_tao_nghe", "table_label": "Số hộ hỗ trợ đào tạo nghề"},
    "htro_y_te": {"label": "hỗ trợ y tế", "aliases": ["hỗ trợ y tế", "được hỗ trợ y tế", "nhận hỗ trợ y tế"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_y_te", "table_label": "Số hộ hỗ trợ y tế"},
    "htro_nha_o": {"label": "hỗ trợ nhà ở", "aliases": ["hỗ trợ nhà ở", "hỗ trợ về nhà ở", "được hỗ trợ nhà ở", "nhận hỗ trợ nhà ở"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_nha_o", "table_label": "Số hộ hỗ trợ nhà ở"},
    "htro_vay_von": {"label": "hỗ trợ vay vốn", "aliases": ["hỗ trợ vay vốn", "được hỗ trợ vay vốn", "nhận hỗ trợ vay vốn", "vay vốn"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_vay_von", "table_label": "Số hộ hỗ trợ vay vốn"},
    "htro_san_xuat": {"label": "hỗ trợ sản xuất", "aliases": ["hỗ trợ sản xuất", "được hỗ trợ sản xuất", "nhận hỗ trợ sản xuất"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_san_xuat", "table_label": "Số hộ hỗ trợ sản xuất"},
    "htro_giao_duc": {"label": "hỗ trợ giáo dục", "aliases": ["hỗ trợ giáo dục", "được hỗ trợ giáo dục", "nhận hỗ trợ giáo dục"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_giao_duc", "table_label": "Số hộ hỗ trợ giáo dục"},
    "htro_dien": {"label": "hỗ trợ điện", "aliases": ["hỗ trợ điện", "hỗ trợ điện sinh hoạt", "được hỗ trợ điện"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_dien", "table_label": "Số hộ hỗ trợ điện"},
    "htro_nuoc_sach": {"label": "hỗ trợ nước sạch", "aliases": ["hỗ trợ nước sạch", "hỗ trợ nước sạch vệ sinh", "được hỗ trợ nước sạch"], "kind": "flag", "value": 1, "group": "ho_tro", "table_alias": "so_ho_ho_tro_nuoc_sach", "table_label": "Số hộ hỗ trợ nước sạch"},

    "co_tre_em": {
        "label": "có trẻ em",
        "aliases": [
            "có trẻ em",
            "hộ có trẻ em",
            "có trẻ nhỏ",
            "có con nhỏ",
            "con nhỏ",
            "trẻ nhỏ",
        ],
        "kind": "flag",
        "value": 1,
        "group": "nhom_doi_tuong",
        "table_alias": "so_ho_co_tre_em",
        "table_label": "Số hộ có trẻ em",
    },
    "nhom_tre_em_duoi6": {"label": "có trẻ dưới 6 tuổi", "aliases": ["trẻ dưới 6", "trẻ em dưới 6", "có trẻ dưới 6 tuổi", "có trẻ em dưới 6 tuổi"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_tre_em_duoi6", "table_label": "Số hộ có trẻ dưới 6 tuổi"},
    "te_th_bhyt": {"label": "trẻ em thiếu BHYT", "aliases": ["trẻ em thiếu bhyt", "trẻ thiếu bhyt", "trẻ dưới 6 thiếu bhyt", "trẻ em dưới 6 thiếu bhyt", "trẻ em thiếu bảo hiểm y tế", "trẻ thiếu bảo hiểm y tế", "trẻ em dưới 6 thiếu bảo hiểm y tế"], "kind": "flag", "value": 1, "group": "tre_em", "table_alias": "so_ho_tre_thieu_bhyt", "table_label": "Số hộ trẻ em thiếu BHYT", "overlap_filter_cols": ["th_bhyt"]},
    "te_th_dinh_duong": {
        "label": "trẻ em thiếu dinh dưỡng",
        "aliases": [
            "trẻ em thiếu dinh dưỡng",
            "trẻ thiếu dinh dưỡng",
            "trẻ em thiếu hụt dinh dưỡng",
            "trẻ thiếu hụt dinh dưỡng",
        ],
        "kind": "flag",
        "value": 1,
        "group": "tre_em",
        "table_alias": "so_ho_tre_thieu_dinh_duong",
        "table_label": "Số hộ trẻ em thiếu dinh dưỡng",
        "overlap_filter_cols": ["th_dinh_duong"],
    },
    "te_th_di_hoc": {
        "label": "trẻ em thiếu đi học",
        "aliases": [
            "trẻ em thiếu đi học",
            "trẻ thiếu đi học",
            "trẻ em không đi học",
            "trẻ không đi học",
            "trẻ em thiếu học tập",
        ],
        "kind": "flag",
        "value": 1,
        "group": "tre_em",
        "table_alias": "so_ho_tre_em_thieu_di_hoc",
        "table_label": "Số hộ trẻ em thiếu đi học",
        "overlap_filter_cols": ["th_di_hoc_tre_em"],
    },
    "nhom_dtts": {"label": "dân tộc thiểu số", "aliases": ["dân tộc thiểu số", "dtts", "hộ dtts", "thuộc dân tộc thiểu số"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_dtts", "table_label": "Số hộ DTTS"},
    "nhom_don_than": {"label": "hộ đơn thân/độc thân", "aliases": ["đơn thân", "độc thân", "hộ đơn thân", "hộ độc thân", "không có vợ chồng", "không có vợ hoặc chồng"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_don_than", "table_label": "Số hộ đơn thân/độc thân"},
    "nhom_chu_ho_nu": {"label": "chủ hộ nữ", "aliases": ["chủ hộ nữ", "chủ hộ là nữ", "hộ có chủ hộ nữ", "hộ có chủ hộ là nữ"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_chu_ho_nu", "table_label": "Số hộ chủ hộ nữ"},
    "nhom_khuyet_tat": {"label": "có người khuyết tật", "aliases": ["khuyết tật", "người khuyết tật", "có người khuyết tật", "hộ có người khuyết tật"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_khuyet_tat", "table_label": "Số hộ có người khuyết tật"},
    "nhom_cao_tuoi": {
        "label": "có người cao tuổi",
        "aliases": [
            "cao tuổi",
            "người cao tuổi",
            "có người cao tuổi",
            "hộ có người cao tuổi",
            "người già",
            "có người già",
            "trên 60 tuổi",
        ],
        "kind": "flag",
        "value": 1,
        "group": "nhom_doi_tuong",
        "table_alias": "so_ho_cao_tuoi",
        "table_label": "Số hộ có người cao tuổi",
    },
}
FEATURE_KEYWORDS = {
    "th_dinh_duong": ("thiếu dinh dưỡng", "thiếu hụt dinh dưỡng", "không đảm bảo dinh dưỡng"),
    "th_giao_duc_nguoi_lon": ("thiếu giáo dục người lớn", "thiếu hụt giáo dục người lớn", "giáo dục người lớn"),
    "th_di_hoc_tre_em": ("thiếu đi học trẻ em", "thiếu hụt đi học trẻ em", "trẻ em không đi học", "tình trạng đi học trẻ em"),
    "th_vien_thong": ("thiếu viễn thông", "thiếu hụt viễn thông", "không có viễn thông"),
    "th_tai_san_tt": ("thiếu tài sản thông tin", "thiếu hụt tài sản thông tin", "thiếu tài sản tiếp cận thông tin"),
    "th_chat_luong_nha": ("thiếu chất lượng nhà ở", "thiếu hụt chất lượng nhà ở"),
    "th_dien_tich_nha": ("thiếu diện tích nhà ở", "thiếu hụt diện tích nhà ở"),
    "th_bhyt": ("thiếu bhyt", "thiếu bảo hiểm y tế", "thiếu hụt bảo hiểm y tế", "thiếu hụt bhyt", "không có bhyt", "không có bảo hiểm y tế"),
    "th_bhxh": ("thiếu bhxh", "thiếu bảo hiểm xã hội", "thiếu hụt bảo hiểm xã hội", "thiếu hụt bhxh"),
    "th_nuoc_sach": ("thiếu nước sạch",),
    "th_nha_tieu": ("thiếu nhà tiêu",),
    "th_viec_lam": ("thiếu việc làm",),

    "nn_thieu_cong_cu": ("thiếu công cụ", "thiếu công cụ sản xuất", "thiếu phương tiện sản xuất"),
    "nn_thieu_kien_thuc": ("thiếu kiến thức", "thiếu kiến thức sản xuất", "thiếu kỹ thuật sản xuất"),
    "nn_thieu_ky_nang": ("thiếu kỹ năng", "thiếu kỹ năng lao động", "thiếu tay nghề", "không có tay nghề"),
    "nn_khac": ("nguyên nhân khác", "lý do khác"),
    "nn_thieu_dat": ("thiếu đất",),
    "nn_thieu_von": ("thiếu vốn",),
    "nn_thieu_lao_dong": ("thiếu lao động",),
    "nn_om_dau": ("ốm đau", "bệnh nặng"),

    "co_trau_bo": ("trâu bò", "trâu/bò", "nuôi trâu bò", "có nuôi trâu bò", "gia súc lớn"),
    "co_lon": ("nuôi lợn", "nuôi heo", "có lợn", "có heo"),
    "co_ga_vit": ("nuôi gà", "nuôi vịt", "nuôi gà vịt", "gia cầm"),

    "htro_vien_thong": ("hỗ trợ viễn thông", "được hỗ trợ viễn thông", "nhận hỗ trợ viễn thông"),
    "htro_dao_tao_nghe": ("hỗ trợ đào tạo nghề", "được hỗ trợ đào tạo nghề", "nhận hỗ trợ đào tạo nghề", "đào tạo nghề", "học nghề"),
    "htro_nha_o": ("hỗ trợ nhà ở", "hỗ trợ về nhà ở", "được nhận hỗ trợ về nhà ở", "nhận hỗ trợ về nhà ở"),
    "htro_vay_von": ("hỗ trợ vay vốn", "được hỗ trợ vay vốn", "nhận hỗ trợ vay vốn", "vay vốn"),
    "htro_y_te": ("hỗ trợ y tế", "được hỗ trợ y tế", "nhận hỗ trợ y tế"),
    "htro_giao_duc": ("hỗ trợ giáo dục", "được hỗ trợ giáo dục", "nhận hỗ trợ giáo dục"),
    "htro_san_xuat": ("hỗ trợ sản xuất", "được hỗ trợ sản xuất", "nhận hỗ trợ sản xuất"),
    "htro_nuoc_sach": ("hỗ trợ nước sạch", "được hỗ trợ nước sạch", "nhận hỗ trợ nước sạch"),
    "htro_dien": ("hỗ trợ điện", "được hỗ trợ điện", "nhận hỗ trợ điện"),

    "nhom_khuyet_tat": ("khuyết tật",),
    "nhom_cao_tuoi": ("cao tuổi", "người cao tuổi", "có người cao tuổi", "trên 60 tuổi"),
    "nhom_tre_em_duoi6": ("trẻ em dưới 6", "trẻ dưới 6"),
    "co_tre_em": ("có trẻ em",),
    "nhom_chu_ho_nu": ("chủ hộ nữ", "chủ hộ là nữ"),
    "nhom_dtts": ("dân tộc thiểu số", "dtts"),
    "nhom_don_than": ("đơn thân", "độc thân", "không có vợ/chồng", "không có vợ chồng", "không có vợ hoặc chồng"),

    "co_internet": ("có internet",),
    "co_dien": ("có điện",),
}
FEATURE_RULES = [{'col': 'th_bhyt', 'positive': ('thiếu bhyt', 'thiếu bảo hiểm y tế', 'thiếu hụt bảo hiểm y tế', 'thiếu hụt bhyt', 'không có bhyt', 'không có bảo hiểm y tế'), 'value': 1}, {'col': 'th_bhxh', 'positive': ('thiếu bhxh', 'thiếu bảo hiểm xã hội', 'thiếu hụt bảo hiểm xã hội', 'thiếu hụt bhxh', 'không có bhxh', 'không có bảo hiểm xã hội'), 'value': 1}, {'col': 'th_nuoc_sach', 'positive': ('thiếu nước sạch',), 'negative': ('có nước sạch',)}, {'col': 'th_nha_tieu', 'positive': ('không có nhà tiêu hợp vệ sinh', 'không có nhà vệ sinh hợp vệ sinh', 'không có nhà tiêu hvs', 'không có nhà vệ sinh hvs', 'thiếu nhà tiêu', 'thiếu nhà vệ sinh', 'thiếu nhà tiêu hvs', 'thiếu nhà vệ sinh hvs'), 'value': 1}, {'col': 'co_nha_tieu_hvs', 'positive': ('có nhà tiêu hợp vệ sinh', 'có nhà vệ sinh hợp vệ sinh', 'có nhà tiêu hvs', 'có nhà vệ sinh hvs', 'nhà tiêu hvs', 'nhà vệ sinh hvs'), 'value': 1, 'blocked_by': ('không có nhà tiêu hợp vệ sinh', 'không có nhà vệ sinh hợp vệ sinh', 'không có nhà tiêu hvs', 'không có nhà vệ sinh hvs')}, {'col': 'co_dien', 'positive': ('có điện', 'sử dụng điện', 'có điện sinh hoạt'), 'negative': ('chưa có điện', 'không có điện', 'không sử dụng điện', 'chưa có điện sinh hoạt', 'không có điện sinh hoạt')}, {'col': 'co_internet', 'positive': ('có internet', 'có mạng internet', 'truy cập internet', 'sử dụng internet'), 'negative': ('chưa có internet', 'không có internet', 'không có mạng internet', 'chưa có mạng', 'không có mạng')}]
BASE_RECORD_COLUMNS = [
    'chu_ho',
    'nam',
    'huyen',
    'xa_phuong',
    'phan_loai',
    'gioi_tinh',
    'dan_toc_chi_tiet',
    'so_nhan_khau',
]
DETAIL_COLUMN_GROUPS = {'nhan_khau': (('nhân khẩu', 'thành viên', 'phụ thuộc'), ['so_nhan_khau', 'so_tre_em', 'so_nguoi_lao_dong', 'so_nguoi_cao_tuoi', 'ty_le_phu_thuoc']), 'tre_em': (('trẻ em', 'trẻ dưới', 'con em'), ['so_tre_em', 'co_tre_em', 'nhom_tre_em_duoi6', 'nhom_tre_em_di_hoc', 'te_th_bhyt', 'te_th_dinh_duong', 'te_th_di_hoc']), 'lao_dong': (('lao động', 'việc làm', 'khả năng lao động'), ['so_nguoi_lao_dong', 'nghe_nghiep_chu_ho', 'nhom_khong_knld', 'nn_thieu_lao_dong', 'th_viec_lam']), 'cao_tuoi': (('cao tuổi', 'người già', 'trên 60 tuổi'), ['so_nguoi_cao_tuoi', 'nhom_cao_tuoi']), 'nha_o': (('nhà ở', 'tình trạng nhà', 'chất lượng nhà', 'diện tích nhà'), ['tinh_trang_nha', 'th_chat_luong_nha', 'th_dien_tich_nha']), 'nuoc_sach': (('nước sạch', 'nguồn nước', 'nước sinh hoạt'), ['nguon_nuoc', 'th_nuoc_sach']), 'nha_tieu': (('nhà tiêu', 'nhà vệ sinh'), ['co_nha_tieu_hvs', 'th_nha_tieu'])}
FILTER_DETAIL_COLUMNS = {'co_tre_em': 'tre_em', 'nhom_tre_em_duoi6': 'tre_em', 'nhom_tre_em_di_hoc': 'tre_em', 'te_th_bhyt': 'tre_em', 'te_th_dinh_duong': 'tre_em', 'te_th_di_hoc': 'tre_em', 'so_tre_em': 'tre_em', 'so_nhan_khau': 'nhan_khau', 'ty_le_phu_thuoc': 'nhan_khau', 'so_nguoi_lao_dong': 'lao_dong', 'nhom_khong_knld': 'lao_dong', 'nn_thieu_lao_dong': 'lao_dong', 'th_viec_lam': 'lao_dong', 'so_nguoi_cao_tuoi': 'cao_tuoi', 'nhom_cao_tuoi': 'cao_tuoi', 'tinh_trang_nha': 'nha_o', 'th_chat_luong_nha': 'nha_o', 'th_dien_tich_nha': 'nha_o', 'nguon_nuoc': 'nuoc_sach', 'th_nuoc_sach': 'nuoc_sach', 'co_nha_tieu_hvs': 'nha_tieu', 'th_nha_tieu': 'nha_tieu'}

# ===== COVERAGE PATCH: bổ sung catalog-driven features =====

_FLAG_EXTRA = {
    "co_nha_tieu_hvs", "nhom_tre_em_di_hoc", "te_th_bhyt", "te_th_dinh_duong", "te_th_di_hoc",
    "nhom_co_cong", "nhom_khong_knld", "nhom_thuong_binh", "tro_cap_thuong_xuyen", "tro_cap_dot_xuat",
    "co_dien", "co_internet", "xa_dac_biet_kho_khan", "tinh_bien_gioi", "chinh_sach_khac", "co_vo_chong_chu_ho",
}
_OUTPUT_EXTRA = {
    "bien_dong_dau_ky", "cay_trong_chinh", "chinh_sach_khac", "co_vo_chong_chu_ho", "khu_vuc_xa",
    "ky_ra_soat", "loai_xa_phuong", "nhom_ngheo_tong_hop", "tinh_bien_gioi",
    "b1_diem", "b2_diem", "phieu_a", "nguoi_ra_soat",
}
DISPLAY_ONLY_OUTPUT_COLUMNS = {"b1_diem", "b2_diem", "phieu_a", "nguoi_ra_soat"}
_GROUP_EXTRA = {
    "bien_dong_dau_ky", "cay_trong_chinh", "khu_vuc_xa", "ky_ra_soat", "loai_xa_phuong",
    "nhom_ngheo_tong_hop", "dan_toc_tai_cho", "xa_dac_biet_kho_khan", "tinh_bien_gioi", "chinh_sach_khac",
}
CHILD_DEPRIVATION_COUNT_COLUMNS = {
    "so_tre_thieu_bhyt",
    "so_tre_thieu_dinh_duong",
    "so_tre_thieu_di_hoc",
}

FLAG_COLUMNS.update(_FLAG_EXTRA)
OUTPUT_COLUMNS.discard("so_tre_em_trong_ho")
FILTER_COLUMNS.discard("so_tre_em_trong_ho")
NUMERIC_COLUMNS.update(CHILD_DEPRIVATION_COUNT_COLUMNS)
OUTPUT_COLUMNS.update(_OUTPUT_EXTRA | _FLAG_EXTRA | CHILD_DEPRIVATION_COUNT_COLUMNS)
GROUP_COLUMNS.update(_GROUP_EXTRA)
FILTER_COLUMNS.update((OUTPUT_COLUMNS - DISPLAY_ONLY_OUTPUT_COLUMNS) | FLAG_COLUMNS | _GROUP_EXTRA | {"dan_toc_tai_cho", "muc_do_thieu_hut", "nguon_nuoc"})
ALL_COLUMNS = FILTER_COLUMNS | GROUP_COLUMNS
ORDER_COLUMNS = ALL_COLUMNS

NUMERIC_FIELD_CATALOG.update({
    "so_tre_thieu_bhyt": {
        "label": "so tre em thieu BHYT",
        "aliases": [
            "so tre em thieu BHYT",
            "so tre thieu BHYT",
            "tre em thieu BHYT",
            "tre thieu BHYT",
            "tre em thieu bao hiem y te",
            "tre thieu bao hiem y te",
        ],
    },
    "so_tre_thieu_dinh_duong": {
        "label": "so tre em thieu dinh duong",
        "aliases": [
            "so tre em thieu dinh duong",
            "so tre thieu dinh duong",
            "tre em thieu dinh duong",
            "tre thieu dinh duong",
        ],
    },
    "so_tre_thieu_di_hoc": {
        "label": "so tre em thieu di hoc",
        "aliases": [
            "so tre em thieu di hoc",
            "so tre thieu di hoc",
            "tre em thieu di hoc",
            "tre thieu di hoc",
            "tre em khong di hoc",
            "tre khong di hoc",
        ],
    },
})

FEATURE_CATALOG.update({
    "co_dien": {"label": "có điện sinh hoạt", "aliases": ["có điện", "có điện sinh hoạt", "sử dụng điện", "điện sinh hoạt"], "kind": "flag", "value": 1, "group": "dieu_kien_song", "table_alias": "so_ho_co_dien", "table_label": "Số hộ có điện"},
    "co_internet": {"label": "có internet", "aliases": ["có internet", "có mạng internet", "có mạng", "truy cập internet", "sử dụng internet"], "kind": "flag", "value": 1, "group": "dieu_kien_song", "table_alias": "so_ho_co_internet", "table_label": "Số hộ có internet"},
    "co_nha_tieu_hvs": {"label": "có nhà tiêu hợp vệ sinh", "aliases": ["có nhà tiêu hợp vệ sinh", "có nhà vệ sinh hợp vệ sinh", "có nhà tiêu hvs", "có nhà vệ sinh hvs"], "kind": "flag", "value": 1, "group": "dieu_kien_song", "table_alias": "so_ho_co_nha_tieu_hvs", "table_label": "Số hộ có nhà tiêu HVS"},
    "nhom_tre_em_di_hoc": {"label": "có trẻ em đi học", "aliases": ["có trẻ em đi học", "trẻ em đi học", "hộ có trẻ em đi học", "con em đi học"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_tre_em_di_hoc", "table_label": "Số hộ có trẻ em đi học"},
    "nhom_khong_knld": {"label": "không có khả năng lao động", "aliases": ["không có khả năng lao động", "không khả năng lao động", "mất khả năng lao động", "không còn khả năng lao động", "không knld"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_khong_knld", "table_label": "Số hộ không có khả năng lao động"},
    "nhom_co_cong": {"label": "người có công", "aliases": ["người có công", "hộ có người có công", "gia đình có công", "đối tượng có công"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_co_cong", "table_label": "Số hộ có người có công"},
    "nhom_thuong_binh": {"label": "thương binh", "aliases": ["thương binh", "hộ có thương binh", "người thương binh"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_thuong_binh", "table_label": "Số hộ có thương binh"},
    "tro_cap_thuong_xuyen": {"label": "trợ cấp thường xuyên", "aliases": ["trợ cấp thường xuyên", "có trợ cấp thường xuyên", "nhận trợ cấp thường xuyên"], "kind": "flag", "value": 1, "group": "chinh_sach", "table_alias": "so_ho_tro_cap_thuong_xuyen", "table_label": "Số hộ có trợ cấp thường xuyên"},
    "tro_cap_dot_xuat": {"label": "trợ cấp đột xuất", "aliases": ["trợ cấp đột xuất", "có trợ cấp đột xuất", "nhận trợ cấp đột xuất"], "kind": "flag", "value": 1, "group": "chinh_sach", "table_alias": "so_ho_tro_cap_dot_xuat", "table_label": "Số hộ có trợ cấp đột xuất"},
    "te_th_dinh_duong": {"label": "trẻ em thiếu dinh dưỡng", "aliases": ["trẻ em thiếu dinh dưỡng", "trẻ thiếu dinh dưỡng", "trẻ em thiếu hụt dinh dưỡng", "trẻ thiếu hụt dinh dưỡng"], "kind": "flag", "value": 1, "group": "tre_em", "table_alias": "so_ho_tre_thieu_dinh_duong", "table_label": "Số hộ trẻ em thiếu dinh dưỡng", "overlap_filter_cols": ["th_dinh_duong"]},
    "te_th_di_hoc": {"label": "trẻ em thiếu đi học", "aliases": ["trẻ em thiếu đi học", "trẻ thiếu đi học", "trẻ em không đi học", "trẻ không đi học", "trẻ em thiếu học tập"], "kind": "flag", "value": 1, "group": "tre_em", "table_alias": "so_ho_tre_em_thieu_di_hoc", "table_label": "Số hộ trẻ em thiếu đi học", "overlap_filter_cols": ["th_di_hoc_tre_em"]},
    "xa_dac_biet_kho_khan": {"label": "xã đặc biệt khó khăn", "aliases": ["xã đặc biệt khó khăn", "đặc biệt khó khăn", "xã đbkk", "dbkk"], "kind": "flag", "value": 1, "group": "dia_ban", "table_alias": "so_ho_xa_dac_biet_kho_khan", "table_label": "Số hộ ở xã ĐBKK"},
    "tinh_bien_gioi": {"label": "xã biên giới", "aliases": ["biên giới", "xã biên giới", "địa bàn biên giới"], "kind": "flag", "value": 1, "group": "dia_ban", "table_alias": "so_ho_bien_gioi", "table_label": "Số hộ ở xã biên giới"},
    "chinh_sach_khac": {"label": "chính sách khác", "aliases": ["chính sách khác", "hỗ trợ chính sách khác", "được chính sách khác"], "kind": "flag", "value": 1, "group": "chinh_sach", "table_alias": "so_ho_chinh_sach_khac", "table_label": "Số hộ có chính sách khác"},
    "co_vo_chong_chu_ho": {"label": "chủ hộ có vợ/chồng", "aliases": ["có vợ chồng", "chủ hộ có vợ chồng", "có vợ hoặc chồng", "không đơn thân"], "kind": "flag", "value": 1, "group": "nhom_doi_tuong", "table_alias": "so_ho_co_vo_chong_chu_ho", "table_label": "Số hộ chủ hộ có vợ/chồng"},
})

if "co_trau_bo" in FEATURE_CATALOG:
    FEATURE_CATALOG["co_trau_bo"]["aliases"] = list(dict.fromkeys(FEATURE_CATALOG["co_trau_bo"].get("aliases", []) + ["nuôi trâu", "nuôi bò", "có nuôi trâu", "có nuôi bò", "có bò", "có trâu"]))

for _c, _m in FEATURE_CATALOG.items():
    if _m.get("kind") == "flag" and _m.get("aliases"):
        FEATURE_KEYWORDS[_c] = tuple(dict.fromkeys((*FEATURE_KEYWORDS.get(_c, ()), *_m.get("aliases", ()))))

FILTER_ANSWER_LABELS.update({
    "nhom_tre_em_di_hoc": ("có trẻ em đi học", "không có trẻ em đi học"),
    "co_nha_tieu_hvs": ("có nhà tiêu hợp vệ sinh", "không có nhà tiêu hợp vệ sinh"),
    "te_th_bhyt": ("trẻ em thiếu BHYT", "trẻ em không thiếu BHYT"),
    "te_th_dinh_duong": ("trẻ em thiếu dinh dưỡng", "trẻ em không thiếu dinh dưỡng"),
    "te_th_di_hoc": ("trẻ em thiếu đi học", "trẻ em không thiếu đi học"),
    "co_dien": ("có điện sinh hoạt", "chưa có điện sinh hoạt"),
    "co_internet": ("có internet", "chưa có internet"),
    "xa_dac_biet_kho_khan": ("ở xã đặc biệt khó khăn", "không ở xã đặc biệt khó khăn"),
    "tinh_bien_gioi": ("ở xã biên giới", "không ở xã biên giới"),
    "chinh_sach_khac": ("có chính sách khác", "không có chính sách khác"),
    "co_vo_chong_chu_ho": ("chủ hộ có vợ/chồng", "chủ hộ không có vợ/chồng"),
    "dan_toc_tai_cho": (
        "thuộc nhóm dân tộc thiểu số tại chỗ",
        "không thuộc nhóm dân tộc thiểu số tại chỗ",
    ),
})

DETAIL_COLUMN_GROUPS["tre_em"][1].extend([
    "so_tre_thieu_bhyt",
    "so_tre_thieu_dinh_duong",
    "so_tre_thieu_di_hoc",
])
FILTER_DETAIL_COLUMNS.update({
    "so_tre_thieu_bhyt": "tre_em",
    "so_tre_thieu_dinh_duong": "tre_em",
    "so_tre_thieu_di_hoc": "tre_em",
})

TEXT_FILTER_LABELS.update({
    "bien_dong_dau_ky": "biến động đầu kỳ", "cay_trong_chinh": "cây trồng chính", "khu_vuc_xa": "khu vực xã",
    "ky_ra_soat": "kỳ rà soát", "loai_xa_phuong": "loại xã/phường", "nhom_ngheo_tong_hop": "nhóm nghèo tổng hợp",
    "dan_toc_tai_cho": "dân tộc tại chỗ",
})

TEXT_FILTER_LABELS.update({
    "b1_diem": "Điểm B1",
    "b2_diem": "Điểm B2",
    "phieu_a": "Phiếu A",
    "nguoi_ra_soat": "Người rà soát",
})

SAME_COLUMN_CATALOG_CONTEXTS.update({
    "bien_dong_dau_ky": (
        "bien dong dau ky", "tai ngheo", "thoat ngheo", "phat sinh",
        "tai can ngheo", "ngheo cu", "can ngheo cu", "giu nguyen ngheo",
        "giu nguyen can ngheo", "tu ho ngheo len can ngheo",
        "can ngheo tro thanh ho ngheo", "ho can ngheo tro thanh ho ngheo",
        "tu ho can ngheo thanh ho ngheo", "tu ho can ngheo tro thanh ho ngheo",
        "can ngheo xuong ngheo", "can ngheo chuyen sang ngheo",
        "thoat can ngheo", "giam ngheo khac", "tang ngheo khac",
        "giam can ngheo khac", "tang can ngheo khac",
        "khong thay doi khong ngheo", "khong ngheo giu nguyen",
    ),
    "cay_trong_chinh": ("cay trong", "cay trong chinh", "trong cay", "nong san"),
    "khu_vuc_xa": ("khu vuc xa", "khu vuc", "xa khu vuc"),
    "ky_ra_soat": ("ky ra soat", "dot ra soat", "ra soat"),
    "loai_xa_phuong": ("loai xa", "loai xa phuong", "xa phuong", "thi tran", "phuong"),
    "nhom_ngheo_tong_hop": ("nhom ngheo tong hop", "nhom ngheo", "ngheo kinh te", "ngheo dtts"),
    "dan_toc_tai_cho": ("dan toc tai cho", "dtts tai cho", "tai cho"),
})
SPECIFIC_FILTER_OVERRIDES = {
    "dan_toc_tai_cho": {
        "suppresses": ["nhom_dtts"],
    },
    # "Nghèo DTTS tại chỗ" ở đây là một giá trị đầy đủ của nhóm nghèo
    # tổng hợp, không phải yêu cầu lọc riêng cột dân_toc_tai_cho.
    "nhom_ngheo_tong_hop": {
        "suppresses": ["dan_toc_tai_cho"],
    },
}

CATALOG_VALUE_ALIASES.update({
    "bien_dong_dau_ky": {
        "Nghèo cũ (giữ nguyên)": (
            "ngheo cu", "ho ngheo cu", "giu nguyen ngheo", "ngheo giu nguyen",
        ),
        "Tái nghèo": ("tai ngheo", "ho tai ngheo"),
        "Nghèo mới phát sinh": ("ngheo moi phat sinh", "ho ngheo moi phat sinh"),
        "Thoát nghèo -> cận nghèo": (
            "thoat ngheo len can ngheo", "thoat ngheo sang can ngheo", "thoat ngheo can ngheo",
            "tu ho ngheo len can ngheo",
        ),
        "Thoát nghèo -> vượt chuẩn": (
            "thoat ngheo vuot chuan", "thoat ngheo len vuot chuan",
        ),
        "Cận nghèo cũ (giữ nguyên)": (
            "can ngheo cu", "ho can ngheo cu", "giu nguyen can ngheo", "can ngheo giu nguyen",
        ),
        "Tái cận nghèo": ("tai can ngheo", "ho tai can ngheo"),
        "Cận nghèo mới phát sinh": (
            "can ngheo moi phat sinh", "ho can ngheo moi phat sinh",
        ),
        "Thoát cận nghèo -> vượt chuẩn": (
            "thoat can ngheo vuot chuan", "thoat can ngheo len vuot chuan",
            "can ngheo thoat vuot chuan",
        ),
        "Cận nghèo trở thành hộ nghèo": (
            "can ngheo tro thanh ho ngheo",
            "ho can ngheo tro thanh ho ngheo",
            "tu ho can ngheo thanh ho ngheo",
            "tu ho can ngheo tro thanh ho ngheo",
            "can ngheo xuong ngheo",
            "can ngheo chuyen sang ngheo",
        ),
        "Không thay đổi (không nghèo)": (
            "khong thay doi khong ngheo", "ho khong ngheo khong thay doi",
            "khong ngheo giu nguyen",
        ),
    },
    "khu_vuc_xa": {
        "I": ("khu vuc i", "kv i", "vung i"),
        "II": ("khu vuc ii", "kv ii", "vung ii"),
        "III": ("khu vuc iii", "kv iii", "vung iii"),
    },
    "loai_xa_phuong": {
        "xa": ("xa",),
        "phuong": ("phuong",),
        "thi_tran": ("thi tran", "thị trấn"),
    },
    "nhom_ngheo_tong_hop": {
        "Nghèo kinh tế thuần": ("ngheo kinh te thuan",),
        "Nghèo DTTS tại chỗ": ("ngheo dtts tai cho",),
        "Không nghèo": ("khong ngheo",),
    },
    "dan_toc_tai_cho": {
        "Có": (
            "co",
            "dtts tai cho",
            "dan toc tai cho",
            "dan toc thieu so tai cho",
            "ho dtts tai cho",
            "ho dan toc thieu so tai cho",
        ),
        "Không": (
            "khong",
            "khong tai cho",
            "khong phai dtts tai cho",
            "khong phai dan toc thieu so tai cho",
        ),
    },
})


MULTI_METRIC_TERM_ALIASES = globals().get("MULTI_METRIC_TERM_ALIASES", {})

for c, meta in FEATURE_CATALOG.items():
    if meta.get("kind") == "flag" and not c.startswith("htro_"):
        existing = tuple(MULTI_METRIC_TERM_ALIASES.get(c, ()))
        auto = tuple(meta.get("aliases", ()))
        MULTI_METRIC_TERM_ALIASES[c] = tuple(dict.fromkeys((*existing, *auto)))

GROUP_BY_TERM_ALIASES = globals().get("GROUP_BY_TERM_ALIASES", {})
GROUP_BY_TERM_ALIASES.update({
    "cay_trong_chinh": ("cây trồng", "cây trồng chính", "trồng cây gì"),
    "bien_dong_dau_ky": (
        "biến động đầu kỳ", "diễn biến hộ nghèo", "diễn biến hộ cận nghèo",
        "diễn biến", "loại biến động", "trạng thái biến động",
        "cơ cấu biến động", "nghèo cũ", "tái nghèo", "thoát nghèo",
        "nghèo mới phát sinh", "cận nghèo trở thành hộ nghèo",
    ),
    "khu_vuc_xa": ("khu vực xã", "khu vực"),
    "loai_xa_phuong": ("loại xã", "loại xã phường", "xã phường thị trấn"),
    "nhom_ngheo_tong_hop": ("nhóm nghèo tổng hợp", "nhóm nghèo"),
    "dan_toc_tai_cho": ("dân tộc tại chỗ", "dtts tại chỗ"),
})

DERIVED_METRIC_DEFINITIONS = globals().get("DERIVED_METRIC_DEFINITIONS", {})
DERIVED_METRIC_DEFINITIONS.setdefault("nha_o_kem", {"source_col": "tinh_trang_nha", "values": ("Nhà tạm", "Nhà đơn sơ"), "alias": "so_ho_nha_o_kem", "label": "Số hộ nhà ở kém"})
INTENT_TERM_CATALOG = {
    "multi_condition": (" và ", " hoặc ", " kèm ", " đồng thời "),
    "list": ("liệt kê", "danh sách", "tra cứu", "thông tin hộ", "chi tiết hộ"),
    "ratio": ("tỷ lệ", "tỷ trọng", "phần trăm", "%"),
}

UNSUPPORTED_INTENT_RULES = {
    "unsupported_policy_recommendation": {
        "patterns": (
            r"\b(?:de xuat|goi y|khuyen nghi|nen lam gi|nen uu tien gi)\b.{0,60}\b(?:chinh sach|giai phap|ho tro|xoa ngheo|giam ngheo)\b",
            r"\b(?:chinh sach|giai phap|cach nao|bien phap nao)\b.{0,60}\b(?:tot nhat|hieu qua nhat|xoa ngheo|giam ngheo)\b",
            r"\b(?:xoa ngheo|giam ngheo)\b.{0,60}\b(?:tot nhat|hieu qua nhat|nen lam gi|de xuat)\b",
        ),
        "answer": "Không thể khuyến nghị chính sách tốt nhất chỉ từ bộ dữ liệu này. Cần thêm mục tiêu chính sách, ngân sách, địa bàn ưu tiên và tiêu chí đánh giá.",
    },
    "unsupported_personal_ranking": {
        "patterns": (
            r"\b(?:ho nao|chu ho nao|gia dinh nao)\b.{0,50}\b(?:dang duoc ho tro nhat|duoc ho tro nhat|can ho tro nhat|can uu tien nhat|dang thuong nhat|kho nhat|nen giup nhat)\b",
            r"\b(?:xep hang|chon|tim)\b.{0,50}\b(?:ho|chu ho|gia dinh)\b.{0,50}\b(?:can ho tro|uu tien|dang giup)\b",
        ),
        "answer": "Không thể xếp hạng cá nhân/hộ nào đáng được hỗ trợ nhất nếu chưa có tiêu chí ưu tiên rõ ràng.",
    },
    "unsupported_attribution": {
        "patterns": (
            r"\b(?:loi cua ai|ai co loi|ai chiu trach nhiem|quy trach nhiem)\b",
            r"\b(?:ai|don vi nao|co quan nao|chinh quyen|can bo)\b.{0,40}\b(?:chiu trach nhiem|co loi|lam kem|quan ly kem|thieu trach nhiem)\b",
            r"\b(?:ngheo|ho ngheo|ngheo nhieu)\b.{0,50}\b(?:do ai|tai ai|vi ai|do quan ly kem|do lam kem|do chinh quyen|do can bo)\b",
            r"\b(?:chinh quyen|can bo|xa|huyen)\b.{0,50}\b(?:lam kem|quan ly kem|yeu kem|thieu trach nhiem)\b",
        ),
        "answer": "Không thể kết luận hoặc quy trách nhiệm cá nhân/tổ chức từ bộ dữ liệu thống kê này.",
    },
}

SENSITIVE_DATA_TERMS = (
    "dia chi cu the",
    "xuat danh sach dia chi",
    "thong tin dinh danh",
    "ma ho va thong tin dinh danh",
    "giay to tuy than",
    "cccd",
    "cmnd",
    "can cuoc",
    "so dien thoai",
)

RATIO_DENOMINATOR_TERMS = (
    "tổng số hộ nghèo",
    "tổng hộ nghèo",
    "tổng số hộ cận nghèo",
    "tổng hộ cận nghèo",
    "tổng số hộ không nghèo",
    "tổng hộ không nghèo",
    "tổng số hộ rà soát",
    "tổng hộ rà soát",
)

RATIO_FEATURE_COLS = {
    "th_nuoc_sach",
    "th_bhyt",
    "th_bhxh",
    "nhom_dtts",
    "nhom_chu_ho_nu",
    "co_tre_em",
    "nhom_tre_em_duoi6",
    "nhom_khuyet_tat",
    "nhom_cao_tuoi",
    "nhom_don_than",
}

COMPLEX_QUESTION_TERMS = (
    "huyện nào", "xã nào", "theo huyện", "theo xã", "từng huyện", "từng xã",
    "đứng đầu", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất",
    "xếp lại", "xếp hạng", "dẫn đầu", "top",
    "liệt kê", "danh sách", "tra cứu", "thông tin hộ", "chi tiết hộ",
    "so sánh", "đối chiếu", "chênh lệch", "biến động", "từ 2023 sang 2024",
    "bức tranh", "phân bố", "cơ cấu", "gom", "nhóm theo",
    "tỷ lệ", "tỷ trọng", "phần trăm",
    "tương ứng", "hai dạng", "hai loại", "lần lượt",
    "tạm bợ", "không vững chắc", "vừa", "đồng thời", "cùng lúc",
    "dân tộc nào", "theo dân tộc", "top dân tộc", "phổ biến nhất",
)

COMPLEX_QUESTION_KEY_TERMS = (
    "huyen nao", "xa nao", "theo huyen", "theo xa", "tung huyen", "tung xa",
    "dung dau", "cao nhat", "thap nhat", "nhieu nhat", "it nhat",
    "xep lai", "xep hang", "dan dau",
    "liet ke", "danh sach", "tra cuu", "thong tin ho", "chi tiet ho",
    "so sanh", "doi chieu", "chenh lech", "bien dong",
    "buc tranh", "phan bo", "co cau", "gom", "nhom theo",
    "ty le", "ty trong", "phan tram",
    "tuong ung", "hai dang", "hai loai", "lan luot",
    "tam bo", "khong vung chac", "vua", "dong thoi", "cung luc",
    "dan toc nao", "theo dan toc", "top dan toc", "pho bien nhat",
)

LLM_AUDIT_TERMS = (
    "thieu nuoc sach",
    "dan toc",
    "m'nong",
    "mnong",
    "tuy duc",
    "dak song",
    "cu jut",
    "dak mil",
    "dak rlap",
)

LLM_AUDIT_COLON_TERMS = (
    "ho tro",
    "co dien",
    "internet",
    "nha tieu",
    "thu nhap",
    "nhan khau",
    "binh quan",
    "tong ho",
    "chu ho nu",
    "tre em",
    "bhxh",
    "bhyt",
)

# ===== PATCH evalC_edge: alias cho nhiều giá trị trong cùng một cột =====
CATALOG_VALUE_ALIASES.setdefault("trinh_do_hoc_van_chu_ho", {}).update({
    "Tốt nghiệp THCS": ("thcs", "tot nghiep thcs", "trung hoc co so"),
    "Tốt nghiệp THPT": ("thpt", "tot nghiep thpt", "trung hoc pho thong"),
    "Tốt nghiệp tiểu học": ("tieu hoc", "tot nghiep tieu hoc"),
    "Chưa tốt nghiệp tiểu học": ("chua tot nghiep tieu hoc",),
    "Chưa biết đọc/viết": ("chua biet doc viet", "mu chu"),
    "Đại học trở lên": ("dai hoc", "dai hoc tro len"),
})

CATALOG_VALUE_ALIASES.setdefault("suc_khoe_chu_ho", {}).update({
    "Ốm đau mãn tính": ("om dau man tinh", "om dau", "benh man tinh"),
    "Khuyết tật": ("khuyet tat", "chu ho khuyet tat"),
    "Tàn tật nặng": ("tan tat nang",),
    "Bình thường": ("binh thuong",),
})

CATALOG_VALUE_ALIASES.setdefault("nguon_nuoc", {}).update({
    "Giếng đào hợp vệ sinh": ("gieng dao", "gieng dao hop ve sinh"),
    "Giếng khoan hợp vệ sinh": ("gieng khoan", "gieng khoan hop ve sinh"),
    "Nước máy/nước sạch tập trung": ("nuoc may", "nuoc sach tap trung", "nuoc may nuoc sach tap trung"),
    "Nước mua bình/bể": ("nuoc mua binh", "nuoc mua be", "mua binh", "mua be", "nuoc mua binh be"),
    "Nước mưa": ("nuoc troi",),
    "Nước suối/khe chưa qua xử lý": ("nuoc suoi", "nuoc khe", "nuoc suoi khe"),
})

# Cho ratio hiểu các text-column cũng là feature rõ ràng.
RATIO_FEATURE_COLS.update({
    "tinh_trang_nha",
    "nguon_nuoc",
    "suc_khoe_chu_ho",
    "trinh_do_hoc_van_chu_ho",
    "co_internet",
    "co_dien",
    "th_tai_san_tt",
    "th_vien_thong",
    "dan_toc_tai_cho",
})

RATIO_FEATURE_COLS.update(
    col for col, meta in FEATURE_CATALOG.items()
    if meta.get("kind") == "flag"
)

if "th_tai_san_tt" in FEATURE_CATALOG:
    FEATURE_CATALOG["th_tai_san_tt"]["aliases"] = list(dict.fromkeys(
        FEATURE_CATALOG["th_tai_san_tt"].get("aliases", [])
        + ["thiếu tài sản tiếp cận thông tin", "tài sản tiếp cận thông tin"]
    ))
    FEATURE_KEYWORDS["th_tai_san_tt"] = tuple(dict.fromkeys(
        (*FEATURE_KEYWORDS.get("th_tai_san_tt", ()), *FEATURE_CATALOG["th_tai_san_tt"]["aliases"])
    ))

# "ốm đau" trần thường là nguyên nhân nghèo nn_om_dau,
# không nên tự ép thành suc_khoe_chu_ho = "Ốm đau mãn tính".
SAME_COLUMN_CATALOG_CONTEXTS["suc_khoe_chu_ho"] = tuple(
    x for x in SAME_COLUMN_CATALOG_CONTEXTS.get("suc_khoe_chu_ho", ())
    if x != "om dau"
)

CATALOG_VALUE_ALIASES.setdefault("suc_khoe_chu_ho", {}).update({
    "Ốm đau mãn tính": ("om dau man tinh", "benh man tinh", "man tinh"),
    "Khuyết tật": ("khuyet tat", "chu ho khuyet tat"),
    "Tàn tật nặng": ("tan tat nang",),
    "Bình thường": ("binh thuong",),
})
