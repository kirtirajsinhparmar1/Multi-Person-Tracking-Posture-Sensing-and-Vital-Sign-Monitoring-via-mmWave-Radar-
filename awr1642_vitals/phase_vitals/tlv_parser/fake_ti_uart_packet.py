"""Fake TI UART frame generator for the custom VitalPhaseTrace TLV."""

from __future__ import annotations

import math
import struct
from typing import Iterable, List, Tuple

try:
    from .parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        pack_fake_vital_phase_payload,
    )
    from .ti_uart_packet_parser import FRAME_HEADER_STRUCT, MAGIC_WORD, TLV_HEADER_STRUCT
    from .vital_phase_tlv_types import VitalPhaseTrace
except ImportError:  # Direct script execution from this folder.
    from parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        pack_fake_vital_phase_payload,
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
