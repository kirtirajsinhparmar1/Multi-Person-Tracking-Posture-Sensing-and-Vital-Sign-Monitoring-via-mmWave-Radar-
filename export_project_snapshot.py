"""Export a readable project snapshot for sharing/debugging."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


INCLUDE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".cfg",
    ".toml",
    ".yml",
    ".yaml",
}

EXCLUDE_DIRS = {
    "__pycache__",
    ".venv",
    ".venv_ti_ui",
    "venv",
    "env",
    "logs",
    "dataset",
    "outputs",
    "cache",
    "snapshots",
    "ti_style_vendor",
}

SELECTED_VENDOR_FILES = [
    Path("ti_style_vendor/common/Common_Tabs/plot_3d.py"),
    Path("ti_style_vendor/common/Common_Tabs/gl_text.py"),
    Path("ti_style_vendor/common/gl_text.py"),
    Path("ti_style_vendor/common/Demo_Classes/people_tracking.py"),
    Path("ti_style_vendor/common/parseFrame.py"),
    Path("ti_style_vendor/common/parseTLVs.py"),
    Path("ti_style_vendor/common/tlv_defines.py"),
    Path("ti_style_vendor/PySide2/__init__.py"),
    Path("ti_style_vendor/PySide2/QtCore.py"),
    Path("ti_style_vendor/PySide2/QtGui.py"),
    Path("ti_style_vendor/PySide2/QtWidgets.py"),
]

SELECTED_MODEL_FILES = [
    Path("model_experiments/train_or_export_ti_pose_model.py"),
    Path("model_experiments/ti_pose_feature_extractor.py"),
    Path("model_experiments/TI_POSE_MODEL_REUSE_REPORT.md"),
    Path("model_experiments/README_MODEL.md"),
]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = out_dir / f"project_snapshot_{timestamp}.txt"
    max_bytes = max(1, args.max_file_kb) * 1024

    files = collect_files(root, include_vendor=args.include_vendor)
    with snapshot_path.open("w", encoding="utf-8", newline="\n") as handle:
        write_header(handle, root, timestamp, files)
        write_tree(handle, files)
        for path in files:
            write_file(handle, root, path, max_bytes)

    print(f"Created snapshot: {snapshot_path}")
    print(f"Files included: {len(files)}")
    print(f"Total size: {format_size(snapshot_path.stat().st_size)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a readable project snapshot.")
    parser.add_argument("--out", default="snapshots", help="Output snapshot folder")
    parser.add_argument("--max-file-kb", type=int, default=300, help="Max KB per file before truncation")
    vendor_group = parser.add_mutually_exclusive_group()
    vendor_group.add_argument(
        "--include-vendor",
        dest="include_vendor",
        action="store_true",
        default=True,
        help="Include selected important vendored files. This is the default.",
    )
    vendor_group.add_argument(
        "--no-vendor",
        dest="include_vendor",
        action="store_false",
        help="Exclude all vendored files.",
    )
    return parser.parse_args()


def collect_files(root: Path, include_vendor: bool) -> list[Path]:
    collected: set[Path] = set()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if should_skip(rel):
            continue
        if path.suffix.lower() in INCLUDE_EXTENSIONS:
            collected.add(rel)

    for rel in SELECTED_MODEL_FILES:
        path = root / rel
        if path.is_file():
            collected.add(rel)

    if include_vendor:
        for rel in SELECTED_VENDOR_FILES:
            path = root / rel
            if path.is_file() and path.suffix.lower() in INCLUDE_EXTENSIONS:
                collected.add(rel)

    return sorted(collected, key=lambda item: str(item).lower())


def should_skip(rel: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in rel.parts)


def write_header(handle, root: Path, timestamp: str, files: list[Path]) -> None:
    handle.write("PROJECT SNAPSHOT\n")
    handle.write("================\n\n")
    handle.write(f"Current timestamp: {timestamp}\n")
    handle.write(f"Current working directory: {Path.cwd()}\n")
    handle.write(f"Project root: {root}\n")
    handle.write(f"Python version: {sys.version.replace(chr(10), ' ')}\n")
    handle.write(f"Files included: {len(files)}\n\n")


def write_tree(handle, files: list[Path]) -> None:
    handle.write("PROJECT FILE TREE\n")
    handle.write("=================\n\n")
    for rel in files:
        handle.write(f"{format_rel(rel)}\n")
    handle.write("\n")


def write_file(handle, root: Path, rel: Path, max_bytes: int) -> None:
    path = root / rel
    handle.write("=" * 80 + "\n")
    handle.write(f"FILE: {format_rel(rel)}\n")
    handle.write("=" * 27 + "\n\n")

    try:
        if is_binary(path):
            handle.write("[SKIPPED: binary file]\n\n")
            return
        data = path.read_bytes()
    except OSError as exc:
        handle.write(f"[SKIPPED: could not read file: {exc}]\n\n")
        return

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]

    text = data.decode("utf-8", errors="replace")
    handle.write(text)
    if text and not text.endswith("\n"):
        handle.write("\n")
    if truncated:
        handle.write(f"\n[TRUNCATED: file exceeded {max_bytes // 1024} KB]\n")
    handle.write("\n")


def is_binary(path: Path, sample_size: int = 4096) -> bool:
    try:
        sample = path.read_bytes()[:sample_size]
    except OSError:
        return True
    return b"\x00" in sample


def format_rel(path: Path) -> str:
    return str(path).replace("/", "\\")


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


if __name__ == "__main__":
    raise SystemExit(main())
