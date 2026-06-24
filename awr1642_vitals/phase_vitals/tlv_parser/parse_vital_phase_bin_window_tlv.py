"""Parser for the AWR1642 real-I/Q range-bin window TLV 0xFE02."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Tuple


VITAL_PHASE_BIN_WINDOW_TLV_ID = 0xFE02
VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT = struct.Struct("<IHHf")
VITAL_PHASE_BIN_SAMPLE_STRUCT = struct.Struct("<HHfffff")


@dataclass(frozen=True)
class VitalPhaseBinSample:
    bin_index: int
    range_meters: float
    i_value: float
    q_value: float
    phase_rad: float
    magnitude: float
    reserved: int = 0


@dataclass(frozen=True)
class VitalPhaseBinWindow:
    frame_number: int
    start_bin: int
    num_bins: int
    range_resolution: float
    samples: Tuple[VitalPhaseBinSample, ...]


def parse_vital_phase_bin_window_payload(payload: bytes) -> VitalPhaseBinWindow:
    """Parse one complete 0xFE02 payload and validate its declared sample count."""
    header_size = VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT.size
    sample_size = VITAL_PHASE_BIN_SAMPLE_STRUCT.size
    if len(payload) < header_size:
        raise ValueError(
            f"VitalPhaseBinWindow payload too short: {len(payload)} < {header_size}"
        )

    frame_number, start_bin, num_bins, range_resolution = (
        VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT.unpack_from(payload, 0)
    )
    expected_size = header_size + int(num_bins) * sample_size
    if len(payload) != expected_size:
        raise ValueError(
            "VitalPhaseBinWindow payload length mismatch: "
            f"declared {num_bins} bins requires {expected_size} bytes, "
            f"got {len(payload)}"
        )

    samples = []
    offset = header_size
    for _ in range(num_bins):
        (
            bin_index,
            reserved,
            range_meters,
            i_value,
            q_value,
            phase_rad,
            magnitude,
        ) = VITAL_PHASE_BIN_SAMPLE_STRUCT.unpack_from(payload, offset)
        samples.append(
            VitalPhaseBinSample(
                bin_index=bin_index,
                reserved=reserved,
                range_meters=range_meters,
                i_value=i_value,
                q_value=q_value,
                phase_rad=phase_rad,
                magnitude=magnitude,
            )
        )
        offset += sample_size

    return VitalPhaseBinWindow(
        frame_number=frame_number,
        start_bin=start_bin,
        num_bins=num_bins,
        range_resolution=range_resolution,
        samples=tuple(samples),
    )


def pack_vital_phase_bin_window_payload(window: VitalPhaseBinWindow) -> bytes:
    """Pack a synthetic 0xFE02 payload for offline parser validation."""
    if window.num_bins != len(window.samples):
        raise ValueError(
            f"num_bins={window.num_bins} does not match {len(window.samples)} samples"
        )

    payload = bytearray(
        VITAL_PHASE_BIN_WINDOW_HEADER_STRUCT.pack(
            int(window.frame_number),
            int(window.start_bin),
            int(window.num_bins),
            float(window.range_resolution),
        )
    )
    for sample in window.samples:
        payload.extend(
            VITAL_PHASE_BIN_SAMPLE_STRUCT.pack(
                int(sample.bin_index),
                int(sample.reserved),
                float(sample.range_meters),
                float(sample.i_value),
                float(sample.q_value),
                float(sample.phase_rad),
                float(sample.magnitude),
            )
        )
    return bytes(payload)
