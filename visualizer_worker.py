"""Background workers for the standalone IWR6843 visualizer."""

from __future__ import annotations

import math
import time

import numpy as np
from PyQt5 import QtCore

from cli_sender import CliSenderError, send_config
from csv_logger import CsvLogger
from fall_detector import FallDetector
from frame_types import FrameHeader, ParsedFrame, Point, Target, TargetHeight
from parser import MAGIC_WORD
from serial_reader import RadarSerialReader


NO_DATA_MESSAGE = (
    "No data frames received. Check: board functional mode, COM6/COM7 ports, "
    "cfg sent successfully, sensorStart Done, and close TI Visualizer/UniFlash."
)


class CliConfigWorker(QtCore.QObject):
    message = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(bool)

    def __init__(self, cli_port: str, cli_baud: int, cfg_path: str):
        super().__init__()
        self.cli_port = cli_port
        self.cli_baud = cli_baud
        self.cfg_path = cfg_path

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            result = send_config(
                self.cli_port,
                self.cli_baud,
                self.cfg_path,
                output=self.message.emit,
            )
        except CliSenderError as exc:
            self._safe_emit(self.error, str(exc))
            self._safe_emit(self.finished, False)
            return
        self._safe_emit(
            self.message,
            f"Config sent: {result.commands_sent} cfg commands from {result.cfg_path}"
        )
        self._safe_emit(self.finished, result.success)

    def _safe_emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


class RadarStreamWorker(QtCore.QObject):
    frame_ready = QtCore.pyqtSignal(object, object, float)
    message = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(
        self,
        data_port: str,
        data_baud: int,
        out_dir: str,
        log_enabled: bool,
        fall_enabled: bool,
        threshold: float,
        max_tracks: int = 10,
        frame_time_ms: int = 55,
        serial_timeout: float = 0.6,
        no_points: bool = False,
    ):
        super().__init__()
        self.data_port = data_port
        self.data_baud = data_baud
        self.out_dir = out_dir
        self.log_enabled = log_enabled
        self.fall_enabled = fall_enabled
        self.threshold = threshold
        self.max_tracks = max_tracks
        self.frame_time_ms = frame_time_ms
        self.serial_timeout = serial_timeout
        self.no_points = no_points
        self._running = False

    @QtCore.pyqtSlot()
    def run(self) -> None:
        self._running = True
        detector = FallDetector(
            max_num_tracks=self.max_tracks,
            frame_time_ms=self.frame_time_ms,
            falling_threshold_proportion=self.threshold,
        )
        logger = CsvLogger(self.out_dir, log_points=not self.no_points) if self.log_enabled else None

        try:
            with RadarSerialReader(self.data_port, self.data_baud, self.serial_timeout) as reader:
                self._safe_emit(self.message, f"Opened data port {self.data_port} at {self.data_baud}")
                last_timeout_message = 0.0
                frames_received = 0
                while self._running:
                    try:
                        frame = reader.read_parsed_frame()
                    except TimeoutError:
                        now = time.time()
                        if now - last_timeout_message > 2.0:
                            self._safe_emit(self.error, NO_DATA_MESSAGE)
                            last_timeout_message = now
                        continue
                    except Exception as exc:
                        self._safe_emit(self.error, f"Data UART/parser error: {exc}")
                        break

                    detector.set_fall_sensitivity(self.threshold)
                    statuses = detector.step(frame.heights, frame.targets) if self.fall_enabled else []
                    timestamp = time.time()
                    frames_received += 1

                    if logger is not None:
                        logger.write_frame(frame, timestamp, statuses)

                    if frames_received % 30 == 1:
                        self._safe_emit(
                            self.message,
                            f"Parser stats frame={frame.frame_num} points={len(frame.points)} "
                            f"targets={len(frame.targets)} heights={len(frame.heights)} "
                            f"presence={frame.presence} unknown_tlvs={frame.unknown_tlvs} "
                            f"parse_error={frame.parse_error or '-'}"
                        )
                    self._safe_emit(self.frame_ready, frame, statuses, timestamp)
        except Exception as exc:
            self._safe_emit(self.error, str(exc))
        finally:
            if logger is not None:
                logger.close()
                self._safe_emit(self.message, f"Closed CSV logs in {self.out_dir}")
            self._safe_emit(self.finished)

    def stop(self) -> None:
        self._running = False

    def set_threshold(self, threshold: float) -> None:
        self.threshold = threshold

    def set_fall_enabled(self, enabled: bool) -> None:
        self.fall_enabled = enabled

    def _safe_emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


class DemoStreamWorker(QtCore.QObject):
    frame_ready = QtCore.pyqtSignal(object, object, float)
    message = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(
        self,
        out_dir: str,
        log_enabled: bool,
        fall_enabled: bool,
        threshold: float,
        frame_time_ms: int = 55,
        no_points: bool = False,
    ):
        super().__init__()
        self.out_dir = out_dir
        self.log_enabled = log_enabled
        self.fall_enabled = fall_enabled
        self.threshold = threshold
        self.frame_time_ms = frame_time_ms
        self.no_points = no_points
        self._running = False

    @QtCore.pyqtSlot()
    def run(self) -> None:
        self._running = True
        detector = FallDetector(
            max_num_tracks=10,
            frame_time_ms=self.frame_time_ms,
            falling_threshold_proportion=self.threshold,
        )
        logger = CsvLogger(self.out_dir, log_points=not self.no_points) if self.log_enabled else None
        frame_num = 0
        period = max(self.frame_time_ms / 1000.0, 0.01)
        self._safe_emit(
            self.message,
            "Demo mode started: synthetic point cloud, two targets, trails, and a fall event",
        )

        try:
            while self._running:
                frame = make_demo_frame(frame_num)
                detector.set_fall_sensitivity(self.threshold)
                statuses = detector.step(frame.heights, frame.targets) if self.fall_enabled else []
                timestamp = time.time()
                if logger is not None:
                    logger.write_frame(frame, timestamp, statuses)
                if frame_num % 30 == 1:
                    self._safe_emit(
                        self.message,
                        f"Demo parser stats frame={frame.frame_num} points={len(frame.points)} "
                        f"targets={len(frame.targets)} heights={len(frame.heights)}"
                    )
                self._safe_emit(self.frame_ready, frame, statuses, timestamp)
                frame_num += 1
                time.sleep(period)
        finally:
            if logger is not None:
                logger.close()
                self._safe_emit(self.message, f"Closed demo CSV logs in {self.out_dir}")
            self._safe_emit(self.finished)

    def stop(self) -> None:
        self._running = False

    def set_threshold(self, threshold: float) -> None:
        self.threshold = threshold

    def set_fall_enabled(self, enabled: bool) -> None:
        self.fall_enabled = enabled

    def _safe_emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


def make_demo_frame(frame_num: int) -> ParsedFrame:
    magic = int.from_bytes(MAGIC_WORD, byteorder="little")
    header = FrameHeader(
        magic=magic,
        version=0,
        total_packet_len=0,
        platform=0,
        frame_num=frame_num,
        time_cpu_cycles=frame_num * 55,
        num_detected_obj=90,
        num_tlvs=5,
        sub_frame_num=0,
    )

    t = frame_num * 0.055
    target1 = Target(
        tid=1,
        pos_x=1.0 + 0.8 * math.sin(t * 0.7),
        pos_y=2.0 + 0.8 * math.cos(t * 0.5),
        pos_z=-0.15,
        vel_x=0.5 * math.cos(t * 0.7),
        vel_y=-0.4 * math.sin(t * 0.5),
        vel_z=0.0,
        acc_x=0.0,
        acc_y=0.0,
        acc_z=0.0,
        g=1.0,
        confidence=0.95,
    )
    falling_phase = 1.55 if frame_num < 70 else max(0.55, 1.55 - (frame_num - 70) * 0.035)
    target2 = Target(
        tid=2,
        pos_x=-1.1 + 0.5 * math.sin(t * 0.4),
        pos_y=4.2 + 0.4 * math.cos(t * 0.6),
        pos_z=falling_phase - 2.0,
        vel_x=0.1,
        vel_y=0.0,
        vel_z=-0.8 if frame_num >= 70 and falling_phase > 0.55 else 0.0,
        acc_x=0.0,
        acc_y=0.0,
        acc_z=-0.2,
        g=1.0,
        confidence=0.90,
    )
    targets = [target1, target2]
    heights = [
        TargetHeight(tid=1, max_z=1.65, min_z=0.10),
        TargetHeight(tid=2, max_z=falling_phase, min_z=0.05),
    ]

    rng = np.random.default_rng(seed=frame_num)
    points: list[Point] = []
    index = 0
    for target, height in zip(targets, heights):
        for _ in range(45):
            px = target.pos_x + rng.normal(0.0, 0.22)
            py = target.pos_y + rng.normal(0.0, 0.25)
            pz_world = rng.uniform(height.min_z, height.max_z)
            # Parser output is sensor-relative. The visualizer applies height/tilt later,
            # so keep demo Z around physical height minus the 2 m demo sensor height.
            pz = pz_world - 2.0
            points.append(
                Point(
                    index=index,
                    x=float(px),
                    y=float(py),
                    z=float(pz),
                    doppler=float(target.vel_y + rng.normal(0.0, 0.05)),
                    snr=float(12.0 + rng.normal(0.0, 2.0)),
                    range_m=float(math.sqrt(px * px + py * py + pz * pz)),
                    azimuth=0.0,
                    elevation=0.0,
                    track_index=target.tid,
                )
            )
            index += 1

    frame = ParsedFrame(
        header=header,
        targets=targets,
        heights=heights,
        points=points,
        target_indexes=[point.track_index for point in points],
        presence=1,
    )
    return frame
