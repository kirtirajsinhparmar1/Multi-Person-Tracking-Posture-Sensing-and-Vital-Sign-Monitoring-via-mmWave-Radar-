"""Create segment-safe locked chest phase, displacement, and PSD plots."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dual_sensor_fusion.vital_estimator_bridge import (  # noqa: E402
    analyze_locked_vital_signal,
    build_segment_safe_phase,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plot the three locked chest-beam waveform diagnostics. "
            "PSD/heart-rate debugging is optional."
        )
    )
    parser.add_argument("csv_path", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--input", dest="input_path")
    parser.add_argument(
        "--summary",
        help="Optional phase_diagnostics_summary.csv for status annotation",
    )
    parser.add_argument("--out-dir", default="plots")
    parser.add_argument("--out", help="Legacy explicit PNG output path")
    parser.add_argument("--window-start-sec", type=float)
    parser.add_argument("--window-sec", type=float)
    parser.add_argument("--phase-visible-window-sec", type=float, default=60.0)
    parser.add_argument("--phase-segment-id", type=int)
    parser.add_argument(
        "--phase-chart-mode",
        choices=("displacement", "phase"),
        default="displacement",
    )
    parser.add_argument(
        "--component-chart-normalize",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--phase-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument(
        "--phase-unwrap-discontinuity-rad",
        type=float,
        default=np.pi,
    )
    parser.add_argument("--phase-gap-reset-sec", type=float, default=1.0)
    parser.add_argument("--carrier-frequency-ghz", type=float, default=77.0)
    parser.add_argument("--include-vitals-debug", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--title", default="Locked Chest Phase Diagnostics")
    return parser


def _number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value in ("", None, "None"):
        return float("nan")
    try:
        return float(value)
    except ValueError:
        return float("nan")


def load_trace(path: Path) -> dict[str, np.ndarray]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No data rows found in {path}")
    elapsed = np.asarray([_number(row, "elapsedSec") for row in rows])
    if not np.all(np.isfinite(elapsed)):
        timestamp = np.asarray([_number(row, "timestamp") for row in rows])
        finite = timestamp[np.isfinite(timestamp)]
        if finite.size == 0:
            raise ValueError("CSV contains no valid elapsedSec or timestamp values")
        elapsed = timestamp - finite[0]
    return {
        "time": elapsed,
        "raw": np.asarray([_number(row, "lockedPhaseRaw") for row in rows]),
        "unwrapped": np.asarray(
            [_number(row, "lockedPhaseUnwrapped") for row in rows]
        ),
        "displacement": np.asarray(
            [_number(row, "displacementMm") for row in rows]
        ),
        "segment": np.asarray(
            [_number(row, "phaseSegmentId") for row in rows]
        ),
        "valid": np.asarray(
            [
                str(row.get("phaseValid", "")).strip().lower()
                in {"1", "true", "yes"}
                for row in rows
            ]
        ),
        "beam_key": [
            (
                row.get("lockedRangeBin", ""),
                row.get("lockedAzimuthDeg", ""),
            )
            for row in rows
        ],
    }


def _plot_segments(axis, time_sec, values, segments, valid, **kwargs):
    finite = np.isfinite(time_sec) & np.isfinite(values) & valid
    for segment in np.unique(segments[np.isfinite(segments)]):
        mask = finite & (segments == segment)
        if np.any(mask):
            axis.plot(time_sec[mask], values[mask], **kwargs)


def _load_latest_summary(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    summary_path = Path(path).expanduser().resolve()
    if not summary_path.exists():
        return {}
    with summary_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-1] if rows else {}


def _load_summary_history(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    summary_path = Path(path).expanduser().resolve()
    if not summary_path.exists():
        return []
    with summary_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def create_plot(
    input_path,
    output_path=None,
    window_start_sec=None,
    window_sec=60.0,
    phase_segment_id=None,
    title="Locked Chest Phase Diagnostics",
    summary_path=None,
    *,
    phase_chart_mode="displacement",
    component_chart_normalize=True,
    phase_sign=1.0,
    phase_unwrap_discontinuity_rad=np.pi,
    phase_gap_reset_sec=1.0,
    carrier_frequency_ghz=77.0,
    include_vitals_debug=False,
):
    path = Path(input_path).expanduser().resolve()
    data = load_trace(path)
    phase = build_segment_safe_phase(
        data["raw"],
        data["time"],
        data["segment"],
        valid_mask=data["valid"],
        beam_keys=data["beam_key"],
        phase_sign=phase_sign,
        discontinuity_rad=phase_unwrap_discontinuity_rad,
        gap_reset_sec=phase_gap_reset_sec,
        reset_on_beam_switch=True,
        carrier_frequency_ghz=carrier_frequency_ghz,
    )
    mask = (
        data["valid"]
        & np.isfinite(data["segment"])
        & (phase.continuityIds >= 0)
    )
    if phase_segment_id is not None:
        mask &= data["segment"] == phase_segment_id
    if window_start_sec is None:
        valid_time = data["time"][mask]
        if valid_time.size:
            window_start_sec = max(
                float(valid_time[0]), float(valid_time[-1] - window_sec)
            )
        else:
            window_start_sec = 0.0
    mask &= data["time"] >= window_start_sec
    mask &= data["time"] <= window_start_sec + window_sec
    if not np.any(mask):
        raise ValueError("No valid locked-phase samples in the requested window")

    selected_time = data["time"][mask]
    selected_signal = (
        phase.displacementMm[mask]
        if phase_chart_mode == "displacement"
        else phase.relative[mask]
    )
    selected_segments = phase.continuityIds[mask]
    differences = np.diff(selected_time)
    differences = differences[differences > 1e-6]
    fs = float(1.0 / np.median(differences)) if differences.size else 10.0
    breath = np.full(selected_signal.shape, np.nan)
    heart = np.full(selected_signal.shape, np.nan)
    latest_analysis = None
    for segment in np.unique(selected_segments):
        segment_mask = selected_segments == segment
        values = selected_signal[segment_mask]
        if np.all(np.isfinite(values)):
            analysis = analyze_locked_vital_signal(values, fs)
            breath[segment_mask] = analysis.breathingFiltered
            heart[segment_mask] = analysis.heartFiltered
            if segment == selected_segments[-1]:
                latest_analysis = analysis
    current_segment = selected_segments[-1]
    if latest_analysis is None:
        latest_analysis = analyze_locked_vital_signal(
            selected_signal[selected_segments == current_segment], fs
        )
    summary = _load_latest_summary(summary_path)
    summary_history = _load_summary_history(summary_path)

    import matplotlib.pyplot as plt

    axis_count = 5 if include_vitals_debug else 3
    figure, axes = plt.subplots(
        axis_count,
        1,
        figsize=(15, 15 if include_vitals_debug else 10),
        squeeze=False,
    )
    axes = axes[:, 0]
    summary_note = ""
    if summary:
        summary_note = (
            f"\nBreath {summary.get('breathEstimateState', '--')} "
            f"conf={summary.get('breathConfidence', '--')} | "
            f"Heart {summary.get('heartEstimateState', '--')} "
            f"conf={summary.get('heartConfidence', '--')}"
        )
    figure.suptitle(title + summary_note)
    _plot_segments(
        axes[0],
        data["time"],
        phase.wrapped,
        phase.continuityIds,
        mask,
        color="#2a78c4",
        linewidth=1.0,
    )
    axes[0].set_title("Wrapped Phase")
    axes[0].set_ylabel("Phase (rad)")
    axes[0].set_ylim(-np.pi, np.pi)
    _plot_segments(
        axes[1],
        data["time"],
        phase.displacementMm
        if phase_chart_mode == "displacement"
        else phase.relative,
        phase.continuityIds,
        mask,
        color="#7652b8",
        linewidth=1.1,
    )
    axes[1].set_title(
        "Chest Displacement from Unwrapped Phase"
        if phase_chart_mode == "displacement"
        else "Unwrapped Phase"
    )
    axes[1].set_ylabel(
        "Displacement (mm)" if phase_chart_mode == "displacement" else "Phase (rad)"
    )

    def normalize(values):
        result = np.asarray(values, dtype=float).copy()
        finite = np.isfinite(result)
        scale = float(np.nanmax(np.abs(result[finite]))) if np.any(finite) else 0.0
        if component_chart_normalize and scale > 1e-12:
            result[finite] /= scale
        return result

    component_valid = np.ones(selected_time.shape, dtype=bool)
    _plot_segments(
        axes[2],
        selected_time,
        normalize(breath),
        selected_segments,
        component_valid,
        color="blue",
        linewidth=1.4,
        label="Estimated breathing-band component",
    )
    _plot_segments(
        axes[2],
        selected_time,
        normalize(heart),
        selected_segments,
        component_valid,
        color="red",
        linewidth=1.0,
        label="Estimated heart-band component",
    )
    axes[2].set_title("Breathing and Heartbeat Components")
    axes[2].set_ylabel(
        "Normalized amplitude"
        if component_chart_normalize
        else ("Displacement (mm)" if phase_chart_mode == "displacement" else "Phase (rad)")
    )
    axes[2].set_xlabel("Elapsed time (s)")
    axes[2].legend(loc="upper right", fontsize=8)

    if include_vitals_debug:
        bpm = latest_analysis.frequencyHz * 60.0
        power = latest_analysis.spectrumPower
        heart_bpm_axis = latest_analysis.heartFrequencyHz * 60.0
        heart_power = latest_analysis.heartSpectrumPower
        axes[3].plot(bpm, power, color="blue", label="Breath PSD")
        axes[3].plot(heart_bpm_axis, heart_power, color="red", label="Heart PSD")
        axes[3].axvspan(6, 30, color="blue", alpha=0.1)
        axes[3].axvspan(48, 120, color="red", alpha=0.1)
        axes[3].set_xlim(0, 150)
        axes[3].set_ylabel("Power")
        axes[3].set_xlabel("BPM")
        axes[3].set_title("Vitals PSD Debug")
        axes[3].legend(loc="upper right", fontsize=8)

    if include_vitals_debug and summary_history:
        summary_time = np.asarray(
            [_number(row, "elapsedSec") for row in summary_history],
            dtype=float,
        )
        raw_hr = np.asarray(
            [_number(row, "rawHeartCandidateBpm") for row in summary_history],
            dtype=float,
        )
        tracked_hr = np.asarray(
            [_number(row, "trackedHeartBpm") for row in summary_history],
            dtype=float,
        )
        displayed_hr = np.asarray(
            [_number(row, "displayedHeartBpm") for row in summary_history],
            dtype=float,
        )
        confidence = np.asarray(
            [_number(row, "heartConfidence") for row in summary_history],
            dtype=float,
        )
        summary_mask = (
            np.isfinite(summary_time)
            & (summary_time >= window_start_sec)
            & (summary_time <= window_start_sec + window_sec)
        )
        axes[4].plot(
            summary_time[summary_mask],
            raw_hr[summary_mask],
            color="#f0ad4e",
            alpha=0.75,
            label="Raw candidate",
        )
        axes[4].plot(
            summary_time[summary_mask],
            tracked_hr[summary_mask],
            color="#8b0000",
            linewidth=1.8,
            label="Tracked",
        )
        axes[4].plot(
            summary_time[summary_mask],
            displayed_hr[summary_mask],
            color="#d9534f",
            linestyle="--",
            label="Displayed",
        )
        axes[4].plot(
            summary_time[summary_mask],
            confidence[summary_mask] * 100.0,
            color="#6f42c1",
            linewidth=1.0,
            label="Confidence (%)",
        )
    elif include_vitals_debug:
        axes[4].text(
            0.5,
            0.5,
            "Pass --summary to plot raw/tracked/displayed HR history",
            ha="center",
            va="center",
            transform=axes[4].transAxes,
        )
    if include_vitals_debug:
        axes[4].set_ylabel("BPM / confidence %")
        axes[4].set_xlabel("Elapsed time (s)")
        axes[4].set_title("Heart Candidate Tracking Debug")
        axes[4].legend(loc="upper right", fontsize=8)
    for index, axis in enumerate(axes):
        axis.grid(True, alpha=0.25)
        if not include_vitals_debug or index != 3:
            axis.set_xlim(window_start_sec, window_start_sec + window_sec)
    figure.tight_layout()
    if output_path:
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output, dpi=160, bbox_inches="tight")
    return figure


def main() -> int:
    args = build_arg_parser().parse_args()
    input_path = args.input_path or args.csv_path
    if not input_path:
        raise SystemExit("--input is required")
    output = args.out
    if args.save and not output:
        output = str(
            Path(args.out_dir)
            / "locked_chest_phase_diagnostics.png"
        )
    window_sec = (
        args.phase_visible_window_sec
        if args.window_sec is None
        else args.window_sec
    )
    figure = create_plot(
        input_path,
        output,
        args.window_start_sec,
        window_sec,
        args.phase_segment_id,
        args.title,
        args.summary,
        phase_chart_mode=args.phase_chart_mode,
        component_chart_normalize=args.component_chart_normalize,
        phase_sign=args.phase_sign,
        phase_unwrap_discontinuity_rad=args.phase_unwrap_discontinuity_rad,
        phase_gap_reset_sec=args.phase_gap_reset_sec,
        carrier_frequency_ghz=args.carrier_frequency_ghz,
        include_vitals_debug=args.include_vitals_debug,
    )
    if output:
        print(Path(output).expanduser().resolve())
    if args.show or not output:
        import matplotlib.pyplot as plt

        plt.show()
    else:
        import matplotlib.pyplot as plt

        plt.close(figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
