"""Run the existing TI 3D UI in a responsive dual-sensor fusion layout."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
from types import MethodType
from typing import Any

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
REPO_ROOT = PROJECT_DIR.parent
DEFAULT_HUMAN_MODEL_DIR = PROJECT_DIR / "ui_human_pose_models"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import run_ti_style_visualizer as ti_launcher
from awr1642_vitals.phase_vitals.azimuth_beamforming import BeamformingConfig
from dual_sensor_fusion.awr_bin_selector import SelectorConfig
from dual_sensor_fusion.beam_lock import BeamLockConfig
from dual_sensor_fusion.chest_point_estimator import ChestEstimatorConfig
from dual_sensor_fusion.coordinate_transform import TransformConfig
from dual_sensor_fusion.dual_sensor_logger import (
    DualSensorCsvLogger,
    Fe03LivenessTracker,
    FusionConfig,
    FusionEngine,
    PrimaryTargetTracker,
    convert_awr_virtual_ant_window,
    convert_awr_window,
    extract_iwr_targets,
    make_status_fused,
)
from dual_sensor_fusion.fusion_types import AwrBinSample, AwrBinWindow
from dual_sensor_fusion.posture_gate import (
    MONITORING,
    MONITORING_POSE_GRACE,
    SEATED_LOCK,
    SittingGateConfig,
)
from dual_sensor_fusion.nearby_beam_combiner import NearbyBeamCombinerConfig
from dual_sensor_fusion.ui_performance import (
    AsyncMethodWorker,
    RateLimiter,
    RollingRate,
    downsample_series,
    drain_latest_by_kind,
)


ACTIVE_MONITORING_STATES = {MONITORING, MONITORING_POSE_GRACE, SEATED_LOCK}
from dual_sensor_fusion.run_dual_sensor_fusion_logger import (
    DEFAULT_AWR_CFG,
    DEFAULT_IWR_CFG,
    DEFAULT_POSE_MODEL,
)
from dual_sensor_fusion.vital_estimator_bridge import VitalEstimatorConfig


PHASE_PRIMARY_CHART_TITLES = (
    "Wrapped Phase",
    "Unwrapped Phase",
    "Breathing and Heartbeat Components",
)


def rolling_visible_series(
    time_values,
    *series,
    visible_window_sec: float,
    max_points: int,
):
    """Return only the latest rolling time window, bounded for plotting."""
    time_array = np.asarray(time_values, dtype=float)
    arrays = [np.asarray(values) for values in series]
    if not time_array.size:
        return (time_array, *arrays)
    latest = float(time_array[-1])
    mask = time_array >= latest - max(0.0, float(visible_window_sec))
    visible_time = time_array[mask] - latest
    visible_series = [values[mask] for values in arrays]
    return downsample_series(
        visible_time,
        *visible_series,
        max_points=max_points,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TI 3D tracking UI plus AWR1642 range-bin and vital fusion panels."
    )
    parser.add_argument("--iwr-cli", default="COM7")
    parser.add_argument("--iwr-data", default="COM6")
    parser.add_argument("--iwr-cfg", default=str(DEFAULT_IWR_CFG))
    parser.add_argument("--awr-cli", default="COM9")
    parser.add_argument("--awr-data", default="COM8")
    parser.add_argument("--awr-cfg", default=str(DEFAULT_AWR_CFG))
    parser.add_argument(
        "--out", default=str(PROJECT_DIR / "logs" / "dual_sensor_fusion_ui_test")
    )
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fs", type=float, default=10.0)
    parser.add_argument("--search-half-width", type=int, default=4)
    parser.add_argument("--azimuth-search-half-width-deg", type=float, default=20.0)
    parser.add_argument("--angle-min-deg", type=float, default=-60.0)
    parser.add_argument("--angle-max-deg", type=float, default=60.0)
    parser.add_argument("--angle-step-deg", type=float, default=2.0)
    parser.add_argument("--antenna-spacing-lambda", type=float, default=0.5)
    parser.add_argument(
        "--beam-window-type",
        choices=("none", "hann"),
        default="none",
    )
    parser.add_argument("--dx", type=float, default=0.0)
    parser.add_argument("--dy", type=float, default=0.0)
    parser.add_argument("--dz", type=float, default=0.0)
    parser.add_argument("--yaw-offset-deg", type=float, default=0.0)
    parser.add_argument(
        "--use-iwr-range-direct",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--use-chest-targeting",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Use the posture-aware chest range/azimuth for FE03 beam selection "
            "and FE02 range fallback (default: enabled)."
        ),
    )
    parser.add_argument(
        "--disable-chest-targeting",
        action="store_false",
        dest="use_chest_targeting",
        help="Use the legacy target-center/range selection path.",
    )
    parser.add_argument("--chest-sitting-height", type=float, default=0.85)
    parser.add_argument("--chest-standing-height", type=float, default=1.35)
    parser.add_argument("--sensor-dx", type=float, default=None)
    parser.add_argument("--sensor-dy", type=float, default=None)
    parser.add_argument("--sensor-dz", type=float, default=None)
    parser.add_argument("--sensor-yaw-deg", type=float, default=None)
    parser.add_argument("--sensor-pitch-deg", type=float, default=0.0)
    parser.add_argument("--sensor-roll-deg", type=float, default=0.0)
    parser.add_argument(
        "--awr-chest-height-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use AWR horizontal range + azimuth only; elevation is physically constrained.",
    )
    parser.add_argument(
        "--ignore-iwr-elevation-for-awr",
        "--awr-use-range-azimuth-only",
        action="store_true",
        dest="awr_chest_height_mode",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--sitting-stable-frames", type=int, default=10)
    parser.add_argument("--non-sitting-grace-sec", type=float, default=3.0)
    parser.add_argument("--max-grace-speed-mps", type=float, default=0.25)
    parser.add_argument("--sitting-lock-sec", type=float, default=5.0)
    parser.add_argument(
        "--allow-standing-grace",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--disable-pose-grace",
        action="store_false",
        dest="pose_grace_enabled",
        help="Restore strict posture gating with no transient-label grace.",
    )
    parser.set_defaults(pose_grace_enabled=True)
    parser.add_argument(
        "--hard-pause-on-falling",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--hard-pause-on-lying",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--primary-target-id", type=int, default=None)
    parser.add_argument("--pose-model", default=str(DEFAULT_POSE_MODEL))
    parser.add_argument(
        "--pose-human-models",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show posture-specific 3D human meshes in the embedded IWR view.",
    )
    parser.add_argument(
        "--pose-human-model-dir",
        default=str(DEFAULT_HUMAN_MODEL_DIR),
        help="Directory containing human_standing.obj, human_sitting.obj, and human_lying.obj.",
    )
    parser.add_argument(
        "--pose-human-model-mode",
        choices=("overlay_box", "replace_box", "model_only"),
        default="overlay_box",
    )
    parser.add_argument("--pose-human-model-scale", type=float, default=1.0)
    parser.add_argument("--pose-human-model-target-height", type=float, default=1.70)
    parser.add_argument("--pose-human-model-sitting-height", type=float, default=1.20)
    parser.add_argument("--pose-human-model-lying-length", type=float, default=1.70)
    parser.add_argument("--pose-human-model-height-scale", type=float, default=None)
    parser.add_argument("--pose-human-model-opacity", type=float, default=1.0)
    parser.add_argument("--pose-human-model-ground-z", type=float, default=0.0)
    parser.add_argument(
        "--pose-human-model-fallback-standing",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use the standing mesh rather than a target box for unknown poses.",
    )
    parser.add_argument(
        "--pose-human-model-debug",
        action="store_true",
        help="Enable renderer-specific mesh diagnostics.",
    )
    parser.add_argument(
        "--pose-ground-plane",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show the IWR ground plane used to align pose meshes.",
    )
    parser.add_argument("--pose-ground-plane-size", type=float, default=8.0)
    parser.add_argument("--pose-ground-plane-alpha", type=float, default=0.18)
    parser.add_argument(
        "--pose-ground-plane-grid",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--awr-cli-baud", type=int, default=115200)
    parser.add_argument("--awr-data-baud", type=int, default=921600)
    parser.add_argument("--max-awr-age", type=float, default=1.0)
    parser.add_argument("--fe03-stale-timeout-sec", type=float, default=2.0)
    parser.add_argument("--vital-display-hold-sec", type=float, default=10.0)
    parser.add_argument("--min-estimation-window-sec", type=float, default=30.0)
    parser.add_argument("--min-vital-window-sec", type=float, default=30.0)
    parser.add_argument("--min-heart-window-sec", type=float, default=30.0)
    parser.add_argument("--heart-stable-window-sec", type=float, default=60.0)
    parser.add_argument("--breath-stable-window-sec", type=float, default=30.0)
    parser.add_argument("--bpm-smoothing-sec", type=float, default=10.0)
    parser.add_argument(
        "--breath-max-jump-bpm-per-sec", type=float, default=3.0
    )
    parser.add_argument(
        "--heart-max-jump-bpm-per-sec", type=float, default=10.0
    )
    parser.add_argument("--heart-top-k-peaks", type=int, default=5)
    parser.add_argument("--heart-peak-persistence-sec", type=float, default=8.0)
    parser.add_argument("--heart-switch-confirm-sec", type=float, default=8.0)
    parser.add_argument("--heart-switch-margin", type=float, default=1.35)
    parser.add_argument("--heart-min-snr", type=float, default=3.0)
    parser.add_argument("--heart-min-confidence", type=float, default=0.35)
    parser.add_argument("--heart-window-sec", type=float, default=60.0)
    parser.add_argument("--heart-preliminary-window-sec", type=float, default=30.0)
    parser.add_argument("--breath-window-sec", type=float, default=30.0)
    parser.add_argument("--vital-model-dir")
    parser.add_argument(
        "--enable-vital-ml",
        dest="enable_vital_ml",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--disable-vital-ml",
        dest="enable_vital_ml",
        action="store_false",
    )
    parser.add_argument("--ml-min-window-sec", type=float, default=30.0)
    parser.add_argument("--phase-plot-window-sec", type=float, default=120.0)
    parser.add_argument("--phase-visible-window-sec", type=float, default=60.0)
    parser.add_argument("--beam-hysteresis-ratio", type=float, default=1.15)
    parser.add_argument("--beam-lock-sec", type=float, default=2.0)
    parser.add_argument("--beam-hold-sec", type=float, default=3.0)
    parser.add_argument("--beam-switch-margin", type=float, default=1.5)
    parser.add_argument("--beam-switch-confirm-sec", type=float, default=2.0)
    parser.add_argument("--beam-max-jump-bins", type=int, default=1)
    parser.add_argument("--beam-max-jump-deg", type=float, default=6.0)
    parser.add_argument("--disable-beam-lock", action="store_true")
    parser.add_argument(
        "--beam-switch-hold-sec",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--carrier-frequency-ghz", type=float, default=77.0)
    parser.add_argument(
        "--phase-chart-mode",
        choices=("displacement", "phase"),
        default="displacement",
    )
    parser.add_argument("--phase-smooth-sec", type=float, default=0.5)
    parser.add_argument("--phase-detrend-sec", type=float, default=20.0)
    parser.add_argument("--phase-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument(
        "--phase-unwrap-discontinuity-rad",
        type=float,
        default=math.pi,
    )
    parser.add_argument("--phase-gap-reset-sec", type=float, default=1.0)
    parser.add_argument(
        "--phase-reset-on-beam-switch",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--component-chart-normalize",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--component-chart-heart-scale", default="auto")
    parser.add_argument("--component-chart-breath-color", default="blue")
    parser.add_argument("--component-chart-heart-color", default="red")
    parser.add_argument(
        "--enable-nearby-beam-combining",
        action="store_true",
        help=(
            "Optionally combine phase-stable FE03 cells near the locked beam. "
            "The live classical estimator does not require this option or ML."
        ),
    )
    parser.add_argument(
        "--nearby-beam-range-radius-bins", type=int, default=1
    )
    parser.add_argument(
        "--nearby-beam-azimuth-radius-deg", type=float, default=6.0
    )
    parser.add_argument(
        "--beam-combine-mode",
        choices=("best", "weighted", "coherent"),
        default="weighted",
    )
    parser.add_argument("--ui-layout", choices=("full",), default="full")
    parser.add_argument(
        "--ui-scale",
        type=float,
        default=1.0,
        help="Scale application fonts without forcing fixed widget sizes.",
    )
    parser.add_argument(
        "--compact-metrics",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use tighter spacing in the scrollable metrics panel.",
    )
    parser.add_argument(
        "--diagnostics-tabbed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Place phase/PSD diagnostics in a dedicated tab (default).",
    )
    parser.add_argument("--right-panel-width", type=int, default=420)
    parser.add_argument("--plot-max-visible-points", type=int, default=1200)
    parser.add_argument("--ui-update-hz", type=float, default=10.0)
    parser.add_argument("--heatmap-update-hz", type=float, default=5.0)
    parser.add_argument("--phase-plot-update-hz", type=float, default=5.0)
    parser.add_argument("--spectrum-update-hz", type=float, default=1.0)
    parser.add_argument("--csv-flush-interval-sec", type=float, default=1.0)
    parser.add_argument("--csv-flush-rows", type=int, default=50)
    parser.add_argument(
        "--beam-score-mode",
        choices=("magnitude", "magnitude_roi_stability"),
        default="magnitude_roi_stability",
    )
    parser.add_argument("--window-width", type=int, default=1700)
    parser.add_argument("--window-height", type=int, default=1000)
    parser.add_argument(
        "--layout-debug",
        action="store_true",
        help="Draw panel borders and periodically print panel dimensions.",
    )
    parser.add_argument(
        "--demo-mode",
        action="store_true",
        help="Run synthetic IWR/AWR frames without opening serial ports.",
    )
    parser.add_argument("--no-auto-start", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser


def _make_ti_args(args: argparse.Namespace) -> argparse.Namespace:
    """Use the existing launcher's defaults while applying the proven pose flags."""
    argv = [
        "run_ti_style_visualizer.py",
        "--cli",
        args.iwr_cli,
        "--data",
        args.iwr_data,
        "--cfg",
        args.iwr_cfg,
        "--out",
        args.out,
        "--enable-pose",
        "--pose-model",
        args.pose_model,
        "--pose-log",
        "--pose-3d-labels",
        "--pose-3d-label-format",
        "ID {tid} | {final_label} {confidence_percent}%",
        "--pose-min-associated-points-for-inference",
        "1",
        "--pose-allow-target-only",
    ]
    if args.pose_human_models:
        argv.append("--pose-human-models")
    argv.extend(
        [
            "--pose-human-model-dir",
            args.pose_human_model_dir,
            "--pose-human-model-mode",
            args.pose_human_model_mode,
            "--pose-human-model-scale",
            str(args.pose_human_model_scale),
            "--pose-human-model-target-height",
            str(args.pose_human_model_target_height),
            "--pose-human-model-target-sitting-height",
            str(args.pose_human_model_sitting_height),
            "--pose-human-model-target-lying-length",
            str(args.pose_human_model_lying_length),
            "--pose-human-model-opacity",
            str(args.pose_human_model_opacity),
            "--pose-human-model-fallback",
            "standing" if args.pose_human_model_fallback_standing else "box",
            "--pose-ground-z",
            str(args.pose_human_model_ground_z),
            "--pose-ground-plane-size",
            str(args.pose_ground_plane_size),
            "--pose-ground-plane-alpha",
            str(args.pose_ground_plane_alpha),
        ]
    )
    if args.pose_human_model_height_scale is not None:
        argv.extend(
            [
                "--pose-human-model-height-scale",
                str(args.pose_human_model_height_scale),
            ]
        )
    if args.pose_human_model_debug:
        argv.append("--pose-human-model-debug")
    if args.pose_ground_plane:
        argv.append("--pose-ground-plane")
    if not args.pose_ground_plane_grid:
        argv.append("--no-pose-ground-plane-grid")
    if args.debug:
        argv.extend(["--debug", "--pose-debug"])
    if args.no_auto_start or args.demo_mode:
        argv.append("--no-auto-start")
    original_argv = sys.argv
    try:
        sys.argv = argv
        return ti_launcher.parse_args()
    finally:
        sys.argv = original_argv


def _put_latest(destination: queue.Queue, item: Any) -> None:
    try:
        destination.put_nowait(item)
    except queue.Full:
        try:
            destination.get_nowait()
        except queue.Empty:
            pass
        destination.put_nowait(item)


def _awr_worker(
    args: argparse.Namespace,
    destination: queue.Queue,
    stop_event: threading.Event,
) -> None:
    try:
        import serial
        from cli_sender import send_config
        from awr1642_vitals.phase_vitals.tlv_parser.run_live_vital_phase_virtual_ant_window_reader import (
            _extract_complete_frames,
        )

        buffer = bytearray()
        with serial.Serial(
            args.awr_data,
            args.awr_data_baud,
            timeout=0.25,
        ) as data_port:
            data_port.reset_input_buffer()
            send_config(
                cli_port=args.awr_cli,
                cli_baud=args.awr_cli_baud,
                cfg_path=args.awr_cfg,
                output=print if args.debug else None,
            )
            while not stop_event.is_set():
                waiting = int(getattr(data_port, "in_waiting", 0))
                chunk = data_port.read(min(max(waiting, 1), 65536))
                if not chunk:
                    continue
                buffer.extend(chunk)
                for _header, virtual_windows, windows, _fixed in _extract_complete_frames(
                    buffer, args.debug
                ):
                    timestamp = time.time()
                    for parsed in virtual_windows:
                        _put_latest(
                            destination,
                            (
                                "virtual_ant_window",
                                timestamp,
                                convert_awr_virtual_ant_window(
                                    parsed,
                                    timestamp,
                                ),
                            ),
                        )
                    for parsed in windows:
                        _put_latest(
                            destination,
                            (
                                "window",
                                timestamp,
                                convert_awr_window(parsed, timestamp),
                            ),
                        )
    except Exception as exc:
        _put_latest(destination, ("error", time.time(), str(exc)))


def _copy_tracks(output_dict: dict[str, Any]):
    tracks = output_dict.get("trackData")
    if tracks is None:
        return None
    try:
        return tracks.copy()
    except AttributeError:
        return [list(row) for row in tracks]


def _format_value(value: Any, digits: int = 2) -> str:
    if value is None:
        return "--"
    if isinstance(value, float) and not math.isfinite(value):
        return "--"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _build_widgets():
    from PySide2.QtCore import QPointF, QRectF, Qt
    from PySide2.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
    from PySide2.QtWidgets import (
        QFormLayout,
        QFrame,
        QLabel,
        QVBoxLayout,
        QWidget,
    )

    class AwrRangeWidget(QWidget):
        def __init__(self, phase_chart_mode="displacement"):
            super().__init__()
            self.phase_chart_mode = phase_chart_mode
            self.setMinimumSize(430, 300)
            self.window = None
            self.selection = None
            self.active = False
            self.status = "NO_AWR_WINDOW"
            self.selection_mode = "RANGE_ONLY_CHEST_GUIDED"
            self.expected_azimuth = None
            self.expected_elevation = None

        def set_state(self, window, selection, active: bool, status: str):
            self.window = window
            self.selection = selection
            self.active = bool(active)
            self.status = status
            self.update()

        def set_spatial_status(self, fused):
            self.selection_mode = fused.selectionMode
            self.expected_azimuth = fused.expectedAwrAzimuthDeg
            self.expected_elevation = fused.expectedAwrElevationDeg
            self.update()

        def paintEvent(self, _event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(24, 28, 34))
            width = max(1, self.width())
            height = max(1, self.height())
            left, right = 42.0, width - 26.0
            top, axis_y = 52.0, height - 58.0

            painter.setPen(QPen(QColor(65, 85, 105), 1))
            painter.setBrush(QBrush(QColor(30, 68, 88, 95)))
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(left, axis_y),
                        QPointF(right, top),
                        QPointF(right, axis_y),
                    ]
                )
            )
            painter.setPen(QPen(QColor(180, 190, 205), 1))
            painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))
            painter.drawText(
                QRectF(10, 8, width - 20, 28),
                Qt.AlignCenter,
                "AWR1642 Focus / Range Bins",
            )

            if self.window is None or not self.window.bins:
                painter.setPen(QColor(220, 170, 80))
                painter.drawText(
                    QRectF(10, 120, width - 20, 40),
                    Qt.AlignCenter,
                    "Waiting for TLV 0xFE02",
                )
                return

            bins = self.window.bins
            min_bin = min(sample.binIndex for sample in bins)
            max_bin = max(sample.binIndex for sample in bins)
            span = max(1, max_bin - min_bin)
            max_mag = max(1.0, max(sample.magnitude for sample in bins))

            def x_for(bin_index: int) -> float:
                return left + (bin_index - min_bin) * (right - left) / span

            for sample in bins:
                x = x_for(sample.binIndex)
                bar_height = 95.0 * max(0.0, sample.magnitude) / max_mag
                painter.setPen(QPen(QColor(80, 125, 155), 2))
                painter.drawLine(
                    QPointF(x, axis_y - 2),
                    QPointF(x, axis_y - 2 - bar_height),
                )
                if sample.binIndex % 5 == 0:
                    painter.setPen(QColor(155, 165, 175))
                    painter.drawText(
                        QRectF(x - 15, axis_y + 5, 30, 18),
                        Qt.AlignCenter,
                        str(sample.binIndex),
                    )

            markers = []
            if self.window.strongestBin is not None:
                markers.append(
                    (self.window.strongestBin, QColor(255, 196, 70), "strongest")
                )
            if self.selection and self.selection.expectedAwrBin is not None:
                markers.append(
                    (self.selection.expectedAwrBin, QColor(70, 205, 255), "expected")
                )
            if self.selection and self.selection.selectedAwrBin is not None:
                color = QColor(65, 220, 120) if self.active else QColor(220, 105, 80)
                markers.append((self.selection.selectedAwrBin, color, "selected"))
            if min_bin <= 32 <= max_bin:
                markers.append((32, QColor(205, 115, 255), "fixed 32"))

            label_y = 34.0
            for bin_index, color, label in markers:
                x = x_for(bin_index)
                painter.setPen(QPen(color, 3 if label == "selected" else 2))
                painter.drawLine(QPointF(x, top), QPointF(x, axis_y))
                painter.setPen(color)
                painter.drawText(
                    QRectF(x - 45, label_y, 90, 18),
                    Qt.AlignCenter,
                    f"{label}: {bin_index}",
                )
                label_y += 18.0

            painter.setPen(
                QColor(70, 225, 125) if self.active else QColor(235, 150, 90)
            )
            painter.drawText(
                QRectF(10, height - 30, width - 20, 20),
                Qt.AlignCenter,
                f"{self.status} | selected range "
                f"{_format_value(getattr(self.selection, 'selectedAwrRangeMeters', None), 3)} m "
                f"| magnitude {_format_value(getattr(self.selection, 'selectedMagnitude', None), 0)}",
            )

    class VitalPanel(QWidget):
        def __init__(
            self,
            phase_chart_mode: str = "displacement",
            phase_smooth_sec: float = 0.5,
            phase_detrend_sec: float = 20.0,
        ):
            super().__init__()
            self.phase_chart_mode = phase_chart_mode
            self.phase_smooth_sec = max(0.0, float(phase_smooth_sec))
            self.phase_detrend_sec = max(0.0, float(phase_detrend_sec))
            layout = QVBoxLayout(self)
            self.banner = QLabel("Vitals paused — no target")
            self.banner.setAlignment(Qt.AlignCenter)
            self.banner.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            self.banner.setMinimumHeight(34)
            layout.addWidget(self.banner)
            form = QFormLayout()
            self.values = {}
            for key, label in [
                ("target", "Target ID"),
                ("posture", "Posture"),
                ("state", "Monitoring state"),
                ("iwr_range", "IWR target range"),
                ("expected_bin", "Expected AWR bin"),
                ("selected_bin", "Selected AWR bin"),
                ("selected_range", "Selected AWR range"),
                ("magnitude", "Selected magnitude"),
                ("breath", "Breathing rate"),
                ("heart", "Heart rate"),
                ("quality", "Quality"),
                ("motion", "Motion flag"),
                ("updated", "Last update"),
                ("reason", "Reason"),
            ]:
                value = QLabel("--")
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(label, value)
                self.values[key] = value
            layout.addLayout(form)

        def set_no_target(self, state: str = "NO_TARGET", reason: str = ""):
            self.banner.setText("Vitals paused — no IWR target")
            self.banner.setStyleSheet("background:#6b4b2a; color:white; padding:5px;")
            for value in self.values.values():
                value.setText("--")
            self.values["state"].setText(state)
            self.values["reason"].setText(reason or "No tracked person")
            self.values["updated"].setText(time.strftime("%H:%M:%S"))

        def set_fused(self, fused):
            active = fused.monitoringState in ACTIVE_MONITORING_STATES
            if fused.monitoringState == MONITORING_POSE_GRACE:
                banner = "Vitals active — brief pose glitch grace"
                color = "#6f5d20"
            elif active:
                banner = "Vitals active — stable SITTING"
                color = "#245f3a"
            elif fused.monitoringState == "PAUSED_NOT_SITTING":
                banner = "Vitals paused — target not sitting"
                color = "#70452f"
            else:
                banner = f"Vitals paused — {fused.monitoringState}"
                color = "#6b4b2a"
            self.banner.setText(banner)
            self.banner.setStyleSheet(
                f"background:{color}; color:white; padding:5px; font-weight:bold;"
            )
            values = {
                "target": fused.targetId,
                "posture": fused.posture,
                "state": fused.monitoringState,
                "iwr_range": f"{_format_value(fused.iwrRangeMeters, 3)} m",
                "expected_bin": fused.expectedAwrBin,
                "selected_bin": fused.selectedAwrBin,
                "selected_range": f"{_format_value(fused.selectedAwrRangeMeters, 3)} m",
                "magnitude": _format_value(fused.selectedMagnitude, 1),
                "breath": (
                    f"{_format_value(fused.breathingBpm, 1)} BPM"
                    if active
                    else "--"
                ),
                "heart": (
                    f"{_format_value(fused.heartBpm, 1)} BPM" if active else "--"
                ),
                "quality": fused.quality,
                "motion": "YES" if fused.motionDetected else "NO",
                "updated": time.strftime("%H:%M:%S"),
                "reason": fused.selectionReason,
            }
            for key, value in values.items():
                self.values[key].setText(str(value if value is not None else "--"))

    return AwrRangeWidget, VitalPanel


def _build_responsive_widgets():
    """Build bounded fusion panels that scale independently of the TI plot."""
    import numpy as np
    import pyqtgraph as pg

    from PySide2.QtCore import QPointF, QRectF, Qt
    from PySide2.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
    from PySide2.QtWidgets import (
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )

    class AwrRangeCanvas(QWidget):
        def __init__(self):
            super().__init__()
            self.setMinimumSize(320, 250)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.window = None
            self.virtual_window = None
            self.candidate_beam = None
            self.locked_beam = None
            self.selection = None
            self.active = False

        def set_state(
            self,
            window,
            selection,
            active,
            virtual_window=None,
            candidate_beam=None,
            locked_beam=None,
        ):
            self.window = window
            self.virtual_window = virtual_window
            self.candidate_beam = candidate_beam
            self.locked_beam = locked_beam
            self.selection = selection
            self.active = bool(active)
            self.update()

        def paintEvent(self, _event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(24, 28, 34))
            width = max(1, self.width())
            height = max(1, self.height())
            left, right = 56.0, width - 24.0
            top, axis_y = 30.0, height - 54.0
            graph_width = max(1.0, right - left)
            graph_height = max(1.0, axis_y - top)

            if (
                self.virtual_window is not None
                and (self.candidate_beam is not None or self.locked_beam is not None)
                and (self.candidate_beam or self.locked_beam).beamMap is not None
            ):
                self._paint_fe03(
                    painter,
                    left,
                    top,
                    graph_width,
                    graph_height,
                )
                return

            painter.setPen(QPen(QColor(65, 85, 105), 1))
            painter.setBrush(QBrush(QColor(30, 68, 88, 65)))
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF((left + right) / 2.0, axis_y),
                        QPointF(left, top),
                        QPointF(right, top),
                    ]
                )
            )
            painter.setPen(QPen(QColor(180, 190, 205), 1))
            painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))

            if self.window is None or not self.window.bins:
                painter.setPen(QColor(220, 170, 80))
                painter.drawText(
                    QRectF(10, height / 2.0 - 20, width - 20, 40),
                    Qt.AlignCenter,
                    "Waiting for TLV 0xFE02",
                )
                return

            bins = self.window.bins
            min_bin = min(sample.binIndex for sample in bins)
            max_bin = max(sample.binIndex for sample in bins)
            span = max(1, max_bin - min_bin)
            max_mag = max(1.0, max(sample.magnitude for sample in bins))

            def x_for(bin_index: int) -> float:
                return left + (bin_index - min_bin) * graph_width / span

            for sample in bins:
                x = x_for(sample.binIndex)
                bar_height = (
                    graph_height
                    * 0.68
                    * max(0.0, sample.magnitude)
                    / max_mag
                )
                painter.setPen(QPen(QColor(75, 135, 175), 2))
                painter.drawLine(
                    QPointF(x, axis_y - 2),
                    QPointF(x, axis_y - 2 - bar_height),
                )
                if sample.binIndex % 5 == 0:
                    painter.setPen(QColor(155, 165, 175))
                    painter.drawText(
                        QRectF(x - 15, axis_y + 5, 30, 18),
                        Qt.AlignCenter,
                        str(sample.binIndex),
                    )

            painter.setPen(QColor(150, 165, 178))
            painter.drawText(
                QRectF(4, top - 8, left - 10, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{max_mag:.0f}",
            )
            painter.drawText(
                QRectF(4, axis_y - 8, left - 10, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                "0",
            )
            painter.drawText(
                QRectF(left, height - 24, graph_width, 18),
                Qt.AlignCenter,
                "Range-bin index",
            )

            markers = []
            if self.window.strongestBin is not None:
                markers.append(
                    (self.window.strongestBin, QColor(255, 196, 70), "strongest")
                )
            if self.selection and self.selection.expectedAwrBin is not None:
                markers.append(
                    (self.selection.expectedAwrBin, QColor(70, 205, 255), "expected")
                )
            if self.selection and self.selection.selectedAwrBin is not None:
                selected_color = (
                    QColor(255, 112, 67)
                    if self.active
                    else QColor(194, 91, 66)
                )
                markers.append(
                    (self.selection.selectedAwrBin, selected_color, "selected")
                )
            if min_bin <= 32 <= max_bin:
                markers.append((32, QColor(205, 115, 255), "fixed 32"))

            for marker_index, (bin_index, color, label) in enumerate(markers):
                x = x_for(bin_index)
                painter.setPen(QPen(color, 3 if label == "selected" else 2))
                painter.drawLine(QPointF(x, top), QPointF(x, axis_y))
                painter.setPen(color)
                label_width = 92.0
                label_x = max(
                    2.0,
                    min(width - label_width - 2.0, x - label_width / 2.0),
                )
                painter.drawText(
                    QRectF(
                        label_x,
                        top + 4.0 + marker_index * 18.0,
                        label_width,
                        18,
                    ),
                    Qt.AlignCenter,
                    f"{label}: {bin_index}",
                )

        def _paint_fe03(
            self,
            painter,
            left: float,
            top: float,
            graph_width: float,
            graph_height: float,
        ):
            import numpy as np

            map_source = self.candidate_beam or self.locked_beam
            beam_map = np.asarray(map_source.beamMap)
            magnitudes = np.abs(beam_map)
            if magnitudes.size == 0:
                return
            angles = np.asarray(map_source.angleGridDeg, dtype=float)
            bins = np.asarray(self.virtual_window.binIndices, dtype=float)
            rows, columns = magnitudes.shape
            cell_width = graph_width / max(1, columns)
            cell_height = graph_height / max(1, rows)
            max_magnitude = max(1.0, float(np.max(magnitudes)))

            painter.setPen(Qt.NoPen)
            for row in range(rows):
                for column in range(columns):
                    level = min(
                        1.0,
                        float(magnitudes[row, column]) / max_magnitude,
                    )
                    painter.setBrush(
                        QColor(
                            int(18 + 220 * level),
                            int(35 + 120 * level),
                            int(70 + 30 * (1.0 - level)),
                        )
                    )
                    painter.drawRect(
                        QRectF(
                            left + column * cell_width,
                            top + row * cell_height,
                            cell_width + 0.5,
                            cell_height + 0.5,
                        )
                    )

            def x_for(angle: float) -> float:
                if len(angles) <= 1:
                    return left + graph_width / 2.0
                return left + (
                    (angle - float(angles[0]))
                    / (float(angles[-1]) - float(angles[0]))
                    * graph_width
                )

            def y_for(bin_index: float) -> float:
                if len(bins) <= 1:
                    return top + graph_height / 2.0
                return top + (
                    (bin_index - float(bins[0]))
                    / (float(bins[-1]) - float(bins[0]))
                    * graph_height
                )

            expected_x = x_for(map_source.expectedAzimuthDeg)
            expected_y = y_for(map_source.expectedRangeBin)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(70, 205, 255), 2))
            painter.drawEllipse(QPointF(expected_x, expected_y), 7, 7)
            painter.drawText(
                QRectF(expected_x + 8, expected_y - 18, 130, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                "IWR chest expected",
            )
            if self.candidate_beam is not None:
                candidate_x = x_for(self.candidate_beam.selectedAzimuthDeg)
                candidate_y = y_for(self.candidate_beam.selectedRangeBin)
                painter.setPen(QPen(QColor(255, 196, 70), 2))
                painter.drawEllipse(QPointF(candidate_x, candidate_y), 7, 7)
                painter.drawText(
                    QRectF(candidate_x + 8, candidate_y - 18, 130, 18),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    "AWR candidate",
                )
            if self.locked_beam is not None:
                locked_x = x_for(self.locked_beam.selectedAzimuthDeg)
                locked_y = y_for(self.locked_beam.selectedRangeBin)
                selected_color = (
                    QColor(255, 112, 67)
                    if self.active
                    else QColor(194, 91, 66)
                )
                painter.setPen(QPen(selected_color, 3))
                painter.drawEllipse(QPointF(locked_x, locked_y), 9, 9)
                painter.drawText(
                    QRectF(locked_x + 8, locked_y + 2, 140, 18),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    "locked chest beam",
                )
            painter.setPen(QPen(QColor(180, 190, 205), 1))
            painter.drawRect(QRectF(left, top, graph_width, graph_height))
            painter.drawText(
                QRectF(left, top + graph_height + 5, graph_width, 18),
                Qt.AlignCenter,
                "Azimuth angle (deg)",
            )
            painter.drawText(
                QRectF(left, top - 22, graph_width, 18),
                Qt.AlignCenter,
                "FE03 range × azimuth beam magnitude",
            )
            painter.drawText(
                QRectF(3, top, left - 8, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                str(int(bins[0])),
            )
            painter.drawText(
                QRectF(3, top + graph_height - 18, left - 8, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                str(int(bins[-1])),
            )
            for angle in (-60, -30, 0, 30, 60):
                if angles[0] <= angle <= angles[-1]:
                    x = x_for(angle)
                    painter.drawText(
                        QRectF(x - 18, top + graph_height - 18, 36, 18),
                        Qt.AlignCenter,
                        str(angle),
                    )

    class AwrRangeWidget(QGroupBox):
        def __init__(self):
            super().__init__("AWR1642 Focus / Range Bins")
            self.window = None
            self.selection = None
            self.virtual_window = None
            self.candidate_beam = None
            self.locked_beam = None
            self.active = False
            self.status = "NO_AWR_WINDOW"
            self.selection_mode = "RANGE_ONLY_CHEST_GUIDED"
            self.expected_azimuth = None
            self.expected_elevation = None
            self.selected_azimuth = None
            self.num_virtual_antennas = None
            self.fe03_status = "NOT_AVAILABLE"
            self.fe03_age_sec = None
            self.fe03_fps = 0.0
            self.beam_state = "SEARCHING_BEAM"
            self.setMinimumWidth(330)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(8, 10, 8, 8)
            layout.setSpacing(6)
            self.canvas = AwrRangeCanvas()
            layout.addWidget(self.canvas, 1)
            legend = QLabel(
                '<span style="color:#46cdff">Expected</span>  '
                '<span style="color:#ffc446">Candidate</span>  '
                '<span style="color:#ff7043">Locked</span>  '
                '<span style="color:#cd73ff">Fixed 32</span>  '
                '<span style="color:#ffc446">Strongest</span>'
            )
            legend.setAlignment(Qt.AlignCenter)
            layout.addWidget(legend)
            self.status_strip = QLabel("Waiting for AWR TLV 0xFE03 or 0xFE02")
            self.status_strip.setAlignment(Qt.AlignCenter)
            self.status_strip.setWordWrap(True)
            self.status_strip.setMinimumHeight(42)
            layout.addWidget(self.status_strip)
            self._update_strip()

        def _update_strip(self):
            selected_range = _format_value(
                getattr(self.selection, "selectedAwrRangeMeters", None), 3
            )
            magnitude = _format_value(
                getattr(self.selection, "selectedMagnitude", None), 0
            )
            self.status_strip.setText(
                "IWR chest ROI estimate → AWR selected chest beam | "
                "AWR range+azimuth only | AWR elevation unavailable on "
                "AWR1642BOOST; chest height is physically constrained | "
                f"{self.status}  |  locked {selected_range} m"
                f"  |  magnitude {magnitude}  |  "
                f"expected az {_format_value(self.expected_azimuth, 1)} deg  |  "
                f"locked az {_format_value(self.selected_azimuth, 1)} deg  |  "
                f"elevation {_format_value(self.expected_elevation, 1)} deg"
                " (IWR metadata only)  |  "
                f"{self.fe03_status} + {self.beam_state}"
                f" age {_format_value(self.fe03_age_sec, 2)} s"
                f" / {_format_value(self.fe03_fps, 1)} FPS"
                f" ({_format_value(self.num_virtual_antennas, 0)} ant)  |  "
                f"{self.selection_mode} | candidate chest displacement signal"
            )
            color = "#255d3b" if self.active else "#5f4931"
            self.status_strip.setStyleSheet(
                f"background:{color}; color:white; border-radius:4px; padding:4px;"
            )

        def set_state(
            self,
            window,
            selection,
            active: bool,
            status: str,
            virtual_window=None,
            candidate_beam=None,
            locked_beam=None,
        ):
            self.window = window
            self.virtual_window = virtual_window
            self.candidate_beam = candidate_beam
            self.locked_beam = locked_beam
            self.selection = selection
            self.active = bool(active)
            self.status = status
            self.canvas.set_state(
                window,
                selection,
                active,
                virtual_window,
                candidate_beam,
                locked_beam,
            )
            self.setTitle(
                "AWR1642 Range / Azimuth Beamforming"
                if virtual_window is not None
                else "AWR1642 Focus / Range Bins"
            )
            self._update_strip()

        def set_spatial_status(self, fused):
            self.selection_mode = fused.selectionMode
            self.expected_azimuth = fused.expectedAwrAzimuthDeg
            self.expected_elevation = fused.expectedAwrElevationDeg
            self.selected_azimuth = fused.selectedAwrAzimuthDeg
            self.num_virtual_antennas = fused.numVirtualAntennas
            self.fe03_status = fused.fe03Status
            self.fe03_age_sec = fused.fe03AgeSec
            self.fe03_fps = fused.fe03FramesPerSecond
            self.beam_state = fused.beamState
            self._update_strip()

    class DashboardCard(QFrame):
        def __init__(self, title: str):
            super().__init__()
            self.setFrameShape(QFrame.StyledPanel)
            self.setStyleSheet(
                "background:#252b33; border:1px solid #46515e;"
                " border-radius:6px;"
            )
            self.grid = QGridLayout(self)
            self.grid.setContentsMargins(12, 8, 12, 8)
            self.grid.setHorizontalSpacing(12)
            self.grid.setVerticalSpacing(4)
            title_label = QLabel(title)
            title_label.setStyleSheet(
                "border:0; font-weight:600; color:#a9c7df; padding-bottom:3px;"
            )
            self.grid.addWidget(title_label, 0, 0, 1, 2)
            self.row = 1

        def add_metric(self, label: str, large: bool = False):
            name = QLabel(label)
            name.setStyleSheet("border:0;")
            value = QLabel("--")
            value.setStyleSheet("border:0;")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if large:
                value.setStyleSheet(
                    "border:0; font-size:22px; font-weight:700; color:#f4f7fa;"
                )
            self.grid.addWidget(name, self.row, 0)
            self.grid.addWidget(value, self.row, 1)
            self.row += 1
            return value

    class FusionStatusSummary(QGroupBox):
        def __init__(self):
            super().__init__("Fusion Status Summary")
            layout = QGridLayout(self)
            self.values = {}
            rows = [
                ("iwr", "IWR stream"),
                ("awr", "AWR stream"),
                ("iwr_frame", "Latest IWR frame"),
                ("awr_frame", "Latest AWR frame"),
                ("updated", "Fused update"),
                ("target", "Selected target"),
                ("bin", "Selected bin"),
                ("iwr_fps", "IWR FPS"),
                ("fe03_fps", "FE03 FPS"),
                ("ui_fps", "UI FPS"),
                ("ui_latency", "UI update latency"),
                ("processing_latency", "Processing latency"),
                ("plot_points", "Visible plot points"),
                ("phase_seconds", "Phase buffer"),
                ("dropped_frames", "Dropped UI frames"),
                ("csv_backlog", "CSV backlog"),
                ("csv_flush_age", "Last CSV flush"),
            ]
            for row, (key, text) in enumerate(rows):
                layout.addWidget(QLabel(text), row, 0)
                value = QLabel("Waiting")
                value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                layout.addWidget(value, row, 1)
                self.values[key] = value

        def update_status(self, **updates):
            aliases = {"selected_bin": "bin"}
            for key, value in updates.items():
                key = aliases.get(key, key)
                if key in self.values and value is not None:
                    self.values[key].setText(str(value))

    class VitalPanel(QWidget):
        def __init__(self, compact: bool = False):
            super().__init__()
            self.setMinimumWidth(300)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = QVBoxLayout(self)
            margin = 4 if compact else 8
            spacing = 4 if compact else 7
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(spacing)
            self.banner = QLabel("Vitals paused — no target")
            self.banner.setAlignment(Qt.AlignCenter)
            self.banner.setMinimumHeight(36)
            layout.addWidget(self.banner)

            cards = QVBoxLayout()
            cards.setSpacing(spacing)
            self.values = {}

            target_card = DashboardCard("TARGET / POSTURE")
            for key, label in [
                ("target", "Target ID"),
                ("posture", "Posture"),
                ("raw_posture", "Raw posture"),
                ("stable_posture", "Displayed posture"),
                ("gate_posture", "Gate posture"),
                ("state", "Monitoring state"),
                ("chest_confidence", "Chest ROI confidence"),
                ("grace_remaining", "Grace remaining"),
                ("non_sitting_streak", "Non-sitting streak"),
                ("last_stable_posture", "Last stable posture"),
                ("reason", "Reason"),
            ]:
                self.values[key] = target_card.add_metric(label)
            self.values["reason"].setWordWrap(True)

            bin_card = DashboardCard("AWR BIN SELECTION")
            for key, label in [
                ("iwr_range", "IWR target range"),
                ("iwr_angles", "IWR azimuth / elevation"),
                ("iwr_xyz", "IWR x / y / z"),
                ("expected_horizontal_range", "Expected AWR horizontal range"),
                ("expected_bin", "Expected bin"),
                ("candidate_beam", "Candidate beam"),
                ("locked_beam", "Locked chest beam"),
                ("beam_state", "Beam state"),
                ("beam_lock_age", "Beam lock age"),
                ("selected_bin", "Selected bin"),
                ("selected_range", "Selected range"),
                ("magnitude", "Selected magnitude"),
                ("strongest_bin", "Strongest overall"),
                ("expected_azimuth", "Expected azimuth"),
                ("selected_azimuth", "Selected azimuth"),
                ("azimuth_error", "Azimuth error"),
                ("expected_elevation", "IWR elevation (metadata)"),
                ("fe03_status", "FE03 status"),
                ("fe03_age", "FE03 age"),
                ("fe03_frame", "Latest FE03 frame"),
                ("fe03_fps", "FE03 FPS"),
                ("virtual_antennas", "Virtual antennas"),
                ("beam_score", "Beam score"),
                ("beam_switches", "Beam switches"),
                ("selection_mode", "Selection mode"),
            ]:
                self.values[key] = bin_card.add_metric(label)

            vital_card = DashboardCard("VITALS")
            self.values["breath"] = vital_card.add_metric("Breathing", large=True)
            self.values["heart"] = vital_card.add_metric("Heart", large=True)
            for key, label in [
                ("breath_state", "Breath estimate state"),
                ("heart_state", "Heart estimate state"),
                ("heart_raw_candidate", "Raw HR candidate"),
                ("heart_tracked", "Tracked / displayed HR"),
                ("heart_candidates", "HR candidates"),
                ("heart_switch", "HR switch state"),
                ("heart_hold", "HR hold reason"),
                ("heart_reason", "HR quality reason"),
                ("breath_ml", "ML breathing"),
                ("heart_ml", "ML heart"),
                ("quality", "Quality"),
                ("estimate_age", "Estimate age"),
                ("motion", "Motion"),
                ("updated", "Last update"),
            ]:
                self.values[key] = vital_card.add_metric(label)

            cards.addWidget(target_card, 1)
            cards.addWidget(bin_card, 1)
            cards.addWidget(vital_card, 1)
            layout.addLayout(cards, 1)
            self._set_banner("NO_TARGET", "Vitals paused — no target")

        def _set_banner(self, state: str, text: str):
            colors = {
                "MONITORING": "#24713f",
                "MONITORING_POSE_GRACE": "#6f5d20",
                "SEATED_LOCK": "#2d6b57",
                "WAITING_FOR_SITTING": "#40576d",
                "PAUSED_NOT_SITTING": "#8a5a20",
                "POSTURE_UNSTABLE": "#8a5a20",
                "NO_TARGET": "#555d66",
                "TARGET_LOST": "#555d66",
                "NO_AWR_WINDOW": "#a34d24",
                "NO_BIN": "#a34d24",
                "BIN_SWITCHING": "#8a5a20",
            }
            self.banner.setText(text)
            self.banner.setStyleSheet(
                f"background:{colors.get(state, '#555d66')}; color:white;"
                " border-radius:5px; padding:6px; font-weight:700;"
            )

        def set_no_target(self, state: str = "NO_TARGET", reason: str = ""):
            text = (
                "Waiting for AWR bin-window data"
                if state == "NO_AWR_WINDOW"
                else "Vitals paused — no IWR target"
            )
            self._set_banner(state, text)
            for value in self.values.values():
                value.setText("--")
            self.values["state"].setText(state)
            self.values["reason"].setText(reason or "No tracked person")
            self.values["updated"].setText(time.strftime("%H:%M:%S"))

        def set_fused(self, fused, selection=None):
            active = fused.monitoringState in ACTIVE_MONITORING_STATES
            if active and fused.beamState in {"SEARCHING_BEAM", "BEAM_CANDIDATE"}:
                banner = "Monitoring active - beam locking..."
            elif fused.monitoringState == MONITORING_POSE_GRACE:
                banner = "Vitals active — brief pose glitch grace"
            elif fused.monitoringState == SEATED_LOCK:
                banner = "Vitals active — seated lock"
            elif active:
                banner = "Vitals active — stable SITTING"
            elif fused.estimateHeld:
                banner = "Vitals held — brief posture/beam/input glitch"
            elif fused.monitoringState == "PAUSED_NOT_SITTING":
                banner = "Vitals paused — target not sitting"
            elif fused.monitoringState == "NO_AWR_WINDOW":
                banner = "Waiting for AWR bin-window data"
            else:
                banner = f"Vitals paused — {fused.monitoringState}"
            self._set_banner(fused.monitoringState, banner)
            values = {
                "target": fused.targetId,
                "posture": fused.posture,
                "raw_posture": fused.rawPosture,
                "stable_posture": fused.stablePosture,
                "gate_posture": fused.gatePosture,
                "state": fused.monitoringState,
                "chest_confidence": (
                    f"{_format_value(fused.chestConfidence * 100.0, 0)}%"
                    if fused.chestConfidence is not None
                    else "--"
                ),
                "grace_remaining": (
                    f"{fused.graceRemainingSec:.1f} s"
                    if fused.poseGraceActive
                    else "--"
                ),
                "non_sitting_streak": f"{fused.nonSittingStreakSec:.1f} s",
                "last_stable_posture": fused.lastStablePosture,
                "iwr_range": f"{_format_value(fused.iwrRangeMeters, 3)} m",
                "iwr_angles": (
                    f"{_format_value(fused.iwrAzimuthDeg, 1)} / "
                    f"{_format_value(fused.iwrElevationDeg, 1)} deg"
                ),
                "iwr_xyz": (
                    f"{_format_value(fused.iwrX, 2)} / "
                    f"{_format_value(fused.iwrY, 2)} / "
                    f"{_format_value(fused.iwrZ, 2)} m"
                ),
                "expected_horizontal_range": (
                    f"{_format_value(fused.expectedAwrRangeHorizontalMeters, 3)} m"
                ),
                "expected_bin": fused.expectedAwrBin,
                "candidate_beam": (
                    f"bin {fused.candidateRangeBin}, "
                    f"{_format_value(fused.candidateAzimuthDeg, 1)} deg, "
                    f"mag {_format_value(fused.candidateMagnitude, 0)}"
                ),
                "locked_beam": (
                    f"bin {fused.lockedRangeBin}, "
                    f"{_format_value(fused.lockedAzimuthDeg, 1)} deg, "
                    f"mag {_format_value(fused.lockedMagnitude, 0)}"
                ),
                "beam_state": fused.beamState,
                "beam_lock_age": (
                    f"{fused.beamLockAgeSec:.1f} s"
                    if fused.beamLockAgeSec is not None
                    else "--"
                ),
                "selected_bin": fused.selectedAwrBin,
                "selected_range": (
                    f"{_format_value(fused.selectedAwrRangeMeters, 3)} m"
                ),
                "magnitude": _format_value(fused.selectedMagnitude, 1),
                "strongest_bin": getattr(selection, "strongestOverallBin", None),
                "expected_azimuth": (
                    f"{_format_value(fused.expectedAwrAzimuthDeg, 1)} deg"
                ),
                "selected_azimuth": (
                    f"{_format_value(fused.selectedAwrAzimuthDeg, 1)} deg"
                ),
                "azimuth_error": (
                    f"{_format_value(fused.azimuthErrorDeg, 1)} deg"
                ),
                "expected_elevation": (
                    f"{_format_value(fused.expectedAwrElevationDeg, 1)} deg"
                ),
                "fe03_status": fused.fe03Status,
                "fe03_age": (
                    f"{fused.fe03AgeSec:.2f} s"
                    if fused.fe03AgeSec is not None
                    else "--"
                ),
                "fe03_frame": fused.latestFe03FrameNumber,
                "fe03_fps": f"{fused.fe03FramesPerSecond:.1f}",
                "virtual_antennas": fused.numVirtualAntennas,
                "beam_score": _format_value(fused.selectedBeamScore, 3),
                "beam_switches": fused.beamSwitchCount,
                "selection_mode": fused.selectionMode,
                "breath": (
                    "collecting..."
                    if fused.breathCollecting and fused.breathingBpm is None
                    else (
                        f"{_format_value(fused.breathingBpm, 1)} bpm"
                        + (" HOLD" if fused.estimateHeld else "")
                        if fused.breathingBpm is not None
                        and (active or fused.estimateHeld)
                        else "--"
                    )
                ),
                "breath_state": fused.breathEstimateState,
                "heart_state": fused.heartEstimateState,
                "heart_raw_candidate": (
                    f"{_format_value(fused.rawHeartCandidateBpm, 1)} bpm"
                    if fused.rawHeartCandidateBpm is not None
                    else "--"
                ),
                "heart_tracked": (
                    f"{_format_value(fused.trackedHeartBpm, 1)} / "
                    f"{_format_value(fused.displayedHeartBpm, 1)} bpm"
                    if fused.trackedHeartBpm is not None
                    else "--"
                ),
                "heart_candidates": fused.heartCandidateCount,
                "heart_switch": (
                    "pending "
                    f"{_format_value(fused.heartSwitchCandidateBpm, 1)} bpm"
                    if fused.heartSwitchPending
                    else "stable"
                ),
                "heart_hold": fused.heartHoldReason or "--",
                "heart_reason": fused.heartQualityReason or "--",
                "breath_ml": (
                    f"{_format_value(fused.breathingBpmMl, 1)} bpm"
                    if fused.breathingBpmMl is not None
                    else "--"
                ),
                "heart_ml": (
                    f"{_format_value(fused.heartBpmMl, 1)} bpm"
                    if fused.heartBpmMl is not None
                    else "--"
                ),
                "heart": (
                    "heart collecting..."
                    if fused.heartCollecting and fused.heartBpm is None
                    else (
                        f"{_format_value(fused.heartBpm, 1)} bpm"
                        + (" HOLD" if fused.estimateHeld else "")
                        if fused.heartBpm is not None
                        and (active or fused.estimateHeld)
                        else "--"
                    )
                ),
                "quality": fused.quality,
                "estimate_age": (
                    f"{fused.estimateAgeSec:.1f} s"
                    if fused.estimateAgeSec is not None
                    else "--"
                ),
                "motion": "YES" if fused.motionDetected else "NO",
                "updated": time.strftime("%H:%M:%S"),
                "reason": (
                    f"{fused.postureGateReason}; {fused.selectionReason}"
                    if fused.selectionReason
                    else fused.postureGateReason
                ),
            }
            for key, value in values.items():
                self.values[key].setText(str(value if value is not None else "--"))

    class PhaseDiagnosticsPanel(QWidget):
        """Three rolling waveform views for locked chest-beam phase quality."""

        def __init__(
            self,
            phase_chart_mode: str = "displacement",
            phase_smooth_sec: float = 0.5,
            phase_detrend_sec: float = 20.0,
            visible_window_sec: float = 60.0,
            max_visible_points: int = 1200,
            component_normalize: bool = True,
            component_heart_scale: str = "auto",
            breath_color: str = "blue",
            heart_color: str = "red",
            parent=None,
        ):
            super().__init__(parent)
            self.phase_chart_mode = phase_chart_mode
            self.phase_smooth_sec = max(0.0, float(phase_smooth_sec))
            self.phase_detrend_sec = max(0.0, float(phase_detrend_sec))
            self.visible_window_sec = max(1.0, float(visible_window_sec))
            self.max_visible_points = max(100, int(max_visible_points))
            self.component_normalize = bool(component_normalize)
            self.component_heart_scale = component_heart_scale
            self.rendered_point_count = 0
            self.setMinimumSize(600, 280)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(4)
            self.status = QLabel(
                "Waiting for selected AWR chest beam phase samples"
            )
            self.status.setWordWrap(True)
            self.status.setStyleSheet(
                "background:#2d333b; color:#dce6ef; border-radius:4px;"
                " padding:5px;"
            )
            layout.addWidget(self.status)

            plots = QVBoxLayout()
            plots.setSpacing(4)
            self.raw_plot = self._make_plot("Wrapped Phase", "rad")
            self.raw_plot.setYRange(-math.pi, math.pi, padding=0.02)
            self.unwrap_plot = self._make_plot(
                "Chest Displacement from Unwrapped Phase"
                if phase_chart_mode == "displacement"
                else "Unwrapped Phase",
                "mm" if phase_chart_mode == "displacement" else "rad",
            )
            component_units = (
                "normalized amplitude"
                if self.component_normalize
                else ("mm" if phase_chart_mode == "displacement" else "rad")
            )
            self.component_plot = self._make_plot(
                "Breathing and Heartbeat Components", component_units
            )
            self.component_plot.addLegend(offset=(8, 8))
            plots.addWidget(self.raw_plot, 1)
            plots.addWidget(self.unwrap_plot, 1)
            plots.addWidget(self.component_plot, 1)
            layout.addLayout(plots, 1)

            self.raw_curve = self.raw_plot.plot(pen=pg.mkPen("#73c5ff", width=1))
            self.unwrap_curve = self.unwrap_plot.plot(
                pen=pg.mkPen("#b89cff", width=1)
            )
            self.breath_curve = self.component_plot.plot(
                pen=pg.mkPen(breath_color, width=2),
                name="Estimated breathing-band component",
            )
            self.heart_curve = self.component_plot.plot(
                pen=pg.mkPen(heart_color, width=1.5),
                name="Estimated heart-band component",
            )

        @staticmethod
        def _make_plot(title: str, left_label: str):
            plot = pg.PlotWidget(title=title)
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("bottom", "Time", units="s")
            plot.setLabel("left", left_label)
            plot.setMenuEnabled(False)
            return plot

        def set_diagnostics(
            self,
            diagnostics,
            fused=None,
            *,
            update_phase: bool = True,
            update_spectrum: bool = True,
        ):
            if diagnostics is None or diagnostics.sampleCount <= 0:
                self.status.setText(
                    "Waiting for selected AWR chest beam phase samples"
                )
                return

            time_values = np.asarray(diagnostics.timeSec, dtype=float)
            if time_values.size:
                time_values = time_values - time_values[-1]
            continuity_ids = getattr(diagnostics, "phaseContinuityIds", None)
            segments = np.asarray(
                diagnostics.phaseSegmentIds
                if continuity_ids is None
                else continuity_ids,
                dtype=float,
            )
            raw_phase = np.asarray(diagnostics.rawPhase, dtype=float)
            locked_trace = np.asarray(
                diagnostics.displacementMm
                if self.phase_chart_mode == "displacement"
                else diagnostics.relativePhase,
                dtype=float,
            )
            breathing = np.asarray(diagnostics.breathingFiltered, dtype=float)
            heart = np.asarray(diagnostics.heartFiltered, dtype=float)
            (
                time_values,
                segments,
                raw_phase,
                locked_trace,
                breathing,
                heart,
            ) = rolling_visible_series(
                time_values,
                segments,
                raw_phase,
                locked_trace,
                breathing,
                heart,
                visible_window_sec=self.visible_window_sec,
                max_points=self.max_visible_points,
            )
            self.rendered_point_count = int(time_values.size)

            def segmented(values):
                data = np.asarray(values, dtype=float).copy()
                if data.size == segments.size and data.size > 1:
                    breaks = np.flatnonzero(segments[1:] != segments[:-1]) + 1
                    data[breaks] = np.nan
                return data

            def smooth_detrend(values):
                data = np.asarray(values, dtype=float).copy()
                if self.phase_chart_mode == "phase":
                    return segmented(data)
                fs = max(0.1, float(diagnostics.effectiveSampleRateHz))
                for segment in np.unique(segments[np.isfinite(segments)]):
                    mask = (segments == segment) & np.isfinite(data)
                    indices = np.flatnonzero(mask)
                    if indices.size == 0:
                        continue
                    values_segment = data[indices]
                    smooth_count = max(
                        1, int(round(self.phase_smooth_sec * fs))
                    )
                    if smooth_count > 1 and values_segment.size >= smooth_count:
                        kernel = np.ones(smooth_count) / smooth_count
                        values_segment = np.convolve(
                            values_segment, kernel, mode="same"
                        )
                    detrend_count = max(
                        1, int(round(self.phase_detrend_sec * fs))
                    )
                    if (
                        detrend_count > 1
                        and values_segment.size >= detrend_count
                    ):
                        kernel = np.ones(detrend_count) / detrend_count
                        baseline = np.convolve(
                            values_segment, kernel, mode="same"
                        )
                        values_segment = values_segment - baseline
                    data[indices] = values_segment
                return segmented(data)

            def component_for_display(values, *, heart_component=False):
                data = segmented(values)
                finite = np.isfinite(data)
                if not np.any(finite):
                    return data
                if self.component_normalize:
                    scale = float(np.nanmax(np.abs(data[finite])))
                    if scale > 1e-12:
                        data[finite] /= scale
                elif heart_component and self.component_heart_scale != "auto":
                    data[finite] *= float(self.component_heart_scale)
                return data

            if update_phase:
                self.raw_curve.setData(time_values, segmented(raw_phase))
                self.unwrap_curve.setData(
                    time_values, smooth_detrend(locked_trace)
                )
                self.breath_curve.setData(
                    time_values, component_for_display(breathing)
                )
                self.heart_curve.setData(
                    time_values,
                    component_for_display(heart, heart_component=True),
                )
                for plot in (
                    self.raw_plot,
                    self.unwrap_plot,
                    self.component_plot,
                ):
                    plot.setXRange(
                        -self.visible_window_sec,
                        0.0,
                        padding=0.0,
                    )

            mode = getattr(fused, "selectionMode", "UNKNOWN")
            switch_note = (
                " | Beam switched - new phase segment"
                if diagnostics.beamSwitchedRecently
                else ""
            )
            signal_source = getattr(
                diagnostics, "phaseSignalSource", "single_locked_beam"
            )
            combine_note = (
                f"{signal_source}; n={diagnostics.combinedBeamCount}; "
                f"mode={diagnostics.beamCombineMode}; "
                f"confidence={diagnostics.beamCombineConfidence:.2f}"
            )
            self.status.setText(
                "Locked chest-beam phase waveform quality | "
                f"mode={mode} | bin={diagnostics.selectedRangeBin} | "
                f"az={_format_value(diagnostics.selectedAzimuthDeg, 1)} deg | "
                f"mag={_format_value(diagnostics.selectedMagnitude, 1)} | "
                f"beam={getattr(fused, 'beamState', '--')} | "
                f"phaseValid={diagnostics.phaseValid} | "
                f"locked={diagnostics.validLockedDurationSec:.1f}s | "
                f"segment={diagnostics.phaseSegmentId} | "
                f"signal={combine_note} | "
                f"status={diagnostics.quality}{switch_note}"
            )

    return AwrRangeWidget, VitalPanel, FusionStatusSummary, PhaseDiagnosticsPanel


class FusionUiController:
    def __init__(
        self,
        args: argparse.Namespace,
        awr_widget,
        vital_panel,
        diagnostics_panel,
        status_summary,
        iwr_status,
        timer_class,
        start_awr: bool = True,
        iwr_core=None,
    ):
        self.args = args
        self.awr_widget = awr_widget
        self.vital_panel = vital_panel
        self.diagnostics_panel = diagnostics_panel
        self.status_summary = status_summary
        self.iwr_status = iwr_status
        self.iwr_core = iwr_core
        self.awr_queue: queue.Queue = queue.Queue(maxsize=24)
        self.stop_event = threading.Event()
        self.latest_awr = None
        self.latest_awr_time = 0.0
        self.fe03_tracker = Fe03LivenessTracker(
            args.fe03_stale_timeout_sec
        )
        self.last_state = None
        self.last_target_id = None
        self.primary = PrimaryTargetTracker(args.primary_target_id)
        self.engine = FusionEngine(
            FusionConfig(
                transform=TransformConfig(
                    dx=args.dx if args.sensor_dx is None else args.sensor_dx,
                    dy=args.dy if args.sensor_dy is None else args.sensor_dy,
                    dz=args.dz if args.sensor_dz is None else args.sensor_dz,
                    yawOffsetDeg=args.yaw_offset_deg,
                    yawDeg=args.sensor_yaw_deg,
                    pitchDeg=args.sensor_pitch_deg,
                    rollDeg=args.sensor_roll_deg,
                    useIwrRangeDirect=args.use_iwr_range_direct,
                    awrChestHeightMode=args.awr_chest_height_mode,
                ),
                selector=SelectorConfig(searchHalfWidth=args.search_half_width),
                gate=SittingGateConfig(
                    requiredStableFrames=args.sitting_stable_frames,
                    nonSittingGraceSec=args.non_sitting_grace_sec,
                    sittingLockSec=args.sitting_lock_sec,
                    updateRateHz=args.fs,
                    maxGraceSpeedMps=args.max_grace_speed_mps,
                    allowStandingGrace=args.allow_standing_grace,
                    enablePoseGrace=args.pose_grace_enabled,
                    pauseImmediatelyOnFalling=args.hard_pause_on_falling,
                    pauseImmediatelyOnLying=args.hard_pause_on_lying,
                ),
                estimator=VitalEstimatorConfig(
                    fs=args.fs,
                    displayHoldSec=args.vital_display_hold_sec,
                    minEstimationWindowSec=args.min_estimation_window_sec,
                    minVitalWindowSec=args.min_vital_window_sec,
                    minHeartWindowSec=args.min_heart_window_sec,
                    breathStableWindowSec=args.breath_stable_window_sec,
                    heartStableWindowSec=args.heart_stable_window_sec,
                    bpmSmoothingSec=args.bpm_smoothing_sec,
                    breathMaxJumpBpmPerSec=(
                        args.breath_max_jump_bpm_per_sec
                    ),
                    heartMaxJumpBpmPerSec=args.heart_max_jump_bpm_per_sec,
                    heartTopKPeaks=args.heart_top_k_peaks,
                    heartPeakPersistenceSec=args.heart_peak_persistence_sec,
                    heartSwitchConfirmSec=args.heart_switch_confirm_sec,
                    heartSwitchMargin=args.heart_switch_margin,
                    heartMinSnr=args.heart_min_snr,
                    heartMinConfidence=args.heart_min_confidence,
                    heartWindowSec=args.heart_window_sec,
                    heartPreliminaryWindowSec=(
                        args.heart_preliminary_window_sec
                    ),
                    breathWindowSec=args.breath_window_sec,
                    phasePlotWindowSec=args.phase_plot_window_sec,
                    phaseSign=args.phase_sign,
                    phaseUnwrapDiscontinuityRad=(
                        args.phase_unwrap_discontinuity_rad
                    ),
                    phaseGapResetSec=args.phase_gap_reset_sec,
                    phaseResetOnBeamSwitch=args.phase_reset_on_beam_switch,
                    carrierFrequencyGhz=args.carrier_frequency_ghz,
                    analysisUpdateHz=args.spectrum_update_hz,
                    enableVitalMl=args.enable_vital_ml,
                    vitalModelDir=args.vital_model_dir,
                    mlMinWindowSec=args.ml_min_window_sec,
                ),
                chest=ChestEstimatorConfig(
                    sittingChestHeightM=args.chest_sitting_height,
                    standingChestHeightM=args.chest_standing_height,
                ),
                useChestTargeting=args.use_chest_targeting,
                beamforming=BeamformingConfig(
                    angleMinDeg=args.angle_min_deg,
                    angleMaxDeg=args.angle_max_deg,
                    angleStepDeg=args.angle_step_deg,
                    antennaSpacingLambda=args.antenna_spacing_lambda,
                    windowType=args.beam_window_type,
                    hysteresisStrengthRatio=args.beam_hysteresis_ratio,
                    scoreMode=args.beam_score_mode,
                ),
                azimuthSearchHalfWidthDeg=args.azimuth_search_half_width_deg,
                beamLock=BeamLockConfig(
                    lockSec=args.beam_lock_sec,
                    holdSec=(
                        args.beam_switch_hold_sec
                        if args.beam_switch_hold_sec is not None
                        else args.beam_hold_sec
                    ),
                    switchMargin=args.beam_switch_margin,
                    switchConfirmSec=args.beam_switch_confirm_sec,
                    maxJumpBins=args.beam_max_jump_bins,
                    maxJumpDeg=args.beam_max_jump_deg,
                    enabled=not args.disable_beam_lock,
                ),
                nearbyBeamCombiner=NearbyBeamCombinerConfig(
                    enabled=args.enable_nearby_beam_combining,
                    rangeRadiusBins=args.nearby_beam_range_radius_bins,
                    azimuthRadiusDeg=args.nearby_beam_azimuth_radius_deg,
                    mode=args.beam_combine_mode,
                ),
                carrierFrequencyGhz=args.carrier_frequency_ghz,
            )
        )
        self.logger = DualSensorCsvLogger(
            args.out,
            {
                **vars(args),
                "mode": "ui",
                "fusionConfig": asdict(self.engine.config),
            },
            flush_interval_sec=args.csv_flush_interval_sec,
            flush_rows=args.csv_flush_rows,
        )
        self.csv_worker = AsyncMethodWorker(
            self.logger,
            flush_interval_sec=args.csv_flush_interval_sec,
            flush_rows=args.csv_flush_rows,
        )
        self._heatmap_limiter = RateLimiter(args.heatmap_update_hz)
        self._phase_limiter = RateLimiter(args.phase_plot_update_hz)
        self._spectrum_limiter = RateLimiter(args.spectrum_update_hz)
        self._iwr_rate = RollingRate()
        self._fe03_rate = RollingRate()
        self._ui_rate = RollingRate()
        self._dropped_ui_frames = 0
        self._last_processing_ms = 0.0
        self._last_ui_latency_ms = 0.0
        self._last_fused = None
        self._last_selection = None
        self._last_fe03 = self.fe03_tracker.status(time.time())
        self._last_diagnostics = None
        self._last_target = None
        self.thread = None
        if start_awr:
            self.status_summary.update_status(awr="Connecting")
            self.thread = threading.Thread(
                target=_awr_worker,
                args=(args, self.awr_queue, self.stop_event),
                name="awr-ui-reader",
                daemon=True,
            )
            self.thread.start()
        self.timer = timer_class()
        self.timer.timeout.connect(self.render_tick)
        self.timer.start(max(1, int(round(1000.0 / args.ui_update_hz))))

    def _log(self, method_name: str, *args, row_weight: int = 1) -> None:
        self.csv_worker.submit(method_name, *args, row_weight=row_weight)

    def inject_awr_window(self, window) -> None:
        _put_latest(
            self.awr_queue,
            ("bin_window", time.time(), window),
        )

    def inject_awr_virtual_ant_window(self, window) -> None:
        _put_latest(
            self.awr_queue,
            ("virtual_ant_window", time.time(), window),
        )

    def drain_awr(self):
        latest, _consumed, dropped = drain_latest_by_kind(self.awr_queue)
        self._dropped_ui_frames += dropped
        for kind, item in latest.items():
            _kind, timestamp, payload = item
            if kind == "error":
                self._log("log_ui_event", "AWR_ERROR", None, str(payload))
                self.vital_panel.set_no_target("NO_AWR_WINDOW", str(payload))
                self.status_summary.update_status(awr="Error")
                if self.args.debug:
                    print(f"[fusion-ui] AWR error: {payload}", flush=True)
                continue
            if kind == "virtual_ant_window":
                self.fe03_tracker.update(payload, timestamp)
                self._fe03_rate.mark()
                self._log("log_awr_virtual_ant_window", payload, row_weight=8)
            else:
                self.latest_awr = payload
                self.latest_awr_time = timestamp
                self._log("log_awr_window", payload, row_weight=4)
            self._last_fe03 = self.fe03_tracker.status(timestamp)
            self.status_summary.update_status(awr_frame=payload.frameNumber)

    def handle_iwr_frame(
        self,
        output_dict: dict[str, Any],
        pose_results: dict[int, dict[str, Any]],
    ) -> None:
        processing_started = time.perf_counter()
        timestamp = time.time()
        self._iwr_rate.mark()
        targets = extract_iwr_targets(output_dict, pose_results, timestamp)
        self.status_summary.update_status(
            iwr="Demo" if self.args.demo_mode else "Live",
            iwr_frame=output_dict.get("frameNum", "--"),
        )
        self._log(
            "log_iwr_targets",
            targets,
            row_weight=max(1, len(targets)),
        )
        target = self.primary.select(targets)
        if target is None:
            state = "TARGET_LOST" if self.last_target_id is not None else "NO_TARGET"
            status = make_status_fused(
                state,
                timestamp=timestamp,
                target_id=self.last_target_id,
                reason="no primary IWR target in current frame",
            )
            self._log("log_fused", status, None)
            self._last_fused = status
            self._last_selection = None
            self._last_target = None
            self.iwr_status.setText("No tracked IWR target")
            self._update_chest_marker(None)
            self._state_event(state, self.last_target_id, "no primary IWR target")
            self._last_processing_ms = (
                time.perf_counter() - processing_started
            ) * 1000.0
            return

        self.last_target_id = target.targetId
        self._last_target = target
        confidence = (
            f" {target.postureConfidence * 100.0:.0f}%"
            if target.postureConfidence is not None
            else ""
        )
        self.iwr_status.setText(
            f"ID {target.targetId} | {target.posture}{confidence} | Chest ROI"
        )
        awr_window = self.latest_awr
        if awr_window and timestamp - self.latest_awr_time > self.args.max_awr_age:
            awr_window = None
        fe03 = self.fe03_tracker.status(timestamp)
        fused, selection = self.engine.process(
            target,
            awr_window,
            timestamp,
            awr_virtual_ant_window=fe03.window,
            fe03_age_sec=fe03.ageSec,
            latest_fe03_frame_number=fe03.frameNumber,
            fe03_frames_per_second=fe03.framesPerSecond,
            fe03_stream_state=fe03.streamState,
            fe03_frame_count=fe03.frameCount,
            latest_fe03_payload_ok=fe03.payloadOk,
            latest_fe03_parse_error=fe03.parseError,
        )
        if (
            self.args.demo_mode
            and fused.monitoringState in ACTIVE_MONITORING_STATES
            and fused.breathingBpm is None
        ):
            # Demo mode must communicate the final dashboard layout immediately;
            # the real estimator still receives the synthetic phase stream.
            fused.breathingBpm = 15.0
            fused.heartBpm = 72.0
            fused.quality = "DEMO"
        self._log("log_fused", fused, selection)
        if self.engine.latest_beam_selection is not None:
            self._log(
                "log_beam_selection",
                fused,
                self.engine.latest_beam_selection,
            )
        self._last_fused = fused
        self._last_selection = selection
        self._update_chest_marker(fused)
        self._state_event(
            fused.monitoringState,
            fused.targetId,
            fused.selectionReason,
        )
        self._last_processing_ms = (
            time.perf_counter() - processing_started
        ) * 1000.0

    def render_tick(self) -> None:
        """Render the newest state at a fixed rate; stale UI frames are skipped."""
        render_started = time.perf_counter()
        timestamp = time.time()
        self.drain_awr()
        self._ui_rate.mark()

        fe03 = self.fe03_tracker.status(timestamp)
        self._last_fe03 = fe03
        fused = self._last_fused
        selection = self._last_selection

        if fused is None:
            self.vital_panel.set_no_target("NO_TARGET")
        elif fused.targetId is None:
            self.vital_panel.set_no_target(fused.monitoringState)
        else:
            self.vital_panel.set_fused(fused, selection)

        if self._heatmap_limiter.due():
            state = (
                fused.monitoringState
                if fused is not None
                else "NO_TARGET"
            )
            self.awr_widget.set_state(
                self.latest_awr,
                selection,
                bool(
                    fused is not None
                    and state in ACTIVE_MONITORING_STATES
                ),
                state,
                fe03.window,
                self.engine.latest_candidate_beam_selection,
                self.engine.latest_locked_beam_selection,
            )
            if fused is not None and fused.targetId is not None:
                self.awr_widget.set_spatial_status(fused)

        phase_due = self._phase_limiter.due()
        spectrum_due = self._spectrum_limiter.due()
        if (
            (phase_due or spectrum_due)
            and fused is not None
            and fused.targetId is not None
        ):
            diagnostics = self.engine.phase_diagnostics(
                fused.targetId, timestamp
            )
            self._last_diagnostics = diagnostics
            self.diagnostics_panel.set_diagnostics(
                diagnostics,
                fused,
                update_phase=phase_due,
                update_spectrum=spectrum_due,
            )
            if spectrum_due:
                self._log("log_phase_diagnostics", fused, diagnostics)

        diagnostics = self._last_diagnostics
        phase_seconds = (
            f"{diagnostics.bufferLengthSec:.1f} s"
            if diagnostics is not None
            else "0.0 s"
        )
        plot_points = getattr(
            self.diagnostics_panel, "rendered_point_count", 0
        )
        awr_state = fe03.streamState
        if fe03.window is None and self.latest_awr is not None:
            awr_state = "FE02_FALLBACK"
        self.status_summary.update_status(
            awr=awr_state,
            awr_frame=(
                fe03.frameNumber
                if fe03.frameNumber is not None
                else getattr(self.latest_awr, "frameNumber", "--")
            ),
            updated=time.strftime("%H:%M:%S"),
            target=(
                fused.targetId
                if fused is not None and fused.targetId is not None
                else "--"
            ),
            selected_bin=(
                fused.selectedAwrBin
                if fused is not None and fused.selectedAwrBin is not None
                else "--"
            ),
            iwr_fps=f"{self._iwr_rate.value():.1f}",
            fe03_fps=f"{max(fe03.framesPerSecond, self._fe03_rate.value()):.1f}",
            ui_fps=f"{self._ui_rate.value():.1f}",
            ui_latency=f"{self._last_ui_latency_ms:.1f} ms",
            processing_latency=f"{self._last_processing_ms:.1f} ms",
            plot_points=plot_points,
            phase_seconds=phase_seconds,
            dropped_frames=(
                self._dropped_ui_frames + self.csv_worker.dropped
            ),
            csv_backlog=self.csv_worker.backlog,
            csv_flush_age=f"{self.csv_worker.last_flush_age_sec:.1f} s",
        )
        self._last_ui_latency_ms = (
            time.perf_counter() - render_started
        ) * 1000.0

    def _update_chest_marker(self, fused) -> None:
        if self.iwr_core is None:
            return
        demo = None
        demo_classes = getattr(self.iwr_core, "demoClassDict", None)
        demo_name = getattr(self.iwr_core, "demo", None)
        if isinstance(demo_classes, dict):
            demo = demo_classes.get(demo_name)
        marker_owner = (
            demo if demo is not None and hasattr(demo, "updateChestRoi") else self.iwr_core
        )
        if not hasattr(marker_owner, "updateChestRoi"):
            return
        if fused is None or fused.chestIwrX is None:
            marker_owner.updateChestRoi([])
            return
        marker_owner.updateChestRoi(
            [
                {
                    "tid": fused.targetId,
                    "x": fused.chestIwrX,
                    "y": fused.chestIwrY,
                    "z": fused.chestIwrZ,
                    "confidence": fused.chestConfidence,
                }
            ]
        )

    def _state_event(
        self, state: str, target_id: int | None, details: str
    ) -> None:
        key = (target_id, state)
        if key == self.last_state:
            return
        self.last_state = key
        self._log(
            "log_ui_event",
            "MONITORING_STATE_CHANGE",
            target_id,
            f"{state}: {details}",
        )

    def close(self):
        self.stop_event.set()
        self.timer.stop()
        if self.thread is not None:
            self.thread.join(timeout=1.5)
        self.csv_worker.close()


def _reflow_ti_window(
    window,
    awr_widget,
    vital_panel,
    diagnostics_panel,
    status_summary,
    args: argparse.Namespace,
):
    """Move existing TI widgets into a scrollable sidebar and split main view."""
    from PySide2.QtCore import Qt
    from PySide2.QtWidgets import (
        QAbstractItemView,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QTableWidget,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    source_layout = window.gridLayout
    sidebar_entries = []
    for index in range(source_layout.count()):
        item = source_layout.itemAt(index)
        widget = item.widget()
        if widget is None or widget in {window.demoTabs, window.replayBox}:
            continue
        row, column, _row_span, _column_span = source_layout.getItemPosition(index)
        if column == 0:
            sidebar_entries.append((row, widget))
    sidebar_entries.sort(key=lambda entry: entry[0])

    for _row, widget in sidebar_entries:
        source_layout.removeWidget(widget)
    source_layout.removeWidget(window.demoTabs)
    source_layout.removeWidget(window.replayBox)

    sidebar_content = QWidget()
    sidebar_content.setMinimumWidth(280)
    sidebar_layout = QVBoxLayout(sidebar_content)
    sidebar_layout.setContentsMargins(8, 8, 8, 8)
    sidebar_layout.setSpacing(8)
    for _row, widget in sidebar_entries:
        widget.setMinimumWidth(260)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        for label in widget.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumHeight(label.sizeHint().height())
        for button in widget.findChildren(QPushButton):
            button.setMinimumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for line_edit in widget.findChildren(QLineEdit):
            line_edit.setMinimumHeight(26)
        for table in widget.findChildren(QTableWidget):
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setMinimumHeight(120)
        sidebar_layout.addWidget(widget)
    sidebar_layout.addWidget(window.replayBox)
    sidebar_layout.addStretch(1)

    sidebar_scroll = QScrollArea()
    sidebar_scroll.setObjectName("fusionSidebar")
    sidebar_scroll.setWidgetResizable(True)
    sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sidebar_scroll.setWidget(sidebar_content)
    sidebar_scroll.setMinimumWidth(300)
    sidebar_scroll.setMaximumWidth(380)
    sidebar_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    iwr_panel = QGroupBox("IWR6843 3D Tracking / Pose View")
    iwr_layout = QVBoxLayout(iwr_panel)
    iwr_layout.setContentsMargins(6, 8, 6, 6)
    iwr_layout.setSpacing(4)
    iwr_status = QLabel("Waiting for IWR target")
    iwr_status.setObjectName("iwrCompactStatus")
    iwr_status.setAlignment(Qt.AlignCenter)
    iwr_status.setMinimumHeight(28)
    iwr_status.setStyleSheet(
        "background:#303843; color:#dce6ef; border-radius:4px;"
        " padding:4px; font-weight:600;"
    )
    iwr_layout.addWidget(iwr_status)
    window.demoTabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    iwr_layout.addWidget(window.demoTabs, 1)

    top_splitter = QSplitter(Qt.Horizontal)
    top_splitter.setObjectName("fusionTopSplitter")
    top_splitter.setChildrenCollapsible(False)
    top_splitter.addWidget(iwr_panel)
    top_splitter.addWidget(awr_widget)
    top_splitter.setStretchFactor(0, 7)
    top_splitter.setStretchFactor(1, 3)
    top_width = max(
        650, args.window_width - 320 - max(320, args.right_panel_width)
    )
    top_splitter.setSizes([int(top_width * 0.68), int(top_width * 0.32)])

    right_content = QWidget()
    right_content.setObjectName("fusionRightStatusContent")
    right_layout = QVBoxLayout(right_content)
    right_layout.setContentsMargins(6, 6, 6, 6)
    right_layout.setSpacing(8)
    status_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    vital_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    right_layout.addWidget(status_summary)
    right_layout.addWidget(vital_panel)
    right_layout.addStretch(1)

    right_scroll = QScrollArea()
    right_scroll.setObjectName("fusionRightStatusScroll")
    right_scroll.setWidgetResizable(True)
    right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    right_scroll.setWidget(right_content)
    right_scroll.setMinimumWidth(320)
    right_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    if args.diagnostics_tabbed:
        central_widget = top_splitter
        content_splitter = None
    else:
        content_splitter = QSplitter(Qt.Vertical)
        content_splitter.setObjectName("fusionContentSplitter")
        content_splitter.setChildrenCollapsible(False)
        content_splitter.addWidget(top_splitter)
        content_splitter.addWidget(diagnostics_panel)
        content_splitter.setStretchFactor(0, 7)
        content_splitter.setStretchFactor(1, 3)
        content_splitter.setSizes(
            [
                max(500, int(args.window_height * 0.65)),
                max(260, int(args.window_height * 0.30)),
            ]
        )
        central_widget = content_splitter

    main_splitter = QSplitter(Qt.Horizontal)
    main_splitter.setObjectName("fusionMainSplitter")
    main_splitter.setChildrenCollapsible(False)
    main_splitter.addWidget(sidebar_scroll)
    main_splitter.addWidget(central_widget)
    main_splitter.addWidget(right_scroll)
    main_splitter.setStretchFactor(0, 0)
    main_splitter.setStretchFactor(1, 1)
    main_splitter.setStretchFactor(2, 0)
    sidebar_width = 320
    right_width = max(320, int(args.right_panel_width))
    center_width = max(
        650, args.window_width - sidebar_width - right_width - 32
    )
    main_splitter.setSizes([sidebar_width, center_width, right_width])

    overview = QWidget()
    overview_layout = QHBoxLayout(overview)
    overview_layout.setContentsMargins(0, 0, 0, 0)
    overview_layout.addWidget(main_splitter)

    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    tabs.addTab(overview, "Full Fusion View")
    if args.diagnostics_tabbed:
        tabs.addTab(diagnostics_panel, "Locked Chest Phase Diagnostics")

    root = QWidget()
    root.setObjectName("fusionRoot")
    root_layout = QHBoxLayout(root)
    root_layout.setContentsMargins(8, 8, 8, 8)
    root_layout.addWidget(tabs)

    old_central = window.central
    window.setCentralWidget(root)
    window.central = root
    old_central.deleteLater()
    window.setMinimumSize(1200, 750)
    window.showNormal()
    screen = window.screen()
    available = screen.availableGeometry() if screen is not None else None
    target_width = int(args.window_width)
    target_height = int(args.window_height)
    if available is not None:
        # Leave room for the native frame and taskbar. Requesting the exact
        # available geometry can overflow by the Windows title-bar margins on
        # high-DPI displays and cause Qt to repeatedly renegotiate the layout.
        usable_width = max(1200, available.width() - 24)
        usable_height = max(750, available.height() - 48)
        target_width = min(target_width, usable_width)
        target_height = min(target_height, usable_height)
    window.resize(target_width, target_height)

    panels = {
        "sidebar": sidebar_scroll,
        "iwr": iwr_panel,
        "awr": awr_widget,
        "vitals": vital_panel,
        "right_status": right_scroll,
        "top_splitter": top_splitter,
        "content_splitter": content_splitter,
        "main_splitter": main_splitter,
        "tabs": tabs,
        "iwr_status": iwr_status,
    }
    if args.layout_debug:
        for panel in (
            sidebar_scroll,
            iwr_panel,
            awr_widget,
            vital_panel,
            right_scroll,
        ):
            panel.setStyleSheet(
                panel.styleSheet()
                + " border:1px dashed #ff4fd8;"
            )
    window._fusion_layout_panels = panels
    return panels


def _install_layout_debug(args, timer_class, panels, window):
    if not args.layout_debug:
        return None
    timer = timer_class(window)

    def report_sizes():
        parts = []
        for name in ("sidebar", "iwr", "awr", "vitals"):
            widget = panels[name]
            parts.append(f"{name}={widget.width()}x{widget.height()}")
        print("[layout-debug] " + " ".join(parts), flush=True)

    timer.timeout.connect(report_sizes)
    timer.start(3000)
    return timer


def _make_demo_awr_window(frame_number: int, elapsed: float) -> AwrBinWindow:
    resolution = 1.7541 / 37.0
    breath_phase = 0.85 * math.sin(2.0 * math.pi * 0.25 * elapsed)
    heart_phase = 0.16 * math.sin(2.0 * math.pi * 1.2 * elapsed)
    phase = breath_phase + heart_phase
    samples = []
    for bin_index in range(20, 61):
        distance = bin_index - 37
        magnitude = 480.0 + 2050.0 * math.exp(-(distance * distance) / 5.0)
        sample_phase = phase if bin_index == 37 else phase * 0.15 + distance * 0.04
        samples.append(
            AwrBinSample(
                timestamp=time.time(),
                frameNumber=frame_number,
                binIndex=bin_index,
                rangeMeters=bin_index * resolution,
                iValue=magnitude * math.cos(sample_phase),
                qValue=magnitude * math.sin(sample_phase),
                phaseRad=sample_phase,
                magnitude=magnitude,
            )
        )
    strongest = max(samples, key=lambda sample: sample.magnitude)
    return AwrBinWindow(
        timestamp=time.time(),
        frameNumber=frame_number,
        startBin=20,
        numBins=len(samples),
        bins=samples,
        strongestBin=strongest.binIndex,
        strongestRangeMeters=strongest.rangeMeters,
        strongestMagnitude=strongest.magnitude,
    )


def _make_demo_awr_virtual_ant_window(frame_number: int, elapsed: float):
    import numpy as np

    from awr1642_vitals.phase_vitals.tlv_parser.fake_ti_uart_packet import (
        make_fake_vital_phase_virtual_ant_window,
    )

    parsed = make_fake_vital_phase_virtual_ant_window(
        frame_number=frame_number,
        source_bin=37,
        source_azimuth_deg=2.0,
    )
    vital_phase = (
        0.85 * math.sin(2.0 * math.pi * 0.25 * elapsed)
        + 0.16 * math.sin(2.0 * math.pi * 1.2 * elapsed)
    )
    parsed = replace(
        parsed,
        samples=(
            np.asarray(parsed.samples, dtype=np.complex64)
            * np.exp(1j * vital_phase)
        ).astype(np.complex64),
    )
    return convert_awr_virtual_ant_window(parsed, time.time())


class DemoPoseManager:
    """Pose-manager-compatible source for exercising labels and meshes offline."""

    def __init__(self, ti_args: argparse.Namespace):
        self.enable_3d_labels = bool(ti_args.pose_3d_labels)
        self.enable_human_models = bool(ti_args.pose_human_models)
        self.debug = bool(ti_args.pose_debug)
        self.ground_z = float(ti_args.pose_ground_z)
        self.target_height = float(ti_args.pose_human_model_target_height)
        self.sitting_height = float(
            ti_args.pose_human_model_target_sitting_height
        )
        self.lying_length = float(ti_args.pose_human_model_target_lying_length)
        self.latest_results: dict[int, dict[str, Any]] = {}

    def process_output_dict(self, output_dict: dict) -> dict[int, dict[str, Any]]:
        self.latest_results = {
            int(tid): dict(result)
            for tid, result in output_dict.get("_fusionDemoPose", {}).items()
        }
        return self.latest_results

    @staticmethod
    def _track_positions(track_data) -> dict[int, tuple[float, float, float]]:
        positions: dict[int, tuple[float, float, float]] = {}
        if track_data is None:
            return positions
        for row in track_data:
            if len(row) >= 4:
                positions[int(row[0])] = (
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                )
        return positions

    def get_3d_label_records(self, track_data=None, height_data=None) -> list[dict]:
        if not self.enable_3d_labels:
            return []
        positions = self._track_positions(track_data)
        records = []
        for tid, pose in sorted(self.latest_results.items()):
            x, y, z = positions.get(
                tid,
                (
                    float(pose.get("x", 0.0)),
                    float(pose.get("y", 0.0)),
                    float(pose.get("z", 0.0)),
                ),
            )
            label = str(pose.get("displayed_label", "UNKNOWN")).upper()
            if label == "SITTING":
                label_z = self.ground_z + self.sitting_height + 0.15
            elif label in {"LYING", "FALLING"}:
                label_z = self.ground_z + 0.65
            else:
                label_z = self.ground_z + self.target_height + 0.15
            confidence = float(pose.get("displayed_confidence", 0.0))
            records.append(
                {
                    "tid": tid,
                    "text": f"ID {tid} | {label} {confidence:.0%}",
                    "x": x,
                    "y": y,
                    "z": label_z,
                    "final_label": label,
                    "confidence": confidence,
                    "quality": "OK",
                    "window_ready": True,
                }
            )
        return records

    def get_3d_model_records(self, track_data=None, height_data=None) -> list[dict]:
        if not self.enable_human_models:
            return []
        positions = self._track_positions(track_data)
        records = []
        for tid, pose in sorted(self.latest_results.items()):
            x, y, z = positions.get(
                tid,
                (
                    float(pose.get("x", 0.0)),
                    float(pose.get("y", 0.0)),
                    float(pose.get("z", 0.0)),
                ),
            )
            label = str(pose.get("displayed_label", "UNKNOWN")).upper()
            confidence = float(pose.get("displayed_confidence", 0.0))
            records.append(
                {
                    "tid": tid,
                    "x": x,
                    "y": y,
                    "z": z,
                    "bottom_z": self.ground_z,
                    "ground_z": self.ground_z,
                    "height": self.target_height,
                    "target_height": self.target_height,
                    "final_label": label,
                    "displayed_label": label,
                    "candidate_label": label,
                    "confidence": confidence,
                    "displayed_confidence": confidence,
                    "final_confidence": confidence,
                    "quality": "OK",
                    "window_ready": True,
                    "model_asset_used": (
                        "human_sitting.obj"
                        if label == "SITTING"
                        else "human_lying.obj"
                        if label in {"LYING", "FALLING"}
                        else "human_standing.obj"
                    ),
                    "model_scale": (
                        self.sitting_height
                        if label == "SITTING"
                        else self.lying_length
                        if label in {"LYING", "FALLING"}
                        else self.target_height
                    ),
                }
            )
        return records

    def close(self) -> None:
        self.latest_results.clear()


def _demo_posture(elapsed: float) -> str:
    poses = ("STANDING", "MOVING", "SITTING", "LYING", "FALLING")
    return poses[int(elapsed // 4.0) % len(poses)]


def _make_demo_iwr_output(frame_number: int, elapsed: float):
    import numpy as np

    posture = _demo_posture(elapsed)
    x = 0.18 * math.sin(elapsed * 0.8) if posture == "MOVING" else 0.03
    z = (
        0.90
        if posture in {"STANDING", "MOVING"}
        else 0.55
        if posture == "SITTING"
        else 0.20
    )
    y = math.sqrt(1.75 * 1.75 - z * z)
    velocity_x = 0.14 * math.cos(elapsed * 0.8) if posture == "MOVING" else 0.0
    track = np.array([[1, x, y, z, velocity_x, 0.0, 0.0]], dtype=float)
    points = []
    for index in range(32):
        angle = 2.0 * math.pi * index / 32.0
        points.append(
            [
                x + 0.22 * math.cos(angle),
                y + 0.10 * math.sin(angle),
                0.25 + 1.0 * (index % 8) / 8.0,
                0.0,
                18.0 + index % 7,
                5.0,
                1.0,
            ]
        )
    output = {
        "frameNum": frame_number,
        "numDetectedPoints": len(points),
        "numDetectedTracks": 1,
        "pointCloud": np.asarray(points, dtype=float),
        "trackData": track,
        "_fusionDemoPose": {
            1: {
                "displayed_label": posture,
                "final_label": posture,
                "candidate_label": posture,
                "displayed_confidence": 0.94,
                "display_status": "STABLE",
                "window_ready": True,
                "prediction_exists": True,
                "quality": "OK",
                "x": x,
                "y": y,
                "z": z,
            }
        },
    }
    return output


def _start_demo(timer_class, window, controller):
    started = time.monotonic()
    state = {"frame": 0}
    timer = timer_class(window)

    def tick():
        state["frame"] += 1
        elapsed = time.monotonic() - started
        controller.inject_awr_window(
            _make_demo_awr_window(state["frame"], elapsed)
        )
        controller.inject_awr_virtual_ant_window(
            _make_demo_awr_virtual_ant_window(state["frame"], elapsed)
        )
        window.core.updateGraph(
            _make_demo_iwr_output(state["frame"], elapsed)
        )

    timer.timeout.connect(tick)
    timer.start(100)
    window._fusion_demo_timer = timer
    return timer


def run(args: argparse.Namespace) -> int:
    if args.fs <= 0:
        raise ValueError("--fs must be positive")
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration must be positive")
    if args.window_width < 1200 or args.window_height < 750:
        raise ValueError(
            "--window-width/--window-height must be at least 1200 x 750"
        )
    if args.ui_scale <= 0:
        raise ValueError("--ui-scale must be positive")
    if args.right_panel_width < 300:
        raise ValueError("--right-panel-width must be at least 300")
    if args.plot_max_visible_points < 100:
        raise ValueError("--plot-max-visible-points must be at least 100")
    for option, value in (
        ("--ui-update-hz", args.ui_update_hz),
        ("--heatmap-update-hz", args.heatmap_update_hz),
        ("--phase-plot-update-hz", args.phase_plot_update_hz),
        ("--spectrum-update-hz", args.spectrum_update_hz),
        ("--csv-flush-interval-sec", args.csv_flush_interval_sec),
    ):
        if value <= 0:
            raise ValueError(f"{option} must be positive")
    if args.csv_flush_rows <= 0:
        raise ValueError("--csv-flush-rows must be positive")
    if args.pose_human_model_scale <= 0:
        raise ValueError("--pose-human-model-scale must be positive")
    if args.pose_human_model_target_height <= 0:
        raise ValueError("--pose-human-model-target-height must be positive")
    if args.pose_human_model_sitting_height <= 0:
        raise ValueError("--pose-human-model-sitting-height must be positive")
    if args.pose_human_model_lying_length <= 0:
        raise ValueError("--pose-human-model-lying-length must be positive")
    if not 0.0 < args.pose_human_model_opacity <= 1.0:
        raise ValueError("--pose-human-model-opacity must be in (0, 1]")
    if args.pose_ground_plane_size <= 0:
        raise ValueError("--pose-ground-plane-size must be positive")
    if not 0.0 <= args.pose_ground_plane_alpha <= 1.0:
        raise ValueError("--pose-ground-plane-alpha must be in [0, 1]")
    if args.non_sitting_grace_sec < 0:
        raise ValueError("--non-sitting-grace-sec must be non-negative")
    if args.sitting_lock_sec < 0:
        raise ValueError("--sitting-lock-sec must be non-negative")
    if args.max_grace_speed_mps < 0:
        raise ValueError("--max-grace-speed-mps must be non-negative")
    if args.fe03_stale_timeout_sec < 0:
        raise ValueError("--fe03-stale-timeout-sec must be non-negative")
    for option, value in (
        ("--vital-display-hold-sec", args.vital_display_hold_sec),
        ("--min-estimation-window-sec", args.min_estimation_window_sec),
        ("--min-vital-window-sec", args.min_vital_window_sec),
        ("--min-heart-window-sec", args.min_heart_window_sec),
        ("--heart-stable-window-sec", args.heart_stable_window_sec),
        ("--breath-stable-window-sec", args.breath_stable_window_sec),
        ("--bpm-smoothing-sec", args.bpm_smoothing_sec),
        (
            "--breath-max-jump-bpm-per-sec",
            args.breath_max_jump_bpm_per_sec,
        ),
        ("--heart-max-jump-bpm-per-sec", args.heart_max_jump_bpm_per_sec),
        ("--heart-peak-persistence-sec", args.heart_peak_persistence_sec),
        ("--heart-switch-confirm-sec", args.heart_switch_confirm_sec),
        ("--heart-switch-margin", args.heart_switch_margin),
        ("--heart-min-snr", args.heart_min_snr),
        ("--heart-min-confidence", args.heart_min_confidence),
        ("--heart-window-sec", args.heart_window_sec),
        ("--heart-preliminary-window-sec", args.heart_preliminary_window_sec),
        ("--breath-window-sec", args.breath_window_sec),
        ("--ml-min-window-sec", args.ml_min_window_sec),
        ("--phase-plot-window-sec", args.phase_plot_window_sec),
        ("--phase-visible-window-sec", args.phase_visible_window_sec),
        (
            "--phase-unwrap-discontinuity-rad",
            args.phase_unwrap_discontinuity_rad,
        ),
        ("--phase-gap-reset-sec", args.phase_gap_reset_sec),
        ("--beam-switch-hold-sec", args.beam_switch_hold_sec),
        (
            "--nearby-beam-range-radius-bins",
            args.nearby_beam_range_radius_bins,
        ),
        (
            "--nearby-beam-azimuth-radius-deg",
            args.nearby_beam_azimuth_radius_deg,
        ),
    ):
        if value is None:
            continue
        if value < 0:
            raise ValueError(f"{option} must be non-negative")
    if args.heart_top_k_peaks < 1:
        raise ValueError("--heart-top-k-peaks must be at least 1")
    if args.phase_visible_window_sec <= 0:
        raise ValueError("--phase-visible-window-sec must be positive")
    if args.phase_unwrap_discontinuity_rad <= 0:
        raise ValueError("--phase-unwrap-discontinuity-rad must be positive")
    if args.carrier_frequency_ghz <= 0:
        raise ValueError("--carrier-frequency-ghz must be positive")
    if args.component_chart_heart_scale != "auto":
        try:
            heart_scale = float(args.component_chart_heart_scale)
        except ValueError as exc:
            raise ValueError(
                "--component-chart-heart-scale must be 'auto' or a positive number"
            ) from exc
        if heart_scale <= 0:
            raise ValueError(
                "--component-chart-heart-scale must be 'auto' or a positive number"
            )

    args.iwr_cfg = str(Path(args.iwr_cfg).expanduser().resolve())
    args.awr_cfg = str(Path(args.awr_cfg).expanduser().resolve())
    args.pose_model = str(Path(args.pose_model).expanduser().resolve())
    args.pose_human_model_dir = str(
        Path(args.pose_human_model_dir).expanduser().resolve()
    )
    args.out = str(ti_launcher.resolve_project_path(args.out))
    ti_args = _make_ti_args(args)
    pose_manager = (
        DemoPoseManager(ti_args)
        if args.demo_mode
        else ti_launcher.create_pose_manager_before_qt(ti_args, ti_args.debug)
    )
    ti_launcher.add_import_paths(ti_args.debug)
    using_shim = ti_launcher.check_pyside2_shim(ti_args.debug)
    gl_text_disabled = ti_launcher.configure_gl_text(
        ti_args, using_shim, ti_args.debug
    )
    ti_launcher.ensure_vendor_runtime_dirs()

    original_cwd = Path.cwd()
    os.chdir(ti_launcher.VENDOR_INDUSTRIAL)
    ti_launcher.debug_print(
        ti_args.debug,
        f"cwd changed from {original_cwd} to {ti_launcher.VENDOR_INDUSTRIAL}",
    )
    ti_launcher.configure_business_demo_list()
    ti_launcher.install_debug_hooks(ti_args.debug, gl_text_disabled)

    QApplication, QTimer, QPalette, QColor, Window, demo_name = (
        ti_launcher.import_ti_qt()
    )
    from PySide2.QtCore import Qt

    if not using_shim:
        try:
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except (AttributeError, TypeError):
            pass
    app = QApplication(sys.argv[:1])
    ti_launcher.apply_ti_dark_palette(app, QPalette, QColor)
    if args.ui_scale != 1.0:
        font = app.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() * args.ui_scale))
        app.setFont(font)
    screen = app.primaryScreen()
    size = screen.size() if screen is not None else []
    window = Window(
        size=size,
        title="Dual-Sensor Fusion - IWR6843 Tracking + AWR1642 Vitals",
    )
    ti_launcher.configure_window(window, ti_args, demo_name, ti_args.debug)
    ti_launcher.attach_pose_manager(
        window, pose_manager, ti_args, ti_args.debug
    )

    (
        AwrRangeWidget,
        VitalPanel,
        FusionStatusSummary,
        PhaseDiagnosticsPanel,
    ) = (
        _build_responsive_widgets()
    )
    awr_widget = AwrRangeWidget()
    vital_panel = VitalPanel(compact=args.compact_metrics)
    status_summary = FusionStatusSummary()
    diagnostics_panel = PhaseDiagnosticsPanel(
        phase_chart_mode=args.phase_chart_mode,
        phase_smooth_sec=args.phase_smooth_sec,
        phase_detrend_sec=args.phase_detrend_sec,
        visible_window_sec=args.phase_visible_window_sec,
        max_visible_points=args.plot_max_visible_points,
        component_normalize=args.component_chart_normalize,
        component_heart_scale=args.component_chart_heart_scale,
        breath_color=args.component_chart_breath_color,
        heart_color=args.component_chart_heart_color,
    )
    panels = _reflow_ti_window(
        window,
        awr_widget,
        vital_panel,
        diagnostics_panel,
        status_summary,
        args,
    )
    if args.demo_mode:
        window.connectStatus.setText("Demo mode — no COM ports opened")
        status_summary.update_status(iwr="Demo", awr="Demo")
    else:
        status_summary.update_status(iwr="Connecting", awr="Connecting")

    controller = FusionUiController(
        args,
        awr_widget,
        vital_panel,
        diagnostics_panel,
        status_summary,
        panels["iwr_status"],
        QTimer,
        start_awr=not args.no_auto_start and not args.demo_mode,
        iwr_core=window.core,
    )
    original_update = window.core.updateGraph

    def fused_update(_core, output_dict):
        raw_tracks = _copy_tracks(output_dict)
        demo_pose = output_dict.get("_fusionDemoPose")
        original_update(output_dict)
        safe_output = dict(output_dict)
        if raw_tracks is not None:
            safe_output["trackData"] = raw_tracks
        demo = window.core.demoClassDict.get(window.core.demo)
        pose_results = (
            demo_pose
            if demo_pose is not None
            else (getattr(demo, "latestPoseResults", {}) if demo else {})
        )
        controller.handle_iwr_frame(safe_output, pose_results)

    window.core.updateGraph = MethodType(fused_update, window.core)
    app.aboutToQuit.connect(controller.close)
    window._fusion_layout_debug_timer = _install_layout_debug(
        args,
        QTimer,
        panels,
        window,
    )
    window.show()

    if args.demo_mode:
        _start_demo(QTimer, window, controller)
    elif not args.no_auto_start:
        QTimer.singleShot(
            500, lambda: ti_launcher.auto_start(window, ti_args.debug)
        )
    if args.duration is not None:
        QTimer.singleShot(int(args.duration * 1000), app.quit)
    return int(app.exec())


def main() -> int:
    args = build_arg_parser().parse_args()
    try:
        return run(args)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
