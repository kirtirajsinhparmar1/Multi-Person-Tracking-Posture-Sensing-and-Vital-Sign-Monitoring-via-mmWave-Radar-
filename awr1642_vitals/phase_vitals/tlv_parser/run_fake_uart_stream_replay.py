from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
PHASE_DIR = THIS_DIR.parent
for path in (THIS_DIR, PHASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fake_ti_uart_packet import build_fake_vital_phase_stream  # noqa: E402
from phase_vitals_estimator import estimate_vitals_from_phase  # noqa: E402
from run_phase_vitals_demo import print_estimates  # noqa: E402
from ti_uart_packet_parser import parse_uart_stream_for_vital_phase  # noqa: E402


def _estimate_to_dict(estimates) -> dict:
    return {
        "breathingRateEst_FFT": estimates.breathing_rate_fft_bpm,
        "breathingEst_xCorr": estimates.breathing_rate_xcorr_bpm,
        "breathingEst_peakCount": estimates.breathing_rate_peak_count_bpm,
        "heartRateEst_FFT": estimates.heart_rate_fft_bpm,
        "heartRateEst_FFT_4Hz": estimates.heart_rate_fft_4hz_bpm,
        "heartRateEst_xCorr": estimates.heart_rate_xcorr_bpm,
        "heartRateEst_peakCount": estimates.heart_rate_peak_count_bpm,
        "confidenceMetricBreathOut": estimates.confidence_breath,
        "confidenceMetricHeartOut": estimates.confidence_heart,
        "sumEnergyBreathWfm": estimates.breath_energy,
        "sumEnergyHeartWfm": estimates.heart_energy,
        "motionDetectedFlag": int(estimates.motion_detected),
        "quality_state": estimates.quality_state,
        "notes": estimates.notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a fake TI UART stream containing VitalPhaseTrace TLVs."
    )
    parser.add_argument("--fs", type=float, default=20.0, help="Frame/sample rate in Hz.")
    parser.add_argument("--duration", type=float, default=50.0, help="Duration in seconds.")
    parser.add_argument("--out", type=Path, default=None, help="Optional output JSON path.")
    args = parser.parse_args()

    stream = build_fake_vital_phase_stream(duration_s=args.duration, fs=args.fs)
    records = parse_uart_stream_for_vital_phase(stream)
    if not records:
        raise RuntimeError("No VitalPhaseTrace records parsed from fake stream")

    phase = np.asarray([record.phase_rad for record in records], dtype=float)
    estimates = estimate_vitals_from_phase(phase, args.fs)

    print(f"Parsed VitalPhaseTrace samples: {len(records)}")
    print_estimates(estimates)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fs": args.fs,
            "duration": args.duration,
            "samples": len(records),
            "estimates": _estimate_to_dict(estimates),
        }
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
