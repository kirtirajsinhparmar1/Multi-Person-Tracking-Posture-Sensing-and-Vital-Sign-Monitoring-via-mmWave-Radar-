from __future__ import annotations

import numpy as np

try:
    from .phase_vitals_estimator import estimate_vitals_from_phase
except ImportError:  # pragma: no cover - supports direct script execution
    from phase_vitals_estimator import estimate_vitals_from_phase


def make_signal(fs=20.0, duration_s=50.0, motion=False):
    t = np.arange(0.0, duration_s, 1.0 / fs)
    rng = np.random.default_rng(11)
    phase = (
        0.35 * np.sin(2.0 * np.pi * 0.25 * t)
        + 0.08 * np.sin(2.0 * np.pi * 1.2 * t + 0.2)
        + 0.12 * np.sin(2.0 * np.pi * 0.02 * t)
        + rng.normal(0.0, 0.02, size=t.size)
    )
    if motion:
        phase[int(12 * fs) :] += 4.0
        phase[int(31 * fs) :] -= 5.0
    return phase


def main():
    fs = 20.0
    clean = estimate_vitals_from_phase(make_signal(fs=fs), fs)
    assert clean.breathing_rate_fft_bpm is not None
    assert clean.heart_rate_fft_bpm is not None
    assert abs(clean.breathing_rate_fft_bpm - 15.0) <= 2.0, clean
    assert abs(clean.heart_rate_fft_bpm - 72.0) <= 5.0, clean
    assert clean.quality_state != "INVALID", clean
    assert clean.motion_detected is False, clean

    corrupted = estimate_vitals_from_phase(make_signal(fs=fs, motion=True), fs)
    assert corrupted.motion_detected or corrupted.quality_state != "OK", corrupted

    print(
        "Synthetic test OK: "
        f"breath_fft={clean.breathing_rate_fft_bpm:.2f} bpm, "
        f"heart_fft={clean.heart_rate_fft_bpm:.2f} bpm, "
        f"motion_corrupted_detected={corrupted.motion_detected}, "
        f"motion_quality={corrupted.quality_state}"
    )


if __name__ == "__main__":
    main()
