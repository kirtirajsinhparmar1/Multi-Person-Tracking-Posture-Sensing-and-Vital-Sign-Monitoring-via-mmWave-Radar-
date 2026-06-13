"""Main Qt application for the standalone IWR6843 fall visualizer."""

from __future__ import annotations

from pathlib import Path
import time

from PyQt5 import QtCore, QtWidgets

from cfg_parser import default_scene_config, parse_scene_config
from visualizer_widgets import ControlBar, PointCloud3DWidget, StatusPanel, TargetTable
from visualizer_worker import CliConfigWorker, DemoStreamWorker, RadarStreamWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.setWindowTitle("IWR6843 ODS Fall Logger")
        self.resize(1500, 900)

        self.scene_config = parse_scene_config(args.cfg) if args.cfg else default_scene_config()
        self.control = ControlBar(args.cli, args.data, args.cfg, args.out)
        self.status_panel = StatusPanel()
        self.plot_3d = PointCloud3DWidget(self.scene_config)
        self.target_table = TargetTable()
        self.target_table.set_scene_config(self.scene_config)
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1000)
        self.alert_label = QtWidgets.QLabel("No fall detected")
        self.alert_label.setAlignment(QtCore.Qt.AlignCenter)
        self.alert_label.setStyleSheet("font-weight: 700; padding: 8px; background: #202020; color: #dddddd;")

        root = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.addWidget(self.control)
        root_layout.addWidget(self.alert_label)

        center_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        center_split.addWidget(self.status_panel)
        center_split.addWidget(self.plot_3d)
        center_split.addWidget(self.target_table)
        center_split.setStretchFactor(0, 0)
        center_split.setStretchFactor(1, 2)
        center_split.setStretchFactor(2, 1)
        root_layout.addWidget(center_split, stretch=1)
        root_layout.addWidget(self.console, stretch=0)
        self.setCentralWidget(root)

        self.worker_thread = None
        self.worker = None
        self.config_thread = None
        self.config_worker = None
        self.config_sent = bool(args.no_send_cfg or args.demo)
        self.last_frame_wall_time = None
        self.fall_event_count = 0

        self.control.send_config_clicked.connect(self.send_config)
        self.control.start_clicked.connect(self.start_streaming)
        self.control.stop_clicked.connect(self.stop_streaming)
        self.control.cfg_browse_clicked.connect(self.browse_cfg)
        self.control.out_browse_clicked.connect(self.browse_out)
        self.control.threshold_changed.connect(self.threshold_changed)
        self.control.fall_enabled_changed.connect(self.fall_enabled_changed)
        self.plot_3d.debug_message.connect(self.append_console)

        self.status_panel.set_value("connection", "Demo idle" if args.demo else "Idle")
        self._log_scene_config()
        if args.replay:
            self.append_console("Replay mode is not implemented yet. TODO: load frames from saved logs.")
        if args.demo:
            self.append_console("Demo mode selected. Starting synthetic stream automatically.")
            QtCore.QTimer.singleShot(350, self.start_streaming)

    def browse_cfg(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select radar cfg",
            self.control.cfg_edit.text(),
            "Config files (*.cfg);;All files (*)",
        )
        if filename:
            self.control.cfg_edit.setText(filename)
            self.config_sent = False
            self.reload_scene_config()

    def browse_out(self) -> None:
        dirname = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select output log folder",
            self.control.out_edit.text(),
        )
        if dirname:
            self.control.out_edit.setText(dirname)

    def send_config(self) -> None:
        self.reload_scene_config()
        self._start_config_worker(mark_sent=True)

    def _start_config_worker(self, mark_sent: bool) -> None:
        if self.config_thread is not None:
            self.append_console("Config sender is already running")
            return
        self.config_thread = QtCore.QThread()
        self.config_worker = CliConfigWorker(
            self.control.cli_edit.text().strip(),
            self.args.cli_baud,
            self.control.cfg_edit.text().strip(),
        )
        self.config_worker.moveToThread(self.config_thread)
        self.config_thread.started.connect(self.config_worker.run)
        self.config_worker.message.connect(self.append_console)
        self.config_worker.error.connect(self.handle_error)
        self.config_worker.finished.connect(lambda ok: self._config_finished(ok, mark_sent))
        self.config_worker.finished.connect(self.config_thread.quit)
        self.config_worker.finished.connect(self.config_worker.deleteLater)
        self.config_thread.finished.connect(self._clear_config_thread)
        self.config_thread.start()
        self.status_panel.set_value("connection", "Sending config")

    def _config_finished(self, ok: bool, mark_sent: bool) -> None:
        self.config_sent = ok if mark_sent else self.config_sent
        self.status_panel.set_value("connection", "Config sent" if ok else "Config failed")

    def _clear_config_thread(self) -> None:
        self.config_thread.deleteLater()
        self.config_thread = None
        self.config_worker = None

    def start_streaming(self) -> None:
        if self.worker_thread is not None:
            return
        self.reload_scene_config()
        if self.args.demo:
            self._start_demo_worker()
            return
        if not self.args.no_send_cfg and not self.config_sent:
            self.append_console("Config has not been sent in this session. Sending cfg before streaming.")
            self._start_config_then_stream()
            return
        self._start_stream_worker()

    def _start_config_then_stream(self) -> None:
        if self.config_thread is not None:
            self.append_console("Config sender is already running")
            return
        self.config_thread = QtCore.QThread()
        self.config_worker = CliConfigWorker(
            self.control.cli_edit.text().strip(),
            self.args.cli_baud,
            self.control.cfg_edit.text().strip(),
        )
        self.config_worker.moveToThread(self.config_thread)
        self.config_thread.started.connect(self.config_worker.run)
        self.config_worker.message.connect(self.append_console)
        self.config_worker.error.connect(self.handle_error)
        self.config_worker.finished.connect(self._after_config_start_stream)
        self.config_worker.finished.connect(self.config_thread.quit)
        self.config_worker.finished.connect(self.config_worker.deleteLater)
        self.config_thread.finished.connect(self._clear_config_thread)
        self.config_thread.start()
        self.status_panel.set_value("connection", "Sending config")

    def _after_config_start_stream(self, ok: bool) -> None:
        self.config_sent = ok
        if ok:
            self._start_stream_worker()
        else:
            self.status_panel.set_value("connection", "Config failed")

    def _start_stream_worker(self) -> None:
        self.worker_thread = QtCore.QThread()
        self.worker = RadarStreamWorker(
            data_port=self.control.data_edit.text().strip(),
            data_baud=self.args.baud,
            out_dir=self.control.out_edit.text().strip(),
            log_enabled=self.control.log_checkbox.isChecked(),
            fall_enabled=self.control.fall_checkbox.isChecked(),
            threshold=self.control.threshold_value(),
            max_tracks=self.scene_config.max_tracks or self.args.max_tracks,
            frame_time_ms=self.scene_config.frame_time_ms or self.args.frame_time,
            serial_timeout=self.args.timeout,
            no_points=self.args.no_points,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.frame_ready.connect(self.frame_ready)
        self.worker.message.connect(self.append_console)
        self.worker.error.connect(self.handle_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._stream_finished)
        self.worker_thread.start()
        self.control.set_streaming(True)
        self.status_panel.set_value("connection", "Streaming")
        self.append_console("Streaming started")

    def _start_demo_worker(self) -> None:
        self.worker_thread = QtCore.QThread()
        self.worker = DemoStreamWorker(
            out_dir=self.control.out_edit.text().strip(),
            log_enabled=self.control.log_checkbox.isChecked(),
            fall_enabled=self.control.fall_checkbox.isChecked(),
            threshold=self.control.threshold_value(),
            frame_time_ms=self.scene_config.frame_time_ms or self.args.frame_time,
            no_points=self.args.no_points,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.frame_ready.connect(self.frame_ready)
        self.worker.message.connect(self.append_console)
        self.worker.error.connect(self.handle_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._stream_finished)
        self.worker_thread.start()
        self.control.set_streaming(True)
        self.status_panel.set_value("connection", "Demo streaming")
        self.append_console("Demo streaming started")

    def stop_streaming(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.append_console("Stopping stream...")

    def _stream_finished(self) -> None:
        self.worker_thread.deleteLater()
        self.worker_thread = None
        self.worker = None
        self.control.set_streaming(False)
        self.status_panel.set_value("connection", "Stopped")
        self.append_console("Streaming stopped")

    def threshold_changed(self, value: float) -> None:
        if self.worker is not None:
            self.worker.set_threshold(value)

    def fall_enabled_changed(self, enabled: bool) -> None:
        if self.worker is not None:
            self.worker.set_fall_enabled(enabled)

    def frame_ready(self, frame, statuses, timestamp: float) -> None:
        fps = "-"
        if self.last_frame_wall_time is not None:
            dt = timestamp - self.last_frame_wall_time
            if dt > 0:
                fps = f"{1.0 / dt:.1f}"
        self.last_frame_wall_time = timestamp

        self.status_panel.set_value("last_frame", frame.frame_num)
        self.status_panel.set_value("fps", fps)
        self.status_panel.set_value("points", len(frame.points))
        self.status_panel.set_value("targets", len(frame.targets))
        frame_falls = sum(1 for status in statuses if status.is_fallen)
        if frame_falls:
            self.fall_event_count += frame_falls
        self.status_panel.set_value("fall_events", self.fall_event_count)
        self.status_panel.set_value("presence", frame.presence if frame.presence is not None else "-")
        self.status_panel.set_value("warnings", frame.parse_error or "-")
        self.plot_3d.update_scene(frame, statuses)
        self.target_table.update_data(frame, statuses)
        self.status_panel.set_value("plot_updates", self.plot_3d.update_count)
        self.status_panel.set_value("table_updates", self.target_table.update_count)
        if self.plot_3d.update_count % 30 == 1:
            self.append_console(
                f"UI update frame={frame.frame_num} points={len(frame.points)} "
                f"targets={len(frame.targets)} plot_updates={self.plot_3d.update_count} "
                f"table_updates={self.target_table.update_count}"
            )
        self.update_alert(statuses)

    def update_alert(self, statuses) -> None:
        fallen = [status for status in statuses if status.is_fallen]
        if not fallen:
            self.alert_label.setText("No fall detected")
            self.alert_label.setStyleSheet(
                "font-weight: 700; padding: 8px; background: #202020; color: #dddddd;"
            )
            return
        text = " | ".join(
            f"TID {status.tid} FALL height={status.current_height:.2f} "
            f"ratio={status.drop_ratio:.2f}" if status.drop_ratio is not None
            else f"TID {status.tid} FALL height={status.current_height:.2f}"
            for status in fallen
        )
        self.alert_label.setText(text)
        self.alert_label.setStyleSheet(
            "font-weight: 800; padding: 8px; background: #b00020; color: white;"
        )
        self.append_console(text)

    def append_console(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.console.appendPlainText(f"[{ts}] {message}")

    def handle_error(self, message: str) -> None:
        self.status_panel.set_value("warnings", message)
        self.append_console(f"ERROR: {message}")

    def reload_scene_config(self) -> None:
        self.scene_config = parse_scene_config(self.control.cfg_edit.text().strip())
        self.plot_3d.set_scene_config(self.scene_config)
        self.target_table.set_scene_config(self.scene_config)
        self._log_scene_config()

    def _log_scene_config(self) -> None:
        self.append_console(
            "Scene cfg: "
            f"sensorHeight={self.scene_config.sensor_height}m "
            f"azTilt={self.scene_config.az_tilt_deg}deg "
            f"elevTilt={self.scene_config.elev_tilt_deg}deg "
            f"boxes={len(self.scene_config.boundary_boxes)} "
            f"frameTime={self.scene_config.frame_time_ms}ms"
        )

    def closeEvent(self, event) -> None:
        self.stop_streaming()
        super().closeEvent(event)


def run_app(args) -> int:
    app = QtWidgets.QApplication([])
    app.setApplicationName("IWR6843 Fall Visualizer")
    window = MainWindow(args)
    window.show()
    return app.exec_()
