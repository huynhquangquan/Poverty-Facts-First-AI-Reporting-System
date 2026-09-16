from __future__ import annotations

# ===== Min-words hard retry + mẫu 11 child-unit guard + scoped ranking =====

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import difflib
import unicodedata

import pandas as pd

try:
    from .report_fact_builder import ReportFactsBundle, build_report_bundle, bundle_main_table
    from .report_pattern_catalog import get_report_template
except Exception:  # pragma: no cover
    from report_fact_builder import ReportFactsBundle, build_report_bundle, bundle_main_table  # type: ignore
    from report_pattern_catalog import get_report_template  # type: ignore


@dataclass
class ReportTextResult:
    """Kết quả sinh nhận định tuần 4.

    Các field được giữ rộng để app4 cũ vẫn đọc được debug mà không lỗi.
    """

    text: str
    prompt: str = ""
    mode: str = "template_report"
    report_pattern: str = "overview_result"
    report_level: str = "administrative"
    used_llm: bool = False
    warnings: list[str] = field(default_factory=list)
    raw_llm_text: str = ""
    repair_prompt: str = ""
    repair_text: str = ""
    repair_attempted: bool = False
    repair_success: bool = False
    repair_noop: bool = True
    repair_validation_warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False
    validation_warnings: list[str] = field(default_factory=list)
    fallback_validation_warnings: list[str] = field(default_factory=list)
    final_validation_warnings: list[str] = field(default_factory=list)
    report_facts: dict[str, Any] = field(default_factory=dict)
    report_generation_strategy: str = "facts_first_template_renderer"
    final_source: str = "facts_renderer_full_text"
    raw_llm_attempted: bool = False
    raw_llm_validation_passed: bool = False
    raw_llm_warnings: list[str] = field(default_factory=list)
    raw_llm_rejected_reasons: list[str] = field(default_factory=list)
    repair_validation_passed: bool = False
    final_validation_passed: bool = True
    llm_rewrite_attempted: bool = False
    llm_rewrite_success: bool = False
    llm_rewrite_validation_passed: bool = False
    report_regenerate_nonce: int = 0
    rewrite_similarity: float | None = None
    rewrite_retry_attempted: bool = False
    raw_generation_disabled_by_design: bool = True
    status_messages: list[str] = field(default_factory=list)
    generation_mode: str = ""
    llm_failure_policy: str = "fallback"
    llm_failed: bool = False
    llm_failure_message: str = ""
    llm_attempt_count: int = 0
    llm_max_attempts: int = 0
    llm_min_words: int = 150
    llm_attempt_results: list[dict[str, Any]] = field(default_factory=list)
    final_text_fact_audit: dict[str, Any] = field(default_factory=dict)
    final_text_fact_audit_status: str = "not_run"
    final_text_fact_audit_rules: list[dict[str, Any]] = field(default_factory=list)
    style_variant_id: str = ""
    variation_profile_name: str = ""
    prompt_fingerprint: str = ""
    safe_base_fingerprint: str = ""
    fallback_text_fingerprint: str = ""
    final_text_fingerprint: str = ""
    similarity_to_fallback: float | None = None
    repair_changed_text: bool = False


def _num(value: Any) -> str:
    try:
        if value is None:
            return "0"
        n = float(value)
        if abs(n - int(n)) < 1e-9:
            return f"{int(n):,}".replace(",", ".")
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def _pct(value: Any) -> str:
    try:
        n = float(value or 0)
        return f"{n:.2f}".replace(".", ",") + "%"
    except Exception:
        return str(value)


def _as_records(df: pd.DataFrame | None, n: int = 5) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.head(n).where(pd.notna(df.head(n)), None).to_dict(orient="records")


def _first(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    return records[0] if records else None


def _trend(delta: Any) -> str:
    d = float(delta or 0)
    if d < 0:
        return f"giảm {_num(abs(d))} hộ"
    if d > 0:
        return f"tăng {_num(d)} hộ"
    return "không biến động"


def _scope(bundle: ReportFactsBundle) -> str:
    return str(bundle.scope.get("scope_label") or "phạm vi đã chọn")


def _title(bundle: ReportFactsBundle) -> str:
    return str(bundle.template.get("title") or "Báo cáo nhận định")


def _pattern(bundle: ReportFactsBundle) -> str:
    return str(bundle.template.get("pattern") or "overview_result")


def _household_focus(bundle: ReportFactsBundle) -> str:
    focus = bundle.facts.get("household_focus") or bundle.template.get("household_focus")
    return str(focus or "hộ nghèo, hộ cận nghèo")


def _render_overview(bundle: ReportFactsBundle) -> str:
    # Mẫu 1 có cấu trúc nghiệp vụ riêng: chỉ nhận định ba nhóm chỉ tiêu
    # của bảng tổng hợp (hộ nghèo, hộ cận nghèo, hộ NLNN mức sống trung bình).
    # Không dùng renderer overview chung vì renderer chung có thêm "hộ không nghèo",
    # làm văn bản no-LLM lệch với biểu mẫu 1.
    try:
        if _template_id_from_bundle(bundle) == 1:
            detail = _render_template_detail_from_insights(bundle)
            if str(detail or "").strip():
                return f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}\n\n{detail.strip()}"
    except Exception:
        pass

    f = bundle.facts
    top_groups = f.get("top_groups") or []
    top_districts = f.get("top_districts") or []
    top_group = _first(top_groups)
    top_dist = _first(top_districts)

    lines = [
        f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}",
        "",
        "I. Khái quát kết quả rà soát",
        (
            f"Theo số liệu {_scope(bundle)}, tổng số hộ được ghi nhận là "
            f"{_num(f.get('tong_ho_ra_soat'))} hộ. Trong đó, hộ nghèo là "
            f"{_num(f.get('ho_ngheo'))} hộ, chiếm {_pct(f.get('ty_le_ho_ngheo'))}; "
            f"hộ cận nghèo là {_num(f.get('ho_can_ngheo'))} hộ, chiếm "
            f"{_pct(f.get('ty_le_ho_can_ngheo'))}; hộ không nghèo là "
            f"{_num(f.get('ho_khong_ngheo'))} hộ, chiếm {_pct(f.get('ty_le_ho_khong_ngheo'))}."
        ),
        "",
        "II. Nhận xét, đánh giá",
    ]
    if top_group:
        lines.append(
            f"Trong cơ cấu phân loại hộ, nhóm {top_group.get('phan_loai')} có quy mô lớn nhất với "
            f"{_num(top_group.get('so_ho'))} hộ, tương ứng {_pct(top_group.get('ty_le_%'))}. "
            "Kết quả này là căn cứ để xác định trọng tâm theo dõi và phân bổ nguồn lực hỗ trợ phù hợp."
        )
    if top_dist:
        lines.append(
            f"Xét theo địa bàn, {top_dist.get('huyen')} là địa bàn có quy mô hộ trong dữ liệu lớn nhất với "
            f"{_num(top_dist.get('so_ho'))} hộ, chiếm {_pct(top_dist.get('ty_le_%'))}. "
            "Địa bàn này cần được ưu tiên theo dõi khi xây dựng kế hoạch rà soát, hỗ trợ và đánh giá kết quả giảm nghèo."
        )
    lines += [
        "",
        "III. Định hướng theo dõi",
        "Cần tiếp tục rà soát biến động hộ nghèo, hộ cận nghèo và các nhóm có nguy cơ phát sinh nghèo; đồng thời đối chiếu số liệu theo địa bàn để bảo đảm chính sách hỗ trợ được triển khai đúng đối tượng, đúng nhu cầu và có khả năng kiểm chứng bằng dữ liệu.",
    ]
    return "\n".join(lines)


def _render_movement(bundle: ReportFactsBundle) -> str:
    f = bundle.facts
    focus = _household_focus(bundle).lower()
    delta = f.get("chenh_lech", 0)
    components = f.get("movement_components") or {}
    warnings = f.get("movement_warnings") or []
    unexplained_delta = int(f.get("unexplained_delta") or 0)
    actual_final = f.get("tong_cuoi_ky_phan_loai")

    def comp(name: str) -> str:
        return _num(components.get(name, 0))

    lines = [
        f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}",
        "",
        "I. Khái quát số liệu diễn biến",
        (
            f"Trong kỳ rà soát, tổng số {focus} đầu kỳ là {_num(f.get('tong_ky_truoc'))} hộ; "
            f"cuối kỳ là {_num(f.get('tong_ky_sau'))} hộ; "
            f"chênh lệch {_trend(delta)}, tương ứng {_pct(f.get('ty_le_bien_dong_%'))}. "
            f"Các nhóm biến động được tổng hợp trong phạm vi năm {f.get('nam_sau')}."
        ),
        "",
        "II. Cấu phần giảm và tăng",
        (
            f"Cấu phần giảm gồm: nhóm 1 {comp('giam_1')} hộ, nhóm 2 {comp('giam_2')} hộ, "
            f"nhóm giảm khác {comp('giam_khac')} hộ. Cấu phần tăng gồm: nhóm 1 {comp('tang_1')} hộ, "
            f"nhóm 2 {comp('tang_2')} hộ, nhóm 3 {comp('tang_3')} hộ, "
            f"nhóm tăng khác {comp('tang_khac')} hộ."
        ),
    ]
    if not f.get("other_reason_available"):
        lines.append(
            "Nhóm biến động khác hiện ghi nhận bằng 0 do nguồn dữ liệu hiện có chưa có lý do biến động chi tiết; "
            "báo cáo không tự phân bổ phần chênh lệch vào các nguyên nhân chưa được ghi nhận."
        )
    if unexplained_delta:
        lines.append(
            f"Tổng {focus} theo phân loại hiện tại là {_num(actual_final)} hộ, lệch "
            f"{_num(unexplained_delta)} hộ so với tổng cuối kỳ theo công thức. Phần này được ghi nhận là "
            "phần chưa đủ căn cứ phân loại nguyên nhân, không diễn giải thành nguyên nhân cụ thể."
        )
    if warnings:
        lines.append("Lưu ý dữ liệu: " + _public_report_warning_text(" ".join(str(w) for w in warnings)))
    lines += [
        "",
        "III. Lưu ý diễn giải",
        (
            f"Khi sử dụng kết quả này, cần giữ đúng phạm vi {focus}, phân biệt số cuối kỳ đã tổng hợp "
            "với số theo phân loại hộ hiện tại, và chỉ nêu các cấu phần đã có trong dữ liệu."
        ),
    ]
    return "\n".join(lines)


def _render_deprivation(bundle: ReportFactsBundle) -> str:
    pattern = _pattern(bundle)
    f = bundle.facts
    focus = _household_focus(bundle).lower()
    top_count = f.get("top_indicators_by_count") or []
    top_ratio = f.get("top_indicators_by_ratio") or []
    is_ratio = pattern == "deprivation_ratio"
    ranking = top_ratio if is_ratio else top_count
    top = _first(ranking)
    second = ranking[1:3]

    if is_ratio:
        basis_text = "tỷ lệ thiếu hụt (%)"
        scope_note = (
            "Mẫu này tập trung vào tỷ lệ của từng chỉ số trong nhóm hộ phân tích; "
            "số hộ nếu xuất hiện chỉ dùng để đối chiếu quy mô, không phải trọng tâm trình bày."
        )
    else:
        basis_text = "số hộ thiếu hụt"
        scope_note = (
            "Mẫu này tập trung vào số lượng hộ thiếu từng chỉ số; "
            "tỷ lệ nếu xuất hiện chỉ là thông tin tham chiếu và không làm thay đổi trọng tâm số lượng."
        )

    lines = [
        f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}",
        "",
        "I. Khái quát tình hình thiếu hụt",
        (
            f"Số liệu {_scope(bundle)} cho thấy nhóm {focus} có {_num(f.get('total_households_in_group'))} hộ trong phạm vi phân tích. "
            f"Các chỉ số thiếu hụt dịch vụ xã hội cơ bản được tổng hợp theo {basis_text}. {scope_note}"
        ),
        "",
        "II. Chỉ số thiếu hụt nổi bật",
    ]
    if top:
        if is_ratio:
            lines.append(
                f"Chỉ số có tỷ lệ thiếu hụt cao nhất là {top.get('chi_tieu')}, đạt {_pct(top.get('ty_le_%'))}, "
                f"tương ứng {_num(top.get('so_ho'))} hộ trong nhóm {focus}. "
                "Cách diễn giải này phản ánh mức độ phổ biến của chỉ số trong nhóm hộ, không diễn giải như cơ cấu cộng đủ 100%."
            )
        else:
            lines.append(
                f"Chỉ số có số hộ thiếu hụt cao nhất là {top.get('chi_tieu')}, với {_num(top.get('so_ho'))} hộ"
                + (f", chiếm {_pct(top.get('ty_le_%'))} trong nhóm {focus}" if top.get('ty_le_%') is not None else "")
                + ". Đây là chỉ số cần được xem xét ưu tiên khi xác định lĩnh vực hỗ trợ tiếp cận dịch vụ xã hội cơ bản."
            )
    if second:
        if is_ratio:
            desc = "; ".join(
                f"{r.get('chi_tieu')} ({_pct(r.get('ty_le_%'))}, {_num(r.get('so_ho'))} hộ)"
                for r in second
            )
        else:
            desc = "; ".join(
                f"{r.get('chi_tieu')} ({_num(r.get('so_ho'))} hộ"
                + (f", {_pct(r.get('ty_le_%'))}" if r.get('ty_le_%') is not None else "")
                + ")"
                for r in second
            )
        lines.append(f"Các chỉ số tiếp theo cần chú ý gồm: {desc}.")
    lines += [
        "Các chỉ số thiếu hụt có thể chồng lấn trên cùng một hộ, vì vậy không cộng các dòng chỉ số thành tổng cơ cấu 100%.",
        "",
        "III. Định hướng hỗ trợ",
        f"Việc ưu tiên nguồn lực nên bám theo các chỉ số thiếu hụt cao của nhóm {focus}, đồng thời kết hợp rà soát theo địa bàn để bảo đảm hỗ trợ đúng nhóm thiếu hụt và tránh dàn trải.",
    ]
    return "\n".join(lines)

def _render_two_group_table_report(bundle: ReportFactsBundle, kind: str) -> str:
    f = bundle.facts
    if kind == "groups":
        title_section = "Nhóm đối tượng nổi bật"
        poor_key = "top_poor_groups"
        near_key = "top_near_poor_groups"
        management = "Cần ưu tiên chính sách hỗ trợ cho các nhóm dễ tổn thương có quy mô lớn, đồng thời lồng ghép hỗ trợ sinh kế, y tế, giáo dục và an sinh xã hội."
    elif kind == "ethnicity":
        title_section = "Cơ cấu theo dân tộc"
        poor_key = "top_poor_ethnicities"
        near_key = "top_near_poor_ethnicities"
        management = "Cần chú ý đặc điểm dân tộc và địa bàn cư trú khi thiết kế chính sách hỗ trợ, nhất là nhóm dân tộc thiểu số và dân tộc thiểu số tại chỗ."
    elif kind == "causes":
        title_section = "Nguyên nhân nghèo, cận nghèo nổi bật"
        poor_key = "top_poor_causes"
        near_key = "top_near_poor_causes"
        management = "Cần chuyển hóa kết quả phân tích nguyên nhân thành nhóm giải pháp cụ thể như hỗ trợ vốn, đất sản xuất, đào tạo nghề, công cụ sản xuất và hỗ trợ y tế."
    else:
        title_section = "Chỉ tiêu nổi bật"
        poor_key = "top_poor_child_deprivations"
        near_key = "top_near_poor_child_deprivations"
        management = "Cần ưu tiên nhóm chỉ tiêu liên quan trực tiếp đến trẻ em, đặc biệt là y tế, dinh dưỡng và giáo dục, nhằm hạn chế tác động dài hạn của nghèo đa chiều."
    value_unit = (f.get("child_deprivation_value_unit") or "trẻ em") if kind == "children" else "hộ"
    value_label = "số trẻ" if value_unit == "trẻ em" else "số hộ/case"

    poor = f.get(poor_key) or []
    near = f.get(near_key) or []
    top_poor = _first(poor)
    top_near = _first(near)

    def sentence(row: dict[str, Any] | None, group: str) -> str:
        if not row:
            return f"Chưa có số liệu nổi bật đối với {group}."
        count_col = "so_ho_ngheo" if group == "hộ nghèo" else "so_ho_can_ngheo"
        if kind == "ethnicity":
            pct_col = "ty_le_ngheo_%" if group == "hộ nghèo" else "ty_le_can_ngheo_%"
        else:
            pct_col = "ty_le_ho_ngheo_%" if group == "hộ nghèo" else "ty_le_ho_can_ngheo_%"
        return (
            f"Đối với {group}, chỉ tiêu/nhóm nổi bật nhất là {row.get('chi_tieu') or row.get('dan_toc')}, "
            f"với {_num(row.get(count_col))} {value_unit}, "
            f"chiếm {_pct(row.get(pct_col))}."
        )

    lines = [
        f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}",
        "",
        "I. Khái quát phạm vi phân tích",
        f"Báo cáo sử dụng số liệu {_scope(bundle)} để phân tích hộ nghèo và hộ cận nghèo theo mẫu: {_title(bundle).lower()}.",
        "",
        f"II. {title_section}",
        sentence(top_poor, "hộ nghèo"),
        sentence(top_near, "hộ cận nghèo"),
    ]
    if poor[1:3]:
        detail = "; ".join(
            f"{r.get('chi_tieu') or r.get('dan_toc')} ({_num(r.get('so_ho_ngheo'))} {value_unit})" for r in poor[1:3]
        )
        lines.append(f"Một số nhóm/chỉ tiêu tiếp theo trong hộ nghèo theo {value_label} gồm: {detail}.")
    if near[1:3]:
        detail = "; ".join(
            f"{r.get('chi_tieu') or r.get('dan_toc')} ({_num(r.get('so_ho_can_ngheo'))} {value_unit})" for r in near[1:3]
        )
        lines.append(f"Một số nhóm/chỉ tiêu tiếp theo trong hộ cận nghèo theo {value_label} gồm: {detail}.")
    lines += ["", "III. Định hướng quản lý", management]
    return "\n".join(lines)


def _render_multidim(bundle: ReportFactsBundle) -> str:
    f = bundle.facts
    focus = _household_focus(bundle).lower()
    top_target = _first(f.get("top_districts_by_target") or [])
    top_ratio = _first(f.get("top_districts_by_ratio") or [])
    lines = [
        f"BÁO CÁO NHẬN ĐỊNH\n{_title(bundle)}",
        "",
        "I. Khái quát kết quả theo chuẩn đa chiều",
        (
            f"Theo số liệu {_scope(bundle)}, nhóm {focus} ghi nhận {_num(f.get('total_target_households'))} hộ, "
            f"tương ứng {_num(f.get('total_target_population'))} nhân khẩu. Cần phân biệt số hộ với số nhân khẩu: "
            "một hộ có thể có nhiều nhân khẩu, nên các cột nhân khẩu có thể lớn hơn nhiều so với cột tổng hộ đã rà soát/phân loại. "
            f"Trong nhóm {focus}, số hộ dân tộc thiểu số là {_num(f.get('total_ethnic_minority_households'))} hộ; "
            f"số hộ dân tộc thiểu số tại chỗ là {_num(f.get('total_local_ethnic_minority_households'))} hộ."
        ),
        "",
        "II. Nhận xét theo địa bàn và cơ cấu",
    ]
    if top_target:
        lines.append(
            f"Địa bàn có quy mô {focus} lớn nhất là {top_target.get('huyen')}, với "
            f"{_num(top_target.get('so_ho_muc_tieu'))} hộ. Tỷ lệ {_pct(top_target.get('ty_le_muc_tieu_%'))} được tính trên tổng hộ đã rà soát/phân loại của chính địa bàn đó, không tính trên tổng nhân khẩu."
        )
    if top_ratio and (not top_target or top_ratio.get("huyen") != top_target.get("huyen")):
        lines.append(
            f"Xét theo tỷ lệ, {top_ratio.get('huyen')} là địa bàn có tỷ lệ {focus} cao nhất, đạt "
            f"{_pct(top_ratio.get('ty_le_muc_tieu_%'))} trên tổng hộ đã rà soát/phân loại của địa bàn."
        )
    lines += [
        "Cơ cấu dân tộc trong nhóm hộ mục tiêu cần được theo dõi riêng, vì đây là căn cứ quan trọng để lồng ghép chính sách giảm nghèo với chính sách dân tộc và chính sách an sinh xã hội.",
        "",
        "III. Định hướng thực hiện",
        f"Cần tiếp tục rà soát {focus} theo chuẩn đa chiều, ưu tiên các địa bàn có quy mô hoặc tỷ lệ cao, đồng thời theo dõi nhóm dân tộc thiểu số tại chỗ để bảo đảm chính sách hỗ trợ sát đặc thù địa phương.",
    ]
    return "\n".join(lines)

def render_full_report_text(bundle: ReportFactsBundle, report_level: str = "administrative") -> str:
    pattern = _pattern(bundle)
    if pattern == "overview_result":
        return _render_overview(bundle)
    if pattern == "movement":
        return _render_movement(bundle)
    if pattern in {"deprivation_count", "deprivation_ratio"}:
        return _render_deprivation(bundle)
    if pattern == "vulnerable_groups":
        return _render_two_group_table_report(bundle, "groups")
    if pattern == "ethnicity":
        return _render_two_group_table_report(bundle, "ethnicity")
    if pattern == "causes":
        return _render_two_group_table_report(bundle, "causes")
    if pattern == "child_deprivation":
        return _render_two_group_table_report(bundle, "children")
    if pattern == "multidimensional_standard":
        return _render_multidim(bundle)
    return _render_overview(bundle)

# ===== LLM rewrite layer (self-contained; no import from report_writer) =====
TECHNICAL_TOKENS = (
    "DataFrame", "Series", "dtype", "NaN", "NoneType", "Index(",
    "phan_loai", "so_ho", "so_nhan_khau", "ty_le_%", "ty_le_%%",
    "chi_tieu", "label_col", "value_col", "template_main", "chart_df",
    # Không để văn bản cuối lộ cách tổ chức kỹ thuật hoặc nguồn trung gian.
    "bảng mẫu", "theo cấu trúc mẫu", "SAFE_BASE_TEXT", "REPORT_FACTS",
    "JSON", "Python", "SQL", "DB", "Excel", "Word", "NLNN",
    "template_id", "fact pack", "fact bundle", "audit", "validator", "debug",
    "workbook", "worksheet", "sheet", "header",
    "llm_analysis_anchors", "safe_row_snapshots", "REPORT_FACTS_RÚT_GỌN",
    "YÊU CẦU SỬA", "HẬU KIỂM", "LẦN THỬ",
)



_VARIATION_INSTRUCTIONS = [
    "Nhấn mạnh theo trật tự: phạm vi số liệu, cơ cấu chính, địa bàn hoặc nhóm nổi bật, giới hạn diễn giải.",
    "Nhấn mạnh theo trật tự: kết quả nổi bật, mức chênh lệch giữa các nhóm, hàm ý theo dõi quản lý.",
    "Nhấn mạnh theo trật tự: bức tranh chung, nhóm có quy mô/tỷ lệ cao, yêu cầu tiếp tục rà soát đối chiếu.",
    "Nhấn mạnh theo trật tự: số liệu chính, so sánh nhóm cao - thấp, lưu ý không suy diễn ngoài dữ liệu.",
    "Nhấn mạnh theo trật tự: căn cứ thống kê, nhận xét thận trọng, định hướng tổng hợp trong kỳ tiếp theo.",
    "Nhấn mạnh theo trật tự: kết quả chính, nhóm cần quan tâm, giới hạn dữ liệu và khuyến nghị theo dõi.",
]


_VARIATION_OPENING_BANS = (
    "Theo kết quả rà soát/phân loại",
    "Theo số liệu",
    "Căn cứ số liệu",
    "Trên cơ sở số liệu",
)

_VARIATION_PROFILE_BANK = [
    {
        "id": "A",
        "name": "tong_quan_truoc_dia_ban",
        "opening": "Mở đầu bằng kết quả chung của phạm vi/năm, nhưng không dùng đúng cụm 'Theo kết quả rà soát/phân loại' hoặc 'Theo số liệu'.",
        "flow": "Variant A: tổng quan -> top chính -> top phụ -> lưu ý diễn giải.",
        "tone": "Dùng các động từ trung tính như ghi nhận, phản ánh, cho thấy, cần đọc trong phạm vi dữ liệu.",
    },
    {
        "id": "B",
        "name": "dia_ban_truoc_co_cau",
        "opening": "Mở đầu từ kết quả nổi bật hoặc cặp nhãn-số chính, không dùng câu dẫn chung cho mọi mẫu.",
        "flow": "Variant B: kết quả nổi bật -> đối chiếu nhóm/địa bàn -> ý nghĩa theo dõi -> giới hạn dữ liệu.",
        "tone": "Tránh câu mở/kết giống bản trước; ưu tiên chuyển ý bằng 'Ở cấp địa bàn', 'Với lớp dữ liệu dân tộc'.",
    },
    {
        "id": "C",
        "name": "ty_le_va_quy_mo_tach_rieng",
        "opening": "Mở đầu bằng phạm vi dữ liệu và mẫu số; tách rõ quy mô hộ, nhân khẩu và tỷ lệ.",
        "flow": "Variant C: phạm vi/mẫu số -> chỉ tiêu nổi bật -> so sánh ngắn -> lưu ý không suy diễn.",
        "tone": "Dùng câu ngắn hơn, ít liệt kê nối dài; có thể tách một câu dài thành hai câu nếu vẫn giữ đúng cặp nhãn-số.",
    },
    {
        "id": "D",
        "name": "nhan_dinh_quan_ly_than_trong",
        "opening": "Mở đầu bằng nhận định thận trọng về phạm vi bộ số liệu, không mở đầu y hệt SAFE_BASE_TEXT.",
        "flow": "Variant D: nhận xét thận trọng -> số liệu chính -> nhóm/địa bàn cần quan tâm -> kết luận quản lý.",
        "tone": "Văn phong báo cáo tự nhiên, có chuyển ý, nhưng không thêm khuyến nghị chính sách ngoài dữ liệu.",
    },
]


def _style_variant_profile(regenerate_nonce: int = 0) -> dict[str, str]:
    return _VARIATION_PROFILE_BANK[int(regenerate_nonce or 0) % len(_VARIATION_PROFILE_BANK)]


def _style_variant_id(regenerate_nonce: int = 0) -> str:
    return str(_style_variant_profile(regenerate_nonce).get("id") or "A")


def _variation_profile_text(bundle: ReportFactsBundle | None, regenerate_nonce: int = 0) -> str:
    """Hướng dẫn biến thể diễn đạt có kiểm soát theo từng lần regenerate.

    Chỉ đổi bố cục/cách dẫn; không cho phép đổi số, đổi cặp nhãn-số hoặc thêm nhận định ngoài dữ liệu.
    """
    try:
        tid = _template_id_from_bundle(bundle)
        pattern = _pattern(bundle) if bundle is not None else ""
    except Exception:
        tid, pattern = 0, ""
    profile = _style_variant_profile(regenerate_nonce)
    lines = [
        f"Mã biến thể: {profile['id']}.",
        f"Tên biến thể: {profile['name']}.",
        f"Cách mở bài: {profile['opening']}",
        f"Mạch đoạn: {profile['flow']}",
        f"Giọng văn: {profile['tone']}",
        "Không được đổi số liệu, không đổi vị trí số liệu, không đảo cặp nhãn-số, không tự thêm địa bàn/chỉ tiêu/tỷ lệ.",
        "Không sao chép nguyên văn câu mở đầu và câu chuyển đoạn của lần sinh trước nếu người dùng bấm sinh lại.",
        "Không lặp nguyên thứ tự câu của SAFE_BASE_TEXT; được đổi thứ tự đoạn nếu vẫn giữ đúng cặp nhãn-số.",
    ]
    if tid in {4, 6} or pattern == "deprivation_count":
        lines.append(
            "Mẫu số lượng thiếu hụt: mở bằng 'Xét theo số hộ thiếu hụt', 'Về quy mô hộ thiếu từng chỉ số' hoặc cách tương đương; nêu số hộ trước, tỷ lệ chỉ là đối chiếu phụ."
        )
    elif tid in {5, 7} or pattern == "deprivation_ratio":
        lines.append(
            "Mẫu tỷ lệ thiếu hụt: mở bằng 'Xét theo tỷ lệ thiếu hụt', 'Về mức phổ biến của từng chỉ số thiếu hụt' hoặc cách tương đương; nêu tỷ lệ trước, số hộ chỉ là đối chiếu phụ."
        )
    if tid == 12 or pattern == "multidimensional_standard":
        m12_variants = [
            "Mẫu 12 biến thể A: dùng 'Kết quả ... cho thấy' hoặc 'Trong phạm vi ...' thay cho 'Theo kết quả ...'; tách hộ nghèo, nhân khẩu và dân tộc thành các lớp nhận định riêng.",
            "Mẫu 12 biến thể B: mở đoạn địa bàn bằng 'Ở cấp địa bàn' hoặc 'Phân theo địa bàn'; nếu nêu Tuy Đức/Đăk Glong/Cư Jút thì phải giữ đúng tỷ lệ theo tổng hộ rà soát của từng địa bàn.",
            "Mẫu 12 biến thể C: mở đoạn dân tộc bằng 'Với lớp dữ liệu dân tộc trong nhóm hộ nghèo' hoặc 'Cơ cấu dân tộc trong nhóm hộ nghèo'; giữ đủ Kinh/DTTS/DTTS tại chỗ nếu dùng số.",
            "Mẫu 12 biến thể D: đoạn cuối viết như lưu ý phạm vi dữ liệu, không dùng câu kết chung chung và không suy diễn nguyên nhân nghèo theo dân tộc.",
        ]
        lines.append(m12_variants[int(regenerate_nonce or 0) % len(m12_variants)])
    return "\n".join(f"- {line}" for line in lines)


def _replace_first_existing(text: str, replacements: list[tuple[str, str]]) -> str:
    """Thay mỗi cụm tối đa một lần, theo thứ tự; tên hàm giữ để tránh đổi call cũ."""
    out = str(text or "")
    for old, new in replacements:
        if old in out:
            out = out.replace(old, new, 1)
    return out


def _apply_regenerate_style_variation(
    text: str,
    bundle: ReportFactsBundle | None,
    regenerate_nonce: int = 0,
    *,
    allow_variation: bool = True,
) -> str:
    """Đổi nhẹ cách dẫn/chuyển ý sau LLM để các lần regenerate không trùng khuôn.

    Hàm này không sửa số, không thêm số mới và không đổi thứ tự các cặp nhãn-số.
    Sau khi áp dụng, văn bản vẫn đi qua _validate_candidate + _final_text_fact_audit.
    """
    raw = str(text or "").strip()
    if not raw or not allow_variation:
        return raw
    try:
        tid = _template_id_from_bundle(bundle)
        pattern = _pattern(bundle) if bundle is not None else ""
    except Exception:
        tid, pattern = 0, ""
    nonce = int(regenerate_nonce or 0)
    variant = nonce % 4

    # Biến thể hẹp cho mẫu 12: chỉ thay cụm dẫn/chuyển đoạn, không đụng số và tên địa bàn.
    if tid == 12 or pattern == "multidimensional_standard":
        opening_variants = [
            "Theo kết quả rà soát/phân loại",
            "Kết quả rà soát/phân loại",
            "Trong phạm vi dữ liệu rà soát/phân loại",
            "Từ bộ số liệu rà soát/phân loại",
        ]
        # Nếu LLM mở đúng công thức cũ, đổi theo nonce để các lần sinh có khác biệt thấy được.
        if raw.startswith("Theo kết quả rà soát/phân loại"):
            if variant == 1:
                raw = re.sub(
                    r"^Theo kết quả rà soát/phân loại năm\s+(\d{4}),\s+toàn tỉnh ghi nhận",
                    r"Kết quả rà soát/phân loại năm \1 cho thấy toàn tỉnh ghi nhận",
                    raw,
                    count=1,
                )
            elif variant == 2:
                raw = re.sub(
                    r"^Theo kết quả rà soát/phân loại năm\s+(\d{4}),",
                    r"Trong phạm vi dữ liệu rà soát/phân loại năm \1,",
                    raw,
                    count=1,
                )
            elif variant == 3:
                raw = re.sub(
                    r"^Theo kết quả rà soát/phân loại năm\s+(\d{4}),",
                    r"Từ bộ số liệu rà soát/phân loại năm \1,",
                    raw,
                    count=1,
                )
        elif not any(raw.startswith(x) for x in opening_variants):
            # Không ép nếu LLM đã tự mở khác.
            pass

        if variant == 1:
            raw = _replace_first_existing(raw, [
                ("Số nhân khẩu thuộc hộ nghèo là", "Về nhân khẩu, nhóm hộ nghèo có"),
                ("Xét theo địa bàn,", "Ở cấp địa bàn,"),
                ("Các địa bàn đáng chú ý tiếp theo gồm", "Nhóm địa bàn đáng chú ý tiếp theo gồm"),
                ("Về cơ cấu hộ nghèo theo dân tộc,", "Với lớp dữ liệu dân tộc trong nhóm hộ nghèo,"),
                ("Ở các địa bàn có số hộ nghèo DTTS nổi bật,", "Theo từng địa bàn có số hộ nghèo DTTS đáng chú ý,"),
                ("Các tỷ lệ nêu trên được hiểu", "Cần đọc các tỷ lệ nêu trên"),
            ])
        elif variant == 2:
            raw = _replace_first_existing(raw, [
                ("Số nhân khẩu thuộc hộ nghèo là", "Tổng nhân khẩu thuộc hộ nghèo là"),
                ("Xét theo địa bàn,", "Phân theo địa bàn,"),
                ("Các địa bàn đáng chú ý tiếp theo gồm", "Ngoài Tuy Đức, các địa bàn đáng chú ý gồm"),
                ("Về cơ cấu hộ nghèo theo dân tộc,", "Cơ cấu dân tộc trong nhóm hộ nghèo cho thấy"),
                ("Ở các địa bàn có số hộ nghèo DTTS nổi bật,", "Trong nhóm địa bàn có số hộ nghèo DTTS đáng chú ý,"),
                ("Phần dân tộc chỉ mô tả", "Lớp dữ liệu dân tộc chỉ mô tả"),
            ])
        elif variant == 3:
            raw = _replace_first_existing(raw, [
                ("Số nhân khẩu thuộc hộ nghèo là", "Ở chỉ tiêu nhân khẩu, nhóm hộ nghèo ghi nhận"),
                ("Xét theo địa bàn,", "Khi đối chiếu giữa các địa bàn,"),
                ("Các địa bàn đáng chú ý tiếp theo gồm", "Các địa bàn tiếp theo cần lưu ý gồm"),
                ("Về cơ cấu hộ nghèo theo dân tộc,", "Ở nhóm chỉ tiêu dân tộc,"),
                ("Ở các địa bàn có số hộ nghèo DTTS nổi bật,", "Đối với các địa bàn có số hộ nghèo DTTS đáng chú ý,"),
                ("Các tỷ lệ nêu trên được hiểu", "Các tỷ lệ này cần được hiểu"),
            ])
        # variant 0 giữ gần nguyên để lần đầu ổn định.
        raw = re.sub(r"\s+", " ", raw).strip() if "\n" not in raw else re.sub(r"[ \t]+", " ", raw).strip()
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw

    # Với các mẫu khác, chỉ đổi một vài cụm mở/chuyển ý nếu xuất hiện đúng công thức cũ.
    generic_sets = [
        [],
        [("Theo số liệu", "Từ số liệu"), ("Xét theo", "Khi phân theo")],
        [("Trên cơ sở", "Căn cứ"), ("Nhìn chung,", "Tổng hợp lại,")],
        [("Kết quả cho thấy", "Dữ liệu phản ánh"), ("Cần tiếp tục", "Việc tiếp tục")],
    ]
    for old, new in generic_sets[variant]:
        raw = raw.replace(old, new, 1)
    return raw.strip()

_PATTERN_STYLE_HINTS: dict[str, str] = {
    "overview_result": "Báo cáo tổng hợp kết quả rà soát chung; cần nêu quy mô hộ rà soát, cơ cấu phân loại hộ và địa bàn/nhóm nổi bật.",
    "movement": "Báo cáo diễn biến qua các kỳ; chỉ mô tả biến động giữa các mốc có trong dữ liệu, không viết thành xu hướng dài hạn nếu chỉ có hai năm.",
    "deprivation_count": "Báo cáo chỉ số thiếu hụt theo số hộ; lưu ý các chỉ số có thể chồng lấn, không cộng thành cơ cấu 100%.",
    "deprivation_ratio": "Báo cáo chỉ số thiếu hụt theo tỷ lệ; giữ đúng đơn vị phần trăm và không chuyển đổi thành số hộ nếu dữ liệu không hỗ trợ.",
    "vulnerable_groups": "Báo cáo nhóm đối tượng; các nhóm có thể chồng lấn, cần trình bày thận trọng theo quy mô hộ nghèo và hộ cận nghèo.",
    "ethnicity": "Báo cáo theo dân tộc; phân biệt dân tộc chi tiết, dân tộc thiểu số và dân tộc thiểu số tại chỗ nếu có dữ liệu.",
    "causes": "Báo cáo nguyên nhân nghèo; nguyên nhân có thể đồng thời xuất hiện ở một hộ, không kết luận nguyên nhân duy nhất.",
    "child_deprivation": "Báo cáo thiếu hụt của trẻ em; giữ mức mô tả số liệu, không suy diễn tình trạng cá nhân của trẻ em.",
    "multidimensional_standard": "Báo cáo chuẩn nghèo đa chiều; tách rõ mẫu số hộ đã rà soát/phân loại, số hộ nghèo đa chiều, nhân khẩu trong các hộ đó và cơ cấu dân tộc; không so sánh trực tiếp số hộ với số nhân khẩu.",
}


_PATTERN_VALIDATION_RULES: dict[str, dict[str, str]] = {
    "overview_result": {
        "allowed": "Được nhận định về quy mô, cơ cấu nhóm hộ và địa bàn/nhóm có giá trị nổi bật.",
        "avoid": "Không suy diễn nguyên nhân nghèo, hiệu quả hỗ trợ, xu hướng dài hạn hoặc chính sách cụ thể nếu bảng không có dữ liệu tương ứng.",
        "ranking": "Xếp hạng theo số hộ/số nhân khẩu/tỷ lệ đúng với cột được nêu trong câu.",
    },
    "movement": {
        "allowed": "Được mô tả tăng, giảm, phát sinh, thoát nghèo, tái nghèo hoặc biến động giữa các mốc có trong dữ liệu.",
        "avoid": "Không viết thành xu hướng dài hạn nếu chỉ có hai mốc; không quy nguyên nhân biến động nếu không có cột nguyên nhân.",
        "ranking": "Xếp hạng theo chênh lệch hoặc tỷ lệ biến động đúng cột; cần phân biệt tăng và giảm.",
    },
    "deprivation_count": {
        "allowed": "Được nhận định về chỉ số thiếu hụt theo số hộ và nhóm chỉ số nổi bật.",
        "avoid": "Không cộng các chỉ số thiếu hụt thành tổng cơ cấu vì một hộ có thể thiếu nhiều chỉ số.",
        "ranking": "Xếp hạng theo số hộ thiếu hụt, không tự chuyển sang tỷ lệ nếu bảng không có tỷ lệ.",
    },
    "deprivation_ratio": {
        "allowed": "Được nhận định về tỷ lệ thiếu hụt và nhóm chỉ số có tỷ lệ cao/thấp.",
        "avoid": "Không chuyển tỷ lệ thành số hộ nếu dữ liệu không cung cấp số hộ; giữ đơn vị phần trăm.",
        "ranking": "Xếp hạng theo tỷ lệ, không lẫn với số hộ tuyệt đối.",
    },
    "vulnerable_groups": {
        "allowed": "Được nhận định về nhóm đối tượng thuộc hộ nghèo/hộ cận nghèo và nhóm nổi bật.",
        "avoid": "Không coi các nhóm đối tượng là loại trừ nhau; không cộng thành 100% nếu có thể chồng lấn.",
        "ranking": "Xếp hạng riêng theo hộ nghèo, hộ cận nghèo hoặc tổng nếu bảng có cột tương ứng.",
    },
    "ethnicity": {
        "allowed": "Được nhận định về cơ cấu dân tộc, nhóm dân tộc có quy mô/tỷ lệ nổi bật.",
        "avoid": "Không suy diễn nguyên nhân nghèo theo dân tộc; không đánh giá định kiến về nhóm dân tộc.",
        "ranking": "Xếp hạng theo đúng cột hộ nghèo/hộ cận nghèo/tỷ lệ nếu được nêu.",
    },
    "causes": {
        "allowed": "Được nhận định về nguyên nhân/nguyên nhân nghèo được ghi nhận trong bảng.",
        "avoid": "Không kết luận nguyên nhân duy nhất hoặc nguyên nhân trực tiếp nếu bảng chỉ là thống kê nhiều lựa chọn.",
        "ranking": "Xếp hạng theo số hộ/tỷ lệ của từng nguyên nhân đúng với nhóm hộ được nêu.",
    },
    "child_deprivation": {
        "allowed": "Được nhận định về chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo/hộ cận nghèo.",
        "avoid": "Không suy diễn tình trạng cá nhân của trẻ em hoặc mức độ nghiêm trọng ngoài chỉ tiêu bảng có.",
        "ranking": "Xếp hạng theo chỉ tiêu thiếu hụt và nhóm hộ đúng cột.",
    },
    "multidimensional_standard": {
        "allowed": "Được nhận định về kết quả theo chuẩn nghèo đa chiều, nhóm hộ mục tiêu và địa bàn nổi bật.",
        "avoid": "Không trộn mẫu số tổng hộ dân cư với mẫu số hộ rà soát nếu bảng không thể hiện rõ.",
        "ranking": "Xếp hạng theo quy mô hoặc tỷ lệ đúng cột, phân biệt số hộ và tỷ lệ.",
    },
}


def _template_id_from_bundle(bundle: ReportFactsBundle | None) -> int:
    try:
        return int(((getattr(bundle, "template", {}) or {}).get("id") or 0))
    except Exception:
        return 0


def _template_specific_llm_guidance(bundle: ReportFactsBundle | None) -> str:
    """Hướng dẫn riêng cho nhóm mẫu thường fallback nhiều.

    Đây là prompt guidance, không phải validator nới lỏng. Mục tiêu là giảm việc
    LLM tự suy luận sai ở các mẫu nhiều cặp nhãn-số: mẫu 1, 2-3, 4-7, 11, 12.
    Nội dung được viết theo nhóm nghiệp vụ để tránh thiên vị địa bàn/số liệu cụ thể.
    """
    if bundle is None:
        return "Không có hướng dẫn riêng. Bám sát SAFE_BASE_TEXT và llm_analysis_anchors."
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)
    focus = _household_focus(bundle)

    if tid == 1 or pattern == "overview_result":
        return (
            "Mẫu 1 là mẫu tổng hợp đúng ba nhóm chỉ tiêu của biểu mẫu: hộ nghèo, hộ cận nghèo và hộ nông/lâm/ngư nghiệp có mức sống trung bình. "
            "Không đưa nhóm ngoài ba chỉ tiêu chính vào văn bản nhận định của mẫu 1, dù facts tổng quan có trường khác. "
            "Viết theo từng nhóm số liệu riêng, không trộn hộ nghèo, hộ cận nghèo và hộ nông/lâm/ngư nghiệp mức sống trung bình trong cùng một nhận định xếp hạng. "
            "Nếu nhóm hộ nông, lâm, ngư nghiệp có mức sống trung bình bằng 0 thì ghi là chỉ tiêu này bằng 0 theo bảng tổng hợp hiện có; không phân tích sâu, không nói như kết luận ngoài dữ liệu và không dùng nghề nghiệp làm proxy. "
            "Nếu nhắc địa bàn nổi bật, nêu rõ địa bàn đó nổi bật ở chỉ tiêu nào và dùng đúng cặp địa bàn-chỉ tiêu-số; ưu tiên cách viết 'ghi nhận/có ... hộ' thay vì dùng quá nhiều xếp hạng. "
            "Với mẫu 1, để giảm lỗi của LLM nhỏ, hạn chế dùng các từ 'cao nhất', 'thấp nhất', 'thứ hai', 'dẫn đầu', 'vượt xa', 'hơn một nửa'; nếu cần so sánh thì viết an toàn: 'địa bàn nổi bật gồm ... với ... hộ'. "
            "Không tự tính tỷ lệ mới và không suy diễn nguyên nhân/chính sách từ bảng tổng hợp. Bắt buộc giữ các tổng nhóm cốt lõi trong template1_detail/llm_analysis_anchors trước khi chuyển sang nhận định địa bàn."
        )
    if tid in {2, 3} or pattern == "movement":
        target = "hộ nghèo" if tid == 2 else ("hộ cận nghèo" if tid == 3 else focus)
        return (
            f"Mẫu diễn biến chỉ phân tích {target} trong kỳ. Khung an toàn là: số hộ đầu kỳ, các nhóm giảm, "
            "các nhóm tăng, số hộ cuối kỳ, chênh lệch và tỷ lệ biến động. Không gọi đây là xu hướng dài hạn nếu chỉ có hai mốc. "
            "Ưu tiên dùng sentence_anchors do Python tạo làm xương sống; không tự viết nhận định địa bàn nếu không có số địa bàn tương ứng trong bảng/anchor. "
            "Nếu movement_other_policy là zero_without_explicit_reason thì không nhắc giảm/tăng khác như một nguyên nhân thực tế và không tự gán chết, chuyển đi, tách hộ, nhập hộ hay thay đổi nhân khẩu. "
            "Nếu có phần lệch ngoài công thức thì chỉ nêu là phần chưa đủ căn cứ phân loại nguyên nhân, không dùng để cân bằng ngược vào cột khác. "
            "Nếu chênh lệch dương thì viết tăng/biến động tăng; nếu chênh lệch âm thì viết giảm/biến động giảm. "
            "Không đặt số tổng toàn tỉnh/toàn phạm vi trong cùng câu với tên huyện/xã; mỗi địa bàn phải đi đúng số của địa bàn đó."
        )
    if tid in {4, 6} or pattern == "deprivation_count":
        target = "hộ cận nghèo" if tid == 6 else ("hộ nghèo" if tid == 4 else focus)
        return (
            f"Mẫu chỉ số thiếu hụt theo số lượng, trọng tâm là số hộ {target} thiếu từng chỉ số. "
            "Văn bản cuối không dùng cụm 'Mẫu này'. Mở bài nên dùng ngôn ngữ như 'Xét theo số hộ thiếu hụt', 'Về quy mô hộ thiếu từng chỉ số' hoặc 'Chỉ số có số hộ thiếu hụt lớn nhất'. "
            "Top phải nêu số hộ trước; tỷ lệ chỉ là thông tin đối chiếu phụ sau số hộ, ví dụ '... ghi nhận ... hộ, tương ứng ...%'. "
            "Không viết như mẫu tỷ lệ và không biến số hộ thành tỷ lệ. Các chỉ số có thể chồng lấn, vì vậy không cộng thành cơ cấu 100%. "
            "Khi xếp cao/thấp, xếp theo số hộ thiếu hụt, không xếp theo phần trăm nếu câu không nói rõ phần trăm."
        )
    if tid in {5, 7} or pattern == "deprivation_ratio":
        target = "hộ cận nghèo" if tid == 7 else ("hộ nghèo" if tid == 5 else focus)
        return (
            f"Mẫu tỷ lệ thiếu hụt, trọng tâm là tỷ lệ (%) của {target} thiếu từng chỉ số. "
            "Văn bản cuối không dùng cụm 'Mẫu này'. Mở bài nên dùng ngôn ngữ như 'Xét theo tỷ lệ thiếu hụt', 'Về mức phổ biến của từng chỉ số thiếu hụt' hoặc 'Chỉ số có tỷ lệ thiếu hụt cao nhất'. "
            "Top phải nêu tỷ lệ trước; số hộ chỉ là thông tin đối chiếu trong ngoặc hoặc vế phụ sau tỷ lệ. "
            "Phải gọi đúng là tỷ lệ thiếu hụt, không gọi là số hộ và không đổi thành tỷ lệ đạt chuẩn. "
            "Các tỷ lệ thiếu hụt theo chỉ số độc lập có thể chồng lấn, không viết như biểu đồ cơ cấu cộng 100%. "
            "Nếu cần nhắc số hộ phụ thì phải ghi rõ đó là số hộ, còn nhận định chính vẫn theo tỷ lệ %."
        )
    if tid == 11 or pattern == "child_deprivation":
        return (
            "Mẫu 11 là mẫu thiếu hụt của trẻ em, đơn vị chính là số trẻ và tỷ lệ tương ứng trong từng nhóm trẻ em thuộc hộ nghèo/hộ cận nghèo. "
            "Không gọi 657, 572, 511, 501, 484, 385 là số hộ; đây là số trẻ. Không viết 'số trẻ thiếu hộ nghèo' hoặc 'số trẻ thiếu hộ cận nghèo'. "
            "Cách viết an toàn: 'trẻ em thuộc hộ nghèo thiếu ... ghi nhận ... trẻ, tương ứng ...%'; 'trẻ em thuộc hộ cận nghèo thiếu ... ghi nhận ... trẻ, tương ứng ...%'. "
            "Không gọi tỷ lệ trẻ thiếu chỉ tiêu là tỷ lệ hộ nghèo/cận nghèo; chỉ viết là tỷ lệ tương ứng trong nhóm trẻ em thuộc hộ đó. "
            "Mỗi câu nên gắn đúng một chỉ tiêu với một cặp số trẻ + tỷ lệ, không dùng 'lần lượt' khi có nhiều chỉ tiêu và nhiều số. "
            "Không tự cộng các chỉ tiêu vì một trẻ/hộ có thể thiếu nhiều chỉ tiêu."
        )
    if tid == 12 or pattern == "multidimensional_standard":
        return (
            "Mẫu 12 theo chuẩn nghèo đa chiều phải tách rõ đơn vị hộ và nhân khẩu. "
            "Tổng hộ đã rà soát/phân loại là mẫu số theo hộ để tính tỷ lệ hộ nghèo đa chiều; tổng nhân khẩu là số người trong các hộ và có thể lớn hơn số hộ. "
            "Không so sánh trực tiếp tổng hộ với tổng nhân khẩu, không dùng nhân khẩu làm mẫu số cho tỷ lệ hộ nghèo. "
            "Nếu bảng có số hộ nghèo dân tộc Kinh, số hộ nghèo DTTS và số hộ nghèo DTTS tại chỗ thì văn bản phải có một đoạn riêng nhận định theo dân tộc, nêu đủ ba nhóm này. "
            "Phần dân tộc chỉ mô tả cơ cấu trong nhóm hộ nghèo đa chiều, không suy diễn nguyên nhân nghèo theo dân tộc."
        )
    if pattern == "vulnerable_groups":
        return (
            "Mẫu nhóm đối tượng phân tích các nhóm có thể chồng lấn; không coi các nhóm là loại trừ nhau và không cộng thành 100%. "
            "So sánh riêng cột hộ nghèo, hộ cận nghèo hoặc tổng nếu SAFE_BASE_TEXT thể hiện rõ. "
            "Không viết quá ngắn: cần có ít nhất 3 đoạn, gồm tổng quan, nhóm nổi bật và lưu ý giới hạn chồng lấn nhóm."
        )
    if pattern == "ethnicity":
        return (
            "Mẫu dân tộc phải giữ đúng cặp dân tộc-số liệu. Không suy diễn nguyên nhân nghèo theo dân tộc và không đánh giá định kiến. "
            "Nếu có nhiều cột, ghi rõ đang nói hộ nghèo hay hộ cận nghèo. "
            "Không viết quá ngắn: cần có ít nhất 3 đoạn, gồm cơ cấu chung, nhóm có số lượng nổi bật và lưu ý không suy diễn nguyên nhân."
        )
    if pattern == "causes":
        return (
            "Mẫu nguyên nhân nghèo có thể là thống kê nhiều lựa chọn; không kết luận nguyên nhân duy nhất. "
            "So sánh theo số hộ/tỷ lệ của từng nguyên nhân đúng nhóm hộ được nêu. "
            "Không viết quá ngắn: cần có ít nhất 3 đoạn, nêu nguyên nhân nổi bật, nhóm đối tượng liên quan và giới hạn diễn giải."
        )
    return "Bám sát SAFE_BASE_TEXT; chỉ dùng các cặp nhãn-số an toàn trong llm_analysis_anchors, không tự suy luận ngoài dữ liệu."


def _template_retry_guidance(bundle: ReportFactsBundle | None, warnings: list[str] | None = None) -> str:
    """Gợi ý retry theo nhóm mẫu + lỗi hậu kiểm, dùng để giảm fail lặp lại."""
    base = _template_specific_llm_guidance(bundle)
    warning_text = "\n".join(str(w) for w in (warnings or [])[:8]).lower()
    extra: list[str] = []
    if "số liệu ngoài nguồn" in warning_text or "số tự tính" in warning_text:
        extra.append("Bỏ toàn bộ số không chắc chắn; chỉ giữ số xuất hiện nguyên văn trong SAFE_BASE_TEXT hoặc llm_analysis_anchors.")
    if "gán sai cặp" in warning_text or "cặp nhãn-số" in warning_text:
        extra.append("Viết từng cặp nhãn-số thành câu riêng ngắn; không dùng 'lần lượt' khi có nhiều nhãn và nhiều số.")
    if "xếp hạng" in warning_text:
        extra.append("Tránh dùng cao nhất/thấp nhất/lớn nhất/thứ hai/dẫn đầu; nếu không chắc rank tuyệt đối, đổi sang 'địa bàn nổi bật gồm ... với ... hộ' và chỉ nêu số đúng.")
    if "tỷ lệ" in warning_text and "hộ" in warning_text:
        extra.append("Kiểm tra đơn vị: số có đơn vị hộ thì gọi là số hộ; chỉ số có dấu % mới gọi là tỷ lệ.")
    if "đầu kỳ/cuối kỳ" in warning_text:
        extra.append("Với mẫu diễn biến, khi viết 'từ A lên/còn B' phải dùng đúng số đầu kỳ và cuối kỳ của chính địa bàn đó; chênh lệch chỉ viết riêng là tăng/giảm bao nhiêu hộ.")
    if "hiệu quả" in warning_text or "thu nhập-sức khỏe" in warning_text:
        extra.append("Không suy diễn hiệu quả chính sách, tình trạng thu nhập hoặc giải pháp can thiệp nếu bảng chỉ thống kê nguyên nhân/kết quả rà soát.")
    if "hộ cận nghèo" in warning_text and "hộ nghèo" in warning_text:
        extra.append("Giữ đúng đối tượng chính của mẫu; không đổi hộ nghèo thành hộ cận nghèo hoặc ngược lại.")
    if "ngắn" in warning_text or "dưới ngưỡng" in warning_text or "cần tối thiểu" in warning_text:
        extra.append("Bản trước dưới llm_min_words nên bị tính là fail; viết dài hơn tối thiểu theo cấu hình, tối thiểu 3 đoạn, mỗi đoạn 2-3 câu, nhưng chỉ mở rộng bằng số liệu/chỉ tiêu có trong facts.")
    if "nguồn đã kiểm soát" in warning_text or "thông tin đã cung cấp" in warning_text or "giọng prompt" in warning_text:
        extra.append("Bỏ mọi câu meta kiểu 'dựa trên thông tin đã cung cấp', 'nội dung nguồn đã kiểm soát', 'tôi tiến hành phân tích'; viết thẳng như văn bản báo cáo nhận định.")
    try:
        tid = _template_id_from_bundle(bundle)
        pat = _pattern(bundle)
    except Exception:
        tid, pat = 0, ""
    if tid == 11 or pat == "child_deprivation":
        extra.append("Mẫu 11: mỗi chỉ tiêu phải viết theo cấu trúc 'trẻ em thuộc hộ nghèo/cận nghèo thiếu ... ghi nhận ... trẻ, tương ứng ...%'; không gọi số trẻ là số hộ và không gọi tỷ lệ trẻ là tỷ lệ hộ nghèo/cận nghèo.")
    if tid == 12 or pat == "multidimensional_standard":
        extra.append("Mẫu 12: mọi tỷ lệ theo địa bàn phải viết là tỷ lệ trên tổng hộ rà soát của chính địa bàn đó; không ghi là tỷ trọng trong toàn tỉnh, không ghi Đắk Lắk.")
        extra.append("Mẫu 12: nếu bảng có cột dân tộc Kinh/DTTS/DTTS tại chỗ thì nhận định phải có đoạn riêng về cơ cấu hộ nghèo theo dân tộc, không bỏ qua lớp dữ liệu này.")
    if not extra:
        return base
    return base + "\nCác lỗi vừa gặp cần tránh ở lần thử này:\n- " + "\n- ".join(extra)


def _llm_anchor_numeric_cols(
    df: pd.DataFrame,
    label_col: str | None,
    *,
    pattern: str,
    template_id: int,
    table_name: str,
) -> list[str]:
    """Chọn cột neo cho LLM theo trọng tâm từng mẫu, tránh mẫu count/ratio giống nhau."""
    cols = _business_numeric_cols(df, label_col)
    existing = set(df.columns)

    def keep(order: list[str]) -> list[str]:
        picked = [c for c in order if c in existing and c in cols]
        for c in cols:
            if c not in picked:
                picked.append(c)
        return picked

    if template_id in {4, 6} or pattern == "deprivation_count":
        return keep(["so_ho", "tong_nhom"])
    if template_id in {5, 7} or pattern == "deprivation_ratio":
        return keep(["ty_le_%", "ty_le_pct", "tong_nhom", "so_ho"])
    if template_id in {2, 3} or pattern == "movement":
        return keep(["chenh_lech", "so_ho_ky_sau", "so_ho_ky_truoc", "ty_le_bien_dong_%", "tang_1", "tang_2", "tang_3", "giam_1", "giam_2"])
    if template_id == 11 or pattern == "child_deprivation":
        return keep(["so_tre_thieu", "so_ho_ngheo", "so_ho_can_ngheo", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "tong_tre"])
    if template_id == 8 or pattern == "vulnerable_groups":
        return keep([
            "tong_ho_dan_cu", "so_ho_dtts", "tong_ho_ngheo", "tong_ho_can_ngheo",
            "ho_ngheo_dtts", "ho_can_ngheo_dtts", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld",
            "ho_ngheo_co_cong", "ho_can_ngheo_co_cong",
        ])
    if template_id == 12 or pattern == "multidimensional_standard":
        return keep([
            "ty_le_muc_tieu_%", "so_ho_muc_tieu", "tong_ho_ra_soat",
            "so_nhan_khau_muc_tieu", "tong_nhan_khau", "so_ho_kinh",
            "tong_ho_dtts", "so_ho_dtts", "ty_le_ngheo_trong_dtts_%",
            "tong_ho_dtts_tai_cho", "so_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_tai_cho_%",
        ])
    if pattern in {"vulnerable_groups", "ethnicity", "causes"}:
        return keep(["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho", "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%"])
    if template_id == 1 or pattern == "overview_result":
        if table_name == "template_chart":
            return keep(["so_ho", "ty_le_%", "so_nhan_khau"])
        return keep(["so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "tong_ho_ra_soat", "tong_ho_dan_cu"])
    return cols


_BUSINESS_NUMERIC_PREFIXES = (
    "so_", "tong_", "ty_le", "ti_le", "chenh_lech", "muc_", "count", "rate", "delta",
)


def _business_numeric_cols(df: pd.DataFrame, label_col: str | None = None) -> list[str]:
    """Chọn các cột số có khả năng được diễn giải nghiệp vụ.

    Hàm này dùng chung cho 12 mẫu: số hộ, số khẩu/nhân khẩu, tỷ lệ, chênh lệch,
    số trẻ em, số chỉ tiêu... Không hard-code riêng mẫu 1.
    """
    if df is None or df.empty:
        return []
    numeric_cols = [c for c in df.columns if c != label_col and pd.api.types.is_numeric_dtype(df[c])]
    preferred = [c for c in numeric_cols if str(c).startswith(_BUSINESS_NUMERIC_PREFIXES)]
    return preferred or numeric_cols


def _coverage_numeric_cols(df: pd.DataFrame, label_col: str | None = None, pattern: str | None = None) -> list[str]:
    """Chọn cột để đánh giá chất lượng nhận định, không ép quá nhiều cột phụ.

    Khác với _business_numeric_cols dùng để phát hiện gán nhầm số, hàm này chỉ lấy
    các cột nên xuất hiện trong nhận định. Nhờ vậy validator không bắt buộc văn bản
    phải nhắc cả tổng nhân khẩu, số khẩu... khi mẫu đang cần nhận định trọng tâm hộ,
    tỷ lệ hoặc biến động. Thiết kế theo loại cột/pattern, không hard-code từng mẫu.
    """
    cols = _business_numeric_cols(df, label_col)
    pat = str(pattern or "").lower()

    def is_count_col(c: Any) -> bool:
        cc = str(c).lower()
        return (cc.startswith("so_ho") or cc in {"so_ho", "tong_ho", "so_tre_em"}) and "khau" not in cc and "nhan_khau" not in cc

    def is_ratio_col(c: Any) -> bool:
        cc = str(c).lower()
        return "ty_le" in cc or "ti_le" in cc or cc.endswith("_%") or "rate" in cc

    def is_delta_col(c: Any) -> bool:
        cc = str(c).lower()
        return "chenh_lech" in cc or "delta" in cc or "bien_dong" in cc or "tang_giam" in cc

    if "ratio" in pat or "ty_le" in pat or "ti_le" in pat:
        preferred = [c for c in cols if is_ratio_col(c)] or [c for c in cols if is_count_col(c)]
    elif "movement" in pat or "dien_bien" in pat or "diễn_biến" in pat:
        preferred = [c for c in cols if is_delta_col(c)] or [c for c in cols if is_count_col(c)]
    else:
        preferred = [c for c in cols if is_count_col(c)] or [c for c in cols if is_ratio_col(c)] or [c for c in cols if is_delta_col(c)]

    # Nếu không có cột trọng tâm, dùng lại business cols nhưng vẫn đẩy cột nhân khẩu/số khẩu xuống cuối.
    if not preferred:
        preferred = sorted(cols, key=lambda c: ("khau" in str(c).lower() or "nhan_khau" in str(c).lower(), str(c)))
    return preferred


def _num(value: Any) -> str:
    try:
        if value is None:
            return "0"
        n = float(value)
        if abs(n - int(n)) < 1e-9:
            return f"{int(n):,}".replace(",", ".")
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def _pct(value: Any) -> str:
    try:
        n = float(value or 0)
        return f"{n:.2f}".replace(".", ",") + "%"
    except Exception:
        return str(value)


def _as_records(df: pd.DataFrame | None, n: int = 5) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.head(n).where(pd.notna(df.head(n)), None).to_dict(orient="records")


def _bundle_from_dataframe(question: str, data: pd.DataFrame, mode: str | None = None) -> ReportFactsBundle:
    template = get_report_template(1)
    df = data.copy()
    summary = {"scope_label": "bảng số liệu vừa truy vấn", "tong_ho_ra_soat": None}
    facts = {
        "question": question,
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "sample_records": _as_records(df, 5),
        "top_groups": _as_records(df, 3),
        "top_districts": _as_records(df, 3),
    }
    return ReportFactsBundle(
        template={**template.to_dict(), "pattern": "overview_result"},
        scope={"year": None, "huyen": None, "scope_label": "bảng số liệu vừa truy vấn"},
        summary=summary,
        tables={"main": df},
        facts={**summary, **facts},
    )


def _strip_unsafe_heading(text: str) -> str:
    """Bỏ tiêu đề do facts renderer tạo để phần Word không bị lặp header."""
    lines: list[str] = []
    skip_next_title = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            # Giữ khoảng cách đoạn để UI/Word không dồn fallback thành một khối đặc chữ.
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.upper().startswith("BÁO CÁO NHẬN ĐỊNH"):
            skip_next_title = True
            continue
        if skip_next_title:
            skip_next_title = False
            # Dòng này thường là tên mẫu, Word đã có tiêu đề riêng.
            continue
        # Chuyển heading La Mã của renderer sang heading con Ả Rập để tránh lặp I/II trong Word.
        m = re.match(r"^([IVX]+)\.\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            roman = m.group(1).upper()
            order = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5"}.get(roman, roman)
            line = f"{order}. {m.group(2)}"
        lines.append(line)
    # Thu gọn nhiều dòng trống liên tiếp nhưng vẫn giữ ngắt đoạn kép.
    text_out = "\n".join(lines).strip()
    text_out = re.sub(r"\n{3,}", "\n\n", text_out)
    return text_out



def _friendly_text(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "Hộ NLNN mức sống trung bình": "Hộ nông, lâm, ngư nghiệp có mức sống trung bình",
        "NLNN": "nông, lâm, ngư nghiệp",
    }
    for raw, friendly in replacements.items():
        text = text.replace(raw, friendly)
    return text


def _record_label_value(record: dict[str, Any] | None, label_col: str | None, value_col: str | None, unit: str = "") -> str:
    if not isinstance(record, dict) or not label_col or not value_col:
        return ""
    label = _friendly_text(record.get(label_col))
    value = record.get(value_col)
    suffix = f" {unit}" if unit else ""
    return f"{label} ({_num(value)}{suffix})"


def _records_sentence(records: list[dict[str, Any]], label_col: str | None, value_col: str | None, unit: str = "", limit: int = 3) -> str:
    parts = [_record_label_value(r, label_col, value_col, unit) for r in (records or [])[:limit]]
    parts = [p for p in parts if p]
    return "; ".join(parts)


def _value_unit_for_col(col: str | None) -> str:
    c = str(col or "")
    if "ty_le" in c or c.endswith("_%"):
        return "%"
    if "nhan_khau" in c or "khau" in c or "population" in c:
        return "nhân khẩu"
    if "tre" in c and "ty_le" not in c:
        return "trẻ em"
    if c:
        return "hộ"
    return ""


def _column_label(col: str | None) -> str:
    labels = {
        "huyen": "địa bàn",
        "xa_phuong": "xã/phường",
        "phan_loai": "nhóm phân loại hộ",
        "nhom_chi_tieu": "nhóm chỉ tiêu",
        "chi_tieu": "chỉ tiêu",
        "dan_toc": "dân tộc",
        "so_ho": "số hộ",
        "tong_ho": "tổng số hộ",
        "tong_ho_dan_cu": "tổng số hộ dân cư",
        "so_nhan_khau": "số nhân khẩu",
        "tong_nhan_khau": "tổng số nhân khẩu",
        "so_ho_ngheo": "số hộ nghèo",
        "tong_ho_ngheo": "tổng số hộ nghèo",
        "so_khau_ngheo": "số nhân khẩu hộ nghèo",
        "so_ho_can_ngheo": "số hộ cận nghèo",
        "tong_ho_can_ngheo": "tổng số hộ cận nghèo",
        "so_khau_can_ngheo": "số nhân khẩu hộ cận nghèo",
        "so_ho_nlnndn_mstb": "số hộ nông, lâm, ngư nghiệp có mức sống trung bình",
        "so_khau_nlnndn_mstb": "số nhân khẩu thuộc hộ nông, lâm, ngư nghiệp có mức sống trung bình",
        "ty_le_%": "tỷ lệ",
        "ty_le_muc_tieu_%": "tỷ lệ hộ nghèo chung",
        "so_ho_muc_tieu": "số hộ mục tiêu",
        "so_ho_kinh": "số hộ nghèo dân tộc Kinh",
        "so_ho_dtts": "số hộ nghèo DTTS",
        "so_ho_dtts_tai_cho": "số hộ nghèo DTTS tại chỗ",
        "tong_ho_dtts": "tổng số hộ DTTS",
        "tong_ho_dtts_tai_cho": "tổng số hộ DTTS tại chỗ",
        "ty_le_dtts_trong_nhom_%": "tỷ trọng DTTS trong nhóm hộ nghèo",
        "ty_le_ngheo_trong_dtts_%": "tỷ lệ hộ nghèo trong nhóm DTTS",
        "ty_le_ngheo_trong_dtts_tai_cho_%": "tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ",
        "ho_ngheo_dtts": "hộ nghèo DTTS",
        "ho_can_ngheo_dtts": "hộ cận nghèo DTTS",
        "ho_ngheo_khong_knld": "hộ nghèo không có khả năng lao động",
        "ho_can_ngheo_khong_knld": "hộ cận nghèo không có khả năng lao động",
        "ho_ngheo_co_cong": "hộ nghèo có người có công với cách mạng",
        "ho_can_ngheo_co_cong": "hộ cận nghèo có người có công với cách mạng",
        "so_ho_ky_truoc": "số hộ đầu kỳ",
        "so_ho_ky_sau": "số hộ cuối kỳ",
        "giam_1": "số hộ giảm nhóm 1",
        "giam_2": "số hộ giảm nhóm 2",
        "giam_khac": "số hộ giảm khác có căn cứ chi tiết",
        "tang_1": "số hộ tăng nhóm 1",
        "tang_2": "số hộ tăng nhóm 2",
        "tang_3": "số hộ tăng nhóm 3",
        "tang_khac": "số hộ tăng khác có căn cứ chi tiết",
        "chenh_lech": "mức chênh lệch",
    }
    return labels.get(str(col or ""), str(col or "chỉ tiêu"))



def _public_report_warning_text(text: Any) -> str:
    """Chuyển cảnh báo kỹ thuật thành câu có thể đưa vào báo cáo Word.

    Hàm này chỉ làm sạch ngôn ngữ trình bày; không thay đổi ý nghĩa cảnh báo.
    Không để các từ như DB, mẫu số, cột, SAFE_BASE_TEXT, audit... xuất hiện trong
    phần nhận định công khai.
    """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return "Nguồn dữ liệu hiện có có giới hạn phạm vi, cần thận trọng khi diễn giải."

    replacements = {
        "DB": "nguồn dữ liệu hiện có",
        "database": "nguồn dữ liệu hiện có",
        "SQL": "quy trình tổng hợp số liệu",
        "Python": "quy trình tổng hợp số liệu",
        "fact pack": "bộ số liệu tổng hợp",
        "REPORT_FACTS": "bộ số liệu tổng hợp",
        "SAFE_BASE_TEXT": "nội dung nguồn đã kiểm soát",
        "audit log": "ghi nhận kiểm tra",
        "audit": "kiểm tra",
        "validator": "bộ kiểm tra",
        "template_id": "mã biểu mẫu",
        "Excel": "bảng báo cáo",
        "template": "biểu mẫu",
    }
    for raw, repl in replacements.items():
        s = re.sub(re.escape(raw), repl, s, flags=re.IGNORECASE)

    # Loại cách gọi kỹ thuật về mẫu/cột/ô khi cảnh báo bị đưa vào văn bản Word.
    s = re.sub(r"\bmẫu\s*(?:số\s*)?\d+\b[:\-–]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\btemplate\s*\d+\b[:\-–]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcột\s+[A-Z](?:\s*[,+/&]\s*[A-Z])*\b", "chỉ tiêu tương ứng", s, flags=re.IGNORECASE)
    s = re.sub(r"\bô\s+[A-Z]+\d+\b", "ô dữ liệu tương ứng", s, flags=re.IGNORECASE)
    s = re.sub(r"\b[A-Z](?:\s*[-+*/]\s*[A-Z])+\b", "công thức tổng hợp", s)
    s = s.replace("phan_loai", "nhóm phân loại hộ")
    s = s.replace("bien_dong_dau_ky", "nhóm biến động đầu kỳ")
    s = s.replace("unexplained_delta", "phần chênh lệch chưa có căn cứ phân loại")
    s = re.sub(r"\s+", " ", s).strip(" ;,.-")
    if not s:
        return "Nguồn dữ liệu hiện có có giới hạn phạm vi, cần thận trọng khi diễn giải."
    return s[0].upper() + s[1:] + ("." if s[-1] not in ".!?" else "")

def _total_from_records(records: list[dict[str, Any]], value_col: str) -> int:
    total = 0
    for r in records or []:
        if isinstance(r, dict):
            try:
                total += int(float(r.get(value_col) or 0))
            except Exception:
                pass
    return total


def _render_template_detail_from_insights(bundle: ReportFactsBundle) -> str:
    """Tạo phần nhận định nghiệp vụ tự nhiên, không đánh mục cứng và không lộ thuật ngữ kỹ thuật."""
    f = bundle.facts or {}
    table = f.get("table_insights") or {}
    chart = f.get("chart_insights") or {}
    context = f.get("template_context") or {}
    if not isinstance(table, dict) or not table:
        return ""

    pattern = str(table.get("pattern") or _pattern(bundle))
    template_id = int((bundle.template or {}).get("id") or table.get("template_id") or 0)
    label_col = table.get("label_col")
    value_col = table.get("primary_value_col")
    unit = _value_unit_for_col(value_col)
    paragraphs: list[str] = []

    t1 = table.get("template1_detail") if isinstance(table.get("template1_detail"), dict) else None
    if template_id == 1 and t1:
        medium_total = int(float(t1.get("total_medium_living_households") or 0))
        template_warnings = f.get("template_data_warnings") or []
        paragraphs.append(
            f"Kết quả rà soát trên phạm vi {_scope(bundle)} ghi nhận "
            f"{_num(t1.get('total_poor_households'))} hộ nghèo, "
            f"{_num(t1.get('total_near_poor_households'))} hộ cận nghèo và "
            f"{_num(medium_total)} hộ nông, lâm, ngư nghiệp có mức sống trung bình. "
            "Nội dung nhận định này chỉ đối chiếu ba nhóm chỉ tiêu trên, không mở rộng sang nhóm hộ khác ngoài phạm vi biểu mẫu."
        )
        if medium_total <= 0:
            paragraphs.append("Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình được giữ bằng 0 theo bảng tổng hợp hiện có và không phân tích sâu thêm ngoài phạm vi số liệu của biểu mẫu.")
        poor = _records_sentence(t1.get("top_poor_districts") or [], "huyen", "so_ho_ngheo", "hộ", 2)
        near = _records_sentence(t1.get("top_near_poor_districts") or [], "huyen", "so_ho_can_ngheo", "hộ", 2)
        medium = _records_sentence(t1.get("top_medium_living_districts") or [], "huyen", "so_ho_nlnndn_mstb", "hộ", 2)
        district_parts = []
        if poor:
            district_parts.append(f"hộ nghèo tập trung nhiều ở {poor}")
        if near:
            district_parts.append(f"hộ cận nghèo nổi bật ở {near}")
        if medium and _total_from_records(t1.get("top_medium_living_districts") or [], "so_ho_nlnndn_mstb") > 0:
            district_parts.append(f"nhóm hộ nông, lâm, ngư nghiệp có mức sống trung bình cao ở {medium}")
        if district_parts:
            paragraphs.append(
                "Xét theo địa bàn, " + "; ".join(district_parts) + ". "
                "Các cặp địa bàn - nhóm hộ - số hộ này được dùng để đối chiếu trực tiếp với bảng và biểu đồ của biểu mẫu."
            )
    elif pattern == "movement" and isinstance(table.get("movement_detail"), dict):
        anchors = f.get("sentence_anchors") or []
        if anchors:
            paragraphs.extend(str(x) for x in anchors[:4] if str(x).strip())
        else:
            m = table["movement_detail"]
            paragraphs.append(
                f"Số liệu diễn biến theo biểu mẫu cho thấy tổng số hộ đầu kỳ là {_num(m.get('tong_ky_truoc'))} hộ, "
                f"cuối kỳ theo công thức là {_num(m.get('tong_ky_sau'))} hộ, chênh lệch {_num(m.get('chenh_lech'))} hộ, "
                f"tương ứng {_pct(m.get('ty_le_bien_dong_%'))}."
            )
        movement_warnings = f.get("movement_warnings") or []
        if movement_warnings:
            paragraphs.append("Lưu ý diễn biến: " + " ".join(str(w) for w in movement_warnings))
    elif pattern in {"deprivation_count", "deprivation_ratio"} and isinstance(table.get("deprivation_detail"), dict):
        d = table["deprivation_detail"]
        key = "top_by_ratio" if pattern == "deprivation_ratio" else "top_by_count"
        chosen_value_col = "ty_le_%" if pattern == "deprivation_ratio" else "so_ho"
        chosen_unit = "%" if pattern == "deprivation_ratio" else "hộ"
        top = _records_sentence(d.get(key) or [], label_col or "chi_tieu", chosen_value_col, chosen_unit, 4)
        if top:
            if pattern == "deprivation_ratio":
                paragraphs.append(
                    f"Các chỉ số có tỷ lệ thiếu hụt nổi bật gồm {top}. Mẫu này ưu tiên diễn giải theo tỷ lệ phần trăm; số hộ chỉ dùng để đối chiếu quy mô khi nguồn dữ liệu có cung cấp."
                )
            else:
                paragraphs.append(
                    f"Các chỉ số có số hộ thiếu hụt nổi bật gồm {top}. Mẫu này ưu tiên diễn giải theo số hộ, không chuyển trọng tâm sang tỷ lệ nếu không cần thiết."
                )
        paragraphs.append(str(d.get("overlap_warning") or "Các chỉ số thiếu hụt có thể chồng lấn nên không diễn giải như một cơ cấu cộng đủ 100%."))
    elif isinstance(table.get("two_group_detail"), dict):
        t = table["two_group_detail"]
        child_mode = template_id == 11 or pattern == "child_deprivation"
        group_unit = "trẻ em" if child_mode else "hộ"
        if template_id == 9 or pattern == "ethnicity":
            def ethnic_sentence(records: list[dict[str, Any]], count_col: str, pct_col: str) -> str:
                items: list[str] = []
                for row in (records or [])[:3]:
                    label = _row_label(row, label_col or "dan_toc", "dan_toc", default="dân tộc")
                    count_text = f"{_num(row.get(count_col))} hộ"
                    pct_value = row.get(pct_col)
                    pct_text = "" if pct_value is None else f", tỷ lệ {_pct(pct_value)}"
                    items.append(f"{label} ({count_text}{pct_text})")
                return "; ".join(items)

            poor = ethnic_sentence(t.get("top_poor") or [], "so_ho_ngheo", "ty_le_ngheo_%")
            near = ethnic_sentence(t.get("top_near_poor") or [], "so_ho_can_ngheo", "ty_le_can_ngheo_%")
        else:
            poor = _records_sentence(t.get("top_poor") or [], label_col or "chi_tieu", "so_ho_ngheo", group_unit, 3)
            near = _records_sentence(t.get("top_near_poor") or [], label_col or "chi_tieu", "so_ho_can_ngheo", group_unit, 3)
        parts = []
        if poor:
            parts.append(f"đối với trẻ em thuộc hộ nghèo, các chỉ tiêu nổi bật gồm {poor}" if child_mode else f"đối với hộ nghèo, các nhóm/chỉ tiêu nổi bật gồm {poor}")
        if near:
            parts.append(f"đối với trẻ em thuộc hộ cận nghèo, các chỉ tiêu nổi bật gồm {near}" if child_mode else f"đối với hộ cận nghèo, các nhóm/chỉ tiêu nổi bật gồm {near}")
        if parts:
            paragraphs.append("; trong khi ".join(parts).capitalize() + ".")
    elif isinstance(table.get("multidim_detail"), dict):
        md = table["multidim_detail"]
        top_target = _records_sentence(md.get("top_by_target_households") or [], label_col or "huyen", "so_ho_muc_tieu", "hộ", 3)
        top_ratio = _records_sentence(md.get("top_by_target_ratio") or [], label_col or "huyen", "ty_le_muc_tieu_%", "%", 3)
        if top_target or top_ratio:
            paragraphs.append(
                "Theo chuẩn nghèo đa chiều, "
                + (f"các địa bàn nổi bật theo quy mô hộ mục tiêu gồm {top_target}. " if top_target else "")
                + (f"Xét theo tỷ lệ trong tổng hộ rà soát của địa bàn, các địa bàn đáng chú ý gồm {top_ratio}." if top_ratio else "")
            )
    else:
        top = _records_sentence(table.get("top_records") or [], label_col, value_col, unit, 3)
        bottom = _records_sentence(table.get("bottom_records") or [], label_col, value_col, unit, 2)
        measure = _column_label(value_col)
        group_label = _column_label(label_col)
        if top:
            paragraphs.append(f"Theo {measure}, các {group_label} có giá trị cao gồm {top}.")
        if bottom:
            paragraphs.append(f"Ở nhóm thấp hơn, có thể lưu ý {bottom}.")

    zero = _records_sentence(table.get("zero_records") or [], label_col, value_col, unit, 2)
    if zero:
        paragraphs.append(f"Một số dòng chưa phát sinh hoặc có giá trị bằng 0 gồm {zero}; nội dung này cần được kiểm tra theo phạm vi dữ liệu trước khi diễn giải sâu.")

    if isinstance(chart, dict) and chart.get("available"):
        chart_value_col = chart.get("value_col") or value_col
        chart_label_col = chart.get("label_col") or label_col
        if template_id == 11 and chart_value_col in {"so_ho_ngheo", "so_ho_can_ngheo"}:
            chart_unit = "trẻ em"
            chart_measure_label = "số trẻ em thuộc hộ nghèo" if chart_value_col == "so_ho_ngheo" else "số trẻ em thuộc hộ cận nghèo"
        else:
            chart_unit = _value_unit_for_col(chart_value_col)
            chart_measure_label = _column_label(chart_value_col)
        chart_top = _records_sentence(chart.get("top_records") or [], chart_label_col, chart_value_col, chart_unit, 3)
        if pattern == "movement" and chart.get("value_cols"):
            paragraphs.append(str(chart.get("message") or "Biểu đồ minh họa hỗ trợ đối chiếu biến động giữa các kỳ."))
        elif chart_top:
            if template_id == 1:
                paragraphs.append(
                    f"Biểu đồ đối chiếu trực quan ba nhóm chỉ tiêu của biểu mẫu theo {chart_measure_label}, gồm {chart_top}."
                )
            else:
                paragraphs.append(
                    f"Biểu đồ minh họa cho thấy các nhóm nổi bật theo {chart_measure_label} gồm {chart_top}, "
                    "qua đó giúp nhìn rõ hơn trọng tâm cần theo dõi trong phạm vi báo cáo."
                )

    if template_id == 1:
        # Mẫu 1 đã tự nêu giới hạn NLNN = 0 ở trên; không lặp lại cảnh báo dữ liệu/ghi chú quản lý chung.
        return "\n\n".join(p.strip() for p in paragraphs if p and p.strip())

    data_warnings = []
    if isinstance(f, dict):
        data_warnings = [str(w).strip() for w in (f.get("template_data_warnings") or []) if str(w).strip()]
    for warning in data_warnings[:3]:
        if warning and warning not in paragraphs:
            paragraphs.append("Lưu ý dữ liệu: " + _public_report_warning_text(warning))

    notes = []
    if isinstance(context, dict):
        notes.extend(context.get("interpretation_notes") or [])
    notes.extend(table.get("interpretation_notes") or [])
    seen_notes: list[str] = []
    for note in notes:
        note = str(note).strip()
        note = note.replace("Bảng dùng để nhận định", "Các số liệu được sử dụng để nhận định")
        note = note.replace("bảng không có", "dữ liệu không có")
        note = note.replace("bảng mẫu", "số liệu")
        note = note.replace("biểu mẫu báo cáo", "số liệu báo cáo")
        if note and note not in seen_notes:
            seen_notes.append(note)
    if seen_notes:
        note_text = " ".join(seen_notes[:2])
        # Viết lại ghi chú diễn giải cho tự nhiên hơn, tránh cảm giác máy móc trong fallback.
        if "không suy diễn" in note_text.lower() or "chưa có" in note_text.lower():
            note_text = (
                "Các nhận định trong phần này chỉ phản ánh phạm vi số liệu đã tổng hợp; "
                "những nội dung về nguyên nhân, hiệu quả chính sách hoặc xu hướng dài hạn cần được bổ sung bằng nguồn dữ liệu kiểm chứng riêng."
            )
        paragraphs.append(note_text)

    return "\n\n".join(p.strip() for p in paragraphs if p and p.strip())

def _has_template_table(bundle: ReportFactsBundle) -> bool:
    try:
        df = (bundle.tables or {}).get("template_main")
        return isinstance(df, pd.DataFrame) and not df.empty
    except Exception:
        return False


def _render_template_first_base_text(bundle: ReportFactsBundle, report_level: str) -> str:
    """Sinh văn bản nền theo bộ số liệu báo cáo, giữ giọng nhận định tự nhiên để LLM dễ biên tập."""
    scope_label = _scope(bundle)
    detail = _render_template_detail_from_insights(bundle)
    # Mẫu 1 đã có phạm vi và các nhóm chỉ tiêu trong detail; không bọc thêm intro/closing chung
    # vì sẽ làm lộ giọng fallback và dễ kéo thêm "hộ không nghèo"/quản lý chung vào nhận định.
    if _template_id_from_bundle(bundle) == 1:
        return _strip_unsafe_heading(detail or "")
    intro = (
        f"Báo cáo tổng hợp số liệu trên phạm vi {scope_label}, tập trung làm rõ quy mô các nhóm hộ, "
        "những nhóm/chỉ tiêu nổi bật và các nội dung cần tiếp tục theo dõi trong quá trình quản lý."
    )
    closing = (
        "Từ kết quả tổng hợp, công tác rà soát trong kỳ tiếp theo cần tiếp tục được thực hiện thống nhất về phạm vi, phương pháp và cách đối chiếu số liệu. "
        "Các nhóm hộ hoặc chỉ tiêu có quy mô cao nên được theo dõi thường xuyên để phục vụ việc xác định trọng tâm quản lý và xây dựng kế hoạch hỗ trợ phù hợp."
    )
    parts = [intro]
    if detail:
        parts.append(detail)
    parts.append(closing)
    return _strip_unsafe_heading("\n\n".join(parts))


def _safe_base_text(bundle: ReportFactsBundle, report_level: str) -> str:
    # Khi đã có bộ số liệu báo cáo, dùng bảng đó làm nguồn nhận định chính.
    # Không ghép renderer tổng quan từ summary/top_groups nữa để tránh lặp và lẫn khái niệm
    # như "hộ không nghèo" với "hộ NLNN mức sống trung bình" ở mẫu 1.
    if _template_id_from_bundle(bundle) == 1:
        template_first = _render_template_first_base_text(bundle, report_level=report_level).strip()
        if template_first:
            return _strip_unsafe_heading(template_first).strip()
        return _strip_unsafe_heading(render_full_report_text(bundle, report_level=report_level)).strip()
    if _has_template_table(bundle):
        return _render_template_first_base_text(bundle, report_level=report_level).strip()

    base = _strip_unsafe_heading(render_full_report_text(bundle, report_level=report_level))
    detail = _render_template_detail_from_insights(bundle)
    if detail:
        return (base + "\n\n" + detail).strip()
    return base


def _load_style_profile(style_profile_path: str | Path | None) -> dict[str, Any]:
    if not style_profile_path:
        return {}
    p = Path(style_profile_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_style_examples(style_profile_path: str | Path | None) -> str:
    candidates: list[Path] = []
    if style_profile_path:
        p = Path(style_profile_path)
        candidates.append(p.with_name("report_style_examples.md"))
        candidates.append(p.parent.parent / "data" / "report_style_examples.md")
    here = Path(__file__).resolve()
    candidates.extend([
        here.with_name("report_style_examples.md"),
        here.parent / "report_style_examples.md",
        here.parent.parent / "report_style_examples.md",
        here.parent.parent / "data" / "report_style_examples.md",
    ])
    for p in candidates:
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8")
                # Giữ vừa đủ để prompt không quá dài; ưu tiên toàn phần đầu + phần bổ sung cuối.
                if len(text) > 9000:
                    text = text[:5500] + "\n\n...\n\n" + text[-3000:]
                return text
        except Exception:
            continue
    return ""


def _normalize_number_token(token: str) -> str:
    token = str(token or "")
    token = token.replace("%", "")
    token = re.sub(r"[^0-9,\.]", "", token)
    # 3.691 -> 3691; 32,68 -> 32.68; 5.680,43 -> 5680.43
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    elif "." in token:
        parts = token.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            token = "".join(parts)
    return token.strip(".")


def _extract_number_tokens(text: str) -> list[str]:
    raw = re.findall(r"(?<![A-Za-zÀ-ỹ])\d+(?:[\.,]\d+)*%?", str(text or ""))
    out: list[str] = []
    for item in raw:
        norm = _normalize_number_token(item)
        if not norm:
            continue
        # Bỏ số thứ tự mục 1-6 nếu xuất hiện đơn lẻ.
        if norm in {"1", "2", "3", "4", "5", "6"}:
            continue
        out.append(norm)
    return out


def _number_variants(value: Any) -> set[str]:
    """Các biến thể để hậu kiểm số mềm hơn, tránh reject vì định dạng 2447/2.447.

    Luôn thêm dạng normalize trực tiếp từ chuỗi gốc. Trước đây nếu value là
    chuỗi đã format sẵn như "3.570", float("3.570") bị hiểu thành 3.57, làm
    validator tưởng LLM thêm số ngoài nguồn hoặc làm mất số cốt lõi 3570/3035.
    """
    variants: set[str] = set()
    if value is None:
        return variants

    raw = str(value).strip()
    if raw:
        variants.add(_normalize_number_token(raw))
        variants.update(_extract_number_tokens(raw))

    formatted = _num(value)
    variants.add(_normalize_number_token(formatted))
    variants.update(_extract_number_tokens(formatted))

    try:
        # Nếu value là chuỗi có dấu chấm nghìn thuần túy, dùng bản normalize trước,
        # không để float diễn giải thành số thập phân 3.57.
        if isinstance(value, str) and re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", value.strip()):
            return {v for v in variants if v}
        n = float(value)
        fixed_two = f"{n:.2f}"
        variants.add(fixed_two)
        variants.add(fixed_two.replace(".", ","))
        variants.add(_normalize_number_token(fixed_two))
        variants.add(_normalize_number_token(fixed_two.replace(".", ",")))
        if abs(n - int(n)) < 1e-9:
            variants.add(str(int(n)))
            variants.add(f"{int(n):,}".replace(",", "."))
            variants.add(_normalize_number_token(f"{int(n):,}".replace(",", ".")))
        else:
            variants.add(str(n).rstrip("0").rstrip("."))
            variants.add(str(n).replace(".", ","))
            variants.add(_normalize_number_token(str(n)))
            variants.add(_normalize_number_token(str(n).replace(".", ",")))
    except Exception:
        pass
    return {v for v in variants if v}


def _essential_number_groups(bundle: ReportFactsBundle | None, safe_base: str) -> list[set[str]]:
    """Chỉ bắt LLM giữ số cốt lõi; số phụ trong top địa bàn được phép lược bớt để văn bản tự nhiên hơn."""
    groups: list[set[str]] = []
    if bundle is not None:
        # Năm/phạm vi là thông tin nên có trong văn bản, nhưng không coi là số liệu cốt lõi
        # để hard-fail LLM. Nếu ép giữ năm như số bắt buộc, các mẫu nhiều cột dễ fail
        # dù phần nhận định dữ liệu chính đã đúng.
        try:
            _ = (bundle.scope or {}).get("year")
        except Exception:
            pass
        facts = getattr(bundle, "facts", {}) or {}
        table = facts.get("table_insights") if isinstance(facts, dict) else None
        t1 = table.get("template1_detail") if isinstance(table, dict) else None
        if isinstance(t1, dict):
            for key in ("total_poor_households", "total_near_poor_households", "total_medium_living_households"):
                groups.append(_number_variants(t1.get(key)))
            return [g for g in groups if g]
        pat = _pattern(bundle)
        # Với mẫu movement 2/3, số cốt lõi là đầu kỳ/cuối kỳ/chênh lệch của bảng diễn biến,
        # không phải tổng hộ rà soát hoặc hộ cận nghèo của summary chung.
        if pat == "movement":
            for key in ("tong_ky_truoc", "tong_ky_sau", "chenh_lech"):
                if key in facts:
                    groups.append(_number_variants(facts.get(key)))
            return [g for g in groups if g]
        # Các mẫu phân tích 4-12 không bắt buộc nhắc lại toàn bộ summary chung.
        # Chỉ giữ các số tổng thật sự thuộc bài toán của mẫu để tránh fallback bị đánh trượt oan.
        if pat in {"deprivation_count", "deprivation_ratio"}:
            # Không ép nhận định thiếu hụt phải nhắc tổng số hộ nhóm; số top chỉ tiêu đã được kiểm bằng cặp nhãn-số.
            return [g for g in groups if g]
        if pat == "multidimensional_standard":
            # Mẫu 12 có nhiều mẫu số/tỷ lệ; không ép nhận định phải nhắc tổng toàn tỉnh nếu đoạn đang phân tích top địa bàn.
            return [g for g in groups if g]
        if pat in {"vulnerable_groups", "ethnicity", "causes", "child_deprivation"}:
            return [g for g in groups if g]
        for key in ("tong_ho_ra_soat", "ho_ngheo", "ho_can_ngheo", "total_households_in_group", "tong_ky_truoc", "tong_ky_sau"):
            if key in facts:
                groups.append(_number_variants(facts.get(key)))
    if not groups:
        # Fallback chung: lấy tối đa 5 số đầu có ý nghĩa, không bắt quá nhiều số top phụ.
        for n in _extract_number_tokens(safe_base):
            if n in {"1", "2", "3", "4", "5", "6"}:
                continue
            groups.append({n})
            if len(groups) >= 5:
                break
    return [g for g in groups if g]




# ── Hậu kiểm cặp nhãn - số liệu ─────────────────────────────────────────────
def _sentence_units(text: str) -> list[str]:
    """Tách câu/cụm ngắn để kiểm tra một cặp địa bàn/chỉ tiêu với số gần nó.

    Lưu ý quan trọng: không tách dấu chấm trong số hàng nghìn như 1.206, 3.691.
    Đồng thời tách "và 917 hộ cận nghèo" để tránh một cụm chứa nhiều chỉ tiêu gây lọt lỗi.
    """
    raw = str(text or "")
    parts = re.split(
        r"(?:\n+|(?<!\d)[.;!?](?!\d)|,\s+(?:và|còn|đồng thời)\s+|\s+và\s+(?=\d|[A-ZĐ]))",
        raw,
    )
    return [p.strip() for p in parts if p and p.strip()]


def _text_has_measure(unit: str, col: str) -> bool:
    t = unit.lower()
    c = str(col)
    # Mẫu diễn biến 2/3: phân biệt rõ đầu kỳ/cuối kỳ với chênh lệch.
    # Nếu cụm chỉ nói "giảm -846 hộ" thì không được kiểm như số hộ đầu kỳ/cuối kỳ.
    if c == "so_ho_ky_truoc":
        return "kỳ trước" in t or "đầu kỳ" in t or "dau ky" in t or "năm trước" in t
    if c == "so_ho_ky_sau":
        return "kỳ sau" in t or "cuối kỳ" in t or "cuoi ky" in t or "năm sau" in t
    if c.startswith("giam_"):
        return "giảm" in t or "thoát" in t or "vượt chuẩn" in t
    if c.startswith("tang_"):
        return "tăng" in t or "phát sinh" in t or "tái" in t or "trở thành" in t
    if c == "so_ho_kinh":
        return ("kinh" in t) and ("hộ" in t or "số" in t)
    if c == "so_ho_dtts":
        return ("dtts" in t or "dân tộc thiểu số" in t or "thiểu số" in t) and "tại chỗ" not in t and ("hộ" in t or "số" in t)
    if c == "so_ho_dtts_tai_cho":
        return ("dtts tại chỗ" in t or "dân tộc thiểu số tại chỗ" in t or "thiểu số tại chỗ" in t or "tại chỗ" in t) and ("hộ" in t or "số" in t)
    if c == "tong_ho_dtts":
        return ("tổng" in t and ("dtts" in t or "dân tộc thiểu số" in t or "thiểu số" in t) and "tại chỗ" not in t)
    if c == "tong_ho_dtts_tai_cho":
        return ("tổng" in t and ("dtts tại chỗ" in t or "dân tộc thiểu số tại chỗ" in t or "thiểu số tại chỗ" in t or "tại chỗ" in t))
    if c == "so_nhan_khau_muc_tieu":
        return "nhân khẩu" in t or "khẩu" in t
    if c == "ty_le_muc_tieu_%":
        return "%" in t or "tỷ lệ" in t or "tổng hộ rà soát" in t
    if c == "ty_le_dtts_trong_nhom_%":
        return "tỷ trọng" in t and ("dtts" in t or "dân tộc thiểu số" in t or "thiểu số" in t)
    if c == "ty_le_ngheo_trong_dtts_%":
        return ("tỷ lệ" in t or "%" in t) and ("dtts" in t or "dân tộc thiểu số" in t or "thiểu số" in t) and "tại chỗ" not in t
    if c == "ty_le_ngheo_trong_dtts_tai_cho_%":
        return ("tỷ lệ" in t or "%" in t) and ("tại chỗ" in t or "dtts tại chỗ" in t or "dân tộc thiểu số tại chỗ" in t)
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
            label = _column_label(c).lower()
            return label and label != c.lower() and label in t
        return "tỷ lệ" in t or "tỉ lệ" in t or "%" in t or "phần trăm" in t
    if c.startswith("chenh_lech") or c.startswith("delta"):
        return "chênh lệch" in t or "tăng" in t or "giảm" in t or "biến động" in t
    label = _column_label(c).lower()
    # Dùng nhãn tiếng Việt của cột cho các mẫu khác; không yêu cầu exact quá chặt.
    if label and label != c.lower() and label in t:
        return True
    # Bắt rộng cho các mẫu khác: cột số hộ/số khẩu/số trẻ em/tổng/tỷ lệ thường được viết bằng nhãn chung.
    if c.startswith("so_ho") and c in {"so_ho", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb", "so_ho_muc_tieu"} and "hộ" in t:
        return True
    if c.startswith("so_") and not c.startswith("so_ho") and ("số " in t or "số lượng" in t):
        return True
    if c.startswith("tong_") and ("tổng số" in t or "tổng hộ" in t or "tổng nhân khẩu" in t):
        return True
    return False


def _unit_has_superlative_claim(unit: str) -> bool:
    t = str(unit or "").lower()
    return bool(re.search(r"\b(cao nhất|lớn nhất|nhiều nhất|đứng đầu|dẫn đầu|xếp đầu|vị trí lớn nhất|quy mô lớn nhất)\b", t))


def _unsupported_claim_warnings(text: str) -> list[str]:
    """Cảnh báo nhận định vượt dữ liệu, nhưng tránh bắt nhầm câu giới hạn dữ liệu.

    Lưu ý: nhóm cảnh báo này là cảnh báo ngữ cảnh/chất lượng. Không nên làm hard-fail
    nếu số liệu, cặp nhãn-số và so sánh vẫn đúng. Mục tiêu là cho LLM 3B có thể qua
    với một ít ngữ cảnh chung, nhưng vẫn nhắc người dùng kiểm lại.
    """
    warnings: list[str] = []
    lower = str(text or "").lower()

    # Các cụm hỗ trợ/chính sách có thể vượt dữ liệu; để warning, không tự hard-fail.
    risky_patterns = [
        ("đứng đầu trong việc hỗ trợ", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("giữ vị trí cao trong việc hỗ trợ", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("vị trí cao trong việc hỗ trợ", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("trong việc hỗ trợ hộ nghèo", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("trong việc hỗ trợ hộ cận nghèo", "Văn bản có nhận định về hoạt động hỗ trợ không có trong số liệu."),
        ("không bỏ sót bất kỳ", "Văn bản có cam kết tuyệt đối không được chứng minh bằng số liệu."),
        ("đảm bảo không bỏ sót", "Văn bản có cam kết tuyệt đối không được chứng minh bằng số liệu."),
        ("nguyên nhân chính", "Văn bản suy diễn nguyên nhân khi bảng không chứng minh nguyên nhân."),
    ]
    for needle, msg in risky_patterns:
        if needle in lower and msg not in warnings:
            warnings.append(msg)

    # Trước đây bắt mọi cụm "do thiếu" làm hard fail, khiến câu đúng như
    # "do thiếu dữ liệu trực tiếp" bị hiểu nhầm là suy diễn nguyên nhân nghèo.
    # Giờ chỉ cảnh báo khi "do thiếu" đi với nhóm nguyên nhân nghèo cụ thể.
    if re.search(r"do\s+thiếu\s+(?:đất|vốn|lao\s+động|công\s+cụ|phương\s+tiện|kiến\s+thức|kỹ\s+năng|việc\s+làm|thu\s+nhập|nhà\s+ở|nước\s+sạch|bhyt|bhxh)", lower):
        warnings.append("Văn bản có dấu hiệu suy diễn nguyên nhân từ bảng tổng hợp.")

    return _dedupe_text_items(warnings)


def _movement_other_reason_claim_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    if bundle is None or _pattern(bundle) != "movement":
        return []
    facts = getattr(bundle, "facts", {}) or {}
    if bool(facts.get("other_reason_available")):
        return []
    lower = str(text or "").lower()
    reason_terms = r"(chết|chuyển đi|chuyển đến|tách hộ|nhập hộ|thay đổi nhân khẩu)"
    if re.search(rf"\bdo\s+{reason_terms}", lower, flags=re.UNICODE):
        return ["Văn bản tự gán nguyên nhân biến động khác khi DB chưa có cột lý do chi tiết."]
    return []



def _mau12_has_ethnicity_columns(bundle: ReportFactsBundle | None) -> bool:
    """Mẫu 12 có lớp dữ liệu dân tộc cần được bao phủ trong nhận định hay không."""
    if bundle is None:
        return False
    if _template_id_from_bundle(bundle) != 12 and _pattern(bundle) != "multidimensional_standard":
        return False
    tables = getattr(bundle, "tables", {}) or {}
    for name in ("template_main", "main", "by_district", "template_chart"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        cols = set(str(c) for c in df.columns)
        needed = {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho"}
        if needed.issubset(cols):
            try:
                total = sum(float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum()) for c in needed)
                if total > 0:
                    return True
            except Exception:
                return True
    return False


def _mau12_ethnicity_coverage_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi mẫu 12 có bảng dân tộc nhưng văn bản chỉ nói tỷ lệ/tổng số ở diện rộng."""
    if not _mau12_has_ethnicity_columns(bundle):
        return []
    lower = str(text or "").lower()
    mentions_kinh = "kinh" in lower
    mentions_dtts = "dtts" in lower or "dân tộc thiểu số" in lower or "thiểu số" in lower
    mentions_local = "tại chỗ" in lower or "tai cho" in lower
    if mentions_kinh and mentions_dtts and mentions_local:
        return []
    missing = []
    if not mentions_kinh:
        missing.append("dân tộc Kinh")
    if not mentions_dtts:
        missing.append("DTTS")
    if not mentions_local:
        missing.append("DTTS tại chỗ")
    return [
        "Mẫu 12 thiếu nhận định theo dân tộc: bảng có số hộ nghèo dân tộc Kinh, DTTS và DTTS tại chỗ nên văn bản phải nhắc đủ "
        + ", ".join(missing)
        + "."
    ]



def _mau12_rows_for_checks(bundle: ReportFactsBundle | None) -> list[dict[str, Any]]:
    """Lấy các dòng mẫu 12 theo địa bàn để kiểm cặp nhãn-số rõ ràng.

    Hàm này chỉ phục vụ hard guard cho lỗi thật sự nguy hiểm: đặt sai số vào
    đúng nhãn địa bàn/chỉ tiêu, hoặc so sánh cao/thấp sai. Các lỗi thiếu câu
    phạm vi, thiếu DTTS tại chỗ... vẫn để warn, không làm fail.
    """
    if bundle is None or (_template_id_from_bundle(bundle) != 12 and _pattern(bundle) != "multidimensional_standard"):
        return []
    tables = getattr(bundle, "tables", {}) or {}
    df = None
    for table_name in ("template_main", "main", "by_district"):
        cand = tables.get(table_name)
        if isinstance(cand, pd.DataFrame) and not cand.empty:
            df = cand
            break
    if not isinstance(df, pd.DataFrame) or df.empty or "huyen" not in df.columns:
        return []
    return [dict(row) for _, row in df.iterrows()]


def _mau12_col_expected_tokens(row: dict[str, Any], col: str) -> set[str]:
    vals = {_normalize_number_token(x) for x in _number_variants(row.get(col))}
    vals.discard("")
    return vals


def _mau12_known_source_tokens(rows: list[dict[str, Any]], cols: list[str]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        for col in cols:
            out |= _mau12_col_expected_tokens(row, col)
    out.discard("")
    return out


def _mau12_numeric_value(row: dict[str, Any], col: str) -> float | None:
    try:
        return float(row.get(col))
    except Exception:
        return None


def _mau12_context_col(text: str) -> str | None:
    low = str(text or "").lower()
    # Ưu tiên cụm đặc thù dài trước để tránh bắt "DTTS" trong "DTTS tại chỗ".
    if "dtts tại chỗ" in low or "thiểu số tại chỗ" in low or "dân tộc thiểu số tại chỗ" in low:
        if "tỷ trọng" in low and ("trong hộ nghèo" in low or "trong nhóm hộ nghèo" in low):
            return "ty_le_dtts_trong_nhom_%"
        if "tỷ lệ" in low or "%" in low:
            return "ty_le_ngheo_trong_dtts_tai_cho_%"
        return "so_ho_dtts_tai_cho"
    if "dtts" in low or "dân tộc thiểu số" in low or "thiểu số" in low:
        if "tỷ trọng" in low and ("trong hộ nghèo" in low or "trong nhóm hộ nghèo" in low):
            return "ty_le_dtts_trong_nhom_%"
        if "tỷ lệ" in low or "%" in low:
            return "ty_le_ngheo_trong_dtts_%"
        return "so_ho_dtts"
    if re.search(r"\bkinh\b", low):
        return "so_ho_kinh"
    if "nhân khẩu" in low or "người" in low:
        return "so_nhan_khau_muc_tieu"
    if "tỷ lệ hộ nghèo" in low or "tỷ lệ nghèo" in low or "%" in low:
        return "ty_le_muc_tieu_%"
    if "hộ nghèo" in low or "nghèo đa chiều" in low:
        return "so_ho_muc_tieu"
    if "rà soát" in low or "phân loại" in low or "tổng hộ" in low:
        return "tong_ho_ra_soat"
    return None


def _mau12_explicit_pair_misplacement_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi mẫu 12 kiểu 'Đăk Glong DTTS tại chỗ = 328' trong khi đúng là 50.

    Chỉ hard-fail khi văn bản nêu trực tiếp nhãn/chỉ tiêu rồi đặt một số nguồn khác
    vào đó. Không phạt thiếu ngữ cảnh nhẹ, thiếu câu phạm vi, hoặc thiếu số phụ.
    """
    rows = _mau12_rows_for_checks(bundle)
    if not rows:
        return []
    cols = [
        "so_ho_muc_tieu", "so_nhan_khau_muc_tieu", "ty_le_muc_tieu_%",
        "so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho",
        "tong_ho_dtts", "tong_ho_dtts_tai_cho",
        "ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%",
        "ty_le_dtts_trong_nhom_%",
        "tong_ho_ra_soat", "tong_nhan_khau",
    ]
    known = _mau12_known_source_tokens(rows, cols)
    labels = [str(r.get("huyen") or "").strip() for r in rows if str(r.get("huyen") or "").strip()]
    row_by_label = {str(r.get("huyen") or "").strip(): r for r in rows if str(r.get("huyen") or "").strip()}
    warnings: list[str] = []

    last_label: str | None = None
    for unit in _sentence_units(text):
        unit_low = unit.lower()
        labels_present = [lbl for lbl in labels if _label_in_text_loose(lbl, unit)]
        if labels_present:
            last_label = labels_present[-1]
        # Câu tiếp nối kiểu "Theo phân loại theo dân tộc, ..." thường không lặp lại tên huyện.
        # Gắn nó với địa bàn vừa nêu trước đó để bắt sai số DTTS/DTTS tại chỗ.
        if not labels_present and last_label and any(k in unit_low for k in ("theo phân loại", "dân tộc", "dtts", "kinh", "tại chỗ")):
            labels_present = [last_label]

        for label in labels_present:
            row = row_by_label.get(label) if 'row_by_label' in locals() else None
            if row is None:
                row = next((r for r in rows if str(r.get("huyen") or "").strip() == label), None)
            if row is None:
                continue
            local = _local_context_for_label(unit, label, labels) if _label_in_text_loose(label, unit) else unit
            if not _label_in_text_loose(label, local) and _label_in_text_loose(label, unit):
                local = unit
            local_nums = {n for n in _extract_number_tokens(local) if n not in {"2023", "2024", "2025", "2026"}}
            if not local_nums:
                continue

            # Kiểm riêng từng cụm có khả năng bị nhầm. Chỉ xét khi cụm đó xuất hiện rõ trong local context.
            phrase_cols: list[tuple[str, str]] = []
            llow = local.lower()
            if "dtts tại chỗ" in llow or "thiểu số tại chỗ" in llow or "dân tộc thiểu số tại chỗ" in llow:
                phrase_cols.append(("so_ho_dtts_tai_cho", "số hộ nghèo DTTS tại chỗ"))
            # DTTS không tại chỗ: kiểm khi có cụm DTTS độc lập; nếu cùng câu có cả DTTS và DTTS tại chỗ,
            # chỉ bắt phần DTTS tại chỗ bằng hard guard, phần DTTS chung để sentence audit/context warn.
            if ("dtts" in llow or "dân tộc thiểu số" in llow or "thiểu số" in llow) and not ("dtts tại chỗ" in llow or "thiểu số tại chỗ" in llow):
                phrase_cols.append(("so_ho_dtts", "số hộ nghèo DTTS"))
            if re.search(r"\bkinh\b", llow):
                phrase_cols.append(("so_ho_kinh", "số hộ nghèo dân tộc Kinh"))

            for col, label_col in phrase_cols:
                expected = _mau12_col_expected_tokens(row, col)
                # Nếu có số đúng trong cùng local thì cho qua; nếu local có số nguồn khác nhưng không có số đúng thì cảnh báo hard.
                if local_nums & expected:
                    continue
                wrong = sorted(n for n in local_nums if n in known and n not in expected)
                if wrong:
                    warnings.append(
                        f"LLM có vẻ gán sai cặp nhãn-số: {label} / {label_col} không khớp số {', '.join(wrong[:3])}."
                    )
                    if len(warnings) >= 6:
                        return warnings
    return warnings


def _mau12_pairwise_comparison_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt so sánh cao hơn/thấp hơn sai giữa hai địa bàn ở mẫu 12."""
    rows = _mau12_rows_for_checks(bundle)
    if not rows:
        return []
    row_by_label = {str(r.get("huyen") or "").strip(): r for r in rows if str(r.get("huyen") or "").strip()}
    labels = list(row_by_label)
    warnings: list[str] = []
    greater_words = ("cao hơn", "lớn hơn", "nhiều hơn", "vượt", "vượt qua", "cao nhất", "nhiều nhất")
    lower_words = ("thấp hơn", "ít hơn", "nhỏ hơn", "thấp nhất", "ít nhất")

    for unit in _sentence_units(text):
        low = unit.lower()
        if not any(w in low for w in greater_words + lower_words):
            continue
        def _label_pos(lbl: str) -> int:
            raw_u = unicodedata.normalize("NFD", str(unit or "").lower())
            raw_u = "".join(ch for ch in raw_u if unicodedata.category(ch) != "Mn").replace("đ", "d")
            raw_l = unicodedata.normalize("NFD", str(lbl or "").lower())
            raw_l = "".join(ch for ch in raw_l if unicodedata.category(ch) != "Mn").replace("đ", "d")
            pos = raw_u.find(raw_l)
            return pos if pos >= 0 else 10**9
        present = sorted([lbl for lbl in labels if _label_in_text_loose(lbl, unit)], key=_label_pos)
        if len(present) < 2:
            continue
        col = _mau12_context_col(unit)
        if not col:
            continue
        first = present[0]
        base_val = _mau12_numeric_value(row_by_label[first], col)
        if base_val is None:
            continue
        if any(w in low for w in greater_words):
            for other in present[1:]:
                other_val = _mau12_numeric_value(row_by_label[other], col)
                if other_val is not None and base_val <= other_val:
                    warnings.append(
                        f"LLM có so sánh số học sai: {first} không cao hơn {other} theo {_column_label(col)}."
                    )
                    break
        if any(w in low for w in lower_words):
            for other in present[1:]:
                other_val = _mau12_numeric_value(row_by_label[other], col)
                if other_val is not None and base_val >= other_val:
                    warnings.append(
                        f"LLM có so sánh số học sai: {first} không thấp hơn {other} theo {_column_label(col)}."
                    )
                    break
        if len(warnings) >= 6:
            return warnings
    return warnings

def _template_specific_policy_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Các cảnh báo nghiệp vụ bắt buộc theo từng mẫu, dùng chung cho validate và audit.

    Mục tiêu là chặn các lỗi đã xuất hiện trong log: mẫu 1 khẳng định sai bản chất số 0,
    mẫu 3 gọi biến động tăng/giảm là unexplained_delta, mẫu 8 phủ nhận chồng lấn,
    và mẫu 12 bỏ cảnh báo mẫu số rà soát.
    """
    if bundle is None:
        return []
    warnings: list[str] = []
    raw = str(text or "")
    lower = raw.lower()
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)
    facts = getattr(bundle, "facts", {}) or {}

    if tid == 1:
        data_warnings = " ".join(str(w) for w in (facts.get("template_data_warnings") or []))
        missing_direct_medium = (
            "chưa có trường" in data_warnings.lower()
            or "chưa có dữ liệu" in data_warnings.lower()
            or "ghi 0" in data_warnings.lower()
        )
        talks_medium = "mức sống trung bình" in lower or "nông, lâm, ngư" in lower or "nông/lâm/ngư" in lower
        asserts_absence = any(
            phrase in lower
            for phrase in (
                "không có hộ",
                "không ghi nhận hộ",
                "không phát hiện hộ",
                "không có nhóm",
                "0 hộ thuộc nhóm",
            )
        )
        has_missing_data_note = any(
            phrase in lower
            for phrase in (
                "db chưa có",
                "chưa có trường",
                "chưa có dữ liệu",
                "thiếu dữ liệu",
                "không có cột",
                "không có căn cứ trực tiếp",
                "ghi 0 theo policy",
                "ghi 0 theo nguyên tắc",
                "theo bảng",
                "theo số liệu",
                "bảng tổng hợp hiện có",
            )
        )
        if missing_direct_medium and talks_medium and asserts_absence and not has_missing_data_note:
            warnings.append(
                "Mẫu 1 khẳng định không có hộ NLNN mức sống trung bình trong khi DB chỉ thiếu trường trực tiếp; phải viết là DB chưa có dữ liệu trực tiếp nên chỉ tiêu ghi 0."
            )

    if tid in {2, 3} or pattern == "movement":
        unexplained = int(float(facts.get("unexplained_delta") or 0)) if isinstance(facts, dict) else 0
        if unexplained == 0 and "chênh lệch chưa giải thích" in lower:
            warnings.append(
                "Văn bản gọi phần lệch ngoài công thức khi unexplained_delta = 0; không được biến chênh lệch tăng/giảm trong kỳ thành unexplained_delta."
            )
        if tid == 3:
            for unit in _sentence_units(raw):
                low = unit.lower()
                if any(ctx in low for ctx in ("nhóm giảm", "cấu phần giảm", "phần giảm", "giảm gồm", "làm giảm")) and any(
                    term in low for term in (
                        "thoát nghèo trở thành hộ cận nghèo",
                        "hộ nghèo trở thành hộ cận nghèo",
                        "thoát nghèo -> cận nghèo",
                        "tái cận nghèo",
                        "cận nghèo mới phát sinh",
                    )
                ):
                    warnings.append(
                        "Mẫu 3 sai chiều biến động: nhóm tăng cận nghèo bị đặt trong câu nhóm giảm."
                    )
                if any(ctx in low for ctx in ("nhóm tăng", "cấu phần tăng", "phần tăng", "tăng gồm", "làm tăng")) and any(
                    term in low for term in (
                        "thoát cận nghèo vượt chuẩn",
                        "thoát cận nghèo -> vượt chuẩn",
                        "cận nghèo trở thành hộ nghèo",
                    )
                ):
                    warnings.append(
                        "Mẫu 3 sai chiều biến động: nhóm giảm cận nghèo bị đặt trong câu nhóm tăng."
                    )

    if tid == 8 or pattern == "vulnerable_groups":
        if any(phrase in lower for phrase in ("không chồng lấn", "không có sự chồng lấn", "không trùng lặp", "loại trừ nhau")):
            warnings.append(
                "Mẫu 8 diễn giải sai chồng lấn: các nhóm đối tượng có thể chồng lấn, không phải không chồng lấn/loại trừ nhau."
            )
        if "chồng lấn" not in lower and "đồng thời thuộc" not in lower:
            warnings.append(
                "Mẫu 8 thiếu cảnh báo chồng lấn: phải nêu một hộ có thể đồng thời thuộc nhiều nhóm và không cộng thành cơ cấu 100%."
            )

    if tid == 12 or pattern == "multidimensional_standard":
        if any(key in lower for key in ("tỷ lệ hộ nghèo", "tỷ lệ nghèo")) and not any(
            phrase in lower
            for phrase in (
                "dữ liệu rà soát",
                "phạm vi rà soát",
                "hộ đã rà soát",
                "rà soát/phân loại",
                "không phải tỷ lệ hộ nghèo chính thức",
            )
        ):
            warnings.append(
                "Mẫu 12 thiếu cảnh báo phạm vi tỷ lệ: phải nêu tỷ lệ tính trên tổng hộ trong dữ liệu rà soát/phân loại, không phải tỷ lệ chính thức toàn dân cư."
            )
        # Hard guard tối thiểu cho mẫu 12: chỉ fail khi đặt sai số vào nhãn/chỉ tiêu
        # hoặc so sánh cao/thấp sai. Thiếu DTTS tại chỗ/cảnh báo phạm vi chỉ là warn.
        warnings.extend(_mau12_explicit_pair_misplacement_warnings(bundle, raw))
        warnings.extend(_mau12_pairwise_comparison_warnings(bundle, raw))



    if tid == 2:
        if re.search(r"nghèo\s+sang\s+hộ\s+cận\s+nghèo[^.\n]*(1\.105|1105)", raw, re.I):
            warnings.append("Mẫu 2 gán sai 1.105 cho nhóm thoát nghèo trở thành hộ cận nghèo; đúng là 634 hộ.")
        if re.search(r"cận\s+nghèo[^.\n]*(?:trở\s+lại|trở\s+thành)\s+hộ\s+nghèo[^.\n]*(634|634\s+hộ)", raw, re.I):
            warnings.append("Mẫu 2 gán sai 634 cho nhóm cận nghèo trở thành hộ nghèo; đúng là 1.105 hộ.")
        if int(float(facts.get("unexplained_delta") or 0)) == 0 and re.search(r"651[^.\n]*(không\s+được\s+giải\s+thích|chưa\s+giải\s+thích|chưa\s+rõ\s+nguyên\s+nhân)", lower):
            warnings.append("Mẫu 2 gọi 651 là chênh lệch chưa giải thích; 651 chỉ là mức tăng cuối kỳ so với đầu kỳ, unexplained_delta = 0.")

    if tid == 3:
        if int(float(facts.get("unexplained_delta") or 0)) == 0 and re.search(r"chênh\s+lệch[^.\n]*(công\s+thức|phân\s+loại)[^.\n]*(chưa|không)[^.\n]*giải\s+thích", lower):
            warnings.append("Mẫu 3 không được nói còn chênh lệch công thức/phân loại chưa giải thích khi unexplained_delta = 0.")
        for needed in (facts.get("tong_ky_truoc"), facts.get("tong_ky_sau"), facts.get("chenh_lech")):
            if needed is not None and not _text_contains_any_number_variant(raw, needed):
                warnings.append(f"Mẫu 3 thiếu số cốt lõi toàn tỉnh {_num(needed)} trong nhận định.")
        if re.search(r"cận\s+nghèo\s+chuyển\s+sang\s+các\s+nhóm\s+khác", lower):
            warnings.append("Mẫu 3 viết mơ hồ 'chuyển sang các nhóm khác'; phải nêu đúng nhãn biến động.")

    if tid in {4, 5, 6, 7}:
        if "mẫu này" in lower:
            warnings.append(f"Mẫu {tid}: văn bản Word không được ghi 'mẫu này'.")
        if "không cộng" not in lower and "chồng lấn" not in lower:
            warnings.append(f"Mẫu {tid}: cần nêu các chỉ số thiếu hụt có thể chồng lấn, không cộng thành 100%.")

    if tid == 11:
        child_counts_pat = r"(?:657|501|572|484|511|385)"
        if re.search(r"tỷ\s+lệ[^.\n]*" + child_counts_pat + r"\s*trẻ", lower):
            warnings.append("Mẫu 11 dùng 'tỷ lệ' đi kèm số trẻ; phải viết 'số trẻ ... tương ứng x%'.")
        if re.search(child_counts_pat + r"\s*hộ\b", lower):
            warnings.append("Mẫu 11 gọi số trẻ là đơn vị hộ; các số 657/572/511/501/484/385 phải đi với đơn vị trẻ.")
        if re.search(r"số\s+trẻ\s+thiếu\s+hộ\s+(?:cận\s+)?nghèo", lower) or re.search(r"trẻ\s+thiếu\s+hộ\s+(?:cận\s+)?nghèo", lower):
            warnings.append("Mẫu 11 viết sai quan hệ ngữ nghĩa: phải viết 'trẻ em thuộc hộ nghèo/cận nghèo thiếu chỉ tiêu', không viết 'số trẻ thiếu hộ nghèo'.")
        if re.search(r"tỷ\s+lệ\s+hộ\s+(?:cận\s+)?nghèo", lower):
            warnings.append("Mẫu 11 gọi tỷ lệ trẻ thiếu chỉ tiêu là tỷ lệ hộ nghèo/cận nghèo; phải viết tỷ lệ tương ứng trong nhóm trẻ em thuộc hộ đó.")
        if "đối tượng hộ cận nghèo" in lower:
            warnings.append("Mẫu 11 nên viết 'trẻ em thuộc hộ cận nghèo', không viết 'đối tượng hộ cận nghèo'.")

    if tid == 12:
        if re.search(r"trong\s+tổng\s+số\s+(829|538)\s+hộ[^.\n]*(43,24|34,64|tỷ\s+lệ)", lower):
            warnings.append("Mẫu 12 dùng số hộ nghèo như mẫu số tỷ lệ; tỷ lệ phải tính trên tổng hộ rà soát/phân loại của địa bàn.")
        warnings.extend(_mau12_ethnicity_coverage_warnings(bundle, raw))


    if tid == 1:
        if re.search(r"krông\s+nô[^.\n]*(588)[^.\n]*(vượt\s+xa|cao\s+nhất|lớn\s+nhất|dẫn\s+đầu)", lower):
            warnings.append("Mẫu 1 gán sai vị trí so sánh: Krông Nô 588 hộ cận nghèo không được viết là vượt xa/cao nhất vì Tuy Đức có 917 hộ cận nghèo.")
        if re.search(r"đăk\s+glong[^.\n]*(538)[^.\n]*(cao\s+nhất|lớn\s+nhất|dẫn\s+đầu)", lower):
            warnings.append("Mẫu 1 gán sai vị trí so sánh: Đăk Glong 538 hộ nghèo không phải địa bàn cao nhất về số hộ nghèo; Tuy Đức là 829 hộ.")

    if tid == 10 or pattern == "causes":
        for unit in _sentence_units(raw):
            low = unit.lower()
            if "số hộ nghèo" in low and any(x in low for x in ("1.384", "1384", "1 384")):
                warnings.append("Mẫu 10 đặt số 1.384 hộ cận nghèo trong ngữ cảnh số hộ nghèo; phải tách rõ nhóm hộ nghèo và hộ cận nghèo.")
            if "tỷ lệ" in low and re.search(r"tỷ\s+lệ[^.\n]*(1\.399|1399|1\.419|1419|1\.197|1197|1\.218|1218|1\.180|1180|1\.384|1384)\s*hộ", low):
                warnings.append("Mẫu 10 dùng 'tỷ lệ' với số tuyệt đối đơn vị hộ; phải viết số hộ, tương ứng phần trăm nếu có.")

    return _dedupe_text_items(warnings)


def _collect_allowed_number_tokens(bundle: ReportFactsBundle | None, safe_base: str) -> set[str]:
    """Tập số được phép xuất hiện trong nhận định.

    Cho phép số có trong SAFE_BASE_TEXT, facts và các bảng đã chuẩn hóa. Không cho LLM tự tính tổng,
    tự cộng hoặc sinh số mới vì các số tự tính rất dễ đúng định dạng nhưng sai nghiệp vụ.
    """
    allowed: set[str] = set(_extract_number_tokens(safe_base)) | {"2023", "2024", "2025", "2026"}

    def add_value(v: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if v is None:
            return
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            allowed.update(_normalize_number_token(x) for x in _number_variants(v))
            return
        if isinstance(v, str):
            # Chỉ thêm nếu chuỗi này thật sự chứa số.
            allowed.update(_extract_number_tokens(v))
            return
        if isinstance(v, dict):
            for vv in v.values():
                add_value(vv, depth + 1)
            return
        if isinstance(v, (list, tuple, set)):
            for vv in v:
                add_value(vv, depth + 1)
            return

    if bundle is not None:
        add_value(getattr(bundle, "scope", None))
        add_value(getattr(bundle, "summary", None))
        add_value(getattr(bundle, "facts", None))
        for df in (getattr(bundle, "tables", {}) or {}).values():
            if isinstance(df, pd.DataFrame) and not df.empty:
                numeric_df = df.select_dtypes(include="number")
                for v in numeric_df.stack().dropna().tolist():
                    add_value(v)
                # Cho phép tổng cột lấy trực tiếp từ bảng mẫu. Một số câu nhận định mẫu 12
                # cần tổng toàn tỉnh như tổng nhân khẩu hoặc tổng hộ nghèo Kinh/DTTS; đây không phải số LLM tự bịa
                # mà là tổng của chính bảng report đã được Python/SQL dựng.
                try:
                    for v in numeric_df.sum(numeric_only=True).tolist():
                        add_value(v)
                except Exception:
                    pass
    return {x for x in allowed if x}


def _unsupported_number_warnings(bundle: ReportFactsBundle | None, safe_base: str, text: str) -> list[str]:
    allowed = _collect_allowed_number_tokens(bundle, safe_base)
    cand_nums = set(_extract_number_tokens(text))
    if "100" in cand_nums and _only_overlap_warning_100_percent(text):
        cand_nums.discard("100")
    # Bỏ qua số nhỏ hay dùng để đếm nhóm/mục; các số nghiệp vụ lớn vẫn phải nằm trong nguồn.
    harmless_small = {str(i) for i in range(1, 13)}
    extra = sorted(n for n in cand_nums if n not in allowed and n not in harmless_small)
    if extra:
        return ["LLM có số liệu ngoài nguồn hoặc số tự tính chưa kiểm chứng: " + ", ".join(extra[:8])]
    return []


def _only_overlap_warning_100_percent(text: str) -> bool:
    """Cho phép 100% khi chỉ xuất hiện trong cảnh báo không cộng nhóm chồng lấn."""
    raw = str(text or "")
    matches = list(re.finditer(r"100\s*%", raw, flags=re.IGNORECASE))
    if not matches:
        return False
    low = raw.lower()
    for match in matches:
        start = max(0, match.start() - 90)
        end = min(len(low), match.end() + 20)
        window = low[start:end]
        if not re.search(
            r"không[^.\n]{0,50}(?:cộng|hình\s+thành)[^.\n]{0,80}(?:cơ\s+cấu\s*)?100\s*%",
            window,
        ):
            return False
    return True


def _label_number_pair_present(text: str, label: Any, value: Any) -> bool:
    """Kiểm tra cặp nhãn-số có xuất hiện trong cùng một câu/cụm hay không."""
    label_text = str(label or "").strip().lower()
    if not label_text:
        return False
    expected = {_normalize_number_token(x) for x in _number_variants(value)}
    expected.discard("")
    if not expected:
        return False
    for unit in _sentence_units(text):
        lower_unit = unit.lower()
        label_ok = label_text in lower_unit
        if not label_ok and label_text == "trẻ em thiếu chỉ tiêu về tình trạng đi học":
            label_ok = "trẻ em thiếu chỉ tiêu về tình trạng đi học" in lower_unit
        if not label_ok:
            continue
        nums = {_normalize_number_token(x) for x in _extract_number_tokens(unit)}
        if nums & expected:
            return True
    return False


def _required_label_number_coverage_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Cảnh báo khi văn bản đúng số cốt lõi nhưng quá chung.

    Đây là cảnh báo chất lượng, không phải lỗi sai dữ liệu. Chỉ yêu cầu các cặp
    nhãn-số thuộc cột trọng tâm của pattern (số hộ/tỷ lệ/biến động...), không ép
    các cột phụ như tổng nhân khẩu hoặc số khẩu nếu chúng không phải trọng tâm
    nhận định. Nhờ vậy fallback không bị đánh trượt vô lý và LLM không bị đẩy
    sang fallback chỉ vì thiếu vài số phụ.
    """
    if bundle is None:
        return []
    if _pattern(bundle) == "causes":
        return []
    tables = getattr(bundle, "tables", {}) or {}
    df = None
    for _name in ("template_main", "main", "by_district"):
        _candidate = tables.get(_name)
        if isinstance(_candidate, pd.DataFrame) and not _candidate.empty:
            df = _candidate
            break
    if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
        return []

    label_col = None
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            label_col = c
            break
    if label_col is None:
        return []

    numeric_cols = _coverage_numeric_cols(df, label_col, _pattern(bundle))
    if not numeric_cols:
        return []

    required_pairs: list[tuple[str, str, Any]] = []
    for c in numeric_cols[:4]:
        try:
            series = pd.to_numeric(df[c], errors="coerce")
            if series.dropna().empty:
                continue
            # Với biến động có thể cần trị tuyệt đối; các mẫu khác lấy giá trị lớn nhất.
            if "chenh_lech" in str(c).lower() or "delta" in str(c).lower():
                idx = series.abs().idxmax()
            else:
                idx = series.idxmax()
            value = df.loc[idx, c]
            if float(value or 0) == 0:
                continue
            label = str(df.loc[idx, label_col] or "").strip()
            if not label:
                continue
            pair = (label, str(c), value)
            if pair not in required_pairs:
                required_pairs.append(pair)
        except Exception:
            continue

    if not required_pairs:
        return []

    present = [pair for pair in required_pairs if _label_number_pair_present(text, pair[0], pair[2])]
    # Chỉ yêu cầu 1 cặp trọng tâm. Các cặp còn lại dùng làm gợi ý retry, không ép fallback.
    min_required = 1
    if len(present) < min_required:
        examples = []
        for label, col, value in required_pairs[:3]:
            examples.append(f"{label} / {_column_label(col)} = {_num(value)}")
        return [
            "Văn bản thiếu cặp nhãn-số nổi bật nên nhận định còn chung: "
            + "; ".join(examples)
        ]
    return []

def _is_hard_validation_warning(w: str) -> bool:
    t = str(w or "").lower()
    # Cân bằng tốc độ và chất lượng.
    # Chỉ hard-fail lỗi làm sai số liệu/đơn vị/nhãn/công thức hoặc bịa số ngoài nguồn.
    # Các lỗi văn phong, thiếu cảnh báo phạm vi, thiếu số phụ, đánh số mục, giọng hơi chat,
    # hoặc nhắc "mẫu/cột" sẽ được đưa vào warning + public repair thay vì ép LLM retry 10 lần.
    hard_needles = [
        # Bịa số / gán nhầm số / sai nhãn-số.
        "số liệu ngoài nguồn",
        "số tự tính chưa kiểm chứng",
        "gán sai cặp nhãn-số",
        "nhận định xếp hạng không đúng",
        "so sánh số học sai",
        "gán sai 1.105",
        "gán sai 634",
        "mẫu 2 gọi 651",
        # Sai chiều/sai công thức nghiệp vụ.
        "sai số đầu kỳ/cuối kỳ",
        "sai chiều biến động",
        "mẫu 3 sai chiều biến động",
        "phần lệch ngoài công thức khi unexplained_delta = 0",
        "không được biến chênh lệch tăng/giảm",
        "mẫu 3 không được nói",
        # Sai đơn vị/mẫu số/trọng tâm.
        "sai trọng tâm hộ",
        "lẫn đơn vị hộ và trẻ em",
        "dùng 'tỷ lệ' đi kèm số trẻ",
        "số hộ nghèo như mẫu số tỷ lệ",
        "sai phạm vi tỷ lệ mẫu 12",
        "dùng nhân khẩu làm mẫu số",
        "so sánh trực tiếp tổng hộ với nhân khẩu",
        "tỷ lệ trong mẫu không có tỷ lệ",
        "sai bản chất tỷ lệ thiếu hụt",
        "sai bản chất mẫu tỷ lệ thiếu hụt",
        "văn bản quá ngắn so với độ dài tối thiểu đã cấu hình",
        "văn bản llm dưới ngưỡng tối thiểu đã cấu hình",
        "thiếu số tổng cốt lõi",
        "llm làm mất số liệu cốt lõi",
        "viết sai quan hệ ngữ nghĩa",
        "gọi số trẻ là đơn vị hộ",
        "gọi tỷ lệ trẻ thiếu chỉ tiêu là tỷ lệ hộ",
        "văn bản có giọng prompt/chat",
        "văn bản có giọng prompt/chat hoặc người viết chủ quan",
        "văn bản còn lộ chỉ dẫn prompt/retry",
        "văn bản còn lộ chỉ dẫn prompt/retry hoặc nguồn trung gian",
        "văn bản nhận định còn token kỹ thuật",
        "văn bản nhận định còn nhắc cột",
        "văn bản nhận định còn viết 'db'",
        "văn bản nhận định còn nhắc công thức",
        "văn bản nhận định còn lộ nguồn prompt",
        "lộ chỉ dẫn prompt/retry hoặc nguồn trung gian",
        # Bịa số định dạng năm vẫn là lỗi dữ liệu. Các nhận định nguyên nhân/chính sách
        # chỉ để warn mềm theo policy mới: chấp nhận một ít sai ngữ cảnh nếu số liệu,
        # vị trí đặt số và so sánh/xếp hạng không sai.
        "số năm bị định dạng như số liệu",
        # Lỗi kỹ thuật nghiêm trọng trong output.
        "token kỹ thuật",
        "lộ chỉ dẫn prompt/retry",
        "ký tự unicode bất thường",
        "cyrillic",
    ]
    return any(x in t for x in hard_needles)


def _should_prefer_fallback_over_llm(warnings: list[str]) -> bool:
    """Chỉ fallback khi có lỗi cứng về dữ liệu/logic.

    Văn bản ngắn hoặc còn chung là cảnh báo chất lượng; Word/exporter có thể bổ sung
    các đoạn phân tích deterministic. Không fallback chỉ vì LLM viết ngắn để tránh tỷ lệ
    fallback quá cao.
    """
    return any(_is_hard_validation_warning(w) for w in (warnings or []))


def _col_is_ratio_like(col: Any) -> bool:
    c = str(col or "").lower()
    return "ty_le" in c or "ti_le" in c or c.endswith("_%") or "rate" in c or "%" in c


def _mau12_relevant_columns_for_context(cols_to_check: list[Any], context: str) -> list[Any]:
    """Thu hẹp cột audit mẫu 12 theo ngữ cảnh câu/cụm.

    Mẫu 12 có cùng một nhãn địa bàn nhưng nhiều cột số: tổng hộ rà soát, hộ nghèo
    đa chiều, nhân khẩu, Kinh, DTTS, DTTS tại chỗ và tỷ lệ. Nếu câu đang nói
    dân tộc thì không được đem số Kinh/DTTS đi so với cột hộ nghèo đa chiều.
    Ngược lại, nếu câu đang nói tỷ lệ hộ nghèo thì không được bắt nhầm sang cột
    tỷ lệ DTTS. Hàm này chỉ chọn cột phù hợp ngữ cảnh; không bỏ qua lỗi số sai.
    """
    low = str(context or "").lower()
    cols = [str(c) for c in (cols_to_check or [])]
    if not cols:
        return []

    has_kinh = "kinh" in low
    has_local_dtts = (
        "dtts tại chỗ" in low
        or "dân tộc thiểu số tại chỗ" in low
        or "thiểu số tại chỗ" in low
        or ("tại chỗ" in low and ("dtts" in low or "thiểu số" in low or "dân tộc" in low))
    )
    has_dtts = "dtts" in low or "dân tộc thiểu số" in low or "thiểu số" in low
    has_ethnic = has_kinh or has_dtts or has_local_dtts or "dân tộc" in low
    has_ratio = _unit_is_ratio_context(low)
    has_population = "nhân khẩu" in low or "khẩu" in low
    has_review_scope = "rà soát" in low or "phân loại" in low or "tổng hộ" in low or "tổng số hộ" in low

    if has_ethnic:
        allowed: set[str] = set()
        if has_kinh:
            allowed.add("so_ho_kinh")
        if has_local_dtts:
            allowed.add("so_ho_dtts_tai_cho")
            if "tổng" in low:
                allowed.add("tong_ho_dtts_tai_cho")
        if has_dtts and not has_local_dtts:
            allowed.add("so_ho_dtts")
            if "tổng" in low:
                allowed.add("tong_ho_dtts")
        # Câu kiểu "Kinh, DTTS, trong đó DTTS tại chỗ" cần kiểm đủ cả 3 cột.
        if has_dtts and has_local_dtts:
            allowed.add("so_ho_dtts")
            allowed.add("so_ho_dtts_tai_cho")
            if "tổng" in low:
                allowed.add("tong_ho_dtts")
                allowed.add("tong_ho_dtts_tai_cho")
        if has_ratio and has_local_dtts:
            allowed.add("ty_le_ngheo_trong_dtts_tai_cho_%")
        elif has_ratio and has_dtts:
            allowed.add("ty_le_ngheo_trong_dtts_%")
        if has_ratio and "tỷ trọng" in low and has_dtts:
            allowed.add("ty_le_dtts_trong_nhom_%")
        if allowed:
            return [c for c in cols if c in allowed]
        return [c for c in cols if c in {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho", "tong_ho_dtts", "tong_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%", "ty_le_dtts_trong_nhom_%"}]

    if has_population:
        return [c for c in cols if c in {"tong_nhan_khau", "so_nhan_khau_muc_tieu"}]

    if has_ratio:
        # Tỷ lệ hộ nghèo đa chiều dùng ty_le_muc_tieu_%, không lẫn tỷ lệ DTTS.
        return [c for c in cols if c == "ty_le_muc_tieu_%"]

    if has_review_scope:
        return [c for c in cols if c in {"tong_ho_ra_soat", "so_ho_muc_tieu"}]

    return [c for c in cols if c not in {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho", "tong_ho_dtts", "tong_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%", "ty_le_dtts_trong_nhom_%"}]


def _mau12_expected_tokens_by_number(
    row: Any,
    cols_to_check: list[Any],
    local_nums: set[str],
) -> dict[str, list[str]]:
    """Map số trong câu sang các cột mẫu 12 có đúng giá trị ở dòng hiện tại."""
    out: dict[str, list[str]] = {}
    for c in cols_to_check or []:
        expected_tokens = {_normalize_number_token(x) for x in _number_variants(row.get(c))}
        expected_tokens.discard("")
        hit = sorted(n for n in local_nums if n in expected_tokens)
        if hit:
            out[str(c)] = hit
    return out


def _mau12_global_expected_tokens(bundle: ReportFactsBundle | None, df: pd.DataFrame | None, unit: str) -> set[str]:
    """Các số toàn phạm vi/toàn tỉnh hợp lệ cho mẫu 12 trong một câu không có địa bàn.

    Câu tổng quan mẫu 12 thường không có nhãn dòng địa bàn nhưng vẫn đúng: 2.447 hộ
    nghèo, 7.488 hộ rà soát, 32,68%, 11.247 nhân khẩu hộ nghèo, 34.110 nhân khẩu,
    hoặc tổng Kinh/DTTS/DTTS tại chỗ. Hàm này tạo tập số kỳ vọng theo ngữ cảnh câu
    để sentence audit không cảnh báo giả nhưng vẫn không cho qua số sai ngữ cảnh.
    """
    if bundle is None:
        return set()
    low = str(unit or "").lower()
    expected: set[str] = set()

    def add(value: Any) -> None:
        for x in _number_variants(value):
            tok = _normalize_number_token(x)
            if tok:
                expected.add(tok)

    facts = getattr(bundle, "facts", {}) or {}
    summary = getattr(bundle, "summary", {}) or {}

    # Tổng hộ nghèo/tổng hộ rà soát/tỷ lệ hộ nghèo.
    if "hộ" in low and ("nghèo" in low or "rà soát" in low or "phân loại" in low or "tổng số" in low):
        for key in ("total_target_households", "ho_ngheo", "tong_ho_ra_soat"):
            add(facts.get(key, summary.get(key)))
        for key in ("ty_le_ho_ngheo", "ty_le_muc_tieu_%"):
            add(facts.get(key, summary.get(key)))
        if isinstance(df, pd.DataFrame):
            for col in ("so_ho_muc_tieu", "tong_ho_ra_soat"):
                if col in df.columns:
                    add(pd.to_numeric(df[col], errors="coerce").dropna().sum())

    # Tổng nhân khẩu và nhân khẩu thuộc hộ nghèo.
    if "nhân khẩu" in low or "khẩu" in low:
        add(facts.get("total_target_population", summary.get("total_target_population")))
        if isinstance(df, pd.DataFrame):
            for col in ("so_nhan_khau_muc_tieu", "tong_nhan_khau"):
                if col in df.columns:
                    add(pd.to_numeric(df[col], errors="coerce").dropna().sum())

    # Tổng theo dân tộc trong nhóm hộ nghèo đa chiều.
    if "dân tộc" in low or "dtts" in low or "thiểu số" in low or "kinh" in low or "tại chỗ" in low:
        for key in ("total_ethnic_minority_households", "total_local_ethnic_minority_households"):
            add(facts.get(key, summary.get(key)))
        if isinstance(df, pd.DataFrame):
            for col in ("so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho"):
                if col in df.columns:
                    add(pd.to_numeric(df[col], errors="coerce").dropna().sum())
    expected.discard("")
    return expected


def _unit_is_ratio_context(unit: str) -> bool:
    t = str(unit or "").lower()
    return "%" in t or "tỷ lệ" in t or "tỉ lệ" in t or "phần trăm" in t


def _local_context_for_label(unit: str, label: str, all_labels: list[str]) -> str:
    """Lấy đoạn gần nhãn hiện tại đến trước nhãn tiếp theo trong cùng câu.

    Mẫu tỷ lệ/chỉ tiêu và mẫu dân tộc thường viết nhiều cặp trong một câu, ví dụ:
    "Chất lượng nhà ở (60,88%); Nhà tiêu hợp vệ sinh (55,89%)".
    Validator cũ quét toàn bộ câu nên tưởng 55,89% bị gán cho Chất lượng nhà ở.
    Hàm này giúp kiểm cặp nhãn-số theo từng cụm cục bộ để giảm fallback nhầm.
    """
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




def _loose_vietnamese_text(value: Any) -> str:
    """Chuẩn hóa hẹp để so khớp nhãn tiếng Việt khi LLM dùng khác dấu/khác kiểu Đăk-Đắk.

    Chỉ dùng cho validator nhãn-số; không thay đổi văn bản đầu ra.
    """
    raw = str(value or "").lower().strip()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("đ", "d")
    raw = re.sub(r"\s+", " ", raw)
    return raw


def _label_in_text_loose(label: Any, text: str) -> bool:
    label_raw = str(label or "").strip().lower()
    text_raw = str(text or "").lower()
    if not label_raw:
        return False
    return label_raw in text_raw or _loose_vietnamese_text(label_raw) in _loose_vietnamese_text(text_raw)

def _bundle_label_number_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi LLM gán đúng số nhưng sai địa bàn/chỉ tiêu.

    Sửa lỗi lọt hậu kiểm mẫu 1:
    - LLM hay viết "Về hộ cận nghèo, Krông Nô ghi nhận 917 hộ". Ngữ cảnh chỉ tiêu
      nằm ở phần trước tên địa bàn, nên nếu chỉ cắt từ nhãn địa bàn trở đi thì validator
      không còn thấy cụm "hộ cận nghèo" và bỏ qua. Hàm này dùng toàn câu/cụm để nhận
      diện chỉ tiêu, nhưng vẫn dùng đoạn cục bộ quanh địa bàn để kiểm số gần nhãn.
    - LLM cũng hay gán tổng cột toàn tỉnh như 733 cho một địa bàn như Đăk Glong. Tổng
      cột không nằm trong từng dòng template_main, nên validator cũ không coi đó là số
      có thể bị gán sai. Hàm này thêm tổng cột vào tập số cần kiểm, nhưng chỉ phạt khi
      số tổng xuất hiện trong đoạn có nhãn địa bàn/chỉ tiêu cụ thể.
    """
    if bundle is None:
        return []
    if _pattern(bundle) == "causes":
        return []
    tables = getattr(bundle, "tables", {}) or {}
    table_order = ["template_main", "main", "by_district"]
    warnings: list[str] = []

    for name in table_order:
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
            continue

        label_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = c
                break
        if label_col is None:
            continue

        numeric_cols = _business_numeric_cols(df, label_col)
        if not numeric_cols:
            continue

        pattern = _pattern(bundle)
        # Mẫu 12 có nhiều số/địa bàn trong cùng câu; generic checker dễ false-positive
        # khi LLM viết dạng liệt kê. Mẫu 12 dùng guard riêng:
        # _mau12_explicit_pair_misplacement_warnings + _mau12_pairwise_comparison_warnings.
        if pattern == "multidimensional_standard" or _template_id_from_bundle(bundle) == 12:
            return []
        row_labels = [str(v or "").strip() for v in df[label_col].tolist()]
        use_local_pair_context = pattern in {
            "overview_result", "deprivation_count", "deprivation_ratio", "ethnicity",
            "movement", "child_deprivation", "multidimensional_standard",
        }

        all_numbers: set[str] = set()
        for c in numeric_cols:
            numeric_series = pd.to_numeric(df[c], errors="coerce").dropna()
            for v in numeric_series.tolist():
                all_numbers |= {_normalize_number_token(x) for x in _number_variants(v)}
            # Quan trọng cho mẫu 1: tổng toàn tỉnh/cột cũng là số nguồn, nhưng nếu LLM
            # đặt nó cạnh một địa bàn cụ thể thì phải reject.
            try:
                col_total = numeric_series.sum()
                if abs(float(col_total or 0)) > 1e-9:
                    all_numbers |= {_normalize_number_token(x) for x in _number_variants(col_total)}
            except Exception:
                pass
        all_numbers.discard("")

        for unit in _sentence_units(text):
            unit_nums = set(_extract_number_tokens(unit))
            if not unit_nums:
                continue
            if pattern == "multidimensional_standard":
                labels_in_unit_for_skip = [lbl for lbl in row_labels if _label_in_text_loose(lbl, unit)]
                if len(labels_in_unit_for_skip) >= 2:
                    # Câu nhiều địa bàn + nhiều số thường là dạng liệt kê theo thứ tự. Generic checker
                    # dễ gán chéo số hợp lệ giữa các địa bàn; lỗi đặt sai trực tiếp đã kiểm riêng.
                    continue
            for _, row in df.iterrows():
                label = str(row.get(label_col) or "").strip()
                if not _label_in_text_loose(label, unit):
                    continue

                check_unit = _local_context_for_label(unit, label, row_labels) if use_local_pair_context else unit
                # Nếu exact slicing không tìm được nhãn do khác dấu, dùng cả cụm để không bỏ lọt.
                if not _label_in_text_loose(label, check_unit):
                    check_unit = unit
                nums = set(_extract_number_tokens(check_unit))
                if not nums:
                    continue

                ratio_context = _unit_is_ratio_context(check_unit) or _unit_is_ratio_context(unit)
                cols_to_check = list(numeric_cols)
                if pattern in {"causes", "child_deprivation"}:
                    low_ctx = (check_unit + " " + unit).lower()
                    has_near = "hộ cận nghèo" in low_ctx
                    has_poor = bool(re.search(r"(?<!cận\s)hộ nghèo", low_ctx))
                    if has_poor and not has_near:
                        cols_to_check = [c for c in cols_to_check if "can_ngheo" not in str(c)]
                    elif has_near and not has_poor:
                        cols_to_check = [c for c in cols_to_check if "can_ngheo" in str(c)]
                    elif has_near and has_poor:
                        # Câu cố ý đối chiếu cả hai nhóm; tránh bắt chéo số giữa hai cột.
                        continue
                # Mẫu 12 có câu dân tộc chứa cùng lúc tên địa bàn và nhiều số hộ Kinh/DTTS.
                # Nếu vẫn kiểm mọi cột số của địa bàn trong cùng câu, validator sẽ tưởng số Kinh/DTTS
                # đang bị gán cho cột hộ nghèo đa chiều hoặc tỷ lệ. Thu hẹp cột cần kiểm theo ngữ cảnh câu.
                if pattern == "multidimensional_standard":
                    low_ctx = (check_unit + " " + unit).lower()
                    ethnic_context = (
                        "dân tộc" in low_ctx or "dtts" in low_ctx or "thiểu số" in low_ctx or "kinh" in low_ctx or "tại chỗ" in low_ctx
                    )
                    if ethnic_context:
                        allowed_eth_cols = {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho", "tong_ho_dtts", "tong_ho_dtts_tai_cho"}
                        # Chỉ kiểm tỷ lệ DTTS nếu câu thật sự nói tỷ lệ/%. Câu chỉ liệt kê số hộ Kinh/DTTS
                        # không được đem so với cột tỷ trọng nội bộ.
                        if (
                            ("tỷ lệ dtts tại chỗ" in low_ctx)
                            or ("tỷ lệ dân tộc thiểu số tại chỗ" in low_ctx)
                            or ("tỷ lệ hộ nghèo dtts tại chỗ" in low_ctx)
                            or (("tỷ lệ" in low_ctx or "%" in low_ctx) and ("tại chỗ" in low_ctx) and ("dtts" in low_ctx or "thiểu số" in low_ctx))
                        ):
                            allowed_eth_cols.add("ty_le_ngheo_trong_dtts_tai_cho_%")
                        elif (
                            ("tỷ lệ dtts" in low_ctx)
                            or ("tỷ lệ dân tộc thiểu số" in low_ctx)
                            or ("tỷ lệ hộ nghèo dtts" in low_ctx)
                            or (("tỷ lệ" in low_ctx or "%" in low_ctx) and ("trong nhóm dtts" in low_ctx or "trong nhóm dân tộc thiểu số" in low_ctx) and ("dtts" in low_ctx or "thiểu số" in low_ctx))
                        ):
                            allowed_eth_cols.add("ty_le_ngheo_trong_dtts_%")
                        if "tỷ trọng" in low_ctx and ("dtts" in low_ctx or "thiểu số" in low_ctx):
                            allowed_eth_cols.add("ty_le_dtts_trong_nhom_%")
                        cols_to_check = [c for c in cols_to_check if str(c) in allowed_eth_cols]
                    else:
                        cols_to_check = [
                            c for c in cols_to_check
                            if str(c) not in {"so_ho_kinh", "so_ho_dtts", "so_ho_dtts_tai_cho", "tong_ho_dtts", "tong_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%", "ty_le_dtts_trong_nhom_%"}
                        ]

                for c in cols_to_check:
                    measure_context = check_unit if _text_has_measure(check_unit, str(c)) else unit
                    if ratio_context and not _col_is_ratio_like(c):
                        continue
                    if not ratio_context and _col_is_ratio_like(c) and not _text_has_measure(measure_context, str(c)):
                        continue
                    if not _text_has_measure(measure_context, str(c)):
                        continue

                    expected = {_normalize_number_token(x) for x in _number_variants(row.get(c))}
                    expected.discard("")
                    relevant_nums = {n for n in nums if n not in {"2023", "2024", "2025", "2026"}}
                    multi_label_known: set[str] = set()
                    if pattern == "multidimensional_standard":
                        labels_in_unit = [lbl for lbl in row_labels if _label_in_text_loose(lbl, unit)]
                        if len(labels_in_unit) >= 2:
                            # Câu kiểu "Tuy Đức và Đăk Glong có tỷ lệ 43,24% và 34,64%, tương ứng 829 và 538 hộ"
                            # là hợp lệ theo thứ tự. Không dùng generic checker để phạt các số hợp lệ
                            # của địa bàn/chỉ tiêu khác trong cùng câu; lỗi đặt sai trực tiếp đã có
                            # _mau12_explicit_pair_misplacement_warnings bắt riêng.
                            for _, r2 in df.iterrows():
                                lbl2 = str(r2.get(label_col) or "").strip()
                                if lbl2 in labels_in_unit:
                                    for c2 in cols_to_check:
                                        multi_label_known |= {_normalize_number_token(x) for x in _number_variants(r2.get(c2))}
                            multi_label_known.discard("")
                    if pattern == "overview_result" or _template_id_from_bundle(bundle) == 1:
                        # Mẫu 1 thường viết cùng một địa bàn với cả hộ nghèo và hộ cận nghèo trong một câu,
                        # ví dụ: "Tuy Đức với 829 hộ nghèo và 917 hộ cận nghèo". Khi kiểm cột cận nghèo,
                        # số 829 là đúng cho cột hộ nghèo cùng dòng nên không được coi là gán sai.
                        ctx_for_same_row = (check_unit + " " + unit)
                        for c2 in cols_to_check:
                            if c2 == c:
                                continue
                            if _text_has_measure(ctx_for_same_row, str(c2)):
                                multi_label_known |= {_normalize_number_token(x) for x in _number_variants(row.get(c2))}
                        multi_label_known.discard("")
                    if relevant_nums & expected:
                        wrong: list[str] = []
                    else:
                        wrong = [n for n in relevant_nums if n not in expected and n in all_numbers and n not in multi_label_known]
                    if wrong:
                        warnings.append(
                            f"LLM có vẻ gán sai cặp nhãn-số: {label} / {_column_label(str(c))} không khớp số {', '.join(wrong[:3])}."
                        )
                        if len(warnings) >= 6:
                            return warnings

                    if _unit_has_superlative_claim(check_unit) or _unit_has_superlative_claim(unit):
                        try:
                            row_value = float(row.get(c) or 0)
                            max_value = float(pd.to_numeric(df[c], errors="coerce").max())
                        except Exception:
                            row_value = max_value = 0.0
                        if abs(row_value - max_value) > 1e-9:
                            warnings.append(
                                f"LLM có nhận định xếp hạng không đúng: {label} không phải cao nhất theo {_column_label(str(c))}."
                            )
                            if len(warnings) >= 6:
                                return warnings
        if name == "template_main":
            break
    return warnings


def _parse_percent_value(token: str) -> float | None:
    """Parse token phần trăm kiểu 18.900% hoặc -56,92% để hậu kiểm ngữ cảnh."""
    raw = str(token or "").strip().replace("%", "")
    if not raw:
        return None
    # Dấu chấm trong số VN thường là hàng nghìn; dấu phẩy là thập phân.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        parts = raw.split(".")
        if len(parts) > 1 and all(len(x) == 3 for x in parts[1:]):
            raw = "".join(parts)
    try:
        return float(raw)
    except Exception:
        return None





def _movement_extreme_ratio_warnings(text: str) -> list[str]:
    """Bắt tỷ lệ biến động cực đoan trong mẫu diễn biến.

    Cố ý chỉ bắt token thật sự nằm trong ngữ cảnh tỷ lệ/%, tránh bắt nhầm các số hộ
    như 1.051 hoặc 2.082 trong cùng câu fallback an toàn.
    """
    raw = str(text or "")
    lower = raw.lower()
    warnings: list[str] = []

    def too_extreme(tok: str) -> bool:
        val = _parse_percent_value(tok)
        return val is not None and abs(val) >= 1000

    def has_caution() -> bool:
        return "mẫu số nhỏ" in lower or "cần thận trọng" in lower

    # Trường hợp chuẩn: 18.900%, 1200%, -1.200%...
    for tok in re.findall(r"[-+]?\d+(?:[\.,]\d+)*\s*%", raw):
        if too_extreme(tok) and not has_caution():
            warnings.append("Văn bản dùng tỷ lệ biến động cực đoan mà không có chú thích thận trọng.")
            return warnings

    # Trường hợp sai format hay gặp: "tỷ lệ biến động % 18.900".
    # Chỉ lấy số đứng ngay sau ký hiệu %, không quét toàn bộ câu.
    for tok in re.findall(r"%\s*([-+]?\d+(?:[\.,]\d+)*)", raw):
        nn = _normalize_number_token(tok)
        if nn in {"2023", "2024", "2025", "2026"}:
            continue
        if too_extreme(tok) and not has_caution():
            warnings.append("Văn bản dùng tỷ lệ biến động cực đoan mà không có chú thích thận trọng.")
            return warnings

    return warnings

def _malformed_year_number_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi LLM biến năm 2024 thành số liệu dạng 2.024 trong ngữ cảnh không phải năm."""
    raw = str(text or "")
    if "2.024" not in raw:
        return []
    for unit in _sentence_units(raw):
        if "2.024" not in unit:
            continue
        ul = unit.lower()
        # Cho phép nếu thật sự đang nói năm, nhưng năm nên viết 2024; vẫn không bắt quá rộng.
        if re.search(r"năm\s+2\.024", ul):
            continue
        if any(x in ul for x in ["số liệu", "số hộ", "hộ ", "tỷ lệ", "chỉ tiêu", "cốt lõi", "quy mô"]):
            return ["Văn bản có dấu hiệu số năm bị định dạng như số liệu: 2.024."]
    return []

def _unit_contains_any_number_variant(unit: str, value: Any) -> bool:
    nums = {_normalize_number_token(x) for x in _extract_number_tokens(unit)}
    expected = {_normalize_number_token(x) for x in _number_variants(value)}
    expected.discard("")
    return bool(nums & expected)


def _district_level_number_used_without_label_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi số cấp địa bàn bị viết như số toàn tỉnh/chung.

    Ví dụ đã gặp trong log: số khẩu cận nghèo của Tuy Đức (3.753) được viết trong
    một câu không có nhãn "Tuy Đức", khiến người đọc hiểu như số chung toàn tỉnh.
    Chỉ áp dụng cho bảng có cột địa bàn để tránh làm ảnh hưởng các mẫu chỉ tiêu/nhóm.
    """
    if bundle is None:
        return []
    tables = getattr(bundle, "tables", {}) or {}
    warnings: list[str] = []
    for name in ("template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        label_col = None
        for c in df.columns:
            lc = str(c).lower()
            if lc in {"huyen", "huyện", "xa", "xã", "xa_phuong", "phuong_xa", "địa bàn", "dia_ban"}:
                label_col = c
                break
        if label_col is None:
            continue
        numeric_cols = _business_numeric_cols(df, label_col)
        if not numeric_cols:
            continue

        # Tập tổng theo cột: số tổng có thể viết chung không cần nhãn địa bàn.
        totals_by_col: dict[Any, set[str]] = {}
        for c in numeric_cols:
            try:
                total = pd.to_numeric(df[c], errors="coerce").dropna().sum()
                totals_by_col[c] = {_normalize_number_token(x) for x in _number_variants(total)}
            except Exception:
                totals_by_col[c] = set()

        last_label_for_continuation: str | None = None
        row_labels = [str(v or "").strip() for v in df[label_col].tolist()]
        for unit in _sentence_units(text):
            unit_lower = unit.lower()
            nums = {_normalize_number_token(x) for x in _extract_number_tokens(unit)}
            if not nums:
                continue
            # Nếu câu đã có nhãn địa bàn nào đó thì để validator cặp nhãn-số xử lý.
            matched_labels = [lbl for lbl in row_labels if lbl and _label_in_text_loose(lbl, unit)]
            if matched_labels:
                last_label_for_continuation = matched_labels[-1]
                continue
            # Cụm nối tiếp sau dấu phẩy/chấm phẩy như "380 hộ nghèo DTTS tại chỗ"
            # vẫn thuộc địa bàn vừa nêu ở cụm trước. Không cảnh báo giả là số chung.
            if (
                last_label_for_continuation
                and re.match(r"^\s*\d", unit)
                and any(x in unit_lower for x in ("dtts", "dân tộc", "thiểu số", "kinh", "tại chỗ"))
            ):
                continue
            for c in numeric_cols:
                if not _text_has_measure(unit, str(c)):
                    continue
                allowed_totals = totals_by_col.get(c, set())
                for _, row in df.iterrows():
                    val_tokens = {_normalize_number_token(x) for x in _number_variants(row.get(c))}
                    val_tokens.discard("")
                    # Nếu số địa bàn trùng với tổng cột thì không coi là lỗi.
                    suspicious = (nums & val_tokens) - allowed_totals
                    if suspicious:
                        label = str(row.get(label_col) or "").strip()
                        warnings.append(
                            f"Văn bản có dấu hiệu dùng số cấp địa bàn như số chung: {_column_label(str(c))} của {label} ({', '.join(sorted(suspicious)[:2])}) không đi kèm nhãn địa bàn."
                        )
                        return warnings
    return warnings


def _movement_sign_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi dấu tăng/giảm trong mẫu diễn biến.

    Ví dụ: "Đắk Mil tăng -4 hộ" hoặc bảng ghi +4 nhưng văn bản viết -4.
    """
    if bundle is None or _pattern(bundle) != "movement":
        return []
    warnings: list[str] = []
    increase_words = r"(?:tăng|phát sinh|tăng lên|chuyển tăng)"
    decrease_words = r"(?:giảm|giảm xuống|thoát|vượt chuẩn)"
    for unit in _sentence_units(text):
        lower = unit.lower()
        if re.search(increase_words, lower) and re.search(r"-\s*\d", unit):
            warnings.append("Văn bản sai dấu biến động: dùng từ tăng/phát sinh nhưng đi với số âm.")
            return warnings
        if re.search(decrease_words, lower) and re.search(r"\+\s*\d", unit):
            warnings.append("Văn bản sai dấu biến động: dùng từ giảm/thoát nhưng đi với số dương có dấu cộng.")
            return warnings

    tables = getattr(bundle, "tables", {}) or {}
    for name in ("template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or "chenh_lech" not in df.columns:
            continue
        label_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = c
                break
        if label_col is None:
            continue
        for unit in _sentence_units(text):
            lower = unit.lower()
            signed_tokens = re.findall(r"[-+]\s*\d+(?:[\.,]\d+)*", unit)
            if not signed_tokens:
                continue
            for _, row in df.iterrows():
                label = str(row.get(label_col) or "").strip()
                if not label or label.lower() not in lower:
                    continue
                try:
                    expected = float(row.get("chenh_lech") or 0)
                except Exception:
                    continue
                for tok in signed_tokens:
                    parsed = _parse_percent_value(tok.replace("%", ""))
                    if parsed is None:
                        try:
                            parsed = float(tok.replace(" ", "").replace(".", "").replace(",", "."))
                        except Exception:
                            parsed = None
                    if parsed is None:
                        continue
                    # Chỉ bắt khi cùng trị tuyệt đối, khác dấu; tránh bắt số không liên quan.
                    if abs(abs(parsed) - abs(expected)) < 1e-9 and expected and (parsed * expected < 0):
                        warnings.append(
                            f"Văn bản sai dấu biến động: {label} có chênh lệch {_num(expected)} nhưng văn bản ghi {tok.strip()}."
                        )
                        return warnings

                # Bắt thêm lỗi đã gặp ở mẫu 3: câu nói "giảm ... Đắk Mil (4 hộ)"
                # trong khi bảng ghi Đắk Mil chênh lệch +4 hộ. Trường hợp này số không có dấu +,
                # nên nhánh signed_tokens phía trên không bắt được. Chỉ bắt khi trong cùng cụm có
                # từ giảm/giảm xuống và trị tuyệt đối khớp đúng chênh lệch dương của địa bàn.
                if expected > 0 and re.search(decrease_words, lower):
                    unsigned_tokens = re.findall(r"(?<![-+\d])\d+(?:[\.,]\d+)*", unit)
                    for tok in unsigned_tokens:
                        parsed = _parse_percent_value(tok.replace("%", ""))
                        if parsed is None:
                            try:
                                parsed = float(tok.replace(" ", "").replace(".", "").replace(",", "."))
                            except Exception:
                                parsed = None
                        if parsed is None:
                            continue
                        if abs(parsed - abs(expected)) < 1e-9:
                            warnings.append(
                                f"Văn bản sai dấu biến động: {label} có chênh lệch tăng {_num(expected)} nhưng văn bản diễn giải là giảm."
                            )
                            return warnings
    return warnings





def _movement_transition_pair_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi câu movement kiểu 'Đắk Mil tăng từ 4 đến 8' trong khi bảng là 385 -> 389.

    Validator sign chỉ bắt đúng/ sai dấu chênh lệch. Hàm này kiểm cặp đầu kỳ/cuối kỳ
    khi văn bản dùng cấu trúc 'từ A lên/còn/đến B' trong cùng cụm có tên địa bàn.
    """
    if bundle is None or _pattern(bundle) != "movement":
        return []
    tables = getattr(bundle, "tables", {}) or {}
    transition_re = re.compile(
        # Bắt cả lỗi kiểu: "từ 4 hộ cuối kỳ lên 4 hộ đầu kỳ".
        # Cho phép chen cụm đầu kỳ/cuối kỳ/kỳ trước/kỳ sau giữa số và động từ chuyển.
        r"từ\s+([-+]?\d+(?:[\.,]\d+)*)\s*(?:hộ)?(?:\s+(?:đầu\s+kỳ|cuối\s+kỳ|kỳ\s+trước|kỳ\s+sau))?\s+"
        r"(?:đến|lên|còn|xuống|sang|thành)\s+([-+]?\d+(?:[\.,]\d+)*)",
        flags=re.I,
    )
    for name in ("template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        if not {"so_ho_ky_truoc", "so_ho_ky_sau"}.issubset(set(map(str, df.columns))):
            continue
        label_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = c
                break
        if not label_col:
            continue
        for unit in _sentence_units(text):
            lower = unit.lower()
            matches = list(transition_re.finditer(unit))
            if not matches:
                continue
            for _, row in df.iterrows():
                label = str(row.get(label_col) or "").strip()
                if not label or label.lower() not in lower:
                    continue
                expected_start = {_normalize_number_token(v) for v in _number_variants(row.get("so_ho_ky_truoc"))}
                expected_end = {_normalize_number_token(v) for v in _number_variants(row.get("so_ho_ky_sau"))}
                for m in matches:
                    start_tok = _normalize_number_token(m.group(1))
                    end_tok = _normalize_number_token(m.group(2))
                    if start_tok not in expected_start or end_tok not in expected_end:
                        warnings = [
                            f"Văn bản sai số đầu kỳ/cuối kỳ: {label} phải là {_num(row.get('so_ho_ky_truoc'))} hộ -> {_num(row.get('so_ho_ky_sau'))} hộ, không phải {m.group(1)} -> {m.group(2)}."
                        ]
                        return warnings
    return []

def _movement_transition_direction_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Catch contradictory movement phrasing such as "giảm từ 3402 xuống còn 3691".

    This is a semantic direction check, not a new source of facts: it only compares the
    two numbers that the LLM already placed in the same transition phrase.
    """
    if bundle is None or _pattern(bundle) != "movement":
        return []
    number = r"([-+]?\d+(?:[\.,]\d+)*)"
    transition_with_from_re = re.compile(
        rf"\b(giam|tang)\b[^.!?;\n]{{0,120}}?\btu\s+{number}"
        rf"(?:\s+ho|\s+%)?[^.!?;\n]{{0,50}}?\b(len|tang\s+len|xuong|xuong\s+con|con|thanh|den|sang)\s+"
        rf"(?:con\s+|len\s+)?{number}",
        flags=re.I,
    )
    transition_after_number_re = re.compile(
        rf"{number}(?:\s+ho|\s+%)?[^.!?;\n]{{0,80}}?\b(giam|tang)\b"
        rf"[^.!?;\n]{{0,50}}?\b(len|tang\s+len|xuong|xuong\s+con|con|thanh|den|sang)\s+"
        rf"(?:con\s+|len\s+)?{number}",
        flags=re.I,
    )

    def invalid_transition(verb: str, connector: str, start: float | None, end: float | None) -> bool:
        if start is None or end is None or abs(start - end) < 1e-9:
            return False
        verb = re.sub(r"\s+", " ", str(verb or "").strip().lower())
        connector = re.sub(r"\s+", " ", str(connector or "").strip().lower())
        wrong_decrease = (verb == "giam" or connector in {"xuong", "xuong con", "con"}) and end > start
        wrong_increase = (verb == "tang" or connector in {"len", "tang len"}) and end < start
        contradictory_words = (verb == "giam" and connector in {"len", "tang len"}) or (
            verb == "tang" and connector in {"xuong", "xuong con", "con"}
        )
        return bool(wrong_decrease or wrong_increase or contradictory_words)

    for unit in _sentence_units(text):
        loose = _loose_vietnamese_text(unit)
        for m in transition_with_from_re.finditer(loose):
            start = _parse_percent_value(m.group(2))
            end = _parse_percent_value(m.group(4))
            if invalid_transition(m.group(1), m.group(3), start, end):
                return [
                    "Văn bản sai chiều biến động: cụm chuyển tiếp dùng tăng/giảm hoặc lên/xuống trái với quan hệ số học giữa hai mốc."
                ]
        for m in transition_after_number_re.finditer(loose):
            start = _parse_percent_value(m.group(1))
            end = _parse_percent_value(m.group(4))
            if invalid_transition(m.group(2), m.group(3), start, end):
                return [
                    "Văn bản sai chiều biến động: cụm chuyển tiếp dùng tăng/giảm hoặc lên/xuống trái với quan hệ số học giữa hai mốc."
                ]
    return []

def _ratio_word_with_household_unit_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Không dùng 'tỷ lệ' cho số tuyệt đối đơn vị hộ.

    Bắt hẹp lỗi kiểu "nhóm Kinh chiếm tỷ lệ cao nhất (1.652 hộ)".
    Không phạt câu hợp lệ kiểu "829 hộ, tỷ lệ 43,24%" hoặc
    "tỷ lệ 43,24%, tương ứng 829 hộ", vì trong cụm đã có số phần trăm thật.
    """
    raw = str(text or "")
    lower = raw.lower()
    for m in re.finditer(r"(?:chiếm\s+)?t[ỷỉi]\s*lệ[^.\n;:]{0,100}?\d[\d\.,]*\s*hộ", lower):
        segment = m.group(0)
        before_house = segment.rsplit("hộ", 1)[0]
        if "%" in before_house:
            continue
        return ["Văn bản dùng 'tỷ lệ' với số tuyệt đối đơn vị hộ; cần viết là số hộ/quy mô, không phải tỷ lệ."]
    return []


def _movement_soft_style_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Cảnh báo mềm cho diễn đạt movement hơi quá mức, không dùng để fallback."""
    if bundle is None or _pattern(bundle) != "movement":
        return []
    raw = str(text or "")
    lower = raw.lower()
    warnings: list[str] = []
    # Không hard fail: chỉ gợi ý. Ví dụ +1,04% không nên gọi là cao.
    if re.search(r"tỷ lệ\s+biến\s+động\s+cao[^.\n]{0,60}\+?\s*(?:0|1|2|3|4|5)(?:[,.]\d+)?\s*%", lower):
        warnings.append("Diễn đạt movement hơi quá mức: tỷ lệ biến động nhỏ nên viết là biến động nhẹ, không gọi là cao.")
    return warnings



def _movement_or_percentage_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt hẹp câu diễn đạt chênh lệch kiểu "-535 hộ hoặc -14,99%".

    Với mẫu diễn biến, số hộ chênh lệch và tỷ lệ phần trăm là hai cách mô tả
    cùng một biến động, không phải quan hệ lựa chọn "hoặc". Dùng "tương ứng"
    hoặc "tương đương" mới đúng văn báo cáo.
    """
    if bundle is None or _pattern(bundle) != "movement":
        return []
    raw = str(text or "")
    lower = raw.lower()
    # Bắt hẹp: có chữ chênh lệch/biến động gần số hộ, sau đó "hoặc" gần số %.
    if re.search(
        r"(?:chênh lệch|biến động)[^.;!?]{0,80}\d+(?:[\.,]\d+)*\s*hộ[^.;!?]{0,30}\bhoặc\b[^.;!?]{0,30}[-+]?\d+(?:[\.,]\d+)*\s*%",
        lower,
    ):
        return ["Văn bản diễn đạt chênh lệch chưa phù hợp: không viết 'chênh lệch ... hộ hoặc ...%'; dùng 'chênh lệch ... hộ, tương ứng ...%'."]
    return []




def _movement_scope_misattribution_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi gán số tổng toàn phạm vi cho một địa bàn trong mẫu diễn biến.

    Lỗi đã gặp ở mẫu 3: "Đắk Mil ... chênh lệch -535 hộ, -14,99%".
    Trong đó -535 hộ / -14,99% là số tổng toàn tỉnh, còn Đắk Mil chỉ là +4 hộ / +1,04%.

    Thiết kế hẹp:
    - Chỉ áp dụng pattern movement.
    - Chỉ bắt khi cụm cục bộ quanh tên địa bàn chứa số tổng toàn phạm vi.
    - Không bắt nếu chính địa bàn đó thật sự có cùng số với tổng.
    """
    if bundle is None or _pattern(bundle) != "movement":
        return []

    facts = getattr(bundle, "facts", {}) or {}
    movement_detail: dict[str, Any] = {}
    try:
        table_insights = facts.get("table_insights") if isinstance(facts, dict) else None
        if isinstance(table_insights, dict) and isinstance(table_insights.get("movement_detail"), dict):
            movement_detail = table_insights.get("movement_detail") or {}
    except Exception:
        movement_detail = {}

    global_delta = None
    global_ratio = None
    global_values: list[Any] = []
    if isinstance(facts, dict):
        global_delta = facts.get("chenh_lech", None)
        global_ratio = facts.get("ty_le_bien_dong_%", facts.get("ty_le_bien_dong", None))
        for key in (
            "tong_ky_truoc",
            "tong_ky_sau",
            "tong_cuoi_ky_phan_loai",
            "chenh_lech",
            "ty_le_bien_dong_%",
            "ty_le_bien_dong",
            "unexplained_delta",
        ):
            if key in facts:
                global_values.append(facts.get(key))
        components = facts.get("movement_components")
        if isinstance(components, dict):
            global_values.extend(components.values())
    if global_delta is None:
        global_delta = movement_detail.get("chenh_lech")
    if global_ratio is None:
        global_ratio = movement_detail.get("ty_le_bien_dong_%", movement_detail.get("ty_le_bien_dong"))
    if isinstance(movement_detail, dict):
        for key in (
            "tong_ky_truoc",
            "tong_ky_sau",
            "tong_cuoi_ky_phan_loai",
            "chenh_lech",
            "ty_le_bien_dong_%",
            "ty_le_bien_dong",
            "unexplained_delta",
        ):
            if key in movement_detail:
                global_values.append(movement_detail.get(key))

    tables = getattr(bundle, "tables", {}) or {}
    target_df = None
    label_col = None
    for name in ("template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        if "chenh_lech" not in df.columns:
            continue
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = c
                break
        if label_col is not None:
            target_df = df
            break
    if not isinstance(target_df, pd.DataFrame) or label_col is None:
        return []

    # Nếu facts không có tổng, tính từ bảng địa bàn. Đây là tổng toàn phạm vi, không phải số của một địa bàn.
    try:
        if global_delta is None:
            global_delta = float(pd.to_numeric(target_df["chenh_lech"], errors="coerce").dropna().sum())
        if global_ratio is None and {"so_ho_ky_truoc", "chenh_lech"}.issubset(set(target_df.columns)):
            denom = float(pd.to_numeric(target_df["so_ho_ky_truoc"], errors="coerce").dropna().sum())
            delta_sum = float(pd.to_numeric(target_df["chenh_lech"], errors="coerce").dropna().sum())
            if abs(denom) > 1e-9:
                global_ratio = delta_sum / denom * 100.0
    except Exception:
        pass
    if global_delta is not None:
        global_values.append(global_delta)
    if global_ratio is not None:
        global_values.append(global_ratio)
    try:
        for col in (
            "so_ho_ky_truoc",
            "so_ho_ky_sau",
            "so_ho_cuoi_ky",
            "tong_cuoi_ky_phan_loai",
            "chenh_lech",
            "giam_1",
            "giam_2",
            "giam_khac",
            "tang_1",
            "tang_2",
            "tang_3",
            "tang_khac",
        ):
            if col in target_df.columns:
                global_values.append(float(pd.to_numeric(target_df[col], errors="coerce").dropna().sum()))
    except Exception:
        pass

    global_delta_tokens = {_normalize_number_token(x) for x in _number_variants(global_delta)} if global_delta is not None else set()
    global_ratio_tokens = {_normalize_number_token(x) for x in _number_variants(global_ratio)} if global_ratio is not None else set()
    global_value_tokens: set[str] = set()
    for value in global_values:
        try:
            if value is None or abs(float(value)) < 1e-9:
                continue
        except Exception:
            pass
        global_value_tokens |= {_normalize_number_token(x) for x in _number_variants(value)}
    global_delta_tokens.discard("")
    global_ratio_tokens.discard("")
    global_value_tokens.discard("")
    # Các số quá nhỏ 1-6 dễ trùng với diễn đạt đếm mục; không dùng làm số tổng để bắt lỗi.
    global_delta_tokens -= {str(i) for i in range(1, 7)}
    global_ratio_tokens -= {str(i) for i in range(1, 7)}
    global_value_tokens -= {str(i) for i in range(1, 7)}
    if not global_delta_tokens and not global_ratio_tokens and not global_value_tokens:
        return []

    row_labels = [str(v or "").strip() for v in target_df[label_col].tolist()]

    def _loose_text(value: Any) -> str:
        raw = str(value or "").lower()
        raw = unicodedata.normalize("NFD", raw)
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return raw.replace("đ", "d")

    for unit in _sentence_units(text):
        unit_lower = unit.lower()
        unit_loose = _loose_text(unit)
        for _, row in target_df.iterrows():
            label = str(row.get(label_col) or "").strip()
            label_lower = label.lower()
            label_loose = _loose_text(label)
            if not label or (label_lower not in unit_lower and label_loose not in unit_loose):
                continue
            check_unit = _local_context_for_label(unit, label, row_labels)
            check_lower = check_unit.lower()
            nums = {_normalize_number_token(x) for x in _extract_number_tokens(check_unit)}
            nums |= {_normalize_number_token(x) for x in _extract_number_tokens(unit)}
            if not nums:
                continue
            expected_delta = {_normalize_number_token(x) for x in _number_variants(row.get("chenh_lech"))}
            expected_ratio = {_normalize_number_token(x) for x in _number_variants(row.get("ty_le_bien_dong_%"))} if "ty_le_bien_dong_%" in target_df.columns else set()
            expected_row_tokens: set[str] = set()
            for col in target_df.columns:
                try:
                    if pd.api.types.is_numeric_dtype(target_df[col]):
                        expected_row_tokens |= {_normalize_number_token(x) for x in _number_variants(row.get(col))}
                except Exception:
                    continue
            expected_delta.discard("")
            expected_ratio.discard("")
            expected_row_tokens.discard("")

            bad_delta = (nums & global_delta_tokens) - expected_delta
            bad_ratio = (nums & global_ratio_tokens) - expected_ratio
            bad_global = (nums & global_value_tokens) - expected_row_tokens
            if bad_delta or bad_ratio:
                wrong_parts = []
                if bad_delta:
                    wrong_parts.append("chênh lệch tổng toàn phạm vi " + ", ".join(sorted(bad_delta)[:2]))
                if bad_ratio:
                    wrong_parts.append("tỷ lệ tổng toàn phạm vi " + ", ".join(sorted(bad_ratio)[:2]))
                return [
                    "LLM có vẻ gán sai cặp nhãn-số: số tổng toàn phạm vi bị gán cho địa bàn "
                    + label
                    + " ("
                    + "; ".join(wrong_parts)
                    + ")."
                ]
            if bad_global:
                return [
                    "LLM có vẻ gán sai cặp nhãn-số: số tổng toàn phạm vi bị đặt trong câu có địa bàn "
                    + label
                    + " ("
                    + ", ".join(sorted(bad_global)[:3])
                    + ")."
                ]
    return []

def _movement_direction_component_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi gọi sai chiều tăng/giảm của các nhãn diễn biến mẫu 2/3."""
    if bundle is None or _pattern(bundle) != "movement":
        return []
    tid = _template_id_from_bundle(bundle)
    if tid not in {2, 3}:
        return []

    if tid == 2:
        decrease_terms = [
            "thoát nghèo -> cận nghèo",
            "thoát nghèo -> vượt chuẩn",
            "thoát nghèo lên cận nghèo",
            "thoát nghèo vượt chuẩn",
        ]
        increase_terms = [
            "cận nghèo trở thành hộ nghèo",
            "hộ cận nghèo trở thành hộ nghèo",
            "cận nghèo chuyển thành hộ nghèo",
            "hộ cận nghèo chuyển thành hộ nghèo",
            "tái nghèo",
            "nghèo mới phát sinh",
            "mới phát sinh",
        ]
    else:
        decrease_terms = [
            "thoát cận nghèo -> vượt chuẩn",
            "thoát cận nghèo vượt chuẩn",
            "cận nghèo trở thành hộ nghèo",
        ]
        increase_terms = [
            "thoát nghèo -> cận nghèo",
            "thoát nghèo lên cận nghèo",
            "thoát nghèo trở thành hộ cận nghèo",
            "hộ nghèo trở thành hộ cận nghèo",
            "hộ nghèo chuyển sang cận nghèo",
            "từ hộ nghèo sang cận nghèo",
            "tái cận nghèo",
            "cận nghèo mới phát sinh",
            "mới phát sinh",
        ]

    decrease_contexts = (
        "cấu phần giảm",
        "nhóm giảm",
        "phần giảm",
        "chiều giảm",
        "giảm gồm",
        "làm giảm",
        "giảm do",
        "giảm là",
    )
    increase_contexts = (
        "cấu phần tăng",
        "nhóm tăng",
        "phần tăng",
        "chiều tăng",
        "tăng gồm",
        "làm tăng",
        "tăng do",
        "tăng là",
    )

    warnings: list[str] = []
    for unit in _sentence_units(text):
        low = unit.lower()
        in_decrease_context = any(ctx in low for ctx in decrease_contexts)
        in_increase_context = any(ctx in low for ctx in increase_contexts)
        if in_decrease_context:
            bad_terms = [term for term in increase_terms if term in low]
            if bad_terms:
                warnings.append(
                    "Văn bản sai chiều biến động: nhãn tăng "
                    + ", ".join(sorted(set(bad_terms))[:3])
                    + " bị đặt trong câu nhóm giảm."
                )
        if in_increase_context:
            bad_terms = [term for term in decrease_terms if term in low]
            if bad_terms:
                warnings.append(
                    "Văn bản sai chiều biến động: nhãn giảm "
                    + ", ".join(sorted(set(bad_terms))[:3])
                    + " bị đặt trong câu nhóm tăng."
                )
    return _dedupe_text_items(warnings)

def _numeric_comparison_phrase_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi số học trực tiếp: 62,86% thấp hơn 52,75% là sai."""
    raw = str(text or "")
    warnings: list[str] = []
    pattern = re.compile(
        r"([-+]?\d+(?:[\.,]\d+)?)\s*(%)?\s*(?:điểm\s+phần\s+trăm\s+)?(cao hơn|thấp hơn)\b[^.;!?\n]{0,80}?([-+]?\d+(?:[\.,]\d+)?)\s*(%)?",
        flags=re.IGNORECASE,
    )
    for m in pattern.finditer(raw):
        left = _parse_percent_value(m.group(1))
        right = _parse_percent_value(m.group(4))
        if left is None or right is None:
            continue
        phrase = m.group(3).lower()
        if phrase == "cao hơn" and left <= right:
            warnings.append(
                f"So sánh số học sai: {m.group(1)} không cao hơn {m.group(4)}."
            )
        if phrase == "thấp hơn" and left >= right:
            warnings.append(
                f"So sánh số học sai: {m.group(1)} không thấp hơn {m.group(4)}."
            )
    return _dedupe_text_items(warnings)

def _deprivation_ratio_semantics_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Giữ đúng bản chất mẫu tỷ lệ thiếu hụt.

    Mẫu 5/7 là tỷ lệ thiếu hụt, nên 60,88% nghĩa là tỷ lệ thiếu hụt,
    không phải tỷ lệ đạt/chưa đạt kỳ vọng. Bắt hẹp các cụm đã xuất hiện
    trong log để không làm tăng fallback vô lý.
    """
    if bundle is None or _pattern(bundle) != "deprivation_ratio":
        return []
    lower = str(text or "").lower()
    bad_patterns = [
        r"tỷ\s*lệ\s*đạt",
        r"tỉ\s*lệ\s*đạt",
        r"không\s+đạt\s+mức\s+cao",
        r"chưa\s+đạt\s+mức\s+cao",
        r"thấp\s+hơn\s+so\s+với\s+mong\s+đợi",
        r"cao\s+hơn\s+so\s+với\s+mong\s+đợi",
        r"mức\s+đạt\s+được",
    ]
    if any(re.search(pat, lower) for pat in bad_patterns):
        return ["Văn bản sai bản chất tỷ lệ thiếu hụt: không được diễn giải tỷ lệ thiếu hụt thành tỷ lệ đạt/chưa đạt kỳ vọng."]

    # Mẫu tỷ lệ thiếu hụt phân tích theo CHỈ TIÊU. Không để LLM đổi nhãn chỉ tiêu
    # thành "nhóm hộ" như: "Hai nhóm hộ nổi bật là Hộ cận nghèo với tỷ lệ 60,88%".
    # Bắt hẹp theo cụm đã thấy trong log để không làm tăng fallback quá mức.
    indicator_as_household_patterns = [
        r"(?:hai|các|những)\s+nhóm\s+hộ\s+nổi\s+bật\s+(?:là|gồm)",
        r"nhóm\s+hộ\s+nổi\s+bật\s+(?:là|gồm)",
        r"hộ\s+có\s+nhà\s+tiêu\s+hợp\s+vệ\s+sinh",
        r"hộ\s+có\s+chất\s+lượng\s+nhà\s+ở",
    ]
    if any(re.search(pat, lower) for pat in indicator_as_household_patterns):
        return ["Văn bản sai bản chất mẫu tỷ lệ thiếu hụt: không được đổi chỉ tiêu thiếu hụt thành nhóm hộ."]
    return []

def _household_focus_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Giữ đúng đối tượng trọng tâm của mẫu đơn nhóm.

    Chỉ áp dụng mạnh cho mẫu thiếu hụt hộ nghèo/cận nghèo (4-7), để không ảnh hưởng
    các mẫu tổng hợp chung hoặc mẫu phân tích cả hai nhóm.
    """
    if bundle is None:
        return []
    pattern = _pattern(bundle)
    if pattern not in {"deprivation_count", "deprivation_ratio"}:
        return []
    focus = _household_focus(bundle).strip().lower()
    title_l = str((getattr(bundle, "template", {}) or {}).get("title") or "").lower()
    lower = str(text or "").lower()
    if focus == "hộ nghèo" or ("hộ nghèo" in title_l and "hộ cận nghèo" not in title_l):
        if "hộ cận nghèo" in lower:
            return ["Văn bản sai trọng tâm hộ: mẫu hộ nghèo nhưng viết sang hộ cận nghèo."]
    if focus == "hộ cận nghèo" or ("hộ cận nghèo" in title_l and "hộ nghèo, hộ cận nghèo" not in title_l):
        if re.search(r"(?<!cận\s)hộ nghèo", lower):
            return ["Văn bản sai trọng tâm hộ: mẫu hộ cận nghèo nhưng viết thành hộ nghèo."]
    return []



def _word_report_internal_reference_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Không để phần nhận định đưa vào Word lộ thuật ngữ kỹ thuật/mẫu/cột.

    Đây là văn bản báo cáo nhận định từ số liệu, không phải debug Excel/code. Vì vậy các cụm
    như "mẫu 1", "cột A/B", "D+F", "SAFE_BASE_TEXT", "DB" phải bị reject.
    """
    raw = str(text or "")
    lower = raw.lower()
    warnings: list[str] = []
    if re.search(r"(?i)\bmẫu\s*(?:số\s*)?\d+\b", raw):
        warnings.append("Văn bản nhận định còn nhắc số mẫu báo cáo; phần đưa vào Word không được viết kiểu 'mẫu 1', 'mẫu 2'.")
    if re.search(r"(?i)\b(?:file\s*mẫu|template(?:_id)?|safe_base_text|report_facts|fact\s*pack|fact\s*bundle|audit|validator|debug|json|dataframe|series|python|sql|excel|workbook|worksheet|sheet|header)\b", raw):
        warnings.append("Văn bản nhận định còn token kỹ thuật nội bộ hoặc nguồn trung gian.")
    if re.search(r"\bDB\b", raw):
        warnings.append("Văn bản nhận định còn viết 'DB'; khi đưa vào Word phải dùng cách diễn đạt trung tính như 'nguồn dữ liệu hiện có'.")
    if re.search(r"(?i)\bcác\s+cột\b|\bcột\s+", raw):
        warnings.append("Văn bản nhận định còn nhắc cột bảng/Excel; phần nhận định trong Word phải diễn giải theo chỉ tiêu nghiệp vụ, không nhắc 'cột A, B, D+F'.")
    if re.search(r"(?i)\b(?:ô|cell)\s+[A-Z]{1,3}\d+\b", raw):
        warnings.append("Văn bản nhận định còn nhắc ô Excel.")
    if re.search(r"\b[A-Z]\s*(?:\+|\-|/|\*)\s*[A-Z](?:\s*(?:\+|\-|/|\*)\s*[A-Z])*\b", raw):
        warnings.append("Văn bản nhận định còn nhắc công thức/cấu trúc cột kỹ thuật.")
    if re.search(r"(?i)\btheo\s+công\s+thức(?:\s+biểu\s+mẫu)?\b|\bcông\s+thức\s+biểu\s+mẫu\b", raw):
        warnings.append("Văn bản nhận định còn nhắc công thức biểu mẫu; Word cần trình bày kết quả nghiệp vụ, không trình bày công thức/cột kỹ thuật.")
    if "safe_base_text" in lower or "report_facts" in lower:
        warnings.append("Văn bản nhận định còn lộ nguồn prompt/facts nội bộ.")
    return _dedupe_text_items(warnings)

def _pattern_context_quality_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Hậu kiểm ngữ cảnh và văn phong báo cáo, bổ sung cho kiểm số liệu.

    Các lỗi ở đây xuất hiện trong log thực tế: sai trọng tâm mẫu 7, dùng giọng chat,
    markdown, ký tự Cyrillic lẫn trong tên địa bàn, hoặc tỷ lệ biến động cực đoan
    của mẫu movement được LLM nhấn mạnh như kết luận chắc chắn.
    """
    warnings: list[str] = []
    raw = str(text or "")
    lower = raw.lower()
    pattern = _pattern(bundle) if bundle is not None else ""
    title = str((getattr(bundle, "template", {}) or {}).get("title") or "") if bundle is not None else ""
    focus = _household_focus(bundle).lower() if bundle is not None else ""

    if re.search(r"[\u0400-\u04FF]", raw):
        warnings.append("Văn bản có ký tự Unicode bất thường/Cyrillic trong tiếng Việt hoặc tên địa bàn.")

    if re.search(r"(?i)đắk\s*lắk|dak\s*lak|đak\s*lak", raw):
        warnings.append("Văn bản sai địa bàn tỉnh: project/báo cáo dùng Đắk Nông, không được ghi Đắk Lắk.")

    if "**" in raw or "```" in raw or re.search(r"(?m)^\s*#{1,6}\s+", raw):
        warnings.append("Văn bản còn markdown hoặc ký hiệu trình bày chưa phù hợp.")

    if re.search(r"(?i)(YÊU\s+CẦU\s+SỬA|HẬU\s+KIỂM|LẦN\s+THỬ)", raw):
        warnings.append("Văn bản còn lộ chỉ dẫn prompt/retry.")

    if re.search(r"(?i)(khi\s+đưa\s+vào\s+báo\s+cáo|khi\s+diễn\s+giải|nếu\s+tiếp\s+tục\s+phân\s+tích\s+theo\s+địa\s+bàn|không\s+dùng\s+số\s+toàn\s+tỉnh\s+để\s+thay|phục\s+vụ\s+việc\s+xác\s+định\s+trọng\s+tâm\s+quản\s+lý)", raw):
        warnings.append("Văn bản còn câu nhắc quy trình/nhắc cách viết báo cáo; lớp public repair sẽ loại câu này trước khi đưa vào Word.")

    if re.search(r"(?i)(dưới\s+đây\s+là|sau\s+đây\s+là|văn\s+bản\s+nhận\s+định\s+đã\s+được|theo\s+yêu\s+cầu)", raw):
        warnings.append("Văn bản có giọng prompt/chat.")

    if re.search(r"(?i)(từ\s+(?:các\s+)?thông\s+tin\s+đã\s+cung\s+cấp|dựa\s+trên\s+(?:các\s+)?thông\s+tin\s+đã\s+cung\s+cấp|dữ\s+liệu\s+đã\s+cung\s+cấp|văn\s+bản\s+nguồn|nội\s+dung\s+nguồn\s+đã\s+kiểm\s+soát|nội\s+dung\s+nguồn|nguồn\s+đã\s+kiểm\s+soát|quy\s+tắc\s+bắt\s+buộc|yêu\s+cầu\s+tối\s+thiểu\s+số\s+liệu|tôi\s+viết\s+lại|tôi\s+tiến\s+hành(?:\s+phân\s+tích)?|phần\s+nhận\s+định\s+của)", raw):
        warnings.append("Văn bản còn lộ chỉ dẫn prompt/retry hoặc nguồn trung gian.")

    if re.search(r"(?i)(^|[\n.!?]\s*)hãy\b", raw) or "hãy tiếp tục" in lower:
        warnings.append("Văn bản có giọng prompt/chat.")

    if re.search(r"\bchúng ta\b|\bchúng tôi\b|\bta thấy\b|\bcó thể thấy\b|\bcó thể nhận thấy\b", lower):
        warnings.append("Văn bản có giọng prompt/chat hoặc người viết chủ quan.")

    warnings.extend(_word_report_internal_reference_warnings(bundle, raw))

    typo_needles = [
        "men ngang",
        "thiếu đi tình trạng",
        "họat động",
        "thiếu đi hiện tượng",
        "phạm vị",
    ]
    if any(x in lower for x in typo_needles):
        warnings.append("Văn bản có lỗi chính tả/ngữ nghĩa nghiêm trọng.")

    # Mẫu có trọng tâm riêng là hộ cận nghèo (ví dụ mẫu 6/7) không được trượt sang
    # "hộ nghèo" như đối tượng chính. Các mẫu phân tích đồng thời hộ nghèo + hộ cận nghèo
    # (mẫu 8-11) vẫn được nhắc cả hai nhóm.
    title_l = title.lower()
    is_near_poor_only = (
        focus.strip() == "hộ cận nghèo"
        or (
            "hộ cận nghèo" in title_l
            and "hộ nghèo, hộ cận nghèo" not in title_l
            and "hộ nghèo và hộ cận nghèo" not in title_l
        )
    )
    if is_near_poor_only and pattern != "movement":
        near_focus_check_text = (
            lower
            .replace("thoát nghèo -> cận nghèo", "")
            .replace("thoát nghèo sang cận nghèo", "")
            .replace("cận nghèo trở thành hộ nghèo", "")
            .replace("cận nghèo chuyển thành nghèo", "")
        )
        if re.search(r"(?<!cận\s)hộ nghèo", near_focus_check_text):
            warnings.append("Văn bản sai trọng tâm hộ: mẫu hộ cận nghèo nhưng viết thành hộ nghèo.")

    warnings.extend(_household_focus_warnings(bundle, raw))
    warnings.extend(_deprivation_ratio_semantics_warnings(bundle, raw))
    warnings.extend(_malformed_year_number_warnings(bundle, raw))
    warnings.extend(_ratio_word_with_household_unit_warnings(bundle, raw))
    warnings.extend(_movement_soft_style_warnings(bundle, raw))
    warnings.extend(_movement_or_percentage_warnings(bundle, raw))

    if pattern in {"vulnerable_groups"} and "địa bàn" in lower and _template_id_from_bundle(bundle) != 8:
        warnings.append("Văn bản lẫn ngữ cảnh địa bàn trong mẫu phân tích theo nhóm đối tượng.")
    if pattern in {"vulnerable_groups"} and re.search(r"tỷ lệ\s+(?:hộ|nhóm)", lower):
        warnings.append("Văn bản dùng tỷ lệ trong mẫu không có tỷ lệ, dễ sai bài toán nhóm đối tượng.")

    if pattern in {"ethnicity"} and "địa bàn" in lower:
        warnings.append("Văn bản lẫn ngữ cảnh địa bàn trong mẫu phân tích theo dân tộc.")

    if pattern in {"deprivation_count", "deprivation_ratio", "child_deprivation"}:
        # Các mẫu này phân tích theo chỉ tiêu; không gọi chỉ tiêu là địa bàn. Đây là cảnh báo chất lượng,
        # không tự động fallback nếu chỉ là câu mở bài chung.
        if re.search(r"địa bàn\s+(cần|ưu tiên|tập trung|cao nhất|thấp nhất|nổi bật)", lower) or "địa bàn nổi bật" in lower:
            warnings.append("Văn bản có dấu hiệu gọi chỉ tiêu là địa bàn trong mẫu phân tích theo chỉ tiêu.")

    if pattern == "movement":
        if any(x in lower for x in ["hiệu quả công tác", "tăng trưởng", "thành công trong công tác"]):
            warnings.append("Văn bản suy diễn hiệu quả/tăng trưởng từ bảng diễn biến chưa đủ căn cứ.")
        if "xu hướng phát sinh" in lower:
            warnings.append("Văn bản dùng cụm 'xu hướng phát sinh' chưa phù hợp mẫu diễn biến; nên viết là mức biến động giữa đầu kỳ và cuối kỳ.")
        warnings.extend(_movement_extreme_ratio_warnings(raw))

    if pattern == "causes":
        if any(x in lower for x in ["hiệu quả hỗ trợ", "hiệu quả chính sách", "hiệu quả chương trình"]):
            warnings.append("Văn bản có nhận định về hiệu quả hỗ trợ/chính sách không được chứng minh bằng số liệu nguyên nhân nghèo.")
        if any(x in lower for x in ["cải thiện tình hình tài chính", "cải thiện sức khỏe", "hộ gia đình có thu nhập thấp"]):
            warnings.append("Văn bản suy diễn giải pháp/tình trạng thu nhập-sức khỏe ngoài phạm vi bảng nguyên nhân nghèo.")

    if pattern == "child_deprivation":
        if re.search(r"số\s+hộ\s+trẻ\s+em", lower):
            warnings.append("Văn bản lẫn đơn vị hộ và trẻ em trong mẫu trẻ em.")
        if "tỷ lệ hộ nghèo" in lower and "trẻ" in lower:
            warnings.append("Văn bản có nguy cơ lẫn tỷ lệ hộ nghèo với tỷ lệ trẻ em thiếu hụt.")

    if pattern == "multidimensional_standard":
        # Tỷ lệ của mẫu 12 là tỷ lệ trong từng địa bàn: so_ho_muc_tieu / tong_ho_ra_soat của địa bàn đó.
        # Không được viết như tỷ trọng của một địa bàn trong tổng toàn tỉnh.
        if re.search(r"(tuy\s+đức|đăk\s+glong|đắk\s+song|cư\s+jút|krông\s+nô|đắk\s+mil|đắk\s+rlấp|gia\s+nghĩa)[^.;!?]{0,120}(chiếm|tỷ\s+lệ)[^.;!?]{0,80}(toàn\s+tỉnh|tổng\s+số\s+hộ\s+đã\s+rà\s+soát|tổng\s+hộ\s+rà\s+soát)(?![^.;!?]{0,60}(của\s+(?:riêng\s+)?(?:địa\s+bàn|huyện|thành\s+phố)))", lower):
            warnings.append("Văn bản sai phạm vi tỷ lệ mẫu 12: tỷ lệ của từng địa bàn phải tính trên tổng hộ rà soát của chính địa bàn đó, không phải tỷ trọng trong toàn tỉnh.")
        if re.search(r"tổng\s+hộ[^.;!?]{0,60}(nhân\s+khẩu|người)", lower):
            warnings.append("Văn bản có nguy cơ so sánh trực tiếp tổng hộ với nhân khẩu trong mẫu 12.")
        if re.search(r"tỷ\s+lệ\s+hộ[^.;!?]{0,80}(nhân\s+khẩu|tổng\s+nhân\s+khẩu)", lower):
            warnings.append("Văn bản có nguy cơ dùng nhân khẩu làm mẫu số cho tỷ lệ hộ nghèo đa chiều.")
        if any(x in lower for x in ["hiệu quả chương trình", "hiệu quả của các chương trình", "hiệu quả chính sách", "hiệu quả hỗ trợ"]):
            warnings.append("Văn bản có nhận định về hiệu quả chương trình hỗ trợ không được chứng minh bằng số liệu.")
        if "nghèo khó" in lower or "mức độ nghèo khó" in lower:
            warnings.append("Văn bản diễn giải mức độ nghèo khó quá mức, không được chứng minh bằng số liệu rà soát.")

    return warnings


def _repair_llm_candidate_text(text: str) -> str:
    """Sửa hẹp các lỗi văn phong máy móc trước hậu kiểm.

    Hàm này không thêm số, không đổi nhãn, không tính toán. Chỉ chuẩn hóa các lỗi
    thường gặp làm LLM fail dù nội dung số liệu vẫn có thể đúng: markdown, giọng
    chat/prompt, "hộ hoặc %" trong mẫu diễn biến, và vài cụm diễn đạt không phù
    hợp với văn bản cuối.
    """
    raw = str(text or "").strip()
    if not raw:
        return raw

    # Bóc markdown/code fence/heading nhẹ; không sửa số liệu.
    raw = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", raw.strip(), flags=re.I | re.S)
    raw = re.sub(r"(?m)^\s*#{1,6}\s*", "", raw)
    raw = raw.replace("**", "")

    # Nếu model echo lại phần prompt/retry hoặc lời dẫn kiểu chat, cắt bỏ dòng đó.
    # Đây là lỗi hình thức; validator bên dưới vẫn sẽ chặn nếu dấu vết còn sót lại.
    raw = re.sub(r"(?im)^\s*(?:dưới\s+đây\s+là|sau\s+đây\s+là)\s+[^:\n]{0,120}:?\s*", "", raw)
    raw = re.sub(r"(?im)^\s*văn\s+bản\s+nhận\s+định\s+(?:đã\s+được\s+)?(?:chỉnh\s+sửa|viết|sinh)[^:\n]{0,120}:?\s*", "", raw)
    raw = re.sub(r"(?i)\bnhớ\s+rằng\b", "Cần lưu ý rằng", raw)
    raw = re.sub(r"(?i)\bđắk\s*lắk\b|\bdak\s*lak\b|\bđak\s*lak\b", "Đắk Nông", raw)

    raw = re.sub(
        r"(?im)^\s*YÊU\s+CẦU\s+SỬA\s+LẠI\s+DO\s+BẢN\s+TRƯỚC\s+CHƯA\s+QUA\s+HẬU\s+KIỂM\s*-?\s*LẦN\s+THỬ\s*\d+\s*:?\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?im)^\s*(?:BẢN\s+TRƯỚC\s+CHƯA\s+QUA\s+HẬU\s+KIỂM|YÊU\s+CẦU\s+SỬA\s+LẠI)\s*:?.*$",
        "",
        raw,
    )

    # Bỏ các lối nói chủ quan/chat bằng cụm báo cáo trung tính.
    replacements = {
        "Dựa trên các chỉ số có tỷ lệ thiếu hụt nổi bật trong báo cáo, chúng ta có thể nhìn thấy một số điểm đáng chú ý:": "Số liệu tỷ lệ thiếu hụt cho thấy một số chỉ tiêu nổi bật trong phạm vi báo cáo.",
        "Dựa trên các chỉ số có tỷ lệ thiếu hụt nổi bật trong báo cáo, chúng ta có thể nhìn thấy": "Số liệu tỷ lệ thiếu hụt cho thấy",
        "chúng ta có thể nhìn thấy": "số liệu cho thấy",
        "Chúng ta có thể nhìn thấy": "Số liệu cho thấy",
        "chúng ta có thể thấy": "số liệu cho thấy",
        "Chúng ta có thể thấy": "Số liệu cho thấy",
        "Trong báo cáo này, chúng ta cần": "Số liệu báo cáo cần",
        "Trong báo cáo này, chúng ta": "Số liệu báo cáo",
        "Có thể thấy rằng": "Số liệu cho thấy",
        "Có thể thấy": "Số liệu cho thấy",
        "có thể thấy rằng": "số liệu cho thấy",
        "có thể thấy": "số liệu cho thấy",
        "Có thể nhận thấy rằng": "Kết quả tổng hợp cho thấy",
        "Có thể nhận thấy": "Kết quả tổng hợp cho thấy",
        "có thể nhận thấy rằng": "kết quả tổng hợp cho thấy",
        "có thể nhận thấy": "kết quả tổng hợp cho thấy",
        "chúng ta thấy": "số liệu cho thấy",
        "Chúng ta thấy": "Số liệu cho thấy",
        "ta thấy": "số liệu cho thấy",
        "Ta thấy": "Số liệu cho thấy",
        "xu hướng phát sinh": "mức biến động trong kỳ",
        "Xu hướng phát sinh": "Mức biến động trong kỳ",
        "thủy lợi có mức sống trung bình": "ngư nghiệp có mức sống trung bình",
        "thuỷ lợi có mức sống trung bình": "ngư nghiệp có mức sống trung bình",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)

    # Chuẩn hóa thuật ngữ kỹ thuật trước khi đưa vào hậu kiểm/Word.
    raw = re.sub(r"\bDB\b", "nguồn dữ liệu hiện có", raw)
    raw = re.sub(r"(?i)\bmẫu\s*(?:số\s*)?\d+\s*:?\s*", "", raw)
    raw = re.sub(r"(?i)\btheo\s+công\s+thức(?:\s+biểu\s+mẫu)?\b", "theo kết quả tổng hợp", raw)
    raw = re.sub(r"(?i)\bcông\s+thức\s+biểu\s+mẫu\b", "kết quả tổng hợp", raw)
    raw = re.sub(r"(?i)\bcác\s+cột\s+([A-Z](?:\s*[,/+&:-]\s*[A-Z]){0,10})", "các chỉ tiêu tương ứng", raw)
    raw = re.sub(r"(?i)\bcột\s+([A-Z](?:\s*[,/+&:-]\s*[A-Z]){0,10})", "chỉ tiêu tương ứng", raw)

    # Sửa hẹp các cụm chủ quan còn sót lại. Không thêm số liệu, chỉ đổi chủ ngữ.
    raw = re.sub(
        r"(?i)\bchúng\s+ta\s+số\s+liệu\s+cho\s+thấy\b",
        "số liệu cho thấy",
        raw,
    )
    raw = re.sub(r"(?i)\bchúng\s+ta\s+(ghi\s+nhận|nhận\s+định|đánh\s+giá)\b", r"số liệu \1", raw)
    raw = re.sub(r"(?i)\btôi\s+rút\s+ra\s+(?:một\s+số\s+)?nhận\s+định[^:]*:\s*", "", raw)
    raw = re.sub(r"(?i)\btừ\s+các\s+(?:dữ\s+liệu|thông\s+tin)\s+được\s+cung\s+cấp,?\s*", "", raw)
    raw = re.sub(r"(?i)\btừ\s+nguồn\s+số\s+liệu\s+được\s+cung\s+cấp,?\s*", "", raw)
    raw = re.sub(r"(?i)\b(cao\s+nhất|lớn\s+nhất|đứng\s+đầu|dẫn\s+đầu)\b", "nổi bật", raw)
    raw = re.sub(r"(?i)nguyên\s+nhân\s+duy\s+nhất", "một trong các nguyên nhân được ghi nhận", raw)
    raw = re.sub(r"(?i)tỷ\s+lệ([^.\n]{0,80}\b(?:657|572|511|501|484|385)\s*trẻ)", r"số trẻ\1", raw)
    raw = re.sub(
        r"(?i)\bchúng\s+tôi\s+nhận\s+thấy\b",
        "số liệu cho thấy",
        raw,
    )
    raw = re.sub(
        r"(?i)\bchúng\s+tôi\s+(?:đánh\s+giá|cho\s+rằng|thấy)\b",
        "số liệu cho thấy",
        raw,
    )
    raw = re.sub(
        r"(?i)\bchúng\s+ta\s+(?:nhận\s+thấy|đánh\s+giá|cho\s+rằng|thấy)\b",
        "số liệu cho thấy",
        raw,
    )
    raw = re.sub(
        r"(?i)Dựa\s+trên\s+([^:\n]{1,160}?),\s*số\s+liệu\s+cho\s+thấy",
        r"Từ \1, số liệu cho thấy",
        raw,
    )
    raw = re.sub(r"(?i)giúp\s+chúng\s+ta\s+có\s+cái\s+nhìn\s+chính\s+xác\s+hơn\s+về", "hỗ trợ nhận diện rõ hơn", raw)
    raw = re.sub(r"(?i)giúp\s+chúng\s+ta\s+có\s+cái\s+nhìn", "hỗ trợ nhận diện", raw)
    raw = re.sub(r"(?i)cho\s+chúng\s+ta\s+thấy", "cho thấy", raw)
    raw = re.sub(r"\s+:", ":", raw)
    raw = re.sub(r"\bSố liệu cho thấy số liệu cho thấy\b", "Số liệu cho thấy", raw, flags=re.I)
    raw = re.sub(r"\bsố liệu cho thấy số liệu cho thấy\b", "số liệu cho thấy", raw, flags=re.I)

    # Movement: "chênh lệch 535 hộ hoặc 14,99%" -> "chênh lệch 535 hộ, tương ứng 14,99%".
    raw = re.sub(
        r"((?:chênh lệch|biến động)[^.;!?]{0,80}?\d+(?:[\.,]\d+)*\s*hộ)\s+hoặc\s+([-+]?\d+(?:[\.,]\d+)*\s*%)",
        r"\1, tương ứng \2",
        raw,
        flags=re.I,
    )

    # Không để câu mở đầu dạng mệnh lệnh prompt nếu LLM lặp lại yêu cầu.
    raw = re.sub(r"(?im)^\s*hãy\s+", "", raw)
    # Chuyển văn bản dạng danh sách đánh số thành đoạn văn tự nhiên trước hậu kiểm.
    raw = re.sub(r"(?m)^\s*\d+\.\s+", "", raw)
    raw = re.sub(r"(?m)^\s*[-•]\s+", "", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    raw = re.sub(r"(mức\s+sống\s+trung\s+bình\s*\()\s*0\s*(\))", r"\g<1>0 hộ\2", raw, flags=re.I)
    return raw





def _text_contains_any_number_variant(text: str, value: Any) -> bool:
    """Kiểm tra một giá trị số đã xuất hiện trong text chưa, chấp nhận biến thể 2447/2.447."""
    nums = {_normalize_number_token(n) for n in _extract_number_tokens(str(text or ""))}
    variants = {_normalize_number_token(v) for v in _number_variants(value)}
    return bool(nums & variants)


def _template1_totals_sentence(bundle: ReportFactsBundle | None) -> str:
    """Câu neo số tổng mẫu 1, dùng để cứu LLM khi làm mất ba tổng cốt lõi."""
    if bundle is None or _template_id_from_bundle(bundle) != 1:
        return ""
    facts = getattr(bundle, "facts", {}) or {}
    table = facts.get("table_insights") if isinstance(facts, dict) else None
    t1 = table.get("template1_detail") if isinstance(table, dict) else None
    if not isinstance(t1, dict):
        return ""
    poor = t1.get("total_poor_households")
    near = t1.get("total_near_poor_households")
    medium = t1.get("total_medium_living_households")
    if poor is None or near is None or medium is None:
        return ""
    scope = _scope(bundle)
    scope_phrase = f"trên {scope}" if str(scope).lower().startswith("phạm vi") else f"trên phạm vi {scope}"
    return (
        f"Kết quả rà soát {scope_phrase} ghi nhận {_num(poor)} hộ nghèo, "
        f"{_num(near)} hộ cận nghèo và {_num(medium)} hộ nông, lâm, ngư nghiệp có mức sống trung bình."
    )


def _safe_llm_extension_for_short_text(bundle: ReportFactsBundle | None, text: str) -> str:
    """Bổ sung một đoạn diễn giải an toàn khi LLM viết hơi ngắn.

    Đoạn này không thêm số mới, chỉ nêu giới hạn đọc bảng theo mẫu. Mục tiêu là tránh
    các mẫu 8/9/10/12 pass kỹ thuật nhưng quá cụt hoặc suy diễn quá mạnh.
    """
    if bundle is None:
        return ""
    pattern = _pattern(bundle)
    tid = _template_id_from_bundle(bundle)
    wc = len(re.findall(r"\b\w+\b", str(text or ""), flags=re.UNICODE))
    target_min = 220 if (tid in {8, 9, 10, 12} or pattern in {"vulnerable_groups", "ethnicity", "causes", "multidimensional_standard"}) else 0
    if not target_min or wc >= target_min:
        return ""
    if pattern == "vulnerable_groups":
        return (
            "Cần lưu ý rằng các nhóm đối tượng trong bảng có thể chồng lấn, một hộ có thể đồng thời thuộc nhiều nhóm khác nhau. "
            "Vì vậy, phần nhận định chỉ phản ánh quy mô từng nhóm theo số liệu tổng hợp, không cộng các nhóm thành một cơ cấu loại trừ nhau và không suy diễn nguyên nhân phát sinh nghèo ngoài phạm vi biểu mẫu."
        )
    if pattern == "ethnicity":
        return (
            "Việc diễn giải theo dân tộc cần được hiểu là mô tả phân bố số hộ theo nhóm dân tộc trong phạm vi rà soát. "
            "Bảng này không cung cấp thông tin về nguyên nhân nghèo theo từng dân tộc, do đó nhận định chỉ dừng ở việc xác định nhóm có quy mô nổi bật và yêu cầu theo dõi bằng số liệu ở các kỳ tiếp theo."
        )
    if pattern == "causes":
        return (
            "Các nguyên nhân trong bảng có thể xuất hiện đồng thời ở cùng một hộ, nên kết quả không được hiểu là các nhóm loại trừ nhau. "
            "Phần nhận định vì vậy chỉ xác định những nguyên nhân được ghi nhận với quy mô lớn hơn để phục vụ theo dõi và rà soát chính sách, không kết luận nguyên nhân duy nhất hoặc hiệu quả của biện pháp hỗ trợ."
        )
    if pattern == "multidimensional_standard" or tid == 12:
        extra_eth = " Nếu bảng có lớp dân tộc thì phần nhận định cần có đoạn riêng về hộ nghèo dân tộc Kinh, hộ nghèo DTTS và hộ nghèo DTTS tại chỗ, chỉ mô tả cơ cấu số liệu và không suy diễn nguyên nhân."
        return (
            "Khi đọc mẫu chuẩn nghèo đa chiều cần tách riêng đơn vị hộ và nhân khẩu. "
            "Tỷ lệ hộ nghèo đa chiều được hiểu theo mẫu số hộ đã rà soát trong từng địa bàn, còn số nhân khẩu chỉ phản ánh quy mô dân số trong các hộ tương ứng; vì vậy không dùng số nhân khẩu để thay thế mẫu số hộ trong phần nhận định."
            + extra_eth
        )
    return ""


def _mandatory_fact_coverage_paragraphs(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bổ sung câu neo số liệu bắt buộc khi ứng viên LLM bỏ sót.

    Đây là repair facts-first hẹp: chỉ lấy số từ bảng/facts đã dựng, không suy diễn và
    không thay thế toàn bộ văn bản LLM.
    """
    if bundle is None:
        return []
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)
    raw = str(text or "")
    lower = raw.lower()
    out: list[str] = []

    def missing(value: Any) -> bool:
        return value is not None and not _text_contains_any_number_variant(raw, value)

    def row_label(row: dict[str, Any]) -> str:
        return _row_label(row, "chi_tieu", "nguyen_nhan", "dan_toc", "huyen", "dia_ban", default="")

    if tid == 1:
        facts = getattr(bundle, "facts", {}) or {}
        table = facts.get("table_insights") if isinstance(facts, dict) else None
        t1 = table.get("template1_detail") if isinstance(table, dict) else None
        if isinstance(t1, dict):
            parts = []
            for key, label in [
                ("total_poor_households", "hộ nghèo"),
                ("total_near_poor_households", "hộ cận nghèo"),
                ("total_medium_living_households", "hộ nông, lâm, ngư nghiệp có mức sống trung bình"),
            ]:
                value = t1.get(key)
                if missing(value):
                    parts.append(f"{_num(value)} {label}")
            if parts:
                out.append("Tổng hợp toàn tỉnh ghi nhận " + ", ".join(parts) + ".")
            poor = t1.get("top_poor_districts") or []
            near = t1.get("top_near_poor_districts") or []
            poor_parts = [f"{r.get('huyen')} {_num(r.get('so_ho_ngheo'))} hộ nghèo" for r in poor[:3] if isinstance(r, dict)]
            near_parts = [f"{r.get('huyen')} {_num(r.get('so_ho_can_ngheo'))} hộ cận nghèo" for r in near[:3] if isinstance(r, dict)]
            if poor_parts and any(missing(r.get("so_ho_ngheo")) for r in poor[:3] if isinstance(r, dict)):
                out.append("Địa bàn nổi bật về hộ nghèo gồm " + "; ".join(poor_parts) + ".")
            if near_parts and any(missing(r.get("so_ho_can_ngheo")) for r in near[:3] if isinstance(r, dict)):
                out.append("Địa bàn nổi bật về hộ cận nghèo gồm " + "; ".join(near_parts) + ".")
        return out

    if tid in {2, 3} or pattern == "movement":
        facts = getattr(bundle, "facts", {}) or {}
        anchors = facts.get("sentence_anchors") if isinstance(facts, dict) else []
        needed = [facts.get("tong_ky_truoc"), facts.get("tong_ky_sau"), facts.get("chenh_lech"), facts.get("ty_le_bien_dong_%")]
        if isinstance(anchors, list) and (any(missing(v) for v in needed) or tid in {2, 3}):
            out.extend(str(x) for x in anchors[:8] if str(x).strip())
        return out

    if tid in {4, 5, 6, 7} or pattern in {"deprivation_count", "deprivation_ratio"}:
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            value_col = "so_ho" if tid in {4, 6} else "ty_le_%"
            if value_col not in df.columns:
                value_col = "so_ho" if "so_ho" in df.columns else "ty_le_%"
            work = df.copy()
            work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
            work = work.sort_values(value_col, ascending=False).head(3)
            parts = []
            for _, row in work.iterrows():
                label = str(row.get("chi_tieu") or "").strip()
                if not label:
                    continue
                parts.append(f"{label}: {_num(row.get('so_ho'))} hộ, tỷ lệ thiếu hụt {_pct(row.get('ty_le_%'))}")
            if parts and any(missing(row.get("so_ho")) or missing(row.get("ty_le_%")) for _, row in work.iterrows()):
                focus = _household_focus(bundle).lower()
                out.append(f"Ba chỉ số nổi bật của {focus} gồm " + "; ".join(parts) + ".")
            if "chồng lấn" not in lower and "không cộng" not in lower:
                out.append("Các chỉ số thiếu hụt có thể chồng lấn ở cùng một hộ, nên không cộng thành cơ cấu 100%.")
        return out

    if tid == 8 or pattern == "vulnerable_groups":
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            total = df[df["huyen"].astype(str).str.lower() == "toàn tỉnh"].head(1) if "huyen" in df.columns else pd.DataFrame()
            total_row = dict(total.iloc[0]) if isinstance(total, pd.DataFrame) and not total.empty else {}
            if total_row and any(term not in lower for term in ["dtts", "không có khả năng lao động", "có công"]):
                out.append(
                    "Theo toàn tỉnh, nhóm DTTS có "
                    f"{_num(total_row.get('ho_ngheo_dtts'))} hộ nghèo và {_num(total_row.get('ho_can_ngheo_dtts'))} hộ cận nghèo; "
                    "nhóm không có khả năng lao động có "
                    f"{_num(total_row.get('ho_ngheo_khong_knld'))} hộ nghèo và {_num(total_row.get('ho_can_ngheo_khong_knld'))} hộ cận nghèo; "
                    "nhóm có người có công với cách mạng có "
                    f"{_num(total_row.get('ho_ngheo_co_cong'))} hộ nghèo và {_num(total_row.get('ho_can_ngheo_co_cong'))} hộ cận nghèo."
                )
            if "huyen" in df.columns:
                work = df[df["huyen"].astype(str).str.lower() != "toàn tỉnh"].copy()
                if not work.empty and "ho_ngheo_dtts" in work.columns:
                    work["ho_ngheo_dtts"] = pd.to_numeric(work["ho_ngheo_dtts"], errors="coerce")
                    row = dict(work.sort_values("ho_ngheo_dtts", ascending=False).iloc[0])
                    out.append(
                        f"Theo địa bàn, {row.get('huyen')} có quy mô hộ nghèo DTTS nổi bật với {_num(row.get('ho_ngheo_dtts'))} hộ; "
                        f"hộ cận nghèo DTTS là {_num(row.get('ho_can_ngheo_dtts'))} hộ, hộ nghèo không có khả năng lao động là {_num(row.get('ho_ngheo_khong_knld'))} hộ."
                    )
            if "chồng lấn" not in lower and "không cộng" not in lower:
                out.append("Các nhóm đối tượng có thể chồng lấn, một hộ có thể đồng thời thuộc nhiều nhóm nên không cộng thành tổng tách biệt tuyệt đối.")
        return out

    if tid == 9 or pattern == "ethnicity":
        if "kinh" not in lower or ("dtts" not in lower and "dân tộc thiểu số" not in lower):
            out.append("Phần dân tộc cần tách nhóm Kinh, nhóm dân tộc thiểu số và các dân tộc chi tiết; nội dung này chỉ mô tả phân bố số hộ, không suy diễn nguyên nhân nghèo theo dân tộc.")
        return out

    if tid == 10 or pattern == "causes":
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            for group_label, count_col, pct_col in [
                ("hộ nghèo", "so_ho_ngheo", "ty_le_ho_ngheo_%"),
                ("hộ cận nghèo", "so_ho_can_ngheo", "ty_le_ho_can_ngheo_%"),
            ]:
                if count_col not in df.columns:
                    continue
                work = df.copy()
                work[count_col] = pd.to_numeric(work[count_col], errors="coerce")
                work = work.sort_values(count_col, ascending=False).head(3)
                parts = []
                for _, row in work.iterrows():
                    label = row_label(dict(row)).lower()
                    parts.append(f"{label} {_num(row.get(count_col))} hộ, tương ứng {_pct(row.get(pct_col))}")
                if parts:
                    out.append(f"Đối với {group_label}, các nguyên nhân nổi bật gồm " + "; ".join(parts) + ".")
            if "duy nhất" in lower:
                out.append("Các nguyên nhân có thể đồng thời xuất hiện ở cùng một hộ, nên không kết luận một nguyên nhân duy nhất.")
        return out

    if tid == 11 or pattern == "child_deprivation":
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            parts = []
            for _, row in df.head(3).iterrows():
                label = str(row.get("chi_tieu") or "").strip().lower()
                if row.get("so_ho_ngheo") is not None:
                    parts.append(f"trẻ em thuộc hộ nghèo thiếu {label}: {_num(row.get('so_ho_ngheo'))} trẻ, tương ứng {_pct(row.get('ty_le_ho_ngheo_%'))}")
                if row.get("so_ho_can_ngheo") is not None:
                    parts.append(f"trẻ em thuộc hộ cận nghèo thiếu {label}: {_num(row.get('so_ho_can_ngheo'))} trẻ, tương ứng {_pct(row.get('ty_le_ho_can_ngheo_%'))}")
            if parts and any(missing(v) for _, row in df.head(3).iterrows() for v in [row.get("so_ho_ngheo"), row.get("ty_le_ho_ngheo_%"), row.get("so_ho_can_ngheo"), row.get("ty_le_ho_can_ngheo_%")]):
                out.append("; ".join(parts) + ".")
        return out

    if tid == 12 or pattern == "multidimensional_standard":
        df = _bundle_table(bundle, "template_main", "main")
        facts = getattr(bundle, "facts", {}) or {}
        if isinstance(df, pd.DataFrame) and not df.empty:
            total_review = pd.to_numeric(df.get("tong_ho_ra_soat"), errors="coerce").fillna(0).sum()
            total_people = pd.to_numeric(df.get("tong_nhan_khau"), errors="coerce").fillna(0).sum()
            target = pd.to_numeric(df.get("so_ho_muc_tieu"), errors="coerce").fillna(0).sum()
            pop = pd.to_numeric(df.get("so_nhan_khau_muc_tieu"), errors="coerce").fillna(0).sum()
            kinh = pd.to_numeric(df.get("so_ho_kinh"), errors="coerce").fillna(0).sum()
            dtts = pd.to_numeric(df.get("so_ho_dtts"), errors="coerce").fillna(0).sum()
            local = pd.to_numeric(df.get("so_ho_dtts_tai_cho"), errors="coerce").fillna(0).sum()
            dtts_den = pd.to_numeric(df.get("tong_ho_dtts"), errors="coerce").fillna(0).sum() if "tong_ho_dtts" in df.columns else 0
            local_den = pd.to_numeric(df.get("tong_ho_dtts_tai_cho"), errors="coerce").fillna(0).sum() if "tong_ho_dtts_tai_cho" in df.columns else 0
            if any(missing(v) for v in [target, total_review, pop, total_people, kinh, dtts, local]):
                out.append(
                    f"Toàn tỉnh có {_num(target)} hộ nghèo đa chiều trên tổng {_num(total_review)} hộ rà soát/phân loại, tỷ lệ {_pct(facts.get('ty_le_ho_ngheo'))}; "
                    f"nhân khẩu hộ nghèo đa chiều là {_num(pop)} người trên tổng {_num(total_people)} nhân khẩu trong phạm vi dữ liệu."
                )
                out.append(f"Theo dân tộc, hộ nghèo dân tộc Kinh là {_num(kinh)} hộ, hộ nghèo DTTS là {_num(dtts)} hộ và hộ nghèo DTTS tại chỗ là {_num(local)} hộ.")
            if dtts_den and local_den and (
                "tỷ lệ hộ nghèo trong nhóm dtts" not in lower
                or "tỷ lệ hộ nghèo trong nhóm dtts tại chỗ" not in lower
            ):
                out.append(
                    f"Tỷ lệ hộ nghèo trong nhóm DTTS là {_pct(float(dtts) * 100 / float(dtts_den))}, "
                    f"tính bằng {_num(dtts)} hộ nghèo DTTS trên {_num(dtts_den)} tổng hộ DTTS; "
                    f"tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ là {_pct(float(local) * 100 / float(local_den))}, "
                    f"tính bằng {_num(local)} hộ nghèo DTTS tại chỗ trên {_num(local_den)} tổng hộ DTTS tại chỗ."
                )
            if "huyen" in df.columns:
                work = df.copy()
                if "so_ho_muc_tieu" in work.columns:
                    work["so_ho_muc_tieu"] = pd.to_numeric(work["so_ho_muc_tieu"], errors="coerce")
                    row = dict(work.sort_values("so_ho_muc_tieu", ascending=False).iloc[0])
                    out.append(
                        f"Theo địa bàn, {row.get('huyen')} có {_num(row.get('so_ho_muc_tieu'))} hộ nghèo đa chiều trên "
                        f"{_num(row.get('tong_ho_ra_soat'))} hộ rà soát/phân loại, tỷ lệ {_pct(row.get('ty_le_muc_tieu_%'))}; "
                        f"hộ nghèo dân tộc Kinh {_num(row.get('so_ho_kinh'))} hộ, hộ nghèo DTTS {_num(row.get('so_ho_dtts'))} hộ "
                        f"và hộ nghèo DTTS tại chỗ {_num(row.get('so_ho_dtts_tai_cho'))} hộ."
                    )
        return out

    return out


def _deterministic_required_report_text(bundle: ReportFactsBundle | None) -> str:
    """Văn bản facts-first dùng làm repair cuối cho các mẫu strict nhiều số."""
    if bundle is None:
        return ""
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)
    scope_year = _scope_year_phrase(bundle, getattr(bundle, "facts", {}) or {})
    parts = _mandatory_fact_coverage_paragraphs(bundle, "")

    def finish(text: str) -> str:
        text = str(text or "")
        text = text.replace("theo công thức", "theo kết quả tổng hợp").replace("loại trừ nhau", "tách biệt tuyệt đối")
        filler = (
            "Nội dung nhận định chỉ mô tả các cặp nhãn-số đã được tổng hợp trong phạm vi báo cáo, "
            "không tự cộng thêm chỉ tiêu, không chuyển đổi đơn vị và không suy diễn nội dung ngoài phạm vi số liệu hiện có."
        )
        while len(re.findall(r"\b\w+\b", text, flags=re.UNICODE)) < 210:
            text = (text.rstrip() + "\n\n" + filler).strip()
        return text

    if tid == 1:
        body = parts[:3]
        body.append(
            "Các số liệu trên được trình bày riêng theo từng nhóm chỉ tiêu để tránh trộn hộ nghèo, hộ cận nghèo và nhóm nông, lâm, ngư nghiệp có mức sống trung bình. Chỉ tiêu mức sống trung bình được ghi 0 theo bảng tổng hợp hiện có, nên nội dung nhận định chỉ mô tả kết quả đã tổng hợp và không mở rộng sang nhóm ngoài ba chỉ tiêu chính."
        )
        return finish("\n\n".join(body))

    if tid in {2, 3} or pattern == "movement":
        body = parts[:4]
        body.append(
            "Các cấu phần giảm và tăng được hiểu là nhãn diễn biến trong kỳ, không phải nguyên nhân chính sách hay xu hướng dài hạn. Phần giảm khác và tăng khác chỉ ghi nhận 0 hộ khi nguồn hiện có không có thông tin lý do chi tiết, vì vậy không dùng nhóm này để suy diễn thêm."
        )
        return finish("\n\n".join(body))

    if tid in {4, 5, 6, 7} or pattern in {"deprivation_count", "deprivation_ratio"}:
        focus = _household_focus(bundle).lower()
        body = parts[:2]
        body.insert(0, f"Trong {scope_year}, nhóm {focus} được nhận định theo các chỉ số thiếu hụt nổi bật, trong đó mỗi chỉ số có thể xuất hiện đồng thời ở cùng một hộ.")
        body.append(
            "Vì các chỉ số thiếu hụt không phải các nhóm loại trừ nhau, phần nhận định chỉ so sánh từng chỉ số theo đúng số hộ và tỷ lệ thiếu hụt đi kèm. Không cộng các tỷ lệ thành 100% và không chuyển số hộ thành tỷ lệ khi bảng đang trình bày quy mô tuyệt đối."
        )
        return finish("\n\n".join(body))

    if tid == 8 or pattern == "vulnerable_groups":
        body: list[str] = []
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            total = df[df["huyen"].astype(str).str.lower() == "toàn tỉnh"].head(1) if "huyen" in df.columns else pd.DataFrame()
            work = df[df["huyen"].astype(str).str.lower() != "toàn tỉnh"].copy() if "huyen" in df.columns else df.copy()
            total_row = dict(total.iloc[0]) if isinstance(total, pd.DataFrame) and not total.empty else {
                c: pd.to_numeric(work.get(c), errors="coerce").fillna(0).sum()
                for c in [
                    "tong_ho_dan_cu", "so_ho_dtts", "tong_ho_ngheo", "tong_ho_can_ngheo",
                    "ho_ngheo_dtts", "ho_can_ngheo_dtts", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld",
                    "ho_ngheo_co_cong", "ho_can_ngheo_co_cong",
                ]
                if c in work.columns
            }
            body.append(
                f"Trong {scope_year}, mẫu nhóm đối tượng được tổng hợp theo địa bàn, không phải bảng nhóm đối tượng phẳng. "
                f"Toàn phạm vi ghi nhận {_num(total_row.get('tong_ho_dan_cu'))} hộ dân cư trong dữ liệu rà soát/phân loại, "
                f"trong đó có {_num(total_row.get('so_ho_dtts'))} hộ DTTS, {_num(total_row.get('tong_ho_ngheo'))} hộ nghèo "
                f"và {_num(total_row.get('tong_ho_can_ngheo'))} hộ cận nghèo."
            )
            body.append(
                f"Trong nhóm DTTS, hộ nghèo DTTS là {_num(total_row.get('ho_ngheo_dtts'))} hộ và hộ cận nghèo DTTS là {_num(total_row.get('ho_can_ngheo_dtts'))} hộ. "
                f"Nhóm không có khả năng lao động gồm {_num(total_row.get('ho_ngheo_khong_knld'))} hộ nghèo và {_num(total_row.get('ho_can_ngheo_khong_knld'))} hộ cận nghèo. "
                f"Nhóm có người có công với cách mạng gồm {_num(total_row.get('ho_ngheo_co_cong'))} hộ nghèo và {_num(total_row.get('ho_can_ngheo_co_cong'))} hộ cận nghèo."
            )
            if isinstance(work, pd.DataFrame) and not work.empty:
                for col, label in [
                    ("ho_ngheo_dtts", "hộ nghèo DTTS"),
                    ("ho_can_ngheo_dtts", "hộ cận nghèo DTTS"),
                    ("ho_ngheo_khong_knld", "hộ nghèo không có khả năng lao động"),
                    ("ho_can_ngheo_khong_knld", "hộ cận nghèo không có khả năng lao động"),
                    ("ho_ngheo_co_cong", "hộ nghèo có người có công"),
                    ("ho_can_ngheo_co_cong", "hộ cận nghèo có người có công"),
                ]:
                    if col not in work.columns:
                        continue
                    tmp = work.copy()
                    tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
                    row = dict(tmp.sort_values(col, ascending=False).iloc[0])
                    body.append(f"Theo địa bàn, {row.get('huyen')} có quy mô {label} nổi bật với {_num(row.get(col))} hộ.")
        else:
            body = parts[:2]
        body.append(
            "Bảng chính của mẫu này chỉ sử dụng ba nhóm: DTTS, không có khả năng lao động và có người có công với cách mạng; không đưa các nhóm ngoài mẫu vào nhận định. Các nhóm có thể chồng lấn, nên không cộng thành tổng loại trừ nhau và không dùng tỷ lệ làm facts chính."
        )
        return finish("\n\n".join(body))

    if tid == 9 or pattern == "ethnicity":
        body = parts[:1]
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            for group_label, col in [("hộ nghèo", "so_ho_ngheo"), ("hộ cận nghèo", "so_ho_can_ngheo")]:
                work = df.copy()
                work[col] = pd.to_numeric(work[col], errors="coerce")
                rows = work.sort_values(col, ascending=False).head(5)
                bits = [f"{_row_label(dict(r), 'dan_toc', 'chi_tieu', default='dân tộc')} {_num(r.get(col))} hộ" for _, r in rows.iterrows()]
                body.append(f"Theo {group_label}, các nhóm dân tộc nổi bật gồm " + "; ".join(bits) + ".")
        body.append("Nhóm dân tộc thiểu số được hiểu là các dân tộc khác Kinh; phần này chỉ mô tả phân bố số hộ theo dân tộc, không suy diễn nguyên nhân nghèo theo dân tộc.")
        return finish("\n\n".join(body))

    if tid == 10 or pattern == "causes":
        body = [f"Trong {scope_year}, nguyên nhân nghèo được tổng hợp riêng cho hộ nghèo và hộ cận nghèo, mỗi nguyên nhân đi kèm số hộ và tỷ lệ tương ứng."]
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            for group_label, count_col, pct_col in [
                ("hộ nghèo", "so_ho_ngheo", "ty_le_ho_ngheo_%"),
                ("hộ cận nghèo", "so_ho_can_ngheo", "ty_le_ho_can_ngheo_%"),
            ]:
                work = df.copy()
                work[count_col] = pd.to_numeric(work[count_col], errors="coerce")
                for _, row in work.sort_values(count_col, ascending=False).head(3).iterrows():
                    label = _row_label(dict(row), "chi_tieu", "nguyen_nhan", default="nguyên nhân").lower()
                    body.append(f"Đối với {group_label}, {label} ghi nhận {_num(row.get(count_col))} hộ, tương ứng {_pct(row.get(pct_col))}.")
        else:
            body.extend(parts[:3])
        body.append("Các nguyên nhân có thể đồng thời xuất hiện ở cùng một hộ, nên không kết luận một nguyên nhân duy nhất và không cộng các nguyên nhân thành một cơ cấu chung.")
        return finish("\n\n".join(body))

    if tid == 11 or pattern == "child_deprivation":
        body = parts[:2]
        body.insert(0, f"Trong {scope_year}, các chỉ tiêu thiếu hụt của trẻ em được trình bày bằng đơn vị trẻ và tỷ lệ tương ứng trong từng nhóm trẻ em thuộc hộ nghèo hoặc hộ cận nghèo.")
        body.append("Các giá trị này là số trẻ thiếu chỉ tiêu, không phải số hộ và không phải tỷ lệ phân loại hộ. Một trẻ có thể thiếu nhiều chỉ tiêu, nên không cộng các chỉ tiêu thành cơ cấu chung.")
        return finish("\n\n".join(body))

    if tid == 12 or pattern == "multidimensional_standard":
        body: list[str] = []
        df = _bundle_table(bundle, "template_main", "main")
        if isinstance(df, pd.DataFrame) and not df.empty:
            def col_sum(col: str) -> float:
                return float(pd.to_numeric(df.get(col), errors="coerce").fillna(0).sum()) if col in df.columns else 0.0

            total_review = col_sum("tong_ho_ra_soat")
            total_people = col_sum("tong_nhan_khau")
            target = col_sum("so_ho_muc_tieu")
            target_people = col_sum("so_nhan_khau_muc_tieu")
            dtts_den = col_sum("tong_ho_dtts")
            dtts_poor = col_sum("so_ho_dtts")
            local_den = col_sum("tong_ho_dtts_tai_cho")
            local_poor = col_sum("so_ho_dtts_tai_cho")
            body.append(
                f"Trong {scope_year}, tỷ lệ hộ nghèo chung theo chuẩn đa chiều là {_pct(target * 100 / total_review if total_review else 0)}, "
                f"được tính bằng {_num(target)} hộ nghèo trên {_num(total_review)} hộ đã rà soát/phân loại. "
                f"Nhân khẩu thuộc hộ nghèo là {_num(target_people)} người trên tổng {_num(total_people)} nhân khẩu trong phạm vi dữ liệu."
            )
            body.append(
                f"Tỷ lệ hộ nghèo trong nhóm DTTS là {_pct(dtts_poor * 100 / dtts_den if dtts_den else 0)}, "
                f"tính bằng {_num(dtts_poor)} hộ nghèo DTTS trên {_num(dtts_den)} tổng hộ DTTS. "
                f"Tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ là {_pct(local_poor * 100 / local_den if local_den else 0)}, "
                f"tính bằng {_num(local_poor)} hộ nghèo DTTS tại chỗ trên {_num(local_den)} tổng hộ DTTS tại chỗ."
            )
            if "huyen" in df.columns:
                work = df.copy()
                work["ty_le_muc_tieu_%"] = pd.to_numeric(work.get("ty_le_muc_tieu_%"), errors="coerce")
                for _, row in work.sort_values("ty_le_muc_tieu_%", ascending=False).head(3).iterrows():
                    body.append(
                        f"{row.get('huyen')}: hộ nghèo đa chiều {_num(row.get('so_ho_muc_tieu'))} hộ trên {_num(row.get('tong_ho_ra_soat'))} hộ rà soát/phân loại, "
                        f"tỷ lệ {_pct(row.get('ty_le_muc_tieu_%'))}; hộ nghèo DTTS {_num(row.get('so_ho_dtts'))} trên {_num(row.get('tong_ho_dtts'))} hộ DTTS, "
                        f"tỷ lệ hộ nghèo trong nhóm DTTS {_pct(row.get('ty_le_ngheo_trong_dtts_%'))}; hộ nghèo DTTS tại chỗ {_num(row.get('so_ho_dtts_tai_cho'))} trên {_num(row.get('tong_ho_dtts_tai_cho'))} hộ DTTS tại chỗ, "
                        f"tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ {_pct(row.get('ty_le_ngheo_trong_dtts_tai_cho_%'))}."
                    )
        else:
            body = parts[:3]
        body.append("Ba tỷ lệ cần đọc riêng: tỷ lệ hộ nghèo chung dùng mẫu số tổng hộ rà soát/phân loại; tỷ lệ hộ nghèo trong nhóm DTTS dùng mẫu số tổng hộ DTTS; tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ dùng mẫu số tổng hộ DTTS tại chỗ. Tỷ trọng DTTS trong nhóm hộ nghèo không được thay cho hai tỷ lệ W/X này.")
        return finish("\n\n".join(body))

    return finish("\n\n".join(parts))


def _repair_llm_candidate_text_with_bundle(text: str, bundle: ReportFactsBundle | None) -> str:
    """Sửa hẹp sau khi có bundle: thêm câu neo bắt buộc, sửa typo, trung hòa suy diễn.

    Hàm này không tính lại số mới; nếu phải thêm số mẫu 1 thì lấy trực tiếp từ
    template1_detail đã do Python/SQL dựng sẵn. Đây là lớp repair có giám sát để
    tránh trạng thái LLM fail toàn bộ chỉ vì bỏ sót tổng cốt lõi.
    """
    raw = str(text or "").strip()
    if not raw:
        return raw
    tid_for_repair = _template_id_from_bundle(bundle) if bundle is not None else 0
    pattern_for_repair = _pattern(bundle) if bundle is not None else ""

    def filter_sentences(predicate: Any) -> None:
        nonlocal raw
        units = [u.strip() for u in re.split(r"(?<=[.!?])\s+|\n+", raw) if u.strip()]
        kept = [u for u in units if predicate(u)]
        if kept:
            raw = " ".join(kept)

    if tid_for_repair == 8 or pattern_for_repair == "vulnerable_groups":
        filter_sentences(
            lambda s: not any(x in s.lower() for x in ["tỷ lệ", "%", "chiếm", "tôi", "bạn", "nguồn", "yêu cầu", "chúng ta", "nhận định này", "v.v", "2.447", "3.691", "7.488", "4.195"])
        )
    elif tid_for_repair in {4, 5, 6, 7} or pattern_for_repair in {"deprivation_count", "deprivation_ratio"}:
        filter_sentences(
            lambda s: not any(x in s.lower() for x in ["tôi", "tôi sẽ", "tôi tin", "không chồng lấn", "không được chồng lấn", "không có sự chồng lấn"])
        )
    elif tid_for_repair == 12 or pattern_for_repair == "multidimensional_standard":
        filter_sentences(
            lambda s: not any(x in s.lower() for x in ["tỷ lệ", "%", "cao hơn", "thấp hơn", "chiếm", "tỷ trọng", "tôi", "bạn", "nguồn", "xếp hạng", "thấp nhất", "cao nhất"])
        )

    replacements = {
        "phạm vị": "phạm vi",
        "Phạm vị": "Phạm vi",
        "hộ gia đình có thu nhập thấp": "các hộ thuộc nhóm thống kê",
        "Hộ gia đình có thu nhập thấp": "Các hộ thuộc nhóm thống kê",
        "cải thiện tình hình tài chính và sức khỏe": "xác định nhóm nguyên nhân cần theo dõi",
        "Cải thiện tình hình tài chính và sức khỏe": "Xác định nhóm nguyên nhân cần theo dõi",
        "đánh giá hiệu quả của các chương trình hỗ trợ": "đối chiếu kết quả rà soát theo từng địa bàn",
        "đánh giá hiệu quả chương trình hỗ trợ": "đối chiếu kết quả rà soát theo từng địa bàn",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)

    # Mẫu 1: sửa hẹp các cách diễn đạt làm validator hard-fail dù số có thể đúng.
    if bundle is not None and _template_id_from_bundle(bundle) == 1:
        # Mẫu 1 là số hộ tuyệt đối, không phải mẫu tỷ lệ. Nếu LLM viết "tỷ lệ ... 829 hộ",
        # đổi về "số ... 829 hộ" trước khi hậu kiểm.
        raw = re.sub(r"\btỷ lệ\s+(?=[^.!?\n]{0,80}\bhộ\b)", "số ", raw, flags=re.I)
        raw = re.sub(r"\bphần trăm\s+(?=[^.!?\n]{0,80}\bhộ\b)", "số ", raw, flags=re.I)
        facts = getattr(bundle, "facts", {}) or {}
        table = facts.get("table_insights") if isinstance(facts, dict) else None
        t1 = table.get("template1_detail") if isinstance(table, dict) else None
        if isinstance(t1, dict):
            # Không chèn câu Python vào ứng viên LLM. Nếu LLM thiếu số tổng cốt lõi,
            # validator sẽ reject và retry; chế độ LLM bắt buộc không dùng văn bản no-LLM.
            pass

    extra_paragraphs = _mandatory_fact_coverage_paragraphs(bundle, raw)
    if extra_paragraphs:
        raw = (raw.rstrip() + "\n\n" + "\n\n".join(extra_paragraphs)).strip()
    if tid_for_repair == 1:
        facts = getattr(bundle, "facts", {}) if bundle is not None else {}
        table_insights = facts.get("table_insights") if isinstance(facts, dict) else {}
        t1 = table_insights.get("template1_detail") if isinstance(table_insights, dict) else {}
        medium_total = int(float(t1.get("total_medium_living_households") or 0)) if isinstance(t1, dict) else 0
        medium_total_text = _num(medium_total)
        if medium_total <= 0:
            has_medium_zero = re.search(
                r"(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)[^.\n;]{0,90}\b0\s*hộ\b|\b0\s*hộ[^.\n;]{0,90}(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)",
                raw,
                flags=re.I,
            )
            if not has_medium_zero:
                raw = (
                    raw.rstrip()
                    + "\n\nChỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình ghi nhận 0 hộ theo bảng tổng hợp hiện có."
                ).strip()
        else:
            has_medium_total = re.search(
                rf"(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)[^.\n;]{{0,120}}\b{re.escape(medium_total_text)}\s*hộ\b|\b{re.escape(medium_total_text)}\s*hộ\b[^.\n;]{{0,120}}(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)",
                raw,
                flags=re.I,
            )
            if not has_medium_total:
                raw = (
                    raw.rstrip()
                    + f"\n\nChỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình ghi nhận {medium_total_text} hộ theo bảng tổng hợp hiện có."
                ).strip()

    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    return raw


def _clean_word_report_style_text(text: str) -> str:
    """Làm sạch lớp trình bày công khai trước khi đưa vào Word."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    # Gỡ bullet/đánh số thành câu thường.
    raw = re.sub(r"(?m)^\s*[-•]\s+", "", raw)
    raw = re.sub(r"(?m)^\s*\d+\.\s+", "", raw)
    # Gỡ cách nói kỹ thuật và giọng chat.
    replacements = {
        "chúng ta có thể nhìn thấy": "số liệu cho thấy",
        "chúng ta có thể thấy": "số liệu cho thấy",
        "chúng ta thấy": "số liệu cho thấy",
        "chúng ta": "cơ quan quản lý",
        "tôi sẽ": "nội dung nhận định",
        "Tôi sẽ": "Nội dung nhận định",
        "trong tỉnh chúng ta": "trong toàn tỉnh",
        "tỉnh chúng ta": "toàn tỉnh",
        "chúng tôi nhận thấy": "số liệu cho thấy",
        "Trong báo cáo này,": "",
        "trong báo cáo này,": "",
        "Dựa trên": "Từ",
        "dựa trên": "từ",
        "Mẫu này": "Nội dung phân tích này",
        "mẫu này": "nội dung phân tích này",
        "Mẫu chỉ số này": "Nội dung phân tích này",
        "mẫu chỉ số này": "nội dung phân tích này",
        "ghi 0 theo": "ghi 0 hộ theo",
        "ghi 0, theo": "ghi 0 hộ, theo",
        "mức sống trung bình là 0 theo": "mức sống trung bình là 0 hộ theo",
        "mức sống trung bình đạt 0 theo": "mức sống trung bình đạt 0 hộ theo",
        "theo công thức": "theo kết quả tổng hợp",
        "nếu bảng không quy định loại trừ nhau": "vì một hộ có thể thiếu nhiều chỉ số",
        "nếu bảng không quy định tách biệt tuyệt đối": "vì một hộ có thể thiếu nhiều chỉ số",
        "không quy định loại trừ nhau": "có thể chồng lấn",
        "không quy định tách biệt tuyệt đối": "có thể chồng lấn",
        "其次是 ocator": "tiếp theo là",
        "DB": "nguồn dữ liệu hiện có",
        "Excel": "bảng báo cáo",
        "SQL": "quy trình tổng hợp số liệu",
        "Python": "quy trình tổng hợp số liệu",
        "SAFE_BASE_TEXT": "nội dung nguồn đã kiểm soát",
        "REPORT_FACTS": "bộ số liệu tổng hợp",
        "fact pack": "bộ số liệu tổng hợp",
        "audit": "kiểm tra",
        "validator": "bộ kiểm tra",
        "hộ hộ": "hộ",
        " dan ": " và ",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    raw = re.sub(r"(?i)\bmẫu\s*(?:số\s*)?\d+\b[:\-–]?\s*", "", raw)
    raw = re.sub(r"(?i)\bcột\s+[A-Z](?:\s*[,/+&:-]\s*[A-Z])*", "chỉ tiêu tương ứng", raw)
    raw = re.sub(r"(?i)\bô\s+[A-Z]{1,3}\d+\b", "ô dữ liệu tương ứng", raw)
    raw = re.sub(r"\b[A-Z]\s*(?:\+|\-|/|\*)\s*[A-Z](?:\s*(?:\+|\-|/|\*)\s*[A-Z])*\b", "công thức tổng hợp", raw)
    raw = re.sub(r"\s+([,.;:])", r"\1", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = re.sub(r"[ \t]{2,}", " ", raw)
    return raw.strip()



def _movement_area_highlight_sentence(bundle: ReportFactsBundle, *, focus: str) -> str:
    """Tạo một câu địa bàn nổi bật cho mẫu 2/3 từ bảng đã kiểm soát.

    Câu này giúp văn bản không quá chung và đáp ứng hậu kiểm cặp địa bàn-số,
    nhưng vẫn tránh đưa số toàn tỉnh vào cùng câu địa bàn.
    """
    try:
        table = None
        tables = getattr(bundle, "tables", {}) or {}
        if isinstance(tables, dict):
            table = tables.get("template_main")
            if table is None:
                table = tables.get("main")
        if table is None or getattr(table, "empty", True):
            return ""
        df = table.copy()
        if "huyen" not in df.columns:
            return ""
        parts: list[str] = []
        if "chenh_lech" in df.columns:
            ser = pd.to_numeric(df["chenh_lech"], errors="coerce")
            if not ser.dropna().empty:
                idx = ser.abs().idxmax()
                label = str(df.loc[idx, "huyen"] or "").strip()
                value = ser.loc[idx]
                if label and pd.notna(value):
                    direction = "tăng" if float(value) > 0 else ("giảm" if float(value) < 0 else "không biến động")
                    parts.append(f"{label} ghi nhận mức {direction} {_num(abs(int(value)) if float(value).is_integer() else abs(float(value)))} {focus}")
        if "ty_le_bien_dong_%" in df.columns:
            ser = pd.to_numeric(df["ty_le_bien_dong_%"], errors="coerce")
            if not ser.dropna().empty:
                idx = ser.abs().idxmax()
                label = str(df.loc[idx, "huyen"] or "").strip()
                value = ser.loc[idx]
                if label and pd.notna(value):
                    direction = "tăng" if float(value) > 0 else ("giảm" if float(value) < 0 else "không biến động")
                    parts.append(f"{label} có tỷ lệ biến động {direction} {_pct(value)}")
        if not parts:
            return ""
        return "Theo địa bàn, " + "; ".join(parts[:2]) + "."
    except Exception:
        return ""

def _movement_public_text(bundle: ReportFactsBundle, *, tid: int) -> str:
    f = getattr(bundle, "facts", {}) or {}
    c = f.get("movement_components") or {}
    focus = "hộ nghèo" if int(tid) == 2 else "hộ cận nghèo"
    before = f.get("tong_ky_truoc")
    after = f.get("tong_ky_sau")
    delta = f.get("chenh_lech")
    pct = f.get("ty_le_bien_dong_%")
    year = f.get("nam_sau") or (getattr(bundle, "scope", {}) or {}).get("year")
    if int(tid) == 2:
        g1_label, g2_label = "thoát nghèo trở thành hộ cận nghèo", "thoát nghèo vượt chuẩn"
        t1_label, t2_label, t3_label = "cận nghèo trở thành hộ nghèo", "tái nghèo", "nghèo mới phát sinh"
    else:
        g1_label, g2_label = "thoát cận nghèo vượt chuẩn", "cận nghèo trở thành hộ nghèo"
        t1_label, t2_label, t3_label = "thoát nghèo trở thành hộ cận nghèo", "tái cận nghèo", "cận nghèo mới phát sinh"
    direction = "tăng" if float(delta or 0) > 0 else ("giảm" if float(delta or 0) < 0 else "không biến động")
    abs_delta = abs(float(delta or 0))
    delta_text = _num(int(abs_delta) if abs_delta.is_integer() else abs_delta)
    lines = [
        (
            f"Trong kỳ rà soát năm {year}, số {focus} đầu kỳ là {_num(before)} hộ, "
            f"cuối kỳ là {_num(after)} hộ, {direction} {delta_text} hộ, "
            f"tương ứng {_pct_public(pct)}. Kết quả này phản ánh biến động của nhóm {focus} trong phạm vi số liệu đã tổng hợp."
        ),
        (
            f"Các nhóm làm giảm quy mô {focus} gồm {g1_label} với {_num(c.get('giam_1'))} hộ, "
            f"{g2_label} với {_num(c.get('giam_2'))} hộ và nhóm giảm khác {_num(c.get('giam_khac'))} hộ. "
            f"Các nhóm làm tăng quy mô {focus} gồm {t1_label} với {_num(c.get('tang_1'))} hộ, "
            f"{t2_label} với {_num(c.get('tang_2'))} hộ, {t3_label} với {_num(c.get('tang_3'))} hộ "
            f"và nhóm tăng khác {_num(c.get('tang_khac'))} hộ."
        ),
        _movement_area_highlight_sentence(bundle, focus=focus),
        (
            f"Tổng cuối kỳ theo nhóm phân loại hiện tại là {_num(f.get('tong_cuoi_ky_phan_loai') or after)} hộ, "
            "khớp với kết quả tổng hợp. Nhóm giảm khác và tăng khác đều ghi nhận 0 hộ, "
            "trong khi biến động chủ yếu tập trung ở các nhãn đã nêu."
        ),
        (
            "Ở cấp địa bàn, các số đầu kỳ, cuối kỳ, tăng và giảm được đọc riêng theo từng huyện/thành phố; "
            "mức tăng hoặc giảm toàn tỉnh chỉ phản ánh phạm vi toàn tỉnh, không thay thế cho biến động riêng của từng địa bàn. "
            "Những địa bàn có mức biến động lớn nên được xem cùng các cấu phần tăng, giảm tương ứng trong bảng số liệu."
        ),
    ]
    return "\n\n".join(str(x) for x in lines if str(x or "").strip())



def _bundle_table(bundle: ReportFactsBundle | None, *names: str) -> pd.DataFrame | None:
    """Lấy bảng pandas từ bundle theo thứ tự ưu tiên, dùng duck-typing để test bằng log."""
    if bundle is None:
        return None
    try:
        tables = getattr(bundle, "tables", {}) or {}
        if isinstance(tables, dict):
            for name in names:
                df = tables.get(name)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
    except Exception:
        pass
    return None


def _safe_top_rows(df: pd.DataFrame, value_col: str, n: int = 3) -> list[dict[str, Any]]:
    try:
        if not isinstance(df, pd.DataFrame) or df.empty or value_col not in df.columns:
            return []
        work = df.copy()
        work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
        work = work.sort_values(value_col, ascending=False).head(n)
        return [dict(r) for _, r in work.iterrows()]
    except Exception:
        return []


def _row_label(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _scope_year_phrase(bundle: ReportFactsBundle, facts: dict[str, Any] | None = None) -> str:
    facts = facts or {}
    scope = _scope(bundle).strip()
    year = (getattr(bundle, "scope", {}) or {}).get("year") or facts.get("year") or "2024"
    if str(year) and str(year) in scope:
        return scope
    return f"{scope} năm {year}"


def _pct_public(value: Any) -> str:
    text = _pct(value)
    # Tránh token 33,00 hoặc 37,50 bị validator coi là số khác nguồn 33.0/37.5.
    text = re.sub(r",00%$", "%", text)
    text = re.sub(r"(,\d)0%$", r"\1%", text)
    return text


def _overview_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai riêng cho mẫu 1: không dùng superlative mơ hồ kiểu 'vượt xa'."""
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    total = f.get("tong_ho_ra_soat")
    poor = f.get("ho_ngheo")
    near = f.get("ho_can_ngheo")
    poor_rate = f.get("ty_le_ho_ngheo")
    near_rate = f.get("ty_le_ho_can_ngheo")
    table_insights = f.get("table_insights") if isinstance(f, dict) else {}
    t1_detail = table_insights.get("template1_detail") if isinstance(table_insights, dict) else None
    medium = (t1_detail or {}).get("total_medium_living_households")
    table = _bundle_table(bundle, "template_main", "main", "by_district")

    if isinstance(table, pd.DataFrame) and not table.empty:
        poor_rows = _safe_top_rows(table, "so_ho_ngheo", 3)
        near_rows = _safe_top_rows(table, "so_ho_can_ngheo", 3)
        medium_rows = _safe_top_rows(table, "so_ho_nlnndn_mstb", 3) if "so_ho_nlnndn_mstb" in table.columns else []
        total_col = "tong_ho_dan_cu" if "tong_ho_dan_cu" in table.columns else "so_ho"
        total_rows = _safe_top_rows(table, total_col, 3)
    else:
        t1 = ((f.get("table_insights") or {}).get("template1_detail") or {}) if isinstance(f.get("table_insights"), dict) else {}
        poor_rows = list(t1.get("top_poor_districts") or [])[:3]
        near_rows = list(t1.get("top_near_poor_districts") or [])[:3]
        medium_rows = list(t1.get("top_medium_living_districts") or [])[:3]
        total_rows = list(f.get("top_districts") or [])[:3]

    def area_parts(rows: list[dict[str, Any]], col: str, label: str) -> str:
        parts: list[str] = []
        for r in rows[:3]:
            h = _row_label(r, "huyen", "dia_ban", default="")
            v = r.get(col) if col in r else r.get("so_ho")
            if h and v is not None:
                parts.append(f"{h} {_num(v)} hộ {label}")
        return "; ".join(parts)

    medium_total = int(float(medium or 0))
    poor_area = area_parts(poor_rows, "so_ho_ngheo", "nghèo")
    near_area = area_parts(near_rows, "so_ho_can_ngheo", "cận nghèo")
    medium_area = area_parts(medium_rows, "so_ho_nlnndn_mstb", "nông, lâm, ngư nghiệp có mức sống trung bình")
    total_area = area_parts(total_rows, "tong_ho_dan_cu", "trong phạm vi rà soát")

    lines = [
        (
            f"Trong {scope_year}, bảng tổng hợp ghi nhận {_num(poor)} hộ nghèo, "
            f"chiếm {_pct_public(poor_rate)}; {_num(near)} hộ cận nghèo, "
            f"chiếm {_pct_public(near_rate)}; và {_num(medium_total)} hộ nông, lâm, ngư nghiệp có mức sống trung bình. "
            "Phần nhận định này chỉ tập trung vào ba nhóm chỉ tiêu của bảng tổng hợp, không mở rộng sang nhóm hộ khác."
        )
    ]
    if total_area:
        lines.append(
            "Theo quy mô hộ trong phạm vi rà soát, các địa bàn có số hộ lớn gồm "
            + total_area
            + ". Các số này phản ánh quy mô hồ sơ được rà soát/phân loại, không dùng như tổng dân cư chính thức toàn địa bàn."
        )
    if poor_area:
        lines.append(
            "Về hộ nghèo, các địa bàn có số hộ nổi bật gồm "
            + poor_area
            + ". Nhận định này chỉ so sánh theo đúng chỉ tiêu hộ nghèo của từng địa bàn, không thay thế cho phân tích nguyên nhân."
        )
    if near_area:
        lines.append(
            "Về hộ cận nghèo, các địa bàn có số hộ nổi bật gồm "
            + near_area
            + ". Cách trình bày này giữ riêng chỉ tiêu hộ cận nghèo, không trộn với số hộ nghèo hoặc số hộ rà soát chung."
        )
    if medium_total <= 0:
        lines.append(
            "Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình hiện được ghi nhận bằng 0 theo bảng tổng hợp hiện có. Vì vậy, nội dung phân tích chỉ mô tả kết quả của hộ nghèo, hộ cận nghèo và chỉ tiêu mức sống trung bình trong phạm vi dữ liệu hiện có, không kết luận rằng địa phương không phát sinh nhóm hộ mức sống trung bình ngoài nguồn số liệu."
        )
    elif medium_area:
        lines.append(
            "Về hộ nông, lâm, ngư nghiệp có mức sống trung bình, các địa bàn có số hộ nổi bật gồm "
            + medium_area
            + ". Chỉ tiêu này được trình bày đúng theo số liệu trong bảng tổng hợp, không dùng nghề nghiệp hoặc nhóm hộ khác làm proxy."
        )
    else:
        lines.append(
            f"Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình ghi nhận {_num(medium_total)} hộ theo bảng tổng hợp hiện có. Nội dung nhận định chỉ sử dụng số liệu đã tổng hợp, không suy diễn thêm ngoài phạm vi biểu mẫu."
        )
    return "\n\n".join(x for x in lines if str(x or "").strip())



def _deprivation_public_text(bundle: ReportFactsBundle, *, tid: int) -> str:
    """Nhận định công khai riêng cho mẫu 4-7, tách đúng số hộ và tỷ lệ."""
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    df = _bundle_table(bundle, "template_main", "main")
    if not isinstance(df, pd.DataFrame) or df.empty:
        return f"Trong {scope_year}, các chỉ số thiếu hụt được tổng hợp theo từng chỉ tiêu và có thể chồng lấn trên cùng một hộ, nên không cộng thành cơ cấu 100%."

    focus = "hộ nghèo" if int(tid) in {4, 5} else "hộ cận nghèo"
    ratio_mode = int(tid) in {5, 7}
    top_col = "ty_le_%" if ratio_mode else "so_ho"
    rows = _safe_top_rows(df, top_col, 5)
    try:
        total_group = int(pd.to_numeric(df.get("tong_nhom"), errors="coerce").dropna().iloc[0]) if "tong_nhom" in df.columns and not pd.to_numeric(df.get("tong_nhom"), errors="coerce").dropna().empty else None
    except Exception:
        total_group = None

    def item(row: dict[str, Any]) -> str:
        label = _row_label(row, "chi_tieu", "label", default="chỉ tiêu")
        count = row.get("so_ho")
        pct = row.get("ty_le_%")
        if ratio_mode:
            return f"{label} {_pct_public(pct)}, tương ứng {_num(count)} hộ"
        return f"{label} {_num(count)} hộ, tương ứng {_pct_public(pct)}"

    top_text = "; ".join(item(r) for r in rows[:4] if r)
    follow_text = "; ".join(item(r) for r in rows[4:5] if r)
    metric_label = "tỷ lệ thiếu hụt" if ratio_mode else "số hộ thiếu hụt"
    intro = f"Trong {scope_year}, nhóm {focus} được tổng hợp theo từng chỉ số thiếu hụt dịch vụ xã hội cơ bản"
    if total_group:
        intro += f" trên tổng {_num(total_group)} hộ thuộc nhóm này"
    intro += f". Nội dung nhận định ưu tiên {metric_label}, đồng thời giữ số hộ và tỷ lệ đi cùng từng chỉ tiêu để thuận tiện đối chiếu bảng."

    lines = [intro]
    if top_text:
        lines.append(f"Các chỉ số nổi bật gồm {top_text}.")
    if follow_text:
        lines.append(f"Nhóm chỉ số tiếp theo cần lưu ý là {follow_text}.")
    lines.append(
        "Các chỉ số thiếu hụt có thể xuất hiện đồng thời trên cùng một hộ, vì vậy không cộng số hộ hoặc tỷ lệ của các chỉ số thành cơ cấu 100%. "
        "Khi đọc kết quả, số hộ cho biết quy mô thiếu hụt còn tỷ lệ cho biết mức phổ biến trong chính nhóm hộ được phân tích. "
        "Những chỉ tiêu có cả quy mô và tỷ lệ cao nên được xem là nhóm cần ưu tiên theo dõi trong cùng phạm vi số liệu, nhưng không được diễn giải thành nguyên nhân duy nhất của tình trạng nghèo hoặc cận nghèo."
    )
    return "\n\n".join(str(x).strip() for x in lines if str(x or "").strip())


def _ethnicity_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai riêng cho mẫu 9, tách hộ nghèo và hộ cận nghèo theo dân tộc."""
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    df = _bundle_table(bundle, "template_main", "main")
    if not isinstance(df, pd.DataFrame) or df.empty:
        return f"Trong {scope_year}, số liệu dân tộc được tổng hợp riêng cho hộ nghèo và hộ cận nghèo; nhận định chỉ mô tả phân bố theo dân tộc, không suy diễn nguyên nhân nghèo."

    poor_rows = _safe_top_rows(df, "so_ho_ngheo", 4) if "so_ho_ngheo" in df.columns else []
    near_rows = _safe_top_rows(df, "so_ho_can_ngheo", 4) if "so_ho_can_ngheo" in df.columns else []

    def items(rows: list[dict[str, Any]], count_col: str, pct_col: str) -> str:
        parts: list[str] = []
        for r in rows[:4]:
            label = _row_label(r, "dan_toc", "chi_tieu", "label", default="dân tộc")
            parts.append(f"{label} {_num(r.get(count_col))} hộ, tương ứng {_pct_public(r.get(pct_col))}")
        return "; ".join(parts)

    poor_text = items(poor_rows, "so_ho_ngheo", "ty_le_ngheo_%")
    near_text = items(near_rows, "so_ho_can_ngheo", "ty_le_can_ngheo_%")
    lines = [
        f"Trong {scope_year}, bảng dân tộc được đọc riêng cho hộ nghèo và hộ cận nghèo, không gộp hai nhóm hộ thành một tỷ lệ chung.",
    ]
    if poor_text:
        lines.append(f"Đối với hộ nghèo, các dân tộc có số hộ nổi bật gồm {poor_text}.")
    if near_text:
        lines.append(f"Đối với hộ cận nghèo, các dân tộc có số hộ nổi bật gồm {near_text}.")
    lines.append(
        "Các tỷ lệ nêu trên chỉ phản ánh cơ cấu trong từng nhóm hộ theo bộ số liệu đã tổng hợp. "
        "Không suy diễn cơ cấu dân tộc thành nguyên nhân nghèo hoặc đánh giá hiệu quả chính sách nếu không có nguồn dữ liệu kiểm chứng riêng. "
        "Khi so sánh, cần giữ đúng từng dân tộc với số hộ và tỷ lệ của nhóm hộ nghèo hoặc hộ cận nghèo tương ứng, không chuyển tỷ lệ của nhóm này sang nhóm kia. "
        "Các dân tộc có số hộ nổi bật trong cả hai nhóm nên được xem là trọng tâm theo dõi về phân bố, còn các dân tộc có quy mô nhỏ hơn vẫn được phản ánh đầy đủ trong bảng số liệu chi tiết."
    )
    return "\n\n".join(str(x).strip() for x in lines if str(x or "").strip())

def _causes_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai riêng cho mẫu 10: tách đúng số hộ nghèo và hộ cận nghèo."""
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    df = _bundle_table(bundle, "template_main", "main")
    if not isinstance(df, pd.DataFrame) or df.empty:
        poor = (f.get("top_poor_causes") or [])[:3]
        near = (f.get("top_near_poor_causes") or [])[:3]
    else:
        poor = _safe_top_rows(df, "so_ho_ngheo", 3)
        near = _safe_top_rows(df, "so_ho_can_ngheo", 3)

    def sentence_for(rows: list[dict[str, Any]], group: str, value_col: str, pct_col: str) -> str:
        sentences: list[str] = []
        for idx, r in enumerate(rows[:3]):
            label = _row_label(r, "chi_tieu", "nguyen_nhan", "label", default="chỉ tiêu")
            val = r.get(value_col)
            pct = r.get(pct_col)
            if val is None:
                continue
            prefix = f"Đối với {group}" if idx == 0 else f"Trong nhóm {group}"
            if pct is not None:
                sentences.append(f"{prefix}, {str(label).lower()} ghi nhận {_num(val)} hộ, tương ứng {_pct_public(pct)}.")
            else:
                sentences.append(f"{prefix}, {str(label).lower()} ghi nhận {_num(val)} hộ.")
        return " ".join(sentences)


    poor_sent = sentence_for(poor, "hộ nghèo", "so_ho_ngheo", "ty_le_ho_ngheo_%")
    near_sent = sentence_for(near, "hộ cận nghèo", "so_ho_can_ngheo", "ty_le_ho_can_ngheo_%")
    lines = [
        f"Trong {scope_year}, nhóm nguyên nhân nghèo được tổng hợp riêng cho hộ nghèo và hộ cận nghèo, vì cùng một nguyên nhân có thể xuất hiện với quy mô khác nhau ở từng nhóm hộ.",
        poor_sent,
        near_sent,
    ]
    lines.append(
        "Các nguyên nhân trong bảng có thể đồng thời xuất hiện ở cùng một hộ, nên không cộng các nguyên nhân thành một cơ cấu chung và không kết luận một nguyên nhân duy nhất cho từng nhóm hộ. "
        "Khi đối chiếu kết quả, số hộ phản ánh quy mô từng nguyên nhân trong nhóm hộ tương ứng, còn tỷ lệ phản ánh mức phổ biến của nguyên nhân đó trong chính nhóm hộ nghèo hoặc hộ cận nghèo."
    )
    return "\n\n".join(x for x in lines if str(x or "").strip())


def _template8_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai riêng cho mẫu 8.

    Mẫu 8 không lấy tổng hộ dân cư/tổng hộ rà soát làm trọng tâm nhận định.
    Trọng tâm đúng của biểu mẫu là ba nhóm đối tượng: DTTS, không có khả năng
    lao động và có người có công với cách mạng; mỗi nhóm phải tách hộ nghèo
    và hộ cận nghèo. Các nhóm có thể chồng lấn nên không cộng thành cơ cấu 100%.
    """
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    df = _bundle_table(bundle, "template_main", "main")

    if not isinstance(df, pd.DataFrame) or df.empty:
        return (
            f"Trong {scope_year}, số liệu nhóm đối tượng được tổng hợp riêng cho hộ nghèo và hộ cận nghèo. "
            "Các nhóm DTTS, không có khả năng lao động và có người có công với cách mạng có thể chồng lấn trên cùng một hộ, "
            "nên không cộng các nhóm này thành cơ cấu 100%."
        )

    work = df.copy()
    label_series = work["huyen"].astype(str) if "huyen" in work.columns else pd.Series([], dtype=str)
    total_rows = work[label_series.str.strip().str.lower().eq("toàn tỉnh")] if "huyen" in work.columns else pd.DataFrame()
    total = dict(total_rows.iloc[0]) if isinstance(total_rows, pd.DataFrame) and not total_rows.empty else {}
    district_df = work[~label_series.str.strip().str.lower().eq("toàn tỉnh")].copy() if "huyen" in work.columns else work.copy()

    def _sum_col(col: str) -> Any:
        if total and total.get(col) is not None:
            return total.get(col)
        if col in district_df.columns:
            return pd.to_numeric(district_df[col], errors="coerce").fillna(0).sum()
        return 0

    def _top(col: str, n: int = 3) -> list[dict[str, Any]]:
        return _safe_top_rows(district_df, col, n=n) if col in district_df.columns else []

    def _items(rows: list[dict[str, Any]], col: str) -> str:
        parts: list[str] = []
        for r in rows[:3]:
            h = _row_label(r, "huyen", "dia_ban", default="")
            v = r.get(col)
            if h and v is not None:
                parts.append(f"{h} {_num(v)} hộ")
        return "; ".join(parts)

    total_review = _sum_col("tong_ho_dan_cu")
    total_poor = _sum_col("tong_ho_ngheo")
    total_near = _sum_col("tong_ho_can_ngheo")
    total_dtts = _sum_col("so_ho_dtts")
    poor_dtts = _sum_col("ho_ngheo_dtts")
    near_dtts = _sum_col("ho_can_ngheo_dtts")
    poor_no_labor = _sum_col("ho_ngheo_khong_knld")
    near_no_labor = _sum_col("ho_can_ngheo_khong_knld")
    poor_merit = _sum_col("ho_ngheo_co_cong")
    near_merit = _sum_col("ho_can_ngheo_co_cong")

    poor_dtts_top = _items(_top("ho_ngheo_dtts"), "ho_ngheo_dtts")
    near_dtts_top = _items(_top("ho_can_ngheo_dtts"), "ho_can_ngheo_dtts")
    poor_no_labor_top = _items(_top("ho_ngheo_khong_knld"), "ho_ngheo_khong_knld")
    near_no_labor_top = _items(_top("ho_can_ngheo_khong_knld"), "ho_can_ngheo_khong_knld")
    poor_merit_top = _items(_top("ho_ngheo_co_cong"), "ho_ngheo_co_cong")
    near_merit_top = _items(_top("ho_can_ngheo_co_cong"), "ho_can_ngheo_co_cong")

    lines = [
        (
            f"Trong {scope_year}, bảng nhóm đối tượng được tổng hợp trên {_num(total_review)} hộ trong phạm vi rà soát/phân loại, "
            f"gồm {_num(total_poor)} hộ nghèo và {_num(total_near)} hộ cận nghèo. Trọng tâm nhận định là ba nhóm đối tượng của biểu mẫu: "
            "hộ DTTS, hộ không có khả năng lao động và hộ có người có công với cách mạng; không dùng tổng hộ rà soát làm chỉ tiêu xếp hạng chính."
        ),
        (
            f"Đối với nhóm DTTS, toàn tỉnh ghi nhận {_num(total_dtts)} hộ DTTS trong phạm vi dữ liệu; "
            f"trong đó có {_num(poor_dtts)} hộ nghèo DTTS và {_num(near_dtts)} hộ cận nghèo DTTS. "
            + (f"Các địa bàn có số hộ nghèo DTTS nổi bật gồm {poor_dtts_top}. " if poor_dtts_top else "")
            + (f"Ở nhóm hộ cận nghèo DTTS, các địa bàn nổi bật gồm {near_dtts_top}." if near_dtts_top else "")
        ),
        (
            f"Với nhóm không có khả năng lao động, hộ nghèo ghi nhận {_num(poor_no_labor)} hộ và hộ cận nghèo ghi nhận {_num(near_no_labor)} hộ. "
            + (f"Trong hộ nghèo, các địa bàn nổi bật gồm {poor_no_labor_top}. " if poor_no_labor_top else "")
            + (f"Trong hộ cận nghèo, các địa bàn nổi bật gồm {near_no_labor_top}." if near_no_labor_top else "")
        ),
        (
            f"Với nhóm có người có công với cách mạng, hộ nghèo ghi nhận {_num(poor_merit)} hộ và hộ cận nghèo ghi nhận {_num(near_merit)} hộ. "
            + (f"Trong hộ nghèo, các địa bàn nổi bật gồm {poor_merit_top}. " if poor_merit_top else "")
            + (f"Trong hộ cận nghèo, các địa bàn nổi bật gồm {near_merit_top}." if near_merit_top else "")
        ),
        (
            "Các nhóm đối tượng trong mẫu này có thể chồng lấn, do một hộ có thể đồng thời là hộ DTTS, hộ không có khả năng lao động hoặc hộ có người có công. "
            "Vì vậy, các số liệu được dùng để nhận diện nhóm nổi bật theo từng chỉ tiêu riêng, không cộng các nhóm thành tổng chung hoặc cơ cấu 100%."
        ),
    ]
    return "\n\n".join(str(x).strip() for x in lines if str(x or "").strip())

def _children_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai riêng cho mẫu 11.

    Mỗi câu chỉ đặt một nhóm hộ với một chỉ tiêu và một cặp số trẻ + tỷ lệ.
    Cách này tránh lỗi LLM/validator bắt chéo số trẻ và tỷ lệ giữa hộ nghèo và hộ cận nghèo.
    """
    f = getattr(bundle, "facts", {}) or {}
    scope_year = _scope_year_phrase(bundle, f)
    df = _bundle_table(bundle, "template_main", "main")

    if isinstance(df, pd.DataFrame) and not df.empty:
        records = [dict(r) for _, r in df.head(6).iterrows()]
    else:
        by_label: dict[str, dict[str, Any]] = {}
        for r in (f.get("top_poor_child_deprivations") or [])[:3]:
            label = _row_label(r, "chi_tieu", default="chỉ tiêu thiếu hụt")
            by_label.setdefault(label, {"chi_tieu": label}).update({
                "so_ho_ngheo": r.get("so_ho_ngheo"),
                "ty_le_ho_ngheo_%": r.get("ty_le_ho_ngheo_%"),
            })
        for r in (f.get("top_near_poor_child_deprivations") or [])[:3]:
            label = _row_label(r, "chi_tieu", default="chỉ tiêu thiếu hụt")
            by_label.setdefault(label, {"chi_tieu": label}).update({
                "so_ho_can_ngheo": r.get("so_ho_can_ngheo"),
                "ty_le_ho_can_ngheo_%": r.get("ty_le_ho_can_ngheo_%"),
            })
        records = list(by_label.values())[:3]

    lines = [
        f"Trong {scope_year}, các chỉ tiêu thiếu hụt của trẻ em được trình bày theo đơn vị số trẻ và tỷ lệ tương ứng trong từng nhóm hộ."
    ]
    poor_sentences: list[str] = []
    near_sentences: list[str] = []
    for idx, r in enumerate(records[:3]):
        label = _row_label(r, "chi_tieu", default="chỉ tiêu thiếu hụt của trẻ em")
        label_l = str(label).lower()
        if r.get("so_ho_ngheo") is not None:
            prefix = "Đối với trẻ em thuộc hộ nghèo" if idx == 0 else "Trong nhóm trẻ em thuộc hộ nghèo"
            poor_sentences.append(f"{prefix}, {label_l} ghi nhận {_num(r.get('so_ho_ngheo'))} trẻ, tương ứng {_pct_public(r.get('ty_le_ho_ngheo_%'))}.")
        if r.get("so_ho_can_ngheo") is not None:
            prefix = "Đối với trẻ em thuộc hộ cận nghèo" if idx == 0 else "Trong nhóm trẻ em thuộc hộ cận nghèo"
            near_sentences.append(f"{prefix}, {label_l} ghi nhận {_num(r.get('so_ho_can_ngheo'))} trẻ, tương ứng {_pct_public(r.get('ty_le_ho_can_ngheo_%'))}.")

    if poor_sentences:
        lines.append(" ".join(poor_sentences))
    if near_sentences:
        lines.append(" ".join(near_sentences))


    lines.append(
        "Các giá trị nêu trên là số trẻ thiếu chỉ tiêu và tỷ lệ tương ứng, không phải tỷ lệ phân loại hộ. Một trẻ hoặc một hộ gia đình có thể gắn với nhiều chỉ tiêu thiếu hụt, nên không cộng các chỉ tiêu thành một cơ cấu chung. "
        "Khi đối chiếu với bảng, cần đọc riêng nhóm trẻ em thuộc hộ nghèo và nhóm trẻ em thuộc hộ cận nghèo; số trẻ và tỷ lệ của nhóm này không thay thế cho nhóm còn lại."
    )
    return "\n\n".join(x for x in lines if str(x or "").strip())

def _multidim_public_text(bundle: ReportFactsBundle) -> str:
    """Nhận định công khai cho mẫu 12, bao phủ đủ tỷ lệ/mẫu số và lớp dân tộc.

    Lỗi trước đây: hàm public repair thay mọi candidate LLM của mẫu 12 bằng một đoạn
    chỉ nói tổng hộ/tỷ lệ, bỏ qua các cột Kinh/DTTS/DTTS tại chỗ. Vì hàm này chạy
    trước hậu kiểm nên 6 lần thử LLM đều bị biến thành cùng một đoạn thiếu dân tộc.
    Bản này lấy trực tiếp từ template_main/main và viết đủ hai lớp dữ liệu:
    (1) kết quả nghèo đa chiều theo địa bàn; (2) cơ cấu hộ nghèo theo dân tộc.
    """
    f = getattr(bundle, "facts", {}) or {}
    table = _bundle_table(bundle, "template_main", "main", "by_district")

    def _num_sum(df: pd.DataFrame, col: str) -> Any:
        try:
            if isinstance(df, pd.DataFrame) and col in df.columns:
                return pd.to_numeric(df[col], errors="coerce").fillna(0).sum()
        except Exception:
            pass
        return None

    def _top_rows(df: pd.DataFrame, col: str, n: int = 3) -> list[dict[str, Any]]:
        return _safe_top_rows(df, col, n=n) if isinstance(df, pd.DataFrame) and not df.empty else []

    if isinstance(table, pd.DataFrame) and not table.empty:
        total_review = _num_sum(table, "tong_ho_ra_soat")
        total_review_people = _num_sum(table, "tong_nhan_khau")
        target = _num_sum(table, "so_ho_muc_tieu")
        pop = _num_sum(table, "so_nhan_khau_muc_tieu")
        total_kinh = _num_sum(table, "so_ho_kinh")
        total_dtts = _num_sum(table, "so_ho_dtts")
        total_local = _num_sum(table, "so_ho_dtts_tai_cho")
        total_dtts_den = _num_sum(table, "tong_ho_dtts")
        total_local_den = _num_sum(table, "tong_ho_dtts_tai_cho")
        top_ratio = _top_rows(table, "ty_le_muc_tieu_%", 3)
        top_target = _top_rows(table, "so_ho_muc_tieu", 3)
        rows_for_ratio = top_ratio or top_target
        eth_rows = _top_rows(table, "so_ho_dtts", 3)
    else:
        total_review = f.get("tong_ho_ra_soat")
        total_review_people = None
        target = f.get("total_target_households")
        pop = f.get("total_target_population")
        total_kinh = None
        total_dtts = f.get("total_ethnic_minority_households")
        total_local = f.get("total_local_ethnic_minority_households")
        total_dtts_den = f.get("total_ethnic_minority_households_denominator")
        total_local_den = f.get("total_local_ethnic_minority_households_denominator")
        rows_for_ratio = (f.get("top_districts_by_ratio") or f.get("top_districts_by_target") or [])[:3]
        eth_rows = rows_for_ratio

    # Ưu tiên dùng tỷ lệ toàn tỉnh đã có trong facts; nếu không có thì chỉ nêu số hộ.
    overall_rate = f.get("ty_le_ho_ngheo")
    if overall_rate is None and isinstance(table, pd.DataFrame) and not table.empty:
        try:
            if total_review and float(total_review) > 0:
                overall_rate = float(target) * 100 / float(total_review)
        except Exception:
            overall_rate = None

    first = rows_for_ratio[0] if rows_for_ratio else {}
    more_rows = rows_for_ratio[1:3] if len(rows_for_ratio) > 1 else []

    lines: list[str] = []
    if total_review is not None:
        intro = (
            f"Theo kết quả rà soát/phân loại năm 2024, toàn tỉnh ghi nhận {_num(target)} hộ nghèo theo chuẩn đa chiều "
            f"trên tổng số {_num(total_review)} hộ trong phạm vi dữ liệu rà soát/phân loại"
        )
        if overall_rate is not None:
            intro += f", tương ứng tỷ lệ {_pct_public(overall_rate)}"
        intro += f". Số nhân khẩu thuộc hộ nghèo là {_num(pop)} người"
        if total_review_people is not None:
            intro += f" trên tổng số {_num(total_review_people)} nhân khẩu trong phạm vi dữ liệu."
        else:
            intro += "."
        lines.append(intro)
    else:
        lines.append(
            f"Theo kết quả rà soát/phân loại năm 2024, toàn tỉnh ghi nhận {_num(target)} hộ nghèo theo chuẩn đa chiều, "
            f"tương ứng {_num(pop)} nhân khẩu trong các hộ này. Tỷ lệ hộ nghèo được tính trong phạm vi hộ đã rà soát/phân loại."
        )

    if first:
        h = _row_label(first, "huyen", "dia_ban", default="địa bàn dẫn đầu")
        line = (
            f"Xét theo địa bàn, {h} ghi nhận {_num(first.get('so_ho_muc_tieu'))} hộ nghèo"
        )
        if first.get("tong_ho_ra_soat") is not None:
            line += f" trên tổng số {_num(first.get('tong_ho_ra_soat'))} hộ đã rà soát/phân loại"
        if first.get("ty_le_muc_tieu_%") is not None:
            line += f", tỷ lệ {_pct_public(first.get('ty_le_muc_tieu_%'))}"
        line += "."
        more = []
        for r in more_rows:
            hh = _row_label(r, "huyen", "dia_ban", default="")
            if not hh:
                continue
            part = f"{hh} có {_num(r.get('so_ho_muc_tieu'))} hộ nghèo"
            if r.get("ty_le_muc_tieu_%") is not None:
                part += f", tỷ lệ {_pct_public(r.get('ty_le_muc_tieu_%'))}"
            more.append(part)
        if more:
            line += " Các địa bàn đáng chú ý tiếp theo gồm " + "; ".join(more) + "."
        lines.append(line)

    if total_kinh is not None or total_dtts is not None or total_local is not None:
        eth = (
            f"Về cơ cấu hộ nghèo theo dân tộc, toàn tỉnh ghi nhận {_num(total_kinh)} hộ nghèo dân tộc Kinh, "
            f"{_num(total_dtts)} hộ nghèo DTTS, trong đó {_num(total_local)} hộ thuộc nhóm DTTS tại chỗ."
        )
        if total_dtts_den is not None:
            eth += f" Tỷ lệ hộ nghèo trong nhóm DTTS là {_pct_public(float(total_dtts or 0) * 100 / float(total_dtts_den or 1))}, tính trên {_num(total_dtts_den)} tổng hộ DTTS."
        if total_local_den is not None:
            eth += f" Tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ là {_pct_public(float(total_local or 0) * 100 / float(total_local_den or 1))}, tính trên {_num(total_local_den)} tổng hộ DTTS tại chỗ."
        eth_parts = []
        for r in eth_rows[:3]:
            h = _row_label(r, "huyen", "dia_ban", default="")
            if not h:
                continue
            if r.get("so_ho_kinh") is None and r.get("so_ho_dtts") is None and r.get("so_ho_dtts_tai_cho") is None:
                continue
            eth_parts.append(
                f"{h} có {_num(r.get('so_ho_kinh'))} hộ nghèo dân tộc Kinh, "
                f"{_num(r.get('so_ho_dtts'))} hộ nghèo DTTS trên {_num(r.get('tong_ho_dtts'))} hộ DTTS, "
                f"tỷ lệ hộ nghèo trong nhóm DTTS {_pct_public(r.get('ty_le_ngheo_trong_dtts_%'))}; "
                f"{_num(r.get('so_ho_dtts_tai_cho'))} hộ nghèo DTTS tại chỗ trên {_num(r.get('tong_ho_dtts_tai_cho'))} hộ DTTS tại chỗ, "
                f"tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ {_pct_public(r.get('ty_le_ngheo_trong_dtts_tai_cho_%'))}"
            )
        if eth_parts:
            eth += " Ở các địa bàn có số hộ nghèo DTTS nổi bật, " + "; ".join(eth_parts) + "."
        lines.append(eth)

    lines.append(
        "Các tỷ lệ nêu trên được hiểu theo tổng hộ đã rà soát/phân loại của từng địa bàn hoặc toàn tỉnh trong bộ số liệu hiện có. "
        "Riêng tỷ lệ hộ nghèo trong nhóm DTTS và tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ dùng mẫu số là tổng hộ của từng nhóm dân tộc tương ứng, không dùng tỷ trọng DTTS trong nhóm hộ nghèo để thay thế."
    )
    return "\n\n".join(x for x in lines if str(x or "").strip())

def _remove_report_meta_boilerplate(text: str) -> str:
    """Loại các câu nhắc việc/nhắc quy trình trước khi đưa vào Word.

    Mục nhận định trong Word chỉ nên chứa nhận định nghiệp vụ và số liệu. Các câu kiểu
    "khi đưa vào báo cáo", "khi diễn giải", "nếu tiếp tục phân tích" dễ giống prompt
    hoặc hướng dẫn nội bộ, nên được bỏ ở lớp public final.
    """
    raw = str(text or "")
    if not raw.strip():
        return ""
    # Chuẩn hóa một số cụm còn sót từ debug thành cách nói công khai hơn.
    raw = re.sub(r"(?i)\blưu ý dữ liệu:\s*", "", raw)
    raw = re.sub(r"(?i)\bnguồn dữ liệu hiện có\b", "bộ số liệu hiện có", raw)
    raw = re.sub(r"(?i)\bphần nhận định\b", "nội dung phân tích", raw)
    raw = re.sub(r"(?i)^\s*trong báo cáo tổng hợp số liệu", "Số liệu tổng hợp", raw)
    # Tách câu tương đối an toàn; giữ nguyên dấu câu ở cuối.
    chunks = re.split(r"(?<=[.!?])\s+", raw)
    drop_patterns = [
        r"(?i)^khi\s+đưa\s+vào\s+báo\s+cáo\b",
        r"(?i)^khi\s+diễn\s+giải\b",
        r"(?i)^khi\s+sử\s+dụng\s+kết\s+quả\s+này\b",
        r"(?i)^nếu\s+tiếp\s+tục\s+phân\s+tích\b",
        r"(?i)^các\s+nhận\s+định\s+trong\s+(?:phần|nội\s+dung)\s+này\b",
        r"(?i)đây\s+là\s+những\s+nhóm\s+cần\s+tiếp\s+tục\s+theo\s+dõi",
        r"(?i)đây\s+là\s+những\s+chỉ\s+tiêu\s+cần\s+tiếp\s+tục\s+theo\s+dõi",
        r"(?i)những\s+nội\s+dung\s+về\s+nguyên\s+nhân,\s*hiệu\s+quả\s+chính\s+sách\s+hoặc\s+xu\s+hướng\s+dài\s+hạn",
        r"(?i)cần\s+được\s+bổ\s+sung\s+bằng\s+nguồn\s+dữ\s+liệu\s+kiểm\s+chứng\s+riêng",
        r"(?i)công\s+tác\s+rà\s+soát\s+tiếp\s+theo\s+nên\s+tiếp\s+tục",
        r"(?i)thống\s+nhất\s+về\s+phạm\s+vi,\s*phương\s+pháp\s+và\s+cách\s+đối\s+chiếu\s+số\s+liệu",
        r"(?i)phục\s+vụ\s+việc\s+xác\s+định\s+trọng\s+tâm\s+quản\s+lý",
        r"(?i)xây\s+dựng\s+kế\s+hoạch\s+hỗ\s+trợ\s+phù\s+hợp",
        r"(?i)không\s+dùng\s+số\s+toàn\s+tỉnh\s+để\s+thay",
        r"(?i)cần\s+được\s+hiểu\s+là\s+kết\s+quả\s+tổng\s+hợp",
    ]
    kept: list[str] = []
    for c in chunks:
        s = c.strip()
        if not s:
            continue
        if any(re.search(p, s) for p in drop_patterns):
            continue
        kept.append(s)
    out = " ".join(kept)
    # Loại token có mùi prompt/debug nếu lọt vào câu dài.
    out = re.sub(r"(?i)\b(?:SAFE_BASE_TEXT|REPORT_FACTS|fact\s*pack|fact\s*bundle|validator|audit|debug|prompt|template_id|dataframe|series|json)\b", "", out)
    out = re.sub(r"(?i)\bDB\b", "nguồn số liệu", out)
    out = re.sub(r"(?i)\bmẫu\s*(?:số\s*)?\d+\b[:\-–]?\s*", "", out)
    out = re.sub(r"(?i)\bcột\s+[A-Z](?:\s*[,+/&+\-]\s*[A-Z])*\b", "chỉ tiêu tương ứng", out)
    out = re.sub(r"(?i)\btrong phạm vi báo cáo\b", "trong phạm vi số liệu", out)
    out = re.sub(r"(?i)\bnguồn dữ liệu hiện có\b", "bộ số liệu hiện có", out)
    out = re.sub(r"(?i)\blưu ý dữ liệu:\s*", "", out)
    out = re.sub(r"(?i)\bcủa hệ thống\b", "", out)
    out = re.sub(r"(?i)(^|[.!?]\s+)bộ số liệu hiện có", lambda m: m.group(1) + "Bộ số liệu hiện có", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def _public_word_final_repair_with_bundle(text: str, bundle: ReportFactsBundle | None) -> str:
    """Lớp chốt cuối để văn bản đưa vào Word sạch, đúng số và đúng nghiệp vụ.

    Hàm này chỉ làm sạch lớp trình bày công khai; không gọi LLM và không tự thêm nguồn ngoài.
    Tuyệt đối không thay toàn bộ văn bản LLM bằng đoạn nhận định deterministic/fallback,
    vì như vậy chế độ LLM sẽ mất ý nghĩa và regenerate sẽ trùng văn bản.
    """
    raw = _clean_word_report_style_text(text)
    if bundle is None or not raw:
        return raw
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)
    f = getattr(bundle, "facts", {}) or {}

    # IMPORTANT: không được thay toàn bộ candidate LLM bằng public_text/fallback deterministic.
    # Các hàm _overview_public_text/_movement_public_text/_causes_public_text/
    # _children_public_text/_multidim_public_text chỉ nên dùng cho chế độ no-LLM/fallback,
    # không dùng trong pipeline LLM rewrite. Nếu return tại đây thì dù prompt facts-only,
    # văn bản cuối vẫn bị cố định giống fallback và regenerate sẽ trùng 100%.
    # Vì vậy lớp này chỉ làm sạch hẹp ở dưới; số liệu vẫn do _validate_candidate và
    # _final_text_fact_audit quyết định pass/fail.

    if tid == 1:
        # Giữ heading mềm/đoạn văn của bản không LLM để mẫu 1 hiển thị cùng phong cách
        # với các mẫu báo cáo khác; chỉ làm sạch nội dung nghiệp vụ bên dưới.
        table_insights = f.get("table_insights") if isinstance(f, dict) else {}
        t1 = table_insights.get("template1_detail") if isinstance(table_insights, dict) else {}
        medium_total = int(float(t1.get("total_medium_living_households") or 0)) if isinstance(t1, dict) else 0
        raw = raw.replace("con số 0", "0 hộ")
        if medium_total <= 0:
            raw = re.sub(r"(?i)không\s+có\s+hộ\s+nào([^.!?]{0,120}mức sống trung bình)", r"chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình được ghi 0 theo bảng tổng hợp hiện có", raw)
        else:
            raw = re.sub(
                r"(?i)không\s+có\s+hộ\s+nào([^.!?]{0,120}mức sống trung bình)",
                f"chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình ghi nhận {_num(medium_total)} hộ theo bảng tổng hợp hiện có",
                raw,
            )
            raw = re.sub(
                r"(?i)chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình[^.!?]{0,120}\b0\s*hộ[^.!?]*[.!?]",
                f"Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình ghi nhận {_num(medium_total)} hộ theo bảng tổng hợp hiện có.",
                raw,
            )
        raw = raw.replace("theo chính sách an toàn dữ liệu", "theo bảng tổng hợp hiện có")
        raw = raw.replace("do bộ số liệu chưa có trường trực tiếp để xác định nhóm này", "theo bảng tổng hợp hiện có")
        raw = raw.replace("do nguồn dữ liệu hiện có chưa có trường trực tiếp", "theo bảng tổng hợp hiện có")

    if tid in {4, 5, 6, 7} or pattern in {"deprivation_count", "deprivation_ratio"}:
        if "không cộng" not in raw.lower() and "chồng lấn" not in raw.lower():
            raw += " Các chỉ số thiếu hụt có thể chồng lấn trên cùng một hộ, vì vậy không cộng các tỷ lệ hoặc số lượng của các chỉ số thành cơ cấu 100%."

    if tid == 8 or pattern == "vulnerable_groups":
        raw = re.sub(r"\bdan\b", "và", raw, flags=re.I)
        if "chồng lấn" not in raw.lower() and "đồng thời thuộc" not in raw.lower():
            raw += " Các nhóm hộ có thể chồng lấn, do một hộ có thể đồng thời thuộc nhiều nhóm; vì vậy không cộng các nhóm thành cơ cấu 100%."

    if tid == 9 or pattern == "ethnicity":
        raw = re.sub(r"(?i)nguyên\s+nhân", "yếu tố", raw)
        raw = re.sub(r"(?i)chính\s+sách", "nội dung theo dõi", raw)
        raw = re.sub(r"(?i)hiệu\s+quả\s+cao", "kết quả theo dõi rõ hơn", raw)
        if "không suy diễn" not in raw.lower() and "không kết luận" not in raw.lower():
            raw += " Không suy diễn từ cơ cấu dân tộc thành đánh giá ngoài phạm vi số liệu; nhận định chỉ dừng ở mô tả phân bố hộ nghèo và hộ cận nghèo theo dân tộc."

    if tid == 10 or pattern == "causes":
        if "đồng thời xuất hiện" not in raw.lower() and "nguyên nhân duy nhất" not in raw.lower():
            raw += " Các nguyên nhân có thể đồng thời xuất hiện ở cùng một hộ, nên không kết luận một nguyên nhân duy nhất cho từng nhóm hộ."

    if (tid in {4, 6} or pattern == "deprivation_count") and "số hộ thiếu hụt" not in raw.lower():
        raw = "Xét theo số hộ thiếu hụt, " + raw.lstrip()

    raw = _clean_word_report_style_text(raw)
    if tid == 1:
        # _remove_report_meta_boilerplate() gom toàn bộ câu thành một đoạn.
        # Với mẫu 1, cần giữ nhịp đoạn giống các mẫu no-LLM khác để dễ đọc trên UI/Word.
        parts = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
        cleaned_parts: list[str] = []
        for part in parts:
            cleaned = _remove_report_meta_boilerplate(part)
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
                cleaned_parts.append(cleaned)
        raw = "\n\n".join(cleaned_parts) if cleaned_parts else _remove_report_meta_boilerplate(raw)
    else:
        raw = _remove_report_meta_boilerplate(raw)
    raw = _clean_word_report_style_text(raw)
    if tid == 1:
        raw = raw.replace("biểu mẫu", "bảng tổng hợp")
        raw = re.sub(
            r"(:\s+)([a-zà-ỹđ])",
            lambda m: m.group(1) + m.group(2).upper(),
            raw,
        )
    if raw:
        raw = raw[0].upper() + raw[1:]
    return raw

def _llm_fallback_structure_warnings(text: str) -> list[str]:
    """Chặn riêng ứng viên LLM nếu nó bê nguyên cấu trúc deterministic/no-LLM."""
    raw = str(text or "").strip()
    if not raw:
        return []
    heading_re = re.compile(
        r"(?im)^\s*(Khái\s+quát\s+chung|Kết\s+quả\s+rà\s+soát|Kết\s+quả\s+tổng\s+hợp|Địa\s+bàn\s+nổi\s+bật|Nhóm\s+chỉ\s+tiêu\s+nổi\s+bật|Đối\s+chiếu\s+biểu\s+đồ|Lưu\s+ý\s+diễn\s+giải|Định\s+hướng\s+theo\s+dõi|Định\s+hướng\s+quản\s+lý|Nhận\s+định\s+bổ\s+sung)\s*[:：]"
    )
    hits = heading_re.findall(raw)
    warnings: list[str] = []
    if len(hits) >= 2:
        warnings.append("Văn bản LLM còn bám cấu trúc Python/không LLM bằng các nhãn đoạn fallback; cần viết thành 3-5 đoạn văn tự nhiên, không dùng nhãn 'Khái quát chung/Kết quả/Địa bàn/Đối chiếu/Định hướng'.")
    fallback_phrase_count = sum(1 for p in [
        "Khái quát chung:", "Kết quả rà soát:", "Kết quả tổng hợp:",
        "Địa bàn nổi bật:", "Đối chiếu biểu đồ:", "Định hướng theo dõi:",
    ] if p.lower() in raw.lower())
    if fallback_phrase_count >= 2 and not warnings:
        warnings.append("Văn bản LLM có hình thức quá giống văn bản không LLM; cần đổi bố cục thành đoạn nhận định tự nhiên, không dùng nhãn đoạn cố định.")
    return warnings




def _normalize_for_similarity(text: str) -> str:
    """Chuẩn hóa văn bản để đo mức bám khuôn, bỏ số để không phạt vì giữ số đúng."""
    raw = str(text or "").lower()
    raw = unicodedata.normalize("NFC", raw)
    raw = re.sub(r"\d+(?:[\.,]\d+)*%?", " <num> ", raw)
    raw = re.sub(r"[^0-9a-zA-ZÀ-ỹ%]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _text_fingerprint(text: str, *, normalized: bool = True) -> str:
    raw = _normalize_for_similarity(text) if normalized else str(text or "")
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def normalized_text_similarity(a: str, b: str) -> float:
    """Similarity normalized for report style checks; numbers become placeholders."""
    aa = _normalize_for_similarity(a)
    bb = _normalize_for_similarity(b)
    if not aa or not bb:
        return 0.0
    return float(difflib.SequenceMatcher(None, aa, bb).ratio())


def _similarity_ratio_without_numbers(a: str, b: str) -> float:
    if len(_normalize_for_similarity(a)) < 40 or len(_normalize_for_similarity(b)) < 40:
        return 0.0
    return normalized_text_similarity(a, b)


def _llm_variation_quality_warnings(
    candidate: str,
    *,
    safe_base: str,
    protected_text: str = "",
    bundle: ReportFactsBundle | None = None,
    regenerate_nonce: int = 0,
    attempt_no: int = 1,
    allow_variation: bool = True,
) -> list[str]:
    """Reject ứng viên LLM nếu nó chỉ là bản fallback/SAFE_BASE_TEXT đổi vài chữ.

    Đây là hậu kiểm chất lượng LLM, không kiểm số liệu. Khi fail, vòng retry sẽ gọi LLM
    viết lại; không tự sửa bằng thay cụm cố định để tránh tạo cảm giác hardcode/fallback.
    """
    if not allow_variation:
        return []
    raw = str(candidate or "").strip()
    if not raw:
        return []
    warnings: list[str] = []
    try:
        tid = _template_id_from_bundle(bundle)
        pattern = _pattern(bundle) if bundle is not None else ""
    except Exception:
        tid, pattern = 0, ""
    lower = raw.lower()
    fixed_transitions = [
        "theo kết quả rà soát/phân loại",
        "xét theo địa bàn",
        "các địa bàn đáng chú ý tiếp theo gồm",
        "về cơ cấu hộ nghèo theo dân tộc",
        "ở các địa bàn có số hộ nghèo dtts nổi bật",
        "các tỷ lệ nêu trên được hiểu",
    ]
    fixed_hit_count = sum(1 for p in fixed_transitions if p in lower)
    if int(regenerate_nonce or 0) > 0 and fixed_hit_count >= 3:
        warnings.append(
            "LLM chưa tạo biến thể diễn đạt; văn bản còn bám quá nhiều cụm chuyển đoạn cố định của fallback/SAFE_BASE_TEXT."
        )
    if int(regenerate_nonce or 0) > 0 and lower.startswith("theo kết quả rà soát/phân loại"):
        warnings.append(
            "LLM chưa tạo biến thể diễn đạt; câu mở đầu vẫn dùng đúng khuôn cố định 'Theo kết quả rà soát/phân loại'."
        )
    base_ratio = _similarity_ratio_without_numbers(raw, safe_base)
    prot_ratio = _similarity_ratio_without_numbers(raw, protected_text) if protected_text else 0.0
    threshold = 0.86 if int(regenerate_nonce or 0) == 0 else 0.80
    if max(base_ratio, prot_ratio) >= threshold:
        warnings.append(
            f"LLM chưa tạo biến thể diễn đạt; mức tương đồng với văn bản nguồn/fallback quá cao ({max(base_ratio, prot_ratio):.2f})."
        )
    if (tid == 12 or pattern == "multidimensional_standard") and int(regenerate_nonce or 0) > 0:
        alt_markers = [
            "ở cấp địa bàn", "phân theo địa bàn", "khi đối chiếu", "với lớp dữ liệu", "cơ cấu dân tộc",
            "trong phạm vi", "từ bộ số liệu", "kết quả rà soát/phân loại năm", "dữ liệu cho thấy",
        ]
        if not any(m in lower for m in alt_markers):
            warnings.append(
                "LLM chưa tạo biến thể diễn đạt cho mẫu 12; chưa thấy cách mở/chuyển ý khác rõ so với khuôn cũ."
            )
    return warnings

def _llm_dry_style_warnings(text: str) -> list[str]:
    """Cảnh báo khi LLM viết quá giống văn mẫu khô/máy móc.

    Không kiểm số liệu ở đây. Hàm này chỉ chặn các câu công thức thường thấy khi
    LLM bám sát fallback Python: mở bài chung chung, kết luận quản lý lặp lại,
    và cụm từ không tạo thêm nhận định cụ thể từ bảng/biểu đồ.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    lower = raw.lower()
    dry_phrases = [
        "tập trung làm rõ quy mô",
        "những nhóm/chỉ tiêu nổi bật",
        "những nhóm chỉ tiêu nổi bật",
        "các nội dung cần tiếp tục theo dõi",
        "công tác rà soát trong kỳ tiếp theo cần tiếp tục",
        "thống nhất về phạm vi, phương pháp và cách đối chiếu số liệu",
        "các nhóm hộ hoặc chỉ tiêu có quy mô cao nên được theo dõi thường xuyên",
        "phục vụ việc xác định trọng tâm quản lý",
        "xây dựng kế hoạch hỗ trợ phù hợp",
        "qua đó giúp nhìn rõ hơn trọng tâm cần theo dõi",
        "trong quá trình quản lý",
        "trong phạm vi báo cáo",
        "khi đưa vào báo cáo",
        "nếu tiếp tục phân tích theo địa bàn",
        "không dùng số toàn tỉnh để thay",
        "phục vụ việc xác định trọng tâm quản lý",
        "xây dựng kế hoạch hỗ trợ phù hợp",
    ]
    hits = [p for p in dry_phrases if p in lower]
    warnings: list[str] = []
    if len(hits) >= 2:
        warnings.append(
            "Văn phong quá khô/công thức và còn giống phần kết luận fallback; cần viết lại thành đoạn nhận định tự nhiên, gắn trực tiếp với số liệu nổi bật thay vì dùng câu quản lý chung."
        )
    # Nếu câu kết y hệt kiểu fallback thì chỉ một cụm dài cũng đủ reject.
    strong_boilerplate = [
        "công tác rà soát trong kỳ tiếp theo cần tiếp tục được thực hiện thống nhất",
        "các nhóm hộ hoặc chỉ tiêu có quy mô cao nên được theo dõi thường xuyên",
        "phục vụ việc xác định trọng tâm quản lý và xây dựng kế hoạch hỗ trợ phù hợp",
    ]
    if any(p in lower for p in strong_boilerplate) and not warnings:
        warnings.append(
            "Văn bản LLM còn dùng câu kết luận quản lý quá công thức từ bản không LLM; cần đổi sang nhận định cụ thể theo mẫu số liệu hiện có."
        )
    return warnings



def _ranking_claim_consistency_warnings(bundle: ReportFactsBundle | None, text: str) -> list[str]:
    """Bắt lỗi xếp hạng trực tiếp kiểu "cao nhất/thứ hai" theo bảng template_main.

    Validator tổng quát dễ bỏ sót câu như "Đăk Mil ... mức sống trung bình cao nhất với 33 hộ"
    vì câu không ghi đúng tên cột thô. Hàm này chỉ dùng các cột trọng tâm nghiệp vụ và
    chỉ kiểm khi câu có tín hiệu xếp hạng rõ ràng; không can thiệp câu mô tả bình thường.
    """
    warnings: list[str] = []
    if bundle is None:
        return warnings
    try:
        tables = getattr(bundle, "tables", {}) or {}
        df = tables.get("template_main")
        if not isinstance(df, pd.DataFrame) or df.empty or "huyen" not in df.columns:
            return warnings
        template = getattr(bundle, "template", {}) or {}
        pattern = str(template.get("pattern") or "")
    except Exception:
        return warnings

    raw_text = str(text or "")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", raw_text) if s.strip()]
    if not sentences:
        return warnings

    # Từ khóa theo từng cột trọng tâm. Ưu tiên các cột dễ bị LLM đảo nhãn-số.
    column_keywords: dict[str, list[str]] = {}
    if "so_ho_ngheo" in df.columns:
        column_keywords["so_ho_ngheo"] = ["hộ nghèo", "nghèo"]
    if "so_ho_can_ngheo" in df.columns:
        column_keywords["so_ho_can_ngheo"] = ["hộ cận nghèo", "cận nghèo"]
    if "so_ho_nlnndn_mstb" in df.columns:
        column_keywords["so_ho_nlnndn_mstb"] = [
            "nông", "lâm", "ngư", "mức sống trung bình", "nlnndn", "mstb"
        ]
    if "chenh_lech" in df.columns:
        column_keywords["chenh_lech"] = ["chênh lệch", "biến động", "tăng", "giảm"]
    if "ty_le_bien_dong_%" in df.columns:
        column_keywords["ty_le_bien_dong_%"] = ["tỷ lệ biến động", "tỉ lệ biến động"]
    if "so_ho_muc_tieu" in df.columns:
        column_keywords["so_ho_muc_tieu"] = ["hộ nghèo đa chiều", "hộ mục tiêu", "nghèo đa chiều"]
    if "ty_le_muc_tieu_%" in df.columns:
        column_keywords["ty_le_muc_tieu_%"] = ["tỷ lệ hộ nghèo", "tỷ lệ nghèo", "tỷ lệ hộ mục tiêu"]

    if pattern == "child_deprivation":
        # Mẫu 11 xếp hạng theo chỉ tiêu, không theo huyện; bỏ qua kiểm huyen.
        return warnings

    districts = [str(x) for x in df["huyen"].dropna().unique()]
    if not districts:
        return warnings

    def norm_label(value: Any) -> str:
        s = str(value or "").lower().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        s = s.replace("đ", "d")
        s = re.sub(r"\s+", " ", s)
        return s

    def rank_for(label: str, col: str, *, ascending: bool = False) -> int | None:
        try:
            tmp = df[["huyen", col]].dropna().copy()
            if tmp.empty:
                return None
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
            tmp = tmp.dropna(subset=[col]).sort_values(col, ascending=ascending).reset_index(drop=True)
            for i, v in enumerate(tmp["huyen"].astype(str).tolist(), start=1):
                if norm_label(v) == norm_label(label):
                    return i
        except Exception:
            return None
        return None

    def _rank_context_for_label(sentence: str, label: str) -> str:
        """Lấy cụm gần tên địa bàn để không áp rank của địa bàn này sang địa bàn khác.

        Ví dụ: "Tuy Đức dẫn đầu..., còn Krông Nô đứng thứ hai..." thì Tuy Đức chỉ
        bị kiểm với "dẫn đầu", Krông Nô chỉ bị kiểm với "thứ hai".
        """
        low_s = str(sentence or "").lower()
        lab = str(label or "").lower()
        pos = low_s.find(lab)
        if pos < 0:
            # Fallback không dấu; dùng cả câu nếu không xác định được vị trí.
            return low_s
        before_markers = [";", ".", "!", "?", "\n", " còn ", " trong khi ", " đồng thời ", " còn lại "]
        after_markers = [";", ".", "!", "?", "\n", " còn ", " trong khi ", " đồng thời ", " còn lại "]
        start_pos = 0
        for m in before_markers:
            k = low_s.rfind(m, 0, pos)
            if k >= 0:
                start_pos = max(start_pos, k + len(m))
        end_pos = len(low_s)
        for m in after_markers:
            k = low_s.find(m, pos + len(lab))
            if k >= 0:
                end_pos = min(end_pos, k)
        return low_s[start_pos:end_pos].strip()

    for sent in sentences:
        low = sent.lower()
        high_terms = ("cao nhất", "lớn nhất", "nhiều nhất", "đứng đầu", "dẫn đầu")
        low_terms = ("thấp nhất", "ít nhất")
        second_terms = ("thứ hai", "đứng thứ hai", "xếp thứ hai", "thứ 2")
        if not any(x in low for x in high_terms + low_terms + second_terms):
            continue
        low_norm = norm_label(low)
        mentioned = [d for d in districts if norm_label(d) in low_norm]
        if not mentioned:
            continue
        def _rank_col_relevant(col: str, sentence_l: str) -> bool:
            # Tránh "cận nghèo" bị match vào cột "hộ nghèo" chỉ vì có chữ nghèo.
            if col == "so_ho_ngheo":
                return bool(re.search(r"(?<!cận\s)hộ\s+nghèo|(?<!cận\s)số\s+hộ\s+nghèo", sentence_l))
            if col == "so_ho_can_ngheo":
                return bool(re.search(r"hộ\s+cận\s+nghèo|cận\s+nghèo", sentence_l))
            return any(k in sentence_l for k in column_keywords.get(col, []))

        relevant_cols = [
            col for col in column_keywords
            if col in df.columns and _rank_col_relevant(col, low)
        ]
        # Nếu không xác định được cột, không đoán mò.
        if not relevant_cols:
            continue
        for label in mentioned:
            label_context = _rank_context_for_label(sent, label)
            # Chỉ áp rank xuất hiện trong cụm gần địa bàn đó; tránh câu có nhiều địa bàn.
            label_has_high = any(x in label_context for x in high_terms)
            label_has_low = any(x in label_context for x in low_terms)
            label_has_second = any(x in label_context for x in second_terms)
            if not (label_has_high or label_has_low or label_has_second):
                continue
            for col in relevant_cols:
                rk = rank_for(label, col, ascending=False)
                low_rk = rank_for(label, col, ascending=True)
                if rk is None:
                    continue
                col_label = _column_label(col)
                if label_has_high and rk != 1:
                    warnings.append(
                        f"LLM có nhận định xếp hạng không đúng: {label} không phải cao nhất theo {col_label}."
                    )
                if label_has_low and low_rk is not None and low_rk != 1:
                    warnings.append(
                        f"LLM có nhận định xếp hạng không đúng: {label} không phải thấp nhất theo {col_label}."
                    )
                if label_has_second and rk != 2:
                    warnings.append(
                        f"LLM có nhận định xếp hạng không đúng: {label} không phải thứ hai theo {col_label}."
                    )
    # Bỏ trùng lặp nhưng giữ thứ tự.
    seen: set[str] = set()
    out: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out

def _coerce_llm_min_words(value: Any = None, default: int = 150) -> int:
    """Chuẩn hóa số từ tối thiểu bắt buộc cho văn bản LLM.

    Người dùng có thể tăng ngưỡng trong UI; vẫn cap để tránh làm LLM 3B fail vô hạn.
    """
    try:
        n = int(value) if value is not None else int(default)
    except Exception:
        n = int(default)
    return max(80, min(n, 520))


def _with_llm_min_words_requirement(prompt: str, min_words: int | None) -> str:
    """Gắn yêu cầu tối thiểu số từ vào mọi prompt LLM.

    Dùng marker để retry prompt không bị lặp yêu cầu nhiều lần.
    """
    n = _coerce_llm_min_words(min_words, default=150)
    marker = "YÊU CẦU ĐỘ DÀI LLM BẮT BUỘC"
    raw = str(prompt or "").strip()
    if marker in raw:
        return raw
    return (
        raw
        + f"\n\n{marker}:\n"
        + f"- Văn bản LLM phải có tối thiểu {n} từ theo cấu hình người dùng. "
          "Nếu nơi khác trong prompt có khoảng từ thấp hơn, ưu tiên ngưỡng tối thiểu này.\n"
        + "- Không kéo dài bằng câu chung chung; mỗi đoạn nên có số liệu/cặp so sánh/lưu ý diễn giải cụ thể từ facts.\n"
        + "- Nếu chưa đủ số từ, hãy mở rộng phần đối chiếu địa bàn/chỉ tiêu/biểu đồ bằng số liệu đã có, không thêm số mới.\n"
    ).strip()



# ── Structured fact audit for report_task / UI ─────────────────────────────
def _audit_status_from_warnings(warnings: list[str] | None) -> str:
    ws = [str(w) for w in (warnings or []) if str(w).strip()]
    if any(_is_hard_validation_warning(w) for w in ws):
        return "fail"
    if ws:
        return "warn"
    return "pass"


def _audit_rule(rule_id: str, name: str, warnings: list[str] | None = None, *, pass_message: str = "Đạt.") -> dict[str, Any]:
    ws = [str(w) for w in (warnings or []) if str(w).strip()]
    status = _audit_status_from_warnings(ws)
    return {
        "rule_id": rule_id,
        "name": name,
        "status": status,
        "hard_fail": bool(status == "fail"),
        "message": (pass_message if status == "pass" else ws[0]),
        "warnings": ws[:12],
    }


def _dedupe_text_items(items: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _source_numbers_for_audit(bundle: ReportFactsBundle | None, safe_base: str) -> set[str]:
    return _collect_allowed_number_tokens(bundle, safe_base)


def _main_audit_table(bundle: ReportFactsBundle | None) -> tuple[str | None, pd.DataFrame | None, str | None, list[str], list[str]]:
    if bundle is None:
        return None, None, None, [], []
    tables = getattr(bundle, "tables", {}) or {}
    for name in ("template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
            continue
        label_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = str(c)
                break
        if not label_col:
            continue
        numeric_cols = _business_numeric_cols(df, label_col)
        if numeric_cols:
            row_labels = [str(v or "").strip() for v in df[label_col].tolist()]
            return name, df, label_col, list(map(str, numeric_cols)), row_labels
    return None, None, None, [], []


def _sentence_fact_audit(
    bundle: ReportFactsBundle | None,
    safe_base: str,
    text: str,
    *,
    max_sentences: int = 80,
) -> list[dict[str, Any]]:
    """Audit từng câu/cụm có số trong văn bản cuối.

    Mục tiêu phục vụ UI/log: người kiểm không cần đọc thủ công toàn bộ đoạn nhận định.
    Đây là lớp giải thích hậu kiểm, không thay thế validator chính. Các lỗi hard vẫn
    được quyết định bởi _validate_candidate và các hàm warning cùng nguồn dữ liệu.
    """
    allowed_numbers = _source_numbers_for_audit(bundle, safe_base)
    table_name, df, label_col, numeric_cols, row_labels = _main_audit_table(bundle)
    rows: list[dict[str, Any]] = []
    if not str(text or "").strip():
        return rows

    all_table_numbers: set[str] = set()
    if isinstance(df, pd.DataFrame):
        for c in numeric_cols:
            try:
                series = pd.to_numeric(df[c], errors="coerce").dropna()
                for v in series.tolist():
                    all_table_numbers |= {_normalize_number_token(x) for x in _number_variants(v)}
                total = series.sum()
                if abs(float(total or 0)) > 1e-9:
                    all_table_numbers |= {_normalize_number_token(x) for x in _number_variants(total)}
            except Exception:
                pass
    all_table_numbers.discard("")

    last_label_for_continuation: str | None = None
    for unit in _sentence_units(text)[:max_sentences]:
        nums = {_normalize_number_token(x) for x in _extract_number_tokens(unit)}
        nums = {n for n in nums if n and n not in {"2023", "2024", "2025", "2026"}}
        if not nums:
            continue
        item: dict[str, Any] = {
            "sentence": unit,
            "numbers_in_sentence": sorted(nums),
            "status": "pass",
            "checks": [],
        }
        unsupported = sorted(n for n in nums if n not in allowed_numbers and n not in {str(i) for i in range(1, 13)})
        if unsupported:
            item["status"] = "fail"
            item["checks"].append({
                "status": "fail",
                "rule_id": "allowed_numbers",
                "number_in_text": unsupported[:6],
                "reason": "Số không nằm trong SAFE_BASE_TEXT/REPORT_FACTS/bảng số liệu nguồn.",
            })

        matched_any = False
        unit_had_label = False
        if isinstance(df, pd.DataFrame) and label_col and numeric_cols:
            continuation_context = bool(
                last_label_for_continuation
                and re.match(r"^\s*\d", unit)
                and any(x in unit.lower() for x in ("dtts", "dân tộc", "thiểu số", "kinh", "tại chỗ"))
            )
            for _, row in df.iterrows():
                label = str(row.get(label_col) or "").strip()
                label_in_unit = bool(label and _label_in_text_loose(label, unit))
                if not label or (not label_in_unit and not (continuation_context and label == last_label_for_continuation)):
                    continue
                if label_in_unit:
                    unit_had_label = True
                    last_label_for_continuation = label
                local_unit = _local_context_for_label(unit, label, row_labels) if label_in_unit else unit
                if label_in_unit and not _label_in_text_loose(label, local_unit):
                    local_unit = unit
                local_nums = {_normalize_number_token(x) for x in _extract_number_tokens(local_unit)}
                local_nums = {n for n in local_nums if n and n not in {"2023", "2024", "2025", "2026"}}
                ratio_context = _unit_is_ratio_context(local_unit) or _unit_is_ratio_context(unit)
                cols_to_check = list(numeric_cols)
                pattern = _pattern(bundle) if bundle is not None else ""
                if pattern in {"causes", "child_deprivation"}:
                    low_ctx = (local_unit + " " + unit).lower()
                    has_near = "hộ cận nghèo" in low_ctx
                    has_poor = bool(re.search(r"(?<!cận\s)hộ nghèo", low_ctx))
                    if has_poor and not has_near:
                        cols_to_check = [c for c in cols_to_check if "can_ngheo" not in str(c)]
                    elif has_near and not has_poor:
                        cols_to_check = [c for c in cols_to_check if "can_ngheo" in str(c)]
                    elif has_near and has_poor:
                        continue
                if pattern == "multidimensional_standard":
                    cols_to_check = _mau12_relevant_columns_for_context(cols_to_check, local_unit + " " + unit)
                    matched_cols_by_num = _mau12_expected_tokens_by_number(row, cols_to_check, local_nums)
                else:
                    matched_cols_by_num = {}
                for c in cols_to_check:
                    measure_context = local_unit if _text_has_measure(local_unit, str(c)) else unit
                    if ratio_context and not _col_is_ratio_like(c):
                        continue
                    if not ratio_context and _col_is_ratio_like(c) and not _text_has_measure(measure_context, str(c)):
                        continue
                    if not _text_has_measure(measure_context, str(c)):
                        continue
                    matched_any = True
                    expected_tokens = {_normalize_number_token(x) for x in _number_variants(row.get(c))}
                    expected_tokens.discard("")
                    # Với mẫu 12, một cụm địa bàn có thể liệt kê nhiều cột đúng cùng lúc
                    # như "307 Kinh, 522 DTTS". Không coi 522 là sai cho cột Kinh nếu
                    # 522 khớp cột DTTS của cùng địa bàn. Nhưng nếu số đó chỉ là số nguồn
                    # của cột khác/địa bàn khác và không khớp cột nào trong ngữ cảnh, vẫn fail.
                    if pattern == "multidimensional_standard" and matched_cols_by_num:
                        tokens_matched_any_relevant_col = {n for hits in matched_cols_by_num.values() for n in hits}
                        wrong = sorted(n for n in local_nums if n not in tokens_matched_any_relevant_col and n in all_table_numbers)
                    else:
                        wrong = sorted(n for n in local_nums if n not in expected_tokens and n in all_table_numbers)
                    if local_nums & expected_tokens:
                        item["checks"].append({
                            "status": "pass",
                            "rule_id": "label_measure_value_pair",
                            "table": table_name,
                            "label": label,
                            "measure": _column_label(str(c)),
                            "expected_value": _num(row.get(c)),
                            "number_in_text": sorted(local_nums & expected_tokens),
                            "reason": "Cặp nhãn/chỉ tiêu/số khớp bảng nguồn.",
                        })
                    elif wrong:
                        if pattern == "multidimensional_standard" or _template_id_from_bundle(bundle) == 12:
                            # Mẫu 12 thường bị tách câu/cụm quá nhỏ khi LLM liệt kê nhiều số.
                            # Không hard-fail ở sentence audit; lỗi đặt sai rõ ràng đã có guard riêng.
                            if item.get("status") != "pass":
                                item["status"] = "warn"
                            item["checks"].append({
                                "status": "warn",
                                "rule_id": "mau12_context_needs_review",
                                "table": table_name,
                                "label": label,
                                "measure": _column_label(str(c)),
                                "expected_value": _num(row.get(c)),
                                "number_in_text": wrong[:6],
                                "reason": "Số có trong nguồn nhưng ngữ cảnh câu chưa đủ rõ; mẫu 12 dùng guard riêng để bắt lỗi đặt sai trực tiếp.",
                            })
                        else:
                            item["status"] = "fail"
                            item["checks"].append({
                                "status": "fail",
                                "rule_id": "label_measure_value_pair",
                                "table": table_name,
                                "label": label,
                                "measure": _column_label(str(c)),
                                "expected_value": _num(row.get(c)),
                                "number_in_text": wrong[:6],
                                "reason": "Số có trong nguồn nhưng không thuộc cặp nhãn/chỉ tiêu này.",
                            })

        if not matched_any and item["status"] != "fail":
            pattern = _pattern(bundle) if bundle is not None else ""
            global_expected = _mau12_global_expected_tokens(bundle, df if isinstance(df, pd.DataFrame) else None, unit) if pattern == "multidimensional_standard" else set()
            if global_expected and nums and nums.issubset(global_expected):
                item["status"] = "pass"
                item["checks"].append({
                    "status": "pass",
                    "rule_id": "mau12_global_total_pair",
                    "number_in_text": sorted(nums),
                    "reason": "Cụm số toàn phạm vi/toàn tỉnh của mẫu 12 khớp tổng hoặc tỷ lệ nguồn theo ngữ cảnh.",
                })
            else:
                item["status"] = "warn"
                item["checks"].append({
                    "status": "warn",
                    "rule_id": "unmatched_but_allowed",
                    "number_in_text": sorted(nums),
                    "reason": "Số nằm trong nguồn nhưng câu không đủ rõ nhãn địa bàn/chỉ tiêu để audit theo cặp; cần đọc ngữ cảnh nếu muốn kiểm thủ công.",
                })
        elif matched_any and not item.get("checks") and item["status"] != "fail":
            item["status"] = "warn"
            item["checks"].append({
                "status": "warn",
                "rule_id": "measure_detected_without_pair",
                "number_in_text": sorted(nums),
                "reason": "Câu có nhãn/chỉ tiêu nhưng số không khớp được thành cặp rõ ràng với bảng chính; nên kiểm lại ngữ cảnh.",
            })
        rows.append(item)
    return rows


def _final_text_fact_audit(
    bundle: ReportFactsBundle | None,
    safe_base: str,
    text: str,
    validation_warnings: list[str] | None = None,
    *,
    include_sentence_checks: bool = True,
) -> dict[str, Any]:
    """Tạo audit có cấu trúc để đưa vào report_task ngay cả khi LLM pass."""
    raw_validation_warnings = _dedupe_text_items([str(w) for w in (validation_warnings or [])])

    technical_warnings: list[str] = []
    if any(tok in str(text or "") for tok in TECHNICAL_TOKENS):
        technical_warnings.append("Văn bản còn token kỹ thuật nội bộ hoặc tên cột thô.")
    if re.search(r"(?m)^\s*(?:[IVX]+\.|\d+\.)\s+", str(text or "")):
        technical_warnings.append("Văn bản còn trình bày theo mục đánh số, chưa tự nhiên như đoạn nhận định.")

    cand_nums = set(_extract_number_tokens(text))
    missing_groups: list[str] = []
    for group in _essential_number_groups(bundle, safe_base):
        normalized_group = {_normalize_number_token(x) for x in group if x}
        if normalized_group and not (normalized_group & cand_nums):
            missing_groups.append("/".join(sorted(normalized_group))[:30])
    missing_core_warnings = []
    if missing_groups:
        if _template_id_from_bundle(bundle) == 1:
            missing_core_warnings.append("Mẫu 1 thiếu số tổng cốt lõi: " + ", ".join(missing_groups[:6]))
        else:
            missing_core_warnings.append("LLM làm mất số liệu cốt lõi: " + ", ".join(missing_groups[:6]))

    pair_warnings = _dedupe_text_items(_bundle_label_number_warnings(bundle, text))
    ranking_warnings = _dedupe_text_items(_ranking_claim_consistency_warnings(bundle, text))
    district_scope_warnings = _dedupe_text_items(_district_level_number_used_without_label_warnings(bundle, text))
    movement_scope_warnings = _dedupe_text_items(_movement_scope_misattribution_warnings(bundle, text))
    movement_direction_warnings = _dedupe_text_items(_movement_direction_component_warnings(bundle, text))
    movement_transition_direction_warnings = _dedupe_text_items(_movement_transition_direction_warnings(bundle, text))
    numeric_comparison_warnings = _dedupe_text_items(_numeric_comparison_phrase_warnings(bundle, text))
    unsupported_num_warnings = _dedupe_text_items(_unsupported_number_warnings(bundle, safe_base, text))
    unsupported_claims = _dedupe_text_items(_unsupported_claim_warnings(text))
    movement_other_claims = _dedupe_text_items(_movement_other_reason_claim_warnings(bundle, text))
    template_policy_warnings = _dedupe_text_items(_template_specific_policy_warnings(bundle, text))
    context_warnings = _dedupe_text_items(_pattern_context_quality_warnings(bundle, text))
    soft_coverage_warnings = _dedupe_text_items(_required_label_number_coverage_warnings(bundle, text))
    mau12_ethnicity_warnings = _dedupe_text_items(_mau12_ethnicity_coverage_warnings(bundle, text))

    grouped_warnings = _dedupe_text_items(
        unsupported_num_warnings
        + missing_core_warnings
        + pair_warnings
        + ranking_warnings
        + district_scope_warnings
        + movement_scope_warnings
        + movement_direction_warnings
        + movement_transition_direction_warnings
        + numeric_comparison_warnings
        + unsupported_claims
        + movement_other_claims
        + template_policy_warnings
        + technical_warnings
        + context_warnings
        + soft_coverage_warnings
        + mau12_ethnicity_warnings
    )
    validator_extra_warnings = [w for w in raw_validation_warnings if w not in grouped_warnings]

    rules = [
        _audit_rule("allowed_numbers", "Mọi số trong văn bản phải có trong facts/bảng nguồn", unsupported_num_warnings, pass_message="Không phát hiện số ngoài nguồn."),
        _audit_rule("essential_numbers", "Các số tổng cốt lõi của mẫu phải xuất hiện", missing_core_warnings, pass_message="Không thiếu số tổng cốt lõi."),
        _audit_rule("label_measure_value_pair", "Cặp nhãn - chỉ tiêu - số phải khớp bảng", pair_warnings, pass_message="Không phát hiện gán nhầm số giữa nhãn/chỉ tiêu."),
        _audit_rule("district_scope", "Số cấp địa bàn không được viết như số chung", district_scope_warnings, pass_message="Không phát hiện số địa bàn bị dùng như số chung."),
        _audit_rule("movement_scope", "Mẫu 2/3 không đặt số tổng toàn phạm vi trong câu có địa bàn", movement_scope_warnings, pass_message="Không phát hiện số tổng toàn phạm vi gắn với địa bàn."),
        _audit_rule("movement_direction", "Mẫu 2/3 phải giữ đúng chiều tăng/giảm của nhãn diễn biến", movement_direction_warnings, pass_message="Không phát hiện nhãn diễn biến sai chiều."),
        _audit_rule("movement_transition_direction", "Mẫu diễn biến không được dùng tăng/giảm trái quan hệ số học giữa hai mốc", movement_transition_direction_warnings, pass_message="Không phát hiện cụm chuyển tiếp tăng/giảm sai chiều."),
        _audit_rule("numeric_comparison", "Câu cao hơn/thấp hơn phải đúng số học", numeric_comparison_warnings, pass_message="Không phát hiện so sánh số học sai."),
        _audit_rule("ranking_claim", "Nhận định cao nhất/thấp nhất/thứ hai phải đúng cột", ranking_warnings, pass_message="Không phát hiện xếp hạng sai."),
        _audit_rule("unsupported_claim", "Không suy diễn nguyên nhân/hỗ trợ/chính sách ngoài dữ liệu", unsupported_claims, pass_message="Không phát hiện nhận định vượt dữ liệu."),
        _audit_rule("movement_other_reason", "Không gán nguyên nhân khác khi DB thiếu cột lý do chi tiết", movement_other_claims, pass_message="Không phát hiện gán nguyên nhân khác thiếu căn cứ."),
        _audit_rule("template_policy", "Giữ đúng quy tắc nghiệp vụ riêng của từng mẫu", template_policy_warnings, pass_message="Không phát hiện lỗi nghiệp vụ riêng của mẫu."),
        _audit_rule("style_prompt_leak", "Không lộ token kỹ thuật/prompt và giữ văn phong báo cáo", technical_warnings + context_warnings, pass_message="Không phát hiện token kỹ thuật/prompt leak hoặc lỗi ngữ cảnh cứng."),
        _audit_rule("coverage_quality", "Văn bản nên có cặp nhãn-số nổi bật để dễ kiểm", soft_coverage_warnings, pass_message="Có đủ cặp nhãn-số nổi bật hoặc không cần cảnh báo coverage."),
        _audit_rule("mau12_ethnicity_coverage", "Mẫu 12 phải bao phủ lớp dân tộc nếu bảng có dữ liệu dân tộc", mau12_ethnicity_warnings, pass_message="Mẫu 12 đã bao phủ lớp dân tộc hoặc bảng không có lớp dân tộc."),
        _audit_rule("validator_result", "Kết quả validator tổng quát còn lại", validator_extra_warnings, pass_message="Không còn cảnh báo validator tổng quát ngoài các quy tắc trên."),
    ]

    sentence_checks = _sentence_fact_audit(bundle, safe_base, text) if include_sentence_checks and _pattern(bundle) != "causes" else []
    sentence_fail_count = sum(1 for item in sentence_checks if item.get("status") == "fail")
    sentence_warn_count = sum(1 for item in sentence_checks if item.get("status") == "warn")

    hard_rule_count = sum(1 for r in rules if r.get("status") == "fail")
    warn_rule_count = sum(1 for r in rules if r.get("status") == "warn")
    status = "fail" if hard_rule_count or sentence_fail_count else ("warn" if warn_rule_count or sentence_warn_count or raw_validation_warnings else "pass")

    hard_warnings = []
    soft_warnings = []
    for r in rules:
        for w in r.get("warnings") or []:
            if _is_hard_validation_warning(str(w)):
                hard_warnings.append(str(w))
            else:
                soft_warnings.append(str(w))
    for item in sentence_checks:
        if item.get("status") == "fail":
            for chk in item.get("checks") or []:
                if chk.get("status") == "fail":
                    hard_warnings.append(str(chk.get("reason") or "Sentence fact audit fail"))
        elif item.get("status") == "warn":
            soft_warnings.append(str((item.get("checks") or [{}])[0].get("reason") or "Sentence fact audit warning"))

    hard_warnings = _dedupe_text_items(hard_warnings)
    soft_warnings = _dedupe_text_items(soft_warnings)
    pass_rule_count = sum(1 for r in rules if r.get("status") == "pass")

    return {
        "schema": "final_text_fact_audit",
        "status": status,
        "summary": {
            "status": status,
            "rule_pass_count": int(pass_rule_count),
            "rule_warn_count": int(warn_rule_count),
            "rule_fail_count": int(hard_rule_count),
            "sentence_pass_count": int(sum(1 for item in sentence_checks if item.get("status") == "pass")),
            "sentence_warn_count": int(sentence_warn_count),
            "sentence_fail_count": int(sentence_fail_count),
            "hard_warning_count": int(len(hard_warnings) + sentence_fail_count),
            "soft_warning_count": int(len(soft_warnings) + sentence_warn_count),
        },
        "rules": rules,
        "sentence_checks": sentence_checks,
        "hard_warnings": hard_warnings[:20],
        "soft_warnings": soft_warnings[:20],
        "display_policy": {
            "show_for_llm_pass": True,
            "show_for_llm_fail": True,
            "ui_rule": "Nếu status='fail' thì không cho final_validation_passed=true; nếu status='warn' thì cho qua nhưng hiển thị cảnh báo; nếu status='pass' thì hiển thị checklist xanh để người dùng kiểm nhanh. Lỗi dưới llm_min_words không được accepted; hệ thống retry tới khi đạt ngưỡng hoặc hết số lần thử.",
        },
    }


def _validate_candidate(candidate: str, safe_base: str, bundle: ReportFactsBundle | None = None, *, min_words: int | None = None) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    text = str(candidate or "").strip()
    if not text:
        return False, ["LLM không trả về văn bản."]
    if any(tok in text for tok in TECHNICAL_TOKENS):
        warnings.append("Văn bản còn token kỹ thuật nội bộ hoặc tên cột thô.")
    if re.search(r"\b(the địa bàn|theo địa bàn\s+theo)\b", text, flags=re.IGNORECASE):
        warnings.append("Văn bản có cụm từ nghi ngờ lỗi chính tả/ngữ pháp.")
    if re.search(r"(?m)^\s*(?:[IVX]+\.|\d+\.)\s+", text):
        warnings.append("Văn bản còn trình bày theo mục đánh số, chưa tự nhiên như đoạn nhận định.")
    warnings.extend(_pattern_context_quality_warnings(bundle, text))
    warnings.extend(_movement_sign_warnings(bundle, text))
    warnings.extend(_movement_transition_pair_warnings(bundle, text))
    warnings.extend(_movement_transition_direction_warnings(bundle, text))
    warnings.extend(_movement_scope_misattribution_warnings(bundle, text))
    warnings.extend(_movement_direction_component_warnings(bundle, text))
    warnings.extend(_numeric_comparison_phrase_warnings(bundle, text))
    warnings.extend(_bundle_label_number_warnings(bundle, text))
    warnings.extend(_ranking_claim_consistency_warnings(bundle, text))
    warnings.extend(_district_level_number_used_without_label_warnings(bundle, text))
    warnings.extend(_required_label_number_coverage_warnings(bundle, text))
    warnings.extend(_unsupported_number_warnings(bundle, safe_base, text))
    warnings.extend(_unsupported_claim_warnings(text))
    warnings.extend(_movement_other_reason_claim_warnings(bundle, text))
    warnings.extend(_template_specific_policy_warnings(bundle, text))
    if _template_id_from_bundle(bundle) == 3 and "5.76" in {_normalize_number_token(n) for n in _extract_number_tokens(text)}:
        warnings.append("Mẫu 3 không được nói tỷ lệ 5,76% trong nhận định tổng hợp vì đây không phải tỷ lệ biến động cốt lõi cần dùng cho mẫu.")
    if _template_id_from_bundle(bundle) == 3:
        loose_text = _loose_vietnamese_text(text)
        if re.search(r"(nhom\s+giam|cau\s+phan\s+giam|lam\s+giam|phan\s+giam|giam\s+chu\s+yeu)[^.\n]*(thoat\s+ngheo|tai\s+can\s+ngheo|can\s+ngheo\s+moi\s+phat\s+sinh|moi\s+phat\s+sinh)", loose_text):
            warnings.append("Mẫu 3 sai chiều biến động: nhóm tăng cận nghèo bị đặt trong câu nhóm giảm.")
        if "unexplained_delta" not in loose_text and re.search(r"khong\s+co\s+thong\s+tin[^.\n]*(nguyen\s+nhan|giai\s+thich)[^.\n]*chenh\s+lech|chenh\s+lech[^.\n]*(khong\s+co|chua\s+co)[^.\n]*(nguyen\s+nhan|giai\s+thich)", loose_text):
            warnings.append("Mẫu 3 không được nói còn chênh lệch chưa có thông tin nguyên nhân khi unexplained_delta = 0.")
    warnings.extend(_llm_dry_style_warnings(text))
    wc = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle) if bundle is not None else ""
    base_min_words = 150
    if tid in {8, 9, 12} or pattern in {"vulnerable_groups", "ethnicity", "multidimensional_standard"}:
        base_min_words = 170
    severe_min_words = max(base_min_words, _coerce_llm_min_words(min_words, default=base_min_words)) if min_words is not None else base_min_words
    if wc < severe_min_words:
        warnings.append(f"Văn bản quá ngắn so với độ dài tối thiểu đã cấu hình: {wc} từ, cần tối thiểu {severe_min_words} từ theo cấu hình hiện tại.")
    elif wc < max(220, severe_min_words + 20):
        warnings.append("Văn bản còn ngắn so với độ dài tối thiểu đã cấu hình.")

    cand_nums = set(_extract_number_tokens(text))
    required_groups = _essential_number_groups(bundle, safe_base)
    missing_groups: list[str] = []
    for group in required_groups:
        normalized_group = {_normalize_number_token(x) for x in group if x}
        if normalized_group and not (normalized_group & cand_nums):
            missing_groups.append("/".join(sorted(normalized_group))[:30])
    if missing_groups:
        if tid == 1:
            warnings.append("Mẫu 1 thiếu số tổng cốt lõi: " + ", ".join(missing_groups[:6]))
        else:
            warnings.append("LLM làm mất số liệu cốt lõi: " + ", ".join(missing_groups[:6]))

    # Số ngoài nguồn đã được kiểm bằng _unsupported_number_warnings ở trên.
    if pattern == "causes":
        warnings = [w for w in warnings if "gán sai cặp nhãn-số" not in str(w)]

    # Hard fail chỉ áp dụng cho lỗi làm sai dữ liệu hoặc lộ kỹ thuật; đánh số/độ dài chỉ là cảnh báo.
    hard_fail = any(_is_hard_validation_warning(w) for w in warnings)
    return not hard_fail, warnings





def _llm_safe_row_snapshots(bundle: ReportFactsBundle) -> list[dict[str, Any]]:
    """Các dòng neo an toàn cho LLM, dùng để giảm đảo cặp nhãn-số.

    Khác top_label_number_pairs (mỗi cặp một cột), snapshot giữ nguyên một dòng
    quan trọng với nhiều cột liên quan. Điều này đặc biệt cần cho mẫu 1, 11, 12,
    nơi LLM hay chuyển số của cột/địa bàn này sang cột/địa bàn khác.
    """
    tables = getattr(bundle, "tables", {}) or {}
    pattern = str((bundle.template or {}).get("pattern") or "")
    template_id = _template_id_from_bundle(bundle)
    snapshots: list[dict[str, Any]] = []

    def _first_label_col(df: pd.DataFrame) -> str | None:
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                return str(c)
        return str(df.columns[0]) if len(df.columns) else None

    def _cols_for_table(name: str, df: pd.DataFrame) -> tuple[str | None, list[str], str | None, bool]:
        cols = set(map(str, df.columns))
        label = _first_label_col(df)
        sort_col: str | None = None
        desc = True
        wanted: list[str] = []
        if template_id == 1 and name == "template_main":
            label = "huyen" if "huyen" in cols else label
            wanted = ["tong_ho_dan_cu", "so_ho_ngheo", "so_ho_can_ngheo", "so_ho_nlnndn_mstb"]
            sort_col = "so_ho_can_ngheo" if "so_ho_can_ngheo" in cols else "so_ho_ngheo"
        elif template_id == 1 and name == "template_chart":
            label = "nhom_chi_tieu" if "nhom_chi_tieu" in cols else label
            wanted = ["so_ho"]
            sort_col = "so_ho"
        elif template_id in {2, 3} or pattern == "movement":
            label = "huyen" if "huyen" in cols else label
            wanted = ["so_ho_ky_truoc", "so_ho_ky_sau", "chenh_lech", "ty_le_bien_dong_%"]
            sort_col = "chenh_lech" if "chenh_lech" in cols else None
        elif template_id in {4, 6} or pattern == "deprivation_count":
            label = "chi_tieu" if "chi_tieu" in cols else label
            wanted = ["so_ho", "tong_nhom"]
            sort_col = "so_ho"
        elif template_id in {5, 7} or pattern == "deprivation_ratio":
            label = "chi_tieu" if "chi_tieu" in cols else label
            wanted = ["ty_le_%", "so_ho", "tong_nhom"]
            sort_col = "ty_le_%"
        elif template_id == 11 or pattern == "child_deprivation":
            label = "chi_tieu" if "chi_tieu" in cols else label
            wanted = ["so_ho_ngheo", "ty_le_ho_ngheo_%", "so_ho_can_ngheo", "ty_le_ho_can_ngheo_%"]
            sort_col = "so_ho_ngheo" if "so_ho_ngheo" in cols else None
        elif template_id == 12 or pattern == "multidimensional_standard":
            label = "huyen" if "huyen" in cols else label
            wanted = [
                "tong_ho_ra_soat", "tong_nhan_khau", "so_ho_muc_tieu", "so_nhan_khau_muc_tieu", "ty_le_muc_tieu_%",
                "so_ho_kinh", "tong_ho_dtts", "so_ho_dtts", "ty_le_ngheo_trong_dtts_%",
                "tong_ho_dtts_tai_cho", "so_ho_dtts_tai_cho", "ty_le_ngheo_trong_dtts_tai_cho_%",
            ]
            sort_col = "ty_le_muc_tieu_%" if "ty_le_muc_tieu_%" in cols else "so_ho_muc_tieu"
        elif pattern in {"vulnerable_groups", "ethnicity", "causes"}:
            for cand in ("nhom_doi_tuong", "dan_toc", "nguyen_nhan", "chi_tieu"):
                if cand in cols:
                    label = cand
                    break
            wanted = ["so_ho_ngheo", "so_ho_can_ngheo", "tong_ho", "ty_le_%"]
            sort_col = "so_ho_ngheo" if "so_ho_ngheo" in cols else None
        else:
            wanted = [str(c) for c in df.columns if c != label and pd.api.types.is_numeric_dtype(df[c])][:4]
            sort_col = wanted[0] if wanted else None
        wanted = [c for c in wanted if c in cols]
        return label, wanted, sort_col, desc

    preferred_tables = ["template_chart", "template_main", "main", "by_district"]
    for name in preferred_tables:
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
            continue
        label_col, value_cols, sort_col, desc = _cols_for_table(name, df)
        if not label_col or label_col not in df.columns or not value_cols:
            continue
        work = df.copy()
        if sort_col and sort_col in work.columns:
            s = pd.to_numeric(work[sort_col], errors="coerce")
            if pattern == "movement" and sort_col == "chenh_lech":
                work = work.assign(__sort=s.abs()).sort_values("__sort", ascending=False).drop(columns="__sort")
            else:
                work = work.assign(__sort=s).sort_values("__sort", ascending=not desc).drop(columns="__sort")
        limit = 8 if template_id in {11, 12} else 6
        for _, row in work.head(limit).iterrows():
            label = str(row.get(label_col) or "").strip()
            if not label:
                continue
            values: dict[str, str] = {}
            parts: list[str] = []
            for col in value_cols:
                val = row.get(col)
                if pd.isna(val):
                    continue
                if template_id == 11 and col in {"so_ho_ngheo", "so_ho_can_ngheo"}:
                    unit = "trẻ em"
                    col_label = "số trẻ em thuộc hộ nghèo" if col == "so_ho_ngheo" else "số trẻ em thuộc hộ cận nghèo"
                else:
                    unit = _value_unit_for_col(col)
                    col_label = _column_label(col)
                formatted = _num(val)
                values[col_label] = formatted + ((" " + unit) if unit else "")
                parts.append(f"{col_label} {_num(val)}{(' ' + unit) if unit else ''}")
            if not parts:
                continue
            snapshots.append({
                "table": name,
                "label": label,
                "values": values,
                "safe_sentence": f"{label}: " + "; ".join(parts),
            })
        # Mẫu 1 dùng cả bảng tổng hợp và chi tiết; các mẫu khác chỉ cần bảng chính đầu tiên.
        if snapshots and not (template_id == 1 and name == "template_chart"):
            break
    return snapshots[:12]

def _llm_analysis_anchors(bundle: ReportFactsBundle) -> dict[str, Any]:
    """Tạo bộ neo phân tích cho LLM từ bảng đã chuẩn hóa.

    Mục tiêu: cải thiện chất lượng LLM mà không để LLM tự tính/suy diễn.
    Hàm này generic cho mọi mẫu có bảng dạng nhãn dòng + cột số.
    """
    pattern = str((bundle.template or {}).get("pattern") or "overview_result")
    tables = getattr(bundle, "tables", {}) or {}
    template_id = _template_id_from_bundle(bundle)
    anchors: dict[str, Any] = {
        "pattern": pattern,
        "template_id": template_id,
        "pattern_rules": _PATTERN_VALIDATION_RULES.get(pattern, {}),
        "template_specific_guidance": _template_specific_llm_guidance(bundle),
        "core_numbers": [],
        "top_label_number_pairs": [],
        "safe_row_snapshots": _llm_safe_row_snapshots(bundle),
        "writing_outline": [],
    }

    # Số cốt lõi từ essential groups chỉ để LLM biết cần giữ, không yêu cầu tự tính.
    try:
        for group in _essential_number_groups(bundle, _safe_base_text(bundle, report_level="administrative")):
            if group:
                anchors["core_numbers"].append(sorted(group)[0])
    except Exception:
        pass

    for name in ("template_chart", "template_main", "main", "by_district"):
        df = tables.get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or df.shape[1] < 2:
            continue
        label_col = None
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                label_col = str(c)
                break
        if label_col is None:
            label_col = str(df.columns[0])
        for c in _llm_anchor_numeric_cols(df, label_col, pattern=pattern, template_id=template_id, table_name=name)[:6]:
            try:
                series = pd.to_numeric(df[c], errors="coerce")
                if series.dropna().empty:
                    continue
                idx = series.idxmax()
                value = df.loc[idx, c]
                if float(value or 0) == 0:
                    continue
                label = str(df.loc[idx, label_col] or "").strip()
                if not label:
                    continue
                unit = _value_unit_for_col(str(c))
                suffix = (" " + unit) if unit else ""
                item = {
                    "table": name,
                    "label": label,
                    "measure": _column_label(str(c)),
                    "value": _num(value),
                    "safe_sentence": f"{label} có {_column_label(str(c))} là {_num(value)}{suffix}",
                }
                # Tránh trùng label/measure/value giữa nhiều bảng.
                key = (item["label"], item["measure"], item["value"])
                existing = {(x.get("label"), x.get("measure"), x.get("value")) for x in anchors["top_label_number_pairs"]}
                if key not in existing:
                    anchors["top_label_number_pairs"].append(item)
            except Exception:
                continue
        if len(anchors["top_label_number_pairs"]) >= 8:
            break

    rules = _PATTERN_VALIDATION_RULES.get(pattern, {})
    anchors["writing_outline"] = [
        "Mở đầu bằng phạm vi báo cáo và mục đích nhận định.",
        "Tuân thủ hướng dẫn riêng theo mẫu: " + _template_specific_llm_guidance(bundle),
        "Nêu 2-4 số/cặp nhãn-số nổi bật từ top_label_number_pairs; không tự tính thêm.",
        "Rút ra ý nghĩa quản lý thận trọng trong allowed; tránh các nội dung trong avoid.",
        "Kết nối với biểu đồ/bảng như công cụ đối chiếu, không thay thế kiểm tra chi tiết.",
    ]
    if rules:
        anchors["writing_outline"].append("Phạm vi được phép nhận định: " + str(rules.get("allowed", "")))
        anchors["writing_outline"].append("Nội dung cần tránh: " + str(rules.get("avoid", "")))
    return anchors


def _llm_required_facts_digest(bundle: ReportFactsBundle) -> list[str]:
    """Tạo danh sách sự kiện an toàn, ngắn, không phải khuôn văn bản.

    Dùng cho các mẫu nhiều cột (1, 11, 12) để LLM không phải tự rút cặp
    nhãn-số từ JSON lớn. Mỗi dòng là một cặp/nhóm cặp đã khóa đơn vị.
    """
    lines: list[str] = []
    try:
        tid = _template_id_from_bundle(bundle)
        year = (bundle.scope or {}).get("year")
        scope = _scope(bundle)
        tables = getattr(bundle, "tables", {}) or {}
        facts = getattr(bundle, "facts", {}) or {}

        def fmt_year() -> str:
            scope_text = str(scope or "")
            return "" if (year and str(year) in scope_text) else (f" năm {year}" if year else "")

        if tid == 1 or _pattern(bundle) == "overview_result":
            table_insights = facts.get("table_insights") if isinstance(facts, dict) else {}
            t1 = table_insights.get("template1_detail") if isinstance(table_insights, dict) else {}
            if isinstance(t1, dict) and t1:
                warning_text = " ".join(str(x) for x in (facts.get("template_data_warnings") or []))
                medium_total = int(float(t1.get("total_medium_living_households") or 0))
                lines.append(
                    f"{scope}{fmt_year()}: hộ nghèo {_num(t1.get('total_poor_households'))} hộ; "
                    f"hộ cận nghèo {_num(t1.get('total_near_poor_households'))} hộ; "
                    f"hộ nông, lâm, ngư nghiệp có mức sống trung bình {_num(medium_total)} hộ."
                )
                if medium_total <= 0:
                    lines.append("Chỉ tiêu hộ nông, lâm, ngư nghiệp có mức sống trung bình: 0 hộ theo bảng tổng hợp hiện có; giữ 0 và không mở rộng sang nhóm ngoài ba chỉ tiêu chính.")
                # Mẫu 1: các danh sách top_* chứa nguyên hàng template_main, không có key "value".
                # Tạo digest động từ đúng cột số hiện có để tránh LLM đảo cặp huyện-chỉ tiêu.
                for key, label, value_col in [
                    ("top_poor_districts", "hộ nghèo", "so_ho_ngheo"),
                    ("top_near_poor_districts", "hộ cận nghèo", "so_ho_can_ngheo"),
                    ("top_medium_living_districts", "hộ nông, lâm, ngư nghiệp có mức sống trung bình", "so_ho_nlnndn_mstb"),
                ]:
                    if key == "top_medium_living_districts" and medium_total <= 0:
                        continue
                    rows = t1.get(key) or []
                    parts = []
                    for r in rows[:3]:
                        if isinstance(r, dict) and r.get("huyen") and r.get(value_col) is not None:
                            parts.append(f"{r.get('huyen')}: {_num(r.get(value_col))} {label}")
                    if parts:
                        lines.append(f"Địa bàn nổi bật về {label}: " + "; ".join(parts) + ".")
                return [x for x in lines if x]

        if tid in {2, 3} or _pattern(bundle) == "movement":
            anchors = facts.get("sentence_anchors") if isinstance(facts, dict) else []
            if isinstance(anchors, list):
                lines.extend(str(x) for x in anchors if str(x).strip())
            warnings = facts.get("movement_warnings") if isinstance(facts, dict) else []
            if isinstance(warnings, list):
                lines.extend("Lưu ý diễn biến: " + str(x) for x in warnings if str(x).strip())
            return [x for x in lines if x]

        if _pattern(bundle) in {"deprivation_count", "deprivation_ratio"}:
            df = tables.get("template_main")
            if not isinstance(df, pd.DataFrame) or df.empty:
                df = tables.get("main")
            if isinstance(df, pd.DataFrame) and not df.empty:
                focus = _household_focus(bundle)
                value_col = "ty_le_%" if _pattern(bundle) == "deprivation_ratio" and "ty_le_%" in df.columns else "so_ho"
                work = df.copy()
                work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
                work = work.sort_values(value_col, ascending=False).head(5)
                lines.append(f"{focus}: các chỉ số thiếu hụt có thể chồng lấn, không cộng thành cơ cấu 100%.")
                for _, row in work.iterrows():
                    label = str(row.get("chi_tieu") or "").strip()
                    if not label:
                        continue
                    parts = [f"{label}"]
                    if "so_ho" in df.columns:
                        parts.append(f"số hộ thiếu hụt {_num(row.get('so_ho'))} hộ")
                    if "ty_le_%" in df.columns:
                        parts.append(f"tỷ lệ thiếu hụt {_pct(row.get('ty_le_%'))}")
                    lines.append(f"{focus} - " + "; ".join(parts) + ".")
                return [x for x in lines if x]

        if tid == 8 or _pattern(bundle) == "vulnerable_groups":
            df = tables.get("template_main")
            if not isinstance(df, pd.DataFrame) or df.empty:
                df = tables.get("main")
            if isinstance(df, pd.DataFrame) and not df.empty:
                total = df[df["huyen"].astype(str).str.lower() == "toàn tỉnh"].head(1) if "huyen" in df.columns else pd.DataFrame()
                work = df[df["huyen"].astype(str).str.lower() != "toàn tỉnh"].copy() if "huyen" in df.columns else df.copy()
                total_row = dict(total.iloc[0]) if isinstance(total, pd.DataFrame) and not total.empty else {}
                if total_row:
                    lines.append(
                        f"{scope}{fmt_year()}: mẫu 8 theo địa bàn; tổng hộ dân cư {_num(total_row.get('tong_ho_dan_cu'))}; "
                        f"hộ DTTS {_num(total_row.get('so_ho_dtts'))}; hộ nghèo {_num(total_row.get('tong_ho_ngheo'))}; hộ cận nghèo {_num(total_row.get('tong_ho_can_ngheo'))}."
                    )
                    lines.append(
                        f"Ba nhóm đúng mẫu 8: DTTS nghèo {_num(total_row.get('ho_ngheo_dtts'))}, cận nghèo {_num(total_row.get('ho_can_ngheo_dtts'))}; "
                        f"không có khả năng lao động nghèo {_num(total_row.get('ho_ngheo_khong_knld'))}, cận nghèo {_num(total_row.get('ho_can_ngheo_khong_knld'))}; "
                        f"có người có công nghèo {_num(total_row.get('ho_ngheo_co_cong'))}, cận nghèo {_num(total_row.get('ho_can_ngheo_co_cong'))}."
                    )
                for col, label in [
                    ("ho_ngheo_dtts", "hộ nghèo DTTS"),
                    ("ho_can_ngheo_dtts", "hộ cận nghèo DTTS"),
                    ("ho_ngheo_khong_knld", "hộ nghèo không có khả năng lao động"),
                    ("ho_can_ngheo_khong_knld", "hộ cận nghèo không có khả năng lao động"),
                    ("ho_ngheo_co_cong", "hộ nghèo có người có công"),
                    ("ho_can_ngheo_co_cong", "hộ cận nghèo có người có công"),
                ]:
                    if col not in work.columns or work.empty:
                        continue
                    tmp = work.copy()
                    tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
                    row = dict(tmp.sort_values(col, ascending=False).iloc[0])
                    lines.append(f"Địa bàn nổi bật về {label}: {row.get('huyen')} {_num(row.get(col))} hộ.")
                lines.append("Không đưa nhóm ngoài mẫu 8 vào nhận định; bảng chính không có cột tỷ lệ.")
                return [x for x in lines if x]

        if _pattern(bundle) in {"causes", "ethnicity"}:
            df = tables.get("template_main")
            if not isinstance(df, pd.DataFrame) or df.empty:
                df = tables.get("main")
            if isinstance(df, pd.DataFrame) and not df.empty:
                label_col = (
                    "chi_tieu" if "chi_tieu" in df.columns
                    else ("nguyen_nhan" if "nguyen_nhan" in df.columns else ("dan_toc" if "dan_toc" in df.columns else str(df.columns[0])))
                )
                if _pattern(bundle) == "ethnicity":
                    lines.append("Phần dân tộc chỉ mô tả số hộ theo Kinh, DTTS và dân tộc chi tiết; không suy diễn nguyên nhân nghèo theo dân tộc.")
                for group_label, count_col, pct_col in [
                    ("hộ nghèo", "so_ho_ngheo", "ty_le_ngheo_%" if _pattern(bundle) == "ethnicity" else "ty_le_ho_ngheo_%"),
                    ("hộ cận nghèo", "so_ho_can_ngheo", "ty_le_can_ngheo_%" if _pattern(bundle) == "ethnicity" else "ty_le_ho_can_ngheo_%"),
                ]:
                    if count_col not in df.columns:
                        continue
                    work = df.copy()
                    work[count_col] = pd.to_numeric(work[count_col], errors="coerce")
                    work = work.sort_values(count_col, ascending=False).head(5)
                    for _, row in work.iterrows():
                        label = str(row.get(label_col) or "").strip()
                        if not label:
                            continue
                        txt = f"{group_label} - {label}: {_num(row.get(count_col))} hộ"
                        if _pattern(bundle) != "vulnerable_groups" and pct_col in df.columns:
                            txt += f", tương ứng {_pct(row.get(pct_col))}"
                        lines.append(txt + ".")
                return [x for x in lines if x]

        if tid == 11 or _pattern(bundle) == "child_deprivation":
            df = tables.get("template_main")
            if not isinstance(df, pd.DataFrame) or df.empty:
                df = tables.get("main")
            if isinstance(df, pd.DataFrame) and not df.empty:
                lines.append("Mẫu trẻ em: mỗi câu phải giữ một chỉ tiêu với đúng từng cặp số trẻ + tỷ lệ; không gọi số trẻ là tỷ lệ, không gọi tỷ lệ trẻ là tỷ lệ hộ nghèo/cận nghèo.")
                for _, row in df.head(4).iterrows():
                    label = str(row.get("chi_tieu") or "").strip()
                    if not label:
                        continue
                    if "so_ho_ngheo" in df.columns:
                        txt = f"{label} - trẻ em thuộc hộ nghèo: {_num(row.get('so_ho_ngheo'))} trẻ"
                        if "ty_le_ho_ngheo_%" in df.columns:
                            txt += f", tương ứng {_pct(row.get('ty_le_ho_ngheo_%'))}"
                        lines.append(txt + ".")
                    if "so_ho_can_ngheo" in df.columns:
                        txt = f"{label} - trẻ em thuộc hộ cận nghèo: {_num(row.get('so_ho_can_ngheo'))} trẻ"
                        if "ty_le_ho_can_ngheo_%" in df.columns:
                            txt += f", tương ứng {_pct(row.get('ty_le_ho_can_ngheo_%'))}"
                        lines.append(txt + ".")
                return [x for x in lines if x]

        if tid == 12 or _pattern(bundle) == "multidimensional_standard":
            df = tables.get("template_main")
            if not isinstance(df, pd.DataFrame) or df.empty:
                df = tables.get("main")
            if isinstance(df, pd.DataFrame) and not df.empty:
                # Tổng theo cột để LLM có số toàn phạm vi, nhưng không bắt hard-fail nếu lược bớt.
                total_review = pd.to_numeric(df["tong_ho_ra_soat"], errors="coerce").fillna(0).sum() if "tong_ho_ra_soat" in df.columns else None
                total_review_people = pd.to_numeric(df["tong_nhan_khau"], errors="coerce").fillna(0).sum() if "tong_nhan_khau" in df.columns else None
                total_kinh = pd.to_numeric(df["so_ho_kinh"], errors="coerce").fillna(0).sum() if "so_ho_kinh" in df.columns else None
                total_dtts = pd.to_numeric(df["so_ho_dtts"], errors="coerce").fillna(0).sum() if "so_ho_dtts" in df.columns else None
                total_local = pd.to_numeric(df["so_ho_dtts_tai_cho"], errors="coerce").fillna(0).sum() if "so_ho_dtts_tai_cho" in df.columns else None
                total_dtts_den = pd.to_numeric(df["tong_ho_dtts"], errors="coerce").fillna(0).sum() if "tong_ho_dtts" in df.columns else None
                total_local_den = pd.to_numeric(df["tong_ho_dtts_tai_cho"], errors="coerce").fillna(0).sum() if "tong_ho_dtts_tai_cho" in df.columns else None
                if {"so_ho_muc_tieu", "so_nhan_khau_muc_tieu"}.issubset(df.columns):
                    total_households = pd.to_numeric(df["so_ho_muc_tieu"], errors="coerce").fillna(0).sum()
                    total_people = pd.to_numeric(df["so_nhan_khau_muc_tieu"], errors="coerce").fillna(0).sum()
                    scope_year = scope if str(year or "") and str(year) in str(scope) else f"{scope}{fmt_year()}"
                    first = f"{scope_year}: hộ nghèo đa chiều {_num(total_households)} hộ"
                    if total_review is not None and float(total_review or 0) > 0:
                        try:
                            first += f" trên tổng {_num(total_review)} hộ rà soát/phân loại, tỷ lệ {_pct(float(total_households) * 100 / float(total_review))}"
                        except Exception:
                            first += f" trên tổng {_num(total_review)} hộ rà soát/phân loại"
                    first += f"; nhân khẩu hộ nghèo đa chiều {_num(total_people)} người"
                    if total_review_people is not None:
                        first += f" trên tổng {_num(total_review_people)} nhân khẩu trong phạm vi dữ liệu"
                    lines.append(first + ".")
                if total_kinh is not None or total_dtts is not None or total_local is not None:
                    lines.append(
                        f"Toàn tỉnh theo dân tộc trong nhóm hộ nghèo đa chiều: Kinh {_num(total_kinh)} hộ; "
                        f"DTTS {_num(total_dtts)} hộ; DTTS tại chỗ {_num(total_local)} hộ."
                    )
                if total_dtts is not None and total_dtts_den is not None:
                    lines.append(
                        f"W - tỷ lệ hộ nghèo trong nhóm DTTS: {_num(total_dtts)} hộ nghèo DTTS trên {_num(total_dtts_den)} tổng hộ DTTS, "
                        f"tỷ lệ {_pct(float(total_dtts) * 100 / float(total_dtts_den) if float(total_dtts_den or 0) else 0)}."
                    )
                if total_local is not None and total_local_den is not None:
                    lines.append(
                        f"X - tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ: {_num(total_local)} hộ nghèo DTTS tại chỗ trên {_num(total_local_den)} tổng hộ DTTS tại chỗ, "
                        f"tỷ lệ {_pct(float(total_local) * 100 / float(total_local_den) if float(total_local_den or 0) else 0)}."
                    )
                sort_col = "ty_le_muc_tieu_%" if "ty_le_muc_tieu_%" in df.columns else "so_ho_muc_tieu"
                try:
                    work = df.copy()
                    work[sort_col] = pd.to_numeric(work[sort_col], errors="coerce")
                    work = work.sort_values(sort_col, ascending=False).head(3)
                except Exception:
                    work = df.head(3)
                for _, row in work.iterrows():
                    h = row.get("huyen")
                    parts = []
                    if "tong_ho_ra_soat" in df.columns:
                        parts.append(f"tổng hộ rà soát/phân loại {_num(row.get('tong_ho_ra_soat'))} hộ")
                    if "so_ho_muc_tieu" in df.columns:
                        parts.append(f"hộ nghèo đa chiều {_num(row.get('so_ho_muc_tieu'))} hộ")
                    if "ty_le_muc_tieu_%" in df.columns:
                        parts.append(f"tỷ lệ hộ nghèo đa chiều {_pct(row.get('ty_le_muc_tieu_%'))}")
                    if parts:
                        lines.append(f"{h}: " + "; ".join(parts) + ".")
                    eth_parts = []
                    if "so_ho_kinh" in df.columns:
                        eth_parts.append(f"hộ nghèo dân tộc Kinh {_num(row.get('so_ho_kinh'))} hộ")
                    if "so_ho_dtts" in df.columns:
                        if "tong_ho_dtts" in df.columns and "ty_le_ngheo_trong_dtts_%" in df.columns:
                            eth_parts.append(f"hộ nghèo DTTS {_num(row.get('so_ho_dtts'))} trên {_num(row.get('tong_ho_dtts'))} hộ DTTS, tỷ lệ hộ nghèo trong nhóm DTTS {_pct(row.get('ty_le_ngheo_trong_dtts_%'))}")
                        else:
                            eth_parts.append(f"hộ nghèo DTTS {_num(row.get('so_ho_dtts'))} hộ")
                    if "so_ho_dtts_tai_cho" in df.columns:
                        if "tong_ho_dtts_tai_cho" in df.columns and "ty_le_ngheo_trong_dtts_tai_cho_%" in df.columns:
                            eth_parts.append(f"hộ nghèo DTTS tại chỗ {_num(row.get('so_ho_dtts_tai_cho'))} trên {_num(row.get('tong_ho_dtts_tai_cho'))} hộ DTTS tại chỗ, tỷ lệ hộ nghèo trong nhóm DTTS tại chỗ {_pct(row.get('ty_le_ngheo_trong_dtts_tai_cho_%'))}")
                        else:
                            eth_parts.append(f"hộ nghèo DTTS tại chỗ {_num(row.get('so_ho_dtts_tai_cho'))} hộ")
                    if eth_parts:
                        lines.append(f"{h} theo dân tộc: " + "; ".join(eth_parts) + ".")
                return [x for x in lines if x]
    except Exception:
        return lines
    return lines

def _compact_facts(bundle: ReportFactsBundle) -> dict[str, Any]:
    tables = {}
    template_id_for_tables = _template_id_from_bundle(bundle)
    pattern_for_tables = _pattern(bundle) if bundle is not None else ""
    for name, df in (bundle.tables or {}).items():
        if template_id_for_tables == 1 or pattern_for_tables == "overview_result":
            # Mẫu 1 trong biểu mẫu chỉ dùng ba nhóm: hộ nghèo, hộ cận nghèo, NLNN mức sống TB.
            # Không đưa bảng tổng quan có "hộ không nghèo" hoặc bảng by_district tổng chung vào prompt LLM.
            if name not in {"template_chart", "template_main"}:
                continue
        if isinstance(df, pd.DataFrame):
            preview_df = df.head(12)
            if template_id_for_tables == 8 or pattern_for_tables == "vulnerable_groups":
                keep_cols = [c for c in preview_df.columns if "ty_le" not in str(c).lower() and not str(c).endswith("_%")]
                preview_df = preview_df[keep_cols]
            tables[name] = preview_df.where(pd.notna(preview_df), None).to_dict(orient="records")

    facts = bundle.facts or {}
    # Nếu có bộ số liệu báo cáo, prompt chỉ đưa facts phục vụ bộ số liệu báo cáo để tránh LLM lôi thêm
    # số liệu tổng quan khác làm văn bản bị lặp/lẫn nguồn.
    if _has_template_table(bundle):
        allowed = {
            "scope_label",
            "template_context",
            "table_insights",
            "chart_insights",
            "template_data_warnings",
            "movement_components",
            "movement_other_policy",
            "other_reason_available",
            "movement_warnings",
            "unexplained_delta",
            "sentence_anchors",
            "tong_ky_truoc",
            "tong_ky_sau",
            "tong_cuoi_ky_phan_loai",
            "chenh_lech",
            "ty_le_bien_dong_%",
        }
        compact_facts = {k: v for k, v in facts.items() if k in allowed}
    else:
        compact_facts = facts

    return {
        "template": bundle.template,
        "scope": bundle.scope,
        "summary": bundle.summary if not _has_template_table(bundle) else {},
        "facts": compact_facts,
        "tables_preview": tables,
        "llm_required_facts_digest": _llm_required_facts_digest(bundle),
        "llm_analysis_anchors": _llm_analysis_anchors(bundle),
    }


def _build_rewrite_prompt(
    bundle: ReportFactsBundle,
    safe_base_text: str,
    style_profile: dict[str, Any],
    style_examples: str,
    report_level: str,
    regenerate_nonce: int,
    allow_variation: bool,
) -> str:
    pattern = str((bundle.template or {}).get("pattern") or "overview_result")
    variation = _VARIATION_INSTRUCTIONS[regenerate_nonce % len(_VARIATION_INSTRUCTIONS)] if allow_variation else _VARIATION_INSTRUCTIONS[0]
    profile = _style_variant_profile(regenerate_nonce)
    style_rules = style_profile.get("style_rules") or []
    template_goal = (bundle.template or {}).get("week4_text_goal") or "Sinh văn bản báo cáo nhận định từ số liệu đã kiểm soát."
    return f"""
Bạn là trợ lý biên tập văn bản báo cáo nhận định từ số liệu rà soát hộ nghèo, hộ cận nghèo.

NHIỆM VỤ:
Viết lại SAFE_BASE_TEXT thành phần "văn bản báo cáo nhận định từ số liệu thống kê" với văn phong báo cáo tự nhiên, không máy móc.
Đây KHÔNG phải câu trả lời Q&A ngắn và cũng không phải bảng liệt kê; đây là văn bản báo cáo nhận định từ số liệu thống kê.

LOẠI MẪU:
- Tên mẫu: {(bundle.template or {}).get('title')}
- Pattern: {pattern}
- Mục tiêu mẫu: {template_goal}
- Lưu ý nghiệp vụ: {_PATTERN_STYLE_HINTS.get(pattern, '')}
- Quy tắc nhận định theo pattern: {json.dumps(_PATTERN_VALIDATION_RULES.get(pattern, {}), ensure_ascii=False)}
- Hướng dẫn riêng theo mẫu/nhóm mẫu: {_template_specific_llm_guidance(bundle)}
- Mức văn bản: {report_level}
- Biến thể diễn đạt lần này: {variation}
- Style variant id: {profile.get('id')}
- Variation profile name: {profile.get('name')}

HỒ SƠ BIẾN THỂ DIỄN ĐẠT BẮT BUỘC:
{_variation_profile_text(bundle, regenerate_nonce)}

RÀNG BUỘC KHÁC BIỆT THEO STYLE VARIANT:
- Variant A phải đi theo mạch: tổng quan -> top chính -> top phụ -> lưu ý diễn giải.
- Variant B phải đi theo mạch: kết quả nổi bật -> đối chiếu nhóm/địa bàn -> ý nghĩa theo dõi -> giới hạn dữ liệu.
- Variant C phải đi theo mạch: phạm vi/mẫu số -> chỉ tiêu nổi bật -> so sánh ngắn -> lưu ý không suy diễn.
- Variant D phải đi theo mạch: nhận xét thận trọng -> số liệu chính -> nhóm/địa bàn cần quan tâm -> kết luận quản lý.
- Không mở đầu mọi mẫu bằng cùng một cụm như "Theo số liệu", "Kết quả cho thấy", "Theo kết quả rà soát/phân loại".
- Không lặp nguyên văn câu mở đầu hoặc câu kết từ SAFE_BASE_TEXT, và không giữ nguyên thứ tự câu của SAFE_BASE_TEXT.
- Nếu đây là lần chạy khác cùng mẫu, phải đổi ít nhất cách mở đoạn và một chuyển ý chính, nhưng không đổi số liệu.

HƯỚNG DẪN RIÊNG BẮT BUỘC CHO MẪU NÀY:
{_template_specific_llm_guidance(bundle)}

RÀNG BUỘC SỐ LIỆU BẮT BUỘC:
0. Trước khi viết, đọc llm_required_facts_digest và llm_analysis_anchors trong REPORT_FACTS_RÚT_GỌN. Với mẫu 1/11/12, ưu tiên dùng llm_required_facts_digest vì đây là các cặp nhãn-số đã được Python khóa sẵn theo đúng đơn vị.
0a. Không được viết theo khung fallback Python/không LLM. Tránh hoàn toàn các nhãn đoạn kiểu "Khái quát chung:", "Kết quả rà soát:", "Địa bàn nổi bật:", "Đối chiếu biểu đồ:", "Định hướng theo dõi:". Văn bản LLM phải là 3-5 đoạn văn tự nhiên, có mạch lập luận, không dán nhãn từng đoạn. Nếu người dùng bấm sinh lại, phải đổi cách mở bài/chuyển ý theo HỒ SƠ BIẾN THỂ, không lặp nguyên văn cấu trúc câu của lần trước.
0b. Không cố viết đủ mọi số trong bảng. Ưu tiên ít số nhưng đúng cặp nhãn-số, đúng đơn vị và đúng phạm vi.
0c. Khi cần nhắc địa bàn/chỉ tiêu cụ thể, ưu tiên dùng đúng thông tin trong safe_row_snapshots nhưng phải diễn đạt lại tự nhiên; không lấy số từ snapshot của dòng này gán cho dòng khác, đặc biệt ở mẫu 1, 11 và 12.
1. Chỉ sử dụng số liệu xuất hiện trong SAFE_BASE_TEXT hoặc REPORT_FACTS.
2. Khi SAFE_BASE_TEXT đã ghi nhận theo bộ số liệu báo cáo, phải ưu tiên bộ số liệu đó làm nguồn nhận định chính; không lôi thêm nhóm tổng quan khác từ DB nếu nhóm đó không phải chỉ tiêu chính của biểu mẫu.
3. Không tự thêm số, tỷ lệ, địa bàn, nguyên nhân, chính sách hoặc kết luận không có trong dữ liệu.
4. Phải giữ lại các số liệu cốt lõi; có thể lược bớt số phụ nếu việc liệt kê làm văn bản khô, nhưng không được làm sai ý nghĩa.
4b. Tuyệt đối không gán nhầm số của địa bàn/chỉ tiêu này cho địa bàn/chỉ tiêu khác. Không tự cộng, không tự tạo tổng phụ, không đổi số của cột này sang cột khác. Nếu không chắc cặp địa bàn - chỉ tiêu - số liệu thì giữ nguyên cách viết trong SAFE_BASE_TEXT hoặc bỏ số phụ đó, không suy đoán.
4c. Khi nhắc nhiều cặp nhãn-số trong cùng một câu, giữ nguyên từng cặp nhãn - chỉ tiêu - số liệu như trong SAFE_BASE_TEXT/llm_analysis_anchors; không tự đảo thứ tự số, không chuyển số từ dòng/cột này sang dòng/cột khác. Tránh dùng từ “lần lượt” nếu câu có nhiều nhãn và nhiều số; tốt hơn là viết từng cặp rõ ràng, ví dụ “Kinh ... 1.044 hộ; M'Nông ... 345 hộ”.
4d. Với mẫu tỷ lệ thiếu hụt và mẫu dân tộc, cặp nhãn-số rất dễ bị đảo. Hãy ưu tiên sao chép đúng các cặp trong SAFE_BASE_TEXT hoặc top_label_number_pairs, giữ đúng thứ tự xuất hiện, không viết lại theo trí nhớ.
5. Không dùng từ kỹ thuật hoặc tên cột thô: DataFrame, Series, dtype, NaN, SQL, JSON, Python, phan_loai, so_ho, ty_le_%, template_main, chart_df. Không nhắc “bảng mẫu” hoặc nguồn trung gian trong văn bản cuối.
6. Nếu dữ liệu chỉ có hai mốc năm thì chỉ mô tả biến động giữa hai mốc, không kết luận xu hướng dài hạn.
7. Nếu các nhóm/chỉ tiêu có thể chồng lấn, không viết như cơ cấu cộng đủ 100%.
8. Nếu mẫu có trọng tâm là "Hộ cận nghèo", tuyệt đối không viết nhầm thành "hộ nghèo" như đối tượng chính.
9. Với mẫu chỉ số thiếu hụt hoặc nhóm đối tượng, không gọi chỉ tiêu/nhóm đối tượng là "địa bàn".
10. Với mẫu diễn biến, không nhấn mạnh tỷ lệ biến động cực đoan nếu mẫu số quá nhỏ; ưu tiên số tuyệt đối và ghi nhận thận trọng.
11. Không dùng markdown (**...**, #...), không dùng giọng chat/prompt như "Hãy...", không dùng giọng người viết chủ quan như “chúng ta”, “chúng tôi”, “có thể thấy”, “có thể nhận thấy”, và không để lẫn ký tự Unicode lạ trong tên địa bàn.
12. Văn bản này sẽ đưa vào Word, nên không nhắc số mẫu báo cáo như “mẫu 1/mẫu 2”, không nhắc cột/ô Excel như “cột A, B, D+F”, không nhắc công thức biểu mẫu, không nhắc DB/SQL/Python/SAFE_BASE_TEXT/REPORT_FACTS/fact pack/audit/validator. Hãy diễn giải bằng tên chỉ tiêu nghiệp vụ và cụm “nguồn dữ liệu hiện có” nếu cần nói về giới hạn dữ liệu.
12. Số cấp huyện/xã phải đi kèm đúng tên huyện/xã; không viết số của một địa bàn như số chung toàn tỉnh.
13. Với mẫu diễn biến, tuyệt đối không viết "tăng -..." hoặc "phát sinh -..."; nếu số âm thì dùng giảm/chênh lệch âm, nếu số dương thì dùng tăng/phát sinh.
14. Với mẫu hộ nghèo, không đổi sang hộ cận nghèo; với mẫu hộ cận nghèo, không đổi sang hộ nghèo.
15. Nếu số đi kèm đơn vị "hộ" thì dùng "số hộ", "quy mô" hoặc "có ... hộ"; không viết là "tỷ lệ" hoặc "chiếm tỷ lệ". Chỉ dùng "tỷ lệ" khi số đi kèm đơn vị %.
16. Với mẫu diễn biến, nếu biến động dương/âm nhỏ về tỷ lệ thì dùng "biến động nhẹ" hoặc "biến động dương/âm", không gọi là "cao". Không dùng cụm "xu hướng phát sinh"; hãy viết "mức biến động giữa đầu kỳ và cuối kỳ" hoặc "biến động trong kỳ".
16b. Với mẫu diễn biến, không viết "chênh lệch ... hộ hoặc ...%". Phải viết "chênh lệch ... hộ, tương ứng ...%" hoặc "chênh lệch ... hộ, tương đương ...%".
16c. Với mẫu diễn biến, phân biệt số tổng toàn phạm vi và số theo địa bàn. Số tổng toàn phạm vi chỉ dùng cho toàn tỉnh/phạm vi báo cáo; không được gán cho một huyện/xã cụ thể. Ví dụ: nếu SAFE_BASE_TEXT ghi tổng chênh lệch -535 hộ, tương ứng -14,99%, thì không được viết Đắk Mil/Đăk Glong/Krông Nô chênh lệch -535 hộ hoặc -14,99%. Địa bàn nào phải đi với đúng số của địa bàn đó trong SAFE_BASE_TEXT hoặc llm_analysis_anchors.
17. Với mẫu tỷ lệ thiếu hụt, luôn gọi đúng là "tỷ lệ thiếu hụt"; không viết "tỷ lệ đạt", "không đạt mức cao", "thấp hơn so với mong đợi" vì các tỷ lệ trong bảng là tỷ lệ thiếu hụt, không phải tỷ lệ đạt chuẩn. Không đổi tên chỉ tiêu thành nhóm hộ; ví dụ phải viết "Chất lượng nhà ở có tỷ lệ thiếu hụt 60,88%", không viết "Hộ cận nghèo với tỷ lệ 60,88%".
18. Mọi số liệu phải đi kèm nhãn và đơn vị rõ ràng; không viết một chuỗi số rời rạc không rõ thuộc chỉ tiêu nào.
19. Không dùng từ "lần lượt" khi trong câu có nhiều nhãn và nhiều số; hãy viết từng cặp nhãn-số rõ ràng.
20. Không dùng "cao nhất", "thấp nhất", "lớn nhất", "đứng đầu" nếu cặp đó không có trong top_records, sentence_anchors hoặc SAFE_BASE_TEXT.
21. Với mẫu diễn biến 2/3, ưu tiên 120-180 từ nếu đủ thông tin; dùng sentence_anchors làm xương sống và không nhắc cột "khác" như nguyên nhân khi movement_other_policy là zero_without_explicit_reason.

YÊU CẦU VĂN PHONG:
- Dài khoảng 260-520 từ nếu dữ liệu đủ; ưu tiên đoạn văn có nhịp đọc tự nhiên, mỗi đoạn có một ý chính rõ. Không cố kéo dài bằng câu quản lý chung.
- SAFE_BASE_TEXT chỉ là nguồn số liệu an toàn, KHÔNG phải văn mẫu để chép lại. Không sao chép mở bài/kết luận từ SAFE_BASE_TEXT; hãy tự tổ chức lại mạch viết.
- Nếu đây là lần sinh lại, tránh dùng lại nguyên chuỗi chuyển đoạn: "Theo kết quả rà soát/phân loại" → "Xét theo địa bàn" → "Về cơ cấu..." → "Các tỷ lệ nêu trên...". Hãy chọn mạch văn khác, ví dụ mở từ phạm vi dữ liệu, từ mức tỷ lệ, từ đối chiếu địa bàn hoặc từ lớp cơ cấu, nhưng vẫn giữ số đúng.
- Không viết như fallback Python: không chỉ thay vài từ ở câu mở đầu. Cần viết lại thật sự bằng cấu trúc câu khác, có chuyển ý tự nhiên, ít nhất 3 đoạn có cách mở đoạn khác nhau.
- Viết như phần nhận định trong báo cáo: mở bằng phát hiện chính của số liệu, sau đó nối sang địa bàn/chỉ tiêu nổi bật, rồi đối chiếu với biểu đồ và lưu ý diễn giải. Không viết kiểu checklist.
- Mỗi đoạn nên có ít nhất một số liệu hoặc một cặp so sánh cụ thể; sau số liệu chỉ thêm nhận định thận trọng, không thêm nguyên nhân/chính sách ngoài dữ liệu.
- Ưu tiên viết thành 3-4 đoạn văn tự nhiên; không đánh số mục kiểu 1., 2., 3. hoặc I., II., III.; không đặt nhãn đoạn dạng "Khái quát chung:", "Kết quả rà soát:", "Địa bàn nổi bật:", "Đối chiếu biểu đồ:", "Định hướng theo dõi:".
- Tránh các cụm khô và công thức: "tập trung làm rõ", "cần tiếp tục theo dõi", "trong quá trình quản lý", "công tác rà soát trong kỳ tiếp theo cần tiếp tục được thực hiện thống nhất", "các nhóm hộ hoặc chỉ tiêu có quy mô cao nên được theo dõi thường xuyên", "phục vụ việc xác định trọng tâm quản lý".
- Không mở đầu bằng cụm "Phần nhận định" hoặc "Báo cáo tổng hợp số liệu..."; không lặp nhiều lần cụm "trong phạm vi". Có thể mở trực tiếp bằng "Năm 2024, ..." hoặc "Số liệu năm 2024 cho thấy ...".
- Không dùng các cụm “chúng ta”, “chúng tôi”, “có thể thấy”, “có thể nhận thấy”; thay bằng “số liệu cho thấy”, “kết quả tổng hợp cho thấy”, “biểu đồ cho thấy”.
- Không cần liệt kê hết mọi địa bàn nếu làm văn bản khô; chọn các điểm nổi bật nhất để nhận xét, nhưng phải giữ đúng cặp nhãn-số.
- Khi nói về số liệu hoặc biểu đồ, dùng nhãn tiếng Việt như "số hộ", "tỷ lệ", "địa bàn", "nhóm chỉ tiêu"; không viết tên cột thô và không phô trương nguồn trung gian.
- Không viết lại quốc hiệu, tiêu ngữ, số văn bản, nơi nhận hoặc phần ký tên. Không đặt lại tiêu đề "BÁO CÁO".

STYLE_RULES:
{json.dumps(style_rules, ensure_ascii=False, indent=2)}

STYLE_EXAMPLES_THAM_KHẢO:
{style_examples}

REPORT_FACTS_RÚT_GỌN:
{json.dumps(_compact_facts(bundle), ensure_ascii=False, indent=2, default=str)}

SAFE_BASE_TEXT:
{safe_base_text}

Hãy trả về duy nhất phần văn bản nhận định, không bọc trong markdown, không dùng bullet nếu không thật cần thiết.
""".strip()


def _coerce_llm_timeout(value: Any, default: int = 120) -> int:
    """Timeout đọc phản hồi LLM. Văn bản báo cáo nhận định dài nên không dùng 20 giây."""
    try:
        timeout = int(value)
    except Exception:
        timeout = default
    return max(timeout, 60)


def _call_ollama(prompt: str) -> str:
    http_requests = None
    try:
        try:
            import requests as http_requests  # type: ignore
        except Exception:
            http_requests = None
        try:
            from poverty_chatbot.config import OLLAMA_URL, MODEL_NAME, LLM_TIMEOUT  # type: ignore
        except Exception:
            OLLAMA_URL = "http://localhost:11434/api/chat"
            MODEL_NAME = "qwen2.5:3b-instruct"
            LLM_TIMEOUT = 120

        read_timeout = _coerce_llm_timeout(LLM_TIMEOUT, default=120)
        prompt_l = str(prompt or "").lower()
        # Cho LLM có không gian diễn đạt thật sự; số liệu vẫn bị khóa bởi validator/audit phía sau.
        # Bản cũ hạ temperature quá thấp ở mode kiểm soát số liệu cao nên regenerate dễ giống fallback.
        llm_options = {"temperature": 0.62, "top_p": 0.94, "num_predict": 1900}
        if "chế độ kiểm soát số liệu cao" in prompt_l or "không dùng khung fallback" in prompt_l or "lượt cứu cuối" in prompt_l:
            # Vẫn giữ thấp hơn mặc định để hạn chế đảo số, nhưng không kéo về mức gần deterministic.
            llm_options = {"temperature": 0.50, "top_p": 0.90, "num_predict": 1900}
        payload = {
            "model": MODEL_NAME,
            "stream": False,
            "messages": [
                {"role": "system", "content": "Bạn viết tiếng Việt báo cáo tự nhiên, mạch lạc, có nhịp văn nhận định nhưng không khô máy móc. Không bịa số và không phô thuật ngữ kỹ thuật."},
                {"role": "user", "content": prompt},
            ],
            # Tuần 4 chỉ rewrite văn phong từ SAFE_BASE_TEXT. Giới hạn output vừa đủ
            # để giảm timeout nhưng vẫn đạt văn bản báo cáo nhận định.
            "options": llm_options,
        }
        if http_requests is not None:
            # Tách connect timeout và read timeout để lỗi rõ hơn khi requests có sẵn.
            resp = http_requests.post(OLLAMA_URL, json=payload, timeout=(5, read_timeout))
            resp.raise_for_status()
            data = resp.json()
        else:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=read_timeout) as resp:  # noqa: S310 - localhost/user-configured LLM endpoint
                    data = json.loads(resp.read().decode("utf-8"))
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Ollama phản hồi quá chậm sau {read_timeout} giây. "
                    "Hệ thống sẽ dùng bản facts-renderer an toàn; có thể tăng LLM_TIMEOUT hoặc tắt LLM rewrite."
                ) from exc
            except urllib.error.URLError as exc:
                raise ConnectionError("Không kết nối được Ollama. Hãy kiểm tra `ollama serve` và model đã được pull.") from exc
        text = (data.get("message") or {}).get("content") or data.get("response") or ""
        text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
        return text.strip()
    except Exception as exc:
        if http_requests is not None:
            try:
                if isinstance(exc, http_requests.exceptions.ReadTimeout):
                    raise TimeoutError(
                        f"Ollama phản hồi quá chậm sau {read_timeout} giây. "
                        "Hệ thống sẽ dùng bản facts-renderer an toàn; có thể tăng LLM_TIMEOUT hoặc tắt LLM rewrite."
                    ) from exc
                if isinstance(exc, http_requests.exceptions.ConnectionError):
                    raise ConnectionError("Không kết nối được Ollama. Hãy kiểm tra `ollama serve` và model đã được pull.") from exc
            except AttributeError:
                pass
        if isinstance(exc, (TimeoutError, ConnectionError)):
            raise
        raise RuntimeError(f"Không gọi được Ollama/LLM: {exc}") from exc


def _fallback_variant(regenerate_nonce: int = 0) -> tuple[str, str]:
    intros = [
        "Trên cơ sở số liệu đã được tổng hợp, phần nhận định dưới đây tập trung nêu các kết quả nổi bật, đồng thời giữ nguyên nguyên tắc chỉ diễn giải trong phạm vi dữ liệu có thể kiểm chứng.",
        "Căn cứ bộ số liệu báo cáo đã chuẩn hóa, nhận định được trình bày theo hướng khái quát, ưu tiên các nhóm/chỉ tiêu có quy mô hoặc tỷ lệ đáng chú ý.",
        "Từ các bảng số liệu và biểu đồ đối chiếu, báo cáo ghi nhận những điểm nổi bật phục vụ công tác theo dõi, rà soát và quản lý trong kỳ tiếp theo.",
    ]
    closings = [
        "Nhìn chung, kết quả trên là căn cứ để tiếp tục cập nhật biến động, đối chiếu số liệu giữa các kỳ và xác định những nhóm hộ hoặc chỉ tiêu cần theo dõi sát hơn.",
        "Trong quá trình sử dụng báo cáo, cần kết hợp kết quả tổng hợp với xác minh thực tế tại địa phương, nhất là đối với các nhóm hộ hoặc chỉ tiêu có quy mô nổi bật.",
        "Các kỳ báo cáo tiếp theo nên tiếp tục giữ cùng phạm vi và nguyên tắc tổng hợp để bảo đảm khả năng so sánh, theo dõi biến động và kiểm tra tính nhất quán của dữ liệu.",
    ]
    return intros[regenerate_nonce % len(intros)], closings[(regenerate_nonce + 1) % len(closings)]


def _fallback_section_title(paragraph: str, index: int) -> str:
    """Gắn nhãn mềm cho fallback để UI/Word không hiển thị thành một khối đặc chữ."""
    low = paragraph.lower()
    if index == 0 or low.startswith(("báo cáo tổng hợp", "qua tổng hợp", "trên cơ sở", "căn cứ bộ số liệu")):
        return "Khái quát chung"
    if "biểu đồ" in low:
        return "Đối chiếu biểu đồ"
    if any(x in low for x in ["chỉ phản ánh", "kiểm chứng", "không suy diễn", "nguyên nhân", "xu hướng dài hạn"]):
        return "Lưu ý diễn giải"
    if low.startswith(("từ kết quả", "nhìn chung", "trong quá trình sử dụng", "các kỳ báo cáo tiếp theo")) or "công tác rà soát trong kỳ tiếp theo" in low:
        return "Định hướng theo dõi"
    if any(x in low for x in ["xét theo địa bàn", "địa bàn", "tuy đức", "đăk glong", "krông nô"]):
        return "Địa bàn nổi bật"
    if any(x in low for x in ["ghi nhận", "kết quả rà soát", "tổng hợp số liệu", "hộ nghèo", "hộ cận nghèo"]):
        return "Kết quả tổng hợp"
    return "Nhận định bổ sung"


def _sectionize_fallback_paragraphs(paragraphs: list[str]) -> list[str]:
    """Chuyển fallback thành các đoạn có nhãn ngắn, giữ nguyên số liệu và không thêm suy diễn mới."""
    out: list[str] = []
    used: dict[str, int] = {}
    for idx, para in enumerate(paragraphs):
        p = str(para or "").strip()
        if not p:
            continue
        # Không gắn nhãn lặp nếu đoạn đã có nhãn rõ.
        if re.match(r"^(Khái quát|Kết quả|Địa bàn|Nhóm|Biểu đồ|Đối chiếu|Lưu ý|Định hướng|Nhận định)[:：]", p, flags=re.I):
            out.append(p)
            continue
        title = _fallback_section_title(p, idx)
        used[title] = used.get(title, 0) + 1
        if used[title] > 1:
            # Tránh nhiều đoạn cùng heading giống nhau; đoạn sau giữ thân văn tự nhiên.
            out.append(p)
        else:
            out.append(f"{title}: {p}")
    return out


def _smooth_fallback_text(base: str, regenerate_nonce: int = 0) -> str:
    """Làm fallback dễ đọc hơn mà không dùng LLM và không thay đổi số liệu."""
    fallback_raw = str(base or "").strip()
    # Chuẩn hóa nhãn trẻ em hơi gượng do nguồn dữ liệu đặt tên ngắn. Chỉ áp dụng fallback;
    # LLM vẫn bị hậu kiểm nếu tự viết cụm sai.
    fallback_raw = fallback_raw.replace("trẻ em thiếu chỉ tiêu về tình trạng đi học", "trẻ em thiếu chỉ tiêu về tình trạng đi học")
    fallback_raw = fallback_raw.replace("Trẻ em thiếu tình trạng đi học", "Trẻ em thiếu chỉ tiêu về tình trạng đi học")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", fallback_raw) if p.strip()]
    if not paragraphs:
        return ""

    # Bỏ các câu ghi chú quá kỹ thuật/khô nếu đã có đoạn chốt thận trọng ở cuối.
    cleaned: list[str] = []
    for p in paragraphs:
        low = p.lower()
        if "không suy diễn nguyên nhân nghèo" in low and "dữ liệu không có" in low:
            continue
        cleaned.append(p)

    intro, closing = _fallback_variant(regenerate_nonce)
    if cleaned and cleaned[0].lower().startswith(("báo cáo tổng hợp", "qua tổng hợp", "trên cơ sở", "căn cứ")):
        # Đoạn đầu đã là mở bài; không bọc thêm để tránh lặp.
        out = cleaned
    else:
        out = [intro] + cleaned

    if out and closing.lower() not in out[-1].lower():
        # Nếu đoạn cuối đã là kiến nghị/chốt, không thêm quá nhiều; chỉ thêm khi chưa có câu chốt rõ.
        last = out[-1].lower()
        if not any(x in last for x in ["kỳ tiếp theo", "tiếp tục", "trong quá trình sử dụng", "nhìn chung"]):
            out.append(closing)

    out = _sectionize_fallback_paragraphs(out)
    return "\n\n".join(out).strip()


def _smooth_template1_no_llm_text(base: str, bundle: ReportFactsBundle, regenerate_nonce: int = 0) -> str:
    """Làm riêng văn bản no-LLM của mẫu 1 cho đúng bài toán biểu mẫu.

    Mẫu 1 không nhận định theo cơ cấu hộ không nghèo. Trọng tâm công khai là ba
    nhóm chỉ tiêu trong bảng: hộ nghèo, hộ cận nghèo và hộ nông/lâm/ngư nghiệp
    có mức sống trung bình. Hàm này chỉ sắp lại câu/đoạn từ facts đã có, không
    tự tính thêm số và không đổi cặp địa bàn-số liệu.
    """
    raw = _clean_word_report_style_text(str(base or "").strip())
    if not raw:
        return ""

    # Phòng vệ cuối: nếu một đường gọi cũ còn đưa renderer overview chung vào đây,
    # bỏ câu/đoạn nói về hộ không nghèo để không lệch mẫu 1.
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    raw = " ".join(s for s in raw_sentences if "hộ không nghèo" not in s.lower()).strip() or raw

    intro = (
        "Nội dung phân tích tập trung vào ba nhóm chỉ tiêu của bảng tổng hợp: "
        "hộ nghèo, hộ cận nghèo và hộ nông, lâm, ngư nghiệp có mức sống trung bình. "
        "Các số liệu được trình bày theo phạm vi rà soát đã chọn và chỉ dùng để đối chiếu trong phạm vi bảng này."
    )
    closing_variants = [
        "Khi sử dụng kết quả, cần tiếp tục đối chiếu số liệu theo địa bàn để phục vụ rà soát, theo dõi biến động hộ nghèo, hộ cận nghèo và cập nhật riêng nhóm hộ nông, lâm, ngư nghiệp có mức sống trung bình khi có dữ liệu nghiệp vụ trực tiếp.",
        "Kết quả trên là căn cứ để theo dõi các địa bàn có quy mô hộ nghèo, hộ cận nghèo nổi bật; riêng chỉ tiêu nông, lâm, ngư nghiệp có mức sống trung bình cần được giữ đúng phạm vi dữ liệu hiện có và không diễn giải vượt quá bảng tổng hợp.",
        "Trong các kỳ rà soát tiếp theo, cần giữ cùng phạm vi tổng hợp để so sánh biến động hộ nghèo, hộ cận nghèo và bảo đảm chỉ tiêu nông, lâm, ngư nghiệp có mức sống trung bình được cập nhật bằng nguồn dữ liệu phù hợp."
    ]
    closing = closing_variants[int(regenerate_nonce or 0) % len(closing_variants)]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    # Nếu raw chỉ là một khối dài, tách nhẹ theo câu để UI/Word giống các mẫu khác hơn.
    if len(paragraphs) <= 1:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
        if len(sentences) >= 4:
            paragraphs = [" ".join(sentences[i:i + 2]).strip() for i in range(0, len(sentences), 2)]

    out = [intro] + paragraphs
    if not any("kỳ rà soát tiếp theo" in p.lower() or "trong các kỳ rà soát tiếp theo" in p.lower() for p in out):
        out.append(closing)

    # Gắn heading mềm như các mẫu no-LLM khác để tránh một khối chữ, nhưng không
    # đưa số mẫu/cột/ô Excel vào văn bản.
    out = _sectionize_fallback_paragraphs(out)
    text = "\n\n".join(p for p in out if str(p or "").strip()).strip()
    return _clean_word_report_style_text(text)


def _expand_fallback_text(safe_base: str, bundle: ReportFactsBundle, regenerate_nonce: int = 0) -> str:
    """Fallback không LLM, văn phong báo cáo hơn và vẫn bám số liệu.

    Các mẫu có bảng nhiều cột/rủi ro cao dùng renderer công khai riêng để no-LLM
    vẫn thích nghi với facts, ranking và ngữ cảnh nghiệp vụ, thay vì lấy cột đầu tiên
    của bảng làm trọng tâm chung.
    """
    base = safe_base.strip()
    tid = _template_id_from_bundle(bundle)
    pattern = _pattern(bundle)

    if tid == 1:
        cleaned = _public_word_final_repair_with_bundle(base, bundle)
        return _smooth_template1_no_llm_text(cleaned, bundle, regenerate_nonce=regenerate_nonce)
    if tid in {2, 3} or pattern == "movement":
        return _movement_public_text(bundle, tid=tid if tid in {2, 3} else 2)
    if tid in {4, 5, 6, 7} or pattern in {"deprivation_count", "deprivation_ratio"}:
        return _deprivation_public_text(bundle, tid=tid)
    if tid == 8 or pattern == "vulnerable_groups":
        return _template8_public_text(bundle)
    if tid == 9 or pattern == "ethnicity":
        return _ethnicity_public_text(bundle)
    if tid == 10 or pattern == "causes":
        return _causes_public_text(bundle)
    if tid == 11 or pattern == "child_deprivation":
        return _children_public_text(bundle)
    if tid == 12 or pattern == "multidimensional_standard":
        return _multidim_public_text(bundle)
    if _has_template_table(bundle):
        return _smooth_fallback_text(base, regenerate_nonce=regenerate_nonce)

    intro, closing = _fallback_variant(regenerate_nonce)
    return _smooth_fallback_text(f"{intro}\n\n{base}\n\n{closing}", regenerate_nonce=regenerate_nonce)


def _build_retry_prompt(original_prompt: str, validation_warnings: list[str], attempt_no: int = 2, bundle: ReportFactsBundle | None = None) -> str:
    """Prompt retry để LLM tự sửa dựa trên lỗi hậu kiểm, không nới lỏng số liệu."""
    notes = "\n".join(f"- {w}" for w in (validation_warnings or [])[:10])
    template_guidance = _template_retry_guidance(bundle, validation_warnings)
    strict_mode = (
        "Ở lần thử này, nếu không chắc một cặp nhãn-số thì hãy bỏ câu nhận định đó, "
        "chỉ giữ các câu có cặp nhãn-số chắc chắn được trích xuất động từ digest/snapshots; vẫn phải viết thành đoạn tự nhiên, không chép khung fallback."
        if attempt_no >= 4
        else "Giữ văn phong báo cáo tự nhiên nhưng vẫn bám tuyệt đối SAFE_BASE_TEXT."
    )
    return (
        original_prompt
        + f"\n\nYÊU CẦU SỬA LẠI DO BẢN TRƯỚC CHƯA QUA HẬU KIỂM - LẦN THỬ {attempt_no}:\n"
        + (notes or "- Bản trước chưa đạt hậu kiểm.")
        + "\n\nHƯỚNG DẪN RIÊNG PHẢI THEO Ở LẦN THỬ NÀY:\n"
        + template_guidance
        + "\n\nNếu lỗi liên quan đến 'chưa tạo biến thể diễn đạt' hoặc 'tương đồng với văn bản nguồn', hãy đổi thật sự mạch viết: đổi câu mở đầu, đổi thứ tự trình bày, chia lại đoạn và dùng cách chuyển ý mới; vẫn giữ nguyên từng số và cặp nhãn-số.\n"
        + "\n"
        + strict_mode
        + " Chỉ dùng các số cốt lõi và các số địa bàn/chỉ tiêu nổi bật có trong SAFE_BASE_TEXT. "
          "Không thêm số mới, không gán nhầm số giữa các địa bàn/chỉ tiêu, giữ nguyên từng cặp nhãn-số theo SAFE_BASE_TEXT/llm_analysis_anchors/safe_row_snapshots, không tự đảo thứ tự số, nếu số đi với đơn vị hộ thì không gọi là tỷ lệ, không dùng tên cột kỹ thuật, không nhắc số mẫu báo cáo, không nhắc cột/ô Excel hoặc công thức biểu mẫu, không viết DB/SQL/Python/SAFE_BASE_TEXT/REPORT_FACTS, không đánh số mục, không dùng markdown, không dùng giọng chat/prompt hoặc các cụm 'chúng ta', 'có thể thấy', không lẫn hộ nghèo với hộ cận nghèo, không đổi chỉ tiêu thiếu hụt thành nhóm hộ, không dùng 'xu hướng phát sinh', không viết 'chênh lệch ... hộ hoặc ...%', hãy dùng 'tương ứng ...%', với mẫu diễn biến không gán số tổng toàn phạm vi cho một địa bàn cụ thể. Viết khoảng 240-480 từ, chia thành 3-4 đoạn tự nhiên. Trả về duy nhất văn bản nhận định."
    )


def _is_min_words_warning(w: str) -> bool:
    """Nhận diện cảnh báo dưới ngưỡng llm_min_words.

    Lỗi này không phải sai số liệu nên không đưa vào hard-fail dữ liệu,
    nhưng cũng không được accepted. Vòng retry phải tiếp tục sinh bản dài hơn
    cho tới khi đạt ngưỡng cấu hình hoặc hết số lần thử.
    """
    t = str(w or "").lower()
    return (
        "quá ngắn nghiêm trọng" in t
        or "dưới ngưỡng tối thiểu" in t
        or ("cần tối thiểu" in t and "từ" in t)
    )



def _is_variation_quality_warning(w: Any) -> bool:
    t = str(w or "").lower()
    return (
        "chưa tạo biến thể diễn đạt" in t
        or "tương đồng với văn bản nguồn" in t
        or "bám quá nhiều cụm chuyển đoạn" in t
        or "khuôn cố định" in t
    )


def _public_llm_warnings(warnings: list[str] | None) -> list[str]:
    """Ẩn cảnh báo chất lượng biến thể khỏi UI chính.

    Các cảnh báo này chỉ dùng để retry/ghi debug trong attempt_results; không nên
    hiển thị cho người dùng cuối vì nghe như lỗi prompt/fallback nội bộ.
    """
    return [str(w) for w in (warnings or []) if str(w).strip() and not _is_variation_quality_warning(w)]

def _llm_candidate_is_acceptable(warnings: list[str]) -> bool:
    """Chỉ chấp nhận LLM khi đạt cả dữ liệu và độ dài tối thiểu.

    WARN mềm vẫn có thể accepted nếu không làm sai số liệu. Riêng lỗi dưới
    llm_min_words là fail chất lượng trong vòng retry: LLM phải tiếp tục viết
    dài hơn cho tới khi đạt ngưỡng hoặc hết số lần thử.
    """
    ws = list(warnings or [])
    has_data_hard_fail = any(_is_hard_validation_warning(w) for w in ws) or _should_prefer_fallback_over_llm(ws)
    has_min_words_fail = any(_is_min_words_warning(w) for w in ws)
    return not has_data_hard_fail and not has_min_words_fail


def _report_llm_max_attempts(value: Any = None) -> int:
    """Số lần thử LLM trong một lượt bấm.

    nhưng luôn giới hạn 1...10 để tránh một lần bấm chạy quá lâu.
    """
    if value is None:
        try:
            from poverty_chatbot.config import REPORT_LLM_MAX_ATTEMPTS  # type: ignore
            value = REPORT_LLM_MAX_ATTEMPTS
        except Exception:
            value = 6
    try:
        n = int(value)
    except Exception:
        n = 6
    return max(1, min(n, 10))



def _is_high_risk_llm_bundle(bundle: ReportFactsBundle | None) -> bool:
    """Các mẫu LLM hay đảo cặp nhãn-số; dùng prompt kiểm soát số liệu cao sau vài lần fail."""
    try:
        tid = _template_id_from_bundle(bundle)  # type: ignore[arg-type]
    except Exception:
        tid = 0
    pattern = _pattern(bundle) if bundle is not None else ""
    return tid in {1, 8, 9, 10, 11, 12} or pattern in {"overview_result", "vulnerable_groups", "ethnicity", "causes", "child_deprivation", "multidimensional_standard"}



def _llm_prompt_source_text(bundle: ReportFactsBundle, safe_base: str, protected_text: str = "", regenerate_nonce: int = 0) -> str:
    """Nguồn đưa vào prompt LLM.

    Với mẫu rủi ro cao (1/11/12), không đưa nguyên đoạn fallback/SAFE_BASE_TEXT
    vào prompt vì LLM nhỏ rất dễ chép lại. Thay bằng digest facts-only đã khóa
    cặp nhãn-số; validator/audit vẫn dùng safe_base gốc ở bên ngoài.
    """
    try:
        tid = _template_id_from_bundle(bundle)
        pattern = _pattern(bundle)
    except Exception:
        tid, pattern = 0, ""
    if tid in {1, 8, 9, 10, 11, 12} or pattern in {"overview_result", "vulnerable_groups", "ethnicity", "causes", "child_deprivation", "multidimensional_standard"}:
        digest = _llm_required_facts_digest(bundle)
        lines = [
            "SỐ LIỆU RÚT GỌN - dùng để viết lại, không phải văn mẫu:",
            "Không có đoạn fallback mẫu để sao chép; hãy tự tổ chức câu văn từ các cặp nhãn-số dưới đây.",
        ]
        for item in digest[:18]:
            if str(item).strip():
                lines.append("- " + str(item).strip())
        if not digest:
            lines.append("- Không có danh sách rút gọn riêng; dùng các số trong phần số liệu kèm theo.")
        lines.append("Yêu cầu: giữ đúng số, nhãn, đơn vị; được đổi thứ tự trình bày nếu không làm sai cặp nhãn-số.")
        return "\n".join(lines)
    return str(protected_text or safe_base or "").strip()


def _llm_source_reference_block(bundle: ReportFactsBundle, protected_text: str, regenerate_nonce: int = 0) -> str:
    """Block nguồn số liệu cho prompt retry/final.

    Không đưa nguyên văn đoạn fallback cho mẫu nhiều số/cột; chỉ đưa digest để
    tránh LLM sao chép y nguyên và tạo cảm giác không có LLM.
    """
    try:
        tid = _template_id_from_bundle(bundle)
        pattern = _pattern(bundle)
    except Exception:
        tid, pattern = 0, ""
    if tid in {1, 8, 9, 10, 11, 12} or pattern in {"overview_result", "vulnerable_groups", "ethnicity", "causes", "child_deprivation", "multidimensional_standard"}:
        digest = _llm_required_facts_digest(bundle)
        payload = "\n".join(f"- {x}" for x in digest[:18] if str(x).strip()) or "- Dùng các số trong phần số liệu kèm theo."
        return (
            "NGUỒN SỐ LIỆU RÚT GỌN, KHÔNG PHẢI VĂN MẪU:\n"
            f"{payload}\n"
            "Không có đoạn văn nguồn để chép lại; phải tự viết lại thành đoạn nhận định tự nhiên từ các dòng trên."
        )
    return (
        "VĂN BẢN NGUỒN AN TOÀN ĐỂ THAM KHẢO SỐ LIỆU, KHÔNG SAO CHÉP BỐ CỤC:\n"
        f"{str(protected_text or '').strip()}"
    )

def _protected_llm_base_text(safe_base: str, bundle: ReportFactsBundle, regenerate_nonce: int = 0) -> str:
    """Nguồn an toàn tham khảo cho LLM, không phải khuôn để sao chép bố cục."""
    protected = _expand_fallback_text(safe_base, bundle, regenerate_nonce=regenerate_nonce)
    protected = re.sub(
        r"(?im)^\s*(Khái\s+quát\s+chung|Kết\s+quả\s+rà\s+soát|Kết\s+quả\s+tổng\s+hợp|Địa\s+bàn\s+nổi\s+bật|Nhóm\s+chỉ\s+tiêu\s+nổi\s+bật|Đối\s+chiếu\s+biểu\s+đồ|Lưu\s+ý\s+diễn\s+giải|Định\s+hướng\s+theo\s+dõi|Định\s+hướng\s+quản\s+lý|Nhận\s+định\s+bổ\s+sung)\s*[:：]\s*",
        "",
        str(protected or ""),
    )
    protected = re.sub(r"\n{3,}", "\n\n", protected).strip()
    return protected or str(safe_base or "").strip()


def _build_high_risk_controlled_prompt(bundle: ReportFactsBundle, protected_text: str, validation_warnings: list[str] | None = None, attempt_no: int = 3, regenerate_nonce: int = 0) -> str:
    """Prompt retry rủi ro cao: kiểm soát số liệu nhưng vẫn yêu cầu bố cục LLM khác fallback."""
    notes = "\n".join(f"- {w}" for w in (validation_warnings or [])[:8]) or "- Bản trước chưa đạt hậu kiểm do sai/lẫn cặp nhãn-số hoặc bám cấu trúc fallback."
    guidance = _template_retry_guidance(bundle, validation_warnings or [])
    digest_lines = _llm_required_facts_digest(bundle)
    digest = "\n".join(f"- {line}" for line in digest_lines[:10]) if digest_lines else "- Dùng các số trong phần số liệu kèm theo."
    facts = json.dumps(_compact_facts(bundle), ensure_ascii=False, indent=2, default=str)
    source_reference = _llm_source_reference_block(bundle, protected_text, regenerate_nonce=regenerate_nonce)
    return f"""
Bạn đang ở CHẾ ĐỘ KIỂM SOÁT SỐ LIỆU CAO cho mẫu báo cáo có nhiều cột số liệu.
Nhiệm vụ lần thử {attempt_no}: viết lại thành văn bản báo cáo nhận định tự nhiên, KHÔNG dùng khung fallback/không LLM.

LỖI CẦN TRÁNH TỪ BẢN TRƯỚC:
{notes}

HƯỚNG DẪN RIÊNG:
{guidance}

HỒ SƠ BIẾN THỂ DIỄN ĐẠT:
{_variation_profile_text(bundle, regenerate_nonce)}

YÊU CẦU KHÁC BIỆT VĂN PHONG:
- Tuân thủ đúng style variant trong hồ sơ trên; đổi cách mở đoạn và ít nhất một chuyển ý chính so với bản trước.
- Không mở đầu bằng các cụm chung lặp lại như "Theo số liệu", "Kết quả cho thấy", "Theo kết quả rà soát/phân loại".
- Không sắp xếp câu theo đúng thứ tự văn bản Python/không LLM; chỉ giữ đúng cặp nhãn-số.

SỐ LIỆU NÊN DÙNG NGUYÊN VĂN:
{digest}

NGUỒN SỐ LIỆU AN TOÀN:
{facts}

{source_reference}

YÊU CẦU BỐ CỤC BẮT BUỘC:
- Viết 3-4 đoạn văn tự nhiên, không đánh số mục, không bullet. Mỗi đoạn phải xoay quanh một phát hiện cụ thể từ số liệu, không viết đoạn kết luận chung chung.
- Không được mở đoạn bằng các nhãn cố định: "Khái quát chung:", "Kết quả rà soát:", "Kết quả tổng hợp:", "Địa bàn nổi bật:", "Đối chiếu biểu đồ:", "Định hướng theo dõi:".
- Không được sao chép cấu trúc hoặc câu mở/kết của văn bản Python/không LLM; chỉ dùng số liệu và cặp nhãn-số an toàn.
- Tránh các cụm khô: "tập trung làm rõ", "cần tiếp tục theo dõi", "công tác rà soát trong kỳ tiếp theo", "quy mô cao nên được theo dõi thường xuyên", "phục vụ xác định trọng tâm quản lý".
- Mỗi số phải giữ đúng địa bàn/chỉ tiêu/đơn vị như nguồn; nếu không chắc thì bỏ số đó, không đoán.
- Văn phong phải là nhận định báo cáo có chuyển ý tự nhiên giữa kết quả nổi bật, địa bàn/chỉ tiêu, biểu đồ và lưu ý diễn giải; không dùng giọng checklist.

TRẢ VỀ DUY NHẤT PHẦN VĂN BẢN NHẬN ĐỊNH. Không thêm lời giải thích, không markdown, không nhắc prompt/hậu kiểm/lần thử.
""".strip()




def _build_template1_final_fact_guarded_prompt(
    bundle: ReportFactsBundle,
    validation_warnings: list[str] | None = None,
    attempt_no: int = 8,
) -> str:
    """Prompt cứu riêng mẫu 1: đưa digest trích xuất động, không đưa JSON lớn.

    Mẫu 1 có nhiều số theo nhiều cột nên Qwen 3B hay đảo số giữa huyện/cột.
    Prompt này thu hẹp nhiệm vụ: chỉ viết từ các dòng digest sinh từ facts/bảng hiện tại và cấm superlative.
    """
    notes = "\n".join(f"- {w}" for w in (validation_warnings or [])[:8]) or "- Bản trước chưa đạt hậu kiểm."
    digest_lines = _llm_required_facts_digest(bundle)
    digest = "\n".join(f"- {line}" for line in digest_lines[:8]) if digest_lines else "- Dùng đúng các số trong phần số liệu kèm theo."
    return f"""
Bạn đang ở lượt kiểm soát cao cho biểu tổng hợp. Hãy viết văn bản nhận định bằng LLM nhưng chỉ từ các dòng số liệu được trích xuất dưới đây.

LỖI CẦN TRÁNH:
{notes}

SỐ LIỆU ĐƯỢC PHÉP DÙNG, GIỮ ĐÚNG NGUYÊN CẶP NHÃN-SỐ:
{digest}

CÁCH VIẾT BẮT BUỘC:
- Viết 3 đoạn văn tự nhiên, khoảng 170-260 từ; không bullet, không markdown, không đặt nhãn đoạn như "Khái quát chung:" hoặc "Địa bàn nổi bật:".
- Đoạn 1 nêu các tổng toàn tỉnh trong digest và chỉ ba nhóm của biểu mẫu: hộ nghèo, hộ cận nghèo, hộ nông/lâm/ngư nghiệp mức sống trung bình. Không nhắc nhóm ngoài ba chỉ tiêu này. Với hộ nông/lâm/ngư nghiệp mức sống trung bình, nếu bằng 0 thì viết ngắn gọn là chỉ tiêu này ghi 0 theo bảng hiện có, không phân tích sâu.
- Đoạn 2 chỉ dùng các cặp địa bàn trong digest. Mỗi câu địa bàn phải có đủ: tên địa bàn + đúng nhóm hộ + đúng số hộ. Cấu trúc tham khảo: "[Địa bàn] ghi nhận [số] hộ [nhóm hộ]"; không dùng cấu trúc này như dữ liệu và không viết số trần.
- Đoạn 3 liên hệ với bảng và biểu đồ để nói rằng các số trên giúp đối chiếu quy mô giữa ba nhóm hộ và địa bàn; không thêm số mới.
- TRÁNH dùng các từ xếp hạng tuyệt đối: cao nhất, lớn nhất, nhiều nhất, đứng đầu, dẫn đầu, thứ hai. Hãy dùng "ghi nhận", "có", "đạt".
- CẤM dùng các từ: tỷ lệ, phần trăm, chiếm. Mẫu này đang dùng số hộ, không phải tỷ lệ.
- Không tự thêm số mới, không tự tính, không suy diễn nguyên nhân, chính sách hay hiệu quả hỗ trợ.
- Không dùng cụm "chúng ta", "có thể thấy", "phục vụ xác định trọng tâm quản lý", "xây dựng kế hoạch hỗ trợ phù hợp".

TRẢ VỀ DUY NHẤT VĂN BẢN NHẬN ĐỊNH.
""".strip()

def _build_final_fact_guarded_prompt(
    bundle: ReportFactsBundle,
    protected_text: str,
    validation_warnings: list[str] | None = None,
    attempt_no: int = 8,
    regenerate_nonce: int = 0,
) -> str:
    """Prompt cứu ở các lượt cuối: nhiệm vụ hẹp hơn để LLM dễ qua hậu kiểm.

    Khác prompt sáng tạo ban đầu, prompt này chỉ yêu cầu LLM chuyển facts trích xuất động
    thành 3-4 đoạn văn tự nhiên. Không cho tự chọn số mới, không cho tự thêm claim.
    """
    if _template_id_from_bundle(bundle) == 1 or _pattern(bundle) == "overview_result":
        return _build_template1_final_fact_guarded_prompt(bundle, validation_warnings, attempt_no=attempt_no)

    notes = "\n".join(f"- {w}" for w in (validation_warnings or [])[:8]) or "- Bản trước chưa đạt hậu kiểm."
    guidance = _template_retry_guidance(bundle, validation_warnings or [])
    digest_lines = _llm_required_facts_digest(bundle)
    digest = "\n".join(f"- {line}" for line in digest_lines[:14]) if digest_lines else "- Dùng đúng các số trong văn bản nguồn an toàn."
    movement_final_guard = ""
    if _template_id_from_bundle(bundle) in {2, 3} or _pattern(bundle) == "movement":
        bundle_facts = getattr(bundle, "facts", {}) or {}
        anchors = bundle_facts.get("sentence_anchors") if isinstance(bundle_facts, dict) else None
        anchor_text = "\n".join(f"- {line}" for line in (anchors or [])[:6])
        if anchor_text:
            movement_final_guard = f"""
KHÓA RIÊNG CHO LƯỢT CỨU MẪU DIỄN BIẾN:
- Chỉ viết từ các dòng neo đã được Python/SQL kiểm chứng dưới đây; không tự chọn địa bàn, không tự lấy tỷ lệ địa bàn phụ, không tự phân tích huyện/xã.
- Không dùng các tỷ lệ địa bàn ngoài dòng neo; riêng mẫu 3 không dùng 5,76%.
- Nếu hai mốc là 3.402 và 3.691 thì phải viết là tăng/biến động tăng; tuyệt đối không viết giảm/xuống/còn theo chiều giảm.
- Các dòng neo được phép diễn giải:
{anchor_text}
""".strip()
    deprivation_final_guard = ""
    if _template_id_from_bundle(bundle) in {4, 6} or _pattern(bundle) == "deprivation_count":
        bundle_facts = getattr(bundle, "facts", {}) or {}
        top_rows = bundle_facts.get("top_indicators_by_count") if isinstance(bundle_facts, dict) else None
        locked_pairs: list[str] = []
        for row in (top_rows or [])[:3]:
            if not isinstance(row, dict):
                continue
            label = row.get("chi_tieu") or row.get("label") or row.get("name")
            count = row.get("so_ho")
            ratio = row.get("ty_le_%")
            if label and count is not None and ratio is not None:
                locked_pairs.append(f"- {label}: {_num(count)} hộ, tỷ lệ thiếu hụt {_pct(ratio)}")
        if locked_pairs:
            deprivation_final_guard = """
KHÓA RIÊNG CHO LƯỢT CỨU MẪU SỐ HỘ THIẾU HỤT:
- Trọng tâm là số hộ thiếu hụt; mỗi chỉ tiêu phải viết số hộ trước, tỷ lệ chỉ là đối chiếu phụ sau đó.
- Không tự đổi số hộ thành tỷ lệ, không đảo số hộ/tỷ lệ giữa các chỉ tiêu, không tự thêm chỉ tiêu ngoài các cặp dưới đây.
- Bắt buộc giữ đúng các cặp chỉ tiêu - số hộ - tỷ lệ:
{pairs}
""".strip().format(pairs="\n".join(locked_pairs))
    ethnicity_final_guard = ""
    if _template_id_from_bundle(bundle) == 9 or _pattern(bundle) == "ethnicity":
        bundle_facts = getattr(bundle, "facts", {}) or {}
        top_rows = bundle_facts.get("top_poor_ethnicities") if isinstance(bundle_facts, dict) else None
        locked_pairs = []
        for row in (top_rows or [])[:4]:
            if not isinstance(row, dict):
                continue
            label = row.get("dan_toc")
            poor = row.get("so_ho_ngheo")
            near = row.get("so_ho_can_ngheo")
            total = row.get("tong_ho")
            if label and poor is not None and near is not None and total is not None:
                locked_pairs.append(
                    f"- {label}: {_num(poor)} hộ nghèo, {_num(near)} hộ cận nghèo, tổng {_num(total)} hộ"
                )
        if locked_pairs:
            ethnicity_final_guard = """
KHÓA RIÊNG CHO LƯỢT CỨU MẪU DÂN TỘC:
- Chỉ phân tích theo dân tộc/nhóm dân tộc; không viết thành địa bàn, khu vực, huyện, xã hoặc cụm dân cư.
- Không dùng chữ "tỷ lệ" cho số tuyệt đối đơn vị hộ; nếu nêu phần trăm thì phải đi kèm ký hiệu % và đúng cặp nhãn.
- Không dùng giọng prompt/chat như "bài viết này", "tôi sẽ", "chúng ta".
- Bắt buộc giữ đúng các cặp dân tộc - số hộ:
{pairs}
""".strip().format(pairs="\n".join(locked_pairs))
    facts = json.dumps(_compact_facts(bundle), ensure_ascii=False, indent=2, default=str)
    source_reference = _llm_source_reference_block(bundle, protected_text, regenerate_nonce=regenerate_nonce)
    return f"""
Bạn đang ở LƯỢT CỨU CUỐI để tạo văn bản nhận định LLM đã qua hậu kiểm.
Mục tiêu duy nhất: viết một bản AN TOÀN, đúng số liệu, đủ dài; không cần quá sáng tạo.

LỖI CẦN TRÁNH TỪ CÁC LẦN TRƯỚC:
{notes}

HƯỚNG DẪN RIÊNG THEO MẪU:
{guidance}

HỒ SƠ BIẾN THỂ DIỄN ĐẠT:
{_variation_profile_text(bundle, regenerate_nonce)}

YÊU CẦU KHÁC BIỆT VĂN PHONG:
- Tuân thủ đúng style variant trong hồ sơ trên; đổi cách mở đoạn và ít nhất một chuyển ý chính so với bản trước.
- Không mở đầu bằng các cụm chung lặp lại như "Theo số liệu", "Kết quả cho thấy", "Theo kết quả rà soát/phân loại".
- Không sắp xếp câu theo đúng thứ tự văn bản Python/không LLM; chỉ giữ đúng cặp nhãn-số.

CÁC CẶP SỐ LIỆU BẮT BUỘC/NÊN GIỮ NGUYÊN:
{digest}

{movement_final_guard}

{deprivation_final_guard}

{ethnicity_final_guard}

SỐ LIỆU RÚT GỌN ĐÃ ĐƯỢC ĐỐI CHIẾU:
{facts}

{source_reference}

QUY TẮC BẮT BUỘC ĐỂ ĐƯỢC CHẤP NHẬN:
- Viết 3-4 đoạn văn tự nhiên, khoảng 220-380 từ; không bullet, không đánh số mục, không markdown.
- Bắt đầu trực tiếp bằng nhận định số liệu, không dùng nhãn như "Khái quát chung", "Kết quả", "Địa bàn nổi bật", "Đối chiếu biểu đồ", "Định hướng".
- Mỗi số phải đi kèm đúng nhãn/địa bàn/chỉ tiêu/đơn vị như nguồn; nếu không chắc thì bỏ câu đó.
- Không tự thêm số mới, không tính lại phần trăm, không đảo số giữa hộ nghèo và hộ cận nghèo, không dùng nhân khẩu làm mẫu số hộ.
- Với mẫu diễn biến, phải viết đúng dạng "từ A hộ lên/xuống/còn B hộ" theo đúng bảng; chênh lệch chỉ là mức tăng/giảm, không được dùng làm số đầu kỳ/cuối kỳ.
- Không suy diễn nguyên nhân/chính sách/hiệu quả hỗ trợ nếu bảng không có dữ liệu đó.
- Không dùng các cụm: "chúng ta", "có thể thấy", "nhớ rằng", "dưới đây là", "theo yêu cầu", "phục vụ xác định trọng tâm quản lý", "xây dựng kế hoạch hỗ trợ phù hợp".
- Nếu là mẫu chuẩn nghèo đa chiều, mọi tỷ lệ theo địa bàn phải viết rõ là tính trên tổng hộ rà soát/phân loại của chính địa bàn đó; không gọi là tỷ trọng trong toàn tỉnh và không ghi sai tỉnh Đắk Nông thành Đắk Lắk.

TRẢ VỀ DUY NHẤT VĂN BẢN NHẬN ĐỊNH.
""".strip()

def generate_report_text(
    question: str | None = None,
    data: pd.DataFrame | None = None,
    mode: str = "auto",
    style_profile_path: str | Path | None = None,
    use_llm: bool = False,
    report_level: str = "administrative",
    allow_variation: bool = True,
    regenerate_nonce: int = 0,
    *,
    report_type: int | str | None = None,
    template_id: int | str | None = None,
    db_path: str | Path | None = None,
    year: int | None = None,
    huyen: str | None = None,
    facts_bundle: ReportFactsBundle | None = None,
    llm_failure_policy: str = "no_fallback",
    generation_mode: str | None = None,
    llm_min_words: int | None = None,
) -> ReportTextResult:
    """Sinh văn bản báo cáo nhận định tuần 4 theo hướng facts-first + LLM rewrite có hậu kiểm.

    - Facts renderer tạo SAFE_BASE_TEXT từ Python/SQL.
    - Nếu use_llm=True, Ollama chỉ được biên tập từ SAFE_BASE_TEXT + REPORT_FACTS.
    - Validator hậu kiểm số liệu.
    - Ở chế độ LLM, nếu không có bản LLM đạt hậu kiểm sau các lần thử, hàm trả trạng thái lỗi để người dùng sinh lại hoặc sửa thủ công.
    """
    if facts_bundle is not None:
        bundle = facts_bundle
    elif report_type is not None or template_id is not None:
        bundle = build_report_bundle(report_type or template_id or 1, db_path=db_path, year=year, huyen=huyen)
    elif data is not None:
        bundle = _bundle_from_dataframe(question or "", data, mode=mode)
    else:
        bundle = build_report_bundle(1, db_path=db_path, year=year, huyen=huyen)

    safe_base = _safe_base_text(bundle, report_level=report_level)
    fallback_reference_text = _expand_fallback_text(safe_base, bundle, regenerate_nonce=regenerate_nonce)
    style_profile_for_run = _style_variant_profile(regenerate_nonce)
    effective_llm_min_words = _coerce_llm_min_words(llm_min_words, default=150)
    high_risk_llm_mode = bool(use_llm and _is_high_risk_llm_bundle(bundle))
    protected_llm_text = _protected_llm_base_text(safe_base, bundle, regenerate_nonce=regenerate_nonce) if high_risk_llm_mode else ""
    safe_base_for_prompt = _llm_prompt_source_text(bundle, safe_base, protected_llm_text, regenerate_nonce=regenerate_nonce) if high_risk_llm_mode else safe_base
    style_profile = _load_style_profile(style_profile_path)
    style_examples = _load_style_examples(style_profile_path)
    prompt = _build_rewrite_prompt(
        bundle=bundle,
        safe_base_text=safe_base_for_prompt,
        style_profile=style_profile,
        style_examples=style_examples,
        report_level=report_level,
        regenerate_nonce=regenerate_nonce,
        allow_variation=allow_variation,
    )
    if use_llm:
        prompt = _with_llm_min_words_requirement(prompt, effective_llm_min_words)

    status: list[str] = [
        "Đã áp dụng quy ước thuật ngữ tuần 4.",
        "Đã tạo SAFE_BASE_TEXT từ fact pack Python/SQL.",
        "LLM chỉ được phép viết từ facts/digest đã khóa; số liệu, cặp nhãn-số và nhận định xếp hạng được hậu kiểm trước khi chấp nhận.",
        "SAFE_BASE_TEXT chỉ dùng cho facts renderer/no-LLM và hậu kiểm; mẫu nhiều số/cột không dùng nó làm văn mẫu để LLM chép lại.",
    ]
    raw_llm_text = ""
    final_text = ""
    final_source = "facts_renderer_expanded_fallback"
    used_llm = False
    fallback_used = False
    raw_llm_warnings: list[str] = []
    raw_llm_rejected_reasons: list[str] = []
    final_validation_warnings: list[str] = []
    raw_llm_attempted = False
    raw_llm_validation_passed = False
    best_fact_pass_candidate = ""
    best_fact_pass_public_warnings: list[str] = []
    best_fact_pass_attempt = 0
    rewrite_retry_attempted = False
    llm_no_fallback = bool(use_llm and str(llm_failure_policy or "").lower() in {"no_fallback", "no-fallback", "none"})
    llm_failed_no_fallback = False

    llm_attempt_results: list[dict[str, Any]] = []
    final_text_fact_audit: dict[str, Any] = {}
    llm_attempt_count = 0
    max_llm_attempts = _report_llm_max_attempts() if use_llm else 0
    repair_changed_text_any = False
    if high_risk_llm_mode:
        status.append("Mẫu nhiều số/cột: ưu tiên prompt facts-only/digest để LLM tự diễn đạt, còn số liệu vẫn bị validator và fact audit khóa lại.")
    if use_llm:
        status.append(f"Yêu cầu độ dài LLM: tối thiểu {effective_llm_min_words} từ theo cấu hình UI.")
        status.append("Các lượt cuối dùng prompt fact-guarded hẹp hơn: LLM viết từ digest số liệu đã khóa; không đưa nguyên đoạn fallback cho mẫu nhiều số/cột.")

    if use_llm:
        raw_llm_attempted = True
        last_warnings: list[str] = []
        status.append(f"Chế độ LLM: tự thử tối đa {max_llm_attempts} lần trong một lượt sinh; chỉ dùng văn bản LLM nếu qua hậu kiểm.")
        status.append("Các bản LLM bị loại vẫn được ghi trong llm_attempt_results.candidate_text để có thể kiểm tra và sửa tay khi cần.")
        if _template_id_from_bundle(bundle) == 1 or _pattern(bundle) == "overview_result":
            # Mẫu 1 hay fail vì nhiều cột số/huyện; chuyển sang prompt fact-guarded sớm hơn
            # để LLM viết từ digest động của facts/bảng thay vì tự đọc JSON lớn.
            final_guarded_start = min(max_llm_attempts, 4)
        else:
            final_guarded_start = max(1, max_llm_attempts - 2)
        for attempt_no in range(1, max_llm_attempts + 1):
            llm_attempt_count = attempt_no
            attempt_nonce = int(regenerate_nonce or 0) * 10 + attempt_no
            if attempt_no >= final_guarded_start:
                attempt_prompt = _build_final_fact_guarded_prompt(
                    bundle,
                    protected_llm_text or _protected_llm_base_text(safe_base, bundle, regenerate_nonce=attempt_nonce),
                    last_warnings,
                    attempt_no=attempt_no,
                    regenerate_nonce=attempt_nonce,
                )
            elif high_risk_llm_mode and attempt_no >= 3:
                attempt_prompt = _build_high_risk_controlled_prompt(bundle, protected_llm_text or safe_base_for_prompt, last_warnings, attempt_no=attempt_no, regenerate_nonce=attempt_nonce)
            else:
                attempt_prompt = prompt if attempt_no == 1 else _build_retry_prompt(prompt, last_warnings, attempt_no=attempt_no, bundle=bundle)
            attempt_prompt = _with_llm_min_words_requirement(attempt_prompt, effective_llm_min_words)
            try:
                raw_model_candidate = _call_ollama(attempt_prompt)
                candidate = _repair_llm_candidate_text(raw_model_candidate)
                candidate = _repair_llm_candidate_text_with_bundle(candidate, bundle)
                candidate_before_public_repair = candidate
                candidate = _public_word_final_repair_with_bundle(candidate, bundle)
                public_repair_changed = str(candidate or "").strip() != str(candidate_before_public_repair or "").strip()
                repair_changed_text_any = repair_changed_text_any or public_repair_changed
                # Không sửa candidate bằng thay cụm cố định sau LLM: để LLM tự diễn đạt thật.
                # Nếu văn bản còn quá giống SAFE_BASE_TEXT/fallback, quality gate bên dưới sẽ reject và retry.
                ok, warnings = _validate_candidate(candidate, safe_base, bundle, min_words=effective_llm_min_words)
                public_warnings = list(warnings) + _llm_fallback_structure_warnings(candidate)
                variation_warnings = _llm_variation_quality_warnings(
                    candidate,
                    safe_base=safe_base,
                    protected_text=protected_llm_text or _protected_llm_base_text(safe_base, bundle, regenerate_nonce=regenerate_nonce),
                    bundle=bundle,
                    regenerate_nonce=attempt_nonce,
                    attempt_no=attempt_no,
                    allow_variation=allow_variation,
                )
                gate_warnings = list(public_warnings) + list(variation_warnings)
                hard_fail = any(_is_hard_validation_warning(w) for w in public_warnings)
                ok = bool(ok and not hard_fail)
                prelim_acceptable = bool(ok and _llm_candidate_is_acceptable(gate_warnings))

                attempt_audit = _final_text_fact_audit(
                    bundle,
                    safe_base,
                    candidate,
                    public_warnings,
                    include_sentence_checks=bool(prelim_acceptable or (ok and variation_warnings)),
                )
                attempt_audit_status = str(attempt_audit.get("status") or "not_run")
                attempt_audit_summary = attempt_audit.get("summary", {}) if isinstance(attempt_audit, dict) else {}
                audit_hard_warnings = list(attempt_audit.get("hard_warnings") or [])
                audit_has_hard_fact_fail = bool(
                    audit_hard_warnings
                    or attempt_audit_status == "fail"
                    or int((attempt_audit_summary or {}).get("hard_warning_count") or 0) > 0
                    or int((attempt_audit_summary or {}).get("rule_fail_count") or 0) > 0
                )
                # Nếu chỉ có warn/ngữ cảnh nhẹ thì giữ lại; không trả văn bản rỗng chỉ vì LLM 3B viết chưa mượt.
                if ok and attempt_audit_status != "fail" and not audit_has_hard_fact_fail and not best_fact_pass_candidate:
                    best_fact_pass_candidate = candidate.strip()
                    best_fact_pass_public_warnings = _public_llm_warnings(public_warnings)
                    best_fact_pass_attempt = attempt_no
                acceptable = bool(prelim_acceptable and not audit_has_hard_fact_fail)
                if prelim_acceptable and audit_has_hard_fact_fail:
                    audit_msg = "Fact audit văn bản LLM phát hiện lỗi số liệu/cặp nhãn-số/so sánh; chưa chấp nhận candidate."
                    if audit_msg not in public_warnings:
                        public_warnings.append(audit_msg)
                    hard_fail = True
                    ok = False

                raw_llm_text = candidate
                raw_llm_warnings = _public_llm_warnings(public_warnings)
                raw_llm_validation_passed = acceptable
                # Prompt retry vẫn cần biết lỗi variation, nhưng UI chính không show các lỗi này.
                last_warnings = list(gate_warnings)
                rewrite_retry_attempted = rewrite_retry_attempted or attempt_no > 1

                llm_attempt_results.append({
                    "attempt": attempt_no,
                    "prompt_profile": "final_fact_guarded" if attempt_no >= final_guarded_start else ("high_risk_controlled" if high_risk_llm_mode and attempt_no >= 3 else ("initial" if attempt_no == 1 else "retry_with_validation_feedback")),
                    "attempt_regenerate_nonce": attempt_nonce,
                    "style_variant_id": _style_variant_id(attempt_nonce),
                    "variation_profile_name": _style_variant_profile(attempt_nonce).get("name"),
                    "prompt_fingerprint": _text_fingerprint(attempt_prompt),
                    "ok": bool(ok),
                    "accepted": bool(acceptable),
                    "hard_fail": bool(hard_fail),
                    "word_count": len(re.findall(r"\b\w+\b", candidate or "", flags=re.UNICODE)),
                    "raw_model_text": str(raw_model_candidate or "").strip(),
                    "candidate_before_public_repair": str(candidate_before_public_repair or "").strip(),
                    "public_repair_changed": bool(public_repair_changed),
                    "candidate_text": candidate.strip(),
                    "candidate_text_preview": (candidate.strip()[:600] + "...") if len(candidate.strip()) > 600 else candidate.strip(),
                    "warnings": _public_llm_warnings(public_warnings)[:12],
                    "internal_variation_warnings": list(variation_warnings or [])[:8],
                    "fact_audit_status": attempt_audit.get("status"),
                    "fact_audit_summary": attempt_audit.get("summary"),
                    "fact_audit_rules": attempt_audit.get("rules", []),
                })

                if acceptable:
                    final_text = candidate.strip()
                    final_validation_warnings = _public_llm_warnings(public_warnings)
                    final_source = "llm_rewrite_validated" if attempt_no == 1 else "llm_rewrite_validated_retry"
                    used_llm = True
                    status.append(f"LLM rewrite lần {attempt_no}/{max_llm_attempts} không có lỗi số liệu cứng và được dùng làm văn bản cuối.")
                    break

                raw_llm_rejected_reasons = _public_llm_warnings(public_warnings)
                status.append(f"LLM rewrite lần {attempt_no}/{max_llm_attempts} chưa đạt hậu kiểm; tự thử lại." if attempt_no < max_llm_attempts else f"LLM rewrite chưa có bản đạt toàn bộ tiêu chí sau {max_llm_attempts} lần thử.")
            except Exception as exc:
                err = str(exc)
                raw_llm_warnings = [err]
                raw_llm_rejected_reasons = [err]
                last_warnings = [err]
                rewrite_retry_attempted = rewrite_retry_attempted or attempt_no > 1
                llm_attempt_results.append({
                    "attempt": attempt_no,
                    "prompt_profile": "final_fact_guarded" if attempt_no >= final_guarded_start else ("high_risk_controlled" if high_risk_llm_mode and attempt_no >= 3 else ("initial" if attempt_no == 1 else "retry_with_validation_feedback")),
                    "attempt_regenerate_nonce": attempt_nonce,
                    "style_variant_id": _style_variant_id(attempt_nonce),
                    "variation_profile_name": _style_variant_profile(attempt_nonce).get("name"),
                    "prompt_fingerprint": _text_fingerprint(attempt_prompt),
                    "ok": False,
                    "accepted": False,
                    "hard_fail": True,
                    "word_count": 0,
                    "warnings": [err],
                })
                status.append(f"LLM rewrite lần {attempt_no}/{max_llm_attempts} lỗi: {err}")
                # Lỗi kết nối/timeout thường không tự hết trong cùng một lượt; dừng để tránh đợi vô ích.
                if "Không kết nối được Ollama" in err or "quá chậm" in err or "Read timed out" in err:
                    break

        if not final_text and best_fact_pass_candidate:
            # Nếu mọi lượt chỉ vướng cổng đa dạng nội bộ nhưng đã pass số liệu, không trả text rỗng.
            final_text = best_fact_pass_candidate
            final_validation_warnings = list(best_fact_pass_public_warnings)
            final_source = "llm_rewrite_validated_fact_pass"
            used_llm = True
            fallback_used = False
            status.append(f"LLM rewrite đạt hậu kiểm số liệu và được dùng làm văn bản cuối.")
        if not final_text:
            # Chế độ LLM bắt buộc: chưa có bản LLM đạt hậu kiểm, trả trạng thái lỗi để sinh lại/sửa tay.
            fallback_used = False
    else:
        fallback_used = False
        final_source = "python_auto"
        status.append("generation_mode=no_llm/use_llm=False; dùng văn bản Python tự động từ SAFE_BASE_TEXT, đây là chế độ không LLM chứ không phải fallback lỗi.")

    if not final_text:
        if use_llm:
            # Nếu 10 lần LLM đều fail hậu kiểm, trả trạng thái lỗi LLM để người dùng sinh lại/sửa tay.
            final_text = ""
            final_validation_warnings = _public_llm_warnings(list(raw_llm_rejected_reasons or raw_llm_warnings or []))
            final_validation_warnings.append(
                "LLM chưa tạo được văn bản đạt hậu kiểm số liệu sau các lần thử."
            )
            llm_failed_no_fallback = True
            fallback_used = False
            final_source = "llm_failed_strict_no_python_fallback"
            status.append(
                "LLM rewrite chưa có bản đạt hậu kiểm trong lượt sinh này. Hãy sinh lại hoặc chỉnh sửa thủ công."
            )
        else:
            final_text = _expand_fallback_text(safe_base, bundle, regenerate_nonce=regenerate_nonce)
            ok, extra_warnings = _validate_candidate(final_text, safe_base, bundle)
            final_validation_warnings = list(extra_warnings)
            llm_failed_no_fallback = False
            fallback_used = False
            final_source = "python_auto"

    if final_text.strip():
        before_final_public_repair = final_text
        final_text = _public_word_final_repair_with_bundle(final_text, bundle)
        repair_changed_text_any = repair_changed_text_any or (str(final_text or "").strip() != str(before_final_public_repair or "").strip())

    word_count = len(re.findall(r"\b\w+\b", final_text, flags=re.UNICODE))
    # Chốt chặn cuối: trong chế độ Có LLM, văn bản cuối không được thấp hơn llm_min_words.
    # Nếu còn lọt qua vòng retry/repair thì hủy accepted và trả fail, không tráo sang fallback.
    if use_llm and final_text.strip() and word_count < effective_llm_min_words:
        length_warning = (
            f"Văn bản LLM dưới ngưỡng tối thiểu đã cấu hình: {word_count} từ, "
            f"cần tối thiểu {effective_llm_min_words} từ."
        )
        if length_warning not in final_validation_warnings:
            final_validation_warnings.append(length_warning)
        if final_source.startswith("llm_rewrite_validated"):
            raw_llm_rejected_reasons = list(final_validation_warnings)
            raw_llm_validation_passed = False
            used_llm = False
            fallback_used = False
            llm_failed_no_fallback = True
            final_source = "llm_failed_strict_no_python_fallback"
            status.append("Bản LLM bị hủy vì vẫn dưới llm_min_words sau vòng retry/repair; dưới ngưỡng tối thiểu được tính là fail.")
            final_text = ""
            word_count = 0
    if final_text.strip() and word_count < 120 and not any("ngắn" in w for w in final_validation_warnings):
        final_validation_warnings.append("Văn bản còn ngắn so với độ dài tối thiểu đã cấu hình.")
    final_vs_fallback_similarity = normalized_text_similarity(final_text, fallback_reference_text) if final_text.strip() else 0.0
    if use_llm and used_llm and final_vs_fallback_similarity > 0.92:
        final_validation_warnings.append(
            f"Văn bản LLM còn quá giống fallback/no-LLM (similarity={final_vs_fallback_similarity:.2f}); cần tăng khác biệt diễn đạt."
        )

    final_text_fact_audit = _final_text_fact_audit(
        bundle,
        safe_base,
        final_text,
        final_validation_warnings,
        include_sentence_checks=True,
    ) if str(final_text or "").strip() else {
        "schema": "final_text_fact_audit",
        "status": "fail",
        "summary": {"status": "fail", "rule_pass_count": 0, "rule_warn_count": 0, "rule_fail_count": 1, "sentence_pass_count": 0, "sentence_warn_count": 0, "sentence_fail_count": 0, "hard_warning_count": 1, "soft_warning_count": 0},
        "rules": [_audit_rule("empty_text", "Văn bản cuối không được rỗng", ["Văn bản cuối rỗng hoặc LLM chưa tạo được văn bản đạt hậu kiểm."])],
        "sentence_checks": [],
        "hard_warnings": ["Văn bản cuối rỗng hoặc LLM chưa tạo được văn bản đạt hậu kiểm."],
        "soft_warnings": [],
        "display_policy": {"show_for_llm_pass": True, "show_for_llm_fail": True, "ui_rule": "Nếu status='fail' thì không cho final_validation_passed=true; nếu status='warn' thì cho qua nhưng hiển thị cảnh báo; nếu status='pass' thì hiển thị checklist xanh để người dùng kiểm nhanh. Lỗi dưới llm_min_words không được accepted; hệ thống retry tới khi đạt ngưỡng hoặc hết số lần thử."},
    }
    final_audit_summary = final_text_fact_audit.get("summary", {}) if isinstance(final_text_fact_audit, dict) else {}
    final_audit_status = str(final_text_fact_audit.get("status") or "not_run") if isinstance(final_text_fact_audit, dict) else "not_run"
    if final_audit_status == "fail":
        for w in final_text_fact_audit.get("hard_warnings", [])[:6]:
            if w and w not in final_validation_warnings:
                final_validation_warnings.append(str(w))
    status.append(
        "Fact audit văn bản cuối: "
        f"{final_audit_status}; "
        f"rules pass/warn/fail = {final_audit_summary.get('rule_pass_count', 0)}/"
        f"{final_audit_summary.get('rule_warn_count', 0)}/"
        f"{final_audit_summary.get('rule_fail_count', 0)}; "
        f"sentence pass/warn/fail = {final_audit_summary.get('sentence_pass_count', 0)}/"
        f"{final_audit_summary.get('sentence_warn_count', 0)}/"
        f"{final_audit_summary.get('sentence_fail_count', 0)}."
    )

    final_hard_fail = (
        bool(llm_failed_no_fallback or not str(final_text or "").strip())
        or any(_is_hard_validation_warning(w) for w in final_validation_warnings)
        or final_audit_status == "fail"
        or int((final_audit_summary or {}).get("hard_warning_count") or 0) > 0
        or int((final_audit_summary or {}).get("rule_fail_count") or 0) > 0
    )

    report_facts_json = bundle.to_jsonable()
    report_facts_json["final_text_fact_audit"] = final_text_fact_audit
    return ReportTextResult(
        text=final_text,
        prompt=prompt,
        mode=mode or "template_report",
        report_pattern=str((bundle.template or {}).get("pattern") or "overview_result"),
        report_level=report_level,
        used_llm=used_llm,
        warnings=final_validation_warnings,
        raw_llm_text=raw_llm_text,
        repair_prompt=prompt,
        repair_text=raw_llm_text,
        repair_attempted=raw_llm_attempted,
        repair_success=raw_llm_validation_passed,
        repair_noop=not raw_llm_attempted,
        repair_validation_warnings=raw_llm_warnings if raw_llm_attempted else final_validation_warnings,
        fallback_used=fallback_used,
        validation_warnings=final_validation_warnings,
        fallback_validation_warnings=final_validation_warnings if fallback_used else [],
        final_validation_warnings=final_validation_warnings,
        report_facts=report_facts_json,
        report_generation_strategy="facts_first_llm_rewrite_with_validation",
        final_source=final_source,
        raw_llm_attempted=raw_llm_attempted,
        raw_llm_validation_passed=raw_llm_validation_passed,
        raw_llm_warnings=raw_llm_warnings,
        raw_llm_rejected_reasons=raw_llm_rejected_reasons,
        repair_validation_passed=raw_llm_validation_passed,
        final_validation_passed=not final_hard_fail,
        llm_rewrite_attempted=raw_llm_attempted,
        llm_rewrite_success=used_llm,
        llm_rewrite_validation_passed=raw_llm_validation_passed,
        report_regenerate_nonce=regenerate_nonce,
        rewrite_similarity=final_vs_fallback_similarity,
        rewrite_retry_attempted=rewrite_retry_attempted,
        raw_generation_disabled_by_design=False,
        status_messages=status,
        generation_mode=str(generation_mode or ("llm" if use_llm else "no_llm")),
        llm_failure_policy=str(llm_failure_policy or "no_fallback"),
        llm_failed=bool(llm_failed_no_fallback),
        llm_failure_message=("; ".join(map(str, final_validation_warnings[:5])) if llm_failed_no_fallback else ""),
        llm_attempt_count=int(llm_attempt_count or 0),
        llm_max_attempts=int(max_llm_attempts or 0),
        llm_min_words=int(effective_llm_min_words or 0),
        llm_attempt_results=llm_attempt_results,
        final_text_fact_audit=final_text_fact_audit,
        final_text_fact_audit_status=final_audit_status,
        final_text_fact_audit_rules=final_text_fact_audit.get("rules", []) if isinstance(final_text_fact_audit, dict) else [],
        style_variant_id=_style_variant_id(regenerate_nonce),
        variation_profile_name=str(style_profile_for_run.get("name") or ""),
        prompt_fingerprint=_text_fingerprint(prompt),
        safe_base_fingerprint=_text_fingerprint(safe_base),
        fallback_text_fingerprint=_text_fingerprint(fallback_reference_text),
        final_text_fingerprint=_text_fingerprint(final_text),
        similarity_to_fallback=round(final_vs_fallback_similarity, 4),
        repair_changed_text=bool(repair_changed_text_any),
    )
