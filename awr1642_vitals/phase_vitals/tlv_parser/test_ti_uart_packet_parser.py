from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
PHASE_DIR = THIS_DIR.parent
for path in (THIS_DIR, PHASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fake_ti_uart_packet import (  # noqa: E402
    build_fake_frame_packet,
    build_fake_vital_phase_packet,
    build_fake_vital_phase_stream,
    make_fake_vital_phase_sample,
)
from parse_vital_phase_tlv import (  # noqa: E402
    VITAL_PHASE_TRACE_TLV_ID,
    pack_fake_vital_phase_payload,
)
from phase_vitals_estimator import estimate_vitals_from_phase  # noqa: E402
from ti_uart_packet_parser import (  # noqa: E402
    extract_vital_phase_tlvs,
    parse_uart_stream_for_vital_phase,
)


def _near(value: float, expected: float, tolerance: float) -> bool:
    return abs(float(value) - float(expected)) <= tolerance


def test_single_packet_roundtrip() -> None:
    sample = make_fake_vital_phase_sample(frame_number=7, fs=20.0)
    packet = build_fake_vital_phase_packet(7, sample)
    records = extract_vital_phase_tlvs(packet)
    assert len(records) == 1
    parsed = records[0]
    assert parsed.frame_number == 7
    assert parsed.range_bin_index_phase == sample.range_bin_index_phase
    assert math.isclose(parsed.range_meters, sample.range_meters, rel_tol=1e-6)
    assert math.isclose(parsed.phase_rad, sample.phase_rad, rel_tol=1e-6, abs_tol=1e-6)


def test_stream_and_estimator() -> None:
    fs = 20.0
    stream = build_fake_vital_phase_stream(duration_s=50.0, fs=fs)
    records = parse_uart_stream_for_vital_phase(stream)
    assert len(records) == 1000
    phase = np.asarray([record.phase_rad for record in records], dtype=float)
    estimates = estimate_vitals_from_phase(phase, fs)
    assert _near(estimates.breathing_rate_fft_bpm, 15.0, 1.5)
    assert _near(estimates.heart_rate_fft_bpm, 72.0, 2.0)
    print(f"fake_uart_samples={len(records)}")
    print(f"fake_uart_breath_fft_bpm={estimates.breathing_rate_fft_bpm:.3f}")
    print(f"fake_uart_heart_fft_bpm={estimates.heart_rate_fft_bpm:.3f}")


def test_garbage_unknown_and_partial() -> None:
    sample = make_fake_vital_phase_sample(frame_number=3, fs=20.0)
    custom_payload = pack_fake_vital_phase_payload(sample)
    unknown_payload = b"unknown"
    packet = build_fake_frame_packet(
        3,
        [
            (0x12345678, unknown_payload),
            (VITAL_PHASE_TRACE_TLV_ID, custom_payload),
        ],
    )
    stream = b"garbage before magic" + packet + packet[:18]
    records = parse_uart_stream_for_vital_phase(stream)
    assert len(records) == 1
    assert records[0].frame_number == 3


def main() -> None:
    test_single_packet_roundtrip()
    test_stream_and_estimator()
    test_garbage_unknown_and_partial()
    print("TI UART packet parser tests passed")


if __name__ == "__main__":
    main()
