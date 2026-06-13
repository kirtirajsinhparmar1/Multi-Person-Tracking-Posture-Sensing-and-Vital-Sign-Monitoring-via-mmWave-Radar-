"""Standalone parser for IWR6843 3D People Tracking UART frames.

This does not import TI visualizer code. Struct layouts are copied from the
inspected TI parser and cited inline:

- TLV IDs: tools\\visualizers\\Applications_Visualizer\\common\\tlv_defines.py:57-61
- frame header: tools\\visualizers\\Applications_Visualizer\\common\\parseFrame.py:103-125
- TLV header: tools\\visualizers\\Applications_Visualizer\\common\\parseFrame.py:197-200
- target list: tools\\visualizers\\Applications_Visualizer\\common\\parseTLVs.py:278-320
- target height: tools\\visualizers\\Applications_Visualizer\\common\\parseTLVs.py:360-377
- target index: tools\\visualizers\\Applications_Visualizer\\common\\parseTLVs.py:416-430
- compressed points: tools\\visualizers\\Applications_Visualizer\\common\\parseTLVs.py:228-275
"""

from __future__ import annotations

import math
import struct
from typing import Iterable

from frame_types import FrameHeader, ParsedFrame, Point, Target, TargetHeight


MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"

TLV_TARGET_LIST = 1010
TLV_TARGET_INDEX = 1011
TLV_TARGET_HEIGHT = 1012
TLV_COMPRESSED_POINTS = 1020
TLV_PRESENCE = 1021

HEADER_STRUCT = "<Q8I"
TLV_HEADER_STRUCT = "<2I"
TARGET_STRUCT = "<I27f"
HEIGHT_STRUCT = "<I2f"
TARGET_INDEX_STRUCT = "<B"
POINT_UNIT_STRUCT = "<5f"
COMPRESSED_POINT_STRUCT = "<2bh2H"
PRESENCE_STRUCT = "<I"

HEADER_LEN = struct.calcsize(HEADER_STRUCT)
TLV_HEADER_LEN = struct.calcsize(TLV_HEADER_STRUCT)
TARGET_LEN = struct.calcsize(TARGET_STRUCT)
HEIGHT_LEN = struct.calcsize(HEIGHT_STRUCT)
POINT_UNIT_LEN = struct.calcsize(POINT_UNIT_STRUCT)
COMPRESSED_POINT_LEN = struct.calcsize(COMPRESSED_POINT_STRUCT)


class FrameParseError(ValueError):
    """Raised when a UART frame is incomplete or malformed."""


def parse_frame(frame_data: bytes) -> ParsedFrame:
    """Parse a complete UART frame including the 8-byte magic word."""
    if len(frame_data) < HEADER_LEN:
        raise FrameParseError(f"Frame shorter than header: {len(frame_data)} bytes")
    if frame_data[: len(MAGIC_WORD)] != MAGIC_WORD:
        raise FrameParseError("Frame does not start with TI magic word")

    header_values = struct.unpack(HEADER_STRUCT, frame_data[:HEADER_LEN])
    header = FrameHeader(
        magic=header_values[0],
        version=header_values[1],
        total_packet_len=header_values[2],
        platform=header_values[3],
        frame_num=header_values[4],
        time_cpu_cycles=header_values[5],
        num_detected_obj=header_values[6],
        num_tlvs=header_values[7],
        sub_frame_num=header_values[8],
    )
    parsed = ParsedFrame(header=header)

    if header.total_packet_len > len(frame_data):
        parsed.parse_error = (
            f"Frame {header.frame_num} incomplete: header length "
            f"{header.total_packet_len}, received {len(frame_data)}"
        )
        return parsed

    offset = HEADER_LEN
    for _ in range(header.num_tlvs):
        if offset + TLV_HEADER_LEN > len(frame_data):
            parsed.parse_error = f"TLV header overruns frame at offset {offset}"
            return parsed

        tlv_type, tlv_len = struct.unpack(
            TLV_HEADER_STRUCT, frame_data[offset : offset + TLV_HEADER_LEN]
        )
        offset += TLV_HEADER_LEN

        if offset + tlv_len > len(frame_data):
            parsed.parse_error = (
                f"TLV {tlv_type} length {tlv_len} overruns frame at offset {offset}"
            )
            return parsed

        payload = frame_data[offset : offset + tlv_len]
        if tlv_type == TLV_TARGET_LIST:
            parsed.targets = parse_target_list(payload)
        elif tlv_type == TLV_TARGET_HEIGHT:
            parsed.heights = parse_target_heights(payload)
        elif tlv_type == TLV_TARGET_INDEX:
            parsed.target_indexes = parse_target_indexes(payload)
        elif tlv_type == TLV_COMPRESSED_POINTS:
            parsed.points = parse_compressed_points(payload)
        elif tlv_type == TLV_PRESENCE:
            parsed.presence = parse_presence(payload)
        else:
            parsed.unknown_tlvs.append((tlv_type, tlv_len))

        offset += tlv_len

    if parsed.target_indexes and parsed.points:
        parsed.points = apply_target_indexes(parsed.points, parsed.target_indexes)

    return parsed


def parse_target_list(payload: bytes) -> list[Target]:
    """Parse TLV 1010.

    TI uses struct format 'I27f' and keeps TID, position, velocity,
    acceleration, G, and confidence while discarding EC in parseTLVs.py:293-320.
    """
    targets: list[Target] = []
    for raw in _chunks(payload, TARGET_LEN):
        if len(raw) != TARGET_LEN:
            break
        values = struct.unpack(TARGET_STRUCT, raw)
        targets.append(
            Target(
                tid=int(values[0]),
                pos_x=values[1],
                pos_y=values[2],
                pos_z=values[3],
                vel_x=values[4],
                vel_y=values[5],
                vel_z=values[6],
                acc_x=values[7],
                acc_y=values[8],
                acc_z=values[9],
                covariance=tuple(values[10:26]),
                g=values[26],
                confidence=values[27],
            )
        )
    return targets


def parse_target_heights(payload: bytes) -> list[TargetHeight]:
    """Parse TLV 1012.

    TI uses struct format 'I2f' for TID, maxZ, and minZ in
    parseTLVs.py:360-377.
    """
    heights: list[TargetHeight] = []
    for raw in _chunks(payload, HEIGHT_LEN):
        if len(raw) != HEIGHT_LEN:
            break
        tid, max_z, min_z = struct.unpack(HEIGHT_STRUCT, raw)
        heights.append(TargetHeight(tid=int(tid), max_z=max_z, min_z=min_z))
    return heights


def parse_target_indexes(payload: bytes) -> list[int]:
    """Parse TLV 1011, one unsigned byte per point.

    TI uses struct format 'B' in parseTLVs.py:416-430.
    """
    return [struct.unpack(TARGET_INDEX_STRUCT, payload[i : i + 1])[0] for i in range(len(payload))]


def parse_compressed_points(payload: bytes) -> list[Point]:
    """Parse TLV 1020 compressed point cloud.

    TI uses '5f' units and '2bh2H' compressed points, then converts spherical
    range/azimuth/elevation to Cartesian XYZ in parseTLVs.py:228-275 and
    gui_common.py:21-40.
    """
    if len(payload) < POINT_UNIT_LEN:
        return []

    elev_unit, az_unit, doppler_unit, range_unit, snr_unit = struct.unpack(
        POINT_UNIT_STRUCT, payload[:POINT_UNIT_LEN]
    )
    points: list[Point] = []
    offset = POINT_UNIT_LEN
    index = 0

    while offset + COMPRESSED_POINT_LEN <= len(payload):
        elevation_i, azimuth_i, doppler_i, range_i, snr_i = struct.unpack(
            COMPRESSED_POINT_STRUCT, payload[offset : offset + COMPRESSED_POINT_LEN]
        )
        offset += COMPRESSED_POINT_LEN

        range_m = range_i * range_unit
        azimuth = azimuth_i * az_unit
        elevation = elevation_i * elev_unit
        doppler = doppler_i * doppler_unit
        snr = snr_i * snr_unit

        x, y, z = spherical_to_cartesian(range_m, azimuth, elevation)
        points.append(
            Point(
                index=index,
                x=x,
                y=y,
                z=z,
                doppler=doppler,
                snr=snr,
                range_m=range_m,
                azimuth=azimuth,
                elevation=elevation,
            )
        )
        index += 1

    return points


def parse_presence(payload: bytes) -> int | None:
    if len(payload) < struct.calcsize(PRESENCE_STRUCT):
        return None
    return int(struct.unpack(PRESENCE_STRUCT, payload[:4])[0])


def apply_target_indexes(points: list[Point], target_indexes: list[int]) -> list[Point]:
    updated: list[Point] = []
    for point in points:
        track_index = target_indexes[point.index] if point.index < len(target_indexes) else 255
        updated.append(
            Point(
                index=point.index,
                x=point.x,
                y=point.y,
                z=point.z,
                doppler=point.doppler,
                snr=point.snr,
                range_m=point.range_m,
                azimuth=point.azimuth,
                elevation=point.elevation,
                track_index=int(track_index),
            )
        )
    return updated


def spherical_to_cartesian(range_m: float, azimuth: float, elevation: float) -> tuple[float, float, float]:
    x = range_m * math.sin(azimuth) * math.cos(elevation)
    y = range_m * math.cos(azimuth) * math.cos(elevation)
    z = range_m * math.sin(elevation)
    return x, y, z


def _chunks(data: bytes, size: int) -> Iterable[bytes]:
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]

