"""TI mmWave UART frame parser for the custom VitalPhaseTrace TLV.

This parser targets the xWR16xx non-OS output packet layout used by the copied
AWR1642 firmware experiment. The packet header is kept isolated here so it can
be adjusted if the firmware base changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import List

try:
    from .parse_vital_phase_bin_window_tlv import (
        VITAL_PHASE_BIN_WINDOW_TLV_ID,
        VitalPhaseBinWindow,
        parse_vital_phase_bin_window_payload,
    )
    from .parse_vital_phase_virtual_ant_window_tlv import (
        VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID,
        VitalPhaseVirtualAntWindow,
        parse_vital_phase_virtual_ant_window_payload,
    )
    from .parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        parse_vital_phase_payload,
    )
    from .vital_phase_tlv_types import VitalPhaseTrace
except ImportError:  # Direct script execution from this folder.
    from parse_vital_phase_bin_window_tlv import (
        VITAL_PHASE_BIN_WINDOW_TLV_ID,
        VitalPhaseBinWindow,
        parse_vital_phase_bin_window_payload,
    )
    from parse_vital_phase_virtual_ant_window_tlv import (
        VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID,
        VitalPhaseVirtualAntWindow,
        parse_vital_phase_virtual_ant_window_payload,
    )
    from parse_vital_phase_tlv import (
        VITAL_PHASE_TRACE_TLV_ID,
        parse_vital_phase_payload,
    )
    from vital_phase_tlv_types import VitalPhaseTrace


MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
FRAME_HEADER_STRUCT = struct.Struct("<8sIIIIIIII")
TLV_HEADER_STRUCT = struct.Struct("<II")
FRAME_HEADER_SIZE = FRAME_HEADER_STRUCT.size
TLV_HEADER_SIZE = TLV_HEADER_STRUCT.size


@dataclass(frozen=True)
class FrameHeader:
    magic_word: bytes
    version: int
    total_packet_len: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_obj: int
    num_tlvs: int
    sub_frame_number: int


@dataclass(frozen=True)
class TlvHeader:
    tlv_type: int
    length: int
    header_offset: int
    payload_offset: int
    payload_end: int


def find_magic_word(buffer: bytes) -> int:
    """Return the first TI magic-word index, or -1 if not present."""
    return buffer.find(MAGIC_WORD)


def parse_frame_header(packet: bytes) -> FrameHeader:
    """Parse the xWR16xx TI mmWave frame header from the start of packet."""
    if len(packet) < FRAME_HEADER_SIZE:
        raise ValueError(
            f"packet too short for frame header: {len(packet)} < {FRAME_HEADER_SIZE}"
        )

    fields = FRAME_HEADER_STRUCT.unpack_from(packet, 0)
    header = FrameHeader(
        magic_word=fields[0],
        version=fields[1],
        total_packet_len=fields[2],
        platform=fields[3],
        frame_number=fields[4],
        time_cpu_cycles=fields[5],
        num_detected_obj=fields[6],
        num_tlvs=fields[7],
        sub_frame_number=fields[8],
    )

    if header.magic_word != MAGIC_WORD:
        raise ValueError("packet does not start with TI magic word")
    if header.total_packet_len < FRAME_HEADER_SIZE:
        raise ValueError(f"invalid total_packet_len={header.total_packet_len}")
    if header.total_packet_len > len(packet):
        raise ValueError(
            f"partial packet: need {header.total_packet_len}, have {len(packet)}"
        )
    return header


def parse_tlv_headers(packet: bytes, header: FrameHeader) -> List[TlvHeader]:
    """Parse TLV headers declared by the frame header.

    The copied non-OS MSS UART path writes an 8-byte TLV header and then exactly
    ``tlv.length`` payload bytes, so length is treated as payload length.
    """
    offset = FRAME_HEADER_SIZE
    packet_end = min(header.total_packet_len, len(packet))
    tlvs: List[TlvHeader] = []

    for _ in range(header.num_tlvs):
        if offset + TLV_HEADER_SIZE > packet_end:
            raise ValueError("malformed packet: TLV header exceeds packet length")

        tlv_type, length = TLV_HEADER_STRUCT.unpack_from(packet, offset)
        payload_offset = offset + TLV_HEADER_SIZE
        payload_end = payload_offset + length

        if length < 0 or payload_end > packet_end:
            raise ValueError(
                "malformed packet: TLV payload exceeds packet length "
                f"(type=0x{tlv_type:X}, length={length})"
            )

        tlvs.append(
            TlvHeader(
                tlv_type=tlv_type,
                length=length,
                header_offset=offset,
                payload_offset=payload_offset,
                payload_end=payload_end,
            )
        )
        offset = payload_end

    return tlvs


def extract_vital_phase_tlvs(packet: bytes) -> List[VitalPhaseTrace]:
    """Extract custom VitalPhaseTrace payloads from one complete frame packet."""
    header = parse_frame_header(packet)
    records: List[VitalPhaseTrace] = []

    for tlv in parse_tlv_headers(packet, header):
        if tlv.tlv_type != VITAL_PHASE_TRACE_TLV_ID:
            continue
        payload = packet[tlv.payload_offset : tlv.payload_end]
        records.append(parse_vital_phase_payload(payload))

    return records


def extract_vital_phase_bin_window_tlvs(packet: bytes) -> List[VitalPhaseBinWindow]:
    """Extract custom real-I/Q bin-window payloads from one complete packet."""
    header = parse_frame_header(packet)
    windows: List[VitalPhaseBinWindow] = []

    for tlv in parse_tlv_headers(packet, header):
        if tlv.tlv_type != VITAL_PHASE_BIN_WINDOW_TLV_ID:
            continue
        payload = packet[tlv.payload_offset : tlv.payload_end]
        windows.append(parse_vital_phase_bin_window_payload(payload))

    return windows


def extract_vital_phase_virtual_ant_window_tlvs(
    packet: bytes,
) -> List[VitalPhaseVirtualAntWindow]:
    """Extract custom FE03 virtual-antenna windows from one complete packet."""
    header = parse_frame_header(packet)
    windows: List[VitalPhaseVirtualAntWindow] = []

    for tlv in parse_tlv_headers(packet, header):
        if tlv.tlv_type != VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID:
            continue
        payload = packet[tlv.payload_offset : tlv.payload_end]
        windows.append(parse_vital_phase_virtual_ant_window_payload(payload))

    return windows


def parse_uart_stream_for_vital_phase(buffer: bytes) -> List[VitalPhaseTrace]:
    """Parse all complete VitalPhaseTrace records from a UART byte stream.

    Extra bytes before magic are skipped. A partial trailing packet is ignored
    without raising so callers can append more bytes in a future read.
    """
    records: List[VitalPhaseTrace] = []
    cursor = 0
    nbytes = len(buffer)

    while cursor < nbytes:
        magic_idx = buffer.find(MAGIC_WORD, cursor)
        if magic_idx < 0:
            break
        if nbytes - magic_idx < FRAME_HEADER_SIZE:
            break

        try:
            header = parse_frame_header(buffer[magic_idx:])
        except ValueError:
            cursor = magic_idx + 1
            continue

        packet_end = magic_idx + header.total_packet_len
        if packet_end > nbytes:
            break

        packet = buffer[magic_idx:packet_end]
        try:
            records.extend(extract_vital_phase_tlvs(packet))
        except ValueError:
            cursor = magic_idx + 1
            continue

        cursor = packet_end

    return records


def parse_uart_stream_for_vital_phase_bin_windows(
    buffer: bytes,
) -> List[VitalPhaseBinWindow]:
    """Parse all complete 0xFE02 windows from a UART byte stream."""
    windows: List[VitalPhaseBinWindow] = []
    cursor = 0
    nbytes = len(buffer)

    while cursor < nbytes:
        magic_idx = buffer.find(MAGIC_WORD, cursor)
        if magic_idx < 0 or nbytes - magic_idx < FRAME_HEADER_SIZE:
            break

        try:
            header = parse_frame_header(buffer[magic_idx:])
        except ValueError:
            cursor = magic_idx + 1
            continue

        packet_end = magic_idx + header.total_packet_len
        if packet_end > nbytes:
            break

        packet = buffer[magic_idx:packet_end]
        try:
            windows.extend(extract_vital_phase_bin_window_tlvs(packet))
        except ValueError:
            cursor = magic_idx + 1
            continue

        cursor = packet_end

    return windows


def parse_uart_stream_for_vital_phase_virtual_ant_windows(
    buffer: bytes,
) -> List[VitalPhaseVirtualAntWindow]:
    """Parse all complete FE03 virtual-antenna windows from a UART stream."""
    windows: List[VitalPhaseVirtualAntWindow] = []
    cursor = 0
    nbytes = len(buffer)

    while cursor < nbytes:
        magic_idx = buffer.find(MAGIC_WORD, cursor)
        if magic_idx < 0 or nbytes - magic_idx < FRAME_HEADER_SIZE:
            break

        try:
            header = parse_frame_header(buffer[magic_idx:])
        except ValueError:
            cursor = magic_idx + 1
            continue

        packet_end = magic_idx + header.total_packet_len
        if packet_end > nbytes:
            break

        packet = buffer[magic_idx:packet_end]
        try:
            windows.extend(extract_vital_phase_virtual_ant_window_tlvs(packet))
        except ValueError:
            cursor = magic_idx + 1
            continue

        cursor = packet_end

    return windows
