from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vital_model_training.features import (  # noqa: E402
    as_float,
    discover_trace_files,
    elapsed_seconds,
    extract_features,
    infer_sample_rate,
    read_trace,
    valid_locked_row,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build supervised-learning windows from UART FE03 chest-beam logs."
    )
    parser.add_argument("--logs", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--window-sec", type=float, default=30.0)
    parser.add_argument("--stride-sec", type=float, default=5.0)
    parser.add_argument("--include-60-sec", action="store_true")
    parser.add_argument("--labels")
    parser.add_argument("--min-valid-fraction", type=float, default=0.9)
    parser.add_argument("--min-fe03-active-fraction", type=float, default=0.8)
    parser.add_argument("--min-selected-magnitude", type=float, default=0.0)
    return parser


def _label_rows(path: str | None) -> list[dict[str, str]]:
    if not path:
        return []
    label_path = Path(path).expanduser()
    if not label_path.exists():
        return []
    with label_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _matching_label(labels, recording_id, start_sec, end_sec):
    midpoint = 0.5 * (start_sec + end_sec)
    for row in labels:
        if row.get("recording_id") != recording_id:
            continue
        start = as_float(row.get("start_time_sec"), float("-inf"))
        end = as_float(row.get("end_time_sec"), float("inf"))
        if start <= midpoint <= end:
            return row
    return None


def _resample(time_sec, values, target_time):
    return np.interp(target_time, time_sec, values).astype(np.float32)


def build_dataset(
    log_paths,
    out_dir,
    window_sec=30.0,
    stride_sec=5.0,
    include_60_sec=False,
    labels_path=None,
    min_valid_fraction=0.9,
    min_fe03_active_fraction=0.8,
    min_selected_magnitude=0.0,
):
    if window_sec <= 0 or stride_sec <= 0:
        raise ValueError("window and stride must be positive")
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    traces = discover_trace_files(log_paths)
    labels = _label_rows(labels_path)
    feature_rows: list[dict] = []
    metadata_rows: list[dict] = []
    arrays = {
        "raw_phase": [],
        "unwrapped_phase": [],
        "displacement": [],
        "breathing_filtered": [],
        "heart_filtered": [],
    }
    window_lengths = [float(window_sec)]
    if include_60_sec and 60.0 not in window_lengths:
        window_lengths.append(60.0)
    skipped = 0

    for trace_path in traces:
        rows = read_trace(trace_path)
        if not rows:
            continue
        elapsed = elapsed_seconds(rows)
        recording_id = trace_path.parent.name
        segment_values = sorted(
            {
                int(as_float(row.get("phaseSegmentId")))
                for row in rows
                if valid_locked_row(row)
            }
        )
        for segment_id in segment_values:
            indices = [
                index
                for index, row in enumerate(rows)
                if valid_locked_row(row)
                and int(as_float(row.get("phaseSegmentId"))) == segment_id
            ]
            if len(indices) < 2:
                continue
            segment_time = elapsed[indices]
            finite_time = np.isfinite(segment_time)
            indices = [index for index, keep in zip(indices, finite_time) if keep]
            segment_time = segment_time[finite_time]
            if len(indices) < 2:
                continue
            fs = infer_sample_rate(segment_time)
            for length_sec in window_lengths:
                start = float(segment_time[0])
                final_start = float(segment_time[-1] - length_sec)
                while start <= final_start + 1e-6:
                    end = start + length_sec
                    selected = [
                        index
                        for index in indices
                        if start <= elapsed[index] < end
                    ]
                    expected = max(2, int(round(length_sec * fs)))
                    if len(selected) < expected * min_valid_fraction:
                        skipped += 1
                        start += stride_sec
                        continue
                    window_time = elapsed[selected]
                    if np.any(np.diff(window_time) <= 0):
                        skipped += 1
                        start += stride_sec
                        continue
                    target_time = np.linspace(start, end, expected, endpoint=False)
                    raw = np.asarray(
                        [as_float(rows[i].get("lockedPhaseRaw")) for i in selected]
                    )
                    unwrapped = np.asarray(
                        [
                            as_float(rows[i].get("lockedPhaseUnwrapped"))
                            for i in selected
                        ]
                    )
                    displacement = np.asarray(
                        [as_float(rows[i].get("displacementMm")) for i in selected]
                    )
                    magnitude = np.asarray(
                        [as_float(rows[i].get("lockedMagnitude"), 0.0) for i in selected]
                    )
                    range_m = np.asarray(
                        [as_float(rows[i].get("lockedRangeMeters"), 0.0) for i in selected]
                    )
                    azimuth = np.asarray(
                        [as_float(rows[i].get("lockedAzimuthDeg"), 0.0) for i in selected]
                    )
                    if not all(
                        np.all(np.isfinite(value))
                        for value in (raw, unwrapped, displacement)
                    ):
                        skipped += 1
                        start += stride_sec
                        continue
                    fe03_active_fraction = float(
                        np.mean(
                            [
                                rows[i].get("fe03StreamState") == "FE03_ACTIVE"
                                for i in selected
                            ]
                        )
                    )
                    if fe03_active_fraction < min_fe03_active_fraction:
                        skipped += 1
                        start += stride_sec
                        continue
                    if float(np.mean(magnitude)) < min_selected_magnitude:
                        skipped += 1
                        start += stride_sec
                        continue
                    raw_i = _resample(window_time, raw, target_time)
                    unwrapped_i = _resample(window_time, unwrapped, target_time)
                    displacement_i = _resample(
                        window_time, displacement, target_time
                    )
                    magnitude_i = _resample(window_time, magnitude, target_time)
                    range_i = _resample(window_time, range_m, target_time)
                    azimuth_i = _resample(window_time, azimuth, target_time)
                    first = rows[selected[0]]
                    metadata = {
                        "window_sec": length_sec,
                        "beam_lock_duration_sec": length_sec,
                        "beam_switch_count": 0.0,
                        "fe03_active_fraction": fe03_active_fraction,
                        "seated_fraction": float(
                            np.mean(
                                [
                                    (
                                        rows[i].get("gatePosture")
                                        or rows[i].get("stablePosture")
                                    )
                                    == "SITTING"
                                    for i in selected
                                ]
                            )
                        ),
                    }
                    features, signals = extract_features(
                        displacement_i,
                        raw_i,
                        unwrapped_i,
                        magnitude_i,
                        range_i,
                        azimuth_i,
                        fs,
                        metadata,
                    )
                    row = {
                        "recording_id": recording_id,
                        "source_csv": str(trace_path),
                        "target_id": first.get("targetId", ""),
                        "phase_segment_id": segment_id,
                        "start_time_sec": start,
                        "end_time_sec": end,
                        **features,
                    }
                    label = _matching_label(labels, recording_id, start, end)
                    if label:
                        row["reference_heart_bpm"] = label.get(
                            "reference_heart_bpm", ""
                        )
                        row["reference_breath_bpm"] = label.get(
                            "reference_breath_bpm", ""
                        )
                    feature_rows.append(row)
                    metadata_rows.append(
                        {
                            key: row[key]
                            for key in (
                                "recording_id",
                                "source_csv",
                                "target_id",
                                "phase_segment_id",
                                "start_time_sec",
                                "end_time_sec",
                                "window_sec",
                                "sample_rate_hz",
                                "sample_count",
                            )
                        }
                    )
                    for key in arrays:
                        arrays[key].append(signals[key].astype(np.float32))
                    start += stride_sec

    def write_csv(path, rows):
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        columns = list(rows[0])
        for row in rows[1:]:
            for key in row:
                if key not in columns:
                    columns.append(key)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(output / "training_windows.csv", metadata_rows)
    write_csv(output / "feature_table.csv", feature_rows)
    npz_payload = {}
    if feature_rows and len({len(item) for item in arrays["displacement"]}) == 1:
        npz_payload = {
            key: np.stack(value) for key, value in arrays.items()
        }
    else:
        npz_payload = {
            key: np.asarray(value, dtype=object) for key, value in arrays.items()
        }
    np.savez_compressed(output / "training_windows.npz", **npz_payload)
    summary = {
        "source_trace_count": len(traces),
        "window_count": len(feature_rows),
        "skipped_window_count": skipped,
        "window_lengths_sec": window_lengths,
        "stride_sec": stride_sec,
        "reference_labels_loaded": len(labels),
        "workflow": "AWR1642BOOST UART FE03 selected chest-beam phase",
    }
    (output / "dataset_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    args = build_arg_parser().parse_args()
    summary = build_dataset(
        args.logs,
        args.out,
        args.window_sec,
        args.stride_sec,
        args.include_60_sec,
        args.labels,
        args.min_valid_fraction,
        args.min_fe03_active_fraction,
        args.min_selected_magnitude,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
