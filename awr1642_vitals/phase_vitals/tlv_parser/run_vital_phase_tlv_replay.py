import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
PHASE_DIR = THIS_DIR.parent
for path in (THIS_DIR, PHASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from parse_vital_phase_tlv import parse_vital_phase_payload, pack_fake_vital_phase_payload
from phase_vitals_estimator import estimate_vitals_from_phase
from run_phase_vitals_demo import print_estimates
from vital_phase_tlv_types import VitalPhaseTrace


def generate_fake_payloads(fs: float, duration: float):
    payloads = []
    n = int(fs * duration)
    for frame in range(n):
        t = frame / fs
        phase_rad = 0.8 * math.sin(2.0 * math.pi * 0.25 * t) + 0.08 * math.sin(2.0 * math.pi * 1.2 * t)
        sample = VitalPhaseTrace(
            frame_number=frame,
            range_bin_index_max=20,
            range_bin_index_phase=20,
            range_meters=1.5,
            i_value=math.cos(phase_rad),
            q_value=math.sin(phase_rad),
            phase_rad=phase_rad,
            magnitude=1.0,
            snr_like=30.0,
            motion_detected=0,
        )
        payloads.append(pack_fake_vital_phase_payload(sample))
    return payloads


def run_fake_replay(fs: float, duration: float):
    payloads = generate_fake_payloads(fs, duration)
    samples = [parse_vital_phase_payload(payload) for payload in payloads]
    phases = np.asarray([sample.phase_rad for sample in samples], dtype=float)
    estimates = estimate_vitals_from_phase(phases, fs)
    return samples, estimates


def main():
    parser = argparse.ArgumentParser(description="Replay fake AWR1642 VitalPhaseTrace TLV payloads.")
    parser.add_argument("--fake", action="store_true", help="Generate synthetic VitalPhaseTrace TLV payloads.")
    parser.add_argument("--fs", type=float, required=True, help="Slow-time sample/frame rate in Hz.")
    parser.add_argument("--duration", type=float, default=50.0, help="Synthetic replay duration in seconds.")
    parser.add_argument("--out", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    if not args.fake:
        raise SystemExit("Only --fake replay is implemented in this milestone.")

    samples, estimates = run_fake_replay(args.fs, args.duration)
    print(f"Generated and parsed {len(samples)} fake VitalPhaseTrace TLV payloads")
    print_estimates(estimates)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "mode": "fake",
                    "fs": args.fs,
                    "duration": args.duration,
                    "sample_count": len(samples),
                    "first_sample": samples[0].to_dict() if samples else None,
                    "estimates": estimates.to_dict(),
                },
                indent=2,
            )
        )
        print(f"Saved replay results: {out_path}")


if __name__ == "__main__":
    main()
