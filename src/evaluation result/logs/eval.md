## Phạm vi các bộ đánh giá

- **EvalA** (120 câu): Độ chính xác chức năng cốt lõi Count, filter, aggregate, ratio, group table, ranking, top-N, danh sách hộ, tra cứu hộ, so sánh năm và bảng nhiều chỉ tiêu.
- **EvalB** (80 câu): Độ bền và an toàn, Câu hỏi tự nhiên, không dấu, lỗi chính tả, cách diễn đạt đời thường; câu thiếu ngữ cảnh, đặc trưng mơ hồ, yêu cầu không hỗ trợ, dữ liệu cá nhân, tra cứu không tồn tại và kiểm soát câu trả lời an toàn.
- **EvalC Edge** (40 câu): Edge case và chống regression Nhiều giá trị cùng cột, điều kiện AND/OR, ranking theo hộ hoặc địa bàn, ratio theo nhóm, top-N, bảng nhiều metric, so sánh 2023–2024 và ngăn kết quả tra cứu bị mở rộng sai.

Bộ kiểm thử hiện tại đã bao phủ tốt các dạng truy vấn chính, nhưng chưa bao phủ toàn bộ đặc trưng trong DB. Trong 95 cột, còn 40 cột chưa xuất hiện trong plan kiểm thử, tương đương 42.1%. Nếu chỉ xét nhóm cột nghiệp vụ, còn thiếu 29/83 đặc trưng, tương đương 34.9%, tập trung ở các nhóm: địa bàn mở rộng, cây trồng chính, trẻ em, hỗ trợ chính sách, nhóm đối tượng chính sách và một số chỉ tiêu nhà ở. Đã bao phủ tốt các dạng truy vấn quan trọng của chatbot, gồm: đếm, tỷ lệ, trung bình/tổng, lọc một hoặc nhiều điều kiện, điều kiện OR, ranking, top N, bảng nhóm, bảng nhiều chỉ tiêu, so sánh năm, danh sách hộ, tra cứu hộ và xử lý câu hỏi mơ hồ. Về đặc trưng dữ liệu, bộ eval đã cover khoảng 55/95 cột DB, tương đương 57.9%; nếu chỉ tính cột nghiệp vụ thì cover khoảng 54/83 đặc trưng, tương đương 65.1%.

### EvalA — Core Accuracy

Đánh giá pipeline có hiểu và thực thi đúng các nghiệp vụ Q&A phổ biến hay không:
Total: 120 | Passed: 120 | Failed: 0 | Accuracy: 100.0%
- Đếm tổng và đếm theo một hoặc nhiều điều kiện.
- Tính tổng, trung bình và tỷ lệ.
- Thống kê theo huyện, xã, dân tộc hoặc đặc trưng.
- Ranking, top-N và vị trí xếp hạng.
- Liệt kê bản ghi và tra cứu chủ hộ.
- So sánh giữa năm 2023 và 2024.
- Sinh bảng nhiều chỉ tiêu.
- Đối chiếu kết quả, cột dữ liệu và giá trị trong answer với SQL ground truth.

### EvalB — Robustness & Safety
Total: 80 | Passed: 79 | Failed: 1 | Accuracy: 98.75%
Đánh giá khả năng xử lý đầu vào không chuẩn và các tình huống cần từ chối hoặc hỏi lại:

- Câu hỏi tiếng Việt tự nhiên, cách nói đời thường.
- Câu không dấu hoặc có lỗi chính tả.
- Câu hỏi thiếu năm, địa bàn, nhóm hộ hoặc chỉ tiêu.
- Khái niệm mơ hồ như “thiếu giáo dục”, “thiếu nhà”, “thiếu thông tin”.
- Yêu cầu chủ quan hoặc ngoài phạm vi dữ liệu.
- Yêu cầu dữ liệu cá nhân như CCCD hoặc số điện thoại.
- Tra cứu hộ không tồn tại.
- Không được trả kết quả quá rộng khi chưa đủ điều kiện.
- Không được phát sinh lỗi nội bộ hoặc bịa số liệu.

### EvalC Edge — Edge Cases & Regression
evalC_edge: 40/40 passed, failed=0, accuracy=100.0%
Bổ sung những pattern phức tạp hoặc còn ít được bao phủ trong EvalA và EvalB:

- Nhiều giá trị của cùng một cột bằng `IN`.
- Điều kiện kết hợp `AND` và `OR`.
- Nhiều nhóm phân loại trong cùng câu hỏi.
- Ratio theo huyện/xã với mẫu số đúng từng nhóm.
- Ranking một kết quả tốt nhất hoặc top-N.
- Phân biệt ranking hộ với ranking địa bàn.
- Ranking theo thu nhập, nhân khẩu, trẻ em và các metric số.
- Bảng nhiều metric, kể cả khi có điều kiện địa bàn.
- So sánh nhiều nhóm giữa năm 2023 và 2024.
- Tìm địa bàn có mức tăng/giảm lớn nhất.
- Đảm bảo lookup không trả danh sách rộng khi không tìm thấy người.
- Dùng như bộ regression sau mỗi lần sửa parser, executor hoặc formatter.
