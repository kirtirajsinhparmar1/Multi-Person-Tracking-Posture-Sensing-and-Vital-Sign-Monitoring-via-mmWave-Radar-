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
from vital_signs_runtime import VitalSignsManager


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
        moving_confirm_frames: int = 4,
        fall_height_drop_threshold: float = 0.35,
        fall_vertical_speed_threshold: float = 0.35,
        fall_high_confidence: float = 0.85,
        fall_min_height_drop_with_high_confidence: float = 0.20,
        fall_stability_frames: int | None = None,
        display_stability_frames: int = 16,
        display_min_confidence: float = 0.55,
        display_hysteresis: bool = True,
        display_stability_ratio: float = 0.70,
        falling_fast_update: bool = True,
        falling_stability_frames: int = 6,
        sitting_stability_frames: int = 8,
        sitting_stability_ratio: float = 0.50,
        sitting_min_confidence: float = 0.40,
        sitting_max_speed: float = 0.25,
        standing_min_confidence: float = 0.50,
        lying_min_confidence: float = 0.50,
        min_associated_points_for_inference: int = 1,
        allow_target_only: bool = False,
        enable_3d_labels: bool = False,
        label_format: str = "{tid} | {final_label} {confidence_percent}%",
        label_z_offset: float = 0.35,
        label_min_confidence: float = 0.45,
        label_max_distance: float | None = None,
        label_debug: bool = False,
        enable_human_models: bool = False,
        human_model_debug: bool = False,
        ground_z: float = 0.0,
        human_model_target_height: float = 1.70,
        human_model_target_sitting_height: float = 1.20,
        human_model_target_lying_length: float = 1.70,
        vitals_enable_gate: bool = False,
        vitals_required_posture: str = "SITTING",
        vitals_sitting_stable_frames: int = 30,
        vitals_max_horizontal_speed: float = 0.08,
        vitals_min_pose_confidence: float = 0.60,
        vitals_grace_frames: int = 15,
        vitals_reset_when_not_sitting: bool = True,
        vitals_labels: bool = False,
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
        self.fall_vertical_speed_threshold = float(fall_vertical_speed_threshold)
        self.fall_high_confidence = float(fall_high_confidence)
        self.fall_min_height_drop_with_high_confidence = float(
            fall_min_height_drop_with_high_confidence
        )
        self.display_stability_frames = max(1, int(display_stability_frames))
        self.display_min_confidence = float(display_min_confidence)
        self.display_hysteresis = bool(display_hysteresis)
        self.display_stability_ratio = max(0.0, min(1.0, float(display_stability_ratio)))
        self.falling_fast_update = bool(falling_fast_update)
        if fall_stability_frames is None:
            fall_stability_frames = falling_stability_frames
        self.fall_stability_frames = max(1, int(fall_stability_frames))
        self.falling_stability_frames = self.fall_stability_frames
        self.sitting_stability_frames = max(1, int(sitting_stability_frames))
        self.sitting_stability_ratio = max(0.0, min(1.0, float(sitting_stability_ratio)))
        self.sitting_min_confidence = float(sitting_min_confidence)
        self.sitting_max_speed = float(sitting_max_speed)
        self.standing_min_confidence = float(standing_min_confidence)
        self.lying_min_confidence = float(lying_min_confidence)
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
        self.enable_human_models = bool(enable_human_models)
        self.human_model_debug = bool(human_model_debug)
        self.ground_z = float(ground_z)
        self.human_model_target_height = float(human_model_target_height)
        self.human_model_target_sitting_height = float(human_model_target_sitting_height)
        self.human_model_target_lying_length = float(human_model_target_lying_length)
        self.vitals_labels = bool(vitals_labels)
        self.vitals_manager = VitalSignsManager(
            enabled=vitals_enable_gate,
            required_posture=vitals_required_posture,
            sitting_stable_frames=vitals_sitting_stable_frames,
            max_horizontal_speed=vitals_max_horizontal_speed,
            min_pose_confidence=vitals_min_pose_confidence,
            grace_frames=vitals_grace_frames,
            reset_when_not_sitting=vitals_reset_when_not_sitting,
            debug=debug,
        )
        self.debug = bool(debug)
        self.model_path = str(Path(model_path).expanduser().resolve())
        self.last_seen_frame: dict[int, int] = {}
        self.latest_results: dict[int, dict] = {}
        self.speed_history = defaultdict(lambda: deque(maxlen=self.moving_confirm_frames))
        self.height_history = defaultdict(lambda: deque(maxlen=8))
        display_history_len = max(
            self.display_stability_frames,
            self.fall_stability_frames,
            self.sitting_stability_frames,
        )
        self.display_history = defaultdict(lambda: deque(maxlen=display_history_len))
        self.display_state: dict[int, dict[str, Any]] = {}
        self.raw_label_history = defaultdict(lambda: deque(maxlen=display_history_len))
        self.confidence_history = defaultdict(lambda: deque(maxlen=display_history_len))
        self.probability_history = defaultdict(lambda: deque(maxlen=display_history_len))
        self.position_history = defaultdict(lambda: deque(maxlen=display_history_len))
        self.velocity_history = defaultdict(lambda: deque(maxlen=display_history_len))
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
        # A nonzero parser status does not invalidate fields that were decoded
        # successfully. In particular, preserve valid target and TLV 1040 data.
        parser_error = output_dict.get("error")
        if (
            self.debug
            and parser_error not in (None, 0)
            and (
                output_dict.get("trackData") is not None
                or output_dict.get("vitals") is not None
            )
        ):
            print(
                f"[pose] frame={frame_num} parser_error={parser_error}; "
                "processing available targets/vitals",
                flush=True,
            )
        self.vitals_manager.update_from_frame(output_dict)
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
            self._update_tuning_histories(
                tid=tid,
                raw_label=raw_label,
                confidence=smoothed_confidence,
                probabilities=probabilities,
                position=(
                    float(target["pos_x"]),
                    float(target["pos_y"]),
                    float(target["pos_z"]),
                ),
                velocity=(vx, vy, vz),
            )
            fall_gate_passed, fall_gate_reason = self._evaluate_fall_gate(
                tid=tid,
                smoothed_label=smoothed_label,
                smoothed_confidence=smoothed_confidence,
                probabilities=probabilities,
                height_drop=height_drop,
                vertical_speed=vertical_speed,
            )
            sitting_gate_passed, sitting_gate_reason = self._evaluate_sitting_gate(
                smoothed_label=smoothed_label,
                smoothed_confidence=smoothed_confidence,
                probabilities=probabilities,
                horizontal_speed=horizontal_speed,
            )
            candidate_label = self._final_label(
                window_ready=window_ready,
                prediction_exists=prediction_exists,
                smoothed_label=smoothed_label,
                smoothed_confidence=smoothed_confidence,
                motion_state=motion_state,
                height_drop=height_drop,
                horizontal_speed=horizontal_speed,
                vertical_speed=vertical_speed,
                probabilities=probabilities,
                fall_gate_passed=fall_gate_passed,
                sitting_gate_passed=sitting_gate_passed,
            )
            candidate_confidence = smoothed_confidence if prediction_exists else 0.0
            display = self._update_display_state(
                tid=tid,
                candidate_label=candidate_label,
                candidate_confidence=candidate_confidence,
                window_ready=window_ready,
                prediction_exists=prediction_exists,
                horizontal_speed=horizontal_speed,
                fall_gate_passed=fall_gate_passed,
                fall_gate_reason=fall_gate_reason,
                sitting_gate_passed=sitting_gate_passed,
                sitting_gate_reason=sitting_gate_reason,
            )
            displayed_label = display["displayed_label"]
            displayed_confidence = display["displayed_confidence"]

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
                "ml_top_label": smoothed_label,
                "ml_top_confidence": smoothed_confidence,
                "smoothed_label": smoothed_label,
                "smoothed_confidence": smoothed_confidence,
                "candidate_confidence": candidate_confidence,
                "final_confidence": displayed_confidence,
                "probabilities": probabilities,
                "below_min_confidence": (
                    prediction_exists and smoothed_confidence < self.min_confidence
                ),
                "prediction_exists": prediction_exists,
                "motion_state": motion_state,
                "candidate_label": candidate_label,
                "pre_display_final_label": candidate_label,
                "final_label": displayed_label,
                "displayed_label": displayed_label,
                "displayed_confidence": displayed_confidence,
                "display_stability_count": display["display_stability_count"],
                "display_stability_required": display["display_stability_required"],
                "display_stability_ratio": display["display_stability_ratio"],
                "display_status": display["display_status"],
                "transition_reason": display["transition_reason"],
                "fall_gate_passed": fall_gate_passed,
                "fall_gate_reason": fall_gate_reason,
                "sitting_gate_passed": sitting_gate_passed,
                "sitting_gate_reason": sitting_gate_reason,
                "stability_count": display["display_stability_count"],
                "stability_required": display["display_stability_required"],
                "stability_ratio": display["display_stability_ratio"],
                "assoc_mode": "index",
                "track_index": tid,
                "horizontal_speed": horizontal_speed,
                "vertical_speed": vertical_speed,
                "height_drop": height_drop,
                "x": float(target["pos_x"]),
                "y": float(target["pos_y"]),
                "z": float(target["pos_z"]),
                "target_height": float(target_heights.get(tid, 0.0)),
                "model_asset_used": self._model_asset_for_label(displayed_label),
                "model_scale": self._model_scale_for_label(displayed_label),
                "ground_z": self.ground_z,
                "vx": vx,
                "vy": vy,
                "vz": vz,
                "frame": frame_num,
            }
            result.update(
                self.vitals_manager.update_eligibility(tid, result, frame_num)
            )
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
        self.display_history.pop(tid_int, None)
        self.display_state.pop(tid_int, None)
        self.raw_label_history.pop(tid_int, None)
        self.confidence_history.pop(tid_int, None)
        self.probability_history.pop(tid_int, None)
        self.position_history.pop(tid_int, None)
        self.velocity_history.pop(tid_int, None)
        self.vitals_manager.reset_tid(tid_int)

    def reset_all(self) -> None:
        features.reset_all()
        self.smoother.reset_all()
        self.last_seen_frame.clear()
        self.latest_results.clear()
        self.speed_history.clear()
        self.height_history.clear()
        self.display_history.clear()
        self.display_state.clear()
        self.raw_label_history.clear()
        self.confidence_history.clear()
        self.probability_history.clear()
        self.position_history.clear()
        self.velocity_history.clear()
        self.vitals_manager.reset_all()

    def get_3d_label_records(self, track_data=None, height_data=None) -> list[dict]:
        if not self.enable_3d_labels:
            return []

        track_positions = _track_position_by_tid(track_data)
        target_heights = _height_by_tid(height_data)
        records: list[dict] = []

        for tid in sorted(self.latest_results):
            pose = self.latest_results[tid]
            window_ready = bool(pose.get("window_ready", False))
            final_label = str(pose.get("displayed_label", pose.get("final_label", "")))
            confidence = float(
                pose.get("displayed_confidence", pose.get("final_confidence", 0.0))
            )

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
            z_label = self._label_z_for_pose(final_label, target_height)
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

    def get_3d_model_records(self, track_data=None, height_data=None) -> list[dict]:
        if not self.enable_human_models:
            return []

        track_positions = _track_position_by_tid(track_data)
        target_heights = _height_by_tid(height_data)
        records: list[dict] = []

        for tid in sorted(self.latest_results):
            pose = self.latest_results[tid]
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

            target_height = float(
                target_heights.get(tid, pose.get("target_height", 0.0)) or 0.0
            )
            displayed_label = str(pose.get("displayed_label", pose.get("final_label", "")))

            records.append(
                {
                    "tid": int(tid),
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                    "bottom_z": float(self.ground_z),
                    "ground_z": float(self.ground_z),
                    "height": float(target_height),
                    "target_height": float(target_height),
                    "final_label": displayed_label,
                    "displayed_label": displayed_label,
                    "candidate_label": str(pose.get("candidate_label", "")),
                    "final_confidence": float(pose.get("displayed_confidence", 0.0)),
                    "displayed_confidence": float(pose.get("displayed_confidence", 0.0)),
                    "confidence": float(pose.get("displayed_confidence", 0.0)),
                    "posture_ml": str(pose.get("smoothed_label", "")),
                    "motion_state": str(pose.get("motion_state", "")),
                    "quality": str(pose.get("quality", "OK")),
                    "window_ready": bool(pose.get("window_ready", False)),
                    "num_points": int(pose.get("num_points", 0) or 0),
                    "model_asset_used": self._model_asset_for_label(displayed_label),
                    "model_scale": self._model_scale_for_label(displayed_label),
                }
            )
        return records

    def _format_3d_label(self, tid: int, pose: dict, quality: str) -> str:
        final_label = str(pose.get("displayed_label", pose.get("final_label", "")))
        candidate_label = str(pose.get("candidate_label", final_label))
        confidence = float(
            pose.get("displayed_confidence", pose.get("final_confidence", 0.0))
        )
        confidence_percent = _percent_text(confidence)
        window_count = int(pose.get("window_count", pose.get("window_age", 0)) or 0)
        if final_label == "WARMUP" or not pose.get("window_ready", False):
            return self._append_vitals_label(
                f"{tid} | WARMUP {window_count}/8", pose
            )
        if final_label == "NO_POSE" or not pose.get("prediction_exists", False):
            return self._append_vitals_label(f"{tid} | NO POSE", pose)
        display_status = str(pose.get("display_status", ""))
        stability_count = int(pose.get("display_stability_count", 0) or 0)
        stability_required = int(
            pose.get("display_stability_required", self.display_stability_frames) or 1
        )
        if self.label_debug:
            fall_ok = str(bool(pose.get("fall_gate_passed", False))).lower()
            text = (
                f"{tid} | {final_label} {confidence_percent}%\n"
                f"Cand:{candidate_label} Stable:{stability_count}/{stability_required} "
                f"FallOK:{fall_ok} Q:{quality}"
            )
            return self._append_vitals_label(text, pose)
        if display_status == "PENDING" and candidate_label != final_label:
            text = (
                f"{tid} | {final_label} -> {candidate_label} "
                f"{confidence_percent}%"
            )
            if quality != "OK":
                text = f"{text} *"
            return self._append_vitals_label(text, pose)

        values = {
            "tid": tid,
            "final_label": final_label,
            "displayed_label": final_label,
            "candidate_label": candidate_label,
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
        return self._append_vitals_label(text, pose)

    def _append_vitals_label(self, text: str, pose: dict) -> str:
        if not self.vitals_labels:
            return text
        state = str(pose.get("vitals_state", "DISABLED"))
        breath = pose.get("breathing_rate_bpm")
        heart = pose.get("heart_rate_bpm")
        if state == "ACTIVE" and (breath is not None or heart is not None):
            parts = []
            if breath is not None:
                parts.append(f"BR {float(breath):.1f}")
            if heart is not None:
                parts.append(f"HR {float(heart):.1f}")
            return f"{text}\n{' '.join(parts)}"
        if state == "WAITING_FOR_SITTING":
            return f"{text}\nVitals: sit required"
        if state != "DISABLED":
            return f"{text}\nVitals: {state}"
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

    def _update_tuning_histories(
        self,
        *,
        tid: int,
        raw_label: str,
        confidence: float,
        probabilities: dict[str, float],
        position: tuple[float, float, float],
        velocity: tuple[float, float, float],
    ) -> None:
        tid_int = int(tid)
        self.raw_label_history[tid_int].append(str(raw_label).upper())
        self.confidence_history[tid_int].append(float(confidence or 0.0))
        self.probability_history[tid_int].append(dict(probabilities or {}))
        self.position_history[tid_int].append(tuple(float(value) for value in position))
        self.velocity_history[tid_int].append(tuple(float(value) for value in velocity))

    def _probability(self, probabilities: dict[str, float], label: str) -> float:
        try:
            return float((probabilities or {}).get(label, 0.0) or 0.0)
        except Exception:
            return 0.0

    def _recent_candidate_ratio(self, tid: int, label: str, frames: int) -> float:
        history = list(self.display_history.get(int(tid), []))[-max(1, int(frames)) :]
        if not history:
            return 0.0
        target = str(label).upper()
        count = sum(1 for item_label, _confidence in history if item_label == target)
        return float(count) / float(len(history))

    def _evaluate_sitting_gate(
        self,
        *,
        smoothed_label: str,
        smoothed_confidence: float,
        probabilities: dict[str, float],
        horizontal_speed: float,
    ) -> tuple[bool, str]:
        label = str(smoothed_label).upper()
        sitting_prob = self._probability(probabilities, "SITTING")
        standing_prob = self._probability(probabilities, "STANDING")
        confidence = max(float(smoothed_confidence or 0.0), sitting_prob)
        if horizontal_speed > self.sitting_max_speed:
            return False, "speed_high"
        if label == "SITTING" and confidence >= self.sitting_min_confidence:
            return True, "sitting_top"
        if (
            sitting_prob >= self.sitting_min_confidence
            and sitting_prob >= standing_prob - 0.12
        ):
            return True, "sitting_close_to_standing"
        return False, "insufficient_sitting_probability"

    def _evaluate_fall_gate(
        self,
        *,
        tid: int,
        smoothed_label: str,
        smoothed_confidence: float,
        probabilities: dict[str, float],
        height_drop: float,
        vertical_speed: float,
    ) -> tuple[bool, str]:
        label = str(smoothed_label).upper()
        if label != "FALLING":
            return False, "ml_not_falling"

        confidence = float(smoothed_confidence or 0.0)
        strong_drop = height_drop >= self.fall_height_drop_threshold
        fast_vertical = vertical_speed >= self.fall_vertical_speed_threshold
        high_conf_with_drop = (
            confidence >= self.fall_high_confidence
            and height_drop >= self.fall_min_height_drop_with_high_confidence
        )

        sitting_prob = self._probability(probabilities, "SITTING")
        recent_sitting = self._recent_candidate_ratio(
            tid, "SITTING", self.display_stability_frames
        )
        previous = self.display_state.get(int(tid), {})
        previous_label = str(previous.get("label", "")).upper()
        if (
            not strong_drop
            and (sitting_prob >= self.sitting_min_confidence or recent_sitting >= 0.25)
        ):
            return False, "slow_sit_guard"
        if previous_label == "SITTING" and not strong_drop:
            return False, "stable_sitting_guard"

        if strong_drop:
            return True, "height_drop"
        if fast_vertical:
            return True, "vertical_speed"
        if high_conf_with_drop:
            return True, "high_confidence_with_mild_drop"
        return False, "no_physical_fall_evidence"

    def _final_label(
        self,
        *,
        window_ready: bool,
        prediction_exists: bool,
        smoothed_label: str,
        smoothed_confidence: float,
        motion_state: str,
        height_drop: float,
        horizontal_speed: float,
        vertical_speed: float,
        probabilities: dict[str, float],
        fall_gate_passed: bool,
        sitting_gate_passed: bool,
    ) -> str:
        if not window_ready:
            return "WARMUP"
        if not prediction_exists:
            return "NO_POSE"
        if smoothed_confidence < self.unknown_confidence:
            return "UNKNOWN"

        label = str(smoothed_label).upper()
        if label == "FALLING":
            if fall_gate_passed:
                return "FALLING"
            if sitting_gate_passed:
                return "SITTING"
            return "UNKNOWN"
        if label == "LYING":
            return "LYING"
        if label == "SITTING":
            if sitting_gate_passed:
                return "SITTING"
            if motion_state == "MOVING":
                return "MOVING"
            return "SITTING"
        if label == "WALKING":
            return "MOVING" if motion_state == "MOVING" else "WALKING"
        if label == "STANDING" and motion_state == "MOVING":
            return "MOVING"
        if label == "STANDING":
            return "STANDING"
        return label if label in self.class_names else "UNKNOWN"

    def _display_requirements(self, candidate_label: str) -> tuple[int, float, float]:
        label = str(candidate_label).upper()
        if label == "SITTING":
            return (
                self.sitting_stability_frames,
                self.sitting_stability_ratio,
                self.sitting_min_confidence,
            )
        if label == "STANDING":
            return (
                min(12, self.display_stability_frames),
                self.display_stability_ratio,
                self.standing_min_confidence,
            )
        if label == "LYING":
            return (
                min(10, self.display_stability_frames),
                0.60,
                self.lying_min_confidence,
            )
        if label == "FALLING":
            required = (
                self.fall_stability_frames
                if self.falling_fast_update
                else self.display_stability_frames
            )
            return required, self.display_stability_ratio, self.display_min_confidence
        if label == "MOVING":
            return self.moving_confirm_frames, self.display_stability_ratio, 0.0
        return self.display_stability_frames, self.display_stability_ratio, 0.0

    def _update_display_state(
        self,
        *,
        tid: int,
        candidate_label: str,
        candidate_confidence: float,
        window_ready: bool,
        prediction_exists: bool,
        horizontal_speed: float,
        fall_gate_passed: bool,
        fall_gate_reason: str,
        sitting_gate_passed: bool,
        sitting_gate_reason: str,
    ) -> dict[str, Any]:
        candidate = str(candidate_label or "UNKNOWN").upper()
        confidence = float(candidate_confidence or 0.0)

        if not window_ready:
            self.display_history.pop(int(tid), None)
            self.display_state.pop(int(tid), None)
            return {
                "displayed_label": "WARMUP",
                "displayed_confidence": 0.0,
                "display_stability_count": 0,
                "display_stability_required": self.display_stability_frames,
                "display_stability_ratio": 0.0,
                "display_status": "WARMUP",
                "transition_reason": "warming_up",
            }

        if not prediction_exists:
            return {
                "displayed_label": "NO_POSE",
                "displayed_confidence": 0.0,
                "display_stability_count": 0,
                "display_stability_required": self.display_stability_frames,
                "display_stability_ratio": 0.0,
                "display_status": "NO_POSE",
                "transition_reason": "no_prediction",
            }

        if not self.display_hysteresis:
            self.display_state[int(tid)] = {
                "label": candidate,
                "confidence": confidence,
            }
            return {
                "displayed_label": candidate,
                "displayed_confidence": confidence,
                "display_stability_count": 1,
                "display_stability_required": 1,
                "display_stability_ratio": 1.0,
                "display_status": "STABLE",
                "transition_reason": "hysteresis_disabled",
            }

        history = self.display_history[int(tid)]
        history.append((candidate, confidence))

        required, required_ratio, min_confidence = self._display_requirements(candidate)
        required = max(1, int(required))
        window_len = max(required, self.display_stability_frames)
        recent = list(history)[-window_len:]
        labels = [label for label, _conf in recent]
        count = labels.count(candidate)
        ratio = float(count) / float(len(recent)) if recent else 0.0
        enough_samples = len(recent) >= required
        confidence_ok = confidence >= min_confidence
        gate_ok = True
        gate_reason = ""
        if candidate == "FALLING":
            gate_ok = bool(fall_gate_passed)
            gate_reason = fall_gate_reason
        elif candidate == "SITTING":
            gate_ok = bool(sitting_gate_passed)
            gate_reason = sitting_gate_reason
        elif candidate == "MOVING" and horizontal_speed <= self.moving_speed_threshold:
            gate_ok = False
            gate_reason = "speed_below_moving_threshold"

        candidate_stable = (
            gate_ok
            and confidence_ok
            and enough_samples
            and (count >= required or ratio >= required_ratio)
        )

        previous = self.display_state.get(int(tid))
        if candidate_stable:
            self.display_state[int(tid)] = {
                "label": candidate,
                "confidence": confidence,
            }
            displayed_label = candidate
            displayed_confidence = confidence
            status = "STABLE"
            transition_reason = "stable_update"
        elif previous is None:
            displayed_label = candidate
            displayed_confidence = confidence
            status = "PENDING"
            if not gate_ok:
                transition_reason = f"gate_blocked:{gate_reason}"
            elif not confidence_ok:
                transition_reason = "confidence_below_min"
            else:
                transition_reason = "pending_start"
        else:
            displayed_label = str(previous.get("label", candidate))
            displayed_confidence = float(previous.get("confidence", confidence) or 0.0)
            status = "PENDING" if candidate != displayed_label else "STABLE"
            if not gate_ok:
                transition_reason = f"gate_blocked:{gate_reason}"
            elif not confidence_ok:
                transition_reason = "confidence_below_min"
            elif not enough_samples:
                transition_reason = "waiting_for_samples"
            elif count < required and ratio < required_ratio:
                transition_reason = "waiting_for_stability"
            else:
                transition_reason = "keep_previous"

        return {
            "displayed_label": displayed_label,
            "displayed_confidence": displayed_confidence,
            "display_stability_count": count,
            "display_stability_required": required,
            "display_stability_ratio": ratio,
            "display_status": status,
            "transition_reason": transition_reason,
        }

    def _label_z_for_pose(self, final_label: str, target_height: float) -> float:
        label = str(final_label).upper()
        if label in {"SITTING"}:
            top = self.human_model_target_sitting_height
        elif label in {"LYING", "FALLING"}:
            top = 0.50
        else:
            top = self.human_model_target_height
        if target_height > 0 and label not in {"LYING", "FALLING"}:
            top = max(top, float(target_height))
        return float(self.ground_z + top + self.label_z_offset)

    def _model_asset_for_label(self, final_label: str) -> str:
        label = str(final_label).upper()
        if label == "SITTING":
            return "human_sitting.obj"
        if label in {"LYING", "FALLING"}:
            return "human_lying.obj"
        return "human_standing.obj"

    def _model_scale_for_label(self, final_label: str) -> float:
        label = str(final_label).upper()
        if label == "SITTING":
            return self.human_model_target_sitting_height
        if label in {"LYING", "FALLING"}:
            return self.human_model_target_lying_length
        return self.human_model_target_height

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
                f"cand={item.get('candidate_label', item['final_label'])} "
                f"display={item.get('displayed_label', item['final_label'])} "
                f"stable={item.get('display_stability_count', 0)}/"
                f"{item.get('display_stability_required', self.display_stability_frames)} "
                f"status={item.get('display_status', '')} "
                f"fall={item.get('fall_gate_passed', False)}:"
                f"{item.get('fall_gate_reason', '')} "
                f"sit={item.get('sitting_gate_passed', False)}:"
                f"{item.get('sitting_gate_reason', '')} "
                f"reason={item.get('transition_reason', '')} "
                f"quality={item['quality']}",
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
            "ml_top_label",
            "ml_top_confidence",
            "candidate_label",
            "candidate_confidence",
            "final_label",
            "final_confidence",
            "displayed_label",
            "displayed_confidence",
            "display_stability_count",
            "display_stability_required",
            "display_stability_ratio",
            "display_status",
            "transition_reason",
            "fall_gate_passed",
            "fall_gate_reason",
            "sitting_gate_passed",
            "sitting_gate_reason",
            "stability_count",
            "stability_required",
            "stability_ratio",
            "motion_state",
            "pose_confidence",
            "sitting_stable_count",
            "vitals_eligible",
            "vitals_state",
            "vitals_state_reason",
            "vitals_source_id",
            "mapped_tid",
            "rangeBin",
            "breathRate",
            "heartRate",
            "breathDeviation",
            "vitals_mapping_mode",
            "breathing_rate_bpm",
            "heart_rate_bpm",
            "vitals_quality",
            "vitals_source",
            "vitals_elapsed_sec",
            "model_asset_used",
            "model_scale",
            "ground_z",
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
            "fall_vertical_speed_threshold": self.fall_vertical_speed_threshold,
            "fall_high_confidence": self.fall_high_confidence,
            "fall_min_height_drop_with_high_confidence": (
                self.fall_min_height_drop_with_high_confidence
            ),
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
            "display_stability_frames": self.display_stability_frames,
            "display_min_confidence": self.display_min_confidence,
            "display_hysteresis": self.display_hysteresis,
            "display_stability_ratio": self.display_stability_ratio,
            "falling_fast_update": self.falling_fast_update,
            "falling_stability_frames": self.falling_stability_frames,
            "fall_stability_frames": self.fall_stability_frames,
            "sitting_stability_frames": self.sitting_stability_frames,
            "sitting_stability_ratio": self.sitting_stability_ratio,
            "sitting_min_confidence": self.sitting_min_confidence,
            "sitting_max_speed": self.sitting_max_speed,
            "standing_min_confidence": self.standing_min_confidence,
            "lying_min_confidence": self.lying_min_confidence,
            "ground_z": self.ground_z,
            "human_model_target_height": self.human_model_target_height,
            "human_model_target_sitting_height": self.human_model_target_sitting_height,
            "human_model_target_lying_length": self.human_model_target_lying_length,
            "vitals_gate_enabled": self.vitals_manager.gate.enabled,
            "vitals_required_posture": self.vitals_manager.gate.required_posture,
            "vitals_sitting_stable_frames": (
                self.vitals_manager.gate.sitting_stable_frames
            ),
            "vitals_max_horizontal_speed": (
                self.vitals_manager.gate.max_horizontal_speed
            ),
            "vitals_min_pose_confidence": (
                self.vitals_manager.gate.min_pose_confidence
            ),
            "vitals_grace_frames": self.vitals_manager.gate.grace_frames,
            "vitals_reset_when_not_sitting": (
                self.vitals_manager.gate.reset_when_not_sitting
            ),
            "normalization_enabled": bool(getattr(self.model, "normalization_enabled", False)),
            "scaler_path": str(getattr(self.model, "scaler_path", "") or ""),
            "date_time": datetime.now().isoformat(timespec="seconds"),
            "notes": (
                "Model was trained on TI IWRL6432 Pose/Fall data. "
                "Live IWR6843 accuracy must be validated. MOVING is derived "
                "from speed, not from the ML class output. Vital rates are "
                "never synthesized; they remain empty unless a real TI vital "
                "sign TLV is present."
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
                    "ml_top_label": item.get("ml_top_label", item["smoothed_label"]),
                    "ml_top_confidence": item.get(
                        "ml_top_confidence", item["smoothed_confidence"]
                    ),
                    "candidate_label": item.get("candidate_label", ""),
                    "candidate_confidence": item.get("candidate_confidence", 0.0),
                    "final_label": item["final_label"],
                    "final_confidence": item.get("final_confidence", 0.0),
                    "displayed_label": item.get("displayed_label", item.get("final_label", "")),
                    "displayed_confidence": item.get("displayed_confidence", item.get("final_confidence", 0.0)),
                    "display_stability_count": item.get("display_stability_count", 0),
                    "display_stability_required": item.get("display_stability_required", self.display_stability_frames),
                    "display_stability_ratio": item.get("display_stability_ratio", 0.0),
                    "display_status": item.get("display_status", ""),
                    "transition_reason": item.get("transition_reason", ""),
                    "fall_gate_passed": item.get("fall_gate_passed", False),
                    "fall_gate_reason": item.get("fall_gate_reason", ""),
                    "sitting_gate_passed": item.get("sitting_gate_passed", False),
                    "sitting_gate_reason": item.get("sitting_gate_reason", ""),
                    "stability_count": item.get("stability_count", item.get("display_stability_count", 0)),
                    "stability_required": item.get("stability_required", item.get("display_stability_required", self.display_stability_frames)),
                    "stability_ratio": item.get("stability_ratio", item.get("display_stability_ratio", 0.0)),
                    "motion_state": item["motion_state"],
                    "pose_confidence": item.get(
                        "displayed_confidence", item.get("final_confidence", 0.0)
                    ),
                    "sitting_stable_count": item.get("sitting_stable_count", 0),
                    "vitals_eligible": item.get("vitals_eligible", False),
                    "vitals_state": item.get("vitals_state", "DISABLED"),
                    "vitals_state_reason": item.get("vitals_state_reason", ""),
                    "vitals_source_id": item.get("vitals_source_id", ""),
                    "mapped_tid": item.get("mapped_tid", item.get("tid", "")),
                    "rangeBin": item.get("rangeBin", ""),
                    "breathRate": item.get("breathRate", ""),
                    "heartRate": item.get("heartRate", ""),
                    "breathDeviation": item.get("breathDeviation", ""),
                    "vitals_mapping_mode": item.get(
                        "vitals_mapping_mode", "id_equals_tid"
                    ),
                    "breathing_rate_bpm": item.get("breathing_rate_bpm", ""),
                    "heart_rate_bpm": item.get("heart_rate_bpm", ""),
                    "vitals_quality": item.get("vitals_quality", ""),
                    "vitals_source": item.get("vitals_source", ""),
                    "vitals_elapsed_sec": item.get("vitals_elapsed_sec", 0.0),
                    "model_asset_used": item.get("model_asset_used", ""),
                    "model_scale": item.get("model_scale", ""),
                    "ground_z": item.get("ground_z", self.ground_z),
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
