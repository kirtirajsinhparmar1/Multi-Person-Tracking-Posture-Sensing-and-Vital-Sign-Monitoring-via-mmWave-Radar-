"""Prepare cleaned TI Pose/Fall windows with recording-level split metadata."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
import random
import tempfile
import zipfile
from pathlib import Path

import numpy as np

from train_or_export_ti_pose_model import (
    CLASS_NAMES,
    FEATURE_NAMES_176,
    FEATURE_NAMES_22,
    FLATTEN_ORDER,
    INPUT_SIZE,
    SNR_FEATURES,
    channel_slice,
    flatten_window,
)


COLUMN_ALIASES = {
    "frame": ["Frame count", "frame", "frameNum", "frameData_frameNum"],
    "tid": ["tid", "TID", "target_id"],
    "posx": ["posx", "posX", "x", "X"],
    "posy": ["posy", "posY", "y", "Y"],
    "posz": ["posz", "posZ", "z", "Z"],
    "velx": ["velx", "velX", "vx", "Vx"],
    "vely": ["vely", "velY", "vy", "Vy"],
    "velz": ["velz", "velZ", "vz", "Vz"],
    "accx": ["accx", "accX", "ax", "Ax"],
    "accy": ["accy", "accY", "ay", "Ay"],
    "accz": ["accz", "accZ", "az", "Az"],
}

POSITION_FEATURES = ["posx", "posy", "posz"]
VELOCITY_FEATURES = ["velx", "vely", "velz"]
ACCELERATION_FEATURES = ["accx", "accy", "accz"]
REQUIRED_POINT_COUNT = 5


def parse_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def suffix_sort_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except ValueError:
        return 10_000, value


def resolve_columns(fieldnames: list[str]) -> dict[str, str | None]:
    available = set(fieldnames)
    resolved = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        resolved[canonical] = next((alias for alias in aliases if alias in available), None)
    return resolved


def detect_point_triplets(fieldnames: list[str]) -> list[tuple[str, str, str, str]]:
    available = set(fieldnames)
    point_suffixes = sorted(
        {
            name.removeprefix("pointy")
            for name in fieldnames
            if name.startswith("pointy")
            and f"pointz{name.removeprefix('pointy')}" in available
            and f"snr{name.removeprefix('pointy')}" in available
        },
        key=suffix_sort_key,
    )
    if point_suffixes:
        return [("point", f"pointy{suffix}", f"pointz{suffix}", f"snr{suffix}") for suffix in point_suffixes]

    yz_suffixes = sorted(
        {
            name.removeprefix("y")
            for name in fieldnames
            if name.startswith("y")
            and name.removeprefix("y").isdigit()
            and f"z{name.removeprefix('y')}" in available
            and f"snr{name.removeprefix('y')}" in available
        },
        key=suffix_sort_key,
    )
    return [("relative", f"y{suffix}", f"z{suffix}", f"snr{suffix}") for suffix in yz_suffixes]


def read_exclusions(path: Path | None) -> set[str]:
    if path is None:
        return set()
    excluded = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            excluded.add(row.get("filename", ""))
            excluded.add(row.get("source_csv", ""))
    return {value for value in excluded if value}


def normalize_class_name(value: str) -> str:
    return value.strip().upper()


def resolve_active_classes(include_classes: list[str] | None, exclude_classes: list[str] | None) -> tuple[list[str], list[str], list[str]]:
    requested_include = [normalize_class_name(value) for value in include_classes] if include_classes else list(CLASS_NAMES)
    requested_exclude = [normalize_class_name(value) for value in exclude_classes] if exclude_classes else []
    requested_include = list(dict.fromkeys(requested_include))
    requested_exclude = list(dict.fromkeys(requested_exclude))
    unknown = sorted({value for value in requested_include + requested_exclude if value not in CLASS_NAMES})
    if unknown:
        raise SystemExit(f"Unknown class name(s): {', '.join(unknown)}. Valid classes: {', '.join(CLASS_NAMES)}")

    excluded_set = set(requested_exclude)
    active_classes = [class_name for class_name in requested_include if class_name not in excluded_set]
    if not active_classes:
        raise SystemExit("No classes selected after applying --include-classes/--exclude-classes.")

    excluded_classes = [class_name for class_name in CLASS_NAMES if class_name not in active_classes]
    return active_classes, requested_include, excluded_classes


def count_raw_windows_for_skipped_classes(classes_root: Path, class_names: list[str], window_size: int) -> dict[str, int]:
    skipped = {class_name: 0 for class_name in class_names}
    for class_name in class_names:
        class_dir = classes_root / class_name.lower()
        for csv_path in sorted(class_dir.glob("*.csv")):
            with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
                row_count = sum(1 for _ in csv.DictReader(handle))
            skipped[class_name] += max(0, row_count - window_size + 1)
    return skipped


def canonical_value(
    row: dict,
    columns: dict[str, str | None],
    name: str,
    imputed_columns: Counter,
    recording_imputed: Counter,
    warnings: set[str],
) -> tuple[float, str | None]:
    source = columns.get(name)
    if source is not None:
        value = parse_float(row.get(source))
        if math.isfinite(value):
            return value, None
        return value, f"invalid numeric {name}"

    if name in VELOCITY_FEATURES or name in ACCELERATION_FEATURES or name in {"posx", "posy"}:
        imputed_columns[name] += 1
        recording_imputed[name] += 1
        warnings.add(f"imputed missing {name} as 0")
        return 0.0, None

    return math.nan, f"missing required {name}"


def build_frame_feature(
    row: dict,
    columns: dict[str, str | None],
    point_triplets: list[tuple[str, str, str, str]],
    imputed_columns: Counter,
    recording_imputed: Counter,
    warnings: set[str],
) -> tuple[list[float] | None, int, str | None]:
    values = {}
    for name in POSITION_FEATURES + VELOCITY_FEATURES + ACCELERATION_FEATURES:
        values[name], reason = canonical_value(row, columns, name, imputed_columns, recording_imputed, warnings)
        if reason and name == "posz":
            return None, 0, reason

    if not math.isfinite(values["posz"]):
        return None, 0, "invalid numeric posz"

    points = []
    for style, y_name, z_name, snr_name in point_triplets:
        y_value = parse_float(row.get(y_name))
        z_value = parse_float(row.get(z_name))
        snr_value = parse_float(row.get(snr_name))
        if not (math.isfinite(y_value) and math.isfinite(z_value) and math.isfinite(snr_value)):
            continue
        relative_y = y_value - values["posy"] if style == "point" else y_value
        points.append((z_value, relative_y, snr_value))

    if len(points) < REQUIRED_POINT_COUNT:
        return None, len(points), f"fewer than {REQUIRED_POINT_COUNT} valid points"

    points.sort(key=lambda item: item[0])
    selected = points[-REQUIRED_POINT_COUNT:]
    feature = [
        values["posz"],
        values["velx"],
        values["vely"],
        values["velz"],
        values["accx"],
        values["accy"],
        values["accz"],
    ]
    for z_value, relative_y, snr_value in selected:
        feature.extend([relative_y, z_value, snr_value])
    return feature, len(points), None


def clean_frame(feature22: list[float], args) -> str | None:
    array = np.asarray(feature22, dtype=np.float32)
    if array.shape != (len(FEATURE_NAMES_22),):
        return "wrong frame feature length"
    if not np.isfinite(array).all():
        return "NaN/inf feature"

    checks = [
        ("posz", array[0], args.max_abs_position),
        ("velx", array[1], args.max_abs_velocity),
        ("vely", array[2], args.max_abs_velocity),
        ("velz", array[3], args.max_abs_velocity),
        ("accx", array[4], args.max_abs_acceleration),
        ("accy", array[5], args.max_abs_acceleration),
        ("accz", array[6], args.max_abs_acceleration),
    ]
    for name, value, limit in checks:
        if abs(float(value)) > limit:
            return f"{name} magnitude > {limit:g}"

    for point_index in range(REQUIRED_POINT_COUNT):
        base = 7 + point_index * 3
        relative_y = float(array[base])
        point_z = float(array[base + 1])
        snr = float(array[base + 2])
        if abs(relative_y) > args.max_abs_position:
            return f"point_y{point_index} magnitude > {args.max_abs_position:g}"
        if abs(point_z) > args.max_abs_position:
            return f"point_z{point_index} magnitude > {args.max_abs_position:g}"
        if snr < args.min_snr or snr > args.max_snr:
            return f"snr{point_index} outside [{args.min_snr:g}, {args.max_snr:g}]"
    return None


def clean_window(feature176: list[float], args) -> str | None:
    array = np.asarray(feature176, dtype=np.float32)
    if array.shape != (INPUT_SIZE,):
        return "wrong feature length"
    if not np.isfinite(array).all():
        return "NaN/inf feature"

    def values(feature_name: str) -> np.ndarray:
        return array[channel_slice(feature_name)]

    for name in ["posz", "y0", "z0", "y1", "z1", "y2", "z2", "y3", "z3", "y4", "z4"]:
        if np.abs(values(name)).max() > args.max_abs_position:
            return f"{name} magnitude > {args.max_abs_position:g}"
    for name in ["velx", "vely", "velz"]:
        if np.abs(values(name)).max() > args.max_abs_velocity:
            return f"{name} magnitude > {args.max_abs_velocity:g}"
    for name in ["accx", "accy", "accz"]:
        if np.abs(values(name)).max() > args.max_abs_acceleration:
            return f"{name} magnitude > {args.max_abs_acceleration:g}"
    for name in SNR_FEATURES:
        column = values(name)
        if column.min() < args.min_snr or column.max() > args.max_snr:
            return f"{name} outside [{args.min_snr:g}, {args.max_snr:g}]"
    return None


def removed_row(base: dict, reason: str) -> dict:
    return {
        "sample_id": "",
        "class_name": base.get("class_name", ""),
        "class_id": base.get("class_id", ""),
        "recording_id": base.get("recording_id", ""),
        "source_csv": base.get("source_csv", ""),
        "window_start_row": base.get("window_start_row", ""),
        "window_end_row": base.get("window_end_row", ""),
        "reason": reason,
    }


def generate_windows(
    classes_root: Path,
    args,
    excluded: set[str],
    class_names: list[str],
    skipped_class_names: list[str],
) -> tuple[list[list[float]], list[int], list[dict], list[dict], list[dict], dict]:
    features = []
    labels = []
    metadata = []
    removed = []
    excluded_recordings = []
    class_to_id = {class_name: index for index, class_name in enumerate(class_names)}
    recordings_per_class = {class_name: 0 for class_name in class_names}
    included_recordings_per_class = {class_name: 0 for class_name in class_names}
    raw_windows_per_class = {class_name: 0 for class_name in class_names}
    clean_windows_per_class = {class_name: 0 for class_name in class_names}
    removed_windows_per_class = {class_name: 0 for class_name in class_names}
    skipped_windows_by_excluded_class = count_raw_windows_for_skipped_classes(classes_root, skipped_class_names, args.window_size)
    imputed_columns = Counter()

    for class_name in class_names:
        class_id = class_to_id[class_name]
        class_dir = classes_root / class_name.lower()
        for csv_path in sorted(class_dir.glob("*.csv")):
            if csv_path.name in excluded or str(csv_path) in excluded:
                continue

            recordings_per_class[class_name] += 1
            recording_id = f"{class_name}:{csv_path.stem}"
            recording_imputed = Counter()
            warnings = set()
            frame_features: list[list[float] | None] = []
            frame_reasons: list[str | None] = []
            frame_point_counts: list[int] = []
            columns = {}
            point_triplets = []

            with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
                reader = csv.DictReader(handle)
                fieldnames = reader.fieldnames or []
                columns = resolve_columns(fieldnames)
                point_triplets = detect_point_triplets(fieldnames)
                if columns.get("posz") is None:
                    warnings.add("missing required posz column")
                if columns.get("posy") is None:
                    warnings.add("missing posy column; point y treated as already relative")
                if not point_triplets:
                    warnings.add("missing point y/z/snr triplets")

                for row in reader:
                    feature22, point_count, parse_reason = build_frame_feature(
                        row,
                        columns,
                        point_triplets,
                        imputed_columns,
                        recording_imputed,
                        warnings,
                    )
                    if feature22 is None:
                        frame_features.append(None)
                        frame_reasons.append(parse_reason or "unusable frame")
                        frame_point_counts.append(point_count)
                        continue
                    clean_reason = clean_frame(feature22, args)
                    frame_features.append(feature22)
                    frame_reasons.append(clean_reason)
                    frame_point_counts.append(point_count)

            raw_windows = max(0, len(frame_features) - args.window_size + 1)
            raw_windows_per_class[class_name] += raw_windows
            candidate_features = []
            candidate_metadata = []
            candidate_removed = []

            for start in range(raw_windows):
                end = start + args.window_size
                base = {
                    "class_name": class_name,
                    "class_id": class_id,
                    "recording_id": recording_id,
                    "source_csv": csv_path.name,
                    "window_start_row": start,
                    "window_end_row": end - 1,
                }
                bad_reasons = sorted({reason for reason in frame_reasons[start:end] if reason})
                if bad_reasons:
                    candidate_removed.append(removed_row(base, "; ".join(bad_reasons)))
                    continue

                window_frames = frame_features[start:end]
                feature176 = flatten_window(window_frames)  # type: ignore[arg-type]
                reason = clean_window(feature176, args)
                if reason:
                    candidate_removed.append(removed_row(base, reason))
                    continue

                point_counts = frame_point_counts[start:end]
                candidate_features.append(feature176)
                candidate_metadata.append(
                    {
                        "sample_id": "",
                        **base,
                        "min_valid_points": min(point_counts) if point_counts else 0,
                        "mean_valid_points": float(np.mean(point_counts)) if point_counts else 0.0,
                    }
                )

            if len(candidate_features) < args.min_windows_per_recording:
                reason = f"recording has fewer than {args.min_windows_per_recording} clean windows"
                excluded_recordings.append(
                    {
                        "class_name": class_name,
                        "class_id": class_id,
                        "recording_id": recording_id,
                        "source_csv": csv_path.name,
                        "rows": len(frame_features),
                        "raw_windows": raw_windows,
                        "clean_windows": len(candidate_features),
                        "reason": reason,
                        "warnings": "; ".join(sorted(warnings)),
                        "imputed_columns": json.dumps(dict(recording_imputed), sort_keys=True),
                    }
                )
                for row in candidate_removed:
                    removed.append(row)
                    removed_windows_per_class[class_name] += 1
                for row in candidate_metadata:
                    removed.append(removed_row(row, reason))
                    removed_windows_per_class[class_name] += 1
                continue

            included_recordings_per_class[class_name] += 1
            clean_windows_per_class[class_name] += len(candidate_features)
            for row in candidate_removed:
                removed.append(row)
                removed_windows_per_class[class_name] += 1
            for feature176, row in zip(candidate_features, candidate_metadata):
                sample_id = len(features)
                row["sample_id"] = sample_id
                features.append(feature176)
                labels.append(class_id)
                metadata.append(row)

    summary = {
        "recordings_per_class": recordings_per_class,
        "included_recordings_per_class": included_recordings_per_class,
        "raw_windows_per_class": raw_windows_per_class,
        "clean_windows_per_class": clean_windows_per_class,
        "removed_windows_per_class": removed_windows_per_class,
        "removed_windows": len(removed),
        "excluded_recordings": len(excluded_recordings),
        "imputed_columns": dict(sorted(imputed_columns.items())),
        "skipped_windows_by_excluded_class": skipped_windows_by_excluded_class,
    }
    return features, labels, metadata, removed, excluded_recordings, summary


def apply_balance(features, labels, metadata, mode: str, target: int | None, seed: int):
    if mode not in {"none", "downsample", "weighted"}:
        raise ValueError(f"Unsupported balance mode: {mode}")
    if mode != "downsample":
        return features, labels, metadata

    rng = random.Random(seed)
    by_class = defaultdict(list)
    for index, label in enumerate(labels):
        by_class[int(label)].append(index)
    target_count = target if target is not None else min(len(indices) for indices in by_class.values() if indices)
    keep = []
    for indices in by_class.values():
        shuffled = list(indices)
        rng.shuffle(shuffled)
        keep.extend(shuffled[: min(target_count, len(shuffled))])
    keep.sort()
    remap = {old: new for new, old in enumerate(keep)}
    balanced_features = [features[index] for index in keep]
    balanced_labels = [labels[index] for index in keep]
    balanced_metadata = []
    for index in keep:
        row = dict(metadata[index])
        row["sample_id"] = remap[index]
        balanced_metadata.append(row)
    return balanced_features, balanced_labels, balanced_metadata


def class_count_dict(labels: list[int] | np.ndarray, class_names: list[str]) -> dict[str, int]:
    counts = Counter(int(label) for label in labels)
    return {class_name: counts.get(index, 0) for index, class_name in enumerate(class_names)}


def recording_counts_by_class(metadata: list[dict], indices: list[int] | np.ndarray, class_names: list[str]) -> dict[str, int]:
    recordings = {class_name: set() for class_name in class_names}
    for index in indices:
        row = metadata[int(index)]
        recordings[row["class_name"]].add(row["recording_id"])
    return {class_name: len(values) for class_name, values in recordings.items()}


def recording_lists(metadata: list[dict], indices: list[int] | np.ndarray) -> list[str]:
    return sorted({metadata[int(index)]["recording_id"] for index in indices})


def split_recordings(
    metadata: list[dict],
    labels: list[int],
    test_size: float,
    seed: int,
    class_names: list[str],
) -> tuple[np.ndarray, np.ndarray, dict, list[dict]]:
    rng = random.Random(seed)
    recordings_by_class = defaultdict(list)
    for row in metadata:
        recordings_by_class[int(row["class_id"])].append(row["recording_id"])
    for class_id in list(recordings_by_class):
        recordings_by_class[class_id] = sorted(set(recordings_by_class[class_id]))

    test_recordings = set()
    train_recordings = set()
    split_rows = []
    for class_id, recordings in recordings_by_class.items():
        shuffled = list(recordings)
        rng.shuffle(shuffled)
        if len(shuffled) <= 1:
            n_test = 0
        else:
            n_test = max(1, int(round(len(shuffled) * test_size)))
            n_test = min(n_test, len(shuffled) - 1)
        class_test = set(shuffled[:n_test])
        class_train = set(shuffled[n_test:])
        test_recordings.update(class_test)
        train_recordings.update(class_train)
        for recording_id in sorted(class_train):
            split_rows.append({"recording_id": recording_id, "class_name": class_names[class_id], "split": "train"})
        for recording_id in sorted(class_test):
            split_rows.append({"recording_id": recording_id, "class_name": class_names[class_id], "split": "test"})

    train_indices = []
    test_indices = []
    for index, row in enumerate(metadata):
        if row["recording_id"] in test_recordings:
            test_indices.append(index)
        else:
            train_indices.append(index)

    train_array = np.asarray(train_indices, dtype=np.int64)
    test_array = np.asarray(test_indices, dtype=np.int64)
    train_labels = [labels[index] for index in train_indices]
    test_labels = [labels[index] for index in test_indices]
    summary = {
        "split_mode": "recording",
        "train_recordings": len(train_recordings),
        "test_recordings": len(test_recordings),
        "train_samples": int(len(train_array)),
        "test_samples": int(len(test_array)),
        "train_window_counts_by_class": class_count_dict(train_labels, class_names),
        "test_window_counts_by_class": class_count_dict(test_labels, class_names),
        "train_recording_counts_by_class": recording_counts_by_class(metadata, train_array, class_names),
        "test_recording_counts_by_class": recording_counts_by_class(metadata, test_array, class_names),
        "train_recordings_list": recording_lists(metadata, train_array),
        "test_recordings_list": recording_lists(metadata, test_array),
    }
    return train_array, test_array, summary, split_rows


def split_windows(metadata: list[dict], labels: list[int], test_size: float, seed: int, class_names: list[str]):
    from sklearn.model_selection import train_test_split

    indices = np.arange(len(labels), dtype=np.int64)
    train_indices, test_indices = train_test_split(
        indices,
        test_size=test_size,
        stratify=labels,
        random_state=seed,
    )
    train_labels = [labels[int(index)] for index in train_indices]
    test_labels = [labels[int(index)] for index in test_indices]
    summary = {
        "split_mode": "window",
        "train_recordings": len(recording_lists(metadata, train_indices)),
        "test_recordings": len(recording_lists(metadata, test_indices)),
        "train_samples": int(len(train_indices)),
        "test_samples": int(len(test_indices)),
        "train_window_counts_by_class": class_count_dict(train_labels, class_names),
        "test_window_counts_by_class": class_count_dict(test_labels, class_names),
        "train_recording_counts_by_class": recording_counts_by_class(metadata, train_indices, class_names),
        "test_recording_counts_by_class": recording_counts_by_class(metadata, test_indices, class_names),
        "train_recordings_list": recording_lists(metadata, train_indices),
        "test_recordings_list": recording_lists(metadata, test_indices),
    }
    return np.asarray(train_indices, dtype=np.int64), np.asarray(test_indices, dtype=np.int64), summary, []


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict | list) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classes-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/prepared_ti_pose_dataset"))
    parser.add_argument("--window-size", type=int, default=8)
    parser.add_argument("--min-points", type=int, default=5)
    parser.add_argument("--split-mode", choices=["recording", "window"], default="recording")
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--balance-mode", choices=["none", "downsample", "weighted"], default="none")
    parser.add_argument("--target-windows-per-class", type=int)
    parser.add_argument("--exclude-suspicious", type=Path)
    parser.add_argument("--include-classes", nargs="+", help="Only include these TI classes, remapped to contiguous IDs.")
    parser.add_argument("--exclude-classes", nargs="+", default=[], help="Skip these TI classes entirely.")
    parser.add_argument("--min-windows-per-recording", type=int, default=20)
    parser.add_argument("--max-abs-position", type=float, default=5.0)
    parser.add_argument("--max-abs-velocity", type=float, default=5.0)
    parser.add_argument("--max-abs-acceleration", type=float, default=10.0)
    parser.add_argument("--min-snr", type=float, default=0.0)
    parser.add_argument("--max-snr", type=float, default=100.0)
    args = parser.parse_args()

    if args.window_size != 8:
        print("Warning: TI Pose/Fall model expects window-size 8.")
    if args.min_points != REQUIRED_POINT_COUNT:
        print(f"Warning: TI feature format requires {REQUIRED_POINT_COUNT} selected points per frame; --min-points is informational.")

    active_class_names, requested_include_classes, excluded_class_names = resolve_active_classes(
        args.include_classes,
        args.exclude_classes,
    )
    class_to_id = {class_name: index for index, class_name in enumerate(active_class_names)}

    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded = read_exclusions(args.exclude_suspicious)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp_dir = Path(tmp_name)
        with zipfile.ZipFile(args.classes_zip) as archive:
            archive.extractall(tmp_dir)
        classes_root = tmp_dir / "classes"
        if not classes_root.exists():
            classes_root = tmp_dir

        features, labels, metadata, removed, excluded_recordings, source_summary = generate_windows(
            classes_root,
            args,
            excluded,
            active_class_names,
            excluded_class_names,
        )

    raw_total_windows = int(sum(source_summary["raw_windows_per_class"].values()))
    clean_total_before_balance = int(sum(source_summary["clean_windows_per_class"].values()))
    features, labels, metadata = apply_balance(features, labels, metadata, args.balance_mode, args.target_windows_per_class, args.seed)

    if not features:
        raise RuntimeError("No clean windows were generated. Check column aliases, thresholds, and excluded recordings.")

    x_array = np.asarray(features, dtype=np.float32)
    y_array = np.asarray(labels, dtype=np.int64)
    if args.split_mode == "recording":
        train_indices, test_indices, split_summary, split_rows = split_recordings(
            metadata,
            labels,
            args.test_size,
            args.seed,
            active_class_names,
        )
    else:
        train_indices, test_indices, split_summary, split_rows = split_windows(
            metadata,
            labels,
            args.test_size,
            args.seed,
            active_class_names,
        )

    np.save(output_dir / "X.npy", x_array)
    np.save(output_dir / "y.npy", y_array)
    np.save(output_dir / "train_indices.npy", train_indices)
    np.save(output_dir / "test_indices.npy", test_indices)
    write_json(
        output_dir / "feature_names_176.json",
        {
            "feature_names_176": FEATURE_NAMES_176,
            "class_names": active_class_names,
            "class_to_id": class_to_id,
        },
    )

    write_csv(
        output_dir / "metadata.csv",
        metadata,
        [
            "sample_id",
            "class_name",
            "class_id",
            "recording_id",
            "source_csv",
            "window_start_row",
            "window_end_row",
            "min_valid_points",
            "mean_valid_points",
        ],
    )
    write_csv(
        output_dir / "removed_windows.csv",
        removed,
        ["sample_id", "class_name", "class_id", "recording_id", "source_csv", "window_start_row", "window_end_row", "reason"],
    )
    write_csv(
        output_dir / "excluded_recordings.csv",
        excluded_recordings,
        ["class_name", "class_id", "recording_id", "source_csv", "rows", "raw_windows", "clean_windows", "reason", "warnings", "imputed_columns"],
    )
    write_csv(output_dir / "split_recordings.csv", split_rows, ["recording_id", "class_name", "split"])

    dataset_summary = {
        "num_samples": int(len(x_array)),
        "num_classes": len(active_class_names),
        "class_names": active_class_names,
        "class_to_id": class_to_id,
        "included_classes": active_class_names,
        "requested_include_classes": requested_include_classes,
        "excluded_classes": excluded_class_names,
        "walking_removed": "WALKING" in excluded_class_names,
        "skipped_windows_by_excluded_class": source_summary["skipped_windows_by_excluded_class"],
        "input_size": INPUT_SIZE,
        "window_size": args.window_size,
        "min_points": args.min_points,
        "split_mode": args.split_mode,
        "balance_mode": args.balance_mode,
        "target_windows_per_class": args.target_windows_per_class,
        "test_size": args.test_size,
        "seed": args.seed,
        "class_counts": class_count_dict(y_array, active_class_names),
        "raw_windows_per_class": source_summary["raw_windows_per_class"],
        "clean_windows_per_class": source_summary["clean_windows_per_class"],
        "removed_windows_per_class": source_summary["removed_windows_per_class"],
        "raw_total_windows": raw_total_windows,
        "clean_total_windows_before_balance": clean_total_before_balance,
        "removed_windows": int(len(removed)),
        "excluded_recordings": excluded_recordings,
        "excluded_recording_count": int(len(excluded_recordings)),
        "imputed_columns": source_summary["imputed_columns"],
        "recordings_per_class": source_summary["recordings_per_class"],
        "included_recordings_per_class": source_summary["included_recordings_per_class"],
        "train_class_counts": class_count_dict(y_array[train_indices], active_class_names),
        "test_class_counts": class_count_dict(y_array[test_indices], active_class_names),
        "class_weights_balanced": {
            class_name: float(len(y_array) / (len(active_class_names) * max(1, count)))
            for class_name, count in class_count_dict(y_array, active_class_names).items()
        },
        "cleaning_thresholds": {
            "max_abs_position": args.max_abs_position,
            "max_abs_velocity": args.max_abs_velocity,
            "max_abs_acceleration": args.max_abs_acceleration,
            "min_snr": args.min_snr,
            "max_snr": args.max_snr,
            "min_windows_per_recording": args.min_windows_per_recording,
        },
        "feature_names_22": FEATURE_NAMES_22,
        "feature_names_176": FEATURE_NAMES_176,
        "flatten_order": FLATTEN_ORDER,
    }
    write_json(output_dir / "dataset_summary.json", dataset_summary)
    write_json(output_dir / "split_summary.json", split_summary)

    removed_count = int(len(removed))
    print(f"Prepared dataset: {output_dir}")
    print(f"  included_classes={active_class_names}")
    print(f"  excluded_classes={excluded_class_names}")
    print(f"  skipped_windows_by_excluded_class={source_summary['skipped_windows_by_excluded_class']}")
    print(f"  raw_total_windows={raw_total_windows}")
    print(f"  clean_total_windows_before_balance={clean_total_before_balance}")
    print(f"  final_windows={len(x_array)}")
    print(f"  removed_windows={removed_count}")
    print(f"  excluded_recordings={len(excluded_recordings)}")
    print(f"  clean_windows_per_class={source_summary['clean_windows_per_class']}")
    print(f"  train_windows_per_class={split_summary['train_window_counts_by_class']}")
    print(f"  test_windows_per_class={split_summary['test_window_counts_by_class']}")
    print(f"  train_recordings_per_class={split_summary['train_recording_counts_by_class']}")
    print(f"  test_recordings_per_class={split_summary['test_recording_counts_by_class']}")
    print(f"  imputed_columns={source_summary['imputed_columns']}")
    if raw_total_windows and removed_count / raw_total_windows > 0.25:
        print("Warning: cleaning removed more than 25% of raw windows. Inspect removed_windows.csv and excluded_recordings.csv.")


if __name__ == "__main__":
    main()
