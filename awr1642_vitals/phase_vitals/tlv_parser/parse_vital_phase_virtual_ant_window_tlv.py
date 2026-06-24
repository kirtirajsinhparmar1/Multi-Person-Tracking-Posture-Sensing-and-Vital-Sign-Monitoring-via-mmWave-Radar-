"""Parser for AWR1642 virtual-azimuth-antenna window TLV 0xFE03."""

from __future__ import annotations

from dataclasses import dataclass
import struct

import numpy as np


VITAL_PHASE_VIRTUAL_ANT_WINDOW_TLV_ID = 0xFE03
VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT = struct.Struct("<IHHHHf")
VITAL_PHASE_VIRTUAL_ANT_SAMPLE_STRUCT = struct.Struct("<hh")


@dataclass(frozen=True)
class VitalPhaseVirtualAntWindow:
    frame_number: int
    start_bin: int
    num_bins: int
    num_virtual_antennas: int
    flags: int
    range_resolution: float
    samples: np.ndarray
    bin_indices: np.ndarray
    range_meters: np.ndarray


def parse_vital_phase_virtual_ant_window_payload(
    payload: bytes,
) -> VitalPhaseVirtualAntWindow:
    """Parse one FE03 payload into a ``[range, antenna]`` complex array."""
    header_size = VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT.size
    sample_size = VITAL_PHASE_VIRTUAL_ANT_SAMPLE_STRUCT.size
    if len(payload) < header_size:
        raise ValueError(
            "VitalPhaseVirtualAntWindow payload too short: "
            f"{len(payload)} < {header_size}"
        )

    (
        frame_number,
        start_bin,
        num_bins,
        num_virtual_antennas,
        flags,
        range_resolution,
    ) = VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT.unpack_from(payload, 0)

    if num_bins == 0:
        raise ValueError("VitalPhaseVirtualAntWindow declares zero range bins")
    if num_virtual_antennas == 0:
        raise ValueError("VitalPhaseVirtualAntWindow declares zero antennas")

    sample_count = int(num_bins) * int(num_virtual_antennas)
    expected_size = header_size + sample_count * sample_size
    if len(payload) != expected_size:
        raise ValueError(
            "VitalPhaseVirtualAntWindow payload length mismatch: "
            f"{num_bins} bins x {num_virtual_antennas} antennas requires "
            f"{expected_size} bytes, got {len(payload)}"
        )

    interleaved_iq = np.frombuffer(
        payload,
        dtype="<i2",
        count=sample_count * 2,
        offset=header_size,
    ).reshape(num_bins, num_virtual_antennas, 2)
    samples = (
        interleaved_iq[..., 0].astype(np.float32)
        + 1j * interleaved_iq[..., 1].astype(np.float32)
    ).astype(np.complex64, copy=False)
    bin_indices = np.arange(
        int(start_bin),
        int(start_bin) + int(num_bins),
        dtype=np.int32,
    )
    range_meters = bin_indices.astype(np.float32) * float(range_resolution)

    return VitalPhaseVirtualAntWindow(
        frame_number=int(frame_number),
        start_bin=int(start_bin),
        num_bins=int(num_bins),
        num_virtual_antennas=int(num_virtual_antennas),
        flags=int(flags),
        range_resolution=float(range_resolution),
        samples=samples,
        bin_indices=bin_indices,
        range_meters=range_meters,
    )


def pack_vital_phase_virtual_ant_window_payload(
    window: VitalPhaseVirtualAntWindow,
) -> bytes:
    """Pack a synthetic FE03 payload for offline validation."""
    samples = np.asarray(window.samples)
    expected_shape = (int(window.num_bins), int(window.num_virtual_antennas))
    if samples.shape != expected_shape:
        raise ValueError(
            f"samples shape {samples.shape} does not match {expected_shape}"
        )

    real = np.rint(samples.real)
    imag = np.rint(samples.imag)
    if (
        np.any(real < np.iinfo(np.int16).min)
        or np.any(real > np.iinfo(np.int16).max)
        or np.any(imag < np.iinfo(np.int16).min)
        or np.any(imag > np.iinfo(np.int16).max)
    ):
        raise ValueError("FE03 synthetic I/Q exceeds int16 range")

    interleaved = np.empty((*expected_shape, 2), dtype="<i2")
    interleaved[..., 0] = real.astype(np.int16)
    interleaved[..., 1] = imag.astype(np.int16)
    header = VITAL_PHASE_VIRTUAL_ANT_WINDOW_HEADER_STRUCT.pack(
        int(window.frame_number),
        int(window.start_bin),
        int(window.num_bins),
        int(window.num_virtual_antennas),
        int(window.flags),
        float(window.range_resolution),
    )
    return header + interleaved.tobytes(order="C")
