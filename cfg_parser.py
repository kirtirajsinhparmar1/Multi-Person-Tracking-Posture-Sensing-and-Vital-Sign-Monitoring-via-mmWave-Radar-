"""Parse visualizer scene settings from TI mmWave cfg files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import numpy as np


@dataclass(frozen=True)
class BoundaryBox:
    name: str
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float
    color: tuple[float, float, float, float]


@dataclass
class SceneConfig:
    sensor_height: float = 0.0
    az_tilt_deg: float = 0.0
    elev_tilt_deg: float = 0.0
    boundary_boxes: list[BoundaryBox] = field(default_factory=list)
    frame_time_ms: int = 55
    max_tracks: int = 10


BOX_COLORS = {
    "boundaryBox": (0.20, 0.55, 1.00, 1.0),
    "staticBoundaryBox": (0.10, 0.90, 0.35, 1.0),
    "presenceBoundaryBox": (1.00, 0.25, 0.90, 1.0),
}


def parse_scene_config(cfg_path: str | Path) -> SceneConfig:
    """Parse the cfg commands the visualizer needs.

    References:
    - TI parses sensorPosition for x843 as height, azimuth tilt, elevation tilt
      in Common_Tabs\\plot_3d.py:254-272.
    - TI parses boundaryBox into min/max X/Y/Z in plot_3d.py:207-219.
    - ODS_6m_default.cfg contains staticBoundaryBox, boundaryBox,
      sensorPosition, trackingCfg, and presenceBoundaryBox.
    """
    config = SceneConfig()
    path = Path(cfg_path)
    if not path.exists():
        return default_scene_config()

    with path.open("r", encoding="utf-8", errors="replace") as cfg:
        for raw_line in cfg:
            line = raw_line.strip()
            if not line or line.startswith("%"):
                continue
            args = line.split()
            cmd = args[0]
            if cmd == "sensorPosition" and len(args) >= 4:
                config.sensor_height = float(args[1])
                config.az_tilt_deg = float(args[2])
                config.elev_tilt_deg = float(args[3])
            elif cmd in BOX_COLORS and len(args) >= 7:
                config.boundary_boxes.append(
                    BoundaryBox(
                        name=cmd,
                        min_x=float(args[1]),
                        max_x=float(args[2]),
                        min_y=float(args[3]),
                        max_y=float(args[4]),
                        min_z=float(args[5]),
                        max_z=float(args[6]),
                        color=BOX_COLORS[cmd],
                    )
                )
            elif cmd == "trackingCfg" and len(args) >= 8:
                # TI People Tracking reads max tracks from args[4] and frame time
                # from args[7] in people_tracking.py:250-283.
                config.max_tracks = int(float(args[4]))
                config.frame_time_ms = int(float(args[7]))
            elif cmd == "frameCfg" and len(args) >= 6:
                try:
                    config.frame_time_ms = int(round(float(args[5])))
                except ValueError:
                    pass

    return config


def default_scene_config() -> SceneConfig:
    return SceneConfig(
        sensor_height=2.0,
        az_tilt_deg=0.0,
        elev_tilt_deg=15.0,
        frame_time_ms=55,
        max_tracks=10,
        boundary_boxes=[
            BoundaryBox("staticBoundaryBox", -3, 3, 0.5, 7.5, 0, 3, BOX_COLORS["staticBoundaryBox"]),
            BoundaryBox("boundaryBox", -4, 4, 0, 8, 0, 3, BOX_COLORS["boundaryBox"]),
            BoundaryBox("presenceBoundaryBox", -3, 3, 0.5, 7.5, 0, 3, BOX_COLORS["presenceBoundaryBox"]),
        ],
    )


def euler_rot(x: float, y: float, z: float, elev_tilt_deg: float, az_tilt_deg: float) -> tuple[float, float, float]:
    """Match TI graph_utilities.eulerRot() from graph_utilities.py:298-330."""
    elev = math.radians(elev_tilt_deg)
    azi = math.radians(az_tilt_deg)
    rot = np.array(
        [
            [math.cos(azi), math.cos(elev) * math.sin(azi), math.sin(elev) * math.sin(azi)],
            [-math.sin(azi), math.cos(elev) * math.cos(azi), math.sin(elev) * math.cos(azi)],
            [0.0, -math.sin(elev), math.cos(elev)],
        ],
        dtype=float,
    )
    out = rot @ np.array([x, y, z], dtype=float)
    return float(out[0]), float(out[1]), float(out[2])


def apply_sensor_transform_xyz(x: float, y: float, z: float, scene: SceneConfig) -> tuple[float, float, float]:
    """Rotate by configured tilt and add sensor height, like TI display code.

    TI applies eulerRot to points in plot_3d.py:85-94 and to tracks in
    people_tracking.py:111-116, then adds sensorHeight to Z.
    """
    rot_x, rot_y, rot_z = euler_rot(x, y, z, scene.elev_tilt_deg, scene.az_tilt_deg)
    return rot_x, rot_y, rot_z + scene.sensor_height


def apply_sensor_transform_array(points: np.ndarray, scene: SceneConfig) -> np.ndarray:
    if points.size == 0:
        return points.reshape((0, 3))
    elev = math.radians(scene.elev_tilt_deg)
    azi = math.radians(scene.az_tilt_deg)
    rot = np.array(
        [
            [math.cos(azi), math.cos(elev) * math.sin(azi), math.sin(elev) * math.sin(azi)],
            [-math.sin(azi), math.cos(elev) * math.cos(azi), math.sin(elev) * math.cos(azi)],
            [0.0, -math.sin(elev), math.cos(elev)],
        ],
        dtype=float,
    )
    out = points @ rot.T
    out[:, 2] += scene.sensor_height
    return out


def rotate_vector(x: float, y: float, z: float, scene: SceneConfig) -> tuple[float, float, float]:
    return euler_rot(x, y, z, scene.elev_tilt_deg, scene.az_tilt_deg)


def box_lines(box: BoundaryBox) -> np.ndarray:
    """Return 12 box edges as 24 GLLinePlotItem vertices.

    This mirrors the box-wireframe role of TI getBoxLines() from
    graph_utilities.py:246-248, implemented locally to keep this project
    standalone.
    """
    xl, xr = box.min_x, box.max_x
    yl, yr = box.min_y, box.max_y
    zl, zr = box.min_z, box.max_z
    verts = np.array(
        [
            [xl, yl, zl],
            [xr, yl, zl],
            [xl, yr, zl],
            [xr, yr, zl],
            [xl, yl, zr],
            [xr, yl, zr],
            [xl, yr, zr],
            [xr, yr, zr],
        ],
        dtype=float,
    )
    edges = [
        (0, 1),
        (0, 2),
        (1, 3),
        (2, 3),
        (4, 5),
        (4, 6),
        (5, 7),
        (6, 7),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    return np.array([verts[index] for edge in edges for index in edge], dtype=float)


def small_box_lines(center: tuple[float, float, float], size: tuple[float, float, float]) -> np.ndarray:
    cx, cy, cz = center
    sx, sy, sz = size
    box = BoundaryBox(
        "sensor",
        cx - sx / 2,
        cx + sx / 2,
        cy - sy / 2,
        cy + sy / 2,
        cz - sz / 2,
        cz + sz / 2,
        (1.0, 0.1, 0.1, 1.0),
    )
    return box_lines(box)

