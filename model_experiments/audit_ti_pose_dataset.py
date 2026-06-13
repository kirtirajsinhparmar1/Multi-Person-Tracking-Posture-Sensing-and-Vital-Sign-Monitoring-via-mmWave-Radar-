"""Audit TI Pose/Fall classes.zip for balance, quality, and recording bias."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import json
import math
import statistics
import tempfile
import zipfile
from pathlib import Path

from train_or_export_ti_pose_model import CLASS_NAMES, FEATURE_NAMES_22, build_frame_features


KEY_FIELDS = ["posx", "posy", "posz", "velx", "vely", "velz", "accx", "accy", "accz"]
RECORDING_FIELDNAMES = [
    "class_name",
    "filename",
    "source_csv",
    "rows",
    "usable_frame_rows",
    "usable_windows",
    "invalid_rows",
    "missing_required_columns",
    "nan_inf_count",
    "mean_point_count",
    "min_point_count",
    "max_point_count",
    "mean_abs_velocity",
    "column_count",
    "columns",
    "audit_error",
    "error_message",
    "suspicious",
    "suspicious_reasons",
]
FEATURE_FIELDNAMES = ["class_name", "filename", "feature", "count", "min", "max", "mean", "std"]


try:
    import pandas as pd
except ImportError:
    class _PandasFallback:
        @staticmethod
        def notna(value) -> bool:
            return value is not None and not (isinstance(value, float) and math.isnan(value))

    pd = _PandasFallback()


def as_float(value) -> float | None:
    if value in ("", None):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else math.nan


def point_columns(fieldnames: list[str]) -> list[tuple[str, str, str]]:
    triplets = []
    for name in fieldnames:
        if name.startswith("pointy"):
            suffix = name.removeprefix("pointy")
            z_name = f"pointz{suffix}"
            snr_name = f"snr{suffix}"
            if z_name in fieldnames and snr_name in fieldnames:
                triplets.append((name, z_name, snr_name))
    if triplets:
        return triplets
    idx = 0
    while f"y{idx}" in fieldnames and f"z{idx}" in fieldnames and f"snr{idx}" in fieldnames:
        triplets.append((f"y{idx}", f"z{idx}", f"snr{idx}"))
        idx += 1
    return triplets


def summarize(values: list[float]) -> dict:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"count": 0, "min": "", "max": "", "mean": "", "std": ""}
    return {
        "count": len(finite),
        "min": min(finite),
        "max": max(finite),
        "mean": statistics.fmean(finite),
        "std": statistics.pstdev(finite) if len(finite) > 1 else 0.0,
    }


def has_numeric_stat(stats, key):
    return (
        isinstance(stats, dict)
        and key in stats
        and stats[key] not in ("", None)
        and pd.notna(stats[key])
    )


def get_numeric_stat(stats, key, default=None):
    if has_numeric_stat(stats, key):
        try:
            return float(stats[key])
        except Exception:
            return default
    return default


def is_valid_min_max(stats):
    mn = get_numeric_stat(stats, "min")
    mx = get_numeric_stat(stats, "max")
    return mn is not None and mx is not None


def read_csv_columns(csv_path: Path) -> list[str]:
    try:
        with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle)
            return reader.fieldnames or []
    except Exception:
        return []


def make_error_row(class_name: str, csv_path: Path, error: Exception) -> dict:
    columns = read_csv_columns(csv_path)
    return {
        "class_name": class_name,
        "filename": csv_path.name,
        "source_csv": str(csv_path),
        "rows": 0,
        "usable_frame_rows": 0,
        "usable_windows": 0,
        "invalid_rows": 0,
        "missing_required_columns": "",
        "nan_inf_count": 0,
        "mean_point_count": 0.0,
        "min_point_count": 0,
        "max_point_count": 0,
        "mean_abs_velocity": 0.0,
        "column_count": len(columns),
        "columns": ";".join(columns),
        "audit_error": True,
        "error_message": str(error),
        "suspicious": True,
        "suspicious_reasons": "audit error",
    }


def audit_recording(class_name: str, csv_path: Path, window_size: int) -> tuple[dict, dict, list[str]]:
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    required = ["posy", "posz", "velx", "vely", "velz", "accx", "accy", "accz"]
    missing = [name for name in required if name not in fieldnames]
    triplets = point_columns(fieldnames)
    if not triplets:
        missing.append("point y/z/snr columns")

    invalid_rows = 0
    nan_inf_count = 0
    usable_frames = 0
    point_counts = []
    feature_values = defaultdict(list)
    motion_values = []

    for row in rows:
        bad_numeric = False
        for name in KEY_FIELDS:
            value = as_float(row.get(name))
            if value is None:
                continue
            if not math.isfinite(value):
                nan_inf_count += 1
                bad_numeric = True
            else:
                feature_values[name].append(value)
        point_count = 0
        for y_name, z_name, snr_name in triplets:
            values = [as_float(row.get(y_name)), as_float(row.get(z_name)), as_float(row.get(snr_name))]
            if all(value is not None and math.isfinite(value) for value in values):
                point_count += 1
                feature_values["point_y"].append(float(values[0]))
                feature_values["point_z"].append(float(values[1]))
                feature_values["point_snr"].append(float(values[2]))
        point_counts.append(point_count)
        motion_values.extend(
            abs(value)
            for value in [as_float(row.get("velx")), as_float(row.get("vely")), as_float(row.get("velz"))]
            if value is not None and math.isfinite(value)
        )
        if build_frame_features(row) is not None:
            usable_frames += 1
        else:
            invalid_rows += 1
        if bad_numeric:
            invalid_rows += 1

    usable_windows = max(0, usable_frames - window_size + 1)
    stats = {name: summarize(values) for name, values in feature_values.items()}
    reasons = []
    posz_stats = stats.get("posz", {})
    point_z_stats = stats.get("point_z", {})
    snr_stats = stats.get("point_snr", {})
    mean_motion = statistics.fmean(motion_values) if motion_values else 0.0

    if usable_windows == 0:
        reasons.append("zero usable windows")
    if 0 < usable_windows < 20:
        reasons.append("very few usable windows")
    if nan_inf_count > 0:
        reasons.append("NaN/inf numeric values")
    if missing:
        reasons.append("missing columns")
    posz_min = get_numeric_stat(posz_stats, "min")
    posz_max = get_numeric_stat(posz_stats, "max")
    if posz_min is None or posz_max is None:
        reasons.append("missing_or_invalid_posz_stats")
    elif posz_min < -5 or posz_max > 5:
        reasons.append("abnormal posz range")

    point_z_min = get_numeric_stat(point_z_stats, "min")
    point_z_max = get_numeric_stat(point_z_stats, "max")
    if point_z_min is None or point_z_max is None:
        reasons.append("missing_or_invalid_point_z_stats")
    elif point_z_min < -5 or point_z_max > 5:
        reasons.append("abnormal point z range")

    snr_min = get_numeric_stat(snr_stats, "min")
    snr_max = get_numeric_stat(snr_stats, "max")
    if snr_min is None or snr_max is None:
        reasons.append("missing_or_invalid_snr_stats")
    elif snr_max > 1000 or snr_min < -100:
        reasons.append("abnormal SNR range")
    if class_name in {"WALKING", "FALLING"} and mean_motion < 0.01:
        reasons.append("walking/falling recording has almost no motion")

    summary = {
        "class_name": class_name,
        "filename": csv_path.name,
        "source_csv": str(csv_path),
        "rows": len(rows),
        "usable_frame_rows": usable_frames,
        "usable_windows": usable_windows,
        "invalid_rows": invalid_rows,
        "missing_required_columns": ";".join(missing),
        "nan_inf_count": nan_inf_count,
        "mean_point_count": statistics.fmean(point_counts) if point_counts else 0.0,
        "min_point_count": min(point_counts) if point_counts else 0,
        "max_point_count": max(point_counts) if point_counts else 0,
        "mean_abs_velocity": mean_motion,
        "column_count": len(fieldnames),
        "columns": ";".join(fieldnames),
        "audit_error": False,
        "error_message": "",
        "suspicious": bool(reasons),
        "suspicious_reasons": "; ".join(reasons),
    }
    return summary, stats, reasons


def writable_fallback_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> Path:
    target = path
    try:
        handle = target.open("w", newline="", encoding="utf-8")
    except PermissionError:
        target = writable_fallback_path(path)
        print(f"Warning: {path} is locked or not writable; writing {target} instead.")
        handle = target.open("w", newline="", encoding="utf-8")

    with handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return target


def write_text(path: Path, text: str) -> Path:
    target = path
    try:
        target.write_text(text, encoding="utf-8")
    except PermissionError:
        target = writable_fallback_path(path)
        print(f"Warning: {path} is locked or not writable; writing {target} instead.")
        target.write_text(text, encoding="utf-8")
    return target


def save_plots(output_dir: Path, recording_rows: list[dict], feature_values: dict[str, list[float]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    if not recording_rows:
        print("Warning: no recording rows available; skipping audit plots.")
        return

    class_windows = {name: 0 for name in CLASS_NAMES}
    class_recordings = {name: 0 for name in CLASS_NAMES}
    for row in recording_rows:
        class_name = row.get("class_name", "")
        if class_name not in class_windows:
            continue
        class_windows[class_name] += int(row.get("usable_windows", 0) or 0)
        class_recordings[class_name] += 1

    def bar(path: Path, values: dict, title: str, ylabel: str) -> None:
        plt.figure(figsize=(8, 5))
        plt.bar(list(values), [values[name] for name in values])
        plt.xticks(rotation=20)
        plt.ylabel(ylabel)
        plt.title(title)
        plt.tight_layout()
        plt.savefig(path, dpi=150)
        plt.close()

    bar(plots_dir / "class_window_counts.png", class_windows, "Usable windows per class", "windows")
    bar(plots_dir / "class_recording_counts.png", class_recordings, "Recordings per class", "recordings")

    plt.figure(figsize=(9, 5))
    plt.hist([int(row["usable_windows"]) for row in recording_rows], bins=20)
    plt.xlabel("usable windows")
    plt.ylabel("recordings")
    plt.title("Windows per recording")
    plt.tight_layout()
    plt.savefig(plots_dir / "windows_per_recording.png", dpi=150)
    plt.close()

    for path_name, fields, title in [
        ("feature_distributions_posz.png", ["posz", "point_z"], "Height feature distributions"),
        ("feature_distributions_snr.png", ["point_snr"], "SNR distribution"),
        ("feature_distributions_velocity.png", ["velx", "vely", "velz"], "Velocity distributions"),
    ]:
        plt.figure(figsize=(8, 5))
        plotted = False
        for field in fields:
            values = feature_values.get(field, [])
            if values:
                plt.hist(values, bins=40, alpha=0.5, label=field)
                plotted = True
        plt.title(title)
        if plotted:
            plt.legend()
        else:
            plt.text(0.5, 0.5, "No numeric values available", ha="center", va="center", transform=plt.gca().transAxes)
        plt.tight_layout()
        plt.savefig(plots_dir / path_name, dpi=150)
        plt.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classes-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/dataset_audit"))
    parser.add_argument("--window-size", type=int, default=8)
    parser.add_argument("--min-points", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    recording_rows = []
    suspicious_rows = []
    feature_rows = []
    all_feature_values = defaultdict(list)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(args.classes_zip) as archive:
            archive.extractall(temp_path)

        for class_name in CLASS_NAMES:
            class_dir = temp_path / class_name.lower()
            for csv_path in sorted(class_dir.glob("*.csv")):
                if args.debug:
                    columns = read_csv_columns(csv_path)
                    print(f"[audit-debug] class={class_name} csv={csv_path}")
                    print(f"[audit-debug] columns={columns}")
                try:
                    row, stats, reasons = audit_recording(class_name, csv_path, args.window_size)
                except Exception as exc:
                    row = make_error_row(class_name, csv_path, exc)
                    stats = {}
                    reasons = ["audit error"]
                    print(f"Warning: failed to audit {csv_path}: {exc}")
                recording_rows.append(row)
                if reasons:
                    suspicious_rows.append(row)
                    if args.debug:
                        print(f"[audit-debug] suspicious {csv_path.name}: {'; '.join(reasons)}")
                for feature_name, stat in stats.items():
                    feature_rows.append({"class_name": class_name, "filename": csv_path.name, "feature": feature_name, **stat})
                    if get_numeric_stat(stat, "count", 0):
                        # Re-read compactly for plot distributions; audit_recording returns summaries only.
                        pass

                try:
                    with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
                        reader = csv.DictReader(handle)
                        columns = reader.fieldnames or []
                        triplets = point_columns(columns)
                        for source_row in reader:
                            for name in KEY_FIELDS:
                                value = as_float(source_row.get(name))
                                if value is not None and math.isfinite(value):
                                    all_feature_values[name].append(value)
                            for y_name, z_name, snr_name in triplets:
                                for out_name, source_name in [("point_y", y_name), ("point_z", z_name), ("point_snr", snr_name)]:
                                    value = as_float(source_row.get(source_name))
                                    if value is not None and math.isfinite(value):
                                        all_feature_values[out_name].append(value)
                except Exception as exc:
                    print(f"Warning: failed to collect plot values from {csv_path}: {exc}")

    class_summary = []
    total_by_class = Counter()
    recording_by_class = Counter()
    for row in recording_rows:
        class_name = row.get("class_name", "")
        if class_name in CLASS_NAMES:
            total_by_class[class_name] += int(row.get("usable_windows", 0) or 0)
            recording_by_class[class_name] += 1
    for class_name in CLASS_NAMES:
        class_records = [row for row in recording_rows if row["class_name"] == class_name]
        windows = [int(row["usable_windows"]) for row in class_records]
        class_summary.append(
            {
                "class_name": class_name,
                "recordings": recording_by_class[class_name],
                "usable_windows": total_by_class[class_name],
                "min_windows_per_recording": min(windows) if windows else 0,
                "max_windows_per_recording": max(windows) if windows else 0,
                "mean_windows_per_recording": statistics.fmean(windows) if windows else 0.0,
            }
        )

    written_outputs = [
        write_csv(args.output / "recording_summary.csv", recording_rows, RECORDING_FIELDNAMES),
        write_csv(args.output / "class_summary.csv", class_summary, list(class_summary[0]) if class_summary else ["class_name", "recordings", "usable_windows", "min_windows_per_recording", "max_windows_per_recording", "mean_windows_per_recording"]),
        write_csv(args.output / "feature_summary.csv", feature_rows, FEATURE_FIELDNAMES),
        write_csv(args.output / "suspicious_recordings.csv", suspicious_rows, RECORDING_FIELDNAMES),
    ]
    save_plots(args.output, recording_rows, all_feature_values)

    window_counts = [total_by_class[name] for name in CLASS_NAMES if total_by_class[name] > 0]
    recording_counts = [recording_by_class[name] for name in CLASS_NAMES if recording_by_class[name] > 0]
    imbalance_ratio = max(window_counts) / min(window_counts) if window_counts else 0.0
    recording_ratio = max(recording_counts) / min(recording_counts) if recording_counts else 0.0
    audit = {
        "classes_zip": str(args.classes_zip),
        "recordings": len(recording_rows),
        "total_windows": sum(total_by_class.values()),
        "class_windows": dict(total_by_class),
        "class_recordings": dict(recording_by_class),
        "class_imbalance_ratio": imbalance_ratio,
        "recording_imbalance_ratio": recording_ratio,
        "suspicious_recordings": len(suspicious_rows),
    }
    written_outputs.append(write_text(args.output / "audit_report.json", json.dumps(audit, indent=2) + "\n"))

    report = [
        "# TI Pose/Fall Dataset Audit",
        "",
        "## Is the dataset balanced enough?",
        "",
        f"Total usable windows: {audit['total_windows']}",
        f"Windows per class: {dict(total_by_class)}",
        f"Recordings per class: {dict(recording_by_class)}",
        f"Class imbalance ratio by windows: {imbalance_ratio:.2f}",
        f"Recording imbalance ratio: {recording_ratio:.2f}",
        f"Suspicious recordings flagged: {len(suspicious_rows)}",
        "",
        "The dataset is usable if suspicious recordings are reviewed, but random window split is optimistic because adjacent windows from one CSV recording are highly correlated.",
        "",
        "Recommendations:",
        "- For honest validation, use recording-level split.",
        "- For training, use all cleaned windows with class_weighting balanced.",
        "- Avoid random window split for final claims.",
        "- Downsampling can be used for stress testing but may discard useful data.",
        "- Weighted loss or weighted sampler is preferred over throwing data away.",
    ]
    written_outputs.append(write_text(args.output / "audit_report.md", "\n".join(report) + "\n"))
    print(f"Audit complete: {args.output}")
    print(f"Recordings={len(recording_rows)} suspicious={len(suspicious_rows)} windows={audit['total_windows']}")
    if args.debug:
        for path in written_outputs:
            print(f"[audit-debug] wrote {path}")


if __name__ == "__main__":
    main()
