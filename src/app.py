"""
Ứng dụng Streamlit chính cho chatbot hộ nghèo và báo cáo hành chính.

Luồng chính:
  1) Hỏi đáp/truy vấn dữ liệu từ db/poverty.db.
  2) Hiển thị bảng, tải XLSX/CSV và biểu đồ theo kết quả truy vấn.
  3) Sinh nhận định, bảng và biểu đồ theo 12 mẫu báo cáo; xuất Word/Excel hành chính.

Chạy:
  streamlit run app.py
"""

import os
import sys

# Best-effort cho Windows + Kaleido/Chrome:
# đặt trước khi import plotly/kaleido để Chromium ưu tiên chạy ẩn và không cố bật GPU.
os.environ.setdefault("KALEIDO_DISABLE_GPU", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import re
import sqlite3
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from io import BytesIO

try:
    import plotly.express as px
except Exception:  # pragma: no cover - plotly là tùy chọn; app vẫn có fallback khi thiếu
    px = None


def _configure_plotly_kaleido_export() -> None:
    """Cấu hình nhẹ cho Plotly/Kaleido mới.

    - pio.defaults là API chính thức từ Plotly 6.1+ cho default size/format/scale.
    - chromium_args qua pio.kaleido.scope chỉ là best-effort cho môi trường cũ/đang còn hỗ trợ;
      nếu thuộc tính không tồn tại thì bỏ qua, không làm app lỗi.
    """
    try:
        import plotly.io as pio

        defaults = getattr(pio, "defaults", None)
        if defaults is not None:
            try:
                defaults.default_format = "png"
                defaults.default_width = 1600
                defaults.default_height = 920
                defaults.default_scale = 2
            except Exception:
                pass

        # Best-effort legacy/deprecated scope. Không phụ thuộc vào thuộc tính này để app chạy.
        try:
            scope = getattr(getattr(pio, "kaleido", None), "scope", None)
            if scope is not None and hasattr(scope, "chromium_args"):
                scope.chromium_args = [
                    "--headless=new",
                    "--headless",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--window-size=1600,920",
                ]
        except Exception:
            pass
    except Exception:
        pass



_configure_plotly_kaleido_export()


def _hidden_kaleido_v1_write_figs_to_paths(figs: list[Any], image_paths: list[Path]) -> tuple[bool, str | None]:
    """Xuất ảnh bằng Kaleido v1 trực tiếp với Chromium class tùy biến để ẩn cửa sổ Windows.

    Lý do không chỉ dùng plotly.io.write_images: Plotly gọi kaleido.write_fig_from_object_sync()
    nhưng chỉ truyền một phần nhỏ `kopts`, nên app khó can thiệp vào class Chromium thật sự.
    Hàm này gọi trực tiếp Kaleido v1 và truyền `browser_cls` để:
    - thay `--headless` bằng `--headless=new`;
    - giữ `--disable-gpu`/`enable_gpu=False`;
    - thêm flags giảm compositor/window surface;
    - trên Windows dùng STARTUPINFO + CREATE_NO_WINDOW ngay trong get_popen_args().

    Nếu môi trường không phải Kaleido v1 hoặc API thay đổi, trả về False để fallback an toàn.
    """
    if not figs:
        return True, None
    if len(figs) != len(image_paths):
        return False, "Số lượng biểu đồ và đường dẫn ảnh tạm không khớp."

    try:
        import platform
        import subprocess

        import kaleido
        from choreographer.browsers.chromium import Chromium
    except Exception as exc:
        return False, f"Không import được Kaleido v1/Choreographer để export ẩn. Chi tiết: {exc}"

    try:
        class _PovertyHiddenChromium(Chromium):  # type: ignore[misc, valid-type]
            """Chromium wrapper riêng cho app: cố gắng ẩn hoàn toàn cửa sổ Chrome trên Windows."""

            def get_cli(self):  # type: ignore[override]
                cli = list(super().get_cli())
                normalized: list[str] = []
                for arg in cli:
                    # Choreographer mặc định dùng --headless. Chrome mới ổn định hơn với --headless=new.
                    if arg == "--headless":
                        normalized.append("--headless=new")
                    else:
                        normalized.append(arg)

                extras = [
                    "--disable-gpu",
                    "--disable-gpu-compositing",
                    "--disable-software-rasterizer",
                    "--disable-accelerated-2d-canvas",
                    "--disable-features=CalculateNativeWinOcclusion,HardwareMediaKeyHandling,MediaRouter,OptimizationHints,VizDisplayCompositor",
                    "--disable-extensions",
                    "--disable-notifications",
                    "--hide-scrollbars",
                    "--mute-audio",
                    "--window-size=1600,920",
                    "--window-position=-32000,-32000",
                ]
                for extra in extras:
                    key = extra.split("=", 1)[0]
                    if not any(str(x).split("=", 1)[0] == key for x in normalized):
                        normalized.append(extra)
                return normalized

            def get_popen_args(self):  # type: ignore[override]
                args = dict(super().get_popen_args())
                if platform.system() == "Windows":
                    try:
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = subprocess.SW_HIDE
                        args["startupinfo"] = startupinfo
                    except Exception:
                        pass
                    flags = int(args.get("creationflags") or 0)
                    flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) or 0)
                    flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
                    # DETACHED_PROCESS có thể làm mất console hoàn toàn. Giữ best-effort nhưng không bắt buộc.
                    flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0) or 0)
                    args["creationflags"] = flags
                    # Chrome dùng remote-debugging pipe trên Windows, nên vẫn cần close_fds=False để giữ handle.
                    args["close_fds"] = False
                return args

        specs = []
        for fig, image_path in zip(figs, image_paths):
            try:
                fig_payload = fig.to_dict() if hasattr(fig, "to_dict") else fig
            except Exception:
                fig_payload = fig
            specs.append(
                {
                    "fig": fig_payload,
                    "path": image_path,
                    "opts": {
                        "format": "png",
                        "width": 1600,
                        "height": 920,
                        "scale": 2,
                    },
                }
            )

        errors = kaleido.write_fig_from_object_sync(
            specs,
            kopts={
                "n": 1,
                "timeout": 90,
                "browser_cls": _PovertyHiddenChromium,
                "headless": True,
                "enable_gpu": False,
                "enable_sandbox": False,
            },
            cancel_on_error=False,
        )
        if errors:
            return False, f"Kaleido v1 export ẩn trả về lỗi: {errors}"
        return True, None
    except Exception as exc:
        return False, f"Kaleido v1 export ẩn thất bại. Chi tiết: {exc}"


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_ROOT / "report"
DATA_SAMPLES_DIR = PROJECT_ROOT / "data" / "report_samples"
DEFAULT_PROFILE_PATH = REPORT_DIR / "report_style_profile.json"
DEFAULT_PROFILE_FALLBACK_PATH = REPORT_DIR / "report_style_profile_default.json"

for _path in (PROJECT_ROOT, REPORT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from report.template_excel_exporter import export_template_xlsx, SUPPORTED_TEMPLATE_IDS
except Exception:
    from template_excel_exporter import export_template_xlsx, SUPPORTED_TEMPLATE_IDS  # type: ignore

try:
    from report.template_excel_llm_exporter import export_mau1_llm_excel, export_mau2_llm_excel, export_mau3_llm_excel, export_mau4_llm_excel, export_mau5_llm_excel, export_mau6_llm_excel, export_mau7_llm_excel, export_mau8_llm_excel, export_mau9_llm_excel, export_mau10_llm_excel, export_mau11_llm_excel, export_mau12_llm_excel
except Exception:
    from template_excel_llm_exporter import export_mau1_llm_excel, export_mau2_llm_excel, export_mau3_llm_excel, export_mau4_llm_excel, export_mau5_llm_excel, export_mau6_llm_excel, export_mau7_llm_excel, export_mau8_llm_excel, export_mau9_llm_excel, export_mau10_llm_excel, export_mau11_llm_excel, export_mau12_llm_excel  # type: ignore

try:
    from report.report_logger import write_report_task_log
except Exception:
    try:
        from report_logger import write_report_task_log  # type: ignore
    except Exception:
        write_report_task_log = None  # type: ignore

try:
    from report.report_ui_llm_planner import (
        build_report_table_plan,
        apply_report_table_plan,
        build_report_chart_plan,
        execute_report_chart_plan,
        build_report_chart_plans,
        execute_report_chart_plans,
        rename_report_display_df,
    )
except Exception:
    try:
        from report_ui_llm_planner import (  # type: ignore
            build_report_table_plan,
            apply_report_table_plan,
            build_report_chart_plan,
            execute_report_chart_plan,
            build_report_chart_plans,
            execute_report_chart_plans,
            rename_report_display_df,
        )
    except Exception:
        build_report_table_plan = None  # type: ignore
        apply_report_table_plan = None  # type: ignore
        build_report_chart_plan = None  # type: ignore
        execute_report_chart_plan = None  # type: ignore
        build_report_chart_plans = None  # type: ignore
        execute_report_chart_plans = None  # type: ignore
        rename_report_display_df = None  # type: ignore


from poverty_chatbot.config import DB_PATH, MODEL_NAME
try:
    from poverty_chatbot.config import OLLAMA_URL, LLM_TIMEOUT
except Exception:
    OLLAMA_URL = "http://localhost:11434/api/chat"
    LLM_TIMEOUT = 20
from core.fallback import process_question
from core.catalog import DERIVED_METRIC_DEFINITIONS, FEATURE_CATALOG
from chart_utils import (
    detect_chart_request,
    export_xlsx,
    infer_chart_type,
    is_chartable,
    allowed_chart_types,
    make_chart,
    prepare_chart_df,
    build_chart_recommendation,
    resolve_requested_chart_type,
    pie_block_reason,
    build_chart_answer,
    build_chart_display_df,
    _safe_title,
)

try:
    # Module facts-first hiện được triển khai tại report/report_writer.py.
    from report.report_writer import generate_report_text
    from report.report_style_trainer import train_style_profile
except Exception:
    try:
        from report_writer import generate_report_text  # type: ignore
        from report_style_trainer import train_style_profile  # type: ignore
    except Exception:
        from report.report_writer import generate_report_text
        from report.report_style_trainer import train_style_profile

try:
    from report.report_pattern_catalog import list_report_templates, get_report_template
    from report.report_fact_builder import build_report_bundle, bundle_main_table
    from report.report_exporter import (
        export_administrative_docx,
        merge_agency_meta,
    )
except Exception:
    # Hỗ trợ trường hợp debug/chạy rời các module report ở cùng thư mục với app.py.
    from report_pattern_catalog import list_report_templates, get_report_template  # type: ignore
    from report_fact_builder import build_report_bundle, bundle_main_table  # type: ignore
    from report_exporter import (  # type: ignore
        export_administrative_docx,
        merge_agency_meta,
    )



# ── Hằng số ──────────────────────────────────────────────────────────────────
DISPLAY_LIMIT = 50
CHART_TYPE_LABELS = {
    "bar": "📊 Biểu đồ cột",
    "pie": "🥧 Biểu đồ tròn",
    "line": "📈 Biểu đồ đường",
}

REPORT_MODE_LABELS = {
    "auto": "Tự động chọn theo nội dung số liệu",
    "general": "Nhận định tổng quan",
    "compare_years": "So sánh diễn biến qua các năm",
    "compare_districts": "So sánh theo địa bàn",
    "causes": "Phân tích nguyên nhân nghèo",
    "deprivation": "Phân tích thiếu hụt dịch vụ xã hội cơ bản",
    "vulnerable_groups": "Phân tích nhóm đối tượng",
    "policy_support": "Phân tích chính sách hỗ trợ",
}

REPORT_PATTERN_LABELS = {
    "overview_result": "Tổng quan kết quả rà soát",
    "multidimensional_poverty_summary": "Tổng hợp chuẩn nghèo đa chiều",
    "poverty_movement": "Diễn biến hộ nghèo/cận nghèo",
    "compare_years_simple": "So sánh hai mốc năm",
    "compare_geography": "So sánh theo địa bàn",
    "deprivation_count": "Thiếu hụt DVXHCB - số lượng",
    "deprivation_ratio": "Thiếu hụt DVXHCB - tỷ lệ",
    "child_deprivation": "Thiếu hụt của trẻ em",
    "vulnerable_groups": "Nhóm đối tượng",
    "ethnicity": "Theo dân tộc",
    "causes": "Nguyên nhân nghèo/cận nghèo",
    "policy_support": "Chính sách/hỗ trợ",
}

REPORT_TABLE_LABELS = {
    "template_main": "Bảng số liệu báo cáo",
    "template_chart": "Dữ liệu biểu đồ minh họa",
    "main": "Bảng số liệu tổng hợp",
    "by_district": "Bảng tổng hợp theo địa bàn",
}

REPORT_COLUMN_LABELS = {
    "phan_loai": "Phân loại hộ",
    "so_ho": "Số hộ",
    "so_nhan_khau": "Số nhân khẩu",
    "ty_le_%": "Tỷ lệ (%)",
    "huyen": "Huyện/TP",
    "chi_tieu": "Chỉ tiêu",
    "so_tre_thieu": "Số trẻ thiếu",
    "so_ho_co_tre_thieu": "Số hộ có trẻ thiếu",
    "tong_tre": "Tổng số trẻ",
    "dan_toc": "Dân tộc",
    "so_ho_ngheo": "Số hộ nghèo",
    "ty_le_ho_ngheo_%": "Tỷ lệ hộ nghèo (%)",
    "so_ho_can_ngheo": "Số hộ cận nghèo",
    "ty_le_ho_can_ngheo_%": "Tỷ lệ hộ cận nghèo (%)",
    "so_tre_thieu_bhyt": "Số trẻ thiếu BHYT",
    "so_tre_thieu_dinh_duong": "Số trẻ thiếu dinh dưỡng",
    "so_tre_thieu_di_hoc": "Số trẻ thiếu đi học",
    "tong_tre_thieu_bhyt": "Tổng trẻ thiếu BHYT",
    "tong_tre_thieu_dinh_duong": "Tổng trẻ thiếu dinh dưỡng",
    "tong_tre_thieu_di_hoc": "Tổng trẻ thiếu đi học",
    "so_ho_ky_truoc": "Số hộ đầu kỳ",
    "so_ho_ky_sau": "Số hộ cuối kỳ",
    "giam_1": "Số hộ giảm nhóm 1",
    "giam_2": "Số hộ giảm nhóm 2",
    "giam_khac": "Số hộ giảm khác có căn cứ chi tiết",
    "tang_1": "Số hộ tăng nhóm 1",
    "tang_2": "Số hộ tăng nhóm 2",
    "tang_3": "Số hộ tăng nhóm 3",
    "tang_khac": "Số hộ tăng khác có căn cứ chi tiết",
    "nam_truoc": "Năm trước",
    "nam_sau": "Năm sau",
    "chenh_lech": "Chênh lệch",
    "ty_le_bien_dong_%": "Tỷ lệ biến động (%)",
    "tong_ho_ra_soat": "Tổng hộ rà soát",
    "tong_ho_dan_cu": "Tổng số hộ dân cư",
    "tong_nhan_khau": "Tổng số nhân khẩu",
    "so_ho_ngheo": "Số hộ nghèo",
    "so_khau_ngheo": "Số nhân khẩu hộ nghèo",
    "so_ho_can_ngheo": "Số hộ cận nghèo",
    "so_khau_can_ngheo": "Số nhân khẩu hộ cận nghèo",
    "so_ho_nlnndn_mstb": "Số hộ nông, lâm, ngư nghiệp mức sống TB",
    "so_khau_nlnndn_mstb": "Số nhân khẩu nông, lâm, ngư nghiệp mức sống TB",
    "nhom_chi_tieu": "Nhóm chỉ tiêu",
    "tong_nhan_khau": "Tổng nhân khẩu",
    "so_ho_muc_tieu": "Số hộ mục tiêu",
    "so_nhan_khau_muc_tieu": "Số nhân khẩu mục tiêu",
    "so_ho_kinh": "Số hộ dân tộc Kinh",
    "so_ho_dtts": "Số hộ DTTS",
    "so_ho_dtts_tai_cho": "Số hộ DTTS tại chỗ",
    "ty_le_muc_tieu_%": "Tỷ lệ hộ mục tiêu (%)",
    "ty_le_dtts_trong_nhom_%": "Tỷ lệ DTTS trong nhóm (%)",
}

def _report_table_label(name: str) -> str:
    return REPORT_TABLE_LABELS.get(str(name), str(name).replace("_", " ").title())

def _rename_report_df(df: pd.DataFrame, pattern: str | None = None) -> pd.DataFrame:
    labels = dict(REPORT_COLUMN_LABELS)
    if pattern == "child_deprivation":
        labels.update({
            "so_ho_ngheo": "Số trẻ thuộc hộ nghèo",
            "ty_le_ho_ngheo_%": "Tỷ lệ trên tổng trẻ hộ nghèo (%)",
            "so_ho_can_ngheo": "Số trẻ thuộc hộ cận nghèo",
            "ty_le_ho_can_ngheo_%": "Tỷ lệ trên tổng trẻ hộ cận nghèo (%)",
        })
    return df.rename(columns={c: labels.get(str(c), str(c)) for c in df.columns})

QA_LOG_DIR = Path(__file__).resolve().parent / "logs"
QA_LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_sidebar_stats(huyen: str | None = None, nam: int | None = None) -> dict:
    """Read sidebar totals directly from SQLite with the same distinct-household rule."""
    clauses = []
    params: list[Any] = []
    if huyen:
        clauses.append("huyen = ?")
        params.append(huyen)
    if nam:
        clauses.append("nam = ?")
        params.append(int(nam))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT id_ho), "
            "COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ nghèo' THEN id_ho END), "
            "COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ cận nghèo' THEN id_ho END), "
            "COUNT(DISTINCT CASE WHEN phan_loai = 'Hộ không nghèo' THEN id_ho END) "
            f"FROM ho_ngheo{where}",
            params,
        ).fetchone()
        huyens = [item[0] for item in conn.execute(
            "SELECT DISTINCT huyen FROM ho_ngheo WHERE huyen IS NOT NULL ORDER BY huyen"
        )]
        nams = [item[0] for item in conn.execute(
            "SELECT DISTINCT nam FROM ho_ngheo WHERE nam IS NOT NULL ORDER BY nam DESC"
        )]
    tong_ho, ho_ngheo, ho_can_ngheo, ho_khong_ngheo = map(int, row)
    return {
        "tong_ho": tong_ho,
        "ho_ngheo": ho_ngheo,
        "ho_can_ngheo": ho_can_ngheo,
        "ho_khong_ngheo": ho_khong_ngheo,
        "huyens": huyens,
        "nams": nams,
    }


def _relative_or_str(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def _default_profile_text() -> str:
    if DEFAULT_PROFILE_PATH.exists():
        return _relative_or_str(DEFAULT_PROFILE_PATH)
    if DEFAULT_PROFILE_FALLBACK_PATH.exists():
        return _relative_or_str(DEFAULT_PROFILE_FALLBACK_PATH)
    return _relative_or_str(DEFAULT_PROFILE_PATH)


def _resolve_project_path(text: str | None) -> Path | None:
    raw = (text or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _train_report_profile() -> tuple[bool, str]:
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        profile = train_style_profile(DATA_SAMPLES_DIR, DEFAULT_PROFILE_PATH)
        source_files = getattr(profile, "source_files", []) or []
        excel_count = sum(1 for name in source_files if str(name).lower().endswith((".xlsx", ".xlsm")))
        text_count = sum(1 for name in source_files if str(name).lower().endswith((".md", ".txt", ".docx", ".pdf")))

        msg = (
            f"Đã đọc {excel_count} biểu biểu mẫu báo cáo"
        )

        if text_count:
            msg += f" và {text_count} file văn phong báo cáo"
        else:
            msg += "; nếu không có file văn bản báo cáo thì dùng bộ quy tắc văn phong báo cáo mặc định"

        msg += "."

        warnings = [
            w for w in (getattr(profile, "warnings", None) or [])
            if "Đã ưu tiên học văn phong" not in str(w)
        ]

        if warnings:
            msg += " Lưu ý: " + " | ".join(warnings[:3])
        return True, msg
    except Exception as exc:
        return False, f"Không train được style profile: {exc}"


def _report_mode_uses_llm() -> bool:
    generation_mode = str(st.session_state.get("report_generation_mode", "Không dùng LLM (Python an toàn)"))
    return generation_mode.startswith("Có LLM")


def _current_report_excel_mode_label() -> str:
    """Excel mode follows the single global report mode.

    UI removes the separate Excel LLM toggle:
    - Không dùng LLM -> deterministic Excel theo mẫu gốc.
    - Có LLM -> Excel LLM-assisted mapping, Python vẫn validate/tính/ghi Excel.
    """
    if _report_mode_uses_llm():
        return "LLM-assisted mapping + Python validated fallback"
    return "Không dùng LLM (Excel thường)"


def _current_report_settings() -> dict[str, Any]:
    profile_path = _resolve_project_path(st.session_state.get("report_profile_path", _default_profile_text()))
    generation_mode = str(st.session_state.get("report_generation_mode", "Không dùng LLM (Python an toàn)"))
    use_llm = _report_mode_uses_llm()
    return {
        "profile_path": profile_path if profile_path and profile_path.exists() else None,
        "generation_mode_label": generation_mode,
        "generation_mode": "llm" if use_llm else "no_llm",
        "use_llm": use_llm,
        "excel_llm_mode": _current_report_excel_mode_label(),
        "allow_variation": bool(st.session_state.get("report_allow_variation", True)),
        "llm_min_words": int(st.session_state.get("report_llm_min_words", 180) or 180),
        "mode": "auto",
        "report_level": "administrative",
        # Chế độ LLM không tự fallback sang văn bản Python. Bản Python là chế độ không LLM riêng.
        "llm_failure_policy": "no_fallback" if use_llm else "python_auto",
    }


def _qa_log_path() -> Path:
    """Trả về path file log Q&A theo ngày hiện tại."""
    return QA_LOG_DIR / f"qa_chat_{datetime.now().strftime('%Y%m%d')}.jsonl"


def to_dataframe(result: Any) -> pd.DataFrame | None:
    """Chuyển kết quả truy vấn về DataFrame nếu có thể, dùng cho log/debug."""
    if result is None:
        return None
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, dict):
        return pd.DataFrame([result])
    if isinstance(result, list):
        return pd.DataFrame(result)
    return None

def _vn_key(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("đ", "d")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _answer_has_markdown_table(answer: str) -> bool:
    text = str(answer or "")
    return "|" in text and "---" in text

def _display_report_text_block(text: str) -> None:
    """Hiển thị văn bản nhận định theo từng đoạn để không bị dính thành một khối trong UI."""
    raw = str(text or "").strip()
    if not raw:
        st.info("Chưa có văn bản nhận định.")
        return

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    if len(paragraphs) <= 1:
        # Fallback cho trường hợp text chỉ có single newline hoặc bị LLM/fallback trả về thành một khối dài.
        rough = re.split(r"(?<=[.!?])\s+(?=(?:[A-ZÀ-ỸĐ]|[0-9]))", raw)
        if len(rough) >= 4:
            chunks = []
            for i in range(0, len(rough), 2):
                chunks.append(" ".join(x.strip() for x in rough[i:i+2] if x.strip()))
            paragraphs = [x for x in chunks if x]

    for para in paragraphs:
        line = para.replace("\n", "  \n")
        if re.match(r"^(Khái quát|Kết quả|Địa bàn|Nhóm|Biểu đồ|Lưu ý|Định hướng|Nhận định)[:：]", para, flags=re.I):
            head, _, body = para.partition(":")
            st.markdown(f"**{head.strip()}:** {body.strip()}" if body.strip() else f"**{head.strip()}**")
        else:
            st.markdown(line)

def _safe_df(df: pd.DataFrame) -> pd.DataFrame:
    hidden_cols = {"id_ho", "__total_count"}
    return df[[col for col in df.columns if col not in hidden_cols]].copy()

def _plan_snapshot(debug: dict) -> dict | str | None:
    return debug.get("query_plan") or debug.get("stages", {}).get("rule_plan")


def _result_summary(result) -> dict:
    df = to_dataframe(result)
    if df is None:
        return {"type": type(result).__name__}

    safe_df = _safe_df(df)

    return {
        "rows": len(safe_df),
        "columns": list(safe_df.columns),
        "sample": safe_df.head(3).where(pd.notna(safe_df.head(3)), None).to_dict(orient="records"),
    }


def _write_qa_log(question: str, answer: str, debug: dict, filters: dict) -> None:
    """Ghi 1 lượt Q&A vào file log hàng ngày trong /logs/."""
    result = debug.get("result_df")

    payload = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "log_event_type": "report_generated" if debug.get("report_requested", False) else "qa_answer",
        "user_question": debug.get("user_question", question),
        "effective_question": question,
        "answer": answer,
        "filters": filters,
        "plan": _plan_snapshot(debug),
        "pipeline": debug.get("pipeline") or debug.get("source") or debug.get("workflow"),
        "result_summary": _result_summary(result) if result is not None else None,
        "table_rendered": debug.get("table_rendered", False),
        "table_reason": debug.get("table_reason"),
        "table_rows": debug.get("table_rows"),
        "table_columns": debug.get("table_columns"),

        "chart_option_visible": debug.get("chart_option_visible", False),
        "chart_option_reason": debug.get("chart_option_reason"),
        "chart_source": debug.get("chart_source"),

        # Optional chart recommendation
        "chart_recommendation_visible": debug.get("chart_recommendation_visible", False),
        "chart_recommendation": debug.get("chart_recommendation"),
        "optional_chart_success": debug.get("optional_chart_success", False),
        "optional_chart_source": debug.get("optional_chart_source"),
        "optional_chart_type": debug.get("optional_chart_type"),
        "optional_chart_debug": debug.get("optional_chart_debug"),

        # Tuần 3: log biểu đồ trực tiếp
        "chart_requested": debug.get("chart_requested", False),
        "chart_success": debug.get("chart_success", False),
        "chart_debug": debug.get("chart_debug"),

        # Tuần 4: log sinh nhận định báo cáo
        "report_requested": debug.get("report_requested", False),
        "report_success": debug.get("report_success", False),
        "report_mode": debug.get("report_mode"),
        "report_mode_label": debug.get("report_mode_label"),
        "report_pattern": debug.get("report_pattern"),
        "report_pattern_label": debug.get("report_pattern_label"),
        "report_level": debug.get("report_level"),
        "report_level_label": debug.get("report_level_label"),
        "report_used_llm": debug.get("report_used_llm"),
        "report_text": debug.get("report_text"),
        "report_prompt": debug.get("report_prompt"),
        "report_warnings": debug.get("report_warnings"),
        "report_raw_llm_text": debug.get("report_raw_llm_text"),
        "report_repair_attempted": debug.get("report_repair_attempted", False),
        "report_repair_success": debug.get("report_repair_success", False),
        "report_repair_noop": debug.get("report_repair_noop", False),
        "report_repair_validation_warnings": debug.get("report_repair_validation_warnings"),
        "report_repair_prompt": debug.get("report_repair_prompt"),
        "report_repair_text": debug.get("report_repair_text"),
        "report_fallback_used": debug.get("report_fallback_used", False),
        "report_validation_warnings": debug.get("report_validation_warnings"),
        "report_fallback_validation_warnings": debug.get("report_fallback_validation_warnings"),
        "report_final_validation_warnings": debug.get("report_final_validation_warnings"),
        "report_facts": debug.get("report_facts"),
        "report_generation_strategy": debug.get("report_generation_strategy"),
        "final_source": debug.get("final_source"),
        "raw_llm_attempted": debug.get("raw_llm_attempted", False),
        "raw_llm_validation_passed": debug.get("raw_llm_validation_passed", False),
        "raw_llm_rejected_reasons": debug.get("raw_llm_rejected_reasons"),
        "repair_attempted": debug.get("report_repair_attempted", False),
        "repair_validation_passed": debug.get("repair_validation_passed", False),
        "fallback_used": debug.get("report_fallback_used", False),
        "final_validation_passed": debug.get("final_validation_passed", False),
        "llm_rewrite_attempted": debug.get("llm_rewrite_attempted", False),
        "llm_rewrite_success": debug.get("llm_rewrite_success", False),
        "llm_rewrite_validation_passed": debug.get("llm_rewrite_validation_passed", False),
        "report_regenerate_nonce": debug.get("report_regenerate_nonce"),
        "rewrite_similarity": debug.get("rewrite_similarity"),
        "rewrite_retry_attempted": debug.get("rewrite_retry_attempted", False),
        "cache_hit": debug.get("cache_hit", False),
        "reused_saved_report": debug.get("reused_saved_report", False),
        "raw_generation_disabled_by_design": debug.get("raw_generation_disabled_by_design", False),
        "status_messages": debug.get("status_messages"),
        "report_debug": debug.get("report_debug"),
    }

    with _qa_log_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

def _allow_chart_option_for_task(debug: dict) -> bool:
    plan = debug.get("query_plan") or {}
    task = plan.get("task")

    # Chỉ cho tạo biểu đồ từ bảng tổng hợp/thống kê.
    # Không cho từ bảng danh sách hộ vì dễ tạo biểu đồ rác.
    return task in {"group_aggregate", "compare_years", "multi_metric_table"}

def _is_table_result(debug: dict) -> bool:
    plan = debug.get("query_plan") or {}
    question = debug.get("question") or debug.get("user_question") or ""
    q = question.lower()
    q_key = _vn_key(question)
    task = plan.get("task")
    group_by = plan.get("group_by") or []

    if debug.get("chart_requested"):
        chart_df = debug.get("chart_df")
        result_df = debug.get("result_df")
        return bool(
            (isinstance(chart_df, pd.DataFrame) and not chart_df.empty)
            or (isinstance(result_df, pd.DataFrame) and not result_df.empty)
        )

    explicit_table = any(x in q for x in ("bảng", "lập bảng", "thống kê", "phân bố", "cơ cấu")) or any(
        x in q_key for x in ("bang", "lap bang", "thong ke", "phan bo", "co cau")
    )

    weak_group_table = (
        "theo " in q
        or "theo " in q_key
        or "từng " in q
        or "tung " in q_key
        or bool(group_by)
    )

    ranking_signal = any(x in q for x in (
        "huyện nào", "xã nào", "dân tộc nào", "nhóm nào", "loại nào",
        "nhiều nhất", "ít nhất", "cao nhất", "thấp nhất", "đứng đầu", "top",
    )) or any(x in q_key for x in (
        "huyen nao", "xa nao", "dan toc nao", "nhom nao", "loai nao",
        "nhieu nhat", "it nhat", "cao nhat", "thap nhat", "dung dau", "top",
    ))

    if task in {"list_records", "lookup_person", "multi_metric_table"}:
        return True

    if ranking_signal and not explicit_table:
        # Ranking nhiều dòng (top N) là một bảng tổng hợp hợp lệ;
        # chỉ giữ câu trả lời ngắn cho single-best/single-worst.
        limit = plan.get("limit")
        if not (task == "group_aggregate" and isinstance(limit, int) and limit > 1):
            return False

    if task in {"group_aggregate", "compare_years"}:
        return explicit_table or weak_group_table

    return False


def _annotate_render_debug(debug: dict) -> None:
    result_df = debug.get("result_df")
    is_df = isinstance(result_df, pd.DataFrame) and not result_df.empty

    chart_df = debug.get("chart_df")
    is_direct_chart = bool(
        debug.get("chart_requested")
        and debug.get("chart_success")
        and isinstance(chart_df, pd.DataFrame)
        and not chart_df.empty
    )
    if is_direct_chart:
        table_df = build_chart_display_df(chart_df, debug.get("chart_debug"), result_df)
        debug["chart_table_df"] = table_df
    else:
        table_df = result_df
    has_table_df = isinstance(table_df, pd.DataFrame) and not table_df.empty

    plan = debug.get("query_plan") or {}
    task = plan.get("task")

    table_rendered = _is_table_result(debug) and has_table_df

    debug["table_rendered"] = bool(table_rendered)
    debug["table_reason"] = (
        f"task={task}, chart_requested={debug.get('chart_requested')}"
        if table_rendered
        else f"not_table_or_empty: task={task}, has_df={is_df}, chart_requested={debug.get('chart_requested')}"
    )

    if has_table_df:
        question = debug.get("question") or debug.get("user_question") or ""

        debug["table_rows"] = int(len(table_df))
        debug["table_columns"] = list(_safe_df(table_df).columns)
        chart_option_allowed = _allow_chart_option_for_task(debug)

        chart_recommendation = None
        if table_rendered and chart_option_allowed and not debug.get("chart_success"):
            optional_chart_df = prepare_chart_df(result_df, debug.get("question", ""), debug.get("query_plan"))
            chart_recommendation = build_chart_recommendation(debug, optional_chart_df, debug.get("question", ""), CHART_TYPE_LABELS)
            chartable = chart_recommendation is not None
        else:
            chartable = False

        debug["chart_recommendation_visible"] = bool(chart_recommendation)
        debug["chart_recommendation"] = chart_recommendation

        # Giữ key cũ để không phá log/eval cũ, nhưng ý nghĩa mới là "có recommendation".
        debug["chart_option_visible"] = bool(chart_recommendation)

        debug["chart_option_reason"] = (
            chart_recommendation.get("reason")
            if chart_recommendation
            else (
                f"table_rendered={table_rendered}, "
                f"chartable={chartable}, "
                f"chart_option_allowed={chart_option_allowed}, "
                f"chart_success={debug.get('chart_success')}"
            )
        )
    else:
        debug["table_rows"] = 0
        debug["table_columns"] = []
        debug["chart_option_visible"] = False
        debug["chart_option_reason"] = "no_result_df"

def _display_rename_map() -> dict[str, str]:
    rename_map = {
        "id_ho": "ID hộ",
        "ma_ho": "Mã hộ",
        "chu_ho": "Chủ hộ",
        "nam": "Năm",
        "huyen": "Huyện",
        "xa_phuong": "Xã/phường",
        "phan_loai": "Phân loại",
        "gioi_tinh": "Giới tính",
        "dan_toc_chi_tiet": "Dân tộc",
        "so_nhan_khau": "Số nhân khẩu",
        "thu_nhap_bq": "Thu nhập BQ",
        "tinh_trang_nha": "Tình trạng nhà",
        "th_bhyt": "Không có BHYT",
        "th_bhxh": "Không có BHXH",
        "co_nha_tieu_hvs": "Nhà tiêu HVS",
        "co_internet": "Có internet",
        "co_dien": "Có điện",
        "so_tre_em": "Số trẻ em",
        "so_tre_thieu": "Số trẻ thiếu",
        "so_ho_co_tre_thieu": "Số hộ có trẻ thiếu",
        "tong_tre": "Tổng số trẻ",
        "so_tre_thieu_bhyt": "Số trẻ thiếu BHYT",
        "so_tre_thieu_dinh_duong": "Số trẻ thiếu dinh dưỡng",
        "so_tre_thieu_di_hoc": "Số trẻ thiếu đi học",
        "tong_tre_thieu_bhyt": "Tổng trẻ thiếu BHYT",
        "tong_tre_thieu_dinh_duong": "Tổng trẻ thiếu dinh dưỡng",
        "tong_tre_thieu_di_hoc": "Tổng trẻ thiếu đi học",
        "co_tre_em": "Có trẻ em",
        "nhom_tre_em_duoi6": "Có trẻ dưới 6 tuổi",
        "nhom_don_than": "Đơn thân/độc thân",
        "so_ho": "Số hộ",
        "ty_le_%": "Tỷ lệ (%)",
        "tong_ho": "Tổng hộ",
        "so_ho_2023": "Số hộ 2023",
        "so_ho_2024": "Số hộ 2024",
        "chenh_lech": "Chênh lệch",
        "bien_dong": "Biến động",
        "avg_thu_nhap_bq": "Thu nhập BQ",
        "tb_thu_nhap_nghin_dong": "Thu nhập BQ",
        "nhom_ngheo_tong_hop": "Nhóm nghèo tổng hợp",
        "cay_trong_chinh": "Cây trồng chính",
        "loai_xa_phuong": "Loại xã/phường",
        "khu_vuc_xa": "Khu vực xã",
        "bien_dong_dau_ky": "Biến động đầu kỳ",
        "ky_ra_soat": "Kỳ rà soát",
    }
    for meta in FEATURE_CATALOG.values():
        alias = meta.get("table_alias")
        label = meta.get("table_label")
        if alias and label:
            rename_map[alias] = label
    for definition in DERIVED_METRIC_DEFINITIONS.values():
        alias = definition.get("alias")
        label = definition.get("label")
        if alias and label:
            rename_map[alias] = label
    return rename_map
def _prepare_display_df(df: pd.DataFrame, limit: int = DISPLAY_LIMIT) -> pd.DataFrame:
    display_df = _safe_df(df).head(limit)
    return display_df.rename(columns={col: _display_rename_map().get(col, col) for col in display_df.columns})


def _prepare_export_df(df: pd.DataFrame) -> pd.DataFrame:
    export_df = _safe_df(df)
    return export_df.rename(columns={col: _display_rename_map().get(col, col) for col in export_df.columns})

def _render_download_buttons(msg_idx: int, df: pd.DataFrame, question: str, prefix: str = "table",) -> None:
    export_df = _prepare_export_df(df)
    title = _safe_title(question) if question else "Bảng thống kê hộ nghèo"
    xlsx_bytes = export_xlsx(export_df, title=title)
    csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"thong_ke_{timestamp}"

    dl_cols = st.columns(2)
    dl_cols[0].download_button(
        "⬇️ Tải bảng XLSX",
        data=xlsx_bytes,
        file_name=f"{base_name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_{prefix}_xlsx_{msg_idx}",
    )
    dl_cols[1].download_button(
        "⬇️ Tải bảng CSV",
        data=csv_bytes,
        file_name=f"{base_name}.csv",
        mime="text/csv",
        key=f"dl_{prefix}_csv_{msg_idx}",
    )


def _render_recommended_chart_section(msg_idx: int, df: pd.DataFrame, question: str, debug: dict) -> None:
    """Render optional chart theo kiểu recommendation: chỉ đề xuất 1 loại biểu đồ phù hợp nhất."""
    recommendation = debug.get("chart_recommendation") or build_chart_recommendation(debug, df, question, CHART_TYPE_LABELS)
    if not recommendation:
        return

    chosen = recommendation.get("chart_type")
    plan = debug.get("query_plan") or {}
    allowed = recommendation.get("allowed_chart_types") or allowed_chart_types(df, question, plan)
    if chosen not in allowed:
        return

    chart_state_key = f"chart_recommendation_{msg_idx}"
    state = st.session_state.get(chart_state_key)

    if state == "skip":
        return

    if state != "show":
        st.info(recommendation.get("message") or "Bạn có muốn xem biểu đồ phù hợp nhất cho kết quả này không?")
        cols = st.columns([1, 1])
        if cols[0].button("Xem biểu đồ đề xuất", key=f"btn_recommend_chart_{msg_idx}"):
            st.session_state[chart_state_key] = "show"
            st.rerun()
        if cols[1].button("✖ Không cần", key=f"btn_skip_recommend_chart_{msg_idx}"):
            st.session_state[chart_state_key] = "skip"
            st.rerun()
        return

    fig = make_chart(df, chart_type=chosen, title="", question=question, plan=plan)
    if fig is not None:
        fig.update_layout(title_text="")
    if fig is None:
        st.warning("Không thể tạo biểu đồ từ bảng này.")
        return

    optional_debug = {
        "source": "recommended_optional_chart",
        "chart_type": chosen,
        "allowed_chart_types": allowed,
        "recommendation_reason": recommendation.get("reason"),
        "recommendation_message": recommendation.get("message"),
        "df_rows": int(len(df)),
        "df_columns": list(df.columns),
        "df_head": df.head(5).to_dict(orient="records"),
    }
    if fig.layout.meta:
        optional_debug.update(dict(fig.layout.meta))

    debug["optional_chart_success"] = True
    debug["optional_chart_source"] = "recommended_optional_chart"
    debug["optional_chart_type"] = chosen
    debug["optional_chart_debug"] = optional_debug

    st.markdown("**Biểu đồ đề xuất**")
    st.plotly_chart(fig, use_container_width=True, key=f"recommended_chart_{msg_idx}")
    st.caption("Biểu đồ này được đề xuất tự động từ task/metric/group_by và dữ liệu bảng.")

    with st.expander("🔍 Debug biểu đồ đề xuất", expanded=False):
        st.code(json.dumps(optional_debug, ensure_ascii=False, indent=2, default=str), language="json")

    # Log optional chart đúng một lần sau khi user bấm xem.
    signature = f"{chosen}:{len(df)}:{','.join(map(str, df.columns))}"
    if debug.get("optional_chart_logged_signature") != signature:
        debug["optional_chart_logged_signature"] = signature
        try:
            _write_qa_log(question, debug.get("answer", ""), debug, debug.get("filters") or {})
        except OSError:
            pass

def _render_report_section(msg_idx: int, df: pd.DataFrame, question: str, debug: dict) -> None:
    """Tuần 4 cũ: sinh nhận định từ bảng Q&A.

    Trong bản refactor, nhận định tuần 4/5 đi theo UI báo cáo hành chính riêng với 12 mẫu chính thức.
    Giữ hàm này để không phá code cũ, nhưng mặc định không hiện trong UI tuần 2+3.
    """
    if st.session_state.get("app_task_mode") != "inline_chat_report":
        return
    if df is None or df.empty:
        return
    plan = debug.get("query_plan") or {}
    task = plan.get("task") if isinstance(plan, dict) else getattr(plan, "task", None)
    report_tasks = {"group_aggregate", "compare_years", "multi_metric_table", "summary", "aggregate"}
    if task not in report_tasks:
        return

    report_key = f"report_result_{msg_idx}"
    visible_key = f"report_visible_{msg_idx}"
    nonce_key = f"report_regenerate_nonce_{msg_idx}"
    report_regenerate_nonce = int(st.session_state.get(nonce_key, 0) or 0)
    saved = st.session_state.get(report_key)

    cols = st.columns([1, 1, 1, 1])
    with cols[-1]:
        report_clicked = st.button(
            "Văn bản báo cáo nhận định",
            key=f"report_toggle_{msg_idx}",
            use_container_width=True,
        )

    if report_clicked:
        if saved:
            st.session_state[visible_key] = not bool(
                st.session_state.get(visible_key, False)
            )
        else:
            st.session_state[visible_key] = True

    if not st.session_state.get(visible_key, False):
        return

    settings = _current_report_settings()
    mode = settings["mode"]

    if not saved:
        debug["cache_hit"] = False
        debug["reused_saved_report"] = False
        debug["report_regenerate_nonce"] = report_regenerate_nonce
        with st.spinner("Đang sinh báo cáo..."):
            report = generate_report_text(
                question=question,
                data=df,
                mode=mode,
                style_profile_path=settings["profile_path"],
                use_llm=settings["use_llm"],
                report_level=settings.get("report_level", "technical"),
                allow_variation=settings.get("allow_variation", True),
                regenerate_nonce=report_regenerate_nonce,
                llm_min_words=settings.get("llm_min_words"),
            )
        saved_report = {
            "mode": report.mode,
            "report_pattern": getattr(report, "report_pattern", "overview_result"),
            "report_level": getattr(report, "report_level", "technical"),
            "text": report.text,
            "prompt": report.prompt,
            "used_llm": report.used_llm,
            "warnings": report.warnings,
            "raw_llm_text": getattr(report, "raw_llm_text", ""),
            "repair_prompt": getattr(report, "repair_prompt", ""),
            "repair_text": getattr(report, "repair_text", ""),
            "repair_attempted": getattr(report, "repair_attempted", False),
            "repair_success": getattr(report, "repair_success", False),
            "repair_noop": getattr(report, "repair_noop", False),
            "repair_validation_warnings": getattr(report, "repair_validation_warnings", None),
            "fallback_used": getattr(report, "fallback_used", False),
            "validation_warnings": getattr(report, "validation_warnings", None),
            "fallback_validation_warnings": getattr(report, "fallback_validation_warnings", None),
            "final_validation_warnings": getattr(report, "final_validation_warnings", None),
            "report_facts": getattr(report, "report_facts", None),
            "report_generation_strategy": getattr(report, "report_generation_strategy", ""),
            "final_source": getattr(report, "final_source", ""),
            "raw_llm_attempted": getattr(report, "raw_llm_attempted", False),
            "raw_llm_validation_passed": getattr(report, "raw_llm_validation_passed", False),
            "raw_llm_rejected_reasons": getattr(report, "raw_llm_rejected_reasons", None),
            "repair_validation_passed": getattr(report, "repair_validation_passed", False),
            "final_validation_passed": getattr(report, "final_validation_passed", False),
            "llm_rewrite_attempted": getattr(report, "llm_rewrite_attempted", False),
            "llm_rewrite_success": getattr(report, "llm_rewrite_success", False),
            "llm_rewrite_validation_passed": getattr(report, "llm_rewrite_validation_passed", False),
            "report_regenerate_nonce": getattr(report, "report_regenerate_nonce", report_regenerate_nonce),
            "rewrite_similarity": getattr(report, "rewrite_similarity", None),
            "rewrite_retry_attempted": getattr(report, "rewrite_retry_attempted", False),
            "cache_hit": False,
            "reused_saved_report": False,
            "raw_generation_disabled_by_design": getattr(report, "raw_generation_disabled_by_design", True),
            "status_messages": getattr(report, "status_messages", None),
        }

        st.session_state[report_key] = saved_report

        report_mode_label = REPORT_MODE_LABELS.get(
            report.mode,
            report.mode or "Tự động chọn theo nội dung số liệu",
        )
        report_pattern = getattr(report, "report_pattern", "overview_result")
        report_level = getattr(report, "report_level", "technical")
        report_pattern_label = REPORT_PATTERN_LABELS.get(report_pattern, report_pattern)

        debug["report_requested"] = True
        debug["report_success"] = True
        debug["report_mode"] = report.mode
        debug["report_mode_label"] = report_mode_label
        debug["report_pattern"] = report_pattern
        debug["report_pattern_label"] = report_pattern_label
        debug["report_level"] = report_level
        debug["report_level_label"] = None
        debug["report_used_llm"] = report.used_llm
        debug["report_text"] = report.text
        debug["report_prompt"] = report.prompt
        debug["report_warnings"] = report.warnings
        debug["report_raw_llm_text"] = getattr(report, "raw_llm_text", "")
        debug["report_repair_attempted"] = getattr(report, "repair_attempted", False)
        debug["report_repair_success"] = getattr(report, "repair_success", False)
        debug["report_repair_noop"] = getattr(report, "repair_noop", False)
        debug["report_repair_validation_warnings"] = getattr(report, "repair_validation_warnings", None)
        debug["report_repair_prompt"] = getattr(report, "repair_prompt", "")
        debug["report_repair_text"] = getattr(report, "repair_text", "")
        debug["report_fallback_used"] = getattr(report, "fallback_used", False)
        debug["report_validation_warnings"] = getattr(report, "validation_warnings", None)
        debug["report_fallback_validation_warnings"] = getattr(report, "fallback_validation_warnings", None)
        debug["report_final_validation_warnings"] = getattr(report, "final_validation_warnings", None)
        debug["report_facts"] = getattr(report, "report_facts", None)
        debug["report_generation_strategy"] = getattr(report, "report_generation_strategy", "")
        debug["final_source"] = getattr(report, "final_source", "")
        debug["raw_llm_attempted"] = getattr(report, "raw_llm_attempted", False)
        debug["raw_llm_validation_passed"] = getattr(report, "raw_llm_validation_passed", False)
        debug["raw_llm_rejected_reasons"] = getattr(report, "raw_llm_rejected_reasons", None)
        debug["repair_validation_passed"] = getattr(report, "repair_validation_passed", False)
        debug["final_validation_passed"] = getattr(report, "final_validation_passed", False)
        debug["llm_rewrite_attempted"] = getattr(report, "llm_rewrite_attempted", False)
        debug["llm_rewrite_success"] = getattr(report, "llm_rewrite_success", False)
        debug["llm_rewrite_validation_passed"] = getattr(report, "llm_rewrite_validation_passed", False)
        debug["report_regenerate_nonce"] = getattr(report, "report_regenerate_nonce", report_regenerate_nonce)
        debug["rewrite_similarity"] = getattr(report, "rewrite_similarity", None)
        debug["rewrite_retry_attempted"] = getattr(report, "rewrite_retry_attempted", False)
        debug["cache_hit"] = False
        debug["reused_saved_report"] = False
        debug["raw_generation_disabled_by_design"] = getattr(report, "raw_generation_disabled_by_design", True)
        debug["status_messages"] = getattr(report, "status_messages", None)
        debug["report_debug"] = {
            "source": "report_writer",
            "data_rows": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
            "data_columns": list(df.columns) if isinstance(df, pd.DataFrame) else [],
            "style_profile_path": str(settings.get("profile_path")),
            "report_pattern": report_pattern,
            "report_pattern_label": report_pattern_label,
            "repair_attempted": getattr(report, "repair_attempted", False),
            "repair_success": getattr(report, "repair_success", False),
            "repair_noop": getattr(report, "repair_noop", False),
            "repair_validation_warnings": getattr(report, "repair_validation_warnings", None),
            "fallback_used": getattr(report, "fallback_used", False),
            "fallback_validation_warnings": getattr(report, "fallback_validation_warnings", None),
            "final_validation_warnings": getattr(report, "final_validation_warnings", None),
            "report_generation_strategy": getattr(report, "report_generation_strategy", ""),
            "final_source": getattr(report, "final_source", ""),
            "raw_llm_attempted": getattr(report, "raw_llm_attempted", False),
            "raw_llm_validation_passed": getattr(report, "raw_llm_validation_passed", False),
            "raw_llm_rejected_reasons": getattr(report, "raw_llm_rejected_reasons", None),
            "repair_validation_passed": getattr(report, "repair_validation_passed", False),
            "final_validation_passed": getattr(report, "final_validation_passed", False),
            "llm_rewrite_attempted": getattr(report, "llm_rewrite_attempted", False),
            "llm_rewrite_success": getattr(report, "llm_rewrite_success", False),
            "llm_rewrite_validation_passed": getattr(report, "llm_rewrite_validation_passed", False),
            "report_regenerate_nonce": getattr(report, "report_regenerate_nonce", report_regenerate_nonce),
            "rewrite_similarity": getattr(report, "rewrite_similarity", None),
            "rewrite_retry_attempted": getattr(report, "rewrite_retry_attempted", False),
            "cache_hit": False,
            "reused_saved_report": False,
            "raw_generation_disabled_by_design": getattr(report, "raw_generation_disabled_by_design", True),
            "status_messages": getattr(report, "status_messages", None),
        }

        try:
            _write_qa_log(question, debug.get("answer", ""), debug, debug.get("filters") or {})
        except OSError:
            pass

        st.rerun()

    saved = st.session_state.get(report_key)
    if not saved:
        return
    debug["cache_hit"] = True
    debug["reused_saved_report"] = True
    debug["report_regenerate_nonce"] = saved.get("report_regenerate_nonce", report_regenerate_nonce)
    debug["rewrite_similarity"] = saved.get("rewrite_similarity")
    debug["rewrite_retry_attempted"] = saved.get("rewrite_retry_attempted", False)

    saved_mode_label = REPORT_MODE_LABELS.get(
        saved.get("mode"),
        saved.get("mode") or "Tự động chọn theo nội dung số liệu",
    )
    saved_pattern = saved.get("report_pattern", "overview_result")
    saved_pattern_label = REPORT_PATTERN_LABELS.get(saved_pattern, saved_pattern)
    final_text = str(saved.get("text") or "")
    word_count = len(re.findall(r"\b\w+\b", final_text, flags=re.UNICODE))
    final_source = str(saved.get("final_source") or "")
    source_label = {
        "llm_rewrite_from_safe_base": "LLM rewrite từ SAFE_BASE_TEXT",
        "facts_renderer_fallback": "Facts renderer an toàn",
    }.get(final_source, final_source or "Không xác định")
    validation_passed = bool(saved.get("final_validation_passed", False))
    validation_label = "đạt" if validation_passed else "chưa đạt"

    st.markdown("**Văn bản báo cáo nhận định**")
    _display_report_text_block(final_text)
    st.caption(
        f"Nguồn: {source_label} · Hậu kiểm: {validation_label} · "
        f"Pattern: {saved_pattern_label} · {word_count} từ"
    )
    if st.button("Tạo lại báo cáo", key=f"report_regenerate_{msg_idx}", use_container_width=True):
        st.session_state[nonce_key] = report_regenerate_nonce + 1
        st.session_state.pop(report_key, None)
        debug["report_text"] = None
        debug["report_prompt"] = None
        debug["report_repair_text"] = None
        debug["report_repair_prompt"] = None
        debug["report_regenerate_nonce"] = report_regenerate_nonce + 1
        debug["cache_hit"] = False
        debug["reused_saved_report"] = False
        st.session_state[visible_key] = True
        st.rerun()

    if saved.get("fallback_used", False):
        st.warning(
            "LLM rewrite không vượt hậu kiểm, hệ thống đã dùng bản facts renderer an toàn."
        )

    with st.expander("🔍 Chi tiết sinh báo cáo", expanded=False):
        tab_overview, tab_text, tab_facts, tab_prompt = st.tabs(
            ["Tổng quan", "Văn bản", "Facts", "Prompt"]
        )

        with tab_overview:
            overview = {
                "report_pattern": saved_pattern,
                "report_pattern_label": saved_pattern_label,
                "report_mode": saved.get("mode"),
                "report_mode_label": saved_mode_label,
                "final_source": final_source,
                "fallback_used": saved.get("fallback_used", False),
                "final_validation_passed": validation_passed,
                "llm_rewrite_attempted": saved.get("llm_rewrite_attempted", False),
                "llm_rewrite_success": saved.get("llm_rewrite_success", False),
                "llm_rewrite_validation_passed": saved.get("llm_rewrite_validation_passed", False),
                "report_regenerate_nonce": saved.get("report_regenerate_nonce"),
                "rewrite_similarity": saved.get("rewrite_similarity"),
                "rewrite_retry_attempted": saved.get("rewrite_retry_attempted", False),
                "cache_hit": debug.get("cache_hit", False),
                "reused_saved_report": debug.get("reused_saved_report", False),
                "repair_validation_warnings": saved.get("repair_validation_warnings") or [],
                "warnings": saved.get("warnings") or [],
                "status_messages": saved.get("status_messages") or [],
                "word_count": word_count,
            }
            st.json(overview)

        with tab_text:
            st.markdown("**Văn bản cuối**")
            _display_report_text_block(final_text)

            st.markdown("**Bản LLM rewrite**")
            if saved.get("repair_text"):
                st.code(saved.get("repair_text", ""), language="text")
            else:
                st.caption("Không có bản rewrite hoặc không gọi được LLM.")

            if saved.get("raw_llm_text"):
                st.markdown("**Raw LLM text**")
                st.code(saved.get("raw_llm_text", ""), language="text")

            st.markdown("**Warnings**")
            st.json({
                "warnings": saved.get("warnings") or [],
                "repair_validation_warnings": saved.get("repair_validation_warnings") or [],
            })

        with tab_facts:
            st.json(saved.get("report_facts") or {})

        with tab_prompt:
            st.markdown("**Prompt sinh báo cáo**")
            st.code(saved.get("prompt", ""), language="text")
            if saved.get("repair_prompt"):
                st.markdown("**Repair prompt**")
                st.code(saved.get("repair_prompt", ""), language="text")


def _render_assistant_turn(msg_idx: int, answer: str, debug: dict, *, enable_inline_report: bool = False):
    """Render 1 lượt trả lời tuần 4: câu trả lời, bảng, biểu đồ, debug."""
    result_df = debug.get("result_df")
    is_table = _is_table_result(debug) and isinstance(result_df, pd.DataFrame) and not result_df.empty

    is_direct_chart = bool(debug.get("chart_requested") and debug.get("chart_success"))

    plan = debug.get("query_plan") or {}
    task = plan.get("task")

    answer_has_markdown_table = _answer_has_markdown_table(answer)

    table_only_tasks = {"group_aggregate", "compare_years", "multi_metric_table"}
    report_source_df = result_df if isinstance(result_df, pd.DataFrame) and not result_df.empty else debug.get("chart_df")
    report_rendered = False

    def render_report_once() -> None:
        nonlocal report_rendered
        if report_rendered or not enable_inline_report:
            return
        if isinstance(report_source_df, pd.DataFrame) and not report_source_df.empty:
            _render_report_section(
                msg_idx,
                _safe_df(report_source_df),
                debug.get("question", ""),
                debug,
            )
            report_rendered = True

    if not is_direct_chart:
        if is_table and task in table_only_tasks:
            pass
        elif task == "lookup_person" and is_table:
            pass
        elif is_table and answer_has_markdown_table and task not in {"list_records", "lookup_person"}:
            pass
        else:
            st.markdown(answer)

    if is_table and not is_direct_chart:
        total_rows = len(result_df)
        display_limit = DISPLAY_LIMIT

        shown_rows = min(total_rows, display_limit)

        if task in {"list_records", "lookup_person"}:
            st.caption(f"📋 Tìm thấy {total_rows:,} dòng phù hợp. Hiển thị {shown_rows:,} dòng đầu tiên.")
        else:
            st.caption(f"📊 Bảng kết quả có {total_rows:,} dòng. Hiển thị {shown_rows:,} dòng đầu tiên.")

        st.dataframe(_prepare_display_df(result_df, display_limit), use_container_width=True, hide_index=True)
        _render_download_buttons(msg_idx, result_df, debug.get("question", ""), prefix="qa")
        render_report_once()

        if debug.get("chart_recommendation_visible") and not debug.get("chart_success"):
            chart_df = prepare_chart_df(_safe_df(result_df), debug.get("question", ""), debug.get("query_plan"))
            if is_chartable(chart_df):
                _render_recommended_chart_section(msg_idx, chart_df, debug.get("question", ""), debug)

    if debug.get("chart_success"):
        chart_fig = debug.get("chart_fig")
        chart_df = debug.get("chart_df")
        chart_debug = debug.get("chart_debug") or {}

        if is_direct_chart:
            st.markdown(answer)

        st.markdown("**📊 Biểu đồ kết quả**")

        if isinstance(chart_df, pd.DataFrame) and not chart_df.empty:
            st.caption(f"📊 Biểu đồ được tạo từ {len(chart_df):,} dòng dữ liệu.")

        if chart_fig is not None:
            st.plotly_chart(chart_fig, use_container_width=True, key=f"chart_workflow_{msg_idx}")

        if is_direct_chart:
            chart_table_df = debug.get("chart_table_df")
            if not isinstance(chart_table_df, pd.DataFrame) or chart_table_df.empty:
                chart_table_df = build_chart_display_df(chart_df, chart_debug, result_df)
            if isinstance(chart_table_df, pd.DataFrame) and not chart_table_df.empty:
                shown_rows = min(len(chart_table_df), DISPLAY_LIMIT)
                st.caption(f"📋 Dữ liệu dùng để vẽ biểu đồ: {len(chart_table_df):,} dòng. Hiển thị {shown_rows:,} dòng đầu tiên.")
                st.dataframe(
                    _prepare_display_df(chart_table_df, DISPLAY_LIMIT),
                    use_container_width=True,
                    hide_index=True,
                )
                _render_download_buttons(msg_idx, chart_table_df, debug.get("question", ""), prefix="chart")
            render_report_once()

    if not report_rendered:
        render_report_once()

    with st.expander("🔍 Chi tiết xử lý Q&A", expanded=False):
        debug_view = {
            k: v for k, v in debug.items()
            if k not in (
                "result_df",
                "question",
                "chart_fig",
                "chart_df",
                "chart_debug",
                "chart_plan",
                "chart_table_df",
            )
        }
        st.code(json.dumps(debug_view, ensure_ascii=False, indent=2, default=str), language="json")


# ── Refactor UI tuần 2+3 / tuần 4 / tuần 5 ────────────────────────────────
TASK_MODE_OPTIONS = {
    "Q&A": "week23",
    "Báo cáo": "report",
}


def _template_options(include_extended: bool = False) -> dict[str, int]:
    """Danh sách mẫu báo cáo chính thức.

    UI mặc định chỉ hiện 12 mẫu đúng yêu cầu task. Mẫu 13 trong catalog được giữ
    như mẫu mở rộng để không phá code cũ, nhưng không đưa vào luồng chính nếu
    người dùng không bật tùy chọn mở rộng.
    """
    items = []
    for item in list_report_templates():
        template_id = int(item["id"])
        if include_extended or template_id <= 12:
            items.append(item)
    return {f"{item['id']}. {item['title']}": int(item["id"]) for item in items}


def _resolve_template_id(label: str | None) -> int:
    options = _template_options(include_extended=True)
    if label in options:
        return options[label]
    return 1


def _safe_scope_label(filters: dict[str, Any]) -> str:
    if filters.get("huyen") and filters.get("nam"):
        return f"{filters['huyen']} — {filters['nam']}"
    if filters.get("huyen"):
        return str(filters["huyen"])
    if filters.get("nam"):
        return f"năm {filters['nam']}"
    return "Toàn tỉnh / năm mới nhất khi sinh báo cáo"


def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _numeric_cols(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


def _build_template_chart(bundle: Any) -> tuple[Any | None, pd.DataFrame | None, str | None]:
    """Tạo biểu đồ minh họa cho báo cáo hành chính từ fact bundle 12 mẫu chính thức.

    Hàm này độc lập với chart_utils/app3 để tránh phá rule biểu đồ Q&A tuần 3.
    """
    if px is None:
        return None, None, "Chưa import được plotly.express."

    try:
        tables = getattr(bundle, "tables", {}) or {}
        if isinstance(tables.get("template_chart"), pd.DataFrame) and not tables.get("template_chart").empty:
            main_df = tables.get("template_chart").copy()
        elif isinstance(tables.get("template_main"), pd.DataFrame) and not tables.get("template_main").empty:
            main_df = tables.get("template_main").copy()
        else:
            main_df = bundle_main_table(bundle)
    except Exception:
        main_df = bundle.tables.get("template_chart", bundle.tables.get("template_main", bundle.tables.get("main", pd.DataFrame()))).copy()

    if not isinstance(main_df, pd.DataFrame) or main_df.empty:
        return None, None, "Bảng số liệu rỗng nên không tạo biểu đồ."

    template = getattr(bundle, "template", {}) or {}
    title = str(template.get("title") or "Biểu đồ minh họa")
    pattern = str(template.get("pattern") or "")
    recommended = str(template.get("recommended_chart") or "bar")

    df = main_df.copy()

    try:
        if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(df.columns):
            nam_truoc = int(df["nam_truoc"].dropna().iloc[0]) if "nam_truoc" in df.columns and not df["nam_truoc"].dropna().empty else "Kỳ trước"
            nam_sau = int(df["nam_sau"].dropna().iloc[0]) if "nam_sau" in df.columns and not df["nam_sau"].dropna().empty else "Kỳ sau"
            if "huyen" in df.columns and df["huyen"].nunique(dropna=True) > 1:
                top = df.copy()
                top["tong_hai_ky"] = top["so_ho_ky_truoc"].fillna(0) + top["so_ho_ky_sau"].fillna(0)
                top = top.sort_values("tong_hai_ky", ascending=False).head(12)
                chart_df = top[["huyen", "so_ho_ky_truoc", "so_ho_ky_sau"]].rename(columns={
                    "huyen": "Địa bàn",
                    "so_ho_ky_truoc": str(nam_truoc),
                    "so_ho_ky_sau": str(nam_sau),
                })
                long_df = chart_df.melt(id_vars=["Địa bàn"], var_name="Năm", value_name="Số hộ")
                fig = px.bar(long_df, x="Địa bàn", y="Số hộ", color="Năm", barmode="group", title=title)
                fig.update_layout(title_text="", xaxis_title="Địa bàn", yaxis_title="Số hộ")
                return fig, long_df, None
            chart_df = pd.DataFrame({
                "Năm": [str(nam_truoc), str(nam_sau)],
                "Số hộ": [int(df["so_ho_ky_truoc"].sum()), int(df["so_ho_ky_sau"].sum())],
            })
            fig = px.line(chart_df, x="Năm", y="Số hộ", markers=True, title=title)
            fig.update_layout(title_text="", xaxis_title="Năm", yaxis_title="Số hộ")
            return fig, chart_df, None

        label_col = _first_existing_col(df, ["chi_tieu", "nhom_chi_tieu", "huyen", "phan_loai", "dan_toc"])
        if label_col is None:
            object_cols = [col for col in df.columns if not pd.api.types.is_numeric_dtype(df[col])]
            label_col = object_cols[0] if object_cols else df.columns[0]

        facts = getattr(bundle, "facts", {}) or {}
        chart_hint = facts.get("chart_insights") if isinstance(facts, dict) else {}
        hinted_label_col = chart_hint.get("label_col") if isinstance(chart_hint, dict) else None
        hinted_value_col = chart_hint.get("value_col") if isinstance(chart_hint, dict) else None
        if hinted_label_col in df.columns:
            label_col = hinted_label_col

        if pattern == "deprivation_ratio":
            value_candidates = ["ty_le_%", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "so_ho"]
        elif pattern in {"vulnerable_groups", "ethnicity", "causes", "child_deprivation"}:
            value_candidates = ["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho", "so_ho"]
        elif pattern == "multidimensional_standard":
            value_candidates = ["so_ho_muc_tieu", "ty_le_muc_tieu_%", "tong_ho_ra_soat"]
        else:
            value_candidates = ["so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "tong_ho", "tong_ho_dan_cu", "so_ho_muc_tieu"]
        if hinted_value_col in df.columns:
            value_candidates = [hinted_value_col] + [c for c in value_candidates if c != hinted_value_col]

        value_col = _first_existing_col(df, value_candidates)
        if value_col is None:
            nums = _numeric_cols(df)
            value_col = nums[0] if nums else None
        if value_col is None:
            return None, None, "Không tìm thấy cột số để vẽ biểu đồ."

        chart_df = df[[label_col, value_col]].dropna().copy()
        chart_df = chart_df.sort_values(value_col, ascending=False).head(15)
        if chart_df.empty:
            return None, None, "Bảng biểu đồ rỗng sau khi lọc dữ liệu."

        if recommended == "pie" and len(chart_df) <= 8:
            fig = px.pie(chart_df, names=label_col, values=value_col, title=title)
        else:
            fig = px.bar(chart_df, x=label_col, y=value_col, title=title)
        fig.update_layout(title_text="", xaxis_title=str(label_col), yaxis_title=str(value_col))
        return fig, chart_df, None
    except Exception as exc:
        return None, None, f"Không tạo được biểu đồ minh họa: {exc}"




def _report_table_items(bundle: Any) -> list[dict[str, Any]]:
    """Các bảng chính hiển thị trong tab Bảng số liệu.

    Không đưa bảng kỹ thuật/gốc gây lẫn nguồn vào UI chính. Với mẫu 1, hiển thị
    đúng hai bảng nghiệp vụ: bảng tổng hợp nhóm hộ và bảng chi tiết theo địa bàn.
    """
    tables = getattr(bundle, "tables", {}) or {}
    template = getattr(bundle, "template", {}) or {}
    try:
        template_id = int(template.get("id") or 0)
    except Exception:
        template_id = 0

    def _nonempty(name: str) -> pd.DataFrame | None:
        df = tables.get(name) if isinstance(tables, dict) else None
        return df if isinstance(df, pd.DataFrame) and not df.empty else None

    items: list[dict[str, Any]] = []
    if template_id == 1:
        summary_df = _nonempty("template_chart")
        detail_df = _nonempty("template_main")
        if summary_df is not None:
            items.append({"name": "template_chart", "title": "Bảng tổng hợp nhóm hộ", "df": summary_df})
        if detail_df is not None:
            items.append({"name": "template_main", "title": "Bảng chi tiết theo địa bàn", "df": detail_df})
        if items:
            return items

    template_df = _nonempty("template_main")
    main_df = _nonempty("main")
    district_df = _nonempty("by_district")
    if template_df is not None:
        items.append({"name": "template_main", "title": "Bảng số liệu báo cáo", "df": template_df})
    elif main_df is not None:
        items.append({"name": "main", "title": "Bảng số liệu báo cáo", "df": main_df})
    if district_df is not None:
        # Chỉ thêm bảng địa bàn khi nó không trùng bảng chính.
        first_df = items[0]["df"] if items else None
        if not isinstance(first_df, pd.DataFrame) or list(first_df.columns) != list(district_df.columns) or len(first_df) != len(district_df):
            items.append({"name": "by_district", "title": "Bảng tổng hợp theo địa bàn", "df": district_df})
    return items


def _chart_label_for_column(col: str) -> str:
    labels = {
        "huyen": "Địa bàn",
        "chi_tieu": "Chỉ tiêu",
        "dan_toc": "Dân tộc",
        "phan_loai": "Nhóm hộ",
        "nhom_chi_tieu": "Nhóm chỉ tiêu",
        "so_ho": "Số hộ",
        "tong_ho": "Tổng số hộ",
        "tong_ho_dan_cu": "Tổng số hộ dân cư",
        "so_ho_ngheo": "Hộ nghèo",
        "so_ho_can_ngheo": "Hộ cận nghèo",
        "so_ho_nlnndn_mstb": "Hộ nông, lâm, ngư nghiệp có mức sống trung bình",
        "so_ho_muc_tieu": "Số hộ mục tiêu",
        "ty_le_%": "Tỷ lệ (%)",
        "ty_le_muc_tieu_%": "Tỷ lệ (%)",
    }
    return labels.get(str(col), str(col).replace("_", " "))


def _chart_value_columns_for_df(df: pd.DataFrame, table_name: str, pattern: str) -> list[str]:
    cols = set(df.columns)
    if table_name == "template_chart" and {"nhom_chi_tieu", "so_ho"}.issubset(cols):
        return ["so_ho"]
    if {"so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"}.issubset(cols):
        return ["so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"]
    if pattern == "movement" and {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(cols):
        return ["so_ho_ky_truoc", "so_ho_ky_sau"]
    if {"so_ho_ngheo", "so_ho_can_ngheo"}.issubset(cols):
        return ["so_ho_ngheo", "so_ho_can_ngheo"]
    if pattern == "deprivation_ratio" and "ty_le_%" in cols:
        return ["ty_le_%"]
    for candidates in (["so_ho"], ["so_ho_muc_tieu"], ["tong_ho"], ["tong_ho_ra_soat"], ["ty_le_muc_tieu_%"]):
        usable = [c for c in candidates if c in cols]
        if usable:
            return usable
    return _numeric_cols(df)[:1]


def _build_chart_item_from_table(item: dict[str, Any], bundle: Any) -> dict[str, Any] | None:
    if px is None:
        return None
    df = item.get("df")
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    template = getattr(bundle, "template", {}) or {}
    pattern = str(template.get("pattern") or "")
    table_name = str(item.get("name") or "")
    label_col = _first_existing_col(df, ["huyen", "chi_tieu", "dan_toc", "phan_loai", "nhom_chi_tieu"])
    if label_col is None:
        object_cols = [col for col in df.columns if not pd.api.types.is_numeric_dtype(df[col])]
        label_col = object_cols[0] if object_cols else df.columns[0]
    value_cols = _chart_value_columns_for_df(df, table_name, pattern)
    value_cols = [c for c in value_cols if c in df.columns]
    if not value_cols:
        return None

    chart_title = "Biểu đồ " + str(item.get("title") or "số liệu báo cáo").lower()
    chart_source = str(item.get("title") or table_name)

    try:
        work = df[[label_col] + value_cols].copy()
        for col in value_cols:
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
        if len(value_cols) > 1:
            work["__sort_total"] = work[value_cols].sum(axis=1)
            work = work.sort_values("__sort_total", ascending=False).head(12)
            long_df = work[[label_col] + value_cols].melt(id_vars=[label_col], var_name="Nhóm chỉ tiêu", value_name="Số hộ")
            long_df["Nhóm chỉ tiêu"] = long_df["Nhóm chỉ tiêu"].map(_chart_label_for_column)
            long_df = long_df.rename(columns={label_col: _chart_label_for_column(label_col)})
            x_col = _chart_label_for_column(label_col)
            fig = px.bar(long_df, x=x_col, y="Số hộ", color="Nhóm chỉ tiêu", barmode="group", title=chart_title)
            fig.update_layout(title_text="", xaxis_title=x_col, yaxis_title="Số hộ")
            return {"source_table": table_name, "title": chart_title, "description": chart_source, "fig": fig, "chart_df": long_df}

        value_col = value_cols[0]
        work = work.sort_values(value_col, ascending=False).head(15)
        display_df = work.rename(columns={label_col: _chart_label_for_column(label_col), value_col: _chart_label_for_column(value_col)})
        x_col = _chart_label_for_column(label_col)
        y_col = _chart_label_for_column(value_col)
        recommended = str(template.get("recommended_chart") or "bar")
        if recommended == "pie" and len(display_df) <= 8:
            fig = px.pie(display_df, names=x_col, values=y_col, title=chart_title)
        else:
            fig = px.bar(display_df, x=x_col, y=y_col, title=chart_title)
        fig.update_layout(title_text="", xaxis_title=x_col, yaxis_title=y_col)
        return {"source_table": table_name, "title": chart_title, "description": chart_source, "fig": fig, "chart_df": display_df}
    except Exception:
        return None


def _build_report_chart_items(bundle: Any, table_items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Tạo một biểu đồ đối chiếu cho mỗi bảng đang hiển thị trong tab Bảng số liệu."""
    if px is None:
        return []
    table_items = table_items if table_items is not None else _report_table_items(bundle)
    chart_items: list[dict[str, Any]] = []
    for item in table_items:
        chart_item = _build_chart_item_from_table(item, bundle)
        if chart_item is not None:
            chart_items.append(chart_item)
    return chart_items


def _chart_items_log_payload(chart_items: list[dict[str, Any]], max_rows: int = 1000) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for idx, item in enumerate(chart_items or [], start=1):
        chart_df = item.get("chart_df")
        payload.append({
            "index": idx,
            "source_table": item.get("source_table"),
            "title": item.get("title"),
            "description": item.get("description"),
            "chart_kind": _infer_chart_kind_from_fig(item.get("fig")),
            "chart_df": _dataframe_log_payload(chart_df, max_rows=max_rows) if isinstance(chart_df, pd.DataFrame) else None,
        })
    return payload

def _prepare_word_export_fig(fig: Any | None) -> tuple[Any | None, str | None]:
    """Clone và chuẩn hóa Plotly figure trước khi xuất ảnh Word.

    Lưu ý: không gọi Kaleido trong hàm này. Kaleido chỉ được gọi ở các hàm
    export bên dưới để kiểm soát chính xác số lần Chrome/Kaleido bật lên.
    """
    if fig is None:
        return None, "Không có biểu đồ để chuyển thành ảnh."
    try:
        # Ảnh đưa vào Word cần chữ lớn hơn UI. Clone figure trước khi chỉnh để
        # không làm thay đổi biểu đồ đang hiển thị trong Streamlit.
        try:
            export_fig = fig.full_copy()
        except Exception:
            try:
                import copy
                export_fig = copy.deepcopy(fig)
            except Exception:
                export_fig = fig

        try:
            export_fig.update_layout(
                font=dict(size=18),
                legend=dict(font=dict(size=16), title_font=dict(size=16)),
                margin=dict(l=80, r=45, t=45, b=95),
                width=1600,
                height=920,
            )
            export_fig.update_xaxes(title_font=dict(size=18), tickfont=dict(size=15), automargin=True)
            export_fig.update_yaxes(title_font=dict(size=18), tickfont=dict(size=15), automargin=True)
            # Nếu có nhãn/annotation, tăng font để khi chèn vào Word không bị nhỏ.
            anns = list(getattr(export_fig.layout, "annotations", []) or [])
            for ann in anns:
                try:
                    ann.font.size = max(int(getattr(ann.font, "size", 0) or 0), 15)
                except Exception:
                    pass
        except Exception:
            pass
        return export_fig, None
    except Exception as exc:
        return None, f"Không chuẩn hóa được biểu đồ trước khi xuất Word. Chi tiết: {exc}"


def _figure_to_png_bytes(fig: Any | None) -> tuple[bytes | None, str | None]:
    _configure_plotly_kaleido_export()
    export_fig, prep_error = _prepare_word_export_fig(fig)
    if prep_error:
        return None, prep_error

    # Ưu tiên Kaleido v1 trực tiếp với Chromium wrapper ẩn cửa sổ.
    try:
        with tempfile.TemporaryDirectory(prefix="plotly_word_hidden_single_") as tmp_dir:
            image_path = Path(tmp_dir) / "chart_0.png"
            ok, hidden_error = _hidden_kaleido_v1_write_figs_to_paths([export_fig], [image_path])
            if ok and image_path.exists():
                return image_path.read_bytes(), None
    except Exception:
        hidden_error = None

    try:
        return export_fig.to_image(format="png", width=1600, height=920, scale=2), None
    except Exception as exc:
        detail = f"Chi tiết: {exc}"
        try:
            if hidden_error:
                detail = f"Chi tiết hidden-export: {hidden_error}; fallback: {exc}"
        except Exception:
            pass
        return None, (
            "Không xuất được ảnh biểu đồ từ Plotly. "
            "Cài/cập nhật kaleido nếu muốn nhúng biểu đồ vào Word: pip install --upgrade kaleido. "
            f"{detail}"
        )


def _figures_to_png_bytes_batch(figs: list[Any]) -> tuple[list[bytes | None], str | None]:
    """Xuất nhiều Plotly figure sang PNG bằng một lần gọi Kaleido nếu có thể.

    Với Plotly/Kaleido mới, plotly.io.write_images(...) nhanh hơn và thường
    tránh việc Chrome/Kaleido bật lên nhiều lần. Nếu môi trường không hỗ trợ
    batch thì fallback từng hình, nhưng app vẫn không export trùng chart_fig.
    """
    _configure_plotly_kaleido_export()
    if not figs:
        return [], None

    prepared_figs: list[Any] = []
    first_error: str | None = None
    for fig in figs:
        export_fig, prep_error = _prepare_word_export_fig(fig)
        if prep_error:
            prepared_figs.append(None)
            if not first_error:
                first_error = prep_error
        else:
            prepared_figs.append(export_fig)

    results: list[bytes | None] = [None] * len(prepared_figs)
    valid_positions = [idx for idx, fig in enumerate(prepared_figs) if fig is not None]
    valid_figs = [prepared_figs[idx] for idx in valid_positions]
    if not valid_figs:
        return results, first_error or "Không có biểu đồ hợp lệ để chuyển thành ảnh."

    # Ưu tiên Kaleido v1 trực tiếp với Chromium wrapper ẩn cửa sổ.
    # Khác với pio.write_images, nhánh này truyền được `browser_cls` vào Choreographer.
    try:
        with tempfile.TemporaryDirectory(prefix="plotly_word_hidden_batch_") as tmp_dir:
            image_paths = [Path(tmp_dir) / f"chart_{idx}.png" for idx in range(len(valid_figs))]
            ok, hidden_error = _hidden_kaleido_v1_write_figs_to_paths(valid_figs, image_paths)
            if ok:
                for pos, image_path in zip(valid_positions, image_paths):
                    results[pos] = image_path.read_bytes()
                return results, first_error
            first_error = first_error or hidden_error
    except Exception as exc:
        first_error = first_error or f"Không xuất được ảnh biểu đồ bằng Kaleido v1 hidden mode. Chi tiết: {exc}"

    # Fallback: batch export của Plotly/Kaleido mới để giảm số lần Chrome/Kaleido hiện cửa sổ.
    try:
        import plotly.io as pio
        write_images = getattr(pio, "write_images", None)
        if callable(write_images):
            # Theo API Plotly mới, write_images nhận danh sách path, không dựa vào BytesIO.
            # Ghi file tạm rồi đọc bytes giúp batch thực sự chạy qua một lệnh Kaleido.
            with tempfile.TemporaryDirectory(prefix="plotly_word_export_") as tmp_dir:
                image_paths = [Path(tmp_dir) / f"chart_{idx}.png" for idx in range(len(valid_figs))]
                write_images(
                    fig=valid_figs,
                    file=image_paths,
                    format="png",
                    width=1600,
                    height=920,
                    scale=2,
                )
                for pos, image_path in zip(valid_positions, image_paths):
                    results[pos] = image_path.read_bytes()
            return results, first_error
    except Exception as exc:
        first_error = first_error or (
            "Không xuất được ảnh biểu đồ theo batch bằng Plotly/Kaleido mới; "
            f"đã thử fallback từng biểu đồ. Chi tiết batch: {exc}"
        )

    # Fallback tương thích môi trường cũ: vẫn xuất từng hình, nhưng không xuất lặp chart_fig.
    for pos in valid_positions:
        png_bytes, png_error = _figure_to_png_bytes(prepared_figs[pos])
        results[pos] = png_bytes
        if png_error and not first_error:
            first_error = png_error
    return results, first_error


def _export_report_docx_with_chart(bundle: Any, report_text: str, chart_png_bytes: bytes | None = None) -> bytes:
    """Xuất Word tuần 5: nhận định + biểu đồ minh họa + bảng số liệu.

    Không sửa report_exporter.py để tránh phá API cũ; app4 tự bọc phần Word có chart.
    """
    try:
        from docx import Document
        from docx.shared import Inches, Pt
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Chưa cài python-docx. Cài bằng: pip install python-docx") from exc

    doc = Document()
    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(13)

    template = getattr(bundle, "template", {}) or {}
    scope = getattr(bundle, "scope", {}) or {}

    doc.add_heading(str(template.get("title") or "Báo cáo"), level=0)
    p = doc.add_paragraph()
    p.add_run("Mẫu báo cáo: ").bold = True
    p.add_run(str(template.get("code") or template.get("id") or ""))
    p = doc.add_paragraph()
    p.add_run("Phạm vi: ").bold = True
    p.add_run(str(scope.get("scope_label") or ""))

    doc.add_heading("I. Văn bản báo cáo nhận định", level=1)
    for para in str(report_text).split("\n"):
        line = para.strip()
        if not line:
            continue
        if line.startswith("BÁO CÁO"):
            continue
        if re.match(r"^[IVX]+\.", line):
            doc.add_heading(line, level=2)
        else:
            doc.add_paragraph(line)

    doc.add_heading("II. Biểu đồ minh họa", level=1)
    if chart_png_bytes:
        doc.add_picture(BytesIO(chart_png_bytes), width=Inches(6.4))
    else:
        doc.add_paragraph(
            "Chưa nhúng được ảnh biểu đồ trong môi trường hiện tại. "
            "Bảng số liệu đối chiếu vẫn được đưa vào phần tiếp theo."
        )

    doc.add_heading("III. Bảng số liệu đối chiếu", level=1)
    tables = getattr(bundle, "tables", {}) or {}
    for name, df in tables.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        doc.add_heading(str(name), level=2)
        show = _prepare_export_df(df).head(30)
        table = doc.add_table(rows=1, cols=len(show.columns))
        table.style = "Table Grid"
        for idx, col in enumerate(show.columns):
            table.rows[0].cells[idx].text = str(col)
        for _, row in show.iterrows():
            cells = table.add_row().cells
            for idx, col in enumerate(show.columns):
                cells[idx].text = "" if pd.isna(row[col]) else str(row[col])

    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()



# ── Deep verification log cho báo cáo hành chính ────────────────────────────
def _clean_json_scalar(value: Any) -> Any:
    """Chuẩn hóa scalar để ghi JSONL ổn định, dễ gửi để hậu kiểm."""
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _json_safe(obj: Any) -> Any:
    """Chuyển object lồng nhau sang dạng JSON-safe nhưng không làm mất nội dung chính."""
    if isinstance(obj, pd.DataFrame):
        return _dataframe_log_payload(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return _clean_json_scalar(obj)


def _dataframe_log_payload(df: pd.DataFrame | None, max_rows: int = 1000) -> dict[str, Any] | None:
    """Ghi cả sample/records và tổng numeric để đối chiếu nhanh bảng báo cáo."""
    if df is None or not isinstance(df, pd.DataFrame):
        return None
    safe_df = df.copy()
    try:
        safe_df = safe_df.where(pd.notna(safe_df), None)
    except Exception:
        pass

    records = safe_df.head(max_rows).to_dict(orient="records")
    numeric_totals: dict[str, Any] = {}
    numeric_min: dict[str, Any] = {}
    numeric_max: dict[str, Any] = {}
    for col in df.columns:
        try:
            series = pd.to_numeric(df[col], errors="coerce")
            if series.notna().any():
                total = series.sum(skipna=True)
                min_value = series.min(skipna=True)
                max_value = series.max(skipna=True)
                numeric_totals[str(col)] = int(total) if float(total).is_integer() else round(float(total), 4)
                numeric_min[str(col)] = int(min_value) if float(min_value).is_integer() else round(float(min_value), 4)
                numeric_max[str(col)] = int(max_value) if float(max_value).is_integer() else round(float(max_value), 4)
        except Exception:
            continue

    return {
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "records": _json_safe(records),
        "records_limit": int(max_rows),
        "records_truncated": bool(len(df) > max_rows),
        "numeric_totals": numeric_totals,
        "numeric_min": numeric_min,
        "numeric_max": numeric_max,
    }


def _extract_numbers_for_review(text: str, max_items: int = 300) -> list[str]:
    """Trích các số xuất hiện trong văn bản để hậu kiểm nhanh với bảng/facts."""
    raw = str(text or "")
    found = re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.\,]*(?:\s*%)?", raw)
    cleaned: list[str] = []
    for item in found:
        value = item.strip()
        if value and value not in cleaned:
            cleaned.append(value)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _report_task_log_path() -> Path:
    """Đường dẫn log duy nhất cho UI Báo cáo: logs/report_task_YYYYMMDD.jsonl."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"report_task_{datetime.now().strftime('%Y%m%d')}.jsonl"




def _review_norm_num(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[^0-9,\.]", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            text = "".join(parts)
    return text.strip(".")


def _review_num_variants(value: Any) -> set[str]:
    out: set[str] = set()
    try:
        n = float(value)
        if abs(n - int(n)) < 1e-9:
            out.add(str(int(n)))
            out.add(f"{int(n):,}".replace(",", "."))
        else:
            out.add(str(n).rstrip("0").rstrip("."))
            out.add(str(n).replace(".", ","))
            out.add(f"{n:.2f}")
            out.add(f"{n:.2f}".replace(".", ","))
    except Exception:
        out.add(str(value))
    return {_review_norm_num(v) for v in out if v is not None and str(v)}


def _review_sentence_units(text: str) -> list[str]:
    # Không tách dấu chấm trong số hàng nghìn như 1.206; tách "và 917 hộ cận nghèo" để kiểm đúng từng chỉ tiêu.
    parts = re.split(
        r"(?:\n+|(?<!\d)[.;!?](?!\d)|,\s+(?:và|còn|đồng thời)\s+|\s+và\s+(?=\d|[A-ZĐ]))",
        str(text or ""),
    )
    return [p.strip() for p in parts if p and p.strip()]


def _review_measure_present(unit: str, col: str) -> bool:
    t = str(unit or "").lower()
    c = str(col)
    # Mẫu diễn biến 2/3: tách đầu kỳ/cuối kỳ/chênh lệch để không gán nhầm số âm giảm vào số hộ kỳ trước/sau.
    if c == "so_ho_ky_truoc":
        return "kỳ trước" in t or "đầu kỳ" in t or "dau ky" in t or "năm trước" in t
    if c == "so_ho_ky_sau":
        return "kỳ sau" in t or "cuối kỳ" in t or "cuoi ky" in t or "năm sau" in t
    if c.startswith("giam_"):
        return "giảm" in t or "thoát" in t or "vượt chuẩn" in t
    if c.startswith("tang_"):
        return "tăng" in t or "phát sinh" in t or "tái" in t or "trở thành" in t
    if c == "so_nhan_khau_muc_tieu":
        return "nhân khẩu" in t or "khẩu" in t
    if c == "ty_le_muc_tieu_%":
        return "%" in t or "tỷ lệ" in t or "tổng hộ rà soát" in t
    if c == "ty_le_dtts_trong_nhom_%":
        return "dtts" in t or "dân tộc thiểu số" in t or "thiểu số" in t
    if c == "ty_le_dtts_tai_cho_trong_dtts_%":
        return "tại chỗ" in t or "dtts tại chỗ" in t or "dân tộc thiểu số tại chỗ" in t
    if c == "so_ho_ngheo":
        return "hộ nghèo" in t and "hộ cận nghèo" not in t
    if c == "so_ho_can_ngheo":
        return "hộ cận nghèo" in t
    if c == "so_ho_nlnndn_mstb":
        return "nông" in t and "lâm" in t and "ngư" in t and "mức sống trung bình" in t
    if c == "tong_ho_dan_cu":
        return "tổng số hộ" in t or "tổng hộ" in t or "hộ dân cư" in t
    if c in {"so_khau_ngheo", "so_khau_can_ngheo", "so_khau_nlnndn_mstb", "tong_nhan_khau", "so_nhan_khau"}:
        return "khẩu" in t or "nhân khẩu" in t
    if c.startswith("ty_le") or c.startswith("ti_le") or "%" in c:
        if c not in {"ty_le_%", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "ty_le_muc_tieu_%"}:
            label = REPORT_COLUMN_LABELS.get(c, c).lower()
            return label and label != c.lower() and label in t
        return "tỷ lệ" in t or "%" in t or "phần trăm" in t
    if c.startswith("chenh_lech") or c.startswith("delta"):
        return "chênh lệch" in t or "tăng" in t or "giảm" in t or "biến động" in t
    try:
        label = REPORT_COLUMN_LABELS.get(c, c).lower()
        if label != c.lower() and label in t:
            return True
    except Exception:
        pass
    if c.startswith("so_ho") and c in {"so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "so_ho_muc_tieu"} and "hộ" in t:
        return True
    if c.startswith("so_") and not c.startswith("so_ho") and ("số " in t or "số lượng" in t):
        return True
    if c.startswith("tong_") and ("tổng số" in t or "tổng hộ" in t or "tổng nhân khẩu" in t):
        return True
    return False


def _review_unit_has_superlative_claim(unit: str) -> bool:
    return bool(re.search(r"\b(cao nhất|lớn nhất|nhiều nhất|đứng đầu|dẫn đầu|xếp đầu|vị trí lớn nhất|quy mô lớn nhất)\b", str(unit or "").lower()))


def _review_allowed_numbers_from_payload(payload: dict[str, Any]) -> set[str]:
    allowed = {"2023", "2024", "2025", "2026"}

    def add(v: Any, depth: int = 0) -> None:
        if depth > 8 or v is None or isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            allowed.update(_review_num_variants(v))
            return
        if isinstance(v, str):
            for n in re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.\,]*(?:\s*%)?", v):
                nn = _review_norm_num(n)
                if nn:
                    allowed.add(nn)
            return
        if isinstance(v, dict):
            for vv in v.values():
                add(vv, depth + 1)
            return
        if isinstance(v, list):
            for vv in v:
                add(vv, depth + 1)
            return

    for key in ("scope", "bundle", "report_tables", "charts"):
        add(payload.get(key))
    return allowed


def _review_extra_number_warnings(report_text: str, payload: dict[str, Any]) -> list[str]:
    allowed = _review_allowed_numbers_from_payload(payload)
    raw_nums = re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.\,]*(?:\s*%)?", report_text or "")
    nums = {_review_norm_num(x) for x in raw_nums if x}
    harmless_small = {str(i) for i in range(1, 13)}
    extra = sorted(n for n in nums if n and n not in allowed and n not in harmless_small)
    if extra:
        return ["Văn bản có số liệu ngoài nguồn hoặc số tự tính chưa kiểm chứng: " + ", ".join(extra[:8])]
    return []


def _review_pair_present(report_text: str, label: Any, value: Any) -> bool:
    label_text = str(label or "").strip().lower()
    if not label_text:
        return False
    expected = _review_num_variants(value)
    expected.discard("")
    if not expected:
        return False
    for unit in _review_sentence_units(report_text):
        if label_text not in unit.lower():
            continue
        raw_nums = re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.,]*(?:\s*%)?", unit)
        nums = {_review_norm_num(x) for x in raw_nums if x}
        if nums & expected:
            return True
    return False


def _review_required_pair_coverage_warnings(report_text: str, report_tables: list[dict[str, Any]], *, template_id: int | str | None = None, template_pattern: str | None = None) -> list[str]:
    """Cảnh báo khi văn bản không giữ đủ cặp nhãn-số nổi bật từ bảng báo cáo."""
    chosen = None
    for item in report_tables or []:
        if item.get("name") in {"template_main", "main", "by_district"}:
            chosen = item
            break
    if not chosen:
        return []
    data = chosen.get("data") or {}
    rows = data.get("records") or []
    cols = data.get("columns") or []
    if not rows or not cols:
        return []
    label_col = None
    for c in cols:
        if any(isinstance((r or {}).get(c), str) for r in rows):
            label_col = c
            break
    if not label_col:
        label_col = cols[0]
    numeric_cols = []
    for c in cols:
        if c == label_col:
            continue
        vals = [(r or {}).get(c) for r in rows]
        if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            numeric_cols.append(c)
    pattern = str(template_pattern or "").lower()
    try:
        tid = int(template_id or 0)
    except Exception:
        tid = 0
    def _is_count_col(c: Any) -> bool:
        cc = str(c).lower()
        return (cc.startswith("so_ho") or cc in {"so_ho", "tong_ho", "so_tre_em"}) and "khau" not in cc and "nhan_khau" not in cc
    def _is_ratio_col(c: Any) -> bool:
        cc = str(c).lower()
        return "ty_le" in cc or "ti_le" in cc or cc.endswith("_%") or "rate" in cc
    def _is_delta_col(c: Any) -> bool:
        cc = str(c).lower()
        return "chenh_lech" in cc or "delta" in cc or "bien_dong" in cc or "tang_giam" in cc
    # Chọn cột trọng tâm đúng theo mẫu để auto-review không báo sai giả.
    if tid in {5, 7} or pattern == "deprivation_ratio":
        preferred = [c for c in numeric_cols if _is_ratio_col(c)]
    elif tid in {4, 6} or pattern == "deprivation_count":
        preferred = [c for c in numeric_cols if _is_count_col(c)]
    elif tid == 11 or pattern == "child_deprivation":
        preferred = [c for c in numeric_cols if str(c) in {"so_ho_ngheo", "so_ho_can_ngheo", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%"}]
    elif tid == 12 or pattern == "multidimensional_standard":
        preferred = [c for c in numeric_cols if str(c) in {"so_ho_muc_tieu", "ty_le_muc_tieu_%", "tong_ho_ra_soat"}]
    elif tid in {2, 3} or pattern == "movement":
        preferred = [c for c in numeric_cols if _is_delta_col(c)] or [c for c in numeric_cols if str(c) in {"so_ho_ky_truoc", "so_ho_ky_sau"}]
    else:
        preferred = [c for c in numeric_cols if _is_count_col(c)] or [c for c in numeric_cols if _is_ratio_col(c)] or [c for c in numeric_cols if _is_delta_col(c)]
    numeric_cols = preferred or numeric_cols
    required = []
    for c in numeric_cols[:4]:
        try:
            best = max(rows, key=lambda r: float((r or {}).get(c) or 0))
            value = (best or {}).get(c)
            if float(value or 0) == 0:
                continue
            label = str((best or {}).get(label_col) or "").strip()
            if label:
                pair = (label, c, value)
                if pair not in required:
                    required.append(pair)
        except Exception:
            continue
        if len(required) >= 4:
            break
    if not required:
        return []
    present = [pair for pair in required if _review_pair_present(report_text, pair[0], pair[2])]
    min_required = 1
    if len(present) < min_required:
        def _coverage_col_label(col: Any) -> str:
            c = str(col)
            if tid == 11 or pattern == "child_deprivation":
                child_labels = {
                    "so_ho_ngheo": "Số trẻ thuộc hộ nghèo",
                    "ty_le_ho_ngheo_%": "Tỷ lệ trên tổng trẻ hộ nghèo (%)",
                    "so_ho_can_ngheo": "Số trẻ thuộc hộ cận nghèo",
                    "ty_le_ho_can_ngheo_%": "Tỷ lệ trên tổng trẻ hộ cận nghèo (%)",
                }
                return child_labels.get(c, REPORT_COLUMN_LABELS.get(c, c))
            if tid == 12 or pattern == "multidimensional_standard":
                md_labels = {
                    "tong_ho_ra_soat": "Tổng hộ đã rà soát/phân loại",
                    "so_ho_muc_tieu": "Số hộ nghèo đa chiều",
                    "ty_le_muc_tieu_%": "Tỷ lệ hộ nghèo đa chiều (%)",
                    "so_nhan_khau_muc_tieu": "Nhân khẩu thuộc hộ nghèo đa chiều",
                }
                return md_labels.get(c, REPORT_COLUMN_LABELS.get(c, c))
            return REPORT_COLUMN_LABELS.get(c, c)

        examples = []
        for label, col, value in required[:4]:
            examples.append(f"{label} / {_coverage_col_label(col)} = {value}")
        return ["Văn bản thiếu cặp nhãn-số nổi bật nên nhận định còn chung: " + "; ".join(examples)]
    return []


def _review_unsupported_claim_warnings(report_text: str) -> list[str]:
    lower = str(report_text or "").lower()
    checks = [
        ("đứng đầu trong việc hỗ trợ", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("không bỏ sót bất kỳ", "Văn bản có cam kết tuyệt đối không được chứng minh bằng số liệu."),
        ("đảm bảo không bỏ sót", "Văn bản có cam kết tuyệt đối không được chứng minh bằng số liệu."),
        ("nguyên nhân chính", "Văn bản suy diễn nguyên nhân khi bảng không chứng minh nguyên nhân."),
        ("do thiếu", "Văn bản có dấu hiệu suy diễn nguyên nhân từ bảng tổng hợp."),
    ]
    return [msg for needle, msg in checks if needle in lower]


def _review_col_is_ratio_like(col: Any) -> bool:
    c = str(col or "").lower()
    return "ty_le" in c or "ti_le" in c or c.endswith("_%") or "rate" in c or "%" in c


def _review_unit_is_ratio_context(unit: str) -> bool:
    t = str(unit or "").lower()
    return "%" in t or "tỷ lệ" in t or "phần trăm" in t


def _review_local_context_for_label(unit: str, label: str, all_labels: list[str]) -> str:
    raw = str(unit or "")
    lower = raw.lower()
    label_l = str(label or "").lower().strip()
    if not label_l:
        return raw
    start = lower.find(label_l)
    if start < 0:
        return raw
    end = len(raw)
    search_from = start + len(label_l)
    for other in all_labels or []:
        other_l = str(other or "").lower().strip()
        if not other_l or other_l == label_l:
            continue
        pos = lower.find(other_l, search_from)
        if pos >= 0:
            end = min(end, pos)
    return raw[start:end].strip(" ;,.-") or raw


def _review_label_number_pair_warnings(report_text: str, report_tables: list[dict[str, Any]], template_id: Any = None, template_pattern: Any = None) -> list[str]:
    warnings: list[str] = []
    try:
        tid = int(template_id or 0)
    except Exception:
        tid = 0
    pattern = str(template_pattern or "")
    # Các mẫu nhiều chỉ tiêu/nhóm thường viết nhiều cặp nhãn-số trong cùng một câu,
    # ví dụ: Kinh (1.044 hộ nghèo, 1.652 hộ cận nghèo) hoặc Tuy Đức 829 hộ, 43,24%.
    # Validator chính trong report_writer đã hậu kiểm số liệu; auto-review ở app chỉ là cảnh báo phụ.
    # Bỏ lớp check phụ này ở các mẫu dễ false-positive để log demo không báo hard warning giả.
    if tid in {8, 9, 10, 11, 12} or pattern in {"vulnerable_groups", "ethnicity", "causes", "child_deprivation", "multidimensional_standard"}:
        return []
    for item in report_tables or []:
        if item.get("name") not in {"template_main", "main", "by_district"}:
            continue
        data = item.get("data") or {}
        rows = data.get("records") or []
        cols = data.get("columns") or []
        if not rows or not cols:
            continue
        label_col = None
        for c in cols:
            if any(isinstance((r or {}).get(c), str) for r in rows):
                label_col = c
                break
        if not label_col:
            label_col = cols[0]
        num_cols = []
        for c in cols:
            if c == label_col:
                continue
            vals = [(r or {}).get(c) for r in rows]
            if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
                if str(c).startswith(("so_", "tong_", "ty_le", "ti_le", "chenh_lech", "muc_", "count", "rate", "delta")):
                    num_cols.append(c)
        if not num_cols:
            continue
        all_numbers: set[str] = set()
        for r in rows:
            for c in num_cols:
                all_numbers |= _review_num_variants((r or {}).get(c))
        row_labels = [str((r or {}).get(label_col) or "").strip() for r in rows]
        for unit in _review_sentence_units(report_text):
            unit_raw_nums = re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.\,]*(?:\s*%)?", unit)
            unit_nums = {_review_norm_num(x) for x in unit_raw_nums if x}
            unit_nums = {n for n in unit_nums if n and n not in {"2023", "2024", "2025", "2026"}}
            if not unit_nums:
                continue
            for r in rows:
                label = str((r or {}).get(label_col) or "").strip()
                if not label or label.lower() not in unit.lower():
                    continue
                check_unit = _review_local_context_for_label(unit, label, row_labels)
                raw_nums = re.findall(r"(?<![A-Za-z0-9_])-?\d[\d\.\,]*(?:\s*%)?", check_unit)
                nums = {_review_norm_num(x) for x in raw_nums if x}
                nums = {n for n in nums if n and n not in {"2023", "2024", "2025", "2026"}}
                if not nums:
                    continue
                ratio_context = _review_unit_is_ratio_context(check_unit)
                for c in num_cols:
                    if ratio_context and not _review_col_is_ratio_like(c):
                        continue
                    if not ratio_context and _review_col_is_ratio_like(c) and not _review_measure_present(check_unit, str(c)):
                        continue
                    if not _review_measure_present(check_unit, str(c)):
                        continue
                    expected = _review_num_variants((r or {}).get(c))
                    wrong = [n for n in nums if n not in expected and n in all_numbers]
                    if wrong:
                        warnings.append(
                            f"Văn bản có vẻ gán sai cặp nhãn-số: {label} / {REPORT_COLUMN_LABELS.get(str(c), str(c))} không khớp số {', '.join(wrong[:3])}."
                        )
                        if len(warnings) >= 6:
                            return warnings
                    if _review_unit_has_superlative_claim(unit):
                        try:
                            row_value = float((r or {}).get(c) or 0)
                            max_value = max(float((rr or {}).get(c) or 0) for rr in rows)
                        except Exception:
                            row_value = max_value = 0.0
                        if abs(row_value - max_value) > 1e-9:
                            warnings.append(
                                f"Văn bản có nhận định xếp hạng không đúng: {label} không phải cao nhất theo {REPORT_COLUMN_LABELS.get(str(c), str(c))}."
                            )
                            if len(warnings) >= 6:
                                return warnings
        if item.get("name") == "template_main":
            break
    return warnings


def _auto_review_report_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Tạo cảnh báo tự động để log gửi lại dễ đọc hơn. Không thay thế kiểm chứng thủ công."""
    warnings: list[str] = []
    report_text = str(((payload.get("report") or {}).get("text")) or "")
    if not report_text.strip():
        return {
            "status": "ok",
            "warnings": ["Chưa có văn bản cuối để auto-review nội dung; LLM đang fail hoặc chưa sinh văn bản."],
            "warning_count": 1,
            "hard_warning_count": 0,
        }
    raw_tokens = [
        "ty_le_%%", "ty_le_%", "phan_loai", "so_ho", "so_nhan_khau", "label_col", "value_col", "template_main", "chart_df",
        "Excel", "mẫu Excel", "bảng mẫu", "bảng theo mẫu", "NLNN",
    ]
    found_raw = [tok for tok in raw_tokens if tok in report_text]
    if found_raw:
        warnings.append("Văn bản còn tên cột/token kỹ thuật: " + ", ".join(found_raw))

    if re.search(r"(?m)^\s*(?:[IVX]+\.|\d+\.)\s+", report_text):
        warnings.append("Văn bản báo cáo nhận định còn trình bày theo mục đánh số; nên dùng các đoạn nhận định tự nhiên hơn.")

    report_tables = payload.get("report_tables") or []
    template_main = {}
    for table_item in report_tables:
        if table_item.get("name") == "template_main":
            template_main = table_item.get("data") or {}
            break
    template_id = payload.get("template_id")
    if int(template_id or 0) == 1:
        cols = template_main.get("columns") or []
        if cols == ["phan_loai", "so_ho", "so_nhan_khau", "ty_le_%"]:
            warnings.append("Mẫu 1 vẫn đang dùng bảng phân loại 3 dòng thay vì bảng theo địa bàn/cột biểu mẫu báo cáo.")
        has_medium_col = any(str(c).startswith("so_ho_nlnndn") or str(c).startswith("so_khau_nlnndn") for c in cols)
        lower_text = report_text.lower()
        if has_medium_col and ("hộ không nghèo" in lower_text or "1.350 hộ" in report_text or "18,03%" in report_text):
            warnings.append("Mẫu 1 đang lẫn dữ liệu hộ không nghèo với nhóm hộ nông/lâm/ngư nghiệp có mức sống trung bình; report nên bám bộ số liệu báo cáo đã tổng hợp.")

    warnings.extend(_review_label_number_pair_warnings(report_text, report_tables, template_id=payload.get("template_id"), template_pattern=payload.get("template_pattern")))
    warnings.extend(_review_required_pair_coverage_warnings(report_text, report_tables, template_id=payload.get("template_id"), template_pattern=payload.get("template_pattern")))
    warnings.extend(_review_extra_number_warnings(report_text, payload))
    warnings.extend(_review_unsupported_claim_warnings(report_text))

    bundle = payload.get("bundle") or {}
    chart_insights = bundle.get("chart_insights") or {}
    # chart_insights dùng tên cột nội bộ để report_writer hiểu; chart_df trong UI/log dùng nhãn hiển thị tiếng Việt.
    # Từ bản table-only/supervised planner, biểu đồ có thể là nhiều chart sinh từ nhiều bảng và thường melt
    # về cặp cột chung như "Nhóm số liệu/Giá trị". Vì vậy auto-review phải so với TẤT CẢ chart,
    # không chỉ chart đầu tiên; nếu không sẽ báo sai giả ở mẫu 1/8/10 dù chart đang bám bảng.
    chart = payload.get("chart") or {}
    chart_df = chart.get("chart_df") or {}
    chart_cols = set(chart_df.get("columns") or [])
    chart_cols_all: set[str] = set(chart_cols)
    for chart_item in payload.get("charts") or []:
        try:
            cdf = (chart_item or {}).get("chart_df") or {}
            chart_cols_all.update(cdf.get("columns") or [])
        except Exception:
            continue

    def _accepted_chart_col_names(col: Any) -> set[str]:
        if not col:
            return set()
        raw = str(col)
        names = {raw}
        try:
            names.add(_chart_label_for_column(raw))
        except Exception:
            pass
        try:
            names.add(REPORT_COLUMN_LABELS.get(raw, raw))
        except Exception:
            pass
        # Các chart nhiều series ở UI luôn melt về cặp cột chung này.
        if raw in {"so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "tong_ho", "tong_ho_dan_cu", "so_ho_muc_tieu", "so_ho_ky_truoc", "so_ho_ky_sau"}:
            names.add("Số hộ")
            names.add("Giá trị")
            names.add("Số hộ thiếu hụt")
        if raw in {"so_ho_ngheo", "so_ho_can_ngheo"}:
            names.add("Số trẻ thuộc hộ nghèo")
            names.add("Số trẻ thuộc hộ cận nghèo")
        if raw in {"ty_le_%", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "ty_le_muc_tieu_%"}:
            names.add("Tỷ lệ")
            names.add("Tỷ lệ thiếu hụt (%)")
            names.add("Giá trị")
        if raw in {"huyen", "xa_phuong"}:
            names.add("Địa bàn")
            names.add("Huyện/TP")
        if raw in {"chi_tieu", "nhom_chi_tieu", "phan_loai", "dan_toc"}:
            names.add("Nhóm chỉ tiêu")
            names.add("Chỉ tiêu")
            names.add("Chỉ số thiếu hụt")
            names.add("Chỉ tiêu thiếu hụt của trẻ em")
            names.add("Nhóm hộ")
        return {n for n in names if n}

    chart_planner = payload.get("chart_planner") or {}
    chart_planner_source = str(chart_planner.get("source") or chart_planner.get("mode") or "")
    chart_is_derived_from_table = "derived_from_table" in chart_planner_source or "table_plan" in chart_planner_source

    if chart_insights.get("available") and not chart_is_derived_from_table:
        label_col = chart_insights.get("label_col")
        value_col = chart_insights.get("value_col")
        value_cols = chart_insights.get("value_cols") or []
        # Chỉ cảnh báo nếu không có chart nào chứa nhãn/cột tương đương. Với chart melt, "Giá trị"
        # hoặc "Nhóm số liệu" là hợp lệ vì dữ liệu vẫn lấy từ bảng đã validate.
        if label_col and chart_cols_all and not (_accepted_chart_col_names(label_col) & chart_cols_all):
            warnings.append(f"chart_insights.label_col={label_col} không khớp các cột biểu đồ hiển thị={sorted(chart_cols_all)}")
        if value_col and chart_cols_all and not (_accepted_chart_col_names(value_col) & chart_cols_all):
            warnings.append(f"chart_insights.value_col={value_col} không khớp các cột biểu đồ hiển thị={sorted(chart_cols_all)}")
        for c in value_cols:
            if chart_cols_all and not (_accepted_chart_col_names(c) & chart_cols_all):
                warnings.append(f"chart_insights.value_cols chứa {c} nhưng không khớp các cột biểu đồ hiển thị.")

    if "Các dòng có giá trị thấp hơn gồm" in report_text:
        warnings.append("Câu 'Các dòng có giá trị thấp hơn gồm...' có thể gây ngược nghĩa nếu lặp lại nhóm top; cần kiểm tra bottom_records.")

    report_tables = payload.get("report_tables") or []
    charts = payload.get("charts") or []
    if report_tables and len(charts) < len(report_tables):
        warnings.append(f"Số biểu đồ ({len(charts)}) ít hơn số bảng hiển thị ({len(report_tables)}); UI cần có biểu đồ đối chiếu cho từng bảng chính.")

    hard_warnings = [
        w for w in warnings
        if not str(w).startswith("Văn bản thiếu cặp nhãn-số nổi bật nên nhận định còn chung")
        and not str(w).startswith("chart_insights.")
    ]
    return {
        "status": "needs_review" if hard_warnings else "ok",
        "warnings": warnings,
        "warning_count": len(warnings),
        "hard_warning_count": len(hard_warnings),
    }




# ── Final text fact audit: log + UI, hiển thị kể cả khi LLM pass ─────────────
def _get_final_text_fact_audit(report: Any) -> tuple[dict[str, Any], str, dict[str, Any], list[dict[str, Any]]]:
    """Lấy audit văn bản cuối từ ReportTextResult.

    report_writer tạo các field:
    - final_text_fact_audit
    - final_text_fact_audit_status
    - final_text_fact_audit_rules

    Hàm này cố ý không import report_writer để không đổi import hiện có trong app.
    Nếu report_writer cũ chưa có audit thì trả not_run và UI/log không bị lỗi.
    """
    audit = getattr(report, "final_text_fact_audit", None) or {}
    if not isinstance(audit, dict):
        audit = {}
    status = str(
        getattr(report, "final_text_fact_audit_status", None)
        or audit.get("status")
        or "not_run"
    )
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    rules = getattr(report, "final_text_fact_audit_rules", None) or audit.get("rules") or []
    if not isinstance(rules, list):
        rules = []
    return audit, status, summary, rules


def _make_user_edited_fact_audit() -> dict[str, Any]:
    """Audit mềm cho trường hợp người dùng tự sửa văn bản trong UI.

    Không cố hậu kiểm lại bằng app.py vì validator chính nằm ở report_writer. Mục tiêu là
    tránh hiển thị checklist xanh cũ sau khi người dùng đã chỉnh sửa số/chữ.
    """
    return {
        "schema": "final_text_fact_audit",
        "status": "warn",
        "summary": {
            "status": "warn",
            "rule_pass_count": 0,
            "rule_warn_count": 1,
            "rule_fail_count": 0,
            "sentence_pass_count": 0,
            "sentence_warn_count": 0,
            "sentence_fail_count": 0,
            "hard_warning_count": 0,
            "soft_warning_count": 1,
        },
        "rules": [
            {
                "rule_id": "user_edited_text",
                "name": "Văn bản đã được người dùng chỉnh sửa thủ công",
                "status": "warn",
                "message": "Audit tự động thuộc bản trước không còn được coi là checklist xanh; cần đối chiếu lại số liệu nếu đã sửa số hoặc nhãn.",
                "warnings": ["Văn bản đã được người dùng chỉnh sửa thủ công; số liệu cần được tự đối chiếu nếu sửa số."],
            }
        ],
        "sentence_checks": [],
        "hard_warnings": [],
        "soft_warnings": ["Văn bản đã được người dùng chỉnh sửa thủ công; số liệu cần được tự đối chiếu nếu sửa số."],
        "display_policy": {
            "show_for_llm_pass": True,
            "show_for_llm_fail": True,
            "ui_rule": "Nếu status='fail' thì không cho final_validation_passed=true; nếu status='warn' thì cho qua nhưng hiển thị cảnh báo; nếu status='pass' thì hiển thị checklist xanh để người dùng kiểm nhanh.",
        },
    }


def _attach_final_text_fact_audit_to_report_task_payload(payload: dict[str, Any], report: Any) -> dict[str, Any]:
    """Gắn audit văn bản cuối vào report_task và chống auto_review xanh giả.

    Gọi sau khi payload["auto_review"] đã được tạo. Không thay đổi text; chỉ thêm
    debug/checklist và đồng bộ trạng thái pass/warn/fail vào report/ui_status/auto_review.
    """
    audit, audit_status, audit_summary, audit_rules = _get_final_text_fact_audit(report)

    report_section = payload.setdefault("report", {})
    report_section["final_text_fact_audit_status"] = audit_status
    report_section["final_text_fact_audit_summary"] = audit_summary
    report_section["final_text_fact_audit_rules"] = audit_rules
    report_section["final_text_fact_audit"] = audit

    ui_status = payload.setdefault("ui_status", {})
    ui_status["final_text_fact_audit_status"] = audit_status
    ui_status["final_text_fact_audit_summary"] = audit_summary

    checklist = payload.setdefault("review_checklist", [])
    audit_rule_text = (
        "Quy tắc audit văn bản cuối: fail = không cho qua; warn = cho qua nhưng cần xem; "
        "pass = checklist xanh để kiểm nhanh văn bản đã được accepted."
    )
    if audit_rule_text not in checklist:
        checklist.append(audit_rule_text)

    auto_review = payload.setdefault("auto_review", {})
    auto_review["final_text_fact_audit_status"] = audit_status
    auto_review["final_text_fact_audit_summary"] = audit_summary
    auto_review["final_text_fact_audit_hard_warning_count"] = int((audit_summary or {}).get("hard_warning_count") or 0)
    auto_review["final_text_fact_audit_soft_warning_count"] = int((audit_summary or {}).get("soft_warning_count") or 0)
    if audit_status == "fail":
        report_section["final_validation_passed"] = False
        ui_status["final_validation_passed"] = False
        auto_review["status"] = "fail"
        auto_review["hard_warning_count"] = max(
            int(auto_review.get("hard_warning_count") or 0),
            int((audit_summary or {}).get("hard_warning_count") or 1),
        )
        auto_review.setdefault("warnings", [])
        for warning in (audit.get("hard_warnings") or [])[:10]:
            if warning not in auto_review["warnings"]:
                auto_review["warnings"].append(warning)
    elif audit_status == "warn":
        # Không ép fail: warn của fact audit nghĩa là cần xem lại, không phải hard fail
        # nếu chỉ còn vấn đề văn phong/độ dài/coverage mềm.
        auto_review["status"] = "needs_review"
        if int((audit_summary or {}).get("hard_warning_count") or 0) == 0:
            auto_review["hard_warning_count"] = 0
        auto_review["warning_count"] = max(
            int(auto_review.get("warning_count") or 0),
            int((audit_summary or {}).get("soft_warning_count") or 1),
        )
        auto_review.setdefault("warnings", [])
        for warning in (audit.get("soft_warnings") or [])[:10]:
            if warning not in auto_review["warnings"]:
                auto_review["warnings"].append(warning)
    elif audit_status == "pass":
        if int((audit_summary or {}).get("hard_warning_count") or 0) == 0:
            auto_review["hard_warning_count"] = 0
            if auto_review.get("status") == "fail":
                auto_review["status"] = "needs_review" if auto_review.get("warnings") else "ok"

    return payload


def _render_final_text_fact_audit_panel(report: Any, *, expanded: bool | None = None) -> None:
    """Hiển thị hậu kiểm số liệu cho văn bản cuối, kể cả khi LLM đã pass.

    Đặt ngay dưới văn bản nhận định trong tab Báo cáo. Không phụ thuộc panel debug LLM fail.
    """
    audit, status, summary, rules = _get_final_text_fact_audit(report)
    if not audit or status == "not_run":
        return

    icon = "✅" if status == "pass" else ("⚠️" if status == "warn" else "❌")
    title = f"{icon} Hậu kiểm số liệu văn bản cuối: {status}"
    if expanded is None:
        expanded = status in {"fail", "warn", "pass"}

    with st.expander(title, expanded=bool(expanded)):
        st.caption(
            "Quy tắc: fail = không cho qua; warn = cho qua nhưng cần xem; "
            "pass = checklist xanh để kiểm nhanh văn bản đã được accepted."
        )
        if summary:
            st.write({
                "rule_pass_count": summary.get("rule_pass_count", 0),
                "rule_warn_count": summary.get("rule_warn_count", 0),
                "rule_fail_count": summary.get("rule_fail_count", 0),
                "sentence_pass_count": summary.get("sentence_pass_count", 0),
                "sentence_warn_count": summary.get("sentence_warn_count", 0),
                "sentence_fail_count": summary.get("sentence_fail_count", 0),
                "hard_warning_count": summary.get("hard_warning_count", 0),
                "soft_warning_count": summary.get("soft_warning_count", 0),
            })

        if rules:
            st.markdown("**Checklist quy tắc**")
            for rule in rules:
                r_status = str(rule.get("status") or "")
                r_icon = "✅" if r_status == "pass" else ("⚠️" if r_status == "warn" else "❌")
                st.write(f"{r_icon} `{rule.get('rule_id')}` - {rule.get('name')}: {rule.get('message')}")

        sentence_checks = audit.get("sentence_checks") or []
        problem_rows = [x for x in sentence_checks if x.get("status") in {"fail", "warn"}]
        if problem_rows:
            st.markdown("**Câu/cụm cần xem lại**")
            for item in problem_rows[:20]:
                s_icon = "⚠️" if item.get("status") == "warn" else "❌"
                st.write(f"{s_icon} {item.get('sentence')}")
                for check in item.get("checks") or []:
                    reason = check.get("reason") or check.get("message") or ""
                    if reason:
                        st.caption(reason)

        hard_warnings = audit.get("hard_warnings") or []
        soft_warnings = audit.get("soft_warnings") or []
        if hard_warnings or soft_warnings:
            with st.expander("Danh sách cảnh báo audit", expanded=False):
                st.json({"hard_warnings": hard_warnings, "soft_warnings": soft_warnings})

def _word_export_section_sources(state: dict[str, Any]) -> dict[str, Any]:
    """Mô tả rõ phần nào trong Word do LLM/fallback tạo, phần nào là khung tự động."""
    report = state.get("report")
    final_source = getattr(report, "final_source", None) if report is not None else None
    used_llm = bool(getattr(report, "used_llm", False)) if report is not None else False
    fallback_used = bool(getattr(report, "fallback_used", False)) if report is not None else False
    validation_passed = bool(getattr(report, "final_validation_passed", False)) if report is not None else False
    if final_source == "user_edited":
        report_source = "user_edited"
    elif used_llm:
        report_source = "llm"
    elif final_source == "llm_failed_no_fallback":
        report_source = "llm_failed_no_final_text"
    else:
        report_source = "python_auto"
    return {
        "I_thông_tin_chung": "Khung hành chính tự động từ report_exporter.py, không phải LLM.",
        "II_số_liệu_tổng_hợp": "Bảng số liệu và biểu đồ do Python render từ bộ số liệu đã kiểm soát; nếu ở chế độ LLM thì LLM chỉ lập plan và có debug riêng.",
        "III_phân_tích_nhận_định": {
            "source": report_source,
            "final_source": final_source,
            "used_llm": used_llm,
            "fallback_used": fallback_used,
            "final_validation_passed": validation_passed,
            "note": "Mục này dùng văn bản báo cáo nhận định đang hiển thị, kết hợp đoạn phân tích tự động từ bảng/biểu đồ để Word dài hơn theo mặc định.",
        },
        "IV_kiến_nghị_đề_xuất": "Khung kiến nghị chung được sinh tự động từ phạm vi báo cáo và nguyên tắc quản lý, không bịa thêm số liệu.",
    }

def _build_report_task_log_payload(state: dict[str, Any], *, max_table_rows: int = 1000, log_event_type: str | None = None) -> dict[str, Any]:
    """Tạo payload report_task thống nhất: text ↔ facts ↔ bảng ↔ biểu đồ ↔ export debug."""
    bundle = state.get("bundle")
    report = state.get("report")
    template = getattr(bundle, "template", {}) if bundle is not None else {}
    scope = getattr(bundle, "scope", {}) if bundle is not None else {}
    facts = getattr(bundle, "facts", {}) if bundle is not None else {}
    tables = getattr(bundle, "tables", {}) if bundle is not None else {}
    summary = getattr(bundle, "summary", {}) if bundle is not None else {}
    report_text = str(getattr(report, "text", "") or "") if report is not None else ""

    report_table_items = state.get("report_table_items") or _report_table_items(bundle)
    report_table_payloads = []
    for idx, item in enumerate(report_table_items, start=1):
        df = item.get("df")
        report_table_payloads.append({
            "index": idx,
            "name": item.get("name"),
            "title": item.get("title"),
            "data": _dataframe_log_payload(df, max_rows=max_table_rows) if isinstance(df, pd.DataFrame) else None,
        })
    report_chart_items = state.get("report_chart_items") or _build_report_chart_items(bundle, report_table_items)
    chart_df = state.get("chart_df")
    payload = {
        "log_schema": "report_task_unified",
        "log_event_type": log_event_type or state.get("log_event_type") or "report_generated",
        "timestamp": datetime.now().astimezone().isoformat(),
        "generated_at": state.get("generated_at"),
        "template_id": state.get("template_id") or template.get("id"),
        "template_title": template.get("title"),
        "template_code": template.get("code"),
        "template_pattern": template.get("pattern"),
        "mode_name": state.get("mode_name"),
        "generation_mode": state.get("generation_mode"),
        "generation_mode_label": state.get("generation_mode_label"),
        "text_source": state.get("text_source"),
        "filters": _json_safe(state.get("filters") or {}),
        "scope": _json_safe(scope),
        "agency_meta": _json_safe(state.get("agency_meta") or {}),
        "report": {
            "text": report_text,
            "word_count": len(re.findall(r"\b\w+\b", report_text, flags=re.UNICODE)),
            "numbers_in_text": _extract_numbers_for_review(report_text),
            "used_llm": bool(getattr(report, "used_llm", False)) if report is not None else False,
            "final_source": getattr(report, "final_source", None) if report is not None else None,
            "fallback_used": bool(getattr(report, "fallback_used", False)) if report is not None else False,
            "final_validation_passed": bool(getattr(report, "final_validation_passed", False)) if report is not None else False,
            "warnings": _json_safe(getattr(report, "warnings", None)) if report is not None else None,
            "validation_warnings": _json_safe(getattr(report, "validation_warnings", None)) if report is not None else None,
            "final_validation_warnings": _json_safe(getattr(report, "final_validation_warnings", None)) if report is not None else None,
            "status_messages": _json_safe(getattr(report, "status_messages", None)) if report is not None else None,
            "llm_attempt_count": _json_safe(getattr(report, "llm_attempt_count", None)) if report is not None else None,
            "llm_max_attempts": _json_safe(getattr(report, "llm_max_attempts", None)) if report is not None else None,
            "llm_min_words": _json_safe(getattr(report, "llm_min_words", None)) if report is not None else None,
            "llm_attempt_results": _json_safe(getattr(report, "llm_attempt_results", None)) if report is not None else None,
            "rewrite_similarity": _json_safe(getattr(report, "rewrite_similarity", None)) if report is not None else None,
        },
        "bundle": {
            "template": _json_safe(template),
            "scope": _json_safe(scope),
            "facts_keys": sorted([str(k) for k in facts.keys()]) if isinstance(facts, dict) else [],
            "facts_values": _json_safe(facts) if isinstance(facts, dict) else {},
            "template_context": _json_safe(facts.get("template_context") if isinstance(facts, dict) else None),
            "table_insights": _json_safe(facts.get("table_insights") if isinstance(facts, dict) else None),
            "chart_insights": _json_safe(facts.get("chart_insights") if isinstance(facts, dict) else None),
            "template_data_warnings": _json_safe(facts.get("template_data_warnings") if isinstance(facts, dict) else None),
        },
        "report_tables": report_table_payloads,
        "table_planner": _json_safe(state.get("table_plan_debug")),
        "chart_planner": _json_safe(state.get("chart_plan_debug")),
        "charts": _chart_items_log_payload(report_chart_items, max_rows=max_table_rows),
        "chart": {
            "chart_kind": _infer_chart_kind_from_fig(state.get("chart_fig")),
            "chart_error": _json_safe(state.get("chart_error")),
            "chart_df": _dataframe_log_payload(chart_df, max_rows=max_table_rows) if isinstance(chart_df, pd.DataFrame) else None,
        },
        "ui_status": {
            "generation_mode": state.get("generation_mode"),
            "used_llm": bool(getattr(report, "used_llm", False)) if report is not None else False,
            "final_source": getattr(report, "final_source", None) if report is not None else None,
            "fallback_used": bool(getattr(report, "fallback_used", False)) if report is not None else False,
            "final_validation_passed": bool(getattr(report, "final_validation_passed", False)) if report is not None else False,
            "regenerate_nonce": state.get("regenerate_nonce", 0),
        },
        "word_export_sections": _json_safe(_word_export_section_sources(state)),
        "exports": _json_safe(state.get("export_debug") or state.get("exports") or None),
        "review_checklist": [
            "Đối chiếu report.text với report_tables, table_insights và chart_insights.",
            "Mỗi bảng hiển thị trong report_tables nên có một biểu đồ đối chiếu trong charts.",
            "Không dùng bảng nguồn DB riêng để kiểm chứng văn bản nếu report_tables đã có đủ số liệu báo cáo.",
            "Kiểm tra used_llm/fallback/final_validation_passed/nonce trong ui_status hoặc report trước khi kết luận đạt.",
        ],
    }
    payload["auto_review"] = _auto_review_report_detail_payload(payload)
    payload = _attach_final_text_fact_audit_to_report_task_payload(payload, report)
    return _json_safe(payload)


def _write_report_task_log(state: dict[str, Any], *, log_event_type: str = "report_generated") -> Path | None:
    """Ghi mọi debug của UI Báo cáo vào một log duy nhất: report_task_YYYYMMDD.jsonl.

    Không còn tạo report_detail_*.jsonl. Export Word/Excel nếu có sẽ được ghi
    bằng event report_export_prepared trong cùng file report_task.
    """
    try:
        path = _report_task_log_path()
        payload = _build_report_task_log_payload(state, log_event_type=log_event_type)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return path
    except Exception as exc:
        try:
            state["report_task_log_error"] = str(exc)
        except Exception:
            pass
        return None


def _generate_template_report_state(template_id: int, filters: dict[str, Any], mode_name: str, agency_meta: dict[str, Any] | None = None, regenerate_nonce: int = 0) -> dict[str, Any]:
    settings = _current_report_settings()
    generation_mode = settings.get("generation_mode", "no_llm")
    use_llm_mode = generation_mode == "llm"
    bundle = build_report_bundle(
        template_id,
        db_path=DB_PATH,
        year=filters.get("nam"),
        huyen=filters.get("huyen"),
    )

    # 1) Văn bản nhận định
    # - no_llm: Python auto text, không gọi là fallback lỗi.
    # - llm: LLM rewrite; nếu fail thì KHÔNG tự chuyển sang Python auto.
    try:
        report = generate_report_text(
            facts_bundle=bundle,
            mode="template_report",
            style_profile_path=settings.get("profile_path"),
            use_llm=use_llm_mode,
            report_level="administrative",
            allow_variation=settings.get("allow_variation", True),
            regenerate_nonce=regenerate_nonce,
            llm_failure_policy=settings.get("llm_failure_policy", "no_fallback" if use_llm_mode else "python_auto"),
            generation_mode=generation_mode,
            llm_min_words=settings.get("llm_min_words"),
        )
    except TypeError:
        # Tương thích nếu report_writer cũ chưa có tham số mới.
        report = generate_report_text(
            report_type=template_id,
            db_path=DB_PATH,
            year=filters.get("nam"),
            huyen=filters.get("huyen"),
            mode="template_report",
            style_profile_path=settings.get("profile_path"),
            use_llm=use_llm_mode,
            report_level="administrative",
            allow_variation=settings.get("allow_variation", True),
            regenerate_nonce=regenerate_nonce,
        )
        if not use_llm_mode:
            try:
                report.final_source = "python_auto"
                report.fallback_used = False
            except Exception:
                pass

    # 2) Bảng số liệu: LLM chỉ lập plan; Python validate/render từ bundle.
    default_table_items = _report_table_items(bundle)
    table_plan_debug: dict[str, Any] = {
        "kind": "table_plan",
        "mode": generation_mode,
        "source": "python_default_legacy",
        "warnings": [],
    }
    report_table_items = default_table_items
    if build_report_table_plan is not None and apply_report_table_plan is not None:
        try:
            table_plan_debug = build_report_table_plan(
                bundle,
                use_llm=use_llm_mode,
                model_name=MODEL_NAME,
                ollama_url=OLLAMA_URL,
                timeout=LLM_TIMEOUT,
                regenerate_nonce=regenerate_nonce,
            )
            report_table_items = apply_report_table_plan(bundle, table_plan_debug, default_table_items)
        except Exception as exc:
            table_plan_debug = {
                "kind": "table_plan",
                "mode": generation_mode,
                "source": "python_default_after_planner_error",
                "warnings": [str(exc)],
            }
            report_table_items = default_table_items

    # 3) Biểu đồ: mỗi bảng phân tích đủ điều kiện có một biểu đồ riêng.
    #    LLM, nếu bật, chỉ lập plan theo từng bảng; Python validate/render từ bundle.
    chart_plan_debug: dict[str, Any] = {
        "kind": "multi_chart_plan",
        "mode": generation_mode,
        "source": "python_default_legacy",
        "warnings": [],
        "chart_plans": [],
    }
    report_chart_items: list[dict[str, Any]] = []
    if build_report_chart_plans is not None and execute_report_chart_plans is not None:
        try:
            chart_plan_debug = build_report_chart_plans(
                bundle,
                table_items=report_table_items,
                use_llm=use_llm_mode,
                model_name=MODEL_NAME,
                ollama_url=OLLAMA_URL,
                timeout=LLM_TIMEOUT,
                regenerate_nonce=regenerate_nonce,
            )
            report_chart_items = execute_report_chart_plans(bundle, chart_plan_debug, px) or []
        except Exception as exc:
            chart_plan_debug = {
                "kind": "multi_chart_plan",
                "mode": generation_mode,
                "source": "python_default_after_multi_planner_error",
                "warnings": [str(exc)],
                "chart_plans": [],
            }

    elif build_report_chart_plan is not None and execute_report_chart_plan is not None:
        # Tương thích với planner hiện tại: chỉ tạo được 1 biểu đồ chính.
        try:
            chart_plan_debug = build_report_chart_plan(
                bundle,
                use_llm=use_llm_mode,
                model_name=MODEL_NAME,
                ollama_url=OLLAMA_URL,
                timeout=LLM_TIMEOUT,
                regenerate_nonce=regenerate_nonce,
            )
            chart_title = f"Biểu đồ minh họa - {(getattr(bundle, 'template', {}) or {}).get('title', 'báo cáo')}"
            planned_chart = execute_report_chart_plan(bundle, chart_plan_debug, px, title=chart_title)
            if planned_chart is not None:
                report_chart_items = [planned_chart]
        except Exception as exc:
            chart_plan_debug = {
                "kind": "chart_plan",
                "mode": generation_mode,
                "source": "python_default_after_planner_error",
                "warnings": [str(exc)],
            }

    if not report_chart_items:
        # Executor mặc định: mỗi bảng đang hiển thị có một biểu đồ nếu đủ điều kiện.
        # Đây không phải fallback văn bản LLM, chỉ là render chart Python an toàn.
        report_chart_items = _build_report_chart_items(bundle, report_table_items)

    if report_chart_items:
        fig = report_chart_items[0].get("fig")
        chart_df = report_chart_items[0].get("chart_df")
        chart_error = None
    else:
        fig, chart_df, chart_error = _build_template_chart(bundle)
        report_chart_items = ([{"source_table": "legacy", "title": "Biểu đồ minh họa", "description": "Biểu đồ minh họa", "fig": fig, "chart_df": chart_df}] if fig is not None else [])

    text_source = getattr(report, "final_source", None)
    # Snapshot bản tự động ngay lúc sinh report. Nút "Khôi phục bản tự động"
    # chỉ được phục hồi snapshot này, KHÔNG gọi lại LLM/Python để sinh report mới.
    automatic_report_snapshot = {
        "text": str(getattr(report, "text", "") or ""),
        "final_source": str(getattr(report, "final_source", "") or ""),
        "used_llm": bool(getattr(report, "used_llm", False)),
        "fallback_used": bool(getattr(report, "fallback_used", False)),
        "final_validation_passed": bool(getattr(report, "final_validation_passed", False)),
        "warnings": list(getattr(report, "warnings", []) or []),
        "final_text_fact_audit": getattr(report, "final_text_fact_audit", {}) or {},
        "final_text_fact_audit_status": getattr(report, "final_text_fact_audit_status", "not_run"),
        "final_text_fact_audit_rules": getattr(report, "final_text_fact_audit_rules", []) or [],
    }
    state = {
        "mode_name": mode_name,
        "generation_mode": generation_mode,
        "generation_mode_label": settings.get("generation_mode_label"),
        "llm_min_words": settings.get("llm_min_words"),
        "text_source": text_source,
        "automatic_report_snapshot": automatic_report_snapshot,
        "template_id": template_id,
        "filters": dict(filters),
        "bundle": bundle,
        "report": report,
        "report_table_items": report_table_items,
        "report_chart_items": report_chart_items,
        "table_plan_debug": table_plan_debug,
        "chart_plan_debug": chart_plan_debug,
        "chart_fig": fig,
        "chart_df": chart_df,
        "chart_error": chart_error,
        "agency_meta": merge_agency_meta(agency_meta),
        "regenerate_nonce": regenerate_nonce,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    task_log_path = _write_report_task_log(state, log_event_type="report_generated")
    if task_log_path is not None:
        state["report_task_log_path"] = str(task_log_path)
    return state

# ── Excel LLM exporter đã tách sang report/template_excel_llm_exporter.py ──

def _infer_chart_kind_from_fig(fig: Any | None) -> str:
    if fig is None or not getattr(fig, "data", None):
        return "bar"
    trace = fig.data[0]
    trace_type = str(getattr(trace, "type", "") or "").lower()
    mode = str(getattr(trace, "mode", "") or "").lower()
    if trace_type == "pie":
        return "pie"
    if "line" in mode or trace_type == "scatter":
        return "line"
    return "bar"


def _default_agency_meta_from_filters(filters: dict[str, Any]) -> dict[str, str]:
    """Default metadata for the Word front page.

    The UI section "Thông tin báo cáo / trang đầu" should mirror only the
    fields actually printed at the beginning of the exported Word report:
    agency name, document number, place and document date. Other administrative
    fields such as recipient, signing block and archive note are intentionally
    kept hidden/blank for the demo report.
    """
    huyen = filters.get("huyen")
    if huyen:
        issuing = f"ỦY BAN NHÂN DÂN {str(huyen).upper()}"
        place = str(huyen)
    else:
        issuing = "ỦY BAN NHÂN DÂN TỈNH ĐẮK NÔNG"
        place = "Đắk Nông"
    return merge_agency_meta({
        # Keep parent == issuing so the Word front page prints one agency line,
        # matching the current exported Word demo.
        "parent_agency": issuing,
        "issuing_agency": issuing,
        "document_no": "/BC-UBND",
        "place": place,
        "document_date": "ngày ... tháng ... năm ...",
        # Hidden demo-only metadata. These are not shown in the front-page UI.
        "recipient": "",
        "prepared_by": "",
        "signing_block": "",
        "signer_title": "NGƯỜI LẬP BÁO CÁO",
        "signer_name": "",
        "archive_note": "",
        "document_author": "admin",
    })


def _clean_document_no_for_word(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^số\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    return text or "/BC-UBND"


def _render_agency_meta_inputs(prefix: str, filters: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_agency_meta_from_filters(filters)
    with st.expander("Thông tin báo cáo / trang đầu", expanded=True):
        st.caption(
            "Chỉ nhập các trường đang xuất hiện ở phần đầu file Word: cơ quan ban hành, "
            "số/ký hiệu, địa danh và ngày tháng văn bản. Tên báo cáo và phạm vi số liệu "
            "được lấy tự động từ mẫu báo cáo/năm đã chọn."
        )
        c1, c2 = st.columns(2)
        issuing_agency = c1.text_input(
            "Cơ quan ban hành",
            value=defaults["issuing_agency"],
            key=f"{prefix}_issuing_agency",
        )
        document_no = c2.text_input(
            "Số/ký hiệu",
            value=defaults["document_no"],
            key=f"{prefix}_document_no",
            help="Chỉ nhập phần sau chữ 'Số:'. Ví dụ: /BC-UBND",
        )
        c3, c4 = st.columns(2)
        place = c3.text_input("Địa danh", value=defaults["place"], key=f"{prefix}_place")
        document_date = c4.text_input(
            "Ngày tháng văn bản",
            value=defaults["document_date"],
            key=f"{prefix}_document_date",
        )

    issuing_agency = str(issuing_agency or defaults["issuing_agency"]).strip()
    return {
        # Parent is intentionally set equal to issuing agency so the Word header
        # stays the same as the current demo file: one agency line on the left.
        "parent_agency": issuing_agency,
        "issuing_agency": issuing_agency,
        "document_no": _clean_document_no_for_word(document_no),
        "place": str(place or defaults["place"]).strip(),
        "document_date": str(document_date or defaults["document_date"]).strip(),
        # Keep non-front-page fields hidden and demo-safe.
        "recipient": "",
        "prepared_by": "",
        "signing_block": "",
        "signer_title": "NGƯỜI LẬP BÁO CÁO",
        "signer_name": "",
        "archive_note": "",
        "document_author": "admin",
    }

def _admin_report_state_signature(state: dict[str, Any], suffix: str = "") -> str:
    """Tạo key ổn định để cache file xuất, tránh render lại Word/Excel mỗi lần rerun."""
    bundle = state.get("bundle")
    scope = getattr(bundle, "scope", {}) if bundle is not None else {}
    payload = {
        "suffix": suffix,
        "template_id": state.get("template_id"),
        "filters": state.get("filters") or {},
        "scope": scope,
        "agency_meta": state.get("agency_meta") or {},
        "regenerate_nonce": state.get("regenerate_nonce", 0),
        "generated_at": state.get("generated_at"),
        # Quan trọng: mode Excel phải nằm trong cache key.
        # Nếu không, người dùng đổi từ mẫu gốc sang LLM nhưng vẫn tải cache cũ _dung_mau_goc.xlsx.
        "excel_llm_mode": _current_report_excel_mode_label(),
        "generation_mode": state.get("generation_mode") or str(st.session_state.get("report_generation_mode", "Không dùng LLM")),
        "text_source": state.get("text_source"),
        "report_text_len": len(str(getattr(state.get("report"), "text", "") or "")),
        "report_text_head": str(getattr(state.get("report"), "text", "") or "")[:80],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return re.sub(r"[^0-9A-Za-z_]+", "_", raw)[-180:]


def _get_admin_report_export_cache(key: str) -> dict[str, Any] | None:
    cache = st.session_state.setdefault("admin_report_export_cache", {})
    value = cache.get(key)
    return value if isinstance(value, dict) else None


def _set_admin_report_export_cache(key: str, value: dict[str, Any]) -> None:
    cache = st.session_state.setdefault("admin_report_export_cache", {})
    # Chỉ giữ vài gói xuất gần nhất để session_state không phình quá lớn.
    if len(cache) > 6:
        for old_key in list(cache.keys())[:-6]:
            cache.pop(old_key, None)
    cache[key] = value


def _strip_export_binary_for_log(value: Any, *, depth: int = 0) -> Any:
    """JSON-safe export debug, không nhét bytes Word/Excel vào JSONL."""
    if depth > 8:
        return "<max_depth>"
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"docx_bytes", "template_xlsx_bytes", "content", "chart_png_bytes"}:
                if isinstance(item, (bytes, bytearray)):
                    out[f"{key_text}_size"] = len(item)
                else:
                    out[key_text] = _strip_export_binary_for_log(item, depth=depth + 1)
                continue
            out[key_text] = _strip_export_binary_for_log(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_strip_export_binary_for_log(item, depth=depth + 1) for item in value]
    return _json_safe(value)


def _export_log_payload(exports: dict[str, Any] | None) -> dict[str, Any]:
    """Tóm tắt Word/Excel export để gộp vào report_task, bao gồm debug Excel LLM."""
    exports = exports or {}
    docx_bytes = exports.get("docx_bytes")
    xlsx_bytes = exports.get("template_xlsx_bytes")
    return {
        "requested": True,
        "prepared_at": datetime.now().astimezone().isoformat(),
        "base_name": exports.get("base_name"),
        "word": {
            "success": isinstance(docx_bytes, (bytes, bytearray)) and len(docx_bytes) > 0,
            "bytes": len(docx_bytes) if isinstance(docx_bytes, (bytes, bytearray)) else 0,
            "chart_png_error": exports.get("chart_png_error"),
            "metadata_author": exports.get("docx_metadata_author"),
            "layout_note": exports.get("docx_layout_note"),
        },
        "excel": {
            "success": isinstance(xlsx_bytes, (bytes, bytearray)) and len(xlsx_bytes) > 0,
            "bytes": len(xlsx_bytes) if isinstance(xlsx_bytes, (bytes, bytearray)) else 0,
            "mode": exports.get("llm_excel_mode"),
            "backend": exports.get("excel_backend"),
            "file_suffix": exports.get("excel_file_suffix"),
            "warnings": _json_safe(exports.get("template_xlsx_warnings") or []),
            "error": exports.get("template_xlsx_error"),
            # Debug cho cả hai nhánh:
            # - python_debug: Excel không LLM / deterministic exporter
            # - llm_debug: Excel có LLM mapping, Python validate/tính/ghi
            "python_debug": _strip_export_binary_for_log(exports.get("python_excel_debug")),
            "llm_log_path": exports.get("llm_excel_log_path"),
            "llm_debug": _strip_export_binary_for_log(exports.get("llm_excel_debug")),
        },
        "raw_export_keys": sorted([str(k) for k in exports.keys()]),
    }


def _build_admin_report_exports(state: dict[str, Any], base_name: str, chart_title: str) -> dict[str, Any]:
    """Sinh file tải về khi người dùng đang ở mục Xuất Word/Excel.

    Có 2 nhánh Excel riêng:
    - Mẫu gốc deterministic: dùng cho kết quả hành chính ổn định.
    - LLM-assisted mapping + Python validated fallback: LLM chỉ tham gia ánh xạ/mapping; Python vẫn validate, tính số và ghi Excel.

    Hai nhánh phải có cache key và tên file khác nhau để tránh tải nhầm.
    """
    bundle = state["bundle"]
    report = state["report"]
    template = getattr(bundle, "template", {}) or {}
    scope = getattr(bundle, "scope", {}) or {}
    report_text = str(getattr(report, "text", "") or "")
    agency_meta = state.get("agency_meta") or {}

    # Không export trùng state["chart_fig"] khi đã có report_chart_items.
    # Trước đây app export chart_fig + từng report_chart_items nên có thể gọi
    # Kaleido 4 lần nếu có 3 biểu đồ. Nhánh mới chỉ export đúng số biểu đồ cần
    # chèn vào Word, và ưu tiên batch export của Plotly/Kaleido mới.
    raw_chart_items = list(state.get("report_chart_items") or [])
    chart_items_for_docx: list[dict[str, Any]] = []
    chart_png: bytes | None = None
    chart_png_error: str | None = None

    if raw_chart_items:
        item_figs = [item.get("fig") for item in raw_chart_items]
        png_results, chart_png_error = _figures_to_png_bytes_batch(item_figs)
        for item, png_bytes in zip(raw_chart_items, png_results):
            chart_items_for_docx.append({
                "title": item.get("title") or chart_title,
                "description": item.get("description") or "",
                "chart_png_bytes": png_bytes,
                "chart_df": item.get("chart_df"),
            })
    else:
        chart_png, chart_png_error = _figure_to_png_bytes(state.get("chart_fig"))

    docx_bytes = export_administrative_docx(
        bundle,
        report_text,
        chart_png_bytes=chart_png,
        chart_df=state.get("chart_df"),
        chart_title=chart_title,
        chart_items=chart_items_for_docx,
        agency_meta=agency_meta,
    )

    exports: dict[str, Any] = {
        "base_name": base_name,
        "docx_bytes": docx_bytes,
        "template_xlsx_bytes": None,
        "template_xlsx_warnings": [],
        "chart_png_error": chart_png_error,
        "docx_metadata_author": str((agency_meta or {}).get("document_author") or (agency_meta or {}).get("issuing_agency") or "admin"),
        "docx_layout_note": "Word DOCX: bảng dùng layout cố định, font bảng thu gọn và metadata tác giả cá nhân được chuẩn hóa trong report_exporter.",
    }

    template_id = int(template.get("id", state.get("template_id") or 0) or 0)
    excel_llm_mode = _current_report_excel_mode_label()
    # Giữ đúng lựa chọn của người dùng:
    # - Không dùng LLM: exporter deterministic theo mẫu gốc.
    # - LLM-assisted mapping + Python validated fallback: gọi template_excel_llm_exporter,
    #   nhưng Python vẫn validate/tính/ghi Excel.
    use_real_llm_excel = excel_llm_mode.startswith("LLM-assisted mapping")

    if use_real_llm_excel:
        # Experimental path riêng cho mẫu 1-12: LLM ánh xạ cột -> fact_key,
        # Python validate, query DB và ghi Excel. Không ảnh hưởng exporter gốc.
        try:
            llm_exporters = {
                1: export_mau1_llm_excel,
                2: export_mau2_llm_excel,
                3: export_mau3_llm_excel,
                4: export_mau4_llm_excel,
                5: export_mau5_llm_excel,
                6: export_mau6_llm_excel,
                7: export_mau7_llm_excel,
                8: export_mau8_llm_excel,
                9: export_mau9_llm_excel,
                10: export_mau10_llm_excel,
                11: export_mau11_llm_excel,
                12: export_mau12_llm_excel,
            }
            exporter_func = llm_exporters.get(template_id)
            if exporter_func is None:
                raise ValueError(f"Mẫu {template_id} chưa hỗ trợ luồng LLM-assisted mapping.")
            llm_export = exporter_func(
                year=scope.get("year"),
                huyen=None,
                use_llm=True,
                samples_dir=DATA_SAMPLES_DIR,
            )
            exports["excel_file_suffix"] = f"_llm_mau{template_id}.xlsx"
            exports["template_xlsx_bytes"] = llm_export["content"]
            exports["template_xlsx_warnings"] = list(llm_export.get("warnings") or [])
            exports["llm_excel_debug"] = llm_export.get("debug")
            exports["llm_excel_log_path"] = llm_export.get("log_path")
            exports["llm_excel_mode"] = excel_llm_mode
            exports["excel_backend"] = "llm_mapping_python_validated_exporter"
        except Exception as exc:
            exports["template_xlsx_error"] = f"Không xuất được Excel mẫu {template_id} theo luồng LLM-assisted mapping: {exc}"
            exports["llm_excel_mode"] = excel_llm_mode
            exports["excel_backend"] = "llm_mapping_python_validated_exporter"
    elif template_id in SUPPORTED_TEMPLATE_IDS:
        template_xlsx = export_template_xlsx(
            template_id,
            db_path=DB_PATH,
            samples_dir=DATA_SAMPLES_DIR,
            year=scope.get("year"),
            huyen=None,
        )
        exports["template_xlsx_bytes"] = template_xlsx.content
        exports["template_xlsx_warnings"] = list(template_xlsx.warnings or [])
        exports["llm_excel_mode"] = excel_llm_mode
        exports["excel_backend"] = "python_template_exporter_no_llm"
        exports["python_excel_debug"] = {
            "attempted": True,
            "mode": "no_llm_python_deterministic",
            "template_id": getattr(template_xlsx, "template_id", template_id),
            "source_template": getattr(template_xlsx, "source_template", None),
            "filled_rows": getattr(template_xlsx, "filled_rows", None),
            "warnings": list(getattr(template_xlsx, "warnings", []) or []),
            "content_bytes": len(template_xlsx.content) if isinstance(getattr(template_xlsx, "content", None), (bytes, bytearray)) else 0,
            "note": "Excel không LLM: dùng mapping Python cố định theo mẫu gốc; không gọi LLM và không có llm_debug.",
        }
        exports["excel_file_suffix"] = "_dung_mau_goc.xlsx"
    else:
        exports["template_xlsx_error"] = "Mẫu này chưa có cell-map Excel đúng mẫu gốc."
        exports["excel_backend"] = "unsupported_template"

    exports["export_log_payload"] = _export_log_payload(exports)
    return exports


def _render_template_report_state(state: dict[str, Any], allow_export: bool) -> None:
    bundle = state.get("bundle")
    report = state.get("report")
    if bundle is None or report is None:
        return

    template = getattr(bundle, "template", {}) or {}
    scope = getattr(bundle, "scope", {}) or {}
    pattern = str(template.get("pattern") or getattr(report, "report_pattern", "") or "")
    report_text = str(getattr(report, "text", "") or "")
    word_count = len(re.findall(r"\b\w+\b", report_text, flags=re.UNICODE))

    st.subheader(str(template.get("title") or "Báo cáo"))
    st.caption(
        f"Mẫu {template.get('id')} · Pattern: {template.get('pattern')} · "
        f"Phạm vi: {scope.get('scope_label')} · {word_count} từ"
    )

    tab_text, tab_table, tab_chart, tab_export, tab_debug = st.tabs(
        ["Báo cáo", "Bảng số liệu", "Biểu đồ theo bảng", "Xuất Word/Excel", "Debug/facts"]
    )

    with tab_text:
        # Chỉ hiện nút sinh lại trong chế độ LLM. Không LLM là bản Python cố định theo facts,
        # bấm sinh lại không tạo thêm giá trị và dễ gây hiểu nhầm là có sáng tạo văn phong.
        is_llm_mode = str(state.get("generation_mode") or "").lower() == "llm"
        if is_llm_mode:
            c_regen_1, c_status = st.columns([1, 3])
            if c_regen_1.button("🔁 Sinh lại LLM", key=f"regen_report_text_{state.get('template_id')}", use_container_width=True):
                new_nonce = int(state.get("regenerate_nonce", 0) or 0) + 1
                with st.spinner("Đang cho LLM tự thử lại đến khi có bản qua hậu kiểm..."):
                    st.session_state["admin_report_state"] = _generate_template_report_state(
                        int(state.get("template_id") or template.get("id") or 1),
                        state.get("filters") or {},
                        state.get("mode_name") or "administrative_report_week4_week5",
                        agency_meta=state.get("agency_meta") or {},
                        regenerate_nonce=new_nonce,
                    )
                st.rerun()
        else:
            c_status = st.container()

        final_source = str(getattr(report, "final_source", "") or "")
        source_label = {
            "python_auto": "Không LLM - Python tự động",
            "llm_rewrite_validated": "LLM rewrite đã qua hậu kiểm",
            "llm_rewrite_validated_retry": "LLM rewrite lần 2 đã qua hậu kiểm",
            "llm_rewrite_validated_initial_after_retry": "LLM rewrite bản đầu đã qua hậu kiểm",
            "llm_failed_no_fallback": "LLM chưa đạt hậu kiểm",
            "llm_failed_strict_no_python_fallback": "LLM chưa đạt hậu kiểm",
            "user_edited": "Người dùng đã chỉnh sửa",
            "facts_renderer_fallback": "Python auto/fallback kỹ thuật",
            "facts_renderer_expanded_fallback": "Python auto/fallback kỹ thuật",
        }.get(final_source, final_source or "Không xác định")
        validation_label = "đạt" if bool(getattr(report, "final_validation_passed", False)) else "chưa đạt"
        _audit_for_caption, _audit_status_for_caption, _audit_summary_for_caption, _audit_rules_for_caption = _get_final_text_fact_audit(report)
        if _audit_status_for_caption == "fail":
            validation_label = "chưa đạt (audit fail)"
        elif _audit_status_for_caption == "warn" and validation_label == "đạt":
            validation_label = "đạt nhưng cần xem audit"
        attempt_count = int(getattr(report, "llm_attempt_count", 0) or 0)
        max_attempts = int(getattr(report, "llm_max_attempts", 0) or 0)
        attempt_note = f" · LLM attempts={attempt_count}/{max_attempts}" if is_llm_mode and max_attempts else ""
        min_words_note = f" · min_words={getattr(report, 'llm_min_words', state.get('llm_min_words', ''))}" if is_llm_mode else ""
        c_status.caption(
            f"Chế độ: {state.get('generation_mode_label') or state.get('generation_mode')} · "
            f"Nguồn văn bản: {source_label} · used_llm={bool(getattr(report, 'used_llm', False))} · "
            f"hậu kiểm={validation_label} · nonce={state.get('regenerate_nonce', 0)} · {word_count} từ"
            f"{min_words_note}"
            f"{attempt_note}"
        )

        if final_source in {"llm_failed_no_fallback", "llm_failed_strict_no_python_fallback"}:
            st.error(
                f"LLM chưa tạo được văn bản đạt hậu kiểm sau {attempt_count or max_attempts or 'nhiều'} lần thử trong lượt này. "
                "Bấm 'Sinh lại LLM' để chạy thêm một lượt retry, hoặc chỉnh sửa thủ công nếu cần."
            )
            rejected = getattr(report, "raw_llm_rejected_reasons", None) or getattr(report, "warnings", None)
            if rejected:
                with st.expander("Lý do LLM chưa đạt", expanded=False):
                    st.json(rejected)
            attempts = getattr(report, "llm_attempt_results", None)
            if attempts:
                with st.expander("Các lần thử LLM", expanded=False):
                    st.json(attempts)

        st.markdown("**Văn bản báo cáo nhận định**")
        edit_key = f"admin_report_text_editing_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}"
        draft_key = f"admin_report_text_draft_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = report_text

        edit_cols = st.columns([1, 1, 2])
        if not st.session_state.get(edit_key, False):
            if edit_cols[0].button("✏️ Chỉnh sửa nhận định", key=f"btn_edit_report_text_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}", use_container_width=True):
                st.session_state[draft_key] = str(getattr(report, "text", "") or "")
                st.session_state[edit_key] = True
                st.rerun()
            if edit_cols[1].button("↩️ Khôi phục bản tự động", key=f"btn_restore_report_text_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}", use_container_width=True):
                # Không sinh lại báo cáo ở đây. Chỉ phục hồi snapshot bản tự động
                # đã được tạo ở lần sinh gần nhất, để tránh nút restore hoạt động
                # giống "Sinh lại báo cáo" và gọi lại LLM/Python.
                auto_snapshot = state.get("automatic_report_snapshot") or {}
                if auto_snapshot:
                    try:
                        report.text = str(auto_snapshot.get("text", "") or "")
                        report.final_source = str(auto_snapshot.get("final_source", "") or "python_auto")
                        report.used_llm = bool(auto_snapshot.get("used_llm", False))
                        report.fallback_used = bool(auto_snapshot.get("fallback_used", False))
                        report.final_validation_passed = bool(auto_snapshot.get("final_validation_passed", False))
                        report.warnings = list(auto_snapshot.get("warnings", []) or [])
                        report.final_text_fact_audit = auto_snapshot.get("final_text_fact_audit", {}) or {}
                        report.final_text_fact_audit_status = auto_snapshot.get("final_text_fact_audit_status", "not_run")
                        report.final_text_fact_audit_rules = auto_snapshot.get("final_text_fact_audit_rules", []) or []
                    except Exception:
                        pass
                    state["report"] = report
                    state["text_source"] = str(getattr(report, "final_source", "") or auto_snapshot.get("final_source", ""))
                    state["restored_auto_at"] = datetime.now().astimezone().isoformat()
                    st.session_state[draft_key] = str(getattr(report, "text", "") or "")
                    st.session_state[edit_key] = False
                    st.session_state["admin_report_state"] = state
                    st.rerun()
                else:
                    st.warning("Không tìm thấy snapshot bản tự động trong phiên hiện tại. Nếu đang ở chế độ LLM, hãy bấm 'Sinh lại LLM' để tạo lại bản tự động mới.")
            _display_report_text_block(report_text or "_(Chưa có văn bản cuối. Hãy sinh lại hoặc chỉnh sửa thủ công.)_")
        else:
            edited_text = st.text_area(
                "Nội dung nhận định",
                value=st.session_state.get(draft_key, report_text),
                height=360,
                key=f"textarea_report_text_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}",
            )
            c_save, c_cancel = st.columns(2)
            if c_save.button("✅ Lưu nhận định", key=f"btn_save_report_text_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}", use_container_width=True):
                try:
                    report.text = str(edited_text or "").strip()
                    report.final_source = "user_edited"
                    report.used_llm = bool(getattr(report, "used_llm", False))
                    report.fallback_used = False
                    report.final_validation_passed = True
                    report.warnings = list(getattr(report, "warnings", []) or []) + ["Văn bản đã được người dùng chỉnh sửa thủ công; số liệu cần được tự đối chiếu nếu sửa số."]
                    manual_audit = _make_user_edited_fact_audit()
                    report.final_text_fact_audit = manual_audit
                    report.final_text_fact_audit_status = manual_audit.get("status", "warn")
                    report.final_text_fact_audit_rules = manual_audit.get("rules", [])
                except Exception:
                    pass
                state["report"] = report
                state["text_source"] = "user_edited"
                state["edited_at"] = datetime.now().astimezone().isoformat()
                st.session_state["admin_report_state"] = state
                st.session_state[edit_key] = False
                st.rerun()
            if c_cancel.button("✖ Huỷ chỉnh sửa", key=f"btn_cancel_report_text_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}", use_container_width=True):
                st.session_state[edit_key] = False
                st.rerun()

        # Luôn hiển thị audit văn bản cuối nếu report_writer có sinh audit, kể cả khi LLM đã pass.
        _render_final_text_fact_audit_panel(report, expanded=is_llm_mode)

    with tab_table:
        table_items = state.get("report_table_items") or _report_table_items(bundle)
        if not table_items:
            st.info("Không có bảng số liệu để hiển thị.")
        for idx, item in enumerate(table_items, start=1):
            df = item.get("df")
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            st.markdown(f"**{idx}. {item.get('title') or _report_table_label(str(item.get('name')))}**")
            raw_display_df = _safe_df(df).head(DISPLAY_LIMIT)
            if rename_report_display_df is not None:
                display_df = rename_report_display_df(
                    raw_display_df,
                    bundle,
                    template_id=state.get("template_id"),
                    pattern=pattern,
                    table_name=item.get("name"),
                )
            else:
                display_df = _rename_report_df(raw_display_df, pattern)
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )
            if item.get("planner_reason"):
                st.caption(f"Planner: {item.get('planner_reason')}")
        table_debug = state.get("table_plan_debug")
        if table_debug:
            with st.expander("🔍 Debug bảng số liệu", expanded=False):
                st.json(table_debug)

    with tab_chart:
        chart_items = state.get("report_chart_items") or _build_report_chart_items(bundle, state.get("report_table_items") or _report_table_items(bundle))
        chart_error = state.get("chart_error")
        if chart_items:
            for idx, item in enumerate(chart_items, start=1):
                fig = item.get("fig")
                chart_df = item.get("chart_df")
                st.markdown(f"**{idx}. {item.get('title') or 'Biểu đồ minh họa'}**")
                if item.get("description"):
                    st.caption(f"Đối chiếu với: {item.get('description')}")
                if fig is not None:
                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                        key=f"template_chart_{state.get('mode_name')}_{state.get('template_id')}_{idx}_{state.get('regenerate_nonce', 0)}",
                    )
                if isinstance(chart_df, pd.DataFrame) and not chart_df.empty:
                    with st.expander("Dữ liệu dùng để vẽ biểu đồ", expanded=False):
                        st.dataframe(chart_df, use_container_width=True, hide_index=True)
                if item.get("chart_debug") or item.get("planner_reason"):
                    with st.expander("🔍 Debug biểu đồ này", expanded=False):
                        st.json({
                            "source_table": item.get("source_table"),
                            "planner_reason": item.get("planner_reason"),
                            "chart_debug": item.get("chart_debug"),
                        })
            chart_plan_debug = state.get("chart_plan_debug")
            if chart_plan_debug:
                with st.expander("🧠 Debug planner biểu đồ / từng bảng", expanded=False):
                    st.json(chart_plan_debug)
        elif chart_error:
            st.warning(chart_error)
        else:
            st.info("Chưa có biểu đồ minh họa cho mẫu này.")

    with tab_export:
        if not allow_export:
            st.info("Preview tuần 4 chưa bật phần xuất file.")
        else:
            st.markdown("**Xuất file báo cáo**")
            st.caption("Chuẩn bị và tải xuống file Word/Excel báo cáo theo mẫu đã chọn.")
            st.caption("Trong file Word: báo cáo mặc định xuất dạng dài; mục II là số liệu/biểu đồ, mục III dùng văn bản báo cáo nhận định đang hiển thị kèm phân tích tự động từ bảng, mục IV là kiến nghị chung có kiểm soát.")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"bao_cao_mau{template.get('id', state.get('template_id'))}_{timestamp}"
            chart_title = f"Biểu đồ minh họa - {template.get('title', 'báo cáo')}"
            cache_key = _admin_report_state_signature(state, suffix="word_template_excel")
            cached_exports = _get_admin_report_export_cache(cache_key)

            if cached_exports is None:
                prep_placeholder = st.empty()
                with prep_placeholder.container():
                    st.info(
                        "Bấm nút bên dưới để chuẩn bị file tải xuống. "
                        "Phần tạo Word/Excel chỉ chạy khi bạn cần xuất file, nên không làm chậm lúc sinh báo cáo."
                    )
                    prepare_clicked = st.button(
                        "⚙️ Chuẩn bị file tải xuống",
                        key=f"prepare_admin_report_exports_{cache_key}",
                        use_container_width=True,
                    )
                if prepare_clicked:
                    try:
                        with st.spinner("Đang chuẩn bị file Word và Excel báo cáo..."):
                            cached_exports = _build_admin_report_exports(state, base_name, chart_title)
                            state["export_debug"] = cached_exports.get("export_log_payload") or _export_log_payload(cached_exports)
                            export_log_path = _write_report_task_log(state, log_event_type="report_export_prepared")
                            if export_log_path is not None:
                                state["report_task_log_path"] = str(export_log_path)
                            _set_admin_report_export_cache(cache_key, cached_exports)
                        prep_placeholder.empty()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Không xuất được Word/Excel: {exc}")
                        cached_exports = None

            if cached_exports is not None:
                if cached_exports.get("chart_png_error"):
                    st.info(cached_exports["chart_png_error"])

                if cached_exports.get("llm_excel_debug"):
                    llm_debug = cached_exports.get("llm_excel_debug") or {}
                    st.caption(
                        "Excel mẫu này đang dùng luồng experimental: LLM ánh xạ cột → Python validate/tính số/ghi Excel."
                    )
                    with st.expander("🧪 Debug LLM Excel", expanded=False):
                        st.json({
                            "mode": cached_exports.get("llm_excel_mode"),
                            "log_note": "Debug Excel LLM đã được gộp vào report_task event=report_export_prepared; không ghi log llm_excel riêng.",
                            "llm_attempted": llm_debug.get("llm_attempted"),
                            "llm_error": llm_debug.get("llm_error"),
                            "validation_warnings": llm_debug.get("validation_warnings"),
                            "validated_plan": llm_debug.get("validated_plan"),
                            "filled_cell_count": llm_debug.get("filled_cell_count"),
                            "filled_rows_total": llm_debug.get("filled_rows_total"),
                            "filled_rows_sample": (llm_debug.get("filled_rows") or [])[:20],
                            "limitations": llm_debug.get("limitations"),
                        })

                c1, c2 = st.columns(2)
                c1.download_button(
                    "⬇️ Tải Word báo cáo",
                    data=cached_exports["docx_bytes"],
                    file_name=f"{cached_exports.get('base_name') or base_name}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key=f"download_word_report_{cache_key}",
                )

                template_xlsx_bytes = cached_exports.get("template_xlsx_bytes")
                if template_xlsx_bytes:
                    c2.download_button(
                        "⬇️ Tải Excel báo cáo",
                        data=template_xlsx_bytes,
                        file_name=f"{cached_exports.get('base_name') or base_name}{cached_exports.get('excel_file_suffix') or '_dung_mau_goc.xlsx'}",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"download_excel_report_{cache_key}",
                    )
                else:
                    c2.button(
                        "⬇️ Tải Excel báo cáo",
                        disabled=True,
                        use_container_width=True,
                        key=f"download_excel_report_disabled_{cache_key}",
                    )
                    if cached_exports.get("template_xlsx_error"):
                        st.error(cached_exports["template_xlsx_error"])

    with tab_debug:
        facts_debug = getattr(report, "report_facts", None) or {}
        bundle_facts = getattr(bundle, "facts", {}) or {}
        task_log_path = state.get("report_task_log_path")
        if task_log_path:
            st.success(f"Đã ghi log report_task thống nhất: `{task_log_path}`")
            try:
                p = Path(str(task_log_path))
                if p.exists():
                    st.download_button(
                        "⬇️ Tải report_task hôm nay",
                        data=p.read_bytes(),
                        file_name=p.name,
                        mime="application/jsonl",
                        use_container_width=True,
                        key=f"download_report_task_log_{state.get('template_id')}_{state.get('regenerate_nonce', 0)}",
                    )
            except Exception as exc:
                st.caption(f"Không đọc được file log để tải trực tiếp: {exc}")
        elif state.get("report_task_log_error"):
            st.warning(f"Không ghi được report_task: {state.get('report_task_log_error')}")

        with st.expander("📦 Snapshot report_task của lượt báo cáo này", expanded=False):
            try:
                st.json(_build_report_task_log_payload(state, max_table_rows=80))
            except Exception as exc:
                st.warning(f"Không tạo được snapshot kiểm chứng: {exc}")

        st.json({
            "generated_at": state.get("generated_at"),
            "report_task_log_path": task_log_path,
            "mode_name": state.get("mode_name"),
            "ui_status": {
                "used_llm": bool(getattr(report, "used_llm", False)),
                "final_source": getattr(report, "final_source", None),
                "fallback_used": bool(getattr(report, "fallback_used", False)),
                "final_validation_passed": bool(getattr(report, "final_validation_passed", False)),
                "generation_mode": state.get("generation_mode"),
                "regenerate_nonce": state.get("regenerate_nonce", 0),
                "table_count": len(state.get("report_table_items") or []),
                "chart_count": len(state.get("report_chart_items") or []),
            },
            "table_planner": state.get("table_plan_debug"),
            "chart_planner": state.get("chart_plan_debug"),
            "template": template,
            "scope": scope,
            "report_warnings": getattr(report, "warnings", None),
            "validation_warnings": getattr(report, "validation_warnings", None),
            "template_context": bundle_facts.get("template_context"),
            "table_insights": bundle_facts.get("table_insights"),
            "chart_insights": bundle_facts.get("chart_insights"),
            "report_facts": facts_debug,
            "status_messages": getattr(report, "status_messages", None),
            "chart_error": state.get("chart_error"),
        })

def _render_common_sidebar() -> tuple[str, dict[str, Any]]:
    with st.sidebar:
        st.title("🧭 Chọn chức năng")
        mode_label = st.radio("Giao diện", list(TASK_MODE_OPTIONS.keys()), index=0)
        mode = TASK_MODE_OPTIONS[mode_label]
        st.session_state["app_task_mode"] = mode

        st.divider()
        st.title("⚙️ Phạm vi dữ liệu")
        base_stats = get_sidebar_stats()

        nam_options = ["(Tất cả)"] + [str(x) for x in base_stats.get("nams", [])]
        nam = st.selectbox("📅 Năm", nam_options, key="scope_filter_nam")

        # Q&A cần cả năm và khu vực để hỏi đáp/truy vấn linh hoạt.
        # Báo cáo hành chính chỉ lọc theo năm.
        if mode == "week23":
            huyen_options = ["(Tất cả)"] + list(base_stats.get("huyens", []))
            huyen = st.selectbox("📍 Khu vực / Huyện, TP", huyen_options, key="qa_scope_filter_huyen")
            filters = {
                "huyen": None if huyen == "(Tất cả)" else str(huyen),
                "nam": None if nam == "(Tất cả)" else int(nam),
            }
        else:
            filters = {
                "huyen": None,
                "nam": None if nam == "(Tất cả)" else int(nam),
            }

        stats = get_sidebar_stats(huyen=filters["huyen"], nam=filters["nam"])
        st.caption(f"📍 {_safe_scope_label(filters)}")
        c1, c2 = st.columns(2)
        c1.metric("Tổng hộ", f"{stats.get('tong_ho', 0):,}")
        c2.metric("Hộ nghèo", f"{stats.get('ho_ngheo', 0):,}")
        c3, c4 = st.columns(2)
        c3.metric("Cận nghèo", f"{stats.get('ho_can_ngheo', 0):,}")
        c4.metric("Không nghèo", f"{stats.get('ho_khong_ngheo', 0):,}")

        if mode == "report":
            st.divider()
            st.title("📝 Văn phong báo cáo")
            if st.button("🔄 Cập nhật biểu mẫu văn phong", use_container_width=True):
                ok, msg = _train_report_profile()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
            report_mode_options = [
                "Không dùng LLM (Python an toàn)",
                "Có LLM (rewrite/planner/Excel LLM)",
            ]
            # Chuẩn hóa giá trị cũ trong session_state để st.radio không bị lệch options.
            previous_report_mode = str(st.session_state.get("report_generation_mode", ""))
            if previous_report_mode and previous_report_mode not in report_mode_options:
                st.session_state["report_generation_mode"] = (
                    report_mode_options[1] if previous_report_mode.startswith("Có LLM") else report_mode_options[0]
                )
            report_mode_label = st.radio(
                "Chế độ báo cáo",
                report_mode_options,
                index=0,
                key="report_generation_mode",
                help=(
                    "Không dùng LLM: Python sinh văn bản, bảng, biểu đồ và Excel mẫu gốc. "
                    "Có LLM: LLM rewrite văn bản, lập plan bảng/biểu đồ và hỗ trợ mapping Excel; Python vẫn validate, tính số và ghi Excel. "
                    "Nếu văn bản LLM không đạt hậu kiểm, UI báo lỗi để sinh lại hoặc sửa tay, không tự thay bằng bản Python."
                ),
            )
            # Excel đi theo cùng chế độ báo cáo; không còn toggle Excel LLM riêng.
            st.session_state["report_excel_llm_mode"] = _current_report_excel_mode_label()
            if str(report_mode_label).startswith("Có LLM"):
                st.caption("LLM được dùng cho nhận định, planner bảng/biểu đồ và mapping Excel; Python vẫn validate, tính số và ghi Excel.")
            else:
                st.caption("Toàn bộ văn bản, bảng, biểu đồ và Excel dùng luồng Python an toàn.")
            with st.expander("Cài đặt nâng cao", expanded=False):
                # Dọn key cũ để UI không còn hiểu rằng Excel có chế độ tách riêng.
                st.session_state.pop("report_use_experimental_llm_excel", None)
                profile_value = st.text_input("File cấu hình văn phong", value=_default_profile_text(), key="report_profile_path")
                resolved_profile = _resolve_project_path(profile_value)
                if resolved_profile and resolved_profile.exists():
                    st.caption(f"Đang dùng: `{_relative_or_str(resolved_profile)}`")
                else:
                    st.warning("Chưa thấy style profile. Có thể bấm cập nhật biểu mẫu văn phong.")
                st.toggle("Đa dạng văn phong có kiểm soát", value=True, key="report_allow_variation")
                st.number_input(
                    "Số từ tối thiểu LLM phải tạo",
                    min_value=120,
                    max_value=500,
                    value=int(st.session_state.get("report_llm_min_words", 180) or 180),
                    step=20,
                    key="report_llm_min_words",
                    help="Chỉ áp dụng cho chế độ Có LLM. Nếu văn bản LLM ít hơn ngưỡng này, hậu kiểm sẽ không chấp nhận và LLM sẽ tự retry.",
                )
                st.caption(f"Chế độ Excel hiện tại: {_current_report_excel_mode_label()}")

        st.divider()
        if st.button("🗑️ Xóa lịch sử / kết quả", use_container_width=True):
            keys_to_delete = [
                k for k in st.session_state
                if k.startswith(("chart_type_", "chart_recommendation_", "btn_", "switch_", "dl_", "report_", "week4_", "week5_", "admin_report_"))
            ]
            for k in keys_to_delete:
                del st.session_state[k]
            st.session_state.messages = []
            st.session_state.debug_history = []
            st.rerun()

        st.caption(f"Model: `{MODEL_NAME}`")

    return mode, filters


def _run_qa_turn(question: str, filters: dict[str, Any]) -> None:
    effective_question = question.strip()
    with st.spinner("⏳ Đang truy vấn..."):
        chart_requested, chart_type_hint = detect_chart_request(effective_question)
        answer, result, debug = process_question(effective_question, filters)

        debug["chart_requested"] = chart_requested
        debug["chart_success"] = False
        debug["chart_type_hint"] = chart_type_hint
        debug["chart_debug"] = None
        debug["chart_plan"] = None
        debug["chart_fig"] = None
        debug["chart_df"] = None
        debug["chart_recommendation_visible"] = False
        debug["chart_recommendation"] = None
        debug["optional_chart_success"] = False
        debug["optional_chart_source"] = None
        debug["optional_chart_type"] = None
        debug["optional_chart_debug"] = None

        result_df = to_dataframe(result)
        if isinstance(result_df, pd.DataFrame):
            result_df = _safe_df(result_df)

        if chart_requested:
            chart_df = None
            plan_for_chart = debug.get("query_plan") or {}
            if isinstance(result_df, pd.DataFrame) and not result_df.empty:
                chart_df = prepare_chart_df(_safe_df(result_df), effective_question, plan_for_chart)

            if chart_df is not None and is_chartable(chart_df):
                allowed = allowed_chart_types(chart_df, effective_question, plan_for_chart)
                chosen_type = chart_type_hint or infer_chart_type(chart_df, effective_question, plan_for_chart)
                requested_chart_type = chosen_type
                chosen_type, chart_fallback_used = resolve_requested_chart_type(chosen_type, allowed)

                if chart_fallback_used:
                    debug["chart_debug"] = {
                        "source": "qa_result_df",
                        "fallback_reason": "unsupported_chart_type_for_current_df",
                        "requested_chart_type": requested_chart_type,
                        "fallback_chart_type": chosen_type,
                        "allowed_chart_types": allowed,
                        "df_columns": list(chart_df.columns),
                        "df_head": chart_df.head(5).to_dict(orient="records"),
                    }
                    block_reason = pie_block_reason(chart_df, effective_question, plan_for_chart) if requested_chart_type == "pie" else None
                    if block_reason == "too_many_groups":
                        answer = "Dữ liệu có nhiều nhóm, biểu đồ cột phù hợp hơn biểu đồ tròn."
                    elif block_reason == "independent_ratio":
                        answer = "Dữ liệu là tỷ lệ so sánh theo từng nhóm, biểu đồ cột phù hợp hơn biểu đồ tròn."
                    else:
                        answer = (
                            f"Loại biểu đồ yêu cầu ({CHART_TYPE_LABELS.get(requested_chart_type, requested_chart_type)}) "
                            f"không phù hợp với dữ liệu; hệ thống chuyển sang "
                            f"{CHART_TYPE_LABELS.get(chosen_type, chosen_type).lower()}."
                        )

                if chosen_type in allowed:
                    chart_fig = make_chart(chart_df, chart_type=chosen_type, title="", question=effective_question, plan=plan_for_chart)
                    if chart_fig is not None:
                        chart_fig.update_layout(title_text="")

                    chart_debug = debug.get("chart_debug") or {}
                    chart_debug.update({
                        "source": "qa_result_df",
                        "chart_type": chosen_type,
                        "requested_chart_type": requested_chart_type,
                        "fallback_used": chart_fallback_used,
                        "allowed_chart_types": allowed,
                        "df_columns": list(chart_df.columns),
                        "df_head": chart_df.head(5).to_dict(orient="records"),
                    })
                    if chart_fig is not None and chart_fig.layout.meta:
                        chart_debug.update(dict(chart_fig.layout.meta))
                    debug["chart_debug"] = chart_debug

                    if chart_fig is not None:
                        debug["chart_success"] = True
                        debug["chart_source"] = "qa_result_df"
                        debug["chart_type"] = chosen_type
                        debug["chart_fallback_used"] = chart_fallback_used
                        debug["chart_fig"] = chart_fig
                        debug["chart_df"] = chart_df
                        if chart_fallback_used:
                            debug["chart_fallback_notice"] = answer
                        answer = build_chart_answer(effective_question, chart_df, chart_debug, plan_for_chart, result_df=result_df)
                    else:
                        debug["chart_success"] = False
                        answer = "Không thể tạo biểu đồ từ bảng dữ liệu hiện tại."
                else:
                    debug["chart_success"] = False
                    answer = "Không có loại biểu đồ phù hợp với bảng dữ liệu hiện tại."
            else:
                debug["chart_success"] = False
                debug["chart_debug"] = {"source": "qa_result_df", "error": "Q&A không trả về bảng hoặc bảng không đủ điều kiện vẽ biểu đồ."}

    debug["result_df"] = result_df
    debug["question"] = effective_question
    debug["user_question"] = question
    debug["answer"] = answer
    debug["filters"] = filters
    _annotate_render_debug(debug)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.debug_history.append(debug)
    try:
        _write_qa_log(effective_question, answer, debug, filters)
    except OSError:
        pass


def _render_week23_page(filters: dict[str, Any]) -> None:
    st.title("📊 Q&A")
    st.caption(
        "Luồng Q&A dùng để hỏi đáp và truy vấn dữ liệu, hiển thị bảng kết quả, tải XLSX/CSV "
        "và tạo biểu đồ cột, tròn hoặc đường theo câu hỏi."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "debug_history" not in st.session_state:
        st.session_state.debug_history = []

    debug_index = 0
    for msg_idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["content"])
            else:
                if debug_index < len(st.session_state.debug_history):
                    debug = st.session_state.debug_history[debug_index]
                    _render_assistant_turn(debug_index, message["content"], debug)
                    debug_index += 1
                else:
                    st.markdown(message["content"])

    st.divider()
    with st.form("chat_form", clear_on_submit=True):
        col_q, col_btn = st.columns([5, 1])
        question = col_q.text_input(
            "Câu hỏi",
            placeholder="Ví dụ: Vẽ biểu đồ hộ nghèo theo huyện năm 2024 hoặc thống kê hộ cận nghèo theo huyện...",
            label_visibility="collapsed",
        )
        submitted = col_btn.form_submit_button("Gửi", use_container_width=True)

    if submitted and question.strip():
        st.session_state.messages.append({"role": "user", "content": question.strip()})
        _run_qa_turn(question.strip(), filters)
        st.rerun()


def _render_template_picker(prefix: str) -> int:
    options = _template_options(include_extended=False)
    labels = list(options.keys())
    selected = st.selectbox("Chọn loại báo cáo / mẫu 1-12", labels, key=f"{prefix}_template")
    return options[selected]


def _render_report_page(filters: dict[str, Any]) -> None:
    st.title("📝 Báo cáo")
    st.caption(
        "Luồng Báo cáo dùng để chọn 1 trong 12 mẫu, tạo nội dung báo cáo, bộ số liệu báo cáo, "
        "biểu đồ minh họa từ bộ số liệu báo cáo và xuất Word/Excel báo cáo theo mẫu."
    )

    with st.form("admin_report_form"):
        template_id = _render_template_picker("admin_report")
        st.info(f"Phạm vi dữ liệu báo cáo: {_safe_scope_label(filters)}")
        agency_meta = _render_agency_meta_inputs("admin_report", filters)
        submitted = st.form_submit_button("Sinh / cập nhật báo cáo", use_container_width=True)

    if submitted:
        st.session_state["admin_report_active_section"] = "Báo cáo"
        with st.spinner("Đang tạo dữ liệu, nội dung báo cáo, bảng số liệu và biểu đồ..."):
            st.session_state["admin_report_state"] = _generate_template_report_state(
                template_id,
                filters,
                "administrative_report_week4_week5",
                agency_meta=agency_meta,
                regenerate_nonce=0,
            )

    state = st.session_state.get("admin_report_state")
    if state:
        _render_template_report_state(state, allow_export=True)


def main():
    st.set_page_config(
        page_title="Hệ thống phân tích hộ nghèo",
        page_icon="💬",
        layout="wide",
    )

    st.markdown("""
    <style>
    [data-testid="stButton"] > button { width: 100%; font-size: 0.85rem; }
    [data-testid="stDownloadButton"] > button { width: 100%; font-size: 0.85rem; }
    </style>
    """, unsafe_allow_html=True)

    if not DB_PATH.exists():
        st.warning("⚠️ Chưa có database. Chạy `python build_db.py` trước.")
        return

    mode, filters = _render_common_sidebar()

    if mode == "week23":
        _render_week23_page(filters)
    elif mode == "report":
        _render_report_page(filters)
    else:
        st.error("Chưa xác định được chế độ giao diện.")


if __name__ == "__main__":
    main()
