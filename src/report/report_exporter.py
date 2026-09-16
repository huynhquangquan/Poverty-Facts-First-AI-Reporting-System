from __future__ import annotations

from io import BytesIO
from typing import Any
from numbers import Number
import re

import pandas as pd

try:
    from .report_fact_builder import ReportFactsBundle
except Exception:  # pragma: no cover
    from report_fact_builder import ReportFactsBundle  # type: ignore


DEFAULT_AGENCY_META: dict[str, str] = {
    "parent_agency": "ỦY BAN NHÂN DÂN TỈNH ĐẮK NÔNG",
    "issuing_agency": "CƠ QUAN LẬP BÁO CÁO",
    "document_no": "        /BC-UBND",
    "place": "Đắk Nông",
    "document_date": "ngày ... tháng ... năm ...",
    # Demo: không in khối "Nơi nhận"/chức danh hành chính thật.
    "recipient": "",
    "prepared_by": "",
    "signing_block": "",
    "signer_title": "NGƯỜI LẬP BÁO CÁO",
    "signer_name": "",
    "archive_note": "",
    "document_author": "admin",
}

TABLE_TITLES = {
    "main": "Bảng số liệu chính",
    "by_district": "Bảng tổng hợp theo địa bàn",
    "district": "Bảng tổng hợp theo địa bàn",
    "overview": "Bảng tổng hợp chung",
    "template_chart": "Bảng tổng hợp nhóm hộ",
    "template_main": "Bảng chi tiết theo địa bàn",
}

COLUMN_LABELS = {
    "phan_loai": "Phân loại hộ",
    "so_ho": "Số hộ",
    "so_nhan_khau": "Số nhân khẩu",
    "ty_le_%": "Tỷ lệ (%)",
    "huyen": "Huyện/TP",
    "xa_phuong": "Xã/phường",
    "chi_tieu": "Chỉ tiêu",
    "dan_toc": "Dân tộc",
    "nguyen_nhan": "Nguyên nhân",
    "tong_nhom": "Tổng nhóm",
    "so_ho_ngheo": "Số hộ nghèo",
    "ty_le_ho_ngheo_%": "Tỷ lệ hộ nghèo (%)",
    "so_ho_can_ngheo": "Số hộ cận nghèo",
    "ty_le_ho_can_ngheo_%": "Tỷ lệ hộ cận nghèo (%)",
    "so_ho_ky_truoc": "Số hộ kỳ trước",
    "so_ho_ky_sau": "Số hộ kỳ sau",
    "nam_truoc": "Năm trước",
    "nam_sau": "Năm sau",
    "chenh_lech": "Chênh lệch",
    "ty_le_bien_dong_%": "Tỷ lệ biến động (%)",
    "tong_ho_ra_soat": "Tổng hộ rà soát",
    "tong_nhan_khau": "Tổng nhân khẩu",
    "tong_ho_dan_cu": "Tổng số hộ dân cư",
    "so_khau_ngheo": "Số khẩu hộ nghèo",
    "so_khau_can_ngheo": "Số khẩu hộ cận nghèo",
    "so_ho_nlnndn_mstb": "Số hộ nông, lâm, ngư nghiệp có mức sống trung bình",
    "so_khau_nlnndn_mstb": "Số khẩu nông, lâm, ngư nghiệp có mức sống trung bình",
    "nhom_chi_tieu": "Nhóm chỉ tiêu",
    "so_ho_muc_tieu": "Số hộ mục tiêu",
    "so_nhan_khau_muc_tieu": "Số nhân khẩu mục tiêu",
    "so_ho_kinh": "Số hộ dân tộc Kinh",
    "so_ho_dtts": "Số hộ DTTS",
    "so_ho_dtts_tai_cho": "Số hộ DTTS tại chỗ",
    "ty_le_muc_tieu_%": "Tỷ lệ hộ mục tiêu (%)",
    "ty_le_dtts_trong_nhom_%": "Tỷ lệ DTTS trong nhóm (%)",
}


def merge_agency_meta(agency_meta: dict[str, Any] | None = None) -> dict[str, str]:
    meta = dict(DEFAULT_AGENCY_META)
    for key, value in (agency_meta or {}).items():
        text = "" if value is None else str(value).strip()
        if text:
            meta[key] = text
    return meta


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, Number) and not isinstance(value, bool):
        try:
            n = float(value)
            if abs(n - int(n)) < 1e-9:
                return f"{int(n):,}".replace(",", ".")
            return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            pass
    return str(value)


def _is_blank_like(value: Any) -> bool:
    """True với None/NaN/pd.NA để không ghi trực tiếp các sentinel này vào Excel."""
    if value is None:
        return True
    try:
        result = pd.isna(value)
        if isinstance(result, bool):
            return result
    except Exception:
        pass
    return False


def _excel_value(value: Any, blank: Any = None) -> Any:
    """Chuẩn hóa giá trị trước khi ghi openpyxl.

    openpyxl không nhận pandas.NA (`Cannot convert <NA> to Excel`).
    Vì vậy mọi giá trị thiếu được chuyển thành None/ô trống. Các kiểu số,
    chuỗi, bool, datetime hợp lệ được giữ nguyên.
    """
    if _is_blank_like(value):
        return blank
    return value


def _is_number_for_excel(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool) and not _is_blank_like(value)


def _table_title(name: str) -> str:
    return TABLE_TITLES.get(str(name), str(name).replace("_", " ").title())


def _column_labels_for_pattern(pattern: str | None = None) -> dict[str, str]:
    labels = dict(COLUMN_LABELS)
    if pattern == "child_deprivation":
        labels.update({
            "so_ho_ngheo": "Số trẻ thuộc hộ nghèo",
            "ty_le_ho_ngheo_%": "Tỷ lệ trên tổng trẻ hộ nghèo (%)",
            "so_ho_can_ngheo": "Số trẻ thuộc hộ cận nghèo",
            "ty_le_ho_can_ngheo_%": "Tỷ lệ trên tổng trẻ hộ cận nghèo (%)",
        })
    return labels


def _rename_df(df: pd.DataFrame, pattern: str | None = None) -> pd.DataFrame:
    out = df.copy()
    labels = _column_labels_for_pattern(pattern)
    out = out.rename(columns={c: labels.get(str(c), str(c)) for c in out.columns})
    return out


def _scope_label(bundle: ReportFactsBundle) -> str:
    scope = bundle.scope or {}
    summary = bundle.summary or {}
    return str(scope.get("scope_label") or summary.get("scope_label") or "phạm vi đã chọn")


def _chart_analysis(chart_df: pd.DataFrame | None) -> str:
    if not isinstance(chart_df, pd.DataFrame) or chart_df.empty or chart_df.shape[1] < 2:
        return "Biểu đồ được lập từ bảng số liệu chính của báo cáo, có chức năng hỗ trợ đối chiếu trực quan với phần nhận định và bảng tổng hợp."
    numeric_cols = [c for c in chart_df.columns if pd.api.types.is_numeric_dtype(chart_df[c])]
    if not numeric_cols:
        return "Biểu đồ được lập từ bảng số liệu chính của báo cáo, có chức năng hỗ trợ đối chiếu trực quan với phần nhận định và bảng tổng hợp."
    value_col = numeric_cols[0]
    top = chart_df.sort_values(value_col, ascending=False).iloc[0]
    unit = " hộ" if "hộ" in str(value_col).lower() or "Số hộ" in str(value_col) else ""

    label_cols = [c for c in chart_df.columns if c != value_col]
    if "Địa bàn" in chart_df.columns and "Nhóm chỉ tiêu" in chart_df.columns:
        label_text = f"{top.get('Nhóm chỉ tiêu')} tại {top.get('Địa bàn')}"
    elif len(label_cols) >= 2:
        label_text = " - ".join(_clean_text(top.get(c)) for c in label_cols if _clean_text(top.get(c)))
    elif label_cols:
        label_text = _clean_text(top.get(label_cols[0]))
    else:
        label_text = "chỉ tiêu cao nhất"

    return (
        f"Biểu đồ minh họa cho thấy {label_text} có giá trị cao nhất trong các nhóm được so sánh, "
        f"đạt {_clean_text(top[value_col])}{unit}. Kết quả này được dùng để hỗ trợ đối chiếu trực quan với bảng số liệu và phần nhận định, "
        "không thay thế cho việc kiểm tra chi tiết theo từng địa bàn hoặc nhóm chỉ tiêu."
    )




def _clean_word_report_text_line(line: str) -> str:
    """Làm sạch câu nhận định trước khi ghi vào Word.

    Đây chỉ là lớp phòng vệ cuối; logic chính vẫn nằm ở report_writer validator.
    Không đổi số liệu, chỉ bỏ marker debug/mẫu/cột kỹ thuật nếu còn sót.
    """
    raw = str(line or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\bDB\b", "nguồn dữ liệu hiện có", raw)
    raw = re.sub(r"(?i)\bmẫu\s*(?:số\s*)?\d+\s*:?\s*", "", raw)
    raw = re.sub(r"(?i)\btheo\s+công\s+thức(?:\s+biểu\s+mẫu)?\b", "theo kết quả tổng hợp", raw)
    raw = re.sub(r"(?i)\bcông\s+thức\s+biểu\s+mẫu\b", "kết quả tổng hợp", raw)
    raw = re.sub(r"(?i)\bcác\s+cột\s+([A-Z](?:\s*[,/+&:-]\s*[A-Z]){0,10})", "các chỉ tiêu tương ứng", raw)
    raw = re.sub(r"(?i)\bcột\s+([A-Z](?:\s*[,/+&:-]\s*[A-Z]){0,10})", "chỉ tiêu tương ứng", raw)
    raw = re.sub(r"(?i)\b(?:SAFE_BASE_TEXT|REPORT_FACTS|fact\s*pack|fact\s*bundle|template_id|validator|audit|debug|JSON|Python|SQL|Excel\s+mapping)\b", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" ;:-")
    return raw

def _iter_report_lines(report_text: str) -> list[tuple[str, bool]]:
    """Trả về (line, is_subheading). Bỏ title/marker thừa và chuẩn hóa heading."""
    out: list[tuple[str, bool]] = []
    skip_next_title = False
    for raw in str(report_text or "").splitlines():
        line = _clean_word_report_text_line(raw.strip())
        if not line:
            continue
        if line.upper().startswith("BÁO CÁO NHẬN ĐỊNH"):
            skip_next_title = True
            continue
        if skip_next_title:
            skip_next_title = False
            continue
        m_roman = re.match(r"^([IVX]+)\.\s*(.+)$", line, flags=re.I)
        if m_roman:
            order = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5"}.get(m_roman.group(1).upper(), m_roman.group(1))
            out.append((f"{order}. {m_roman.group(2)}", True))
            continue
        if re.match(r"^\d+\.\s+", line):
            # Nhận định trong Word không nên thành danh sách đánh số; bỏ số thứ tự và ghi như đoạn văn thường.
            line = re.sub(r"^\d+\.\s+", "", line).strip()
            if line:
                out.append((line, False))
        else:
            out.append((line, False))
    return out


# ───────────────────────────── DOCX helpers ─────────────────────────────

def _set_run_font(run: Any, size: float | None = None, bold: bool | None = None, italic: bool | None = None) -> None:
    from docx.shared import Pt
    from docx.oxml.ns import qn

    run.font.name = "Times New Roman"
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    try:
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.rFonts
        if rFonts is None:
            rFonts = run._element._new_rPr().rFonts
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rFonts.set(qn("w:eastAsia"), "Times New Roman")
        rFonts.set(qn("w:cs"), "Times New Roman")
    except Exception:
        pass


def _set_paragraph_format(paragraph: Any, *, align: Any | None = None, space_after: float = 4, line_spacing: float = 1.18) -> None:
    from docx.shared import Pt

    if align is not None:
        paragraph.alignment = align
    fmt = paragraph.paragraph_format
    fmt.space_after = Pt(space_after)
    fmt.line_spacing = line_spacing


def _remove_table_borders(table: Any) -> None:
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tbl = table._tbl
        tblPr = tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            tag = OxmlElement(f"w:{edge}")
            tag.set(qn("w:val"), "nil")
            borders.append(tag)
        tblPr.append(borders)
    except Exception:
        pass


def _add_heading_p(doc: Any, text: str, level: int = 1) -> Any:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p = doc.add_paragraph()
    _set_paragraph_format(p, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=4)
    r = p.add_run(text.upper() if level == 1 else text)
    _set_run_font(r, size=14, bold=True)
    return p


def _add_body_p(doc: Any, text: str, *, italic: bool = False, justify: bool = True) -> Any:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p = doc.add_paragraph()
    _set_paragraph_format(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY if justify else WD_ALIGN_PARAGRAPH.LEFT, space_after=6)
    r = p.add_run(text)
    _set_run_font(r, size=14, italic=italic)
    return p


def _set_table_fit(table: Any) -> None:
    """Ép bảng vừa chiều rộng trang Word, dùng layout cố định để không tràn lề."""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tbl = table._tbl
        tblPr = tbl.tblPr
        tblW = tblPr.tblW
        if tblW is None:
            tblW = OxmlElement("w:tblW")
            tblPr.append(tblW)
        tblW.set(qn("w:type"), "pct")
        tblW.set(qn("w:w"), "5000")  # 100% chiều rộng vùng soạn thảo
        layout = tblPr.tblLayout
        if layout is None:
            layout = OxmlElement("w:tblLayout")
            tblPr.append(layout)
        layout.set(qn("w:type"), "fixed")
    except Exception:
        pass


def _set_cell_margins(cell: Any, *, top: int = 45, start: int = 55, bottom: int = 45, end: int = 55) -> None:
    """Giảm padding ô để bảng gọn hơn. Đơn vị twips."""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcMar = tcPr.first_child_found_in("w:tcMar")
        if tcMar is None:
            tcMar = OxmlElement("w:tcMar")
            tcPr.append(tcMar)
        for edge, value in (("top", top), ("start", start), ("left", start), ("bottom", bottom), ("end", end), ("right", end)):
            node = tcMar.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                tcMar.append(node)
            node.set(qn("w:w"), str(value))
            node.set(qn("w:type"), "dxa")
    except Exception:
        pass


def _shade_cell(cell: Any, fill: str = "D9EAF7") -> None:
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tcPr = cell._tc.get_or_add_tcPr()
        shd = tcPr.find(qn("w:shd"))
        if shd is None:
            shd = OxmlElement("w:shd")
            tcPr.append(shd)
        shd.set(qn("w:fill"), fill)
    except Exception:
        pass


def _set_cell_width(cell: Any, width_cm: float) -> None:
    try:
        from docx.shared import Cm
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        cell.width = Cm(width_cm)
        tcPr = cell._tc.get_or_add_tcPr()
        tcW = tcPr.tcW
        if tcW is None:
            tcW = OxmlElement("w:tcW")
            tcPr.append(tcW)
        tcW.set(qn("w:type"), "dxa")
        tcW.set(qn("w:w"), str(max(1, int(width_cm * 567))))
    except Exception:
        pass


def _available_docx_width_cm(doc: Any) -> float:
    try:
        section = doc.sections[-1]
        width = section.page_width - section.left_margin - section.right_margin
        return float(width.cm)
    except Exception:
        return 17.5


def _compact_docx_column_label(label: Any) -> str:
    """Rút gọn nhãn cột chỉ cho Word để bảng không bị quá rộng."""
    text = str(label or "")
    replacements = {
        "Số hộ nông, lâm, ngư nghiệp có mức sống trung bình": "Số hộ NLNN MSTB",
        "Số khẩu nông, lâm, ngư nghiệp có mức sống trung bình": "Số khẩu NLNN MSTB",
        "Hộ nông, lâm, ngư nghiệp có mức sống trung bình": "Hộ NLNN MSTB",
        "Tỷ lệ trên tổng trẻ hộ nghèo (%)": "Tỷ lệ trẻ hộ nghèo (%)",
        "Tỷ lệ trên tổng trẻ hộ cận nghèo (%)": "Tỷ lệ trẻ hộ cận nghèo (%)",
        "Số trẻ thuộc hộ nghèo": "Số trẻ hộ nghèo",
        "Số trẻ thuộc hộ cận nghèo": "Số trẻ hộ cận nghèo",
        "Tổng hộ rà soát": "Tổng hộ rà soát",
        "Tổng số hộ dân cư": "Tổng hộ dân cư",
        "Tỷ lệ hộ mục tiêu (%)": "Tỷ lệ hộ mục tiêu (%)",
    }
    text = replacements.get(text, text)
    text = text.replace("nông, lâm, ngư nghiệp", "NLNN")
    text = text.replace("mức sống trung bình", "MSTB")
    text = text.replace("Tỷ lệ biến động (%)", "Tỷ lệ BĐ (%)")
    text = text.replace("Chênh lệch", "Chênh lệch")
    return text


def _rename_df_for_docx(df: pd.DataFrame, pattern: str | None = None) -> pd.DataFrame:
    out = _rename_df(df, pattern=pattern)
    out = out.copy()
    out.columns = [_compact_docx_column_label(c) for c in out.columns]
    return out


def _docx_table_font_size(num_cols: int) -> float:
    if num_cols >= 10:
        return 8.0
    if num_cols >= 8:
        return 8.5
    if num_cols >= 6:
        return 9.5
    return 10.5


def _column_widths_cm(columns: list[Any], total_width_cm: float) -> list[float]:
    weights: list[float] = []
    for idx, col in enumerate(columns):
        low = str(col or "").lower()
        weight = 1.0
        if idx == 0 or any(k in low for k in ("địa bàn", "huyện", "chỉ tiêu", "phân loại", "nguyên nhân", "dân tộc", "nhóm")):
            weight = 2.3
        elif "%" in low or "tỷ lệ" in low or "tỉ lệ" in low:
            weight = 1.15
        elif "nhân khẩu" in low or "số khẩu" in low:
            weight = 1.25
        elif "số hộ" in low or "tổng hộ" in low or "chênh lệch" in low:
            weight = 1.2
        if len(str(col)) > 28:
            weight += 0.35
        weights.append(weight)
    total_weight = sum(weights) or 1.0
    min_width = 1.05 if len(columns) >= 8 else 1.25
    widths = [max(min_width, total_width_cm * w / total_weight) for w in weights]
    scale = total_width_cm / (sum(widths) or total_width_cm)
    return [max(0.9, w * scale) for w in widths]


def _set_docx_core_properties(doc: Any, meta: dict[str, str], title: str) -> None:
    """Metadata sạch cho file Word xuất ra."""
    try:
        cp = doc.core_properties
        cp.author = "admin"
        cp.last_modified_by = "admin"
        cp.title = ""
        cp.subject = ""
        cp.keywords = ""
        cp.comments = ""
    except Exception:
        pass


def _set_xlsx_core_properties(wb: Any, title: str | None = None) -> None:
    """Metadata sạch cho file Excel xuất ra."""
    try:
        props = wb.properties
        props.creator = "admin"
        props.lastModifiedBy = "admin"
        props.title = ""
        props.subject = ""
        props.keywords = ""
        props.description = ""
        props.category = ""
        props.contentStatus = ""
        try:
            props.comments = ""
        except Exception:
            pass
    except Exception:
        pass


def _set_row_cant_split(row: Any) -> None:
    """Không để một hàng bảng bị cắt ngang sang trang sau."""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        trPr = row._tr.get_or_add_trPr()
        if trPr.find(qn("w:cantSplit")) is None:
            trPr.append(OxmlElement("w:cantSplit"))
    except Exception:
        pass


def _set_row_repeat_header(row: Any) -> None:
    """Lặp hàng tiêu đề nếu bảng sang trang."""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        trPr = row._tr.get_or_add_trPr()
        if trPr.find(qn("w:tblHeader")) is None:
            tag = OxmlElement("w:tblHeader")
            tag.set(qn("w:val"), "true")
            trPr.append(tag)
    except Exception:
        pass



def _add_docx_table(doc: Any, title: str, df: pd.DataFrame, max_rows: int = 35, pattern: str | None = None) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

    if not isinstance(df, pd.DataFrame) or df.empty:
        return
    _add_heading_p(doc, title, level=2)
    show = _rename_df_for_docx(df, pattern=pattern).head(max_rows)
    if show.empty:
        return

    font_size = _docx_table_font_size(len(show.columns))
    total_width_cm = _available_docx_width_cm(doc)
    widths = _column_widths_cm(list(show.columns), total_width_cm)

    table = doc.add_table(rows=1, cols=len(show.columns))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_table_fit(table)
    _set_row_cant_split(table.rows[0])
    _set_row_repeat_header(table.rows[0])

    hdr = table.rows[0].cells
    for idx, col in enumerate(show.columns):
        hdr[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_width(hdr[idx], widths[idx])
        _set_cell_margins(hdr[idx])
        _shade_cell(hdr[idx])
        p = hdr[idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = 0
        p.paragraph_format.space_after = 0
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(str(col))
        _set_run_font(r, size=max(8.0, font_size), bold=True)

    for _, row in show.iterrows():
        row_obj = table.add_row()
        _set_row_cant_split(row_obj)
        cells = row_obj.cells
        for idx, col in enumerate(show.columns):
            cells[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_width(cells[idx], widths[idx])
            _set_cell_margins(cells[idx])
            p = cells[idx].paragraphs[0]
            p.paragraph_format.space_before = 0
            p.paragraph_format.space_after = 0
            p.paragraph_format.line_spacing = 1.0
            val = row[col]
            is_num = isinstance(val, (int, float)) and not isinstance(val, bool)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if is_num else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(_clean_text(val))
            _set_run_font(r, size=font_size)

    # Khoảng cách sau bảng vừa phải, tránh bảng dính vào đoạn sau nhưng không tạo trang trắng.
    doc.add_paragraph().paragraph_format.space_after = 2
    if len(df) > len(show):
        _add_body_p(doc, f"Bảng hiển thị {len(show)} dòng đầu tiên trên tổng số {len(df)} dòng; dữ liệu đầy đủ được lưu trong hệ thống xuất báo cáo.", italic=True)

def _top_numeric_record(df: pd.DataFrame) -> tuple[str, str, Any] | None:
    if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
        return None
    label_col = df.columns[0]
    numeric_cols = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return None
    value_col = numeric_cols[0]
    try:
        row = df.sort_values(value_col, ascending=False).iloc[0]
        return str(label_col), str(value_col), row
    except Exception:
        return None


def _table_analysis_paragraphs(report_tables: list[tuple[str, pd.DataFrame]], *, pattern: str | None = None) -> list[str]:
    """Sinh đoạn phân tích chung cho mọi mẫu, không hard-code riêng mẫu 1.

    Mục tiêu là tạo giọng báo cáo tự nhiên hơn thay vì mô tả máy móc theo tên cột.
    Hàm chỉ đọc các bảng đã chọn để đưa vào Word, không dùng bảng debug/thô.
    """
    paragraphs: list[str] = []
    for idx, (title, df) in enumerate(report_tables[:3], start=1):
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        show = _rename_df(df, pattern=pattern)
        top = _top_numeric_record(show)
        if top is None:
            paragraphs.append(
                f"{title} được sử dụng làm căn cứ đối chiếu cho phần nhận định của báo cáo. "
                "Các dòng số liệu trong bảng cần được xem xét trong cùng phạm vi tổng hợp để bảo đảm việc đánh giá không vượt quá nội dung dữ liệu đang có."
            )
            continue
        label_col, value_col, row = top
        unit = " hộ" if "hộ" in value_col.lower() else ""
        top_label = _clean_text(row[label_col])
        top_value = _clean_text(row[value_col])
        if idx == 1:
            paragraphs.append(
                f"{title} cho thấy nhóm nổi bật nhất theo {value_col.lower()} là {top_label}, đạt {top_value}{unit}. "
                "Kết quả này giúp xác định nhóm cần ưu tiên theo dõi trong phần nhận định, đồng thời vẫn cần được đặt trong tương quan với các nhóm còn lại để bảo đảm đánh giá cân đối."
            )
        else:
            paragraphs.append(
                f"Ở bảng chi tiết, {top_label} là địa bàn/chỉ tiêu có giá trị cao nhất theo {value_col.lower()}, với {top_value}{unit}. "
                "Thông tin này hỗ trợ nhận diện địa bàn hoặc nhóm chỉ tiêu cần được kiểm tra, đối chiếu thường xuyên hơn trong quá trình tổng hợp, rà soát và xây dựng kế hoạch quản lý."
            )
    if not paragraphs:
        paragraphs.append(
            "Các bảng số liệu trong báo cáo là cơ sở chính để thực hiện phần phân tích, nhận định và kiến nghị. "
            "Việc sử dụng số liệu cần bảo đảm cùng phạm vi tổng hợp, cùng thời điểm rà soát và không mở rộng sang các nội dung chưa được phản ánh trong dữ liệu."
        )
    return paragraphs


def _recommendation_paragraphs(scope_label: str, template_title: str) -> list[str]:
    return [
        f"Trên cơ sở số liệu đã tổng hợp đối với {scope_label}, đề nghị các cơ quan, đơn vị liên quan tiếp tục duy trì việc rà soát, cập nhật và đối chiếu dữ liệu theo cùng phạm vi quản lý. Những nhóm hộ, địa bàn hoặc chỉ tiêu có quy mô nổi bật cần được theo dõi thường xuyên để phục vụ công tác tổng hợp, kiểm tra và xây dựng kế hoạch hỗ trợ phù hợp.",
        "Trong quá trình sử dụng kết quả báo cáo, cần kết hợp số liệu tổng hợp với kết quả xác minh thực tế tại địa phương, nhất là đối với các trường hợp có biến động hoặc có dấu hiệu cần rà soát bổ sung. Các kiến nghị chính sách cụ thể chỉ nên được đề xuất sau khi đã đối chiếu đầy đủ giữa số liệu, nhu cầu của đối tượng và khả năng cân đối nguồn lực của địa phương.",
        "Các kỳ báo cáo tiếp theo nên tiếp tục sử dụng cùng cấu trúc dữ liệu và cùng nguyên tắc tổng hợp để bảo đảm khả năng so sánh, theo dõi biến động và kiểm tra tính nhất quán của kết quả. Đây là điều kiện cần thiết để báo cáo không chỉ dừng ở việc thống kê số liệu mà còn hỗ trợ tốt hơn cho công tác quản lý nhà nước về giảm nghèo và an sinh xã hội."
    ]



def _docx_report_tables(bundle: ReportFactsBundle) -> list[tuple[str, pd.DataFrame]]:
    """Chọn đúng các bảng nghiệp vụ để đưa vào Word.

    Không in toàn bộ bundle.tables vì trong bundle có thể còn bảng trung gian
    phục vụ tính toán/debug như main/by_district. Word hành chính chỉ nên in
    các bảng đang dùng để đối chiếu báo cáo.
    """
    tables = bundle.tables or {}
    selected: list[tuple[str, pd.DataFrame]] = []

    preferred = [
        ("template_chart", "Bảng tổng hợp chỉ tiêu"),
        ("template_main", "Bảng số liệu chi tiết"),
    ]
    for key, title in preferred:
        df = tables.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            selected.append((title, df))

    if selected:
        return selected

    # Fallback cho các mẫu/chế độ chưa có template_*: giữ hành vi cũ nhưng bỏ bảng rỗng.
    for name, df in tables.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            selected.append((_table_title(str(name)), df))
    return selected


def _normalized_chart_items(
    chart_items: list[dict[str, Any]] | None = None,
    *,
    chart_png_bytes: bytes | None = None,
    chart_df: pd.DataFrame | None = None,
    chart_title: str | None = None,
) -> list[dict[str, Any]]:
    """Chuẩn hóa danh sách biểu đồ đưa vào Word.

    v9 chỉ nhận một chart_png/chart_df nên Word có thể ít biểu đồ hơn UI/log.
    v10 nhận chart_items để mỗi bảng chính có thể có biểu đồ đối chiếu tương ứng.
    """
    out: list[dict[str, Any]] = []
    for item in chart_items or []:
        if not isinstance(item, dict):
            continue
        png = item.get("chart_png_bytes") or item.get("png_bytes")
        df = item.get("chart_df")
        if png is None and not isinstance(df, pd.DataFrame):
            continue
        out.append({
            "title": item.get("title") or "Biểu đồ minh họa",
            "description": item.get("description") or "",
            "chart_png_bytes": png,
            "chart_df": df,
        })
    if out:
        return out
    if chart_png_bytes is not None or isinstance(chart_df, pd.DataFrame):
        return [{
            "title": chart_title or "Biểu đồ minh họa",
            "description": "",
            "chart_png_bytes": chart_png_bytes,
            "chart_df": chart_df,
        }]
    return []


def _add_chart_section(doc: Any, chart_items: list[dict[str, Any]], *, pattern: str | None = None) -> None:
    """Thêm biểu đồ vào Word theo luồng liên tục, không chủ động ngắt trang."""
    if not chart_items:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches

    # Demo không dùng page break cứng: biểu đồ đi tiếp ngay sau bảng.
    # Word vẫn có thể tự sang trang nếu bảng/ảnh dài hơn phần trống còn lại.
    _add_heading_p(doc, "Biểu đồ minh họa", level=2)
    for idx, item in enumerate(chart_items, start=1):
        title = str(item.get("title") or f"Biểu đồ minh họa {idx}")
        if len(chart_items) > 1:
            title = f"Biểu đồ {idx}. {title}"
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        try:
            p.paragraph_format.keep_with_next = True
        except Exception:
            pass
        r = p.add_run(title)
        _set_run_font(r, size=14, bold=True)
        png = item.get("chart_png_bytes")
        if png:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            run.add_picture(BytesIO(png), width=Inches(6.2))
        else:
            _add_body_p(doc, "Biểu đồ chưa được nhúng trong file Word do môi trường xuất ảnh chưa sẵn sàng; phần diễn giải vẫn dựa trên dữ liệu biểu đồ đã được tạo trong hệ thống.", italic=True)


def _report_text_already_discusses_charts(report_text: str) -> bool:
    """Tránh lặp nhận định biểu đồ trong Word.

    report_text do LLM/fallback sinh thường đã có 1 đoạn nhắc biểu đồ. Nếu exporter
    tiếp tục tự thêm phân tích cho từng chart, mục III sẽ bị lặp 2-3 lần cụm
    "Biểu đồ minh họa cho thấy...". Chỉ thêm đoạn biểu đồ tự động khi phần nhận định
    chưa nhắc tới biểu đồ.
    """
    text = str(report_text or "").lower()
    return any(token in text for token in ("biểu đồ", "chart", "minh họa trực quan"))


def _chart_analysis_paragraphs(
    chart_items: list[dict[str, Any]],
    *,
    pattern: str | None = None,
    report_text: str = "",
) -> list[str]:
    if not chart_items or _report_text_already_discusses_charts(report_text):
        return []
    paras: list[str] = []
    for item in chart_items[:3]:
        df = item.get("chart_df")
        if isinstance(df, pd.DataFrame):
            paras.append(_chart_analysis(_rename_df(df, pattern=pattern)))
    return paras

def export_administrative_docx(
    bundle: ReportFactsBundle,
    report_text: str,
    *,
    chart_png_bytes: bytes | None = None,
    chart_df: pd.DataFrame | None = None,
    chart_title: str | None = None,
    chart_items: list[dict[str, Any]] | None = None,
    agency_meta: dict[str, Any] | None = None,
) -> bytes:
    """Xuất Word hành chính một cách chỉnh chu hơn bản v1.

    Điểm chính:
    - Không dùng Heading style mặc định màu xanh của Word.
    - Khóa font Times New Roman cho Normal, heading, bảng và run tiếng Việt.
    - Không in tên kỹ thuật main/by_district.
    - Không lặp cơ quan ban hành nếu trùng cơ quan cấp trên.
    - Không thêm page break cứng giữa bảng và biểu đồ; để Word tự dàn trang tự nhiên.
    - Không thêm trang trắng cuối.
    """
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
        from docx.shared import Cm, Inches, Pt
        from docx.oxml.ns import qn
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Chưa cài python-docx. Cài bằng: pip install python-docx") from exc

    meta = merge_agency_meta(agency_meta)
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    # Chừa thêm ngang cho bảng, vẫn giữ lề hành chính đủ đọc.
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(1.5)

    styles = doc.styles
    for style_name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        try:
            st = styles[style_name]
            st.font.name = "Times New Roman"
            st.font.size = Pt(14)
            st.font.color.rgb = None
            st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        except Exception:
            pass

    template = bundle.template or {}
    pattern = str(template.get("pattern") or "")
    title = str(template.get("title") or "Báo cáo")
    _set_docx_core_properties(doc, meta, title)
    scope_label = _scope_label(bundle)
    document_date = meta.get("document_date") or "ngày ... tháng ... năm ..."

    header_table = doc.add_table(rows=1, cols=2)
    header_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(header_table)
    left = header_table.cell(0, 0)
    right = header_table.cell(0, 1)
    left.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    right.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP

    parent = meta.get("parent_agency", "").upper()
    issuing = meta.get("issuing_agency", "").upper()
    left_lines = []
    if parent and parent != issuing:
        left_lines.append((parent, False))
    if issuing:
        left_lines.append((issuing, True))
    if not left_lines:
        left_lines.append(("CƠ QUAN LẬP BÁO CÁO", True))

    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for idx, (text, bold) in enumerate(left_lines):
        if idx > 0:
            p = left.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        _set_run_font(r, size=12, bold=bold)
    p = left.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("-" * 22)
    _set_run_font(r, size=12)
    p = left.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Số: " + meta.get("document_no", "        /BC-UBND"))
    _set_run_font(r, size=12)

    p = right.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
    _set_run_font(r, size=14, bold=True)
    p = right.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Độc lập - Tự do - Hạnh phúc")
    _set_run_font(r, size=14, bold=True)
    p = right.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("-" * 28)
    _set_run_font(r, size=12)
    p = right.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"{meta.get('place', 'Đắk Nông')}, {document_date}")
    _set_run_font(r, size=12, italic=True)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("BÁO CÁO")
    _set_run_font(r, size=15, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(title.upper())
    _set_run_font(r, size=14, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"Phạm vi số liệu: {scope_label}")
    _set_run_font(r, size=14, italic=True)

    _add_heading_p(doc, "I. Thông tin chung về phạm vi báo cáo", level=1)
    _add_body_p(doc, "Báo cáo được lập nhằm tổng hợp kết quả rà soát, phục vụ công tác theo dõi, quản lý và đánh giá tình hình trong phạm vi được lựa chọn. Các bảng số liệu, biểu đồ minh họa và phần nhận định được trình bày theo cùng phạm vi tổng hợp để bảo đảm tính thống nhất giữa số liệu và diễn giải.")
    _add_body_p(doc, f"Phạm vi tổng hợp của báo cáo là {scope_label}. Các nhận định trong báo cáo chỉ căn cứ trên số liệu đã được tổng hợp, không thay thế cho kết quả thẩm định thực tế tại địa phương và không suy diễn sang các nội dung chưa có dữ liệu kiểm chứng.")

    _add_heading_p(doc, "II. Số liệu tổng hợp", level=1)
    report_tables = _docx_report_tables(bundle)
    if not report_tables:
        _add_body_p(doc, "Chưa có bảng số liệu tổng hợp trong gói dữ liệu báo cáo.", italic=True)
    for title_text, df in report_tables:
        _add_docx_table(doc, title_text, df, pattern=pattern)

    normalized_chart_items = _normalized_chart_items(chart_items, chart_png_bytes=chart_png_bytes, chart_df=chart_df, chart_title=chart_title)
    _add_chart_section(doc, normalized_chart_items, pattern=pattern)

    _add_heading_p(doc, "III. Phân tích, nhận định", level=1)
    report_lines = _iter_report_lines(report_text)
    # Word demo chỉ in phần nhận định đã sinh ra. Không tự chèn thêm đoạn
    # phân tích bảng trước report_text vì sẽ làm mục III bị lặp và nhìn "kì".
    if not report_lines:
        for para in _table_analysis_paragraphs(report_tables, pattern=pattern):
            _add_body_p(doc, para)
    for line, is_heading in report_lines:
        if is_heading:
            # Không tạo cấu trúc con quá sâu; vẫn giữ nếu LLM/fallback trả về nhãn mục hợp lệ.
            _add_heading_p(doc, line, level=2)
        else:
            _add_body_p(doc, line)
    chart_paragraphs = _chart_analysis_paragraphs(normalized_chart_items, pattern=pattern, report_text=report_text)
    for para in chart_paragraphs:
        _add_body_p(doc, para)

    _add_heading_p(doc, "IV. Kiến nghị, đề xuất", level=1)
    for para in _recommendation_paragraphs(scope_label, title):
        _add_body_p(doc, para)

    # Khối ký demo: bỏ "Nơi nhận" và không dùng chức danh/chữ ký hành chính thật.
    # Mục tiêu là file trình diễn, không phải văn bản ban hành chính thức.
    sign_table = doc.add_table(rows=1, cols=2)
    sign_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(sign_table)
    right = sign_table.cell(0, 1)

    p = right.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    demo_title = str(meta.get("demo_signer_title") or "NGƯỜI LẬP BÁO CÁO")
    r = p.add_run(demo_title)
    _set_run_font(r, size=13, bold=True)
    p = right.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("(Ký, ghi rõ họ tên)")
    _set_run_font(r, size=11, italic=True)
    # Chỉ để một khoảng trống vừa phải cho chữ ký demo.
    p.paragraph_format.space_after = Pt(18)
    signer_name = meta.get("signer_name", "")
    if signer_name:
        p = right.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(signer_name)
        _set_run_font(r, size=12, bold=True)

    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()


# ───────────────────────────── XLSX one-sheet export ─────────────────────────────

def export_administrative_xlsx(
    bundle: ReportFactsBundle,
    report_text: str,
    *,
    chart_df: pd.DataFrame | None = None,
    chart_kind: str = "bar",
    agency_meta: dict[str, Any] | None = None,
) -> bytes:
    """Xuất Excel kiểu biểu mẫu: một sheet báo cáo duy nhất, không tách Thông tin/Nhận định/Fact pack.

    Sheet `Bao cao` gồm header hành chính, tiêu đề, phạm vi, nhận định, bảng số liệu và biểu đồ Excel.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.utils import get_column_letter
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Chưa cài openpyxl. Cài bằng: pip install openpyxl") from exc

    meta = merge_agency_meta(agency_meta)
    wb = Workbook()
    ws = wb.active
    ws.title = "Bao cao"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = 0.35
    ws.page_margins.right = 0.35
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    section_fill = PatternFill("solid", fgColor="EDEDED")
    title_font = Font(name="Times New Roman", size=14, bold=True)
    body_font = Font(name="Times New Roman", size=12)
    bold_font = Font(name="Times New Roman", size=12, bold=True)

    for col in range(1, 11):
        ws.column_dimensions[get_column_letter(col)].width = 18
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 20
    ws.column_dimensions["F"].width = 18
    ws.column_dimensions["G"].width = 18
    ws.column_dimensions["H"].width = 18

    def merge(row: int, c1: int, c2: int, value: str, font: Any = body_font, align: str = "center", fill: Any | None = None) -> None:
        ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
        cell = ws.cell(row, c1, _excel_value(value))
        cell.font = font
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        if fill:
            for c in range(c1, c2 + 1):
                ws.cell(row, c).fill = fill

    template = bundle.template or {}
    pattern = str(template.get("pattern") or "")
    title = str(template.get("title") or "Báo cáo")
    _set_xlsx_core_properties(wb, title)
    scope_label = _scope_label(bundle)
    document_date = meta.get("document_date") or "ngày ... tháng ... năm ..."

    r = 1
    parent = meta.get("parent_agency", "").upper()
    issuing = meta.get("issuing_agency", "").upper()
    left_text = issuing if parent == issuing else f"{parent}\n{issuing}"
    merge(r, 1, 4, left_text, bold_font)
    merge(r, 5, 9, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc", bold_font)
    ws.row_dimensions[r].height = 44
    r += 1
    merge(r, 1, 4, "Số: " + meta.get("document_no", "        /BC-UBND"), body_font)
    merge(r, 5, 9, f"{meta.get('place', 'Đắk Nông')}, {document_date}", body_font)
    r += 2
    merge(r, 1, 9, "BÁO CÁO", Font(name="Times New Roman", size=16, bold=True))
    r += 1
    merge(r, 1, 9, title.upper(), title_font)
    ws.row_dimensions[r].height = 36
    r += 1
    merge(r, 1, 9, f"Phạm vi số liệu: {scope_label}", Font(name="Times New Roman", size=12, italic=True))
    r += 2

    merge(r, 1, 9, "I. CĂN CỨ VÀ PHẠM VI BÁO CÁO", bold_font, align="left", fill=section_fill)
    r += 1
    merge(r, 1, 9, "Báo cáo được tổng hợp từ cùng một gói dữ liệu kiểm soát; số liệu, bảng biểu, biểu đồ và nhận định được đối chiếu thống nhất trong phạm vi đã chọn.", body_font, align="left")
    ws.row_dimensions[r].height = 34
    r += 2

    merge(r, 1, 9, "II. NỘI DUNG NHẬN ĐỊNH", bold_font, align="left", fill=section_fill)
    r += 1
    for line, is_heading in _iter_report_lines(report_text):
        merge(r, 1, 9, line, bold_font if is_heading else body_font, align="left")
        ws.row_dimensions[r].height = 24 if is_heading else 46
        r += 1
    r += 1

    merge(r, 1, 9, "III. BẢNG SỐ LIỆU TỔNG HỢP", bold_font, align="left", fill=section_fill)
    r += 1
    tables = bundle.tables or {}
    for name, df in tables.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        merge(r, 1, 9, _table_title(str(name)), bold_font, align="left")
        r += 1
        show = _rename_df(df, pattern=pattern)
        start_row = r
        for j, col in enumerate(show.columns, 1):
            cell = ws.cell(r, j, str(col))
            cell.font = bold_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.fill = header_fill
            cell.border = border
        r += 1
        for _, row in show.iterrows():
            for j, col in enumerate(show.columns, 1):
                value = _excel_value(row[col])
                cell = ws.cell(r, j, value)
                cell.font = body_font
                cell.alignment = Alignment(horizontal="right" if _is_number_for_excel(value) else "left", vertical="center", wrap_text=True)
                cell.border = border
            r += 1
        end_row = r - 1
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(show.columns))}{end_row}"
        r += 2

    # Dữ liệu và chart ngay trong cùng sheet, đặt bên phải/dưới phần bảng.
    if isinstance(chart_df, pd.DataFrame) and not chart_df.empty and chart_df.shape[1] >= 2:
        merge(r, 1, 9, "IV. BIỂU ĐỒ MINH HỌA VÀ DIỄN GIẢI", bold_font, align="left", fill=section_fill)
        r += 1
        chart_start = r
        cdf = _rename_df(chart_df, pattern=pattern).copy()
        for j, col in enumerate(cdf.columns, 1):
            cell = ws.cell(r, j, str(col))
            cell.font = bold_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
        r += 1
        for _, row in cdf.iterrows():
            for j, col in enumerate(cdf.columns, 1):
                value = _excel_value(row[col])
                cell = ws.cell(r, j, value)
                cell.font = body_font
                cell.border = border
                cell.alignment = Alignment(horizontal="right" if _is_number_for_excel(value) else "left", wrap_text=True)
            r += 1
        data_end = r - 1
        numeric_cols = [idx for idx, col in enumerate(cdf.columns, 1) if pd.api.types.is_numeric_dtype(cdf[col])]
        if numeric_cols:
            value_col = numeric_cols[0]
            labels = Reference(ws, min_col=1, min_row=chart_start + 1, max_row=data_end)
            data = Reference(ws, min_col=value_col, min_row=chart_start, max_row=data_end)
            if str(chart_kind).lower() == "line":
                chart = LineChart()
            elif str(chart_kind).lower() == "pie":
                chart = PieChart()
            else:
                chart = BarChart()
                chart.type = "bar"
                chart.style = 10
            chart.title = f"Biểu đồ minh họa - {title}"
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(labels)
            chart.height = 9
            chart.width = 18
            ws.add_chart(chart, f"K{chart_start}")
        r += 1
        merge(r, 1, 9, _chart_analysis(cdf), body_font, align="left")
        ws.row_dimensions[r].height = 42
        r += 2

    merge(r, 1, 9, "V. NHẬN XÉT VÀ KIẾN NGHỊ", bold_font, align="left", fill=section_fill)
    r += 1
    merge(r, 1, 9, "Đề nghị cơ quan, đơn vị liên quan tiếp tục rà soát, cập nhật và đối chiếu số liệu theo cùng phạm vi; các kiến nghị chính sách cụ thể cần căn cứ thêm kết quả xác minh thực tế và nhu cầu của từng địa bàn, nhóm hộ hoặc chỉ tiêu nổi bật.", body_font, align="left")
    ws.row_dimensions[r].height = 42
    r += 2
    # Khối ký demo trong Excel một-sheet: không in "Nơi nhận"/chức danh hành chính thật.
    merge(r, 6, 9, f"{meta.get('demo_signer_title', 'NGƯỜI LẬP BÁO CÁO')}\n\n(Ký, ghi rõ họ tên)\n\n{meta.get('signer_name', '')}", bold_font)
    ws.row_dimensions[r].height = 90

    # Style toàn sheet.
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.font.name != "Times New Roman":
                cell.font = body_font
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="center")

    ws.freeze_panes = "A8"
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
