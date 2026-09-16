from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json

try:
    from .report_pattern_catalog import list_report_templates
except Exception:  # pragma: no cover
    from report_pattern_catalog import list_report_templates  # type: ignore


@dataclass
class ReportStyleProfile:
    """Profile văn phong/pattern dùng cho tuần 4.

    Tuần 4 không train model thật. File này đọc các biểu mẫu hiện có, ghi nhận metadata,
    sau đó sinh style profile có kiểm soát để report_writer dùng làm quy tắc văn phong.
    """

    source_dir: str
    output_path: str
    source_files: list[str] = field(default_factory=list)
    templates: list[dict[str, Any]] = field(default_factory=list)
    style_rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_STYLE_RULES = [
    "Văn phong hành chính, trung tính, không cảm tính.",
    "Mỗi nhận định có số liệu phải đối chiếu được với report_facts.",
    "Không tự thêm số liệu, tỷ lệ, địa bàn hoặc kết luận không có trong dữ liệu.",
    "Ưu tiên cấu trúc: Khái quát số liệu → Nhận xét nổi bật → Định hướng quản lý.",
    "Dùng đơn vị thống nhất: hộ, nhân khẩu, phần trăm.",
    "Không để token kỹ thuật như DataFrame, Series, NaN, dtype xuất hiện trong văn bản.",
    "Có thể dùng trực tiếp trong báo cáo Word/Excel tuần 5.",
]


def _templates_for_sources(source_files: list[str]) -> list[dict[str, Any]]:
    found = set(source_files)
    return [template for template in list_report_templates() if template.get("source_file") in found]


def _portable_profile_path(path: Path, project_root: Path | None) -> str:
    """Return a stable project-relative path for profile metadata when possible.

    The profile still reads/writes using the real absolute Path objects above; this
    helper only controls what is stored in report_style_profile.json so the file is
    portable between machines/folders.
    """
    try:
        if project_root is not None:
            return str(path.resolve().relative_to(project_root.resolve())).replace('\\', '/')
    except Exception:
        pass
    return str(path).replace('\\', '/')


def _infer_project_root(samples: Path, out: Path) -> Path | None:
    """Infer project root from the standard report/profile layout."""
    candidates: list[Path] = []
    try:
        # Typical: <project>/report/report_style_profile.json
        if out.parent.name == 'report':
            candidates.append(out.parent.parent)
    except Exception:
        pass
    try:
        # Typical: <project>/data/report_samples
        if samples.name == 'report_samples' and samples.parent.name == 'data':
            candidates.append(samples.parent.parent)
    except Exception:
        pass

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def train_style_profile(samples_dir: str | Path, output_path: str | Path) -> ReportStyleProfile:
    samples = Path(samples_dir)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    source_files: list[str] = []
    warnings: list[str] = []
    if samples.exists():
        for p in sorted(samples.iterdir(), key=lambda x: x.name):
            if p.suffix.lower() in {".xlsx", ".xlsm", ".xls", ".md", ".txt", ".docx", ".pdf"}:
                source_files.append(p.name)
    else:
        warnings.append(f"Không thấy thư mục mẫu: {samples}")

    templates = _templates_for_sources(source_files)

    project_root = _infer_project_root(samples, out)

    profile = ReportStyleProfile(
        source_dir=_portable_profile_path(samples, project_root),
        output_path=_portable_profile_path(out, project_root),
        source_files=source_files,
        templates=templates,
        style_rules=DEFAULT_STYLE_RULES,
        warnings=warnings,
    )
    out.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def load_style_profile(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"style_rules": DEFAULT_STYLE_RULES, "templates": list_report_templates(), "warnings": [f"Không thấy profile: {p}"]}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"style_rules": DEFAULT_STYLE_RULES, "templates": list_report_templates(), "warnings": [f"Không đọc được profile: {exc}"]}
