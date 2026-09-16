from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

ReportOutputKind = Literal["text", "docx", "xlsx"]


@dataclass(frozen=True)
class ReportTemplate:
    """Metadata cho 13 mẫu báo cáo hành chính.

    Dùng chung cho tuần 4 và tuần 5:
    - Tuần 4: chọn template_id để sinh full text nhận định + fact pack.
    - Tuần 5: dùng lại template_id để render Word/Excel theo đúng cấu trúc mẫu.
    """

    id: int
    code: str
    title: str
    source_file: str
    pattern: str
    business_group: str
    household_focus: str | None
    description: str
    week4_text_goal: str
    week5_output_goal: str
    recommended_chart: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


REPORT_TEMPLATES: dict[int, ReportTemplate] = {
    1: ReportTemplate(
        id=1,
        code="overview_review",
        title="Tổng hợp kết quả rà soát HC, CN, NL, NN có mức sống trung bình",
        source_file="1. Tổng hợp kết quả rà soát HC,CN,NL,NN có mức sống trung bình.xlsx",
        pattern="overview_result",
        business_group="Tổng hợp kết quả rà soát chung",
        household_focus=None,
        description="Tổng hợp quy mô hộ rà soát, hộ nghèo, hộ cận nghèo, hộ không nghèo và nhóm mức sống trung bình.",
        week4_text_goal="Sinh nhận định tổng quan về kết quả rà soát, nêu quy mô, cơ cấu và nhóm cần theo dõi.",
        week5_output_goal="Tạo báo cáo Word/Excel mở đầu, có bảng tổng hợp và nhận định khái quát.",
        recommended_chart="bar",
    ),
    2: ReportTemplate(
        id=2,
        code="poverty_dynamics",
        title="Tổng hợp diễn biến hộ nghèo",
        source_file="2. Tổng hợp diễn biến hộ nghèo.xlsx",
        pattern="movement",
        business_group="Diễn biến hộ nghèo",
        household_focus="Hộ nghèo",
        description="So sánh hộ nghèo giữa các năm, xác định mức tăng/giảm và địa bàn biến động nổi bật.",
        week4_text_goal="Sinh nhận định diễn biến hộ nghèo, chỉ rõ tăng/giảm và địa bàn cần chú ý.",
        week5_output_goal="Tạo báo cáo diễn biến hộ nghèo, có bảng so sánh theo địa bàn và đoạn nhận định.",
        recommended_chart="line",
    ),
    3: ReportTemplate(
        id=3,
        code="near_poverty_dynamics",
        title="Tổng hợp diễn biến hộ cận nghèo",
        source_file="3. Tổng hợp diễn biến hộ cận nghèo.xlsx",
        pattern="movement",
        business_group="Diễn biến hộ cận nghèo",
        household_focus="Hộ cận nghèo",
        description="Tổng hợp diễn biến hộ cận nghèo trong kỳ, tách rõ cấu phần giảm, tăng và tổng cuối kỳ theo công thức mẫu.",
        week4_text_goal="Sinh nhận định diễn biến hộ cận nghèo, chỉ mô tả cấu phần tăng/giảm và giới hạn dữ liệu.",
        week5_output_goal="Tạo báo cáo diễn biến hộ cận nghèo, có bảng so sánh theo địa bàn và đoạn nhận định.",
        recommended_chart="line",
    ),
    4: ReportTemplate(
        id=4,
        code="poor_deprivation_count",
        title="Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo",
        source_file="4. Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo.xlsx",
        pattern="deprivation_count",
        business_group="Thiếu hụt DVXHCB theo số lượng",
        household_focus="Hộ nghèo",
        description="Số hộ nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản.",
        week4_text_goal="Sinh nhận định các chỉ số thiếu hụt nổi bật của hộ nghèo theo số lượng hộ.",
        week5_output_goal="Tạo báo cáo phân tích thiếu hụt DVXHCB hộ nghèo, có bảng số hộ thiếu từng chỉ số.",
        recommended_chart="bar",
    ),
    5: ReportTemplate(
        id=5,
        code="poor_deprivation_ratio",
        title="Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo",
        source_file="5. Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ nghèo.xlsx",
        pattern="deprivation_ratio",
        business_group="Thiếu hụt DVXHCB theo tỷ lệ",
        household_focus="Hộ nghèo",
        description="Tỷ lệ hộ nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản.",
        week4_text_goal="Sinh nhận định tỷ lệ thiếu hụt nổi bật của hộ nghèo, xác định chỉ số ưu tiên.",
        week5_output_goal="Tạo báo cáo tỷ lệ thiếu hụt DVXHCB hộ nghèo, có bảng tỷ lệ và nhận định.",
        recommended_chart="bar",
    ),
    6: ReportTemplate(
        id=6,
        code="near_poor_deprivation_count",
        title="Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo",
        source_file="6. Phân tích chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo.xlsx",
        pattern="deprivation_count",
        business_group="Thiếu hụt DVXHCB theo số lượng",
        household_focus="Hộ cận nghèo",
        description="Số hộ cận nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản.",
        week4_text_goal="Sinh nhận định các chỉ số thiếu hụt nổi bật của hộ cận nghèo theo số lượng hộ.",
        week5_output_goal="Tạo báo cáo phân tích thiếu hụt DVXHCB hộ cận nghèo, có bảng số hộ thiếu từng chỉ số.",
        recommended_chart="bar",
    ),
    7: ReportTemplate(
        id=7,
        code="near_poor_deprivation_ratio",
        title="Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo",
        source_file="7. Phân tích tỷ lệ các chỉ số thiếu hụt dịch vụ xã hội cơ bản hộ cận nghèo.xlsx",
        pattern="deprivation_ratio",
        business_group="Thiếu hụt DVXHCB theo tỷ lệ",
        household_focus="Hộ cận nghèo",
        description="Tỷ lệ hộ cận nghèo thiếu từng chỉ số dịch vụ xã hội cơ bản.",
        week4_text_goal="Sinh nhận định tỷ lệ thiếu hụt của hộ cận nghèo, nêu rõ các tỷ lệ thiếu hụt nổi bật và giới hạn diễn giải.",
        week5_output_goal="Tạo báo cáo tỷ lệ thiếu hụt DVXHCB hộ cận nghèo, có bảng tỷ lệ và nhận định.",
        recommended_chart="bar",
    ),
    8: ReportTemplate(
        id=8,
        code="vulnerable_groups",
        title="Phân tích hộ nghèo, hộ cận nghèo theo các nhóm đối tượng",
        source_file="8. Phân tích hộ nghèo, hộ cận nghèo theo các nhóm đối tượng.xlsx",
        pattern="vulnerable_groups",
        business_group="Nhóm đối tượng chính sách/dễ tổn thương",
        household_focus=None,
        description="Phân tích hộ nghèo/cận nghèo theo địa bàn với ba nhóm đúng mẫu: DTTS, không có khả năng lao động và có người có công với cách mạng.",
        week4_text_goal="Sinh nhận định theo địa bàn về ba nhóm trong mẫu 8: DTTS, không có khả năng lao động và có người có công với cách mạng.",
        week5_output_goal="Tạo báo cáo phân tích mẫu 8 theo địa bàn, chỉ dùng các cột hộ nghèo/cận nghèo của DTTS, không có khả năng lao động và có người có công.",
        recommended_chart="bar",
    ),
    9: ReportTemplate(
        id=9,
        code="ethnicity_structure",
        title="Phân tích hộ nghèo, hộ cận nghèo theo dân tộc",
        source_file="9. Phân tích hộ nghèo, hộ cận nghèo theo dân tộc.xlsx",
        pattern="ethnicity",
        business_group="Cơ cấu dân tộc",
        household_focus=None,
        description="Cơ cấu hộ nghèo/cận nghèo theo dân tộc chi tiết và dân tộc thiểu số tại chỗ.",
        week4_text_goal="Sinh nhận định cơ cấu dân tộc, xác định nhóm dân tộc chiếm quy mô/tỷ trọng lớn.",
        week5_output_goal="Tạo báo cáo theo dân tộc, có bảng hộ nghèo/cận nghèo theo từng dân tộc.",
        recommended_chart="bar",
    ),
    10: ReportTemplate(
        id=10,
        code="poverty_causes",
        title="Phân tích hộ nghèo, hộ cận nghèo theo nguyên nhân nghèo",
        source_file="10. Phân tích hộ nghèo, hộ cận nghèo theo nguyên nhân nghèo.xlsx",
        pattern="causes",
        business_group="Nguyên nhân nghèo/cận nghèo",
        household_focus=None,
        description="Phân tích nguyên nhân nghèo/cận nghèo: thiếu đất, thiếu vốn, thiếu lao động, thiếu công cụ, thiếu kiến thức, ốm đau...",
        week4_text_goal="Sinh nhận định nguyên nhân nghèo chủ yếu và hướng hỗ trợ phù hợp.",
        week5_output_goal="Tạo báo cáo nguyên nhân nghèo, có bảng nguyên nhân và đoạn nhận định quản lý.",
        recommended_chart="bar",
    ),
    11: ReportTemplate(
        id=11,
        code="child_deprivation",
        title="Tổng hợp chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo, hộ cận nghèo",
        source_file="11. Tổng hợp chỉ tiêu thiếu hụt của trẻ em thuộc hộ nghèo, hộ cận nghèo.xlsx",
        pattern="child_deprivation",
        business_group="Thiếu hụt trẻ em",
        household_focus=None,
        description="Tổng hợp thiếu hụt của trẻ em trong hộ nghèo/cận nghèo về BHYT, dinh dưỡng và đi học.",
        week4_text_goal="Sinh nhận định thiếu hụt trẻ em theo y tế, dinh dưỡng, giáo dục.",
        week5_output_goal="Tạo báo cáo chuyên đề trẻ em trong hộ nghèo/cận nghèo.",
        recommended_chart="bar",
    ),
    12: ReportTemplate(
        id=12,
        code="multidim_poverty_summary",
        title="Tổng hợp kết quả rà soát hộ nghèo theo chuẩn đa chiều",
        source_file="12. Tổng hợp kết quả rà soát hộ nghèo theo chuẩn đa chiều.xlsx",
        pattern="multidimensional_standard",
        business_group="Chuẩn nghèo đa chiều",
        household_focus="Hộ nghèo",
        description="Tổng hợp hộ nghèo theo chuẩn đa chiều: tổng hộ, nhân khẩu, cơ cấu Kinh/DTTS/DTTS tại chỗ, tỷ lệ nghèo.",
        week4_text_goal="Sinh nhận định kết quả rà soát hộ nghèo theo chuẩn đa chiều.",
        week5_output_goal="Tạo báo cáo chuẩn nghèo đa chiều cho hộ nghèo.",
        recommended_chart="bar",
    ),
    13: ReportTemplate(
        id=13,
        code="multidim_near_poverty_summary",
        title="Tổng hợp kết quả rà soát hộ cận nghèo theo chuẩn đa chiều",
        source_file="13. Tổng hợp kết quả rà soát hộ cận nghèo theo chuẩn đa chiều.xlsx",
        pattern="multidimensional_standard",
        business_group="Chuẩn nghèo đa chiều",
        household_focus="Hộ cận nghèo",
        description="Tổng hợp hộ cận nghèo theo chuẩn đa chiều: tổng hộ, nhân khẩu, cơ cấu Kinh/DTTS/DTTS tại chỗ, tỷ lệ cận nghèo.",
        week4_text_goal="Sinh nhận định kết quả rà soát hộ cận nghèo theo chuẩn đa chiều, tách rõ số hộ, nhân khẩu và tỷ lệ.",
        week5_output_goal="Tạo báo cáo chuẩn nghèo đa chiều cho hộ cận nghèo.",
        recommended_chart="bar",
    ),
}


REPORT_TEMPLATE_OPTIONS: dict[str, int] = {
    f"{template.id}. {template.title}": template.id
    for template in REPORT_TEMPLATES.values()
}


def get_report_template(template_id: int | str | None) -> ReportTemplate:
    """Resolve template by numeric id or template code."""
    if template_id is None:
        return REPORT_TEMPLATES[1]
    if isinstance(template_id, str):
        raw = template_id.strip()
        if raw.isdigit():
            template_id = int(raw)
        else:
            for template in REPORT_TEMPLATES.values():
                if raw == template.code:
                    return template
            raise KeyError(f"Không tìm thấy report template code: {template_id}")
    if int(template_id) not in REPORT_TEMPLATES:
        raise KeyError(f"Không tìm thấy report template id: {template_id}")
    return REPORT_TEMPLATES[int(template_id)]


def list_report_templates() -> list[dict]:
    return [t.to_dict() for t in REPORT_TEMPLATES.values()]
