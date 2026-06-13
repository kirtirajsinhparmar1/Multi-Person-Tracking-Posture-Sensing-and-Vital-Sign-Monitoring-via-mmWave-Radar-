"""TI Pose/Fall feature extraction for IWR6843 people-tracking frames.

This module does not open serial ports. It converts one tracked target and its
associated point cloud into TI's 22-feature per-frame pose format, maintains an
8-frame per-TID history, and packs the final 176-float input in channel-major
order.

Coordinate assumptions:
- IWR6843ISK-ODS parser uses z as vertical height.
- Point feature y is relative_y = point.y - target.y.
- Point feature z is point.z directly.
- The IWRL6432 Pose/Fall code used a sideways orientation, so do not blindly
  copy its coordinate mapping onto IWR6843 data.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable, Mapping, MutableMapping


CLASS_NAMES = ["STANDING", "SITTING", "LYING", "FALLING", "WALKING"]

FEATURE_NAMES_22 = [
    "posz",
    "velx",
    "vely",
    "velz",
    "accx",
    "accy",
    "accz",
    "y0",
    "z0",
    "snr0",
    "y1",
    "z1",
    "snr1",
    "y2",
    "z2",
    "snr2",
    "y3",
    "z3",
    "snr3",
    "y4",
    "z4",
    "snr4",
]

WINDOW_SIZE = 8
POINTS_PER_FRAME = 5
UNASSOCIATED_TRACK_INDEXES = {253, 254, 255}


@dataclass(frozen=True)
class SelectedPoint:
    source_index: int | None
    relative_y: float
    z: float
    snr: float


@dataclass(frozen=True)
class FeatureQuality:
    num_points: int
    selected_points: list[SelectedPoint] = field(default_factory=list)
    low_quality: bool = False
    reason: str = ""


@dataclass(frozen=True)
class FeatureBuildResult:
    feature22: list[float]
    quality: FeatureQuality

    @property
    def num_points(self) -> int:
        return self.quality.num_points

    @property
    def selected_points(self) -> list[SelectedPoint]:
        return self.quality.selected_points

    @property
    def low_quality(self) -> bool:
        return self.quality.low_quality

    @property
    def reason(self) -> str:
        return self.quality.reason


_WINDOWS: MutableMapping[int, Deque[list[float]]] = defaultdict(
    lambda: deque(maxlen=WINDOW_SIZE)
)
_QUALITY_WINDOWS: MutableMapping[int, Deque[FeatureQuality]] = defaultdict(
    lambda: deque(maxlen=WINDOW_SIZE)
)


def build_22_feature_vector(target: Any, associated_points: Iterable[Any]) -> FeatureBuildResult:
    """Build TI's 22-feature vector and quality metadata for one frame.

    Target fields come from ``frame_types.Target`` when used live:
    ``pos_z, vel_x, vel_y, vel_z, acc_x, acc_y, acc_z``. Mapping/dict aliases
    are accepted for offline tests.

    Associated points must already be filtered to the target ID from TLV 1011.
    The five highest-z points are used. Missing points are zero-padded and mark
    the result as low quality.
    """

    target_y = _get_value(target, "pos_y", "posy", "y")
    feature22 = [
        _get_value(target, "pos_z", "posz", "z"),
        _get_value(target, "vel_x", "velx", "vx"),
        _get_value(target, "vel_y", "vely", "vy"),
        _get_value(target, "vel_z", "velz", "vz"),
        _get_value(target, "acc_x", "accx", "ax"),
        _get_value(target, "acc_y", "accy", "ay"),
        _get_value(target, "acc_z", "accz", "az"),
    ]

    candidates: list[tuple[float, SelectedPoint]] = []
    for point in associated_points:
        point_z = _get_value(point, "z", "pointz")
        point_y = _get_value(point, "y", "pointy")
        selected = SelectedPoint(
            source_index=_get_optional_int(point, "index", "point_index"),
            relative_y=point_y - target_y,
            z=point_z,
            snr=_get_value(point, "snr", default=0.0),
        )
        candidates.append((point_z, selected))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected_points = [item[1] for item in candidates[:POINTS_PER_FRAME]]

    for point in selected_points:
        feature22.extend([point.relative_y, point.z, point.snr])

    while len(feature22) < len(FEATURE_NAMES_22):
        feature22.extend([0.0, 0.0, 0.0])

    low_quality = len(candidates) < POINTS_PER_FRAME
    reason = "" if not low_quality else f"only_{len(candidates)}_associated_points"
    quality = FeatureQuality(
        num_points=len(candidates),
        selected_points=selected_points,
        low_quality=low_quality,
        reason=reason,
    )
    return FeatureBuildResult(feature22=feature22[: len(FEATURE_NAMES_22)], quality=quality)


def update_8_frame_window(
    tid: int,
    feature22: Iterable[float],
    quality: FeatureQuality | None = None,
) -> list[list[float]]:
    """Append one frame to a TID history and return the padded 8-frame window."""

    feature = [float(value) for value in feature22]
    if len(feature) != len(FEATURE_NAMES_22):
        raise ValueError(f"feature22 must contain {len(FEATURE_NAMES_22)} values")

    tid_int = int(tid)
    _WINDOWS[tid_int].append(feature)
    if quality is not None:
        _QUALITY_WINDOWS[tid_int].append(quality)
    return get_8_frame_window(tid_int)


def build_176_feature_vector(tid: int) -> list[float]:
    """Return channel-major 176-float input for TI Pose/Fall.

    Output order is:
    ``posz_f0..posz_f7, velx_f0..velx_f7, ..., snr4_f0..snr4_f7``.
    Frame 0 is the oldest slot in the padded 8-frame window.
    """

    window = get_8_frame_window(tid)
    vector176: list[float] = []
    for feature_index in range(len(FEATURE_NAMES_22)):
        for frame in window:
            vector176.append(frame[feature_index])
    return vector176


def reset_tid(tid: int) -> None:
    _WINDOWS.pop(int(tid), None)
    _QUALITY_WINDOWS.pop(int(tid), None)


def reset_all() -> None:
    _WINDOWS.clear()
    _QUALITY_WINDOWS.clear()


def get_8_frame_window(tid: int) -> list[list[float]]:
    window = _WINDOWS.get(int(tid), deque(maxlen=WINDOW_SIZE))
    missing = WINDOW_SIZE - len(window)
    padding = [[0.0] * len(FEATURE_NAMES_22) for _ in range(max(0, missing))]
    return padding + list(window)


def get_window_age(tid: int) -> int:
    return len(_WINDOWS.get(int(tid), ()))


def is_window_ready(tid: int) -> bool:
    return get_window_age(tid) >= WINDOW_SIZE


def get_recent_num_points(tid: int) -> int:
    quality_window = _QUALITY_WINDOWS.get(int(tid))
    if not quality_window:
        return 0
    return quality_window[-1].num_points


def get_low_quality_count(tid: int) -> int:
    quality_window = _QUALITY_WINDOWS.get(int(tid), ())
    return sum(1 for quality in quality_window if quality.low_quality)


def associated_points_for_target(target: Any, points: Iterable[Any]) -> list[Any]:
    """Filter TLV 1020 points to the TLV 1011 track index for this target."""

    tid = int(_get_value(target, "tid", "track_index", default=-1))
    return [
        point
        for point in points
        if int(_get_value(point, "track_index", default=255)) == tid
    ]


def _get_value(obj: Any, *names: str, default: float = 0.0) -> float:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return float(obj[name])
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return float(value)
    return float(default)


def _get_optional_int(obj: Any, *names: str) -> int | None:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return int(obj[name])
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return int(value)
    return None
