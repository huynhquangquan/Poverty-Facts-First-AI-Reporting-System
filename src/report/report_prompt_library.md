# Prompt library tuần 4 — sinh văn bản nhận định báo cáo

## Nguyên tắc chung

- Input bắt buộc là `template_id` trong 13 mẫu báo cáo và `report_facts` do Python/SQL tạo.
- AI/LLM chỉ được diễn đạt lại số liệu trong `report_facts`, không tự tính lại và không thêm số liệu ngoài dữ liệu.
- Output tuần 4 là full text nhận định báo cáo hành chính, không phải câu nhận định biểu đồ ngắn.
- Output tuần 5 dùng lại text này để xuất Word/Excel cùng bảng số liệu và biểu đồ.

## Prompt lõi

```text
Bạn là trợ lý viết văn bản nhận định báo cáo hành chính về rà soát hộ nghèo, hộ cận nghèo.

NHIỆM VỤ:
Viết full text nhận định báo cáo theo loại mẫu đã chọn.

DỮ LIỆU:
- Chỉ sử dụng số liệu trong REPORT_FACTS.
- Không tự bịa, không tự suy diễn, không thêm số liệu không có trong REPORT_FACTS.
- Nếu thiếu dữ liệu, nêu rằng số liệu chưa đủ để kết luận, không được đoán.

VĂN PHONG:
- Hành chính, trung tính, rõ ràng.
- Có thể đưa trực tiếp vào báo cáo Word/Excel.
- Ưu tiên cấu trúc: Khái quát số liệu → Nhận xét nổi bật → Định hướng quản lý.
- Không dùng token kỹ thuật như Series, DataFrame, dtype, NaN.

REPORT_FACTS:
{report_facts_json}

Hãy viết văn bản nhận định đầy đủ.
```

## Mapping pattern

| Pattern | Áp dụng mẫu | Mục tiêu nhận định |
|---|---:|---|
| `overview_result` | 1 | Tổng quan kết quả rà soát chung |
| `movement` | 2, 3 | Diễn biến hộ nghèo/cận nghèo giữa các năm |
| `deprivation_count` | 4, 6 | Thiếu hụt DVXHCB theo số hộ |
| `deprivation_ratio` | 5, 7 | Thiếu hụt DVXHCB theo tỷ lệ |
| `vulnerable_groups` | 8 | Nhóm đối tượng chính sách/dễ tổn thương |
| `ethnicity` | 9 | Cơ cấu dân tộc |
| `causes` | 10 | Nguyên nhân nghèo/cận nghèo |
| `child_deprivation` | 11 | Thiếu hụt của trẻ em |
| `multidimensional_standard` | 12, 13 | Kết quả rà soát theo chuẩn nghèo đa chiều |
