"""Fake TI UART frame generator for the custom VitalPhaseTrace TLV."""

from __future__ import annotations

import math
import struct
from typing import Iterable, List, Tuple

import numpy as np

try:
    from .parse_vital_phase_bin_window_tlv import (
        VITAL_PHASE_BIN_WINDOW_TLV_ID,
        VitalPhaseBinSample,
        VitalPhaseBinWindow,
        pack_vital_phase_bin_window_payload,
    )
    from .parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        pack_fake_vital_phase_payload,
    )
    from .parse_vital_phase_virtual_ant_window_tlv import (
        VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID,
        VitalPhaseVirtualAntWindow,
        pack_vital_phase_virtual_ant_window_payload,
    )
    from .ti_uart_packet_parser import FRAME_HEADER_STRUCT, MAGIC_WORD, TLV_HEADER_STRUCT
    from .vital_phase_tlv_types import VitalPhaseTrace
except ImportError:  # Direct script execution from this folder.
    from parse_vital_phase_bin_window_tlv import (
        VITAL_PHASE_BIN_WINDOW_TLV_ID,
        VitalPhaseBinSample,
        VitalPhaseBinWindow,
        pack_vital_phase_bin_window_payload,
    )
    from parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        pack_fake_vital_phase_payload,
    )
    from parse_vital_phase_virtual_ant_window_tlv import (
        VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID,
        VitalPhaseVirtualAntWindow,
        pack_vital_phase_virtual_ant_window_payload,
    )
    from ti_uart_packet_parser import FRAME_HEADER_STRUCT, MAGIC_WORD, TLV_HEADER_STRUCT
    from vital_phase_tlv_types import VitalPhaseTrace


MMWDEMO_OUTPUT_MSG_SEGMENT_LEN = 32
FAKE_VERSION = 0x02000004
FAKE_PLATFORM_AWR1642 = 0xA1642


def _round_up(value: int, multiple: int) -> int:
    return multiple * ((value + multiple - 1) // multiple)


def build_tlv(tlv_type: int, payload: bytes) -> bytes:
    """Build one TI TLV. Length is payload length for this firmware path."""
    return TLV_HEADER_STRUCT.pack(int(tlv_type), len(payload)) + payload


def build_fake_frame_packet(
    frame_number: int, tlv_payloads: List[Tuple[int, bytes]]
) -> bytes:
    """Build one complete fake TI UART packet with padding."""
    tlv_bytes = b"".join(build_tlv(tlv_type, payload) for tlv_type, payload in tlv_payloads)
    raw_len = FRAME_HEADER_STRUCT.size + len(tlv_bytes)
    total_len = _round_up(raw_len, MMWDEMO_OUTPUT_MSG_SEGMENT_LEN)

    header = FRAME_HEADER_STRUCT.pack(
        MAGIC_WORD,
        FAKE_VERSION,
        total_len,
        FAKE_PLATFORM_AWR1642,
        int(frame_number),
        0,
        0,
        len(tlv_payloads),
        0,
    )
    return header + tlv_bytes + bytes(total_len - raw_len)


def build_fake_vital_phase_packet(frame_number: int, sample: VitalPhaseTrace) -> bytes:
    payload = pack_fake_vital_phase_payload(sample)
    return build_fake_frame_packet(frame_number, [(VITAL_PHASE_TRACE_TLV_ID, payload)])


def make_fake_vital_phase_bin_window(
    frame_number: int,
    start_bin: int = 20,
    num_bins: int = 41,
    range_resolution: float = 0.04739,
) -> VitalPhaseBinWindow:
    """Generate deterministic I/Q with a strongest sample at range bin 32."""
    samples = []
    for bin_index in range(start_bin, start_bin + num_bins):
        magnitude = 100.0 + max(0.0, 2000.0 - 250.0 * abs(bin_index - 32))
        phase = 0.02 * frame_number + 0.05 * bin_index
        samples.append(
            VitalPhaseBinSample(
                bin_index=bin_index,
                range_meters=bin_index * range_resolution,
                i_value=magnitude * math.cos(phase),
                q_value=magnitude * math.sin(phase),
                phase_rad=phase,
                magnitude=magnitude,
            )
        )
    return VitalPhaseBinWindow(
        frame_number=frame_number,
        start_bin=start_bin,
        num_bins=num_bins,
        range_resolution=range_resolution,
        samples=tuple(samples),
    )


def build_fake_vital_phase_bin_window_packet(
    frame_number: int,
    window: VitalPhaseBinWindow,
    fixed_sample: VitalPhaseTrace | None = None,
) -> bytes:
    """Build a packet containing 0xFE02 and optionally the existing 0xFE01."""
    tlvs = []
    if fixed_sample is not None:
        tlvs.append(
            (VITAL_PHASE_TRACE_TLV_ID, pack_fake_vital_phase_payload(fixed_sample))
        )
    tlvs.append(
        (
            VITAL_PHASE_BIN_WINDOW_TLV_ID,
            pack_vital_phase_bin_window_payload(window),
        )
    )
    return build_fake_frame_packet(frame_number, tlvs)


def make_fake_vital_phase_virtual_ant_window(
    frame_number: int,
    start_bin: int = 20,
    num_bins: int = 41,
    num_virtual_antennas: int = 8,
    range_resolution: float = 0.04739,
    source_bin: int = 37,
    source_azimuth_deg: float = 20.0,
    antenna_spacing_lambda: float = 0.5,
) -> VitalPhaseVirtualAntWindow:
    """Generate deterministic FE03 data with one coherent range/angle source."""
    bin_indices = np.arange(start_bin, start_bin + num_bins, dtype=np.int32)
    range_meters = bin_indices.astype(np.float32) * float(range_resolution)
    antenna_indices = np.arange(num_virtual_antennas, dtype=np.float64)
    phase_slope = (
        2.0
        * np.pi
        * float(antenna_spacing_lambda)
        * antenna_indices
        * np.sin(np.deg2rad(float(source_azimuth_deg)))
    )
    samples = np.zeros(
        (num_bins, num_virtual_antennas),
        dtype=np.complex64,
    )

    for row, bin_index in enumerate(bin_indices):
        magnitude = 300.0 + max(
            0.0,
            12000.0 - 2200.0 * abs(int(bin_index) - int(source_bin)),
        )
        common_phase = 0.03 * float(frame_number) + 0.01 * float(bin_index)
        signal = magnitude * np.exp(1j * (common_phase + phase_slope))
        samples[row, :] = np.rint(signal.real) + 1j * np.rint(signal.imag)

    return VitalPhaseVirtualAntWindow(
        frame_number=int(frame_number),
        start_bin=int(start_bin),
        num_bins=int(num_bins),
        num_virtual_antennas=int(num_virtual_antennas),
        flags=0,
        range_resolution=float(range_resolution),
        samples=samples,
        bin_indices=bin_indices,
        range_meters=range_meters,
    )


def build_fake_vital_phase_virtual_ant_window_packet(
    frame_number: int,
    window: VitalPhaseVirtualAntWindow,
    bin_window: VitalPhaseBinWindow | None = None,
    fixed_sample: VitalPhaseTrace | None = None,
) -> bytes:
    """Build a packet containing FE03 and optional backward-compatible TLVs."""
    tlvs = []
    if fixed_sample is not None:
        tlvs.append(
            (VITAL_PHASE_TRACE_TLV_ID, pack_fake_vital_phase_payload(fixed_sample))
        )
    if bin_window is not None:
        tlvs.append(
            (
                VITAL_PHASE_BIN_WINDOW_TLV_ID,
                pack_vital_phase_bin_window_payload(bin_window),
            )
        )
    tlvs.append(
        (
            VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID,
            pack_vital_phase_virtual_ant_window_payload(window),
        )
    )
    return build_fake_frame_packet(frame_number, tlvs)


def make_fake_vital_phase_sample(frame_number: int, fs: float) -> VitalPhaseTrace:
    """Generate the same synthetic phase trace used by the firmware experiment."""
    t = float(frame_number) / float(fs)
    phase = 0.8 * math.sin(2.0 * math.pi * 0.25 * t)
    phase += 0.08 * math.sin(2.0 * math.pi * 1.2 * t)
    return VitalPhaseTrace(
        frame_number=frame_number,
        range_bin_index_max=20,
        range_bin_index_phase=20,
        range_meters=1.5,
        i_value=math.cos(phase),
        q_value=math.sin(phase),
        phase_rad=phase,
        magnitude=1.0,
        snr_like=30.0,
        motion_detected=0,
        reserved=b"\x00\x00\x00",
    )


def build_fake_vital_phase_stream(duration_s: float, fs: float = 20.0) -> bytes:
    frame_count = max(0, int(round(float(duration_s) * float(fs))))
    packets = [
        build_fake_vital_phase_packet(frame, make_fake_vital_phase_sample(frame, fs))
        for frame in range(frame_count)
    ]
    return b"".join(packets)
