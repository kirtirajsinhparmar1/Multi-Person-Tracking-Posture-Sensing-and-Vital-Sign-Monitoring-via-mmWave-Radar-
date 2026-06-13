"""Typed frame objects for the standalone IWR6843 fall logger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class FrameHeader:
    magic: int
    version: int
    total_packet_len: int
    platform: int
    frame_num: int
    time_cpu_cycles: int
    num_detected_obj: int
    num_tlvs: int
    sub_frame_num: int


@dataclass(frozen=True)
class Target:
    tid: int
    pos_x: float
    pos_y: float
    pos_z: float
    vel_x: float
    vel_y: float
    vel_z: float
    acc_x: float
    acc_y: float
    acc_z: float
    g: float
    confidence: float
    covariance: Tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetHeight:
    tid: int
    max_z: float
    min_z: float


@dataclass(frozen=True)
class Point:
    index: int
    x: float
    y: float
    z: float
    doppler: float
    snr: float
    range_m: float
    azimuth: float
    elevation: float
    track_index: int = 255


@dataclass(frozen=True)
class FallStatus:
    tid: int
    is_fallen: bool
    current_height: Optional[float]
    old_height: Optional[float]
    drop_ratio: Optional[float]
    threshold: float
    hold_frames_remaining: int
    reason: str


@dataclass
class ParsedFrame:
    header: FrameHeader
    targets: list[Target] = field(default_factory=list)
    heights: list[TargetHeight] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    target_indexes: list[int] = field(default_factory=list)
    presence: Optional[int] = None
    unknown_tlvs: list[tuple[int, int]] = field(default_factory=list)
    parse_error: Optional[str] = None

    @property
    def frame_num(self) -> int:
        return self.header.frame_num

