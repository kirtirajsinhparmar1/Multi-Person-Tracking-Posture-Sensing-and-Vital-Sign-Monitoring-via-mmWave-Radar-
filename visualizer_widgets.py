"""Reusable Qt widgets for the standalone IWR6843 visualizer."""

from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.GLGraphicsItem import GLGraphicsItem

from cfg_parser import (
    SceneConfig,
    apply_sensor_transform_array,
    apply_sensor_transform_xyz,
    box_lines,
    default_scene_config,
    rotate_vector,
    small_box_lines,
)


class ControlBar(QtWidgets.QWidget):
    send_config_clicked = QtCore.pyqtSignal()
    start_clicked = QtCore.pyqtSignal()
    stop_clicked = QtCore.pyqtSignal()
    cfg_browse_clicked = QtCore.pyqtSignal()
    out_browse_clicked = QtCore.pyqtSignal()
    threshold_changed = QtCore.pyqtSignal(float)
    fall_enabled_changed = QtCore.pyqtSignal(bool)

    def __init__(self, cli_port: str, data_port: str, cfg_path: str, out_dir: str):
        super().__init__()
        self.cli_edit = QtWidgets.QLineEdit(cli_port)
        self.data_edit = QtWidgets.QLineEdit(data_port)
        self.cfg_edit = QtWidgets.QLineEdit(cfg_path)
        self.out_edit = QtWidgets.QLineEdit(out_dir)
        self.send_button = QtWidgets.QPushButton("Send Config")
        self.start_button = QtWidgets.QPushButton("Start Streaming")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.log_checkbox = QtWidgets.QCheckBox("Start Logging")
        self.log_checkbox.setChecked(True)
        self.fall_checkbox = QtWidgets.QCheckBox("Fall Detection")
        self.fall_checkbox.setChecked(True)
        self.threshold_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.threshold_slider.setRange(0, 100)
        self.threshold_slider.setValue(50)
        self.threshold_label = QtWidgets.QLabel("0.60")

        cfg_button = QtWidgets.QPushButton("Cfg...")
        out_button = QtWidgets.QPushButton("Out...")

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(QtWidgets.QLabel("CLI"), 0, 0)
        layout.addWidget(self.cli_edit, 0, 1)
        layout.addWidget(QtWidgets.QLabel("Data"), 0, 2)
        layout.addWidget(self.data_edit, 0, 3)
        layout.addWidget(QtWidgets.QLabel("Config"), 0, 4)
        layout.addWidget(self.cfg_edit, 0, 5)
        layout.addWidget(cfg_button, 0, 6)
        layout.addWidget(QtWidgets.QLabel("Log Folder"), 1, 0)
        layout.addWidget(self.out_edit, 1, 1, 1, 3)
        layout.addWidget(out_button, 1, 4)
        layout.addWidget(self.send_button, 1, 5)
        layout.addWidget(self.start_button, 1, 6)
        layout.addWidget(self.stop_button, 1, 7)
        layout.addWidget(self.log_checkbox, 0, 7)
        layout.addWidget(self.fall_checkbox, 0, 8)
        layout.addWidget(QtWidgets.QLabel("Threshold"), 1, 8)
        layout.addWidget(self.threshold_slider, 1, 9)
        layout.addWidget(self.threshold_label, 1, 10)
        layout.setColumnStretch(5, 2)
        layout.setColumnStretch(9, 1)

        cfg_button.clicked.connect(self.cfg_browse_clicked)
        out_button.clicked.connect(self.out_browse_clicked)
        self.send_button.clicked.connect(self.send_config_clicked)
        self.start_button.clicked.connect(self.start_clicked)
        self.stop_button.clicked.connect(self.stop_clicked)
        self.threshold_slider.valueChanged.connect(self._threshold_slider_changed)
        self.fall_checkbox.stateChanged.connect(
            lambda state: self.fall_enabled_changed.emit(state == QtCore.Qt.Checked)
        )
        self.stop_button.setEnabled(False)

    def threshold_value(self) -> float:
        # Same mapping as TI people_tracking.py:224-225.
        return ((self.threshold_slider.value() / self.threshold_slider.maximum()) * 0.4) + 0.4

    def _threshold_slider_changed(self) -> None:
        value = self.threshold_value()
        self.threshold_label.setText(f"{value:.2f}")
        self.threshold_changed.emit(value)

    def set_streaming(self, streaming: bool) -> None:
        self.start_button.setEnabled(not streaming)
        self.send_button.setEnabled(not streaming)
        self.stop_button.setEnabled(streaming)


class StatusPanel(QtWidgets.QGroupBox):
    def __init__(self):
        super().__init__("Status")
        self.labels = {}
        layout = QtWidgets.QFormLayout(self)
        for key in [
            "connection",
            "last_frame",
            "fps",
            "points",
            "targets",
            "fall_events",
            "presence",
            "plot_updates",
            "table_updates",
            "warnings",
        ]:
            label = QtWidgets.QLabel("-")
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.labels[key] = label
            layout.addRow(key.replace("_", " ").title(), label)

    def set_value(self, key: str, value) -> None:
        if key in self.labels:
            self.labels[key].setText(str(value))


class TargetTable(QtWidgets.QTableWidget):
    HEADERS = [
        "TID",
        "X",
        "Y",
        "Z",
        "VX",
        "VY",
        "VZ",
        "maxZ",
        "minZ",
        "height",
        "fall",
        "drop_ratio/reason",
    ]

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.scene_config = default_scene_config()
        self.update_count = 0

    def set_scene_config(self, scene_config: SceneConfig) -> None:
        self.scene_config = scene_config

    def update_data(self, frame, statuses) -> None:
        self.update_count += 1
        heights = {height.tid: height for height in frame.heights}
        status_by_tid = {status.tid: status for status in statuses}
        self.setRowCount(len(frame.targets))

        for row, target in enumerate(frame.targets):
            pos_x, pos_y, pos_z = apply_sensor_transform_xyz(
                target.pos_x, target.pos_y, target.pos_z, self.scene_config
            )
            vel_x, vel_y, vel_z = rotate_vector(
                target.vel_x, target.vel_y, target.vel_z, self.scene_config
            )
            height = heights.get(target.tid)
            status = status_by_tid.get(target.tid)
            max_z = height.max_z if height else None
            min_z = height.min_z if height else None
            height_span = (max_z - min_z) if max_z is not None and min_z is not None else None
            fall_text = "FALL" if status and status.is_fallen else "false"
            if status and status.drop_ratio is not None:
                reason = f"{status.drop_ratio:.2f} / {status.reason}"
            elif status:
                reason = status.reason
            else:
                reason = f"conf {target.confidence:.2f}"
            values = [
                target.tid,
                pos_x,
                pos_y,
                pos_z,
                vel_x,
                vel_y,
                vel_z,
                max_z,
                min_z,
                height_span,
                fall_text,
                reason,
            ]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(_format_value(value))
                if col == 10 and fall_text == "FALL":
                    item.setBackground(QtGui.QColor(190, 40, 40))
                    item.setForeground(QtGui.QColor(255, 255, 255))
                self.setItem(row, col, item)


class GLTextLabel(GLGraphicsItem):
    """Simple GL text item compatible with PyQt5.

    TI uses a similar helper in common\\gl_text.py to draw target IDs beside
    tracked objects. This local version avoids importing TI code.
    """

    def __init__(self, view, text: str, pos=(0.0, 0.0, 0.0), color=QtCore.Qt.white, font_size=13):
        super().__init__()
        # Do not assign to self.view: GLGraphicsItem already has a view()
        # method, and update() calls that method internally.
        self.view_widget = view
        self.text = text
        self.pos = pos
        self.color = color
        self.font = QtGui.QFont("Helvetica", font_size)

    def set_data(self, text: str, pos, color=None) -> None:
        self.text = text
        self.pos = pos
        if color is not None:
            self.color = color
        self.update()

    def paint(self):
        self.view_widget.setFont(self.font)
        self.view_widget.qglColor(self.color)
        self.view_widget.renderText(float(self.pos[0]), float(self.pos[1]), float(self.pos[2]), self.text)


class PointCloud3DWidget(QtWidgets.QWidget):
    debug_message = QtCore.pyqtSignal(str)

    def __init__(self, scene_config: SceneConfig | None = None):
        super().__init__()
        self.scene_config = scene_config or default_scene_config()
        self.view_widget = gl.GLViewWidget()
        self.view_widget.setBackgroundColor(70, 72, 79)
        self.view_widget.setCameraPosition(distance=10, elevation=20, azimuth=-65)
        self.point_item = gl.GLScatterPlotItem(pos=np.zeros((0, 3)), size=4, color=(0.2, 0.8, 1.0, 0.8))
        self.target_item = gl.GLScatterPlotItem(pos=np.zeros((0, 3)), size=18, color=(1.0, 0.9, 0.1, 1.0))
        self.velocity_item = gl.GLLinePlotItem(pos=np.zeros((0, 3)), color=(1.0, 1.0, 1.0, 0.8), width=2, mode="lines")
        self.trails = {}
        self.trail_history = defaultdict(lambda: deque(maxlen=80))
        self.labels = {}
        self.fall_labels = {}
        self.boundary_items = []
        self.sensor_items = []
        self.update_count = 0

        grid = gl.GLGridItem()
        grid.setSize(10, 10)
        grid.setSpacing(1, 1)
        self.view_widget.addItem(grid)
        self._add_axes()
        self.view_widget.addItem(self.point_item)
        self.view_widget.addItem(self.target_item)
        self.view_widget.addItem(self.velocity_item)
        self.set_scene_config(self.scene_config)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view_widget)

    def set_scene_config(self, scene_config: SceneConfig) -> None:
        self.scene_config = scene_config
        for item in self.boundary_items + self.sensor_items:
            self.view_widget.removeItem(item)
        self.boundary_items = []
        self.sensor_items = []
        self._add_boundary_boxes()
        self._add_sensor_marker()
        self.debug_message.emit(
            "Boundary boxes parsed: "
            f"{len(self.scene_config.boundary_boxes)} | "
            f"sensor height={self.scene_config.sensor_height}m "
            f"az={self.scene_config.az_tilt_deg}deg elev={self.scene_config.elev_tilt_deg}deg"
        )

    def update_scene(self, frame, statuses) -> None:
        self.update_count += 1
        fallen_tids = {status.tid for status in statuses if status.is_fallen}

        if frame.points:
            point_pos = np.array([[point.x, point.y, point.z] for point in frame.points], dtype=float)
            point_pos = apply_sensor_transform_array(point_pos, self.scene_config)
            colors = np.array([self._point_color(point.track_index) for point in frame.points], dtype=float)
            self.point_item.setData(pos=point_pos, size=4, color=colors)
        else:
            self.point_item.setData(pos=np.zeros((0, 3)), size=3)

        target_positions = []
        velocity_lines = []
        if frame.targets:
            for target in frame.targets:
                x, y, z = apply_sensor_transform_xyz(target.pos_x, target.pos_y, target.pos_z, self.scene_config)
                target_positions.append([x, y, z])
                vx, vy, vz = rotate_vector(target.vel_x, target.vel_y, target.vel_z, self.scene_config)
                start = np.array([x, y, z], dtype=float)
                end = start + np.array([vx, vy, vz], dtype=float) * 0.35
                velocity_lines.extend([start, end])
            target_pos = np.array(target_positions, dtype=float)
            colors = np.array(
                [
                    (1.0, 0.05, 0.05, 1.0) if target.tid in fallen_tids else (1.0, 0.9, 0.1, 1.0)
                    for target in frame.targets
                ],
                dtype=float,
            )
            self.target_item.setData(pos=target_pos, size=16, color=colors)
        else:
            self.target_item.setData(pos=np.zeros((0, 3)), size=16)

        if velocity_lines:
            self.velocity_item.setData(pos=np.array(velocity_lines, dtype=float), color=(1.0, 1.0, 1.0, 0.8), width=2, mode="lines")
        else:
            self.velocity_item.setData(pos=np.zeros((0, 3)), mode="lines")

        active_tids = set()
        for target, pos_values in zip(frame.targets, target_positions):
            tid = int(target.tid)
            active_tids.add(tid)
            pos = np.array(pos_values, dtype=float)
            self.trail_history[tid].append(pos)
            self._update_trail(tid, tid in fallen_tids)
            self._update_label(tid, pos)
            self._update_fall_label(tid, pos, tid in fallen_tids)

        for tid in list(self.labels):
            if tid not in active_tids:
                self.view_widget.removeItem(self.labels.pop(tid))
        for tid in list(self.fall_labels):
            if tid not in active_tids or tid not in fallen_tids:
                self.view_widget.removeItem(self.fall_labels.pop(tid))
        for tid in list(self.trails):
            if tid not in active_tids:
                self.view_widget.removeItem(self.trails.pop(tid))

        if self.update_count % 30 == 1:
            self.debug_message.emit(
                f"3D plot update called: frame={frame.frame_num} "
                f"points={len(frame.points)} targets={len(frame.targets)} "
                f"updates={self.update_count}"
            )

    def _update_trail(self, tid: int, fallen: bool) -> None:
        points = np.array(self.trail_history[tid], dtype=float)
        color = (1.0, 0.1, 0.1, 1.0) if fallen else (1.0, 0.9, 0.1, 0.8)
        if tid not in self.trails:
            self.trails[tid] = gl.GLLinePlotItem(pos=points, color=color, width=2, antialias=True)
            self.view_widget.addItem(self.trails[tid])
        else:
            self.trails[tid].setData(pos=points, color=color, width=2)

    def _update_label(self, tid: int, pos: np.ndarray) -> None:
        label_pos = (float(pos[0]), float(pos[1]), float(pos[2] + 0.25))
        text = f"TID {tid}"
        color = QtCore.Qt.yellow
        if tid not in self.labels:
            item = GLTextLabel(self.view_widget, text, label_pos, color=color)
            self.labels[tid] = item
            self.view_widget.addItem(item)
        else:
            self.labels[tid].set_data(text, label_pos, color=color)

    def _update_fall_label(self, tid: int, pos: np.ndarray, fallen: bool) -> None:
        if not fallen:
            return
        label_pos = (float(pos[0]), float(pos[1]), float(pos[2] + 0.55))
        text = f"FALL TID {tid}"
        if tid not in self.fall_labels:
            item = GLTextLabel(self.view_widget, text, label_pos, color=QtCore.Qt.red, font_size=15)
            self.fall_labels[tid] = item
            self.view_widget.addItem(item)
        else:
            self.fall_labels[tid].set_data(text, label_pos, color=QtCore.Qt.red)

    def _add_axes(self) -> None:
        axes = [
            (np.array([[0, 0, 0], [1.5, 0, 0]], dtype=float), (1.0, 0.1, 0.1, 1.0), "X", (1.7, 0, 0)),
            (np.array([[0, 0, 0], [0, 1.5, 0]], dtype=float), (0.1, 1.0, 0.1, 1.0), "Y", (0, 1.7, 0)),
            (np.array([[0, 0, 0], [0, 0, 1.5]], dtype=float), (0.2, 0.4, 1.0, 1.0), "Z", (0, 0, 1.7)),
        ]
        for points, color, label, label_pos in axes:
            self.view_widget.addItem(gl.GLLinePlotItem(pos=points, color=color, width=3, mode="lines"))
            self.view_widget.addItem(GLTextLabel(self.view_widget, label, label_pos, color=QtCore.Qt.white))

    def _add_boundary_boxes(self) -> None:
        for box in self.scene_config.boundary_boxes:
            item = gl.GLLinePlotItem(pos=box_lines(box), color=box.color, width=2, antialias=True, mode="lines")
            self.boundary_items.append(item)
            self.view_widget.addItem(item)
            center = (
                (box.min_x + box.max_x) / 2.0,
                box.max_y,
                box.max_z + 0.08,
            )
            label = GLTextLabel(self.view_widget, box.name, center, color=QtCore.Qt.white, font_size=10)
            self.boundary_items.append(label)
            self.view_widget.addItem(label)

    def _add_sensor_marker(self) -> None:
        sensor_center = (0.0, 0.0, self.scene_config.sensor_height)
        sensor_box = gl.GLLinePlotItem(
            pos=small_box_lines(sensor_center, (0.35, 0.12, 0.25)),
            color=(1.0, 0.1, 0.1, 1.0),
            width=2,
            antialias=True,
            mode="lines",
        )
        self.sensor_items.append(sensor_box)
        self.view_widget.addItem(sensor_box)

        bx, by, bz = rotate_vector(0.0, 0.9, 0.0, self.scene_config)
        boresight = np.array(
            [
                [0.0, 0.0, self.scene_config.sensor_height],
                [bx, by, bz + self.scene_config.sensor_height],
            ],
            dtype=float,
        )
        bore_item = gl.GLLinePlotItem(pos=boresight, color=(1.0, 0.2, 0.2, 1.0), width=3, mode="lines")
        self.sensor_items.append(bore_item)
        self.view_widget.addItem(bore_item)
        label = GLTextLabel(self.view_widget, "sensor", (0.15, 0.0, self.scene_config.sensor_height + 0.2), color=QtCore.Qt.red)
        self.sensor_items.append(label)
        self.view_widget.addItem(label)

    def _point_color(self, track_index: int):
        if track_index >= 250:
            return (0.45, 0.82, 1.0, 0.72)
        palette = [
            (1.0, 0.4, 0.3, 0.85),
            (0.3, 1.0, 0.4, 0.85),
            (0.4, 0.5, 1.0, 0.85),
            (1.0, 0.9, 0.2, 0.85),
            (1.0, 0.4, 1.0, 0.85),
            (0.2, 1.0, 1.0, 0.85),
        ]
        return palette[int(track_index) % len(palette)]


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
