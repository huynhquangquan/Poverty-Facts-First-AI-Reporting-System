# Tổng hợp prompt và văn bản báo cáo nhận định từ số liệu thống kê – 12 mẫu

> Quy ước: 12 mẫu Excel là biểu mẫu/bảng số liệu thống kê. Phần LLM sinh ra được gọi là văn bản báo cáo nhận định từ số liệu thống kê. Nội dung tập trung vào nhận định mô tả có kiểm soát: tổng hợp, so sánh, xếp hạng, chỉ ra nhóm hoặc địa bàn nổi bật và đối chiếu với bảng số liệu trước khi chấp nhận.
>
> Bản này đã được rà lại theo chuẩn project hiện tại: số liệu được tính trước, phần nhận định chỉ diễn đạt từ bảng đã kiểm soát; các mẫu có chỉ tiêu hoặc nhóm có thể chồng lấn đều không cộng thành cơ cấu 100%.
>
> Văn bản nhận định (Mục III): độ chính xác số liệu 90–100% (facts-first, tính bằng Python/SQL); khả năng tổng hợp/diễn giải của LLM (Qwen 2.5 3B) đạt ~60% so với văn phong hành chính chuẩn, hiện dừng ở liệt kê số liệu, chưa có so sánh/xếp hạng tự động do giới hạn năng lực suy luận của mô hình 3B.

## Prompt khung dùng chung

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.
```

---

## Mẫu 1 – Tổng hợp kết quả rà soát HC, CN, NL, NN có mức sống trung bình

**Nhóm nội dung:** Kết quả rà soát chung.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định mẫu 1 theo đúng ba nhóm chỉ tiêu của biểu mẫu: hộ nghèo, hộ cận nghèo và hộ nông, lâm, ngư nghiệp có mức sống trung bình. Không đưa hộ không nghèo vào nhận định mẫu 1. Nếu nhóm hộ nông, lâm, ngư nghiệp có mức sống trung bình bằng 0 thì ghi 0 hộ theo bảng tổng hợp hiện có, không kết luận ngoài phạm vi dữ liệu và không suy diễn hiệu quả chính sách.
```

### Văn bản báo cáo nhận định

```text
Trong phạm vi dữ liệu rà soát/phân loại năm 2024, toàn tỉnh ghi nhận 2.447 hộ nghèo, 3.691 hộ cận nghèo và 0 hộ nông, lâm, ngư nghiệp có mức sống trung bình. Nội dung nhận định chỉ đối chiếu ba nhóm chỉ tiêu này, không đưa nhóm hộ không nghèo vào mẫu 1.

Tuy Đức cao nhất về hộ nghèo với 829 hộ; Đăk Glong 538 hộ; Đắk Song 279 hộ. Về hộ cận nghèo, Tuy Đức đứng đầu với 917 hộ; Krông Nô 588 hộ; Đắk Song 510 hộ.

Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình giữ bằng 0 hộ theo bảng, không kết luận ngoài phạm vi dữ liệu.
```

**Hậu kiểm:** ĐẠT — nội dung bám đúng phạm vi ba nhóm chỉ tiêu của bảng số liệu.

**Nhược điểm / điểm cần cải thiện:** Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình đang bằng 0 theo bảng nên phần nhận định còn thiên về đối chiếu phạm vi mẫu, chưa phân tích sâu được nhóm này.

---

## Mẫu 2 – Tổng hợp diễn biến hộ nghèo

**Nhóm nội dung:** Diễn biến hộ nghèo.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định diễn biến hộ nghèo theo thứ tự: đầu kỳ, nhóm giảm, nhóm tăng, cuối kỳ và chênh lệch. Chỉ dùng nhãn biến động có trong facts. Không residual-fill nhóm khác. Không dùng lý do chết/chuyển đi/tách/nhập nếu nguồn không có cột lý do chi tiết. Giữ đúng chiều: thoát nghèo là nhóm giảm hộ nghèo; cận nghèo trở thành hộ nghèo, tái nghèo, nghèo mới là nhóm tăng hộ nghèo.
```

### Văn bản báo cáo nhận định

```text
Trong kỳ rà soát năm 2024, số hộ nghèo đầu kỳ là 1.796 hộ, cuối kỳ là 2.447 hộ, tăng 651 hộ, tương ứng 36,25%. Kết quả này phản ánh biến động của nhóm hộ nghèo trong phạm vi số liệu đã tổng hợp.

Các nhóm làm giảm quy mô hộ nghèo gồm thoát nghèo trở thành hộ cận nghèo với 634 hộ, thoát nghèo vượt chuẩn với 104 hộ và nhóm giảm khác 0 hộ. Các nhóm làm tăng quy mô hộ nghèo gồm cận nghèo trở thành hộ nghèo với 1.105 hộ, tái nghèo với 161 hộ, nghèo mới phát sinh với 123 hộ và nhóm tăng khác 0 hộ.

Theo địa bàn, Đăk Glong ghi nhận mức tăng 231 hộ nghèo và có tỷ lệ biến động tăng 75,24%. Tổng cuối kỳ theo nhóm phân loại hiện tại là 2.447 hộ, khớp với kết quả tổng hợp. Nhóm giảm khác và tăng khác đều ghi nhận 0 hộ, trong khi biến động chủ yếu tập trung ở các nhãn đã nêu.
```

**Hậu kiểm:** ĐẠT — số đầu kỳ, cuối kỳ và các nhóm biến động được trình bày đúng theo bảng.

**Nhược điểm / điểm cần cải thiện:** Văn bản mới mô tả biến động đầu kỳ - cuối kỳ và các nhóm tăng/giảm, nhưng chưa giải thích sâu nguyên nhân vì nguồn dữ liệu không có cột lý do chi tiết cho nhóm biến động khác.

---

## Mẫu 3 – Tổng hợp diễn biến hộ cận nghèo

**Nhóm nội dung:** Diễn biến hộ cận nghèo.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định diễn biến hộ cận nghèo theo thứ tự: đầu kỳ, nhóm giảm, nhóm tăng, cuối kỳ và chênh lệch. Giữ đúng chiều: thoát nghèo sang cận nghèo là nhóm tăng cận nghèo; cận nghèo trở thành hộ nghèo và thoát cận nghèo vượt chuẩn là nhóm giảm cận nghèo. Không gọi chênh lệch tăng kỳ là phần chưa giải thích nếu unexplained_delta bằng 0.
```

### Văn bản báo cáo nhận định

```text
Trong kỳ rà soát năm 2024, số hộ cận nghèo đầu kỳ là 3.402 hộ, cuối kỳ là 3.691 hộ, tăng 289 hộ, tương ứng 8,50%. Kết quả này phản ánh biến động của nhóm hộ cận nghèo trong phạm vi số liệu đã tổng hợp.

Các nhóm làm giảm quy mô hộ cận nghèo gồm thoát cận nghèo vượt chuẩn với 134 hộ, cận nghèo trở thành hộ nghèo với 1.105 hộ và nhóm giảm khác 0 hộ. Các nhóm làm tăng quy mô hộ cận nghèo gồm thoát nghèo trở thành hộ cận nghèo với 634 hộ, tái cận nghèo với 440 hộ, cận nghèo mới phát sinh với 454 hộ và nhóm tăng khác 0 hộ.

Theo địa bàn, Đăk Glong ghi nhận mức giảm 157 hộ cận nghèo; Cư Jút có tỷ lệ biến động tăng 32,17%. Tổng cuối kỳ theo nhóm phân loại hiện tại là 3.691 hộ, khớp với kết quả tổng hợp. Nhóm giảm khác và tăng khác đều ghi nhận 0 hộ, trong khi biến động chủ yếu tập trung ở các nhãn đã nêu.
```

**Hậu kiểm:** ĐẠT — diễn biến hộ cận nghèo được trình bày đúng chiều tăng, giảm theo bảng.

**Nhược điểm / điểm cần cải thiện:** Mẫu này dễ bị nhầm chiều tăng/giảm giữa các nhãn biến động, nên cần hậu kiểm chặt hơn khi LLM diễn đạt các cụm như thoát nghèo sang cận nghèo, tái cận nghèo hoặc cận nghèo trở thành hộ nghèo.

---

## Mẫu 4 – Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo

**Nhóm nội dung:** Thiếu hụt dịch vụ xã hội cơ bản hộ nghèo – số lượng.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định theo số hộ nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản. Không chuyển trọng tâm sang tỷ lệ. Không cộng số lượt thiếu hụt thành số hộ duy nhất vì một hộ có thể thiếu nhiều chỉ số.
```

### Văn bản báo cáo nhận định

```text
Xét theo số hộ nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản năm 2024, ba chỉ số có quy mô thiếu hụt lớn nhất là Chất lượng nhà ở với 1.945 hộ, Bảo hiểm xã hội với 1.876 hộ và Nhà tiêu hợp vệ sinh với 1.825 hộ.

Những số liệu này phản ánh quy mô hộ nghèo đang thiếu từng chỉ số, nên trọng tâm của mẫu 4 là số hộ thiếu hụt. Tỷ lệ nếu được nhắc chỉ có vai trò đối chiếu phụ, không thay thế cho xếp hạng theo số hộ.

Các chỉ số thiếu hụt có thể chồng lấn trên cùng một hộ. Vì vậy, không cộng số hộ của các chỉ số thành tổng hộ nghèo riêng biệt và không diễn giải thành cơ cấu 100%.
```

**Hậu kiểm:** ĐẠT — số hộ thiếu hụt được trình bày đúng theo từng chỉ tiêu.

**Nhược điểm / điểm cần cải thiện:** Nhận định chủ yếu nêu ba chỉ số có số hộ thiếu hụt lớn nhất, chưa phân tích được mức độ thiếu hụt theo địa bàn vì bảng hiện tập trung theo chỉ tiêu.

---

## Mẫu 5 – Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo

**Nhóm nội dung:** Thiếu hụt dịch vụ xã hội cơ bản hộ nghèo – tỷ lệ.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định theo tỷ lệ phần trăm hộ nghèo thiếu từng chỉ số. Giữ đơn vị %, không biến tỷ lệ thành số hộ nếu không nêu rõ. Không cộng các tỷ lệ thành 100% vì các chỉ số có thể chồng lấn.
```

### Văn bản báo cáo nhận định

```text
Xét theo tỷ lệ hộ nghèo thiếu từng chỉ số năm 2024, Chất lượng nhà ở là chỉ số có tỷ lệ thiếu hụt cao nhất với 79,49%, tương ứng 1.945 hộ. Tiếp theo là Bảo hiểm xã hội với 76,67%, tương ứng 1.876 hộ, và Nhà tiêu hợp vệ sinh với 74,58%, tương ứng 1.825 hộ.

Trọng tâm của mẫu 5 là tỷ lệ phần trăm, vì vậy các chỉ số được xếp theo mức độ phổ biến của thiếu hụt trong nhóm hộ nghèo. Số hộ đi kèm chỉ dùng để đối chiếu quy mô, không làm thay đổi trọng tâm tỷ lệ.

Các tỷ lệ thiếu hụt của từng chỉ số là các tỷ lệ độc lập và có thể chồng lấn trên cùng một hộ. Do đó, không cộng các tỷ lệ này thành 100% và không diễn giải như cơ cấu loại trừ nhau.
```

**Hậu kiểm:** ĐẠT — tỷ lệ thiếu hụt được trình bày đúng theo từng chỉ tiêu.

**Nhược điểm / điểm cần cải thiện:** Văn bản đã tách đúng trọng tâm tỷ lệ, nhưng vẫn cần đi kèm số hộ đối chiếu để người đọc không hiểu tỷ lệ cao đồng nghĩa quy mô tuyệt đối luôn cao ở mọi địa bàn.

---

## Mẫu 6 – Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo

**Nhóm nội dung:** Thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo – số lượng.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định theo số hộ cận nghèo thiếu từng chỉ số. Nêu rõ đối tượng là hộ cận nghèo. Không dùng số hộ nghèo, không chuyển sang tỷ lệ nếu mẫu đang là số lượng. Nhắc rằng chỉ số có thể chồng lấn.
```

### Văn bản báo cáo nhận định

```text
Xét theo số hộ cận nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản năm 2024, Chất lượng nhà ở ghi nhận quy mô thiếu hụt lớn nhất với 2.320 hộ. Hai chỉ số tiếp theo là Nhà tiêu hợp vệ sinh với 2.059 hộ và Bảo hiểm xã hội với 1.947 hộ.

Các số liệu trên được diễn giải theo số hộ cận nghèo, không chuyển trọng tâm sang tỷ lệ và không dùng số hộ nghèo thay cho hộ cận nghèo. Khi cần đối chiếu với biểu đồ, thứ tự nhận định vẫn bám vào quy mô hộ thiếu hụt.

Một hộ cận nghèo có thể thiếu nhiều chỉ số cùng lúc, nên không cộng các chỉ số thành tổng hộ riêng biệt và không xem các chỉ số là các nhóm loại trừ nhau.
```

**Hậu kiểm:** ĐẠT — số hộ cận nghèo thiếu hụt được trình bày đúng theo từng chỉ tiêu.

**Nhược điểm / điểm cần cải thiện:** Nội dung còn thiên về liệt kê các chỉ số thiếu hụt lớn nhất của hộ cận nghèo, chưa chỉ ra được khác biệt theo địa bàn hoặc nguyên nhân phát sinh thiếu hụt.

---

## Mẫu 7 – Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo

**Nhóm nội dung:** Thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo – tỷ lệ.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định theo tỷ lệ phần trăm hộ cận nghèo thiếu từng chỉ số. Không nhầm mẫu số với hộ nghèo. Không gọi tỷ lệ thấp/cao nếu không đúng số học. Nhắc rằng các tỷ lệ là độc lập, không cộng thành 100%.
```

### Văn bản báo cáo nhận định

```text
Xét theo tỷ lệ hộ cận nghèo thiếu từng chỉ số năm 2024, Chất lượng nhà ở có tỷ lệ thiếu hụt cao nhất với 62,86%. Tiếp theo là Nhà tiêu hợp vệ sinh với 55,78% và Bảo hiểm xã hội với 52,75%.

Nội dung nhận định của mẫu 7 ưu tiên tỷ lệ phần trăm, không chuyển trọng tâm sang số hộ tuyệt đối. Nếu cần đối chiếu quy mô, số hộ chỉ được dùng như thông tin phụ và phải giữ đúng đối tượng là hộ cận nghèo.

Các tỷ lệ thiếu hụt theo chỉ số có thể chồng lấn, vì cùng một hộ cận nghèo có thể thiếu nhiều chỉ số. Do đó, không cộng các tỷ lệ thành cơ cấu 100% và không diễn giải như các nhóm loại trừ nhau.
```

**Hậu kiểm:** ĐẠT — tỷ lệ thiếu hụt của hộ cận nghèo được trình bày đúng theo từng chỉ tiêu.

**Nhược điểm / điểm cần cải thiện:** Mẫu tỷ lệ giúp thấy mức phổ biến của thiếu hụt, nhưng nếu chỉ nhìn phần trăm thì có thể thiếu bối cảnh về quy mô số hộ thực tế; vì vậy cần đối chiếu thêm với mẫu số lượng khi trình bày.

---

## Mẫu 8 – Phân tích hộ nghèo, hộ cận nghèo theo các nhóm đối tượng

**Nhóm nội dung:** Nhóm đối tượng theo địa bàn.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định mẫu 8 theo địa bàn, tách hộ nghèo và hộ cận nghèo trong ba nhóm đúng của biểu mẫu: hộ dân tộc thiểu số, hộ không có khả năng lao động và hộ có người có công với cách mạng. Không đưa các nhóm ngoài biểu mẫu vào nhận định. Không cộng các nhóm thành 100% vì một hộ có thể đồng thời thuộc nhiều nhóm.
```

### Văn bản báo cáo nhận định

```text
Trong toàn tỉnh năm 2024, mẫu 8 tổng hợp hộ nghèo và hộ cận nghèo theo địa bàn đối với ba nhóm chính: dân tộc thiểu số, không có khả năng lao động và có người có công với cách mạng. Toàn tỉnh ghi nhận 1.403 hộ nghèo DTTS và 2.039 hộ cận nghèo DTTS; nhóm không có khả năng lao động có 80 hộ nghèo và 76 hộ cận nghèo; nhóm có người có công với cách mạng có 94 hộ nghèo và 99 hộ cận nghèo.

Theo địa bàn, Tuy Đức là địa bàn nổi bật ở nhóm DTTS với 522 hộ nghèo DTTS và 556 hộ cận nghèo DTTS. Tuy Đức cũng ghi nhận 34 hộ nghèo không có khả năng lao động và 34 hộ nghèo có người có công với cách mạng. Đăk Glong đứng tiếp theo ở nhóm hộ nghèo DTTS với 328 hộ, còn Đắk Song có 267 hộ cận nghèo DTTS.

Ba nhóm đối tượng trong mẫu 8 có thể chồng lấn, vì một hộ có thể vừa thuộc nhóm DTTS vừa thuộc nhóm không có khả năng lao động hoặc có người có công. Vì vậy, các nhóm được dùng để nhận diện trọng tâm theo dõi, không cộng thành tổng loại trừ nhau và không diễn giải thành cơ cấu 100%.
```

**Hậu kiểm:** ĐẠT — nội dung bám đúng ba nhóm đối tượng của bảng theo từng địa bàn.

**Nhược điểm / điểm cần cải thiện:** Mẫu 8 có cấu trúc phức tạp vì vừa theo địa bàn vừa tách hộ nghèo/hộ cận nghèo trong ba nhóm đối tượng; LLM dễ đưa nhầm nhóm ngoài biểu mẫu nếu prompt và facts không khóa chặt.

---

## Mẫu 9 – Phân tích hộ nghèo, hộ cận nghèo theo dân tộc

**Nhóm nội dung:** Dân tộc.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định cơ cấu hộ nghèo/cận nghèo theo dân tộc. Tách Kinh, DTTS và dân tộc chi tiết. Không suy diễn nguyên nhân nghèo theo dân tộc, không viết định kiến và không đưa kết luận chính sách nếu bảng chỉ có cơ cấu số hộ.
```

### Văn bản báo cáo nhận định

```text
Trong toàn tỉnh năm 2024, cơ cấu hộ nghèo và hộ cận nghèo theo dân tộc cho thấy nhóm Kinh có quy mô lớn nhất ở cả hai nhóm hộ. Đối với hộ nghèo, dân tộc Kinh ghi nhận 1.044 hộ, tương ứng 42,66%; tiếp theo là M'Nông với 345 hộ và Ê-đê với 187 hộ.

Đối với hộ cận nghèo, dân tộc Kinh ghi nhận 1.652 hộ, tương ứng 44,76%; tiếp theo là M'Nông với 530 hộ và Ê-đê với 336 hộ. Các số liệu này chỉ mô tả cơ cấu theo dân tộc trong phạm vi bảng thống kê.

Khi diễn giải mẫu 9, cần tách rõ hộ nghèo và hộ cận nghèo, không dùng số của nhóm này cho nhóm kia. Phần dân tộc chỉ là đặc điểm thống kê của hộ trong dữ liệu, không được dùng để kết luận nguyên nhân nghèo hoặc đưa ra nhận định định kiến về bất kỳ nhóm dân tộc nào.
```

**Hậu kiểm:** ĐẠT — số liệu theo dân tộc được trình bày đúng cho hộ nghèo và hộ cận nghèo.

**Nhược điểm / điểm cần cải thiện:** Phần dân tộc chỉ cho biết cơ cấu số hộ theo nhóm dân tộc, không đủ căn cứ để phân tích nguyên nhân nghèo; văn bản cần tránh mọi diễn giải có tính định kiến hoặc suy diễn chính sách.

---

## Mẫu 10 – Phân tích hộ nghèo, hộ cận nghèo theo nguyên nhân nghèo

**Nhóm nội dung:** Nguyên nhân nghèo/cận nghèo.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định nguyên nhân nghèo cho hai nhóm hộ nghèo và hộ cận nghèo. Mỗi nhóm phải giữ riêng số hộ và tỷ lệ. Không đặt số hộ cận nghèo trong ngữ cảnh hộ nghèo. Nhắc rõ nguyên nhân có thể đồng thời xuất hiện ở cùng một hộ, không cộng thành cơ cấu 100% và không kết luận nguyên nhân duy nhất.
```

### Văn bản báo cáo nhận định

```text
Trong toàn tỉnh năm 2024, nhóm nguyên nhân nghèo được tổng hợp riêng cho hộ nghèo và hộ cận nghèo, vì cùng một nguyên nhân có thể xuất hiện với quy mô khác nhau ở từng nhóm hộ.

Đối với hộ nghèo, thiếu vốn sản xuất/kinh doanh ghi nhận 1.399 hộ, tương ứng 57,17%. Trong nhóm hộ nghèo, thiếu lao động ghi nhận 1.197 hộ, tương ứng 48,92%. Trong nhóm hộ nghèo, ốm đau, bệnh nặng, tai nạn ghi nhận 1.180 hộ, tương ứng 48,22%.

Đối với hộ cận nghèo, thiếu vốn sản xuất/kinh doanh ghi nhận 1.419 hộ, tương ứng 38,44%. Trong nhóm hộ cận nghèo, ốm đau, bệnh nặng, tai nạn ghi nhận 1.384 hộ, tương ứng 37,50%. Trong nhóm hộ cận nghèo, thiếu lao động ghi nhận 1.218 hộ, tương ứng 33,00%.

Các nguyên nhân trong bảng có thể đồng thời xuất hiện ở cùng một hộ, nên không cộng các nguyên nhân thành một cơ cấu chung và không kết luận một nguyên nhân duy nhất cho từng nhóm hộ.
```

**Hậu kiểm:** ĐẠT — nguyên nhân được trình bày riêng cho hộ nghèo và hộ cận nghèo.

**Nhược điểm / điểm cần cải thiện:** Các nguyên nhân có thể xuất hiện đồng thời ở cùng một hộ nên nhận định chỉ dừng ở mức thống kê nhóm nguyên nhân nổi bật, chưa thể kết luận nguyên nhân duy nhất hay mức độ tác động thực tế.

---

## Mẫu 11 – Tổng hợp chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo, hộ cận nghèo

**Nhóm nội dung:** Thiếu hụt của trẻ em.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định theo đơn vị số trẻ và tỷ lệ tương ứng. Mỗi câu chỉ chứa một nhóm hộ, một chỉ tiêu và một cặp số trẻ + tỷ lệ. Không gọi số trẻ là tỷ lệ, không gọi số trẻ là số hộ. Tách rõ trẻ em thuộc hộ nghèo và trẻ em thuộc hộ cận nghèo.
```

### Văn bản báo cáo nhận định

```text
Trong toàn tỉnh năm 2024, mẫu 11 phân tích số trẻ thiếu chỉ tiêu và tỷ lệ tương ứng trong từng nhóm trẻ em thuộc hộ nghèo, hộ cận nghèo.

Trẻ em thuộc hộ nghèo: thiếu tình trạng đi học 657 trẻ, 24,49%; thiếu bảo hiểm y tế 572 trẻ, 21,32%; thiếu dinh dưỡng 511 trẻ, 19,05%.

Trẻ em thuộc hộ cận nghèo: thiếu tình trạng đi học 501 trẻ, 13,33%; thiếu bảo hiểm y tế 484 trẻ, 12,88%; thiếu dinh dưỡng 385 trẻ, 10,24%.
```

**Hậu kiểm:** ĐẠT — số trẻ và tỷ lệ được trình bày đúng theo từng chỉ tiêu.

**Nhược điểm / điểm cần cải thiện:** Mẫu 11 dễ nhầm đơn vị giữa số trẻ, tỷ lệ trẻ và số hộ; ngoài ra bảng chỉ có ba chỉ tiêu chính nên phần nhận định còn ngắn và chưa phân tích được theo địa bàn.

---

## Mẫu 12 – Tổng hợp kết quả rà soát hộ nghèo theo chuẩn đa chiều

**Nhóm nội dung:** Kết quả rà soát hộ nghèo đa chiều.

### Prompt tối ưu cho mẫu này

```text
Bạn là trợ lý viết văn bản báo cáo nhận định từ số liệu thống kê từ số liệu đã được Python/SQL tính sẵn. Chỉ được dùng số liệu trong REPORT_FACTS và bảng nguồn đã kiểm soát. Không tự tính thêm số, không bịa nguyên nhân, không đổi đơn vị, không dùng số của nhóm này cho nhóm khác. Văn bản phải là văn bản báo cáo nhận định từ số liệu, không lộ token kỹ thuật như prompt, validator, fact pack, DB, SQL, cột A/B. Nếu có cảnh báo phạm vi dữ liệu, diễn đạt thành câu nghiệp vụ ngắn và không biến thành hướng dẫn người viết báo cáo.

Viết nhận định kết quả rà soát hộ nghèo theo chuẩn đa chiều năm 2024. Bắt buộc nêu và phân biệt rõ tổng hộ đã rà soát/phân loại, số hộ nghèo, nhân khẩu thuộc hộ nghèo, tỷ lệ hộ nghèo, cơ cấu hộ nghèo theo dân tộc Kinh, DTTS, DTTS tại chỗ, tỷ lệ hộ nghèo trong nhóm DTTS và tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ. Tỷ lệ phải đi cùng đúng mẫu số của chỉ tiêu; không dùng số hộ nghèo làm mẫu số, không gọi đây là tỷ lệ nghèo chính thức trên toàn bộ dân cư nếu nguồn không có bảng dân cư độc lập. Không suy diễn nguyên nhân nghèo theo dân tộc, không kết luận chính sách ngoài phạm vi bảng số liệu.
```

### Văn bản báo cáo nhận định

```text
Toàn tỉnh ghi nhận 2.447 hộ nghèo đa chiều trên 7.488 hộ, tỷ lệ 32,68%; nhân khẩu hộ nghèo là 11.247/34.110 người.

Tuy Đức: 829/1.917 hộ, tỷ lệ 43,24%; Đăk Glong: 538/1.553 hộ, tỷ lệ 34,64%; Cư Jút: 204/598 hộ, tỷ lệ 34,11%; Đắk Song: 279/930 hộ, tỷ lệ 30,00%.

Dân tộc: 1.044 hộ nghèo Kinh, 1.403 hộ nghèo DTTS, trong đó 703 hộ nghèo DTTS tại chỗ. Tỷ lệ dân tộc: 1.403/4.195 = 33,44%; 703/2.027 = 34,68%.
```

**Hậu kiểm:** ĐẠT — các tỷ lệ theo hộ nghèo và nhóm dân tộc được đối chiếu đúng với bảng số liệu.

**Nhược điểm / điểm cần cải thiện:** Mẫu 12 có nhiều mẫu số khác nhau như tổng hộ rà soát, tổng hộ DTTS và tổng hộ DTTS tại chỗ, nên dễ nhầm tỷ lệ nếu không đặt đúng tử số và mẫu số trong cùng câu.

---
