"""Offline validation for FE03 parsing and FE01/FE02 coexistence."""

from __future__ import annotations

import numpy as np

from fake_ti_uart_packet import (
    build_fake_vital_phase_virtual_ant_window_packet,
    make_fake_vital_phase_bin_window,
    make_fake_vital_phase_sample,
    make_fake_vital_phase_virtual_ant_window,
)
from parse_vital_phase_virtual_ant_window_tlv import (
    VITAL_PHASE_VIRTUAL_ANT_SAMPLE_STRUCT,
    VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT,
    pack_vital_phase_virtual_ant_window_payload,
    parse_vital_phase_virtual_ant_window_payload,
)
from ti_uart_packet_parser import (
    extract_vital_phase_bin_window_tlvs,
    extract_vital_phase_tlvs,
    extract_vital_phase_virtual_ant_window_tlvs,
    parse_frame_header,
    parse_uart_stream_for_vital_phase_virtual_ant_windows,
)


def test_payload_roundtrip() -> None:
    window = make_fake_vital_phase_virtual_ant_window(
        frame_number=17,
        source_bin=37,
        source_azimuth_deg=20.0,
    )
    payload = pack_vital_phase_virtual_ant_window_payload(window)
    assert len(payload) == (
        VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT.size
        + 41 * 8 * VITAL_PHASE_VIRTUAL_ANT_SAMPLE_STRUCT.size
    )
    parsed = parse_vital_phase_virtual_ant_window_payload(payload)
    assert parsed.frame_number == 17
    assert parsed.start_bin == 20
    assert parsed.num_bins == 41
    assert parsed.num_virtual_antennas == 8
    assert parsed.samples.shape == (41, 8)
    assert parsed.bin_indices.tolist() == list(range(20, 61))
    np.testing.assert_array_equal(parsed.samples, window.samples)


def test_full_packet_coexistence() -> None:
    frame_number = 23
    fe03 = make_fake_vital_phase_virtual_ant_window(frame_number)
    fe02 = make_fake_vital_phase_bin_window(frame_number)
    fixed = make_fake_vital_phase_sample(frame_number, fs=10.0)
    packet = build_fake_vital_phase_virtual_ant_window_packet(
        frame_number,
        fe03,
        bin_window=fe02,
        fixed_sample=fixed,
    )
    header = parse_frame_header(packet)
    assert header.num_tlvs == 3
    assert len(extract_vital_phase_tlvs(packet)) == 1
    assert len(extract_vital_phase_bin_window_tlvs(packet)) == 1
    parsed = extract_vital_phase_virtual_ant_window_tlvs(packet)
    assert len(parsed) == 1
    assert parsed[0].samples.shape == (41, 8)


def test_stream_resynchronization() -> None:
    packets = []
    for frame_number in range(3):
        window = make_fake_vital_phase_virtual_ant_window(frame_number)
        packets.append(
            build_fake_vital_phase_virtual_ant_window_packet(
                frame_number,
                window,
            )
        )
    stream = b"noise" + b"".join(packets) + packets[-1][:19]
    windows = parse_uart_stream_for_vital_phase_virtual_ant_windows(stream)
    assert [window.frame_number for window in windows] == [0, 1, 2]


def main() -> None:
    test_payload_roundtrip()
    test_full_packet_coexistence()
    test_stream_resynchronization()
    print("VitalPhaseVirtualAntWindow TLV parser tests passed")


if __name__ == "__main__":
    main()
