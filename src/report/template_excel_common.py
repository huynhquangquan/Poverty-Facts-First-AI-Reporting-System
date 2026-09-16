"""
report/template_excel_common.py

Hàm phụ dùng chung cho exporter Excel hành chính.
File này không chứa logic riêng mẫu 1, không gọi LLM và không truy vấn DB.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "report"
DATA_SAMPLES_DIR = PROJECT_ROOT / "data" / "report_samples"
LOG_DIR = PROJECT_ROOT / "logs"


def relative_or_str(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def short_text(value: Any, max_len: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def vn_key(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("đ", "d")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_template_sample_path(template_id: int, samples_dir: Path | None = None) -> Path | None:
    """Tìm file template Excel theo số mẫu.

    Ưu tiên data/report_samples, sau đó thư mục project. Bắt tên kiểu:
    "1. ...xlsx", "mau_1...xlsx", "mẫu 1...xlsx".
    """
    roots: list[Path] = []
    if samples_dir:
        roots.append(samples_dir)
    roots.extend([DATA_SAMPLES_DIR, PROJECT_ROOT])

    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        try:
            if not root.exists():
                continue
            for path in root.glob("*.xlsx"):
                if path in seen:
                    continue
                seen.add(path)
                name = path.name.lower()
                if name.startswith(f"{template_id}.") or re.search(rf"(?:mau|mẫu)[_\s-]*{template_id}\b", name):
                    candidates.append(path)
        except Exception:
            continue
    if candidates:
        return sorted(candidates, key=lambda p: (len(str(p)), str(p)))[0]
    return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Lấy một JSON object từ output LLM.

    Qwen đôi khi bọc JSON trong markdown hoặc sinh trailing comma/comment.
    Hàm này chỉ cleanup nhẹ và chỉ trả dict nếu parse được JSON hợp lệ.
    """
    raw = re.sub(r"```(?:json)?|```", "", str(text or "")).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    candidate = match.group(0).strip()
    candidate = re.sub(r"(?m)^\s*//.*$", "", candidate)
    candidate = re.sub(r"(?m)([,\[{]\s*)//.*$", r"\1", candidate)
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# Alias giữ tên cũ để các đoạn code refactor không phải đổi nhiều.
_relative_or_str = relative_or_str
_short_text = short_text
_vn_key = vn_key
_find_template_sample_path = find_template_sample_path
_extract_json_object = extract_json_object
