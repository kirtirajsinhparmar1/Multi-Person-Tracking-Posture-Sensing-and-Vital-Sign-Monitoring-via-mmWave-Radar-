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
from vital_phase_tlv_types import VitalPhaseTrace


def _assert_close(name, actual, expected, tolerance):
    if actual is None or abs(actual - expected) > tolerance:
        raise AssertionError(f"{name}: expected {expected} +/- {tolerance}, got {actual}")


def test_pack_parse_roundtrip():
    sample = VitalPhaseTrace(
        frame_number=123,
        range_bin_index_max=20,
        range_bin_index_phase=21,
        range_meters=1.5,
        i_value=0.9,
        q_value=0.1,
        phase_rad=0.11,
        magnitude=1.0,
        snr_like=30.0,
        motion_detected=0,
    )
    payload = pack_fake_vital_phase_payload(sample)
    parsed = parse_vital_phase_payload(payload)
    assert parsed.frame_number == sample.frame_number
    assert parsed.range_bin_index_max == sample.range_bin_index_max
    assert parsed.range_bin_index_phase == sample.range_bin_index_phase
    _assert_close("range_meters", parsed.range_meters, sample.range_meters, 1e-6)
    _assert_close("i_value", parsed.i_value, sample.i_value, 1e-6)
    _assert_close("q_value", parsed.q_value, sample.q_value, 1e-6)
    _assert_close("phase_rad", parsed.phase_rad, sample.phase_rad, 1e-6)
    assert parsed.motion_detected == sample.motion_detected


def test_synthetic_tlv_estimator():
    fs = 20.0
    duration = 50.0
    n = int(fs * duration)
    phases = []
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
        parsed = parse_vital_phase_payload(pack_fake_vital_phase_payload(sample))
        phases.append(parsed.phase_rad)

    estimates = estimate_vitals_from_phase(np.asarray(phases, dtype=float), fs)
    _assert_close("breathing FFT bpm", estimates.breathing_rate_fft_bpm, 15.0, 2.0)
    _assert_close("heart FFT bpm", estimates.heart_rate_fft_bpm, 72.0, 3.0)
    if estimates.quality_state == "INVALID":
        raise AssertionError("quality_state should not be INVALID")
    if estimates.motion_detected:
        raise AssertionError("motion_detected should be false for clean synthetic TLV stream")
    print(f"synthetic_tlv_breath_fft_bpm={estimates.breathing_rate_fft_bpm:.2f}")
    print(f"synthetic_tlv_heart_fft_bpm={estimates.heart_rate_fft_bpm:.2f}")
    print(f"synthetic_tlv_quality_state={estimates.quality_state}")


if __name__ == "__main__":
    test_pack_parse_roundtrip()
    test_synthetic_tlv_estimator()
    print("VitalPhaseTrace TLV parser tests passed")
