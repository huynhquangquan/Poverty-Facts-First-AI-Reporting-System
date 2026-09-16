"""
report/report_logger.py

Ghi log JSONL cho luồng báo cáo hành chính/Excel LLM.
Bổ sung generation_mode và debug planner bảng/biểu đồ; không ảnh hưởng Excel.
Tách khỏi app.py để UI không phải tự xử lý đường dẫn log.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"


def write_jsonl_log(file_prefix: str, payload: dict[str, Any]) -> str | None:
    """Ghi một dòng JSONL vào logs/<prefix>_YYYYMMDD.jsonl."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{file_prefix}_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except Exception:
            return str(path)
    except Exception:
        return None


def write_report_task_log(state: dict[str, Any]) -> str | None:
    """Ghi log cho một lần sinh báo cáo hành chính tuần 4+5."""
    try:
        bundle = state["bundle"]
        report = state["report"]
        payload = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "log_event_type": state.get("mode_name"),
            "generation_mode": state.get("generation_mode"),
            "generation_mode_label": state.get("generation_mode_label"),
            "text_source": state.get("text_source"),
            "template_id": state.get("template_id"),
            "template": getattr(bundle, "template", {}),
            "scope": getattr(bundle, "scope", {}),
            "filters": state.get("filters"),
            "table_planner": state.get("table_plan_debug"),
            "chart_planner": state.get("chart_plan_debug"),
            "agency_meta": state.get("agency_meta"),
            "report_text": getattr(report, "text", ""),
            "report_pattern": getattr(report, "report_pattern", None),
            "report_warnings": getattr(report, "warnings", []),
            "used_llm": bool(getattr(report, "used_llm", False)),
            "fallback_used": bool(getattr(report, "fallback_used", False)),
            "final_source": getattr(report, "final_source", None),
            "report_generation_mode": getattr(report, "generation_mode", state.get("generation_mode")),
            "llm_failure_policy": getattr(report, "llm_failure_policy", None),
            "llm_failed": bool(getattr(report, "llm_failed", False)),
            "llm_failure_message": getattr(report, "llm_failure_message", ""),
            "final_validation_passed": bool(getattr(report, "final_validation_passed", False)),
            "validation_warnings": getattr(report, "validation_warnings", []),
            "final_validation_warnings": getattr(report, "final_validation_warnings", []),
            "raw_llm_warnings": getattr(report, "raw_llm_warnings", []),
            "raw_llm_rejected_reasons": getattr(report, "raw_llm_rejected_reasons", []),
            "repair_validation_warnings": getattr(report, "repair_validation_warnings", []),
            "llm_rewrite_attempted": bool(getattr(report, "llm_rewrite_attempted", False)),
            "llm_rewrite_success": bool(getattr(report, "llm_rewrite_success", False)),
            "llm_rewrite_validation_passed": bool(getattr(report, "llm_rewrite_validation_passed", False)),
            "rewrite_retry_attempted": bool(getattr(report, "rewrite_retry_attempted", False)),
            "report_regenerate_nonce": getattr(report, "report_regenerate_nonce", None),
            "word_count": len(str(getattr(report, "text", "") or "").split()),
            "raw_llm_text": getattr(report, "raw_llm_text", ""),
            "status_messages": getattr(report, "status_messages", []),
            "report_facts_keys": sorted(list((getattr(report, "report_facts", {}) or {}).keys())) if isinstance(getattr(report, "report_facts", None), dict) else [],
            "table_insights": (getattr(report, "report_facts", {}) or {}).get("facts", {}).get("table_insights") if isinstance(getattr(report, "report_facts", None), dict) else None,
            "chart_insights": (getattr(report, "report_facts", {}) or {}).get("facts", {}).get("chart_insights") if isinstance(getattr(report, "report_facts", None), dict) else None,
            "chart_error": state.get("chart_error"),
        }
        return write_jsonl_log("report_task", payload)
    except Exception:
        return None
