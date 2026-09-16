# Chatbot hộ nghèo và báo cáo hành chính

Đây là project Streamlit dùng để hỏi đáp dữ liệu hộ nghèo, hộ cận nghèo và sinh báo cáo hành chính từ cơ sở dữ liệu `poverty.db`. Ứng dụng dùng nguyên tắc facts-first: Python/SQL chịu trách nhiệm tính toán số liệu, phần LLM nếu được bật chỉ hỗ trợ diễn giải văn bản dựa trên facts đã kiểm soát.

## 1. Cấu trúc thư mục

```text
HuynhQuangQuan_sourcecode/
├── app.py                    # Ứng dụng Streamlit chính
├── app.bat                   # Chạy nhanh app trên Windows
├── requirements.txt          # Danh sách thư viện cần cài
├── run_data_pipeline.py      # Chạy pipeline dữ liệu đầy đủ
├── processing_data.py        # Làm sạch dữ liệu nguồn
├── feature_engineering.py    # Tạo dữ liệu enriched và biến đặc trưng
├── build_db.py               # Sinh SQLite database db/poverty.db
├── validate_db.py            # Kiểm tra database và logic mẫu
├── chart_utils.py            # Xử lý biểu đồ và xuất bảng Q&A
├── db/
│   └── poverty.db            # Database chính, app đọc trực tiếp file này
├── data/
│   ├── raw/                  # File Excel nguồn
│   ├── cleaned/              # Dữ liệu sau làm sạch
│   ├── enriched/             # Dữ liệu sau feature engineering
│   ├── audit/                # File audit dữ liệu
│   └── report_samples/       # 12 mẫu Excel báo cáo + file văn phong .md
├── core/                     # Query plan, executor, formatter, catalog
├── poverty_chatbot/          # Cấu hình, orchestrator, query planner
├── report/                   # Tạo facts, văn bản, Word/Excel báo cáo
└── .streamlit/
    └── config.toml           # Cấu hình giao diện Streamlit
```

Folder `logs/` không bắt buộc có sẵn. Khi chạy app hoặc chạy đánh giá báo cáo, chương trình sẽ tự tạo log mới nếu cần.

## 2. Yêu cầu môi trường

- Python 3.11 trở lên.
- Windows PowerShell hoặc Command Prompt.
- Ollama

### Cài đặt Ollama (tùy chọn)

1. Tải và cài Ollama từ: https://ollama.com/download
2. Khởi động Ollama.
3. Tải model mặc định:

```powershell
ollama pull qwen2.5:3b-instruct
```

4. Kiểm tra:

```powershell
ollama list
```

Nếu chưa chạy dịch vụ:

```powershell
ollama serve
```

Model mặc định được khai báo trong `poverty_chatbot/config.py`:


```python
MODEL_NAME = "qwen2.5:3b-instruct"
OLLAMA_URL = "http://localhost:11434/api/chat"
```

## 3. Cài đặt

Mở terminal tại thư mục `HuynhQuangQuan_sourcecode`, sau đó chạy:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Chạy ứng dụng

Cách nhanh trên Windows:

```powershell
.\app.bat
```

Hoặc chạy thủ công:

```powershell
.\.venv\Scripts\activate
python -m streamlit run app.py
```

Sau khi chạy, mở trình duyệt tại:

```text
http://localhost:8501
```

## 5. Chức năng chính

- Hỏi đáp dữ liệu hộ nghèo, hộ cận nghèo từ `db/poverty.db`.
- Lập bảng kết quả truy vấn và biểu đồ tương ứng.
- Xuất bảng Q&A ra Excel/CSV khi phù hợp.
- Sinh nhận định báo cáo hành chính theo facts từ DB.
- Xuất báo cáo Word `.docx`.
- Xuất Excel báo cáo theo mẫu gốc.
- Có chế độ Excel LLM mapping cho thử nghiệm/debug.

## 6. Dữ liệu và database

App mặc định đọc:

```text
db/poverty.db
```

Đường dẫn database được cấu hình tương đối theo thư mục project, nên có thể đổi tên hoặc di chuyển toàn bộ folder `HuynhQuangQuan_sourcecode` mà không cần sửa code, tuy nhiên sẽ cần tạo môi trường ảo .venv mới mỗi lần di chuyển.

Database hiện có sẵn để chạy app ngay. Nếu muốn tái tạo database từ dữ liệu Excel nguồn:

```powershell
.\.venv\Scripts\activate
python run_data_pipeline.py
```

Pipeline đầy đủ:

```text
processing_data.py -> feature_engineering.py -> build_db.py -> validate_db.py
```

## 7. Báo cáo hành chính

Các file xử lý báo cáo nằm trong `report/`:

- `report_fact_builder.py`: tạo fact pack từ database.
- `report_writer.py`: sinh văn bản nhận định.
- `report_exporter.py`: xuất Word/Excel hành chính.
- `template_excel_exporter.py`: điền số liệu vào Excel mẫu thường.
- `template_excel_llm_exporter.py`: Excel mapping có hỗ trợ LLM, dùng cho experimental/debug.
- `report_style_trainer.py`: tạo profile văn phong từ các mẫu hiện có.
- `report_style_profile.json`: profile văn phong đã sinh sẵn.

Thư mục `data/report_samples/` hiện có 12 mẫu Excel đầu và `report_style_examples.md`.

## 8. Log và file sinh ra khi chạy

Các file log khi chạy, app có thể tự tạo:

```text
logs/report_task_YYYYMMDD.jsonl
logs/qa_chat_YYYYMMDD.jsonl
logs/report_eval/report_eval_*.jsonl
logs/report_eval/report_eval_*_summary.csv
logs/report_eval/report_eval_*_summary.md
logs/report_eval/report_eval_*_failures.jsonl
```

## 9. Kiểm tra nhanh sau khi copy sang máy khác

Tại thư mục project:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -c "import app; print('import app ok')"
python -m streamlit run app.py
```

Kiểm tra database:

```powershell
python -c "import sqlite3; c=sqlite3.connect('db/poverty.db'); print(c.execute('select count(*) from ho_ngheo').fetchone()[0]); c.close()"
```

Nếu app import được, Streamlit mở tại `localhost:8501`, và database trả về số dòng thì project đã sẵn sàng chạy.
