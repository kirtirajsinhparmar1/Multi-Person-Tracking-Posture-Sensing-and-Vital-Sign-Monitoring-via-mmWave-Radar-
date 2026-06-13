"""Feature-vector skeleton for TI Pose/Fall model experiments on PC.

This module does not talk to radar hardware. It only defines the feature order
and window packing needed to test whether IWR6843 tracker/point-cloud data can
be shaped like the TI IWRL6432 Pose/Fall model input.

Coordinate assumptions for IWR6843ISK-ODS:
- z is vertical height.
- y is treated as forward/range-like distance for the relative point feature.
- TI's IWRL6432 demo code appears to use a sideways mounting/orientation, so do
  not blindly copy its x/y/z mapping.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Deque, Dict, Iterable, List, Mapping, MutableMapping


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
MIN_POINTS = 5
_WINDOWS: MutableMapping[int, Deque[List[float]]] = defaultdict(
    lambda: deque(maxlen=WINDOW_SIZE)
)


def _get_value(obj: Any, *names: str, default: float = 0.0) -> float:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return float(obj[name])
        if hasattr(obj, name):
            return float(getattr(obj, name))
    return float(default)


def build_22_feature_vector(target: Any, associated_points: Iterable[Any]) -> List[float]:
    """Build one frame of 22 TI Pose/Fall-style features.

    Expected target fields, by mapping key or attribute:
    z/posz, vx/velx, vy/vely, vz/velz, ax/accx, ay/accy, az/accz, and y/posy.

    Expected point fields:
    y/pointy, z/pointz, and snr. The five highest-z points are selected. Each
    point contributes relative_y = point.y - target.y, vertical z, and snr.

    If fewer than five points are available, the remaining point slots are
    zero-padded so the shape remains stable. For real inference, prefer gating
    on at least five associated points, matching TI's training filter.
    """

    target_y = _get_value(target, "y", "posy")
    feature22 = [
        _get_value(target, "z", "posz"),
        _get_value(target, "vx", "velx"),
        _get_value(target, "vy", "vely"),
        _get_value(target, "vz", "velz"),
        _get_value(target, "ax", "accx"),
        _get_value(target, "ay", "accy"),
        _get_value(target, "az", "accz"),
    ]

    points = []
    for point in associated_points:
        point_y = _get_value(point, "y", "pointy")
        point_z = _get_value(point, "z", "pointz")
        snr = _get_value(point, "snr")
        points.append((point_z, point_y - target_y, point_z, snr))

    points.sort(key=lambda item: item[0])
    top_points = points[-MIN_POINTS:]

    for _, relative_y, point_z, snr in top_points:
        feature22.extend([relative_y, point_z, snr])

    while len(feature22) < len(FEATURE_NAMES_22):
        feature22.extend([0.0, 0.0, 0.0])

    return feature22[: len(FEATURE_NAMES_22)]


def update_8_frame_window(tid: int, feature22: Iterable[float]) -> List[List[float]]:
    """Append one frame for a track ID and return the current 8-frame window.

    Older missing frames are zero-padded to mimic TI's initialized circular
    buffer behavior before a track has accumulated eight frames.
    """

    feature = [float(value) for value in feature22]
    if len(feature) != len(FEATURE_NAMES_22):
        raise ValueError(f"feature22 must contain {len(FEATURE_NAMES_22)} values")

    window = _WINDOWS[int(tid)]
    window.append(feature)
    return _padded_window(window)


def build_176_feature_vector(tid: int) -> List[float]:
    """Return the TI model input vector for a track ID.

    The deployed TI C code interleaves by feature channel across eight frames:
    [posz_f0..posz_f7, velx_f0..velx_f7, ..., snr4_f0..snr4_f7].
    This is column-major relative to the 8x22 frame table, not frame-major.
    """

    window = _padded_window(_WINDOWS[int(tid)])
    vector176: List[float] = []
    for feature_index in range(len(FEATURE_NAMES_22)):
        for frame in window:
            vector176.append(frame[feature_index])
    return vector176


def _padded_window(window: Deque[List[float]]) -> List[List[float]]:
    missing = WINDOW_SIZE - len(window)
    padding = [[0.0] * len(FEATURE_NAMES_22) for _ in range(max(0, missing))]
    return padding + list(window)
