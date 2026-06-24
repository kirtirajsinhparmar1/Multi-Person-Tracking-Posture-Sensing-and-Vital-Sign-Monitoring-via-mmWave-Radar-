"""Offline validation for AWR1642 TLV 0xFE02 and 0xFE01 coexistence."""

from __future__ import annotations

import math

from fake_ti_uart_packet import (
    build_fake_vital_phase_bin_window_packet,
    make_fake_vital_phase_bin_window,
    make_fake_vital_phase_sample,
)
from parse_vital_phase_bin_window_tlv import (
    VITAL_PHASE_BIN_SAMPLE_STRUCT,
    VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT,
    pack_vital_phase_bin_window_payload,
    parse_vital_phase_bin_window_payload,
)
from ti_uart_packet_parser import (
    extract_vital_phase_bin_window_tlvs,
    extract_vital_phase_tlvs,
    parse_frame_header,
    parse_uart_stream_for_vital_phase_bin_windows,
)


def test_payload_roundtrip() -> None:
    window = make_fake_vital_phase_bin_window(frame_number=17)
    payload = pack_vital_phase_bin_window_payload(window)
    assert len(payload) == (
        VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT.size
        + 41 * VITAL_PHASE_BIN_SAMPLE_STRUCT.size
    )

    parsed = parse_vital_phase_bin_window_payload(payload)
    assert parsed.frame_number == 17
    assert parsed.start_bin == 20
    assert parsed.num_bins == 41
    assert len(parsed.samples) == 41
    assert parsed.samples[0].bin_index == 20
    assert parsed.samples[-1].bin_index == 60

    strongest = max(parsed.samples, key=lambda sample: sample.magnitude)
    assert strongest.bin_index == 32
    assert math.isclose(
        strongest.range_meters,
        32 * parsed.range_resolution,
        rel_tol=1e-6,
    )


def test_full_packet_with_fixed_tlv() -> None:
    frame_number = 23
    window = make_fake_vital_phase_bin_window(frame_number)
    fixed = make_fake_vital_phase_sample(frame_number, fs=10.0)
    packet = build_fake_vital_phase_bin_window_packet(frame_number, window, fixed)

    header = parse_frame_header(packet)
    assert header.frame_number == frame_number
    assert header.num_tlvs == 2
    assert len(extract_vital_phase_tlvs(packet)) == 1

    windows = extract_vital_phase_bin_window_tlvs(packet)
    assert len(windows) == 1
    assert windows[0].frame_number == frame_number
    assert windows[0].num_bins == 41


def test_stream_resynchronization() -> None:
    packets = []
    for frame_number in range(3):
        window = make_fake_vital_phase_bin_window(frame_number)
        packets.append(build_fake_vital_phase_bin_window_packet(frame_number, window))

    stream = b"noise-before-magic" + b"".join(packets) + packets[-1][:19]
    windows = parse_uart_stream_for_vital_phase_bin_windows(stream)
    assert [window.frame_number for window in windows] == [0, 1, 2]


def main() -> None:
    test_payload_roundtrip()
    test_full_packet_with_fixed_tlv()
    test_stream_resynchronization()
    print("VitalPhaseBinWindow TLV parser tests passed")


if __name__ == "__main__":
    main()
