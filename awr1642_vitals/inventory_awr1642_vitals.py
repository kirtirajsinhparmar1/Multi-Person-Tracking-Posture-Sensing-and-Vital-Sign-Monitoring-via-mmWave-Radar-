"""Inventory AWR1642/vital-sign related files in a Radar Toolbox tree.

This script only searches files and prints candidate paths. It does not open
serial ports, launch visualizers, flash devices, or modify toolbox files.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path


SEARCH_TERMS = [
    "vital",
    "vital_signs",
    "vitalsigns",
    "vitalsigns",
    "breathing",
    "breath",
    "heart",
    "cardiac",
    "respiration",
    "awr1642",
    "iwr1642",
    "xwr1642",
    "xwr16",
    "1642",
    "driver vital signs",
    "driver_vital_signs",
    "people tracking vital signs",
    "vital signs with people tracking",
]

INCLUDE_SUFFIXES = {
    ".bin",
    ".xe674",
    ".xer4f",
    ".appimage",
    ".cfg",
    ".html",
    ".pdf",
    ".md",
    ".txt",
    ".py",
    ".m",
    ".js",
    ".json",
    ".h",
    ".c",
}

TEXT_SUFFIXES = {
    ".cfg",
    ".html",
    ".md",
    ".txt",
    ".py",
    ".m",
    ".js",
    ".json",
    ".h",
    ".c",
}

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv_ti_ui",
    "__pycache__",
    "binData",
    "cache",
    "dataset",
    "env",
    "logs",
    "outputs",
    "snapshots",
    "venv",
}

GROUP_ORDER = [
    "documentation",
    "prebuilt binaries",
    "cfg files",
    "visualizer/UI files",
    "parser/TLV files",
    "source code",
    "Matlab tools",
    "Python tools",
    "other",
]


def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_included_file(path: Path) -> bool:
    return path.suffix.lower() in INCLUDE_SUFFIXES


def path_matches(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(term.lower() in normalized for term in SEARCH_TERMS)


def content_matches(path: Path, max_content_kb: int) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        if path.stat().st_size > max_content_kb * 1024:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(term.lower() in text for term in SEARCH_TERMS)


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if is_included_file(path):
                yield path


def categorize(path: Path) -> list[str]:
    lower = str(path).replace("\\", "/").lower()
    suffix = path.suffix.lower()
    name = path.name.lower()
    groups: list[str] = []

    if suffix in {".html", ".pdf", ".md", ".txt"} or "/docs/" in lower:
        groups.append("documentation")
    if suffix in {".bin", ".xe674", ".xer4f", ".appimage"} or "prebuilt_binaries" in lower:
        groups.append("prebuilt binaries")
    if suffix == ".cfg" or "chirp_configs" in lower:
        groups.append("cfg files")
    if "visualizer" in lower or "gui_" in name or "demo_classes/vital_signs.py" in lower:
        groups.append("visualizer/UI files")
    if "parse" in name or "tlv" in name or "uart" in lower:
        groups.append("parser/TLV files")
    if suffix in {".c", ".h"}:
        groups.append("source code")
    if suffix == ".m":
        groups.append("Matlab tools")
    if suffix == ".py":
        groups.append("Python tools")

    return groups or ["other"]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory local Radar Toolbox files related to AWR1642 and vital signs."
    )
    parser.add_argument("--root", type=Path, default=default_root(), help="Radar Toolbox root to search.")
    parser.add_argument(
        "--content-search",
        action="store_true",
        default=True,
        help="Search small text files for vital-sign/AWR1642 terms as well as paths.",
    )
    parser.add_argument(
        "--no-content-search",
        action="store_false",
        dest="content_search",
        help="Only match terms in paths and filenames.",
    )
    parser.add_argument(
        "--max-content-kb",
        type=int,
        default=512,
        help="Maximum text file size to scan when --content-search is enabled.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    grouped: dict[str, list[str]] = defaultdict(list)

    for path in iter_files(root):
        matched = path_matches(path)
        if not matched and args.content_search:
            matched = content_matches(path, args.max_content_kb)
        if not matched:
            continue
        for group in categorize(path):
            grouped[group].append(rel(path, root))

    print(f"Root: {root}")
    print("Search mode: path" + (" + content" if args.content_search else " only"))
    total_unique = len({item for paths in grouped.values() for item in paths})
    print(f"Unique candidate files: {total_unique}")

    for group in GROUP_ORDER:
        paths = sorted(set(grouped.get(group, [])))
        print()
        print("=" * 80)
        print(f"{group} ({len(paths)})")
        print("=" * 80)
        if not paths:
            print("(none)")
            continue
        for item in paths:
            print(item)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
