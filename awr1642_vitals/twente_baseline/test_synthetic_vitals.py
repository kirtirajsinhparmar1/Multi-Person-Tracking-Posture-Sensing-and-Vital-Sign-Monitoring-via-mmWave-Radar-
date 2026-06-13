from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vital_signal_baseline import estimate_breath_and_heart_from_displacement


def main() -> int:
    fs = 20.0
    duration_s = 40.0
    t = np.arange(int(fs * duration_s)) / fs
    breathing_hz = 0.25
    heart_hz = 1.2
    rng = np.random.default_rng(42)

    displacement = (
        1.0 * np.sin(2.0 * math.pi * breathing_hz * t)
        + 0.12 * np.sin(2.0 * math.pi * heart_hz * t)
        + 0.05 * rng.standard_normal(t.size)
    )

    estimate = estimate_breath_and_heart_from_displacement(displacement, fs)
    expected_breath_bpm = breathing_hz * 60.0
    expected_heart_bpm = heart_hz * 60.0

    print(f"Estimated breathing: {estimate.breathing_bpm:.2f} bpm")
    print(f"Estimated heart: {estimate.heart_bpm:.2f} bpm")

    assert estimate.breathing_bpm is not None
    assert estimate.heart_bpm is not None
    assert abs(estimate.breathing_bpm - expected_breath_bpm) <= 2.0
    assert abs(estimate.heart_bpm - expected_heart_bpm) <= 5.0
    print("Synthetic vital-sign baseline test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
