from __future__ import annotations

"""
report_eval_batch_36_20260703.py

Offline evaluation runner cho pipeline sinh văn bản báo cáo nhận định.

Mục tiêu:
- Chạy 12 mẫu x N lần/mẫu (mặc định 3 lần) = 36 lượt.
- Mỗi lượt gọi report_writer.generate_report_text(..., use_llm=True).
- Ghi log JSONL đủ chi tiết để kiểm lại: text cuối, attempts, warnings, fact audit,
  facts/tables nguồn, trạng thái accept/fail, và kết luận eval riêng.
- Không thay đổi report_writer.py, không ghi đè log cũ.

Cách chạy gợi ý trong project root:
    python report_eval_batch_36_20260703.py --db db/poverty.db --year 2024 --runs-per-template 3 --llm-min-words 180

Nếu muốn chỉ định trực tiếp file report_writer mới đang test:
    python report_eval_batch_36_20260703.py --writer-path report/report_writer.py --db db/poverty.db

Output mặc định:
    logs/report_eval/report_eval_YYYYMMDD_HHMMSS.jsonl
    logs/report_eval/report_eval_YYYYMMDD_HHMMSS_summary.csv
    logs/report_eval/report_eval_YYYYMMDD_HHMMSS_summary.md
    logs/report_eval/report_eval_YYYYMMDD_HHMMSS_failures.jsonl
"""

import argparse
import csv
import dataclasses
import difflib
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore

TEMPLATE_IDS = list(range(1, 13))

PROMPT_LEAK_PATTERNS = [
    r"\bREPORT_FACTS\b",
    r"\bSAFE_BASE_TEXT\b",
    r"\bfact pack\b",
    r"\bfact\b",
    r"\bvalidator\b",
    r"\bprompt\b",
    r"\bSQL\b",
    r"\bDB\b",
    r"\bdatabase\b",
    r"dữ liệu đã được cung cấp",
    r"dữ liệu đã cung cấp",
    r"thông tin đã cung cấp",
    r"văn bản nguồn",
    r"quy tắc bắt buộc",
    r"dưới đây là",
    r"theo yêu cầu",
    r"tôi viết lại",
    r"tôi tiến hành",
    r"tôi sẽ",
    r"nội dung nguồn",
    r"nguồn đã kiểm soát",
    r"nhận xét an toàn",
    r"cột\s*A\s*/\s*B",
    r"cột\s+A\b",
    r"cột\s+B\b",
]

TEMPLATE1_FORBIDDEN_PATTERNS = [
    r"hộ không nghèo",
    r"1\.350",
    r"1350",
    r"18,03",
    r"18\.03",
    r"7\.488\s+hộ.*(cơ cấu|phân loại)",
    r"49,29",
    r"32,68",
]

# Các số này trong mẫu 11 là số trẻ, không được viết thành hộ.
MAU11_CHILD_COUNT_NUMBERS = ["657", "572", "511", "501", "484", "385"]
MAU11_PERCENT_NUMBERS = ["24,49", "21,32", "19,05", "13,33", "12,88", "10,24"]
MAU11_REQUIRED_PAIRS = [
    ("tình trạng đi học", "657", "24,49", "hộ nghèo"),
    ("bảo hiểm y tế", "572", "21,32", "hộ nghèo"),
    ("dinh dưỡng", "511", "19,05", "hộ nghèo"),
    ("tình trạng đi học", "501", "13,33", "hộ cận nghèo"),
    ("bảo hiểm y tế", "484", "12,88", "hộ cận nghèo"),
    ("dinh dưỡng", "385", "10,24", "hộ cận nghèo"),
]

MAU12_REQUIRED_NUMBERS = [
    "2.447", "7.488", "32,68", "11.247", "34.110",
    "829", "1.917", "43,24", "538", "1.553", "34,64",
    "204", "598", "34,11", "1.044", "1.403", "703",
]

MAU2_REQUIRED_NUMBERS = ["1.796", "2.447", "651", "36,25", "634", "104", "0", "1.105", "161", "123"]
MAU3_REQUIRED_NUMBERS = ["3.402", "3.691", "289", "8,50", "134", "1.105", "0", "634", "440", "454"]
POOR_DEPRIVATION_TOP = [
    ("chất lượng nhà ở", "1.945", "79,49"),
    ("bảo hiểm xã hội", "1.876", "76,67"),
    ("nhà tiêu", "1.825", "74,58"),
]
NEAR_POOR_DEPRIVATION_TOP = [
    ("chất lượng nhà ở", "2.320", "62,86"),
    ("nhà tiêu", "2.059", "55,78"),
    ("bảo hiểm xã hội", "1.947", "52,75"),
]
MAU10_POOR_TOP = [
    ("thiếu vốn", "1.399", "57,17"),
    ("thiếu lao động", "1.197", "48,92"),
    ("ốm đau", "1.180", "48,22"),
]
MAU10_NEAR_TOP = [
    ("thiếu vốn", "1.419", "38,44"),
    ("ốm đau", "1.384", "37,50"),
    ("thiếu lao động", "1.218", "33,00"),
]


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _default_project_root() -> Path:
    return Path.cwd().resolve()


def _resolve_db_path(value: str | None) -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value))
    root = _default_project_root()
    candidates.extend([
        root / "db" / "poverty.db",
        root / "poverty.db",
        Path(__file__).resolve().parent / "db" / "poverty.db",
        Path(__file__).resolve().parent / "poverty.db",
        Path("/mnt/data/poverty.db"),
    ])
    for c in candidates:
        p = c.expanduser().resolve()
        if p.exists():
            return p
    raise FileNotFoundError("Không tìm thấy poverty.db. Truyền --db db/poverty.db")


def _load_writer_module(writer_path: str | None):
    """Load report_writer theo 3 cách:
    1) --writer-path trực tiếp.
    2) report.report_writer nếu chạy từ project root.
    3) report_writer nếu đặt script trong thư mục report.
    """
    if writer_path:
        path = Path(writer_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy writer-path: {path}")
        parent = str(path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        if str(path.parent.parent) not in sys.path:
            sys.path.insert(0, str(path.parent.parent))
        spec = importlib.util.spec_from_file_location("report_writer_eval_runtime", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Không load được module từ {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["report_writer_eval_runtime"] = mod
        spec.loader.exec_module(mod)
        return mod

    root = _default_project_root()
    for p in [root, root / "report", Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]:
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)

    errors: list[str] = []
    for name in ["report.report_writer", "report_writer"]:
        try:
            return importlib.import_module(name)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise ImportError("Không import được report_writer. Lỗi:\n" + "\n".join(errors))


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ỹ]+\b", text or "", flags=re.UNICODE))


def _normalize_for_similarity(text: str) -> str:
    raw = unicodedata.normalize("NFC", str(text or "").lower())
    raw = re.sub(r"\d+(?:[\.,]\d+)*%?", " <num> ", raw)
    raw = re.sub(r"[^0-9a-zA-ZÀ-ỹ%]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def normalized_text_similarity(a: str, b: str) -> float:
    aa = _normalize_for_similarity(a)
    bb = _normalize_for_similarity(b)
    if not aa or not bb:
        return 0.0
    return float(difflib.SequenceMatcher(None, aa, bb).ratio())


def _text_fingerprint(text: str) -> str:
    norm = _normalize_for_similarity(text)
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _normalize_text(text: str) -> str:
    return (text or "").replace("\xa0", " ").strip()


def _number_variants(num: Any) -> list[str]:
    """Tạo một số variant format 2447 <-> 2.447, 24.49 <-> 24,49."""
    if num is None:
        return []
    out: set[str] = set()
    if isinstance(num, bool):
        return []
    if isinstance(num, int):
        out.add(str(num))
        out.add(f"{num:,}".replace(",", "."))
    elif isinstance(num, float):
        out.add(str(num))
        out.add((f"{num:.2f}".replace(".", ",")).rstrip("0").rstrip(","))
        out.add((f"{num:.1f}".replace(".", ",")).rstrip("0").rstrip(","))
    else:
        s = str(num).strip()
        if s:
            out.add(s)
            if re.fullmatch(r"\d+", s):
                try:
                    n = int(s)
                    out.add(f"{n:,}".replace(",", "."))
                except Exception:
                    pass
            if re.fullmatch(r"\d+\.\d+", s):
                out.add(s.replace(".", ","))
    return sorted(out, key=len, reverse=True)


def _contains_number(text: str, wanted: str) -> bool:
    t = _normalize_text(text)
    variants = {wanted, wanted.replace(".", ""), wanted.replace(",", ".")}
    # Không ép mọi dấu chấm nghìn thành decimal, chỉ thêm variant cơ bản.
    for v in list(variants):
        if re.fullmatch(r"\d+", v or ""):
            try:
                variants.add(f"{int(v):,}".replace(",", "."))
            except Exception:
                pass
    return any(v and v in t for v in variants)


def _percent_value(token: str) -> float | None:
    raw = str(token or "").strip().replace("%", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None


def _contains_percent_value(text: str, wanted: str) -> bool:
    expected = _percent_value(wanted)
    if expected is None:
        return False
    for match in re.finditer(r"(?<!\d)\d+(?:[\.,]\d+)?\s*%?", _normalize_text(text)):
        actual = _percent_value(match.group(0))
        if actual is not None and abs(actual - expected) < 0.005:
            return True
    return False


def _claim_units(text: str) -> list[str]:
    return [u.strip() for u in re.split(r"(?<=[.!?])\s+|[\n;]+", _normalize_text(text)) if u.strip()]


def _contains_group_label_value(text: str, group: str, label: str, value: str, *, is_percent: bool = False) -> bool:
    group_l = group.lower()
    label_l = label.lower()
    for unit in _claim_units(text):
        low = unit.lower()
        if group_l not in low or label_l not in low:
            continue
        if is_percent:
            if _contains_percent_value(unit, value):
                return True
        elif _contains_number(unit, value):
            return True
    return False


def _jsonable(obj: Any, max_records: int = 1000) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if dataclasses.is_dataclass(obj):
        return _jsonable(dataclasses.asdict(obj), max_records=max_records)
    if pd is not None and isinstance(obj, pd.DataFrame):
        records = obj.head(max_records).to_dict(orient="records")
        numeric_totals: dict[str, Any] = {}
        for c in obj.columns:
            try:
                if pd.api.types.is_numeric_dtype(obj[c]):
                    v = obj[c].sum()
                    numeric_totals[str(c)] = int(v) if float(v).is_integer() else float(v)
            except Exception:
                pass
        return {
            "rows": int(len(obj)),
            "columns": [str(c) for c in obj.columns],
            "records": _jsonable(records, max_records=max_records),
            "records_limit": max_records,
            "records_truncated": len(obj) > max_records,
            "numeric_totals": numeric_totals,
        }
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, max_records=max_records) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v, max_records=max_records) for v in list(obj)]
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except Exception:
        return str(obj)


def _extract_template_id(bundle: Any, result_record: dict[str, Any]) -> int | None:
    tid = None
    try:
        tid = int(getattr(getattr(bundle, "template", None), "id"))
    except Exception:
        pass
    if tid is None:
        try:
            tid = int(result_record.get("report_pattern") or result_record.get("template_id"))
        except Exception:
            pass
    return tid


def _bundle_snapshot(bundle: Any, max_records: int = 1000) -> dict[str, Any]:
    template = getattr(bundle, "template", None)
    scope = getattr(bundle, "scope", None)
    facts = getattr(bundle, "facts", {}) or {}
    tables = getattr(bundle, "tables", {}) or {}
    return {
        "template": _jsonable(template, max_records=max_records),
        "scope": _jsonable(scope, max_records=max_records),
        "facts_keys": sorted(list(facts.keys())) if isinstance(facts, dict) else [],
        "facts": _jsonable(facts, max_records=max_records),
        "tables": _jsonable(tables, max_records=max_records),
    }


def _result_snapshot(result: Any) -> dict[str, Any]:
    rec = _jsonable(result)
    if not isinstance(rec, dict):
        rec = {"repr": str(result)}
    text = str(rec.get("text") or "")
    rec["word_count_eval"] = _word_count(text)
    rec["numbers_in_text_eval"] = re.findall(r"\d+(?:[\.,]\d+)*", text)
    rec.setdefault("final_text_fingerprint", _text_fingerprint(text))
    rec.setdefault("prompt_fingerprint", _text_fingerprint(str(rec.get("prompt") or "")))
    return rec


def _audit_summary(record: dict[str, Any]) -> dict[str, Any]:
    report = record.get("report") or {}
    audit = report.get("final_text_fact_audit") or {}
    summary = report.get("final_text_fact_audit_summary") or audit.get("summary") or {}
    rules = report.get("final_text_fact_audit_rules") or audit.get("rules") or []
    hard_warning_count = int(summary.get("hard_warning_count") or 0)
    rule_fail_count = int(summary.get("rule_fail_count") or 0)
    status = str(report.get("final_text_fact_audit_status") or audit.get("status") or "not_run")
    hard_rule_ids: list[str] = []
    for r in rules if isinstance(rules, list) else []:
        if isinstance(r, dict) and (r.get("hard_fail") or r.get("status") == "fail"):
            hard_rule_ids.append(str(r.get("rule_id") or r.get("name") or "unknown_rule"))
    return {
        "status": status,
        "hard_warning_count": hard_warning_count,
        "rule_fail_count": rule_fail_count,
        "hard_rule_ids": sorted(set(hard_rule_ids)),
    }


def _check_prompt_leak(text: str) -> list[str]:
    warnings: list[str] = []
    lower = text.lower()
    for pat in PROMPT_LEAK_PATTERNS:
        if re.search(pat, lower, flags=re.IGNORECASE):
            warnings.append(f"prompt_leak_or_chat_voice:{pat}")
    return warnings


def _eval_template_1(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    for pat in TEMPLATE1_FORBIDDEN_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            hard.append(f"mau1_forbidden_scope:{pat}")
    for n in ["2.447", "3.691"]:
        if not _contains_number(text, n):
            hard.append(f"mau1_missing_core_number:{n}")
    if not re.search(r"(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)[^.\n;]{0,90}\b0\s*hộ\b|\b0\s*hộ[^.\n;]{0,90}(nông|lâm|ngư|mức\s+sống\s+trung\s+bình)", text, flags=re.IGNORECASE):
        hard.append("mau1_missing_core_number:0_nlnn_mstb")
    # Nếu có viết địa bàn nổi bật thì nên có đủ nhóm top 3 chính.
    for n in ["829", "538", "279", "917", "588", "510"]:
        if not _contains_number(text, n):
            soft.append(f"mau1_missing_expected_top_context_number:{n}")
    return hard, soft


def _missing_numbers(prefix: str, text: str, numbers: list[str]) -> list[str]:
    return [f"{prefix}_missing_number:{n}" for n in numbers if not _contains_number(text, n)]


def _eval_template_2(text: str) -> tuple[list[str], list[str]]:
    hard = _missing_numbers("mau2", text, MAU2_REQUIRED_NUMBERS)
    soft: list[str] = []
    low = text.lower()
    if "chênh lệch chưa giải thích" in low or re.search(r"651[^.\n]*(chưa\s+rõ|chưa\s+giải\s+thích|không\s+giải\s+thích)", low):
        hard.append("mau2_unexplained_delta_zero_but_claimed")
    if re.search(r"(nhóm\s+giảm|cấu\s+phần\s+giảm|làm\s+giảm)[^.\n]*(tái\s+nghèo|mới\s+phát\s+sinh|cận\s+nghèo\s+trở\s+thành\s+hộ\s+nghèo)", low):
        hard.append("mau2_increase_component_written_as_decrease")
    if re.search(r"(nhóm\s+tăng|cấu\s+phần\s+tăng|làm\s+tăng)[^.\n]*(thoát\s+nghèo)", low):
        hard.append("mau2_decrease_component_written_as_increase")
    return hard, soft


def _eval_template_3(text: str) -> tuple[list[str], list[str]]:
    hard = _missing_numbers("mau3", text, MAU3_REQUIRED_NUMBERS)
    soft: list[str] = []
    low = text.lower()
    if re.search(r"giảm[^.\n]{0,40}(thành|còn)\s*3\.?691", low):
        hard.append("mau3_wrong_direction_giam_thanh_3691")
    if _contains_number(text, "5,76"):
        hard.append("mau3_forbidden_wrong_ratio:5,76")
    if "chênh lệch chưa giải thích" in low:
        hard.append("mau3_unexplained_delta_zero_but_claimed")
    if re.search(r"(nhóm\s+giảm|cấu\s+phần\s+giảm|làm\s+giảm)[^.\n]*(thoát\s+nghèo|tái\s+cận\s+nghèo|cận\s+nghèo\s+mới\s+phát\s+sinh)", low):
        hard.append("mau3_increase_component_written_as_decrease")
    if re.search(r"(nhóm\s+tăng|cấu\s+phần\s+tăng|làm\s+tăng)[^.\n]*(thoát\s+cận\s+nghèo|cận\s+nghèo\s+trở\s+thành\s+hộ\s+nghèo)", low):
        hard.append("mau3_decrease_component_written_as_increase")
    return hard, soft


def _eval_deprivation_template(text: str, template_id: int) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()
    if "mẫu này" in low:
        hard.append(f"mau{template_id}_mentions_template_wording")
    pairs = POOR_DEPRIVATION_TOP if template_id in {4, 5} else NEAR_POOR_DEPRIVATION_TOP
    for label, count, pct in pairs:
        if label not in low:
            hard.append(f"mau{template_id}_missing_top_label:{label}")
        if not _contains_number(text, count):
            hard.append(f"mau{template_id}_missing_top_count:{label}:{count}")
        if not _contains_percent_value(text, pct):
            hard.append(f"mau{template_id}_missing_top_ratio:{label}:{pct}")
    if any(phrase in low for phrase in ("không chồng lấn", "không được chồng lấn", "không có sự chồng lấn", "loại trừ nhau")):
        hard.append(f"mau{template_id}_wrong_overlap_exclusion")
    if template_id in {4, 6}:
        count_focus = (
            "số hộ thiếu" in low
            or "số hộ" in low and ("thiếu hụt" in low or "thiếu từng chỉ số" in low)
            or "quy mô hộ" in low
            or "hộ thiếu hụt" in low
        )
        if not count_focus:
            hard.append(f"mau{template_id}_missing_count_focus_language")
        count_values = r"(1\.945|1\.876|1\.825|2\.320|2\.059|1\.947)"
        ratio_values = r"(79,49|76,67|74,58|62,86|55,78|52,75)"
        wrong_count_as_ratio = re.search(
            rf"tỷ\s+lệ\s*(?:là|đạt|ghi\s+nhận|:)?\s*{count_values}\s*hộ\b",
            low,
        )
        wrong_ratio_as_households = re.search(rf"{ratio_values}\s*hộ\b", low) or re.search(r"%\s*hộ\b", low)
        if wrong_count_as_ratio or wrong_ratio_as_households:
            hard.append(f"mau{template_id}_count_called_ratio")
    if template_id in {5, 7}:
        ratio_focus = (
            "tỷ lệ thiếu hụt" in low
            or "mức phổ biến" in low
            or "tỷ lệ" in low and ("thiếu hụt" in low or "chỉ số" in low)
        )
        if not ratio_focus:
            hard.append(f"mau{template_id}_missing_ratio_focus_language")
        if re.search(r"(79,49|76,67|74,58|62,86|55,78|52,75)\s*hộ\b", low):
            hard.append(f"mau{template_id}_ratio_called_households")
        first_count = min([idx for idx in (low.find(n) for n in ("1.945", "1.876", "1.825", "2.320", "2.059", "1.947")) if idx >= 0] or [10**9])
        first_pct = min([idx for idx in (low.find(n) for n in ("79,49", "76,67", "74,58", "62,86", "55,78", "52,75")) if idx >= 0] or [10**9])
        if first_count < first_pct < 10**9:
            soft.append(f"mau{template_id}_count_appears_before_ratio_focus")
    if template_id == 7 and re.search(r"62,86\s*%?[^.\n]{0,80}thấp\s+hơn[^.\n]{0,80}52,75", low):
        hard.append("mau7_bad_numeric_comparison_62_86_lower_than_52_75")
    return hard, soft


def _eval_template_8(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()
    if "hộ nghèo" not in low or "hộ cận nghèo" not in low:
        hard.append("mau8_missing_poor_or_near_poor_group")
    required_terms = {
        "mau8_missing_dtts_group": ("dtts" in low or "dân tộc thiểu số" in low),
        "mau8_missing_no_labor_group": ("không có khả năng lao động" in low or "không khả năng lao động" in low),
        "mau8_missing_meritorious_group": ("có công" in low or "người có công" in low),
    }
    for err, ok in required_terms.items():
        if not ok:
            hard.append(err)
    forbidden_groups = [
        "chủ hộ nữ", "người khuyết tật", "người cao tuổi", "trẻ em dưới 6 tuổi",
        "trẻ em đang đi học", "đơn thân", "thương binh", "liệt sĩ",
    ]
    for term in forbidden_groups:
        if term in low:
            hard.append(f"mau8_forbidden_group_in_text:{term}")
    if "địa bàn" not in low and "huyện" not in low and "toàn tỉnh" not in low:
        hard.append("mau8_missing_district_based_interpretation")
    if re.search(r"tỷ\s*lệ[^.\n]{0,80}(dtts|không\s+có\s+khả\s+năng|có\s+công)", low):
        hard.append("mau8_ratio_used_as_main_fact")
    if any(phrase in low for phrase in ("không chồng lấn", "không trùng lặp", "loại trừ nhau")):
        hard.append("mau8_wrong_overlap_exclusion")
    return hard, soft


def _eval_template_9(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()
    has_dtts = "dtts" in low or "dân tộc thiểu số" in low
    if "kinh" not in low or not has_dtts:
        hard.append("mau9_missing_kinh_or_dtts_layer")
    if any(phrase in low for phrase in ("nguyên nhân", "do dân tộc", "vì dân tộc")):
        hard.append("mau9_unsupported_ethnicity_cause_claim")
    return hard, soft


def _eval_template_10(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()

    def group_block(group: str) -> str:
        other = "hộ cận nghèo" if group == "hộ nghèo" else "hộ nghèo"
        pat = rf"{re.escape(group)}(.+?)(?={re.escape(other)}|$)"
        matches = re.findall(pat, low, flags=re.S)
        return " ".join(matches) if matches else low

    for group, pairs in (("hộ nghèo", MAU10_POOR_TOP), ("hộ cận nghèo", MAU10_NEAR_TOP)):
        block = group_block(group)
        for label, count, pct in pairs:
            if label not in low:
                hard.append(f"mau10_missing_top_label:{label}")
            if not ((label in block and _contains_number(block, count)) or _contains_group_label_value(text, group, label, count)):
                hard.append(f"mau10_missing_top_count:{label}:{count}")
            if not ((label in block and _contains_percent_value(block, pct)) or _contains_group_label_value(text, group, label, pct, is_percent=True)):
                hard.append(f"mau10_missing_top_ratio:{label}:{pct}")
    for label, _, _ in MAU10_POOR_TOP + MAU10_NEAR_TOP:
        if label not in low:
            hard.append(f"mau10_missing_top_label:{label}")
    if re.search(r"hộ\s+nghèo[^.\n]*(thiếu\s+vốn)[^.\n]*(ốm\s+đau)[^.\n]*(thiếu\s+lao\s+động)", low):
        hard.append("mau10_wrong_poor_top_order_om_dau_before_thieu_lao_dong")
    if "duy nhất" in low and "nguyên nhân" in low and not re.search(r"không[^.\n]{0,80}(?:kết\s+luận|xác\s+định)?[^.\n]{0,80}nguyên\s+nhân[^.\n]{0,40}duy\s+nhất", low):
        hard.append("mau10_unsupported_unique_cause_claim")
    return hard, soft


def _eval_template_11(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()
    # Cấm biến số trẻ thành hộ.
    for n in MAU11_CHILD_COUNT_NUMBERS:
        if re.search(rf"\b{re.escape(n)}\s*hộ\b", low, flags=re.IGNORECASE):
            hard.append(f"mau11_child_count_written_as_households:{n}_ho")
    bad_patterns = [
        r"số\s+trẻ\s+thiếu\s+hộ\s+nghèo",
        r"số\s+trẻ\s+thiếu\s+hộ\s+cận\s+nghèo",
        r"tỷ\s*lệ\s+[^\.\n;]{0,40}\d{3}\s*trẻ",
        r"tỷ\s*lệ\s+hộ\s+nghèo\s+(?:là|đạt|ghi nhận)",
        r"tỷ\s*lệ\s+hộ\s+cận\s+nghèo\s+(?:là|đạt|ghi nhận)",
        r"thiếu\s+[^\.\n;]{0,30}\s+ghi\s+nhận\s+\d{3}\s+hộ",
    ]
    for pat in bad_patterns:
        if re.search(pat, low, flags=re.IGNORECASE):
            hard.append(f"mau11_bad_unit_or_semantics:{pat}")
    # Cần có đủ 6 cặp số trẻ + tỷ lệ. Nếu thiếu coi là hard vì mẫu 11 ít chỉ tiêu và cần đầy đủ.
    for label, count, pct, group in MAU11_REQUIRED_PAIRS:
        if not (_contains_number(text, count) and _contains_number(text, pct)):
            hard.append(f"mau11_missing_pair:{group}:{label}:{count}:{pct}")
    if "trẻ" not in low:
        hard.append("mau11_missing_child_unit_tre")
    return hard, soft


def _eval_template_12(text: str) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    low = text.lower()
    for n in MAU12_REQUIRED_NUMBERS:
        if not _contains_number(text, n):
            soft.append(f"mau12_missing_expected_context_number:{n}")
    for term in ["kinh", "dtts", "dtts tại chỗ"]:
        if term not in low:
            hard.append(f"mau12_missing_ethnicity_layer:{term}")
    if not ("rà soát" in low or "phân loại" in low):
        hard.append("mau12_missing_reviewed_classified_denominator_scope")
    if not ("tỷ lệ hộ nghèo trong nhóm dtts" in low or "tỷ lệ hộ nghèo trong nhóm dân tộc thiểu số" in low):
        hard.append("mau12_missing_poverty_rate_within_dtts")
    if not ("tỷ lệ hộ nghèo trong nhóm dtts tại chỗ" in low or "tỷ lệ hộ nghèo trong nhóm dân tộc thiểu số tại chỗ" in low):
        hard.append("mau12_missing_poverty_rate_within_local_dtts")
    if re.search(r"tỷ\s+trọng[^.\n]{0,80}(?:là|như|thành)[^.\n]{0,80}tỷ\s+lệ\s+hộ\s+nghèo", low):
        hard.append("mau12_dtts_share_called_poverty_rate")
    return hard, soft


def _main_table_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    bundle = record.get("bundle") or {}
    tables = bundle.get("tables") if isinstance(bundle, dict) else {}
    if not isinstance(tables, dict):
        return {}
    table = tables.get("template_main") or tables.get("main") or {}
    return table if isinstance(table, dict) else {}


def _eval_template_8_facts(record: dict[str, Any]) -> list[str]:
    hard: list[str] = []
    table = _main_table_snapshot(record)
    cols = set(str(c) for c in (table.get("columns") or []))
    required = {
        "huyen", "tong_ho_dan_cu", "so_ho_dtts", "tong_ho_ngheo", "tong_ho_can_ngheo",
        "ho_ngheo_dtts", "ho_can_ngheo_dtts", "ho_ngheo_khong_knld", "ho_can_ngheo_khong_knld",
        "ho_ngheo_co_cong", "ho_can_ngheo_co_cong",
    }
    missing = sorted(required - cols)
    for col in missing:
        hard.append(f"mau8_fact_missing_column:{col}")
    forbidden = {
        "chi_tieu", "nhom", "nhom_doi_tuong", "so_ho_ngheo", "so_ho_can_ngheo",
        "ty_le_ho_ngheo_%", "ty_le_ho_can_ngheo_%", "ty_le_%", "ty_le_pct",
    }
    for col in sorted(forbidden & cols):
        hard.append(f"mau8_fact_forbidden_old_or_ratio_column:{col}")
    if "huyen" not in cols:
        hard.append("mau8_fact_main_table_not_district_based")
    records = table.get("records") or []
    if isinstance(records, list):
        for row in records[:20]:
            if not isinstance(row, dict):
                continue
            label = str(row.get("chi_tieu") or row.get("nhom_doi_tuong") or row.get("nhom") or "").lower()
            for term in ("chủ hộ nữ", "khuyết tật", "người cao tuổi", "trẻ em", "đơn thân", "thương binh", "liệt sĩ"):
                if term in label:
                    hard.append(f"mau8_fact_forbidden_group:{term}")
    bundle = record.get("bundle") if isinstance(record, dict) else {}
    if isinstance(bundle, dict):
        metadata_parts = [
            bundle.get("template"),
            (bundle.get("facts") or {}).get("template_context") if isinstance(bundle.get("facts"), dict) else None,
            ((bundle.get("facts") or {}).get("table_insights") or {}).get("interpretation_notes")
            if isinstance(bundle.get("facts"), dict) and isinstance((bundle.get("facts") or {}).get("table_insights"), dict)
            else None,
        ]
        metadata_text = json.dumps(metadata_parts, ensure_ascii=False, default=str).lower()
        for term in ("chủ hộ nữ", "khuyết tật", "người cao tuổi", "trẻ em dưới 6", "trẻ em đang đi học", "đơn thân", "thương binh", "liệt sĩ"):
            if term in metadata_text:
                hard.append(f"mau8_metadata_forbidden_group:{term}")
    return hard


def _eval_template_12_facts(record: dict[str, Any]) -> list[str]:
    hard: list[str] = []
    table = _main_table_snapshot(record)
    cols = set(str(c) for c in (table.get("columns") or []))
    required = {
        "tong_ho_dtts", "tong_ho_dtts_tai_cho",
        "ty_le_ngheo_trong_dtts_%", "ty_le_ngheo_trong_dtts_tai_cho_%",
    }
    for col in sorted(required - cols):
        hard.append(f"mau12_fact_missing_column:{col}")
    records = table.get("records") or []
    if isinstance(records, list):
        for row in records:
            if not isinstance(row, dict) or str(row.get("huyen")) != "Tuy Đức":
                continue
            try:
                wrong_share = float(row.get("ty_le_dtts_trong_nhom_%"))
                right_w = float(row.get("ty_le_ngheo_trong_dtts_%"))
                right_x = float(row.get("ty_le_ngheo_trong_dtts_tai_cho_%"))
            except Exception:
                continue
            if abs(right_w - 44.27) > 0.1:
                hard.append(f"mau12_tuyduc_wrong_w_rate:{right_w}")
            if abs(right_x - 45.45) > 0.1:
                hard.append(f"mau12_tuyduc_wrong_x_rate:{right_x}")
            if abs(wrong_share - right_w) < 0.01:
                hard.append("mau12_w_reuses_dtts_share")
            break
    return hard


def evaluate_record(record: dict[str, Any], *, expected_min_words: int, strict_llm: bool = True) -> dict[str, Any]:
    report = record.get("report") or {}
    text = str(report.get("text") or "")
    template_id = int(record.get("template_id") or 0)
    used_llm = bool(report.get("used_llm"))
    final_validation_passed = bool(report.get("final_validation_passed"))
    fallback_used = bool(report.get("fallback_used"))
    final_source = str(report.get("final_source") or "")
    word_count = int(report.get("word_count") or _word_count(text))
    llm_min_words = int(report.get("llm_min_words") or expected_min_words)
    audit = _audit_summary(record)

    hard: list[str] = []
    soft: list[str] = []

    if strict_llm:
        if not used_llm:
            hard.append("strict_llm_not_used")
        if fallback_used:
            hard.append("strict_llm_fallback_used")
        if "fallback" in final_source and not final_source.startswith("llm"):
            hard.append(f"strict_llm_final_source_is_fallback:{final_source}")

    if word_count < llm_min_words:
        hard.append(f"min_words_fail:{word_count}<{llm_min_words}")

    if audit["status"] == "fail" or audit["hard_warning_count"] > 0 or audit["rule_fail_count"] > 0:
        hard.append(f"final_fact_audit_fail_or_hard_warning:{audit}")

    for leak in _check_prompt_leak(text):
        hard.append(leak)

    # Những dấu hiệu accepted sai.
    if final_validation_passed and word_count < llm_min_words:
        hard.append("accepted_but_under_min_words")
    if final_validation_passed and (audit["status"] == "fail" or audit["hard_warning_count"] > 0):
        hard.append("accepted_but_audit_failed_or_hard_warning")

    # Rule riêng từng mẫu.
    if template_id == 1:
        h, s = _eval_template_1(text)
        hard.extend(h); soft.extend(s)
    elif template_id == 2:
        h, s = _eval_template_2(text)
        hard.extend(h); soft.extend(s)
    elif template_id == 3:
        h, s = _eval_template_3(text)
        hard.extend(h); soft.extend(s)
    elif template_id in {4, 5, 6, 7}:
        h, s = _eval_deprivation_template(text, template_id)
        hard.extend(h); soft.extend(s)
    elif template_id == 8:
        h, s = _eval_template_8(text)
        hard.extend(h); soft.extend(s)
        hard.extend(_eval_template_8_facts(record))
    elif template_id == 9:
        h, s = _eval_template_9(text)
        hard.extend(h); soft.extend(s)
    elif template_id == 10:
        h, s = _eval_template_10(text)
        hard.extend(h); soft.extend(s)
    elif template_id == 11:
        h, s = _eval_template_11(text)
        hard.extend(h); soft.extend(s)
    elif template_id == 12:
        h, s = _eval_template_12(text)
        hard.extend(h); soft.extend(s)
        hard.extend(_eval_template_12_facts(record))

    # Kiểm nhanh attempts: dưới min mà accepted ở bất kỳ attempt nào cũng ghi lại.
    bad_attempts: list[str] = []
    attempts = report.get("llm_attempt_results") or []
    if isinstance(attempts, list):
        for a in attempts:
            if not isinstance(a, dict):
                continue
            awc = int(a.get("word_count") or _word_count(str(a.get("candidate_text") or a.get("raw_model_text") or "")))
            if a.get("accepted") and awc < llm_min_words:
                bad_attempts.append(f"attempt_{a.get('attempt')}_accepted_under_min:{awc}<{llm_min_words}")
    hard.extend(bad_attempts)

    status = "pass"
    if hard:
        status = "fail"
    elif soft or audit["status"] == "warn" or report.get("warnings"):
        status = "warn"

    if hard:
        conclusion = "FAIL: có lỗi cứng, không nên dùng làm bản đạt."
    elif status == "warn":
        conclusion = "WARN: số liệu có thể đúng nhưng cần người kiểm ngữ cảnh/chất lượng."
    else:
        conclusion = "PASS: chưa phát hiện lỗi cứng theo rule eval."

    return {
        "eval_status": status,
        "eval_hard_errors": sorted(set(hard)),
        "eval_soft_warnings": sorted(set(soft)),
        "eval_conclusion": conclusion,
        "word_count_eval": word_count,
        "llm_min_words_eval": llm_min_words,
        "final_fact_audit_eval": audit,
    }


def _make_record(
    *,
    template_id: int,
    run_index: int,
    total_runs: int,
    db_path: Path,
    year: int,
    huyen: str | None,
    started_at: str,
    elapsed_sec: float,
    bundle: Any | None,
    result: Any | None,
    error: str | None,
    traceback_text: str | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    result_rec = _result_snapshot(result) if result is not None else {}
    bundle_rec = _bundle_snapshot(bundle, max_records=args.max_table_records) if bundle is not None else {}
    template = bundle_rec.get("template") or {}
    if isinstance(template, dict):
        template_title = template.get("title")
        template_pattern = template.get("pattern")
    else:
        template_title = None
        template_pattern = None
    rec = {
        "log_schema": "report_eval_batch_36",
        "log_event_type": "report_eval_run",
        "eval_generated_at": datetime.now().isoformat(),
        "started_at": started_at,
        "elapsed_sec": round(elapsed_sec, 3),
        "template_id": template_id,
        "template_title": template_title,
        "template_pattern": template_pattern,
        "run_index": run_index,
        "runs_per_template": total_runs,
        "scope": {"year": year, "huyen": huyen},
        "config": {
            "db_path": str(db_path),
            "use_llm": bool(args.use_llm),
            "llm_min_words": int(args.llm_min_words),
            "llm_failure_policy": args.llm_failure_policy,
            "strict_llm_eval": bool(args.strict_llm_eval),
            "regenerate_nonce": int(template_id) * 100 + int(run_index),
            "require_distinct_llm_text": bool(getattr(args, "require_distinct_llm_text", False)),
        },
        "report": result_rec,
        "bundle": bundle_rec,
        "error": error,
        "traceback": traceback_text,
    }
    eval_rec = evaluate_record(rec, expected_min_words=args.llm_min_words, strict_llm=bool(args.strict_llm_eval and args.use_llm))
    rec["evaluation"] = eval_rec
    return rec


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _summary_row(record: dict[str, Any]) -> dict[str, Any]:
    report = record.get("report") or {}
    ev = record.get("evaluation") or {}
    return {
        "template_id": record.get("template_id"),
        "template_title": record.get("template_title") or "",
        "run_index": record.get("run_index"),
        "eval_status": ev.get("eval_status"),
        "final_validation_passed": report.get("final_validation_passed"),
        "used_llm": report.get("used_llm"),
        "fallback_used": report.get("fallback_used"),
        "final_source": report.get("final_source"),
        "word_count": report.get("word_count") or ev.get("word_count_eval"),
        "llm_min_words": report.get("llm_min_words") or ev.get("llm_min_words_eval"),
        "llm_attempt_count": report.get("llm_attempt_count"),
        "report_regenerate_nonce": report.get("report_regenerate_nonce"),
        "style_variant_id": report.get("style_variant_id"),
        "variation_profile_name": report.get("variation_profile_name"),
        "prompt_fingerprint": report.get("prompt_fingerprint"),
        "safe_base_fingerprint": report.get("safe_base_fingerprint"),
        "final_text_fingerprint": report.get("final_text_fingerprint"),
        "similarity_to_fallback": report.get("similarity_to_fallback"),
        "repair_changed_text": report.get("repair_changed_text"),
        "final_text_fact_audit_status": report.get("final_text_fact_audit_status"),
        "hard_errors": "; ".join(ev.get("eval_hard_errors") or []),
        "soft_warnings": "; ".join(ev.get("eval_soft_warnings") or []),
        "text_preview": str(report.get("text") or "")[:240].replace("\n", " "),
    }


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_md(path: Path, records: list[dict[str, Any]], output_jsonl: Path, failures_jsonl: Path, csv_path: Path) -> None:
    total = len(records)
    counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
    by_template: dict[int, dict[str, int]] = {}
    for r in records:
        st = ((r.get("evaluation") or {}).get("eval_status") or "fail")
        counts[st] = counts.get(st, 0) + 1
        tid = int(r.get("template_id") or 0)
        by_template.setdefault(tid, {"pass": 0, "warn": 0, "fail": 0})
        by_template[tid][st] = by_template[tid].get(st, 0) + 1

    lines = []
    lines.append("# Report evaluation summary")
    lines.append("")
    lines.append(f"- Tổng lượt chạy: **{total}**")
    lines.append(f"- PASS: **{counts.get('pass', 0)}**")
    lines.append(f"- WARN: **{counts.get('warn', 0)}**")
    lines.append(f"- FAIL: **{counts.get('fail', 0)}**")
    lines.append("")
    lines.append("## File output")
    lines.append(f"- JSONL đầy đủ: `{output_jsonl}`")
    lines.append(f"- CSV tóm tắt: `{csv_path}`")
    lines.append(f"- JSONL lỗi: `{failures_jsonl}`")
    lines.append("")
    lines.append("## Theo mẫu")
    lines.append("")
    lines.append("| Mẫu | PASS | WARN | FAIL |")
    lines.append("|---:|---:|---:|---:|")
    for tid in sorted(by_template):
        c = by_template[tid]
        lines.append(f"| {tid} | {c.get('pass', 0)} | {c.get('warn', 0)} | {c.get('fail', 0)} |")
    lines.append("")
    batch_stats = records[0].get("batch_similarity_summary") if records else {}
    if isinstance(batch_stats, dict) and batch_stats:
        lines.append("## Similarity / distinctness")
        lines.append("")
        lines.append(f"- Similarity final-vs-fallback trung bình: **{batch_stats.get('similarity_to_fallback_avg')}**")
        lines.append(f"- Similarity final-vs-fallback cao nhất: **{batch_stats.get('similarity_to_fallback_max')}**")
        lines.append(f"- Nhóm duplicate exact trong cùng mẫu: **{batch_stats.get('same_template_exact_duplicate_groups')}**")
        lines.append(f"- Duplicate exact khác mẫu: **{batch_stats.get('different_template_exact_duplicates')}**")
        high_pairs = batch_stats.get("high_similarity_pairs") or []
        if high_pairs:
            lines.append(f"- Cặp khác mẫu similarity > 0.92: **{len(high_pairs)}**")
        else:
            lines.append("- Cặp khác mẫu similarity > 0.92: **0**")
        lines.append("")
    lines.append("## Các lỗi cứng cần xem trước")
    lines.append("")
    fail_records = [r for r in records if (r.get("evaluation") or {}).get("eval_status") == "fail"]
    if not fail_records:
        lines.append("Không có lỗi cứng theo rule eval.")
    else:
        for r in fail_records[:50]:
            ev = r.get("evaluation") or {}
            report = r.get("report") or {}
            lines.append(f"- Mẫu {r.get('template_id')} lần {r.get('run_index')}: {', '.join(ev.get('eval_hard_errors') or [])}")
            preview = str(report.get("text") or "")[:220].replace("\n", " ")
            if preview:
                lines.append(f"  - Preview: {preview}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _refresh_eval_status(record: dict[str, Any]) -> None:
    ev = record.setdefault("evaluation", {})
    hard = sorted(set(ev.get("eval_hard_errors") or []))
    soft = sorted(set(ev.get("eval_soft_warnings") or []))
    ev["eval_hard_errors"] = hard
    ev["eval_soft_warnings"] = soft
    if hard:
        ev["eval_status"] = "fail"
        ev["eval_conclusion"] = "FAIL: có lỗi cứng, không nên dùng làm bản đạt."
    elif soft or ev.get("eval_status") == "warn":
        ev["eval_status"] = "warn"
        ev["eval_conclusion"] = "WARN: số liệu có thể đúng nhưng cần người kiểm ngữ cảnh/chất lượng."
    else:
        ev["eval_status"] = "pass"
        ev["eval_conclusion"] = "PASS: chưa phát hiện lỗi cứng theo rule eval."


def _add_eval_issue(record: dict[str, Any], *, hard: str | None = None, soft: str | None = None) -> None:
    ev = record.setdefault("evaluation", {})
    if hard:
        items = list(ev.get("eval_hard_errors") or [])
        items.append(hard)
        ev["eval_hard_errors"] = items
    if soft:
        items = list(ev.get("eval_soft_warnings") or [])
        items.append(soft)
        ev["eval_soft_warnings"] = items
    _refresh_eval_status(record)


def _record_text(record: dict[str, Any]) -> str:
    return str(((record.get("report") or {}).get("text") or "")).strip()


def _apply_batch_similarity_guards(records: list[dict[str, Any]], *, require_distinct_llm_text: bool = False) -> dict[str, Any]:
    texts = {i: _record_text(r) for i, r in enumerate(records)}
    norms = {i: _normalize_for_similarity(t) for i, t in texts.items() if t}
    fps = {i: _text_fingerprint(t) for i, t in texts.items() if t}
    stats: dict[str, Any] = {
        "same_template_exact_duplicate_groups": 0,
        "different_template_exact_duplicates": 0,
        "high_similarity_pairs": [],
        "similarity_to_fallback_max": 0.0,
        "similarity_to_fallback_avg": 0.0,
    }

    by_template: dict[int, dict[str, list[int]]] = {}
    for i, rec in enumerate(records):
        tid = int(rec.get("template_id") or 0)
        fp = fps.get(i)
        if not fp:
            continue
        by_template.setdefault(tid, {}).setdefault(fp, []).append(i)
    for tid, groups in by_template.items():
        for fp, idxs in groups.items():
            if len(idxs) <= 1:
                continue
            stats["same_template_exact_duplicate_groups"] += 1
            msg = f"same_template_exact_duplicate:template={tid}:fingerprint={fp}:runs={[records[j].get('run_index') for j in idxs]}"
            for j in idxs:
                if require_distinct_llm_text:
                    _add_eval_issue(records[j], hard=msg)
                else:
                    _add_eval_issue(records[j], soft=msg)

    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            if not texts.get(i) or not texts.get(j):
                continue
            ti = int(records[i].get("template_id") or 0)
            tj = int(records[j].get("template_id") or 0)
            if ti == tj:
                continue
            if fps.get(i) and fps.get(i) == fps.get(j):
                stats["different_template_exact_duplicates"] += 1
                msg = f"different_template_exact_duplicate:{ti}={tj}:fingerprint={fps[i]}"
                _add_eval_issue(records[i], hard=msg)
                _add_eval_issue(records[j], hard=msg)
                continue
            pair_key = {ti, tj}
            if pair_key in ({4, 5}, {6, 7}):
                sim = normalized_text_similarity(texts[i], texts[j])
                pair_meta = {
                    "template_a": ti,
                    "run_a": records[i].get("run_index"),
                    "template_b": tj,
                    "run_b": records[j].get("run_index"),
                    "similarity": round(sim, 4),
                }
                if sim > 0.92:
                    stats["high_similarity_pairs"].append(pair_meta)
                    msg = f"high_similarity_between_templates:{ti}_{tj}:{sim:.3f}"
                    _add_eval_issue(records[i], soft=msg)
                    _add_eval_issue(records[j], soft=msg)
                if sim >= 0.999:
                    msg = f"near_exact_duplicate_between_templates:{ti}_{tj}:{sim:.3f}"
                    _add_eval_issue(records[i], hard=msg)
                    _add_eval_issue(records[j], hard=msg)

    fallback_sims: list[float] = []
    for rec in records:
        report = rec.get("report") or {}
        try:
            sim = float(report.get("similarity_to_fallback") or 0.0)
        except Exception:
            sim = 0.0
        if sim:
            fallback_sims.append(sim)
        if sim > 0.92:
            _add_eval_issue(rec, soft=f"similarity_to_fallback_high:{sim:.3f}")
    if fallback_sims:
        stats["similarity_to_fallback_max"] = round(max(fallback_sims), 4)
        stats["similarity_to_fallback_avg"] = round(sum(fallback_sims) / len(fallback_sims), 4)
    for rec in records:
        rec["batch_similarity_summary"] = stats
    return stats


def run_batch(args: argparse.Namespace) -> dict[str, Path]:
    db_path = _resolve_db_path(args.db)
    writer = _load_writer_module(args.writer_path)
    if not hasattr(writer, "build_report_bundle") or not hasattr(writer, "generate_report_text"):
        raise RuntimeError("report_writer không có build_report_bundle/generate_report_text")

    stamp = _now_stamp()
    out_dir = Path(args.output_dir or (Path.cwd() / "logs" / "report_eval")).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_jsonl = out_dir / f"report_eval_{stamp}.jsonl"
    failures_jsonl = out_dir / f"report_eval_{stamp}_failures.jsonl"
    summary_csv = out_dir / f"report_eval_{stamp}_summary.csv"
    summary_md = out_dir / f"report_eval_{stamp}_summary.md"
    failures_jsonl.touch()

    all_records: list[dict[str, Any]] = []
    template_ids = [int(x) for x in args.templates]

    for tid in template_ids:
        for run_index in range(1, int(args.runs_per_template) + 1):
            started = datetime.now().isoformat()
            t0 = time.time()
            bundle = None
            result = None
            error = None
            tb = None
            try:
                bundle = writer.build_report_bundle(tid, db_path=db_path, year=args.year, huyen=args.huyen)
                regenerate_nonce = int(tid) * 100 + int(run_index)
                result = writer.generate_report_text(
                    report_type=tid,
                    template_id=tid,
                    db_path=db_path,
                    year=args.year,
                    huyen=args.huyen,
                    facts_bundle=bundle,
                    use_llm=bool(args.use_llm),
                    generation_mode="llm" if args.use_llm else "no_llm",
                    llm_failure_policy=args.llm_failure_policy,
                    regenerate_nonce=regenerate_nonce,
                    llm_min_words=int(args.llm_min_words),
                )
            except Exception as exc:
                error = str(exc)
                tb = traceback.format_exc()
            elapsed = time.time() - t0
            rec = _make_record(
                template_id=tid,
                run_index=run_index,
                total_runs=int(args.runs_per_template),
                db_path=db_path,
                year=int(args.year),
                huyen=args.huyen,
                started_at=started,
                elapsed_sec=elapsed,
                bundle=bundle,
                result=result,
                error=error,
                traceback_text=tb,
                args=args,
            )
            if error:
                rec["evaluation"]["eval_status"] = "fail"
                rec["evaluation"].setdefault("eval_hard_errors", []).append("generation_exception")
                rec["evaluation"]["eval_conclusion"] = "FAIL: exception khi sinh report."
            all_records.append(rec)
            print(
                f"[generated template {tid:02d} run {run_index}/{args.runs_per_template}] "
                f"words={(rec.get('evaluation') or {}).get('word_count_eval')} | "
                f"source={(rec.get('report') or {}).get('final_source')}"
            )
            if args.sleep_sec:
                time.sleep(float(args.sleep_sec))

    similarity_stats = _apply_batch_similarity_guards(
        all_records,
        require_distinct_llm_text=bool(args.require_distinct_llm_text),
    )
    for rec in all_records:
        _write_jsonl(output_jsonl, rec)
        if (rec.get("evaluation") or {}).get("eval_status") == "fail":
            _write_jsonl(failures_jsonl, rec)
        print(
            f"[template {int(rec.get('template_id') or 0):02d} run {rec.get('run_index')}/{args.runs_per_template}] "
            f"{(rec.get('evaluation') or {}).get('eval_status')} | "
            f"words={(rec.get('evaluation') or {}).get('word_count_eval')} | "
            f"source={(rec.get('report') or {}).get('final_source')}"
        )
    print(
        "Batch similarity: "
        f"fallback_avg={similarity_stats.get('similarity_to_fallback_avg')} | "
        f"fallback_max={similarity_stats.get('similarity_to_fallback_max')} | "
        f"same_template_duplicates={similarity_stats.get('same_template_exact_duplicate_groups')} | "
        f"different_template_duplicates={similarity_stats.get('different_template_exact_duplicates')}"
    )

    rows = [_summary_row(r) for r in all_records]
    _write_summary_csv(summary_csv, rows)
    _write_summary_md(summary_md, all_records, output_jsonl, failures_jsonl, summary_csv)
    return {
        "jsonl": output_jsonl,
        "failures_jsonl": failures_jsonl,
        "summary_csv": summary_csv,
        "summary_md": summary_md,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chạy evaluation 12 mẫu report x 3 lần/mẫu và ghi log JSONL.")
    p.add_argument("--db", default=None, help="Đường dẫn poverty.db. Mặc định tự tìm db/poverty.db.")
    p.add_argument("--writer-path", default=None, help="Đường dẫn report_writer.py muốn test. Không truyền thì import report.report_writer.")
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--huyen", default=None)
    p.add_argument("--runs-per-template", type=int, default=3)
    p.add_argument("--templates", nargs="+", type=int, default=TEMPLATE_IDS, help="Danh sách mẫu cần chạy. Mặc định 1..12.")
    p.add_argument("--llm-min-words", type=int, default=180)
    p.add_argument("--use-llm", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--strict-llm-eval", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--llm-failure-policy", default="no_fallback", choices=["no_fallback", "fallback"])
    p.add_argument("--output-dir", default=None, help="Thư mục output. Mặc định logs/report_eval.")
    p.add_argument("--max-table-records", type=int, default=1000)
    p.add_argument("--sleep-sec", type=float, default=0.0, help="Nghỉ giữa các lượt gọi LLM nếu cần.")
    p.add_argument("--require-distinct-llm-text", action="store_true", help="FAIL nếu các run cùng mẫu tạo văn bản LLM trùng exact sau normalize.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run_batch(args)
    print("\nDONE. Output files:")
    for k, v in paths.items():
        print(f"- {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
