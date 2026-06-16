import struct
from pathlib import Path
from typing import List

try:
    from .vital_phase_tlv_types import VitalPhaseTrace
except ImportError:
    from vital_phase_tlv_types import VitalPhaseTrace


VITAL_PHASE_TRACE_TLV_ID = 0xFE01
VITAL_PHASE_TRACE_STRUCT = struct.Struct("<IHHffffffB3s")
VITAL_PHASE_TRACE_PAYLOAD_SIZE = VITAL_PHASE_TRACE_STRUCT.size


def parse_vital_phase_payload(payload: bytes) -> VitalPhaseTrace:
    if len(payload) < VITAL_PHASE_TRACE_PAYLOAD_SIZE:
        raise ValueError(
            f"VitalPhaseTrace payload too short: got {len(payload)} bytes, "
            f"need {VITAL_PHASE_TRACE_PAYLOAD_SIZE}"
        )
    (
        frame_number,
        range_bin_index_max,
        range_bin_index_phase,
        range_meters,
        i_value,
        q_value,
        phase_rad,
        magnitude,
        snr_like,
        motion_detected,
        reserved,
    ) = VITAL_PHASE_TRACE_STRUCT.unpack_from(payload, 0)
    return VitalPhaseTrace(
        frame_number=frame_number,
        range_bin_index_max=range_bin_index_max,
        range_bin_index_phase=range_bin_index_phase,
        range_meters=range_meters,
        i_value=i_value,
        q_value=q_value,
        phase_rad=phase_rad,
        magnitude=magnitude,
        snr_like=snr_like,
        motion_detected=motion_detected,
        reserved=reserved,
    )


def pack_fake_vital_phase_payload(sample: VitalPhaseTrace) -> bytes:
    reserved = sample.reserved or b"\x00\x00\x00"
    if len(reserved) != 3:
        raise ValueError("reserved must be exactly 3 bytes")
    return VITAL_PHASE_TRACE_STRUCT.pack(
        int(sample.frame_number),
        int(sample.range_bin_index_max),
        int(sample.range_bin_index_phase),
        float(sample.range_meters),
        float(sample.i_value),
        float(sample.q_value),
        float(sample.phase_rad),
        float(sample.magnitude),
        float(sample.snr_like),
        int(sample.motion_detected),
        reserved,
    )


def parse_many_from_binary_log(path) -> List[VitalPhaseTrace]:
    """Parse a simple payload-only binary log.

    This is a placeholder for early replay files that contain consecutive
    36-byte VitalPhaseTrace payloads. It is not a full TI UART packet parser.
    """
    data = Path(path).read_bytes()
    if len(data) % VITAL_PHASE_TRACE_PAYLOAD_SIZE != 0:
        raise ValueError(
            "payload-only log size is not a multiple of "
            f"{VITAL_PHASE_TRACE_PAYLOAD_SIZE} bytes"
        )
    samples = []
    for offset in range(0, len(data), VITAL_PHASE_TRACE_PAYLOAD_SIZE):
        samples.append(parse_vital_phase_payload(data[offset : offset + VITAL_PHASE_TRACE_PAYLOAD_SIZE]))
    return samples
