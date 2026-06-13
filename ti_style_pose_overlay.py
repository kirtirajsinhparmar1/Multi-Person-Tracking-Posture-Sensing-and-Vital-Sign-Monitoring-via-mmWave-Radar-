"""Live pose integration for the vendored TI-style visualizer.

This module does not open serial ports. It receives parsed TI Visualizer
``outputDict`` frames, builds one independent 8-frame Pose/Fall feature window
per tracker TID, runs ONNX inference, and optionally logs per-TID predictions.

The ONNX model was trained on TI IWRL6432 Pose/Fall data. Live IWR6843ISK-ODS
performance must be validated before treating labels as reliable.
"""

from __future__ import annotations

from collections import defaultdict, deque
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

import pose_feature_extractor as features
from pose_model_runtime import CLASS_NAMES as DEFAULT_CLASS_NAMES, PoseModelRuntime, PoseSmoother


UNASSOCIATED_TRACK_INDEXES = {253, 254, 255}
STALE_TRACK_FRAMES = 30


class TiStylePoseManager:
    def __init__(
        self,
        model_path,
        smoothing_window: int = 7,
        min_confidence: float = 0.55,
        unknown_confidence: float = 0.45,
        moving_speed_threshold: float = 0.18,
        moving_confirm_frames: int = 3,
        fall_height_drop_threshold: float = 0.35,
        min_associated_points_for_inference: int = 1,
        allow_target_only: bool = False,
        enable_3d_labels: bool = False,
        label_format: str = "{tid} | {final_label} {confidence_percent}%",
        label_z_offset: float = 0.35,
        label_min_confidence: float = 0.45,
        label_max_distance: float | None = None,
        label_debug: bool = False,
        debug: bool = False,
        log_dir=None,
        cfg_path=None,
        cli_port: str | None = None,
        data_port: str | None = None,
        allow_missing_scaler: bool = False,
    ):
        self.model = PoseModelRuntime(
            model_path,
            allow_missing_scaler=allow_missing_scaler,
            debug=debug,
        )
        self.class_names = list(getattr(self.model, "class_names", DEFAULT_CLASS_NAMES))
        self.smoother = PoseSmoother(smoothing_window, class_names=self.class_names)
        self.smoothing_window = max(1, int(smoothing_window))
        self.min_confidence = float(min_confidence)
        self.unknown_confidence = float(unknown_confidence)
        self.moving_speed_threshold = float(moving_speed_threshold)
        self.moving_confirm_frames = max(1, int(moving_confirm_frames))
        self.fall_height_drop_threshold = float(fall_height_drop_threshold)
        self.min_associated_points_for_inference = max(
            0, int(min_associated_points_for_inference)
        )
        self.allow_target_only = bool(allow_target_only)
        self.enable_3d_labels = bool(enable_3d_labels)
        self.label_format = str(label_format)
        self.label_z_offset = float(label_z_offset)
        self.label_min_confidence = float(label_min_confidence)
        self.label_max_distance = (
            None if label_max_distance is None else float(label_max_distance)
        )
        self.label_debug = bool(label_debug)
        self.debug = bool(debug)
        self.model_path = str(Path(model_path).expanduser().resolve())
        self.last_seen_frame: dict[int, int] = {}
        self.latest_results: dict[int, dict] = {}
        self.speed_history = defaultdict(lambda: deque(maxlen=self.moving_confirm_frames))
        self.height_history = defaultdict(lambda: deque(maxlen=8))
        self._log_file = None
        self._log_writer = None
        self._log_path: Path | None = None

        features.reset_all()
        if log_dir is not None:
            self._init_logging(log_dir, cfg_path, cli_port, data_port)

    def process_output_dict(self, output_dict: dict[str, Any] | None) -> dict[int, dict]:
        if not isinstance(output_dict, dict):
            return {}

        frame_num = _int_value(output_dict.get("frameNum"), 0)
        tracks = _rows(output_dict.get("trackData"))
        points = _rows(output_dict.get("pointCloud"))
        target_heights = _height_by_tid(output_dict.get("heightData"))

        results: dict[int, dict] = {}
        seen_tids: set[int] = set()
        for track in tracks:
            if len(track) < 4:
                continue
            target = self._track_to_target(track)
            tid = int(target["tid"])
            seen_tids.add(tid)
            self.last_seen_frame[tid] = frame_num

            vx = float(target["vel_x"])
            vy = float(target["vel_y"])
            vz = float(target["vel_z"])
            horizontal_speed = math.sqrt(vx * vx + vy * vy)
            vertical_speed = abs(vz)
            motion_state = self._update_motion_state(tid, horizontal_speed)
            height_drop = self._update_height_drop(tid, float(target["pos_z"]))

            associated_points = self._associated_points(tid, points)
            build_result = features.build_22_feature_vector(target, associated_points)
            num_points = int(build_result.num_points)
            can_use_frame = self._can_use_frame_for_inference(num_points)
            if can_use_frame:
                features.update_8_frame_window(
                    tid, build_result.feature22, build_result.quality
                )
            window_age = features.get_window_age(tid)
            window_ready = features.is_window_ready(tid)

            raw_label = "WARMUP"
            raw_confidence = 0.0
            smoothed_label = "WARMUP"
            smoothed_confidence = 0.0
            probabilities = {name: 0.0 for name in self.class_names}
            prediction_exists = False

            if window_ready and can_use_frame:
                vector176 = features.build_176_feature_vector(tid)
                raw = self.model.predict(vector176)
                raw_label = raw["predicted_label"]
                raw_confidence = float(raw["confidence"])
                smoothed = self.smoother.update(tid, raw["probabilities"])
                smoothed_label = smoothed["smoothed_label"]
                smoothed_confidence = float(smoothed["smoothed_confidence"])
                probabilities = smoothed["smoothed_probabilities"]
                prediction_exists = True

            quality = self._quality_label(
                window_ready=window_ready,
                prediction_exists=prediction_exists,
                can_use_frame=can_use_frame,
                num_points=num_points,
                smoothed_confidence=smoothed_confidence,
            )
            low_quality = quality in {"LOW_POINTS", "NO_POINTS", "LOW_QUALITY"}
            final_label = self._final_label(
                window_ready=window_ready,
                prediction_exists=prediction_exists,
                smoothed_label=smoothed_label,
                smoothed_confidence=smoothed_confidence,
                motion_state=motion_state,
                height_drop=height_drop,
            )
            final_confidence = smoothed_confidence if prediction_exists else 0.0

            result = {
                "tid": tid,
                "window_ready": window_ready,
                "window_count": window_age,
                "window_age": window_age,
                "num_points": num_points,
                "selected_num_points": num_points,
                "low_quality": low_quality,
                "quality": quality,
                "reason": quality if quality != "OK" else "",
                "raw_label": raw_label,
                "raw_confidence": raw_confidence,
                "smoothed_label": smoothed_label,
                "smoothed_confidence": smoothed_confidence,
                "final_confidence": final_confidence,
                "probabilities": probabilities,
                "below_min_confidence": (
                    prediction_exists and smoothed_confidence < self.min_confidence
                ),
                "prediction_exists": prediction_exists,
                "motion_state": motion_state,
                "final_label": final_label,
                "assoc_mode": "index",
                "track_index": tid,
                "horizontal_speed": horizontal_speed,
                "vertical_speed": vertical_speed,
                "height_drop": height_drop,
                "x": float(target["pos_x"]),
                "y": float(target["pos_y"]),
                "z": float(target["pos_z"]),
                "target_height": float(target_heights.get(tid, 0.0)),
                "vx": vx,
                "vy": vy,
                "vz": vz,
                "frame": frame_num,
            }
            results[tid] = result

        self._reset_stale_tracks(frame_num, seen_tids)
        self.latest_results = results
        self._write_log_rows(results)
        self._debug_print(frame_num, len(tracks), results)
        return results

    def close(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def reset_tid(self, tid: int) -> None:
        tid_int = int(tid)
        features.reset_tid(tid_int)
        self.smoother.reset_tid(tid_int)
        self.last_seen_frame.pop(tid_int, None)
        self.latest_results.pop(tid_int, None)
        self.speed_history.pop(tid_int, None)
        self.height_history.pop(tid_int, None)

    def reset_all(self) -> None:
        features.reset_all()
        self.smoother.reset_all()
        self.last_seen_frame.clear()
        self.latest_results.clear()
        self.speed_history.clear()
        self.height_history.clear()

    def get_3d_label_records(self, track_data=None, height_data=None) -> list[dict]:
        if not self.enable_3d_labels:
            return []

        track_positions = _track_position_by_tid(track_data)
        target_heights = _height_by_tid(height_data)
        records: list[dict] = []

        for tid in sorted(self.latest_results):
            pose = self.latest_results[tid]
            window_ready = bool(pose.get("window_ready", False))
            final_label = str(pose.get("final_label", ""))
            confidence = float(pose.get("final_confidence", 0.0))

            x, y, z = track_positions.get(
                tid,
                (
                    float(pose.get("x", 0.0)),
                    float(pose.get("y", 0.0)),
                    float(pose.get("z", 0.0)),
                ),
            )
            if not all(math.isfinite(value) for value in (x, y, z)):
                continue
            if self.label_max_distance is not None:
                distance = math.sqrt(x * x + y * y + z * z)
                if distance > self.label_max_distance:
                    continue

            target_height = float(
                target_heights.get(tid, pose.get("target_height", 0.0)) or 0.0
            )
            z_label = z + max(0.0, target_height) + self.label_z_offset
            quality = str(pose.get("quality", "OK"))
            text = self._format_3d_label(tid, pose, quality)

            records.append(
                {
                    "tid": int(tid),
                    "text": text,
                    "x": float(x),
                    "y": float(y),
                    "z": float(z_label),
                    "final_label": final_label,
                    "posture_ml": str(pose.get("smoothed_label", "")),
                    "motion_state": str(pose.get("motion_state", "")),
                    "confidence": confidence,
                    "quality": quality,
                    "window_ready": window_ready,
                }
            )
        return records

    def _format_3d_label(self, tid: int, pose: dict, quality: str) -> str:
        final_label = str(pose.get("final_label", ""))
        confidence = float(pose.get("final_confidence", 0.0))
        confidence_percent = _percent_text(confidence)
        window_count = int(pose.get("window_count", pose.get("window_age", 0)) or 0)
        if final_label == "WARMUP" or not pose.get("window_ready", False):
            return f"{tid} | WARMUP {window_count}/8"
        if final_label == "NO_POSE" or not pose.get("prediction_exists", False):
            return f"{tid} | NO POSE"
        if self.label_debug:
            return (
                f"{tid} | {final_label} {confidence_percent}%\n"
                f"ML:{pose.get('smoothed_label', '-')} Q:{quality} "
                f"Pts:{pose.get('num_points', 0)}"
            )

        values = {
            "tid": tid,
            "final_label": final_label,
            "posture_ml": str(pose.get("smoothed_label", "")),
            "smoothed_label": str(pose.get("smoothed_label", "")),
            "motion_state": str(pose.get("motion_state", "")),
            "confidence": confidence,
            "confidence_percent": confidence_percent,
            "quality": quality,
            "window_ready": bool(pose.get("window_ready", False)),
            "window_count": window_count,
            "num_points": int(pose.get("num_points", 0) or 0),
        }
        try:
            text = self.label_format.format(**values)
        except Exception:
            text = f"{tid} | {final_label} {confidence_percent}%"
        if quality != "OK":
            text = f"{text} *"
        return text

    def _track_to_target(self, track: list[float]) -> dict[str, float]:
        return {
            "tid": int(track[0]),
            "pos_x": _float_at(track, 1),
            "pos_y": _float_at(track, 2),
            "pos_z": _float_at(track, 3),
            "vel_x": _float_at(track, 4),
            "vel_y": _float_at(track, 5),
            "vel_z": _float_at(track, 6),
            "acc_x": _float_at(track, 7),
            "acc_y": _float_at(track, 8),
            "acc_z": _float_at(track, 9),
            "confidence": _float_at(track, 11),
        }

    def _associated_points(self, tid: int, points: list[list[float]]) -> list[dict[str, float]]:
        associated: list[dict[str, float]] = []
        for index, point in enumerate(points):
            track_index = int(_float_at(point, 6, 255.0))
            if track_index in UNASSOCIATED_TRACK_INDEXES:
                continue
            if track_index != int(tid):
                continue
            associated.append(
                {
                    "index": index,
                    "x": _float_at(point, 0),
                    "y": _float_at(point, 1),
                    "z": _float_at(point, 2),
                    "doppler": _float_at(point, 3),
                    "snr": _float_at(point, 4),
                    "track_index": track_index,
                }
            )

        # TODO: Future improvement: align delayed IWR6843 track index pointCloud
        # with previous frame target positions.
        return associated

    def _update_motion_state(self, tid: int, horizontal_speed: float) -> str:
        history = self.speed_history[int(tid)]
        history.append(float(horizontal_speed) > self.moving_speed_threshold)
        if len(history) >= self.moving_confirm_frames and all(history):
            return "MOVING"
        return "STATIC"

    def _update_height_drop(self, tid: int, current_z: float) -> float:
        history = self.height_history[int(tid)]
        drop = max(0.0, max(history) - current_z) if history else 0.0
        history.append(float(current_z))
        return float(drop)

    def _can_use_frame_for_inference(self, num_points: int) -> bool:
        num_points = int(num_points)
        if num_points <= 0:
            return self.allow_target_only
        return num_points >= self.min_associated_points_for_inference

    def _quality_label(
        self,
        *,
        window_ready: bool,
        prediction_exists: bool,
        can_use_frame: bool,
        num_points: int,
        smoothed_confidence: float,
    ) -> str:
        if not window_ready:
            return "WARMUP"
        if int(num_points) <= 0:
            return "NO_POINTS"
        if not can_use_frame or int(num_points) < 5:
            return "LOW_POINTS"
        if prediction_exists and smoothed_confidence < self.min_confidence:
            return "LOW_CONF"
        return "OK"

    def _final_label(
        self,
        *,
        window_ready: bool,
        prediction_exists: bool,
        smoothed_label: str,
        smoothed_confidence: float,
        motion_state: str,
        height_drop: float,
    ) -> str:
        if not window_ready:
            return "WARMUP"
        if not prediction_exists:
            return "NO_POSE"
        if smoothed_confidence < self.unknown_confidence:
            return "UNKNOWN"

        label = str(smoothed_label).upper()
        if (
            height_drop > self.fall_height_drop_threshold
            and label in {"FALLING", "LYING"}
        ):
            return "FALLING"
        if label == "FALLING":
            return "FALLING"
        if label == "LYING":
            return "LYING"
        if label == "SITTING":
            return "SITTING"
        if label == "WALKING":
            return "MOVING" if motion_state == "MOVING" else "WALKING"
        if label == "STANDING" and motion_state == "MOVING":
            return "MOVING"
        if label == "STANDING":
            return "STANDING"
        return label if label in self.class_names else "UNKNOWN"

    def _reset_stale_tracks(self, frame_num: int, seen_tids: set[int]) -> None:
        stale: list[int] = []
        for tid, last_seen in self.last_seen_frame.items():
            if tid in seen_tids:
                continue
            if frame_num - last_seen > STALE_TRACK_FRAMES:
                stale.append(tid)
        for tid in stale:
            self.reset_tid(tid)

    def _debug_print(self, frame_num: int, num_targets: int, results: dict[int, dict]) -> None:
        if not self.debug or frame_num % 30 != 0:
            return
        print(
            f"[pose-debug] frame={frame_num} targets={num_targets} active_pose={len(results)}",
            flush=True,
        )
        for tid in sorted(results):
            item = results[tid]
            print(
                "[pose] "
                f"tid={tid} idx={item.get('track_index', '-')} "
                f"assoc={item.get('assoc_mode', '-')} "
                f"pts={item['num_points']} window={item['window_count']}/8 "
                f"raw={item['raw_label']} {item['raw_confidence']:.2f} "
                f"smooth={item['smoothed_label']} {item['smoothed_confidence']:.2f} "
                f"final={item['final_label']} quality={item['quality']}",
                flush=True,
            )

    def _init_logging(self, log_dir, cfg_path, cli_port, data_port) -> None:
        log_root = Path(log_dir).expanduser().resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        self._log_path = log_root / "pose_predictions_ui.csv"
        metadata_path = log_root / "pose_ui_metadata.json"

        self._log_file = self._log_path.open("w", newline="", encoding="utf-8")
        fieldnames = [
            "time",
            "frame",
            "tid",
            "x",
            "y",
            "z",
            "vx",
            "vy",
            "vz",
            "horizontal_speed",
            "vertical_speed",
            "height_drop",
            "num_points",
            "track_index",
            "assoc_mode",
            "selected_num_points",
            "quality",
            "low_quality",
            "window_ready",
            "window_count",
            "window_age",
            "raw_label",
            "raw_confidence",
            "smoothed_label",
            "smoothed_confidence",
            "final_label",
            "final_confidence",
            "motion_state",
        ] + [f"prob_{name}" for name in self.class_names]
        self._log_writer = csv.DictWriter(self._log_file, fieldnames=fieldnames)
        self._log_writer.writeheader()

        metadata = {
            "model_path": self.model_path,
            "cfg_path": str(cfg_path) if cfg_path is not None else "",
            "cli_port": cli_port or "",
            "data_port": data_port or "",
            "class_names": self.class_names,
            "feature_order": features.FEATURE_NAMES_22,
            "flatten_order": "channel-major, 22 features by 8 frames",
            "smoothing_window": self.smoothing_window,
            "min_confidence": self.min_confidence,
            "unknown_confidence": self.unknown_confidence,
            "moving_speed_threshold": self.moving_speed_threshold,
            "moving_confirm_frames": self.moving_confirm_frames,
            "fall_height_drop_threshold": self.fall_height_drop_threshold,
            "min_associated_points_for_inference": (
                self.min_associated_points_for_inference
            ),
            "allow_target_only": self.allow_target_only,
            "pose_3d_labels": self.enable_3d_labels,
            "pose_3d_label_format": self.label_format,
            "pose_3d_label_z_offset": self.label_z_offset,
            "pose_3d_label_min_confidence": self.label_min_confidence,
            "pose_3d_label_max_distance": self.label_max_distance,
            "pose_3d_label_debug": self.label_debug,
            "normalization_enabled": bool(getattr(self.model, "normalization_enabled", False)),
            "scaler_path": str(getattr(self.model, "scaler_path", "") or ""),
            "date_time": datetime.now().isoformat(timespec="seconds"),
            "notes": (
                "Model was trained on TI IWRL6432 Pose/Fall data. "
                "Live IWR6843 accuracy must be validated. MOVING is derived "
                "from speed, not from the ML class output."
            ),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _write_log_rows(self, results: dict[int, dict]) -> None:
        if self._log_writer is None:
            return
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        for tid in sorted(results):
            item = results[tid]
            probs = item["probabilities"]
            self._log_writer.writerow(
                {
                    "time": timestamp,
                    "frame": item["frame"],
                    "tid": item["tid"],
                    "x": item["x"],
                    "y": item["y"],
                    "z": item["z"],
                    "vx": item["vx"],
                    "vy": item["vy"],
                    "vz": item["vz"],
                    "horizontal_speed": item["horizontal_speed"],
                    "vertical_speed": item["vertical_speed"],
                    "height_drop": item["height_drop"],
                    "num_points": item["num_points"],
                    "track_index": item.get("track_index", ""),
                    "assoc_mode": item.get("assoc_mode", ""),
                    "selected_num_points": item.get("selected_num_points", item["num_points"]),
                    "quality": item.get("quality", ""),
                    "low_quality": item["low_quality"],
                    "window_ready": item["window_ready"],
                    "window_count": item.get("window_count", item["window_age"]),
                    "window_age": item["window_age"],
                    "raw_label": item["raw_label"],
                    "raw_confidence": item["raw_confidence"],
                    "smoothed_label": item["smoothed_label"],
                    "smoothed_confidence": item["smoothed_confidence"],
                    "final_label": item["final_label"],
                    "final_confidence": item.get("final_confidence", 0.0),
                    "motion_state": item["motion_state"],
                    **{f"prob_{name}": probs.get(name, 0.0) for name in self.class_names},
                }
            )
        if time.time() % 1.0 < 0.1 and self._log_file is not None:
            self._log_file.flush()


def _percent_text(confidence: Any) -> str:
    try:
        percent = float(confidence) * 100.0
    except Exception:
        return "-"
    if not math.isfinite(percent):
        return "-"
    if abs(percent - round(percent)) < 0.05:
        return f"{percent:.0f}"
    return f"{percent:.1f}"


def _rows(value: Any) -> list[list[float]]:
    if value is None:
        return []
    try:
        array = np.asarray(value)
    except Exception:
        return []
    if array.size == 0:
        return []
    if array.ndim == 1:
        array = array.reshape(1, -1)
    rows: list[list[float]] = []
    for row in array:
        try:
            rows.append([float(item) for item in list(row)])
        except Exception:
            continue
    return rows


def _float_at(row: list[float], index: int, default: float = 0.0) -> float:
    try:
        return float(row[index])
    except Exception:
        return float(default)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _height_by_tid(value: Any) -> dict[int, float]:
    heights: dict[int, float] = {}
    for row in _rows(value):
        if len(row) < 2:
            continue
        try:
            heights[int(row[0])] = float(row[1])
        except Exception:
            continue
    return heights


def _track_position_by_tid(value: Any) -> dict[int, tuple[float, float, float]]:
    positions: dict[int, tuple[float, float, float]] = {}
    for row in _rows(value):
        if len(row) < 4:
            continue
        try:
            positions[int(row[0])] = (float(row[1]), float(row[2]), float(row[3]))
        except Exception:
            continue
    return positions
