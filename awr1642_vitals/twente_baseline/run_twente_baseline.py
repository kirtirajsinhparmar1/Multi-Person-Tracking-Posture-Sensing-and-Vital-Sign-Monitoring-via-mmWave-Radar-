from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

try:
    from .load_twente_sample import (
        find_candidate_files,
        load_metadata,
        load_processed_displacement,
        load_reference_labels,
    )
    from .vital_signal_baseline import estimate_breath_and_heart_from_displacement, estimate_to_dict
except ImportError:
    from load_twente_sample import (
        find_candidate_files,
        load_metadata,
        load_processed_displacement,
        load_reference_labels,
    )
    from vital_signal_baseline import estimate_breath_and_heart_from_displacement, estimate_to_dict


DEFAULT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "external_research"
    / "data"
    / "twente_4tu_sample"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an offline vital-sign baseline on a Twente/4TU sample.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Twente sample folder.")
    parser.add_argument("--signal-file", help="Processed chest displacement file. If omitted, the first candidate is used.")
    parser.add_argument("--reference-file", help="Reference HR/RR label file. If omitted, the first candidate is used.")
    parser.add_argument("--fs", type=float, help="Processed displacement sample rate in Hz.")
    parser.add_argument("--out", help="Optional output directory for JSON/CSV results.")
    parser.add_argument("--plot", action="store_true", help="Save a small displacement/estimate plot if matplotlib is installed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    metadata = load_metadata(root)
    candidates = find_candidate_files(root)

    print(f"Twente sample root: {root}")
    print(f"Root exists: {root.exists()}")
    for key in (
        "readme_metadata",
        "processed_displacement",
        "range_maps",
        "raw_adc",
        "reference_labels",
        "cfg_capture_metadata",
    ):
        print(f"{key}: {len(candidates.get(key, []))}")

    signal_path = _resolve_optional_file(root, args.signal_file)
    if signal_path is None:
        first_signal = _first_candidate(root, candidates.get("processed_displacement", []))
        signal_path = first_signal

    if signal_path is None:
        print("No processed displacement file found. Add a sample file or pass --signal-file.")
        return 2

    fs = args.fs or metadata.get("sample_rate_hz")
    if not fs:
        print("No sample rate found. Pass --fs, for example --fs 20.")
        return 2

    displacement, signal_meta = load_processed_displacement(signal_path)
    estimate = estimate_breath_and_heart_from_displacement(displacement, float(fs))

    reference = None
    reference_path = _resolve_optional_file(root, args.reference_file)
    if reference_path is None:
        reference_path = _first_candidate(root, candidates.get("reference_labels", []))
    if reference_path is not None:
        try:
            reference = load_reference_labels(reference_path)
        except Exception as exc:
            print(f"Reference file found but could not be parsed: {reference_path} ({exc})")

    print("")
    print("Estimate")
    print(f"  breathing: {_fmt_bpm(estimate.breathing_bpm)}")
    print(f"  heart:     {_fmt_bpm(estimate.heart_bpm)}")
    print(f"  duration:  {estimate.duration_s:.1f} s")
    print(f"  fs:        {estimate.fs_hz:g} Hz")

    if reference:
        print("")
        print("Reference")
        print(f"  breathing: {_fmt_bpm(reference.breathing_bpm)}")
        print(f"  heart:     {_fmt_bpm(reference.heart_bpm)}")
        print("")
        print("Difference")
        print(f"  breathing: {_fmt_diff(estimate.breathing_bpm, reference.breathing_bpm)}")
        print(f"  heart:     {_fmt_diff(estimate.heart_bpm, reference.heart_bpm)}")

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_outputs(out_dir, root, signal_path, signal_meta, estimate, reference, metadata, candidates)
        if args.plot:
            _write_plot(out_dir, displacement, float(fs), estimate)
        print(f"Saved results to: {out_dir}")
    elif args.plot:
        _write_plot(Path("."), displacement, float(fs), estimate)
        print("Saved plot to current directory.")

    return 0


def _resolve_optional_file(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        direct = Path(value)
        path = direct if direct.exists() else root / value
    return path


def _first_candidate(root: Path, rel_paths: list[str]) -> Path | None:
    if not rel_paths:
        return None
    return root / rel_paths[0]


def _write_outputs(
    out_dir: Path,
    root: Path,
    signal_path: Path,
    signal_meta: dict,
    estimate,
    reference,
    metadata: dict,
    candidates: dict[str, list[str]],
) -> None:
    payload = {
        "root": str(root),
        "signal_file": str(signal_path),
        "signal_metadata": signal_meta,
        "estimate": estimate_to_dict(estimate),
        "reference": asdict(reference) if reference else None,
        "metadata": metadata,
        "candidate_counts": {key: len(value) for key, value in candidates.items() if isinstance(value, list)},
    }
    (out_dir / "twente_baseline_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with (out_dir / "twente_baseline_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "signal_file",
                "breathing_bpm",
                "heart_bpm",
                "reference_breathing_bpm",
                "reference_heart_bpm",
                "fs_hz",
                "duration_s",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "signal_file": str(signal_path),
                "breathing_bpm": estimate.breathing_bpm,
                "heart_bpm": estimate.heart_bpm,
                "reference_breathing_bpm": reference.breathing_bpm if reference else None,
                "reference_heart_bpm": reference.heart_bpm if reference else None,
                "fs_hz": estimate.fs_hz,
                "duration_s": estimate.duration_s,
            }
        )


def _write_plot(out_dir: Path, displacement, fs: float, estimate) -> None:
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        print(f"Plot skipped: matplotlib is not available ({exc})")
        return

    t = np.arange(len(displacement)) / fs
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, displacement, linewidth=1)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Displacement / phase units")
    ax.set_title(
        f"Twente baseline: breath={_fmt_bpm(estimate.breathing_bpm)}, heart={_fmt_bpm(estimate.heart_bpm)}"
    )
    fig.tight_layout()
    fig.savefig(out_dir / "twente_baseline_signal.png", dpi=150)
    plt.close(fig)


def _fmt_bpm(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f} bpm"


def _fmt_diff(value: float | None, reference: float | None) -> str:
    if value is None or reference is None:
        return "-"
    return f"{value - reference:+.1f} bpm"


if __name__ == "__main__":
    raise SystemExit(main())
