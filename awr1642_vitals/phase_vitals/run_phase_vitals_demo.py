from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

try:
    from .phase_trace_io import load_iq_csv, load_phase_csv, save_estimates_json
    from .phase_vitals_estimator import estimate_vitals_from_phase
except ImportError:  # pragma: no cover - supports direct script execution
    from phase_trace_io import load_iq_csv, load_phase_csv, save_estimates_json
    from phase_vitals_estimator import estimate_vitals_from_phase


def make_synthetic_phase(fs: float, duration_s: float = 50.0) -> np.ndarray:
    t = np.arange(0.0, duration_s, 1.0 / fs)
    rng = np.random.default_rng(7)
    breathing = 0.35 * np.sin(2.0 * np.pi * 0.25 * t)
    heart = 0.08 * np.sin(2.0 * np.pi * 1.2 * t + 0.4)
    drift = 0.15 * np.sin(2.0 * np.pi * 0.025 * t)
    noise = rng.normal(0.0, 0.025, size=t.size)
    return breathing + heart + drift + noise


def _phase_from_window(window):
    return np.asarray([sample.phase_rad for sample in window.samples if sample.phase_rad is not None], dtype=float)


def _load_auto(path: Path, mode: str):
    if mode == "phase":
        return load_phase_csv(path)
    if mode == "iq":
        return load_iq_csv(path)
    try:
        return load_phase_csv(path)
    except Exception:
        return load_iq_csv(path)


def print_estimates(estimates) -> None:
    print(f"breathingRateEst_FFT: {estimates.breathing_rate_fft_bpm}")
    print(f"breathingEst_xCorr: {estimates.breathing_rate_xcorr_bpm}")
    print(f"breathingEst_peakCount: {estimates.breathing_rate_peak_count_bpm}")
    print(f"heartRateEst_FFT: {estimates.heart_rate_fft_bpm}")
    print(f"heartRateEst_FFT_4Hz: {estimates.heart_rate_fft_4hz_bpm}")
    print(f"heartRateEst_xCorr: {estimates.heart_rate_xcorr_bpm}")
    print(f"heartRateEst_peakCount: {estimates.heart_rate_peak_count_bpm}")
    print(f"confidenceMetricBreathOut: {estimates.confidence_breath}")
    print(f"confidenceMetricHeartOut: {estimates.confidence_heart}")
    print(f"sumEnergyBreathWfm: {estimates.breath_energy}")
    print(f"sumEnergyHeartWfm: {estimates.heart_energy}")
    print(f"motionDetectedFlag: {int(estimates.motion_detected)}")
    print(f"quality_state: {estimates.quality_state}")
    if estimates.notes:
        print(f"notes: {estimates.notes}")


def plot_phase(phase, fs: float, estimates) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"Plot skipped: matplotlib unavailable ({exc})")
        return
    t = np.arange(len(phase)) / fs
    plt.figure(figsize=(10, 4))
    plt.plot(t, phase)
    plt.xlabel("Time (s)")
    plt.ylabel("Phase (rad)")
    plt.title(
        "Phase vital signs: "
        f"breath={estimates.breathing_rate_fft_bpm:.1f} bpm, "
        f"heart={estimates.heart_rate_fft_bpm:.1f} bpm"
    )
    plt.tight_layout()
    plt.show()


def parse_args():
    parser = argparse.ArgumentParser(description="Estimate breathing and heart rate from AWR1642 phase or I/Q trace CSV.")
    parser.add_argument("--input", help="Optional phase or I/Q CSV file.")
    parser.add_argument("--fs", type=float, help="Sample/frame rate in Hz. Required unless discoverable from time column.")
    parser.add_argument("--mode", choices=["phase", "iq", "auto"], default="auto")
    parser.add_argument("--wavelength-m", type=float, help="Optional radar wavelength in meters for displacement conversion.")
    parser.add_argument("--out", help="Optional output JSON path.")
    parser.add_argument("--plot", action="store_true", help="Plot loaded/synthetic phase trace.")
    parser.add_argument("--synthetic", action="store_true", help="Run a synthetic 15 bpm breathing / 72 bpm heart signal.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.synthetic:
        if args.fs is None:
            raise SystemExit("--fs is required with --synthetic")
        phase = make_synthetic_phase(args.fs)
        fs = args.fs
    else:
        if not args.input:
            raise SystemExit("Provide --input or --synthetic")
        window = _load_auto(Path(args.input), args.mode)
        phase = _phase_from_window(window)
        fs = args.fs or window.fs_hz
        if fs is None:
            raise SystemExit("--fs is required when the CSV has no time column")

    estimates = estimate_vitals_from_phase(phase, fs, wavelength_m=args.wavelength_m)
    print_estimates(estimates)
    if args.out:
        save_estimates_json(args.out, estimates)
        print(f"Saved estimates: {args.out}")
    if args.plot:
        plot_phase(phase, fs, estimates)


if __name__ == "__main__":
    main()
