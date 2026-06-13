"""Inspect captured IWR6843 Pose/Fall dataset folders."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    if not root.exists():
        print(f"Dataset root not found: {root}")
        return 2

    metadata_files = list(root.rglob("metadata.json"))
    csv_files = list(root.rglob("*.csv"))
    label_rows = Counter()
    ready_rows = Counter()
    low_quality_rows = Counter()
    points_sum = defaultdict(int)
    points_count = defaultdict(int)
    trials_by_subject = defaultdict(set)

    for metadata_path in metadata_files:
        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        subject = str(metadata.get("subject_id", "unknown"))
        trial = str(metadata.get("trial_id", metadata_path.parent.name))
        label = str(metadata.get("label", "unknown"))
        trials_by_subject[subject].add((label, trial, str(metadata_path.parent)))

    for feature_path in root.rglob("features_22.csv"):
        with feature_path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                label = row.get("label", "unknown")
                label_rows[label] += 1
                low_quality = row.get("low_quality", "0") in {"1", "true", "True"}
                if low_quality:
                    low_quality_rows[label] += 1
                try:
                    points = int(float(row.get("num_points", 0) or 0))
                except ValueError:
                    points = 0
                points_sum[label] += points
                points_count[label] += 1

    for feature_path in root.rglob("features_176.csv"):
        with feature_path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("ready", "0") in {"1", "true", "True"}:
                    ready_rows[row.get("label", "unknown")] += 1

    print(f"Dataset root: {root.resolve()}")
    print(f"metadata files: {len(metadata_files)}")
    print(f"csv files: {len(csv_files)}")
    print(f"subjects: {len(trials_by_subject)}")
    print()
    print("label      rows_22  ready_176  low_quality_pct  avg_points")
    print("---------  -------  ---------  ---------------  ----------")
    for label in sorted(set(label_rows) | set(ready_rows)):
        rows = label_rows[label]
        ready = ready_rows[label]
        low_pct = 0.0 if rows == 0 else (low_quality_rows[label] / rows) * 100.0
        avg_points = 0.0 if points_count[label] == 0 else points_sum[label] / points_count[label]
        print(f"{label:<9}  {rows:>7}  {ready:>9}  {low_pct:>14.1f}%  {avg_points:>10.2f}")

    print()
    print("subject  trials")
    print("-------  ------")
    for subject in sorted(trials_by_subject):
        print(f"{subject:<7}  {len(trials_by_subject[subject]):>6}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize captured IWR6843 Pose/Fall data.")
    parser.add_argument("--root", default="dataset/iwr6843_pose", help="Dataset root folder")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
