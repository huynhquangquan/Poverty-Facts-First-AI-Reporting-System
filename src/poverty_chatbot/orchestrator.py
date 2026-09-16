from __future__ import annotations
import re
import time
import traceback
import unicodedata
from typing import Any
import pandas as pd
import json
import requests
from .config import MODEL_NAME, OLLAMA_URL
from core.schema import Filter, QueryPlan
from core.catalog import (
    FLAG_GROUPS,
    INTENT_TERM_CATALOG,
    UNSUPPORTED_INTENT_RULES,
    SENSITIVE_DATA_TERMS,
    RATIO_DENOMINATOR_TERMS,
    RATIO_FEATURE_COLS,
    COMPLEX_QUESTION_TERMS,
    COMPLEX_QUESTION_KEY_TERMS,
    LLM_AUDIT_TERMS,
    LLM_AUDIT_COLON_TERMS,
)
from .query_plan import (
    ambiguous_commune_in_question,
    canonicalize_plan,
    extract_rule_plan,
    merge_rule_llm_plan,
    parse_llm_query_plan,
    validate_plan,
    vn_name_key,
    _asks_all_social_deprivation_indicators,
    _is_distinct_value_question,
    _is_general_policy_support_metrics_question,
    _latest_data_year,
)
from core.executor import execute_query_plan, enrich_group_ratio_result
from core.answer_format import format_query_plan_answer
UNKNOWN_ANSWER = (
    "Mình chưa tìm thấy thông tin phù hợp để trả lời chắc chắn cho câu hỏi này. "
    "Vui lòng đặt lại câu hỏi đầy đủ hơn, gồm năm, địa bàn, nhóm hộ hoặc đặc trưng cần tra cứu."
)
SAFE_FAILURE_ANSWER = 'Mình chưa thể truy xuất số liệu đáng tin cậy cho câu hỏi này. Vui lòng thử lại sau.'
RATIO_CLARIFICATION_ANSWER = 'Mình chưa xác định rõ mẫu số của tỷ lệ cần tính nên chưa thể trả lời chắc chắn. Vui lòng đặt lại câu hỏi đầy đủ, ví dụ: tỷ lệ trên tổng hộ nghèo, tổng hộ cận nghèo hoặc tổng số hộ rà soát.'
MULTI_CONDITION_TERMS = INTENT_TERM_CATALOG["multi_condition"]
LIST_TERMS = INTENT_TERM_CATALOG["list"]
RATIO_TERMS = INTENT_TERM_CATALOG["ratio"]

def normalize_question(question: str) -> str:
    if not isinstance(question, str):
        raise TypeError('question phải là chuỗi')
    return unicodedata.normalize('NFC', re.sub('\\s+', ' ', question).strip())

def detect_blocked_question(question: str) -> tuple[str, str] | None:
    q = question.lower()
    q_key = vn_name_key(question)
    for reason, rule in UNSUPPORTED_INTENT_RULES.items():
        if any(re.search(pattern, q_key) for pattern in rule.get("patterns", ())):
            return rule["answer"], reason

    if any(x in q_key for x in SENSITIVE_DATA_TERMS):
        return (
            'Không thể cung cấp CCCD, số điện thoại, địa chỉ cụ thể, mã định danh, giấy tờ tùy thân hoặc thông tin liên hệ cá nhân của hộ.',
            'personal_data_request',
        )

    if any((term in q for term in ('dự báo', 'dự đoán', 'forecast'))):
            return (
                'Không thể dự báo tương lai từ bộ dữ liệu rà soát hiện có.',
                'unsupported_forecast',
            )
    years = [int(y) for y in re.findall(r'\b20\d{2}\b', q_key)]
    if years and max(years) > 2024:
        return (
            'Dữ liệu hiện có không đủ để dự báo hoặc kết luận cho năm sau 2024.',
            'unsupported_future_year',
        )

    if any(x in q_key for x in (
        'ai la nguoi ngheo nhat',
        'nguoi ngheo nhat tinh',
        'ngheo nhat tinh',
        'nguyen nhan that su cua tung ho',
    )):
        return (
            'Không thể xếp hạng cá nhân nghèo nhất hoặc suy diễn nguyên nhân thật sự của từng hộ từ dữ liệu thống kê.',
            'unsupported_personal_inference',
        )

    if re.search(r'\b\d{9,12}\b', q):
        return (
            'Không thể tra cứu hoặc cung cấp thông tin hộ bằng CCCD/mã định danh cá nhân.',
            'personal_identifier_request',
        )

    if any((term in q for term in ('cccd', 'căn cước', 'cmnd', 'chứng minh nhân dân', 'số điện thoại', 'điện thoại', 'phone', 'thông tin liên hệ cá nhân'))):
        return (
            'Không thể cung cấp CCCD, số điện thoại hoặc thông tin liên hệ cá nhân của chủ hộ.',
            'personal_data_request',
        )

    return None

def detect_ambiguous_ratio(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)
    if _asks_all_social_deprivation_indicators(question):
        has_year = re.search(r'\b20\d{2}\b', q_key) is not None
        has_class = any(x in q_key for x in (
            "ho ngheo",
            "ho can ngheo",
            "ho khong ngheo",
            "nhom ngheo",
            "nhom can ngheo",
            "nhom khong ngheo",
        ))

        if has_year and has_class:
            return False
    if not any((term in q for term in RATIO_TERMS)):
        return False

    # Quy ước nghiệp vụ mặc định: tỷ lệ hộ theo phân loại dùng tổng hộ rà
    # soát cùng năm/cùng địa bàn làm mẫu số. Đây là một mẫu câu xác định.
    if re.search(r'\bty le\s+(?:so\s+)?ho\s+(?:ngheo|can ngheo|khong ngheo)\b', q_key):
        return False
    if 'tỷ lệ phụ thuộc' in q or 'ty le phu thuoc' in q_key or 'bình quân' in q or ('trung bình' in q) or ('binh quan' in q_key) or ('trung binh' in q_key):
        return False
    if re.search('\\b(trong|trên|so với)\\s+tổng(?:\\s+số)?\\s+hộ\\s+(nghèo|cận nghèo|không nghèo|rà soát)\\b', q):
        return False
    if any(term in q or vn_name_key(term) in q_key for term in RATIO_DENOMINATOR_TERMS):
        return False
    try:
        rule_plan = extract_rule_plan(question)
        filter_cols = {item.get('col') for item in rule_plan.get('filters', [])}
        target_col = rule_plan.get('target_col')
        metric = rule_plan.get('metric')
        group_by = rule_plan.get('group_by') or []
    except Exception:
        filter_cols = set()
        target_col = None
        metric = None
        group_by = []
    explicit_class = 'phan_loai' in filter_cols
    explicit_feature = bool(filter_cols & RATIO_FEATURE_COLS) or (metric == 'ratio' and target_col in RATIO_FEATURE_COLS)
    explicit_year = 'nam' in filter_cols
    grouped_flag_ratio = (
        metric == 'ratio'
        and len(group_by) == 1
        and group_by[0] in FLAG_GROUPS
        and explicit_year
        and explicit_class
    )
    if grouped_flag_ratio:
        return False
    classification_share = (
        metric == 'ratio'
        and target_col == 'phan_loai'
        and explicit_year
        and explicit_class
    )
    if classification_share:
        return False
    group_ratio_context = (
        explicit_feature
        and any(x in q_key for x in (
            "huyen nao", "xa nao", "dia ban nao",
            "theo huyen", "tung huyen",
            "theo xa", "tung xa",
            "theo phan loai", "phan loai ho",
        ))
        and explicit_year
    )

    if group_ratio_context:
        return False
    if explicit_class and explicit_year and explicit_feature:
        return False
    clear_denominator_context = (
        re.search(r'\btrong\s+(?:nhóm\s+)?hộ\s+(nghèo|cận nghèo|không nghèo)\b', q)
        or re.search(r'\btrên\s+tổng(?:\s+số)?\s+hộ\s+(nghèo|cận nghèo|không nghèo|rà soát)\b', q)
        or re.search(
            r'\blấy\s+riêng\s+(?:nhóm\s+)?hộ\s+(nghèo|cận nghèo|không nghèo)\b.{0,80}\bmẫu\s+số\b',
            q,
        )
    )

    precise_official_feature_context = (
        any(x in q_key for x in (
            "tre em duoi 6",
            "tre duoi 6",
            "duoi 6 tuoi",
        ))
        and any(x in q_key for x in (
            "ho ngheo",
            "ho can ngheo",
            "ho khong ngheo",
        ))
    )

    if precise_official_feature_context:
        return False

    if explicit_class and explicit_feature and clear_denominator_context:
        return False
    return 'chủ hộ' not in q and 'dân tộc' not in q

def is_complex_question(question: str) -> bool:
    q = question.lower()
    q_key = vn_name_key(question)
    complex_terms = COMPLEX_QUESTION_TERMS
    complex_key_terms = COMPLEX_QUESTION_KEY_TERMS
    return any((term in q for term in MULTI_CONDITION_TERMS + LIST_TERMS)) or any((term in q for term in complex_terms)) or any((term in q_key for term in complex_key_terms)) or (len(re.findall('\\b20\\d{2}\\b', q)) > 1)

def requires_llm_audit(question: str) -> bool:
    q_key = vn_name_key(question)
    no_accent_like = not any(
        ch in question
        for ch in "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    )
    return (
        no_accent_like
        or any(x in q_key for x in LLM_AUDIT_TERMS)
        or (
            ":" in question
            and any(x in q_key for x in LLM_AUDIT_COLON_TERMS)
        )
    )

def _as_dataframe(result: Any) -> pd.DataFrame | None:
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, dict):
        return pd.DataFrame([result])
    if isinstance(result, list):
        return pd.DataFrame(result)
    return None

def verify_answer_shape(question: str, result: Any, debug: dict, answer: str='') -> tuple[bool, str]:
    q = question.lower()
    df = _as_dataframe(result)
    columns = set(df.columns) if df is not None else set()
    requirements = ((('huyện nào', 'theo huyện', 'từng huyện'), 'huyen'), (('xã nào', 'theo xã', 'từng xã'), 'xa_phuong'), (('liệt kê', 'danh sách'), 'chu_ho'))
    for terms, column in requirements:
        if column == 'chu_ho' and _is_distinct_value_question(question):
            continue
        if any((term in q for term in terms)) and column not in columns:
            return (False, f'missing_required_column:{column}')
    if any((term in q for term in RATIO_TERMS)):
        q_key = vn_name_key(question)
        is_dependency_average = 'tỷ lệ phụ thuộc' in q or 'ty le phu thuoc' in q_key
        if not is_dependency_average and not ({'ty_le_%', 'ty_le_pct'} & columns) and ('%' not in answer):
            return (False, 'missing_ratio_output')
    return (True, '')

def _plan_matches_question(question: str, plan: QueryPlan) -> tuple[bool, str]:
    q = question.lower()
    q_key = vn_name_key(question)
    if (
        any((term in q for term in ('liệt kê', 'danh sách')))
        and not _is_distinct_value_question(question)
        and plan.task != 'list_records'
    ):
        return (False, 'plan_not_list_records')
    if any((term in q for term in ('tra cứu', 'tìm chủ hộ', 'thông tin hộ', 'chi tiết hộ'))) and plan.task not in {'lookup_person', 'list_records'}:
        return (False, 'plan_not_person_lookup')
    requested_groups = []
    if (
        any(term in q for term in ('huyện nào', 'theo huyện', 'từng huyện', 'chia theo huyện', 'mỗi huyện'))
        or any(term in q_key for term in ('huyen nao', 'theo huyen', 'tung huyen', 'chia theo huyen', 'moi huyen'))
    ):
        requested_groups.append('huyen')

    if (
        any(term in q for term in ('xã nào', 'những xã', 'các xã', 'theo xã', 'từng xã', 'chia theo xã', 'mỗi xã'))
        or any(term in q_key for term in ('xa nao', 'nhung xa', 'cac xa', 'theo xa', 'tung xa', 'chia theo xa', 'moi xa'))
    ):
        requested_groups.append('xa_phuong')
    if plan.task not in {'lookup_person', 'list_records'} and any((col not in plan.group_by for col in requested_groups)):
        return (False, 'plan_missing_requested_group')
    compare_terms = ('so sánh', 'đối chiếu', 'chênh lệch')
    trend_terms = ('biến động',)

    has_compare_term = any(term in q for term in compare_terms)
    has_trend_term = any(term in q for term in trend_terms)

    trend_by_year_ok = (
        has_trend_term
        and plan.task == "group_aggregate"
        and "nam" in plan.group_by
    )

    classification_comparison_ok = (
        has_compare_term
        and plan.task == "group_aggregate"
        and "phan_loai" in plan.group_by
        and len(re.findall(r'\b20\d{2}\b', q_key)) <= 1
    )

    ratio_time_comparison_ok = (
        has_compare_term
        and plan.task == "group_aggregate"
        and plan.metric == "ratio"
        and "nam" in plan.group_by
    )

    movement_label_query_ok = (
        (has_trend_term or has_compare_term)
        and (
            any(item.col == "bien_dong_dau_ky" for item in plan.filters)
            or "bien_dong_dau_ky" in plan.group_by
        )
    )

    same_period_group_comparison_ok = (
        has_compare_term
        and plan.task == "group_aggregate"
        and bool(plan.group_by)
        and len(re.findall(r'\b20\d{2}\b', q_key)) <= 1
    )

    if (
        (has_compare_term or has_trend_term)
        and plan.task != "compare_years"
        and not trend_by_year_ok
        and not classification_comparison_ok
        and not ratio_time_comparison_ok
        and not same_period_group_comparison_ok
        and not movement_label_query_ok
    ):
        return (False, "plan_not_compare_years")
    if any((term in q for term in ('tổng quan', 'tóm tắt', 'khái quát', 'báo cáo nhanh'))) and plan.task != 'summary':
        return (False, 'plan_not_summary')
    if plan.task not in {'multi_metric_table', 'lookup_person', 'list_records'}:
        avg_targets = {
            'thu_nhap_bq': ('thu nhập bình quân', 'thu nhập trung bình'),
            'so_nhan_khau': ('nhân khẩu trung bình', 'nhân khẩu bình quân'),
            'dien_tich_dat': ('diện tích đất trung bình', 'diện tích đất bình quân', 'đất canh tác trung bình'),
        }
        for target, terms in avg_targets.items():
            if any((term in q for term in terms)) and (plan.metric != 'avg' or plan.target_col != target):
                return (False, f'plan_wrong_average:{target}')
    unsupported_group_topics = {'mức độ thiếu hụt': 'muc_do_thieu_hut', 'sức khỏe': 'suc_khoe_chu_ho', 'nghề nghiệp': 'nghe_nghiep_chu_ho', 'học vấn': 'trinh_do_hoc_van_chu_ho', 'trình độ học vấn': 'trinh_do_hoc_van_chu_ho', 'tình trạng nhà': 'tinh_trang_nha'}
    if any((term in q for term in ('phổ biến nhất', 'thống kê', 'phân bố', 'cơ cấu'))):
        for phrase, expected in unsupported_group_topics.items():
            if phrase in q and expected not in plan.group_by:
                return (False, f'plan_missing_topic_group:{expected}')
    q_key = vn_name_key(question)
    poor_housing_asked = any((x in q for x in ('nhà ở kém', 'nhà kém', 'nhà xấu', 'nhà ở không đảm bảo', 'nhà không đảm bảo', 'nhà tạm bợ', 'không vững chắc'))) or any((x in q_key for x in ('nha o kem', 'nha kem', 'nha xau', 'nha o khong dam bao', 'nha khong dam bao', 'nha tam bo', 'khong vung chac')))
    if poor_housing_asked and plan.task != 'multi_metric_table':
        has_house_filter = any((item.col == 'tinh_trang_nha' for item in plan.filters))
        if not has_house_filter:
            return (False, 'missing_poor_housing_filter')
    if plan.task == 'group_aggregate' and plan.group_by:
        return (True, '')
    if plan.task == 'aggregate' and plan.metric == 'count_households':
        count_signal = (
            any(term in q for term in ('bao nhiêu', 'số lượng', 'số hộ', 'có mấy', 'mấy hộ', 'tổng cộng'))
            or any(term in q_key for term in ('bao nhieu', 'so luong', 'so ho', 'co may', 'may ho', 'tong cong', 'tong so', 'tong ho'))
        )

        implicit_household_count = (
            any(term in q for term in ('hộ nghèo', 'hộ cận nghèo', 'chủ hộ'))
            or any(term in q_key for term in ('ho ngheo', 'ho can ngheo', 'chu ho'))
        )
        if count_signal or implicit_household_count:
            return (True, '')
        ratio_with_supported_focus = any((term in q for term in RATIO_TERMS)) and any((item.col in {'gioi_tinh', 'dan_toc_chi_tiet'} for item in plan.filters))
        requested_detail_terms = ('học vấn', 'đọc viết', 'tốt nghiệp', 'thpt', 'đại học', 'cao đẳng')
        if any((term in q for term in requested_detail_terms)):
            has_hoc_van_filter = any((item.col == 'trinh_do_hoc_van_chu_ho' for item in plan.filters))
            has_hoc_van_group = 'trinh_do_hoc_van_chu_ho' in plan.group_by
            if not (has_hoc_van_filter or has_hoc_van_group):
                return (False, 'plan_missing_requested_detail_filter')
        has_feature_filter = any(
            item.col not in {'nam', 'huyen', 'xa_phuong', 'phan_loai', 'dan_toc_chi_tiet', 'gioi_tinh'}
            for item in plan.filters
        )
        has_or_feature_filter = any((item.col not in {'nam', 'huyen', 'xa_phuong', 'phan_loai', 'dan_toc_chi_tiet', 'gioi_tinh'} for item in getattr(plan, 'or_filters', [])))
        if not count_signal and (not ratio_with_supported_focus) and (not has_feature_filter) and (not has_or_feature_filter):
            return (False, 'default_count_without_count_intent')
    return (True, '')

def _apply_sidebar(plan: QueryPlan, sidebar_filters: dict) -> QueryPlan:
    existing = {item.col for item in plan.filters}
    if sidebar_filters.get('nam') and 'nam' not in existing:
        plan.filters.append(Filter('nam', '=', int(sidebar_filters['nam'])))
    if sidebar_filters.get('huyen') and 'huyen' not in existing:
        plan.filters.append(Filter('huyen', '=', sidebar_filters['huyen']))
    return validate_plan(plan)

def _safe_fallback_plan(question: str, sidebar_filters: dict, rule_plan: dict[str, Any] | None=None) -> QueryPlan | None:
    q = question.lower()
    q_key = vn_name_key(question)
    if any((term in q for term in MULTI_CONDITION_TERMS + LIST_TERMS + RATIO_TERMS)):
        return None
    years = [int(value) for value in re.findall('\\b20\\d{2}\\b', q)]
    if not years:
        return None
    classification = 'Hộ cận nghèo' if 'ho can ngheo' in q_key else 'Hộ nghèo' if 'ho ngheo' in q_key else None
    filters = []
    if rule_plan and isinstance(rule_plan.get('filters'), list):
        try:
            for item in rule_plan['filters']:
                if isinstance(item, dict) and item.get('col') in {'nam', 'huyen', 'xa_phuong', 'phan_loai', 'dan_toc_chi_tiet', 'gioi_tinh'}:
                    filters.append(Filter(item['col'], item.get('op', '='), item.get('value')))
        except Exception:
            filters = []
    existing_cols = {item.col for item in filters}
    if 'nam' not in existing_cols:
        filters.append(Filter('nam', '=', years[0]))
    if classification and 'phan_loai' not in existing_cols:
        filters.append(Filter('phan_loai', '=', classification))
    if sidebar_filters.get('huyen') and 'huyen' not in existing_cols:
        filters.append(Filter('huyen', '=', sidebar_filters['huyen']))
    if sidebar_filters.get('nam') and 'nam' not in existing_cols:
        filters.append(Filter('nam', '=', int(sidebar_filters['nam'])))
    if re.fullmatch('tong quan du lieu ho ngheo nam 20\\d{2}\\??', q_key) and len(years) == 1:
        return validate_plan(QueryPlan(task='summary', metric=None, filters=[Filter('nam', '=', years[0])]))
    if re.fullmatch('so sanh ho ngheo 2023 (?:va|vs) 2024\\??', q_key) and {2023, 2024} <= set(years):
        return validate_plan(QueryPlan(task='compare_years', metric='count_households', filters=[Filter('phan_loai', '=', 'Hộ nghèo')], group_by=['nam']))
    averages = ((('thu nhap binh quan', 'thu nhap trung binh'), 'thu_nhap_bq'), (('nhan khau trung binh', 'nhan khau binh quan'), 'so_nhan_khau'), (('dien tich dat trung binh', 'dien tich dat binh quan'), 'dien_tich_dat'))
    for terms, target in averages:
        simple_average = any((re.fullmatch(f'(?:{re.escape(term)}) (?:cua )?ho ngheo nam 20\\d{{2}}(?: la bao nhieu)?\\??', q_key) for term in terms))
        if classification == 'Hộ nghèo' and simple_average:
            return validate_plan(QueryPlan(task='aggregate', metric='avg', target_col=target, filters=filters))
    simple_count = bool(re.fullmatch('(?:(?:co bao nhieu|tong so|tong|so luong) )?ho (?:can )?ngheo(?: huyen [a-z ]+)? nam 20\\d{2}(?: la bao nhieu)?\\??', q_key))
    if classification and simple_count and rule_plan:
        candidate = canonicalize_plan(rule_plan)
        if candidate.task == 'aggregate' and candidate.metric == 'count_households':
            return _apply_sidebar(candidate, sidebar_filters)
    if classification and simple_count and (len(years) == 1):
        return validate_plan(QueryPlan(task='aggregate', metric='count_households', filters=filters))
    return None
ANSWER_SYSTEM = 'Bạn là trợ lý trả lời số liệu thống kê bằng tiếng Việt.\n\nQUY TẮC BẮT BUỘC:\n1. Chỉ dùng số liệu trong DATA và DRAFT_ANSWER.\n2. Không tự bịa số, không tự thêm số ngoài dữ liệu.\n3. Trả lời đúng thứ tự trong câu hỏi, đặc biệt với "lần lượt" và "tương ứng".\n4. Nếu câu hỏi hỏi nhiều đặc trưng, trả lời đủ từng đặc trưng.\n5. Trả lời ngắn gọn, tự nhiên, đúng trọng tâm.\n6. Đơn vị mặc định là hộ nếu DATA là số hộ.\n'

def _result_for_llm(result: pd.DataFrame, max_rows: int=20) -> str:
    if result is None or result.empty:
        return 'Không có dữ liệu.'
    return result.head(max_rows).to_json(orient='records', force_ascii=False)

def llm_rewrite_answer(question: str, plan: QueryPlan, result: pd.DataFrame, draft_answer: str) -> str:
    payload = {'model': MODEL_NAME, 'messages': [{'role': 'system', 'content': ANSWER_SYSTEM}, {'role': 'user', 'content': f'CÂU HỎI:\n{question}\n\nQUERY_PLAN:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\nDATA:\n{_result_for_llm(result)}\n\nDRAFT_ANSWER:\n{draft_answer}\n\nHãy viết câu trả lời cuối cùng bằng tiếng Việt, đúng trọng tâm:'}], 'stream': False, 'options': {'temperature': 0.0, 'num_predict': 300}}
    response = requests.post(OLLAMA_URL, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()['message']['content'].strip()


def _add_default_year_notice(question: str, plan: QueryPlan, answer: str) -> tuple[str, int | None]:
    if re.search(r"\b20\d{2}\b", vn_name_key(question or "")) or _is_distinct_value_question(question):
        return answer, None
    plan_year = next(
        (item.value for item in plan.filters if item.col == "nam" and item.op == "="),
        None,
    )
    latest_year = _latest_data_year()
    if (
        latest_year is not None
        and plan_year == latest_year
        and plan.task in {"aggregate", "group_aggregate", "multi_metric_table", "summary"}
    ):
        return f"Mặc định sử dụng năm mới nhất trong dữ liệu ({latest_year}). {answer}", latest_year
    return answer, None

def _execute_and_verify(question: str, plan: QueryPlan, debug: dict) -> tuple[str, pd.DataFrame, dict]:
    result = execute_query_plan(plan, question)
    result = enrich_group_ratio_result(plan, result, question)

    # Bảng cơ cấu cần cả số lượng và tỷ trọng. Giữ metric=count_households để
    # không đổi nghĩa planner, chỉ bổ sung tỷ lệ từ chính các nhóm kết quả.
    q_key = vn_name_key(question or '')
    if (
        plan.task == 'group_aggregate'
        and plan.metric == 'count_households'
        and 'so_ho' in result.columns
        and any(x in q_key for x in ('co cau', 'phan bo', 'ty trong', 'tren tong', 'trong tong'))
        and not result.empty
    ):
        # Các chiều phân loại/địa bàn trong group_by đều là các lát của cơ cấu,
        # không được tự làm mẫu số cho chính mình (sẽ thành 100% mỗi huyện).
        # Chỉ giữ chiều thời gian để mỗi năm có một tổng cơ cấu riêng.
        base_groups = [col for col in plan.group_by if col == 'nam' and col in result.columns]
        if base_groups:
            totals = result.groupby(base_groups, dropna=False)['so_ho'].transform('sum')
        else:
            totals = pd.Series(result['so_ho'].sum(), index=result.index)
        result['ty_le_%'] = (result['so_ho'] / totals.replace(0, pd.NA) * 100).fillna(0).round(1)
    draft_answer = format_query_plan_answer(plan, result, question)
    draft_answer, default_year = _add_default_year_notice(question, plan, draft_answer)
    if default_year is not None:
        debug["default_year_applied"] = True
        debug["default_year"] = default_year
    support_count_cols = [
        col for col in result.columns
        if str(col).startswith(('so_ho_ho_tro_', 'ho_ho_tro_'))
    ]
    if plan.task in {'aggregate', 'list_records', 'lookup_person', 'group_aggregate', 'compare_years', 'multi_metric_table'} or plan.or_filters or len(support_count_cols) >= 2 or ('|' in draft_answer and '---' in draft_answer):
        debug['answer_source'] = 'python_table_formatter' if '|' in draft_answer and '---' in draft_answer else 'python_formatter'
        debug['draft_answer'] = draft_answer
        ok, reason = verify_answer_shape(question, result, debug, draft_answer)
        if not ok:
            raise ValueError(f'answer_shape_mismatch:{reason}')
        return (draft_answer, result, debug)
    answer = draft_answer
    debug['answer_source'] = 'python_formatter'
    debug['draft_answer'] = draft_answer
    try:
        llm_answer = llm_rewrite_answer(question, plan, result, draft_answer)
        ok, reason = verify_answer_shape(question, result, debug, llm_answer)
        if ok and llm_answer:
            answer = llm_answer
            debug['answer_source'] = 'llm_rewrite'
        else:
            debug['llm_answer_rejected'] = reason
    except Exception as exc:
        debug['llm_answer_error'] = str(exc)
    ok, reason = verify_answer_shape(question, result, debug, answer)
    if not ok:
        raise ValueError(f'answer_shape_mismatch:{reason}')
    return (answer, result, debug)

def _terminal(answer: str, workflow: str, started: float, reason: str, **extra) -> tuple:
    debug = {'workflow': workflow, 'fallback': False, 'reason': reason, 'elapsed': round(time.time() - started, 2), **extra}
    return (answer, None, debug)

def detect_ambiguous_question(question: str) -> tuple[str, str] | None:
    q = question.lower()
    q_key = vn_name_key(question)
    try:
        resolved_filter_cols = {
            item.get("col")
            for item in extract_rule_plan(question).get("filters", [])
            if isinstance(item, dict)
        }
    except Exception:
        resolved_filter_cols = set()

    if re.fullmatch(r"huyen nao dung dau\??", q_key):
        return ("Bạn cần nói rõ huyện đứng đầu theo chỉ tiêu hoặc đặc trưng nào.", "missing_metric")

    if re.fullmatch(r"co bao nhieu ho nam 20\d{2}\??", q_key):
        return ("Bạn muốn hỏi phân loại hộ nào: hộ nghèo, hộ cận nghèo hay hộ không nghèo?", "missing_classification")

    if re.fullmatch(r"(liet ke|danh sach) cac ho ngheo\.?", q_key):
        return ("Yêu cầu danh sách hộ quá rộng. Bạn vui lòng nêu rõ năm, địa bàn và giới hạn số dòng.", "list_too_broad")

    if re.fullmatch(r"bang theo huyen cho toi\.?", q_key):
        return ("Bạn cần nói rõ năm và chỉ tiêu cần thống kê theo huyện.", "missing_table_context")

    is_toilet_question = any(x in q_key for x in (
        "nha tieu",
        "nha ve sinh",
        "nha tieu hop ve sinh",
        "nha ve sinh hop ve sinh",
        "nha tieu hvs",
        "nha ve sinh hvs",
    ))
    if any(x in q_key for x in ("dtts", "dan toc thieu so")):
        has_year = re.search(r"\b20\d{2}\b", q_key) is not None
        has_class = any(x in q_key for x in ("ho ngheo", "ho can ngheo", "ho khong ngheo"))

        if not has_year:
            return (
                "Bạn muốn hỏi năm nào? Ngoài ra, bạn muốn tính DTTS nói chung hay dân tộc thiểu số tại chỗ?",
                "ambiguous_ethnicity_context",
            )

        if not has_class:
            return (
                "Bạn muốn hỏi nhóm hộ nào: hộ nghèo, hộ cận nghèo, hộ không nghèo hay toàn bộ hộ rà soát?",
                "missing_classification",
            )
    if (
        "thieu nha" in q_key
        and not is_toilet_question
        and not any(x in q_key for x in ("chat luong nha", "dien tich nha", "nha tam", "nha don so"))
    ):
        return ("Bạn muốn hỏi thiếu nhà ở theo diện tích, chất lượng nhà ở, hay tình trạng nhà tạm/đơn sơ?", "vague_housing")

    if "thieu giao duc" in q_key and not any(x in q_key for x in ("nguoi lon", "tre em", "di hoc")):
        return ("Bạn muốn hỏi thiếu giáo dục người lớn hay thiếu đi học của trẻ em?", "vague_education")

    if "thieu thong tin" in q_key and not any(x in q_key for x in ("vien thong", "tai san thong tin", "internet")):
        return ("Bạn muốn hỏi thiếu viễn thông, thiếu tài sản thông tin hay chưa có internet?", "vague_information")

    if (
        ("duoc tro cap" in q_key or q_key.endswith("tro cap"))
        and not any(x in q_key for x in ("thuong xuyen", "dot xuat"))
    ):
        return ("Bạn muốn hỏi trợ cấp thường xuyên hay trợ cấp đột xuất?", "vague_allowance")

    if "thieu san xuat" in q_key:
        return ("Bạn muốn hỏi thiếu vốn, thiếu đất, thiếu công cụ, thiếu kiến thức hay thiếu kỹ năng sản xuất?", "vague_production")

    if any(x in q_key for x in ("nam roi", "nam ngoai", "vua roi")):
        return (
            "Mình chưa rõ bạn muốn hỏi năm nào. Bạn vui lòng nêu rõ năm, ví dụ 2023 hoặc 2024.",
            "ambiguous_year",
        )

    missing_reference_patterns = (
        r"\b(o do|o day|cho do|cho nay|cai ay|cai do)\b",
        r"\b(xa do|huyen do)\b",
        r"\bcai huyen dung dau\b",
        r"\bhuyen nhi\b",
    )

    if any(re.search(pattern, q_key) for pattern in missing_reference_patterns):
        return (
            "Mình chưa rõ bạn đang nhắc tới địa bàn hoặc đặc trưng nào. Vui lòng nêu rõ năm, địa bàn và nhóm hộ cần tra cứu.",
            "missing_reference",
        )

    if re.search(r'\bo dak\b', q_key) and not any(x in q_key for x in (
        "dak nong", "dak mil", "dak song", "dak rlap", "dak glong",
    )):
        return (
            "Bạn muốn hỏi Đắk Mil, Đắk Song, Đắk RLấp, Đăk Glong hay toàn tỉnh Đắk Nông?",
            "ambiguous_location",
        )

    if "thieu nhieu thu" in q_key:
        return (
            "Bạn muốn hiểu 'thiếu nhiều thứ' theo tổng số chiều thiếu hụt hay theo từng chỉ số thiếu hụt cụ thể?",
            "vague_metric",
        )

    if "ngheo do thieu cai gi" in q_key and not re.search(r'\b20\d{2}\b', q_key):
        return (
            "Bạn muốn thống kê nguyên nhân nghèo cho năm nào, ví dụ 2023 hay 2024?",
            "missing_year",
        )

    if (
        any(x in q_key for x in ("nha xau", "nha o xau", "nha o kem", "nha kem"))
        and any(x in q_key for x in ("xa nao", "o xa nao"))
        and not any(x in q_key for x in (
            "nhieu nhat", "it nhat", "cao nhat", "thap nhat",
            "top", "bang", "thong ke", "liet ke", "danh sach"
        ))
    ):
        return (
            "Bạn muốn hỏi xã có nhiều nhất, danh sách xã hay bảng thống kê theo xã?",
            "ambiguous_output",
        )

    poverty_count_ranking = (
        any(x in q_key for x in (
            "nhieu ho ngheo nhat",
            "it ho ngheo nhat",
            "so ho ngheo nhat",
            "nhieu ho can ngheo nhat",
            "it ho can ngheo nhat",
            "so ho can ngheo nhat",
        ))
        or re.search(r'\btop\s*\d+\b.{0,80}\bho ngheo\b', q_key)
        or re.search(r'\b(?:huyen|xa|dan toc|dia ban)\b.{0,80}\b(?:nhieu|it)\b.{0,30}\bho ngheo\b', q_key)
    )

    vague_poverty_superlative = (
        any(x in q_key for x in ("ngheo nhat", "kho khan nhat"))
        and not poverty_count_ranking
        and not any(x in q_key for x in (
            "thu nhap", "thu nhap thap", "thieu hut", "so ho", "ty le", "phan tram"
        ))
    )

    if vague_poverty_superlative:
        return (
            "Bạn muốn xác định 'nghèo nhất' theo tiêu chí nào: thu nhập thấp nhất, thiếu hụt nhiều nhất, số hộ nghèo hay tỷ lệ nghèo?",
            "vague_metric",
        )

    if any(x in q_key for x in ("danh sach ho kho khan", "danh sach ho ngheo")) and not re.search(r'\b20\d{2}\b', q_key):
        return (
            "Bạn muốn lấy danh sách cho năm nào, địa bàn nào và giới hạn bao nhiêu dòng?",
            "list_too_broad",
        )

    if "thieu nha ve sinh voi nha tam" in q_key and not any(x in q_key for x in ("dong thoi", "vua", "hoac")):
        return (
            "Bạn muốn đếm hộ đồng thời thiếu nhà vệ sinh và ở nhà tạm, hay muốn tách thành hai chỉ tiêu riêng?",
            "ambiguous_logic",
        )

    has_compare_signal = (
        any(x in q_key for x in (
            "thay doi", "tang giam", "chenh lech", "bien dong",
            "so sanh", "doi chieu", "tu 2023 sang 2024",
        ))
        or len(re.findall(r'\b20\d{2}\b', q_key)) >= 2
    )

    if has_compare_signal and any(x in q_key for x in ("ho ngheo", "ho can ngheo", "khong ngheo")):
        return None

    has_table_signal = any(x in q_key for x in (
        "bang", "thong ke", "phan bo", "co cau", "gom", "nhom theo",
    ))

    has_group_topic = any(x in q_key for x in (
        "suc khoe", "hoc van", "trinh do hoc van", "nghe nghiep",
        "tinh trang nha", "nha cua", "muc thieu hut", "muc do thieu hut",
        "dan toc", "gioi tinh",
    ))

    if has_table_signal and has_group_topic:
        return None

    has_explicit_count_signal = any(x in q_key for x in (
        "bao nhieu", "co bao nhieu", "con so", "so ho", "dem", "tong bao nhieu",
    ))

    has_explicit_feature_or_support = any(x in q_key for x in (
        "ho tro y te", "ho tro giao duc", "ho tro nha o", "ho tro vay von",
        "bhyt", "bhxh", "nha tieu", "nuoc sach", "tre em", "don than",
        "nguoi cao tuoi", "khuyet tat",

        # nguyên nhân nghèo
        "thieu von", "thieu dat", "thieu lao dong", "thieu cong cu",
        "thieu kien thuc", "thieu ky nang", "om dau", "benh tat", "tai nan",
    ))

    if has_explicit_count_signal and has_explicit_feature_or_support:
        return None

    if _is_general_policy_support_metrics_question(question):
        has_year = re.search(r"\b20\d{2}\b", q_key) is not None
        has_class = any(x in q_key for x in ("ho ngheo", "ho can ngheo", "ho khong ngheo"))
        if has_year and has_class:
            return None

    if any(x in q_key for x in (
        "te nhat",
        "cang nhat",
        "on khong",
        "nhieu khong",
        "it hay nhieu",
        "the nao",
        "sao roi",
    )):
        return (
            "Mình chưa rõ tiêu chí cần đánh giá. Bạn muốn tính theo số hộ, tỷ lệ, thiếu hụt hay loại hỗ trợ nào?",
            "vague_metric",
        )

    if "top may" in q_key:
        return (
            "Bạn muốn lấy top bao nhiêu và theo tiêu chí nào?",
            "missing_limit_or_metric",
        )

    if "theo tung cai" in q_key:
        return (
            "Bạn muốn thống kê theo tiêu chí nào: huyện, xã, dân tộc, giới tính, thiếu hụt hay loại hỗ trợ?",
            "ambiguous_group_by",
        )

    if "bao hiem" in q_key and not any(x in q_key for x in (
        "bhyt",
        "bhxh",
        "bao hiem y te",
        "bao hiem xa hoi",
    )):
        return (
            "Bạn muốn hỏi bảo hiểm y tế/BHYT hay bảo hiểm xã hội/BHXH?",
            "ambiguous_feature",
        )

    if (
        "thieu hoc" in q_key
        or (
            "hoc" in q_key
            and "thieu" in q_key
            and not any(x in q_key for x in (
                "giao duc nguoi lon",
                "di hoc tre em",
                "tre em khong di hoc",
                "tre em thieu di hoc",
            ))
        )
    ):
        return (
            "Bạn muốn hỏi thiếu giáo dục người lớn hay thiếu đi học của trẻ em?",
            "ambiguous_education_feature",
        )

    if "nuoc noi" in q_key or (
        re.search(r"\bnuoc\b", q_key)
        and not any(x in q_key for x in ("nuoc sach", "nguon nuoc", "ho tro nuoc sach"))
        and "nguon_nuoc" not in resolved_filter_cols
    ):
        return (
            "Bạn muốn hỏi nguồn nước, thiếu nước sạch hay hỗ trợ nước sạch?",
            "ambiguous_water_feature",
        )

    if "yeu the" in q_key:
        return (
            "Bạn muốn hỏi nhóm yếu thế nào: cao tuổi, khuyết tật, đơn thân, trẻ em hay không có khả năng lao động?",
            "ambiguous_vulnerable_group",
        )

    if "ho tro" in q_key and not any(x in q_key for x in (
        "y te",
        "giao duc",
        "san xuat",
        "vay von",
        "nha o",
        "nuoc sach",
        "dien",
        "vien thong",
        "dao tao nghe",
        "hoc nghe",
    )):
        return (
            "Bạn muốn hỏi loại hỗ trợ nào, năm nào và nhóm hộ nào?",
            "ambiguous_support",
        )
    if re.search(r"\btop\s*\d+\b.{0,60}\bdan toc\b", q_key):
        return None
    if (
        "dan toc" in q_key
        and any(x in q_key for x in ("o dau", "nhieu"))
        and not any(x in q_key for x in (
            "dan toc nao",
            "nhom dan toc nao",
            "theo dan toc",
            "tung dan toc",
            "cac dan toc",
            "top dan toc",
            "xep hang dan toc",
        ))
        and not any(x in q_key for x in (
            "dtts",
            "dan toc thieu so",
            "kinh",
            "mnong",
            "m nong",
            "e de",
            "tay",
            "mong",
            "nung",
            "dao",
        ))
    ):
        return (
            "Bạn muốn hỏi dân tộc cụ thể nào hay nhóm dân tộc thiểu số/DTTS?",
            "ambiguous_ethnicity",
        )

    return None

def process_question(question: str, sidebar_filters: dict | None=None) -> tuple:
    sidebar_filters = sidebar_filters or {}
    started = time.time()
    try:
        normalized = normalize_question(question)
    except Exception:
        return _terminal(SAFE_FAILURE_ANSWER, 'safe_failure', started, 'invalid_question', error=traceback.format_exc())
    blocked = detect_blocked_question(normalized)
    if blocked:
        answer, reason = blocked
        return _terminal(answer, 'blocked', started, reason)
    q_key = vn_name_key(normalized)
    ambiguous_commune = ambiguous_commune_in_question(normalized)
    ambiguous = detect_ambiguous_question(normalized)
    if ambiguous:
        answer, reason = ambiguous
        return _terminal(answer, 'clarify', started, reason)
    if ambiguous_commune:
        commune, districts = ambiguous_commune
        answer = f"{commune} tồn tại ở nhiều huyện ({' hoặc '.join(districts)}). Bạn vui lòng nêu rõ huyện cần tra cứu."
        return _terminal(answer, 'clarify', started, 'ambiguous_commune_parent')
    if detect_ambiguous_ratio(normalized):
        return _terminal(RATIO_CLARIFICATION_ANSWER, 'clarify', started, 'ambiguous_ratio_denominator')
    stages: dict[str, Any] = {'question': normalized}
    rule_plan: dict[str, Any] | None = None
    plan_errors = []
    try:
        rule_plan = extract_rule_plan(normalized)
        stages['rule_plan'] = rule_plan
        try:
            plan = _apply_sidebar(canonicalize_plan(rule_plan), sidebar_filters)
            matches, reason = _plan_matches_question(normalized, plan)
            if not matches:
                raise ValueError(reason)
            debug = {'workflow': 'query_plan', 'query_plan': plan.to_dict(), 'intent': None, 'fallback': False, 'plan_source': 'rule_plan', 'rule_plan_used': True, 'llm_attempted': False, 'llm_used': False, 'stages': stages, 'elapsed': round(time.time() - started, 2), 'error': ''}
            need_llm = is_complex_question(normalized) or requires_llm_audit(normalized)

            if not need_llm:
                return _execute_and_verify(normalized, plan, debug)

            stages['rule_baseline_plan'] = plan.to_dict()
        except Exception as exc:
            plan_errors.append({'stage': 'rule_plan', 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
        llm_candidates = []
        try:
            stages['llm_attempted'] = True
            llm_started = time.time()
            llm_plan = parse_llm_query_plan(normalized)
            stages['llm_elapsed'] = round(time.time() - llm_started, 2)
            stages['llm_plan'] = llm_plan
            if rule_plan:
                llm_candidates.append(('llm_merged_with_rule', merge_rule_llm_plan(rule_plan, llm_plan)))
            llm_candidates.append(('llm_plan', llm_plan))
        except Exception as exc:
            stages['llm_attempted'] = True
            stages['llm_elapsed'] = round(time.time() - llm_started, 2) if 'llm_started' in locals() else None
            stages['llm_plan_error'] = {'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()}
            plan_errors.append({'stage': 'llm_parse', 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
        if stages.get('rule_baseline_plan'):
            try:
                plan = _apply_sidebar(canonicalize_plan(stages['rule_baseline_plan']), sidebar_filters)
                debug = {
                    'workflow': 'query_plan',
                    'query_plan': plan.to_dict(),
                    'intent': None,
                    'fallback': False,
                    'plan_source': 'rule_plan_after_llm_audit',
                    'rule_plan_used': True,
                    'llm_attempted': bool(stages.get('llm_attempted')),
                    'llm_used': False,
                    'llm_elapsed': stages.get('llm_elapsed'),
                    'stages': stages,
                    'query_plan_errors': plan_errors,
                    'elapsed': round(time.time() - started, 2),
                    'error': '',
                }
                return _execute_and_verify(normalized, plan, debug)
            except Exception as exc:
                plan_errors.append({
                    'stage': 'rule_baseline_after_llm_audit',
                    'error_type': type(exc).__name__,
                    'error': str(exc),
                    'traceback': traceback.format_exc(),
                })
        for source, raw_plan in llm_candidates:
            try:
                plan = _apply_sidebar(canonicalize_plan(raw_plan), sidebar_filters)
                matches, reason = _plan_matches_question(normalized, plan)
                if not matches:
                    raise ValueError(reason)
                debug = {'workflow': 'query_plan', 'query_plan': plan.to_dict(), 'intent': None, 'fallback': False, 'plan_source': source, 'rule_plan_used': bool(rule_plan), 'llm_attempted': True, 'llm_used': True, 'llm_elapsed': stages.get('llm_elapsed'), 'stages': stages, 'elapsed': round(time.time() - started, 2), 'error': ''}
                return _execute_and_verify(normalized, plan, debug)
            except Exception as exc:
                plan_errors.append({'stage': source, 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
        if stages.get('rule_baseline_plan'):
            try:
                plan = _apply_sidebar(canonicalize_plan(stages['rule_baseline_plan']), sidebar_filters)
                debug = {'workflow': 'query_plan', 'query_plan': plan.to_dict(), 'intent': None, 'fallback': False, 'plan_source': 'rule_plan_after_llm_attempt', 'rule_plan_used': True, 'llm_attempted': bool(stages.get('llm_attempted')), 'llm_used': False, 'llm_elapsed': stages.get('llm_elapsed'), 'stages': stages, 'query_plan_errors': plan_errors, 'elapsed': round(time.time() - started, 2), 'error': ''}
                return _execute_and_verify(normalized, plan, debug)
            except Exception as exc:
                plan_errors.append({'stage': 'rule_baseline_after_llm_attempt', 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
    except Exception as exc:
        plan_errors.append({'stage': 'query_plan_outer', 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
    needs_clarification_terms = LIST_TERMS + RATIO_TERMS + ('bao nhiêu', 'số lượng', 'số hộ', 'có mấy')
    workflow = 'clarify' if any((term in normalized.lower() for term in needs_clarification_terms)) else 'unknown'
    return _terminal(UNKNOWN_ANSWER, workflow, started, 'query_plan_not_confident', stages=stages, query_plan_errors=plan_errors)
