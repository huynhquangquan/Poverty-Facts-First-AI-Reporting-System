"""
run_data_pipeline.py
--------------------
Chạy toàn bộ data pipeline theo đúng thứ tự:

1. processing_data.py
2. feature_engineering.py
3. build_db.py
4. validate_db.py

Cách dùng:
    python run_data_pipeline.py

Tùy chọn:
    python run_data_pipeline.py --skip-processing
    python run_data_pipeline.py --skip-feature-engineering
    python run_data_pipeline.py --skip-build-db
    python run_data_pipeline.py --skip-validation
    python run_data_pipeline.py --continue-on-error

Đặt file này cùng thư mục với processing_data.py, feature_engineering.py,
build_db.py và validate_db.py.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineStep:
    name: str
    script_name: str
    skip_arg: str


PIPELINE_STEPS = [
    PipelineStep("1. Clean raw data", "processing_data.py", "skip_processing"),
    PipelineStep("2. Feature engineering", "feature_engineering.py", "skip_feature_engineering"),
    PipelineStep("3. Build SQLite DB", "build_db.py", "skip_build_db"),
    PipelineStep("4. Validate DB", "validate_db.py", "skip_validation"),
]


def _force_utf8_stdio() -> None:
    """Keep Vietnamese progress messages from crashing on Windows terminals."""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _pipeline_env() -> dict[str, str]:
    env = os.environ.copy()
    # Override instead of setdefault: parent shells often carry cp1252 settings on Windows.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _format_seconds(seconds: float) -> str:
    seconds = int(round(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _run_step(step: PipelineStep, *, project_dir: Path, python_exe: str) -> int:
    script_path = project_dir / step.script_name
    if not script_path.exists():
        print(f"\n[ERROR] Không tìm thấy script: {script_path}", flush=True)
        return 2

    print("\n" + "=" * 72, flush=True)
    print(f"[RUN] {step.name}: {step.script_name}", flush=True)
    print("=" * 72, flush=True)

    started = time.time()
    completed = subprocess.run(
        [python_exe, str(script_path)],
        cwd=str(project_dir),
        env=_pipeline_env(),
        text=True,
    )
    elapsed = _format_seconds(time.time() - started)

    if completed.returncode == 0:
        print(f"\n[OK] {step.script_name} hoàn tất trong {elapsed}.", flush=True)
    else:
        print(
            f"\n[FAIL] {step.script_name} lỗi với exit code {completed.returncode} "
            f"sau {elapsed}.",
            flush=True,
        )
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chạy data pipeline: processing_data -> feature_engineering -> build_db -> validate_db."
    )
    parser.add_argument(
        "--project-dir",
        default=str(Path(__file__).resolve().parent),
        help="Thư mục chứa các file pipeline. Mặc định là thư mục chứa script này.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable dùng để chạy các bước. Mặc định là Python hiện tại.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Tiếp tục chạy bước sau dù bước trước lỗi. Mặc định: dừng ngay khi lỗi.",
    )
    parser.add_argument("--skip-processing", action="store_true", help="Bỏ qua processing_data.py.")
    parser.add_argument("--skip-feature-engineering", action="store_true", help="Bỏ qua feature_engineering.py.")
    parser.add_argument("--skip-build-db", action="store_true", help="Bỏ qua build_db.py.")
    parser.add_argument("--skip-validation", action="store_true", help="Bỏ qua validate_db.py.")
    return parser.parse_args()


def main() -> int:
    _force_utf8_stdio()
    args = parse_args()
    project_dir = Path(args.project_dir).resolve()
    python_exe = str(args.python)

    print("=" * 72, flush=True)
    print("DATA PIPELINE RUNNER", flush=True)
    print("=" * 72, flush=True)
    print(f"Project dir : {project_dir}", flush=True)
    print(f"Python      : {python_exe}", flush=True)
    print(f"Stop on err : {not args.continue_on_error}", flush=True)

    if not project_dir.exists():
        print(f"\n[ERROR] Project dir không tồn tại: {project_dir}", flush=True)
        return 2

    started_all = time.time()
    failed_steps: list[tuple[str, int]] = []

    for step in PIPELINE_STEPS:
        should_skip = bool(getattr(args, step.skip_arg))
        if should_skip:
            print(f"\n[SKIP] {step.name}: {step.script_name}", flush=True)
            continue

        return_code = _run_step(step, project_dir=project_dir, python_exe=python_exe)
        if return_code != 0:
            failed_steps.append((step.script_name, return_code))
            if not args.continue_on_error:
                break

    total_elapsed = _format_seconds(time.time() - started_all)
    print("\n" + "=" * 72, flush=True)
    print("PIPELINE SUMMARY", flush=True)
    print("=" * 72, flush=True)

    if failed_steps:
        print(f"[FAIL] Pipeline có lỗi sau {total_elapsed}.", flush=True)
        for script_name, code in failed_steps:
            print(f"  - {script_name}: exit code {code}", flush=True)
        return 1

    print(f"[DONE] Pipeline hoàn tất thành công trong {total_elapsed}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
