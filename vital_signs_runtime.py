"""Runtime bridge for TI vital-sign TLVs and posture-gated UI state.

No values are synthesized. When TLV 1040 is absent, eligible targets report
``ELIGIBLE_NO_DATA`` and retain empty breathing/heart measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np

from vital_sign_gate import VitalSignGate


@dataclass
class VitalSignsMeasurement:
    tid: int
    vitals_source_id: int | None = None
    mapped_tid: int | None = None
    mapping_mode: str = "id_equals_tid"
    range_bin: int | None = None
    breath_deviation: float | None = None
    breathing_rate_bpm: float | None = None
    heart_rate_bpm: float | None = None
    breathing_confidence: float | None = None
    heart_confidence: float | None = None
    quality: str = "NO_VITAL_TLV"
    timestamp: float = 0.0
    source: str = ""


class VitalSignsManager:
    def __init__(
        self,
        enabled: bool = False,
        required_posture: str = "SITTING",
        sitting_stable_frames: int = 30,
        max_horizontal_speed: float = 0.08,
        min_pose_confidence: float = 0.60,
        grace_frames: int = 15,
        reset_when_not_sitting: bool = True,
        debug: bool = False,
    ) -> None:
        self.gate = VitalSignGate(
            enabled=enabled,
            required_posture=required_posture,
            sitting_stable_frames=sitting_stable_frames,
            max_horizontal_speed=max_horizontal_speed,
            min_pose_confidence=min_pose_confidence,
            grace_frames=grace_frames,
            reset_when_not_sitting=reset_when_not_sitting,
        )
        self.enabled = bool(enabled)
        self.grace_frames = max(0, int(grace_frames))
        self.debug = bool(debug)
        self._measurements: dict[int, VitalSignsMeasurement] = {}
        self._measurement_frames: dict[int, int] = {}
        self._records: dict[int, dict[str, Any]] = {}
        self._frame_num = 0

    def update_from_frame(self, output_dict: dict[str, Any] | None) -> None:
        if not isinstance(output_dict, dict):
            return
        frame_value = output_dict.get("frameNum")
        if frame_value is not None:
            self._frame_num = int(frame_value)
        payload = output_dict.get("vitals")
        if payload is None:
            return

        for item in _iter_vital_records(payload):
            source_id = _optional_int(
                _record_value(
                    item,
                    "id",
                    "tid",
                    "targetId",
                    "targetID",
                    "target_id",
                )
            )
            if source_id is None:
                continue

            # TI Vital Signs With People Tracking emits the tracker TID in id.
            # Keep the mapping explicit so a future selected-target mapping can
            # replace it without changing UI consumers.
            mapped_tid = source_id
            range_bin = _optional_int(
                _record_value(
                    item,
                    "rangeBin",
                    "range_bin",
                    "rangeBinIndexPhase",
                    "range_bin_index",
                )
            )
            breath = _finite_float(
                _record_value(
                    item,
                    "breathRate",
                    "breathingRate",
                    "breathing_rate_bpm",
                    "breath_rate",
                )
            )
            heart = _finite_float(
                _record_value(
                    item,
                    "heartRate",
                    "heart_rate_bpm",
                    "heart_rate",
                )
            )
            breath_deviation = _finite_float(
                _record_value(
                    item,
                    "breathDeviation",
                    "breath_deviation",
                    "breathingDeviation",
                )
            )
            quality = "OK" if _positive(breath) or _positive(heart) else "UPDATING"
            self._measurements[mapped_tid] = VitalSignsMeasurement(
                tid=mapped_tid,
                vitals_source_id=source_id,
                mapped_tid=mapped_tid,
                mapping_mode="id_equals_tid",
                range_bin=range_bin,
                breath_deviation=breath_deviation,
                breathing_rate_bpm=breath,
                heart_rate_bpm=heart,
                quality=quality,
                timestamp=time.time(),
                source="TI_TLV_1040",
            )
            self._measurement_frames[mapped_tid] = self._frame_num
            if self.debug:
                print(
                    "[vitals] "
                    f"source_id={source_id} mapped_tid={mapped_tid} "
                    f"mapping=id_equals_tid rangeBin={range_bin} "
                    f"BR={breath} HR={heart} dev={breath_deviation}",
                    flush=True,
                )

    def get_measurement_for_tid(self, tid: int) -> VitalSignsMeasurement | None:
        tid = int(tid)
        measurement = self._measurements.get(tid)
        last_frame = self._measurement_frames.get(tid)
        if measurement is None or last_frame is None:
            return None
        if self._frame_num - last_frame > self.grace_frames:
            return None
        return measurement

    def update_eligibility(
        self, tid: int, pose_state: dict[str, Any], frame_num: int
    ) -> dict[str, Any]:
        measurement = self.get_measurement_for_tid(tid)
        gate_result = self.gate.update(
            tid,
            pose_state,
            frame_num,
            measurement_available=measurement is not None,
        )
        record = {
            **gate_result,
            "breathing_rate_bpm": None,
            "heart_rate_bpm": None,
            "breathing_confidence": None,
            "heart_confidence": None,
            "vitals_source_id": (
                measurement.vitals_source_id if measurement is not None else None
            ),
            "mapped_tid": (
                measurement.mapped_tid if measurement is not None else int(tid)
            ),
            "vitals_mapping_mode": (
                measurement.mapping_mode
                if measurement is not None
                else "id_equals_tid"
            ),
            "rangeBin": measurement.range_bin if measurement is not None else None,
            "breathRate": (
                measurement.breathing_rate_bpm
                if measurement is not None
                else None
            ),
            "heartRate": (
                measurement.heart_rate_bpm if measurement is not None else None
            ),
            "breathDeviation": (
                measurement.breath_deviation if measurement is not None else None
            ),
            "vitals_quality": (
                "NO_VITAL_TLV"
                if gate_result["vitals_eligible"] and measurement is None
                else "-"
            ),
            "vitals_source": "",
        }
        if measurement is not None and gate_result["vitals_eligible"]:
            record.update(
                {
                    "breathing_rate_bpm": measurement.breathing_rate_bpm,
                    "heart_rate_bpm": measurement.heart_rate_bpm,
                    "breathing_confidence": measurement.breathing_confidence,
                    "heart_confidence": measurement.heart_confidence,
                    "vitals_quality": measurement.quality,
                    "vitals_source": measurement.source,
                }
            )
        self._records[int(tid)] = record
        return record

    def get_vitals_records(self) -> dict[int, dict[str, Any]]:
        return {tid: dict(record) for tid, record in self._records.items()}

    def reset_tid(self, tid: int) -> None:
        tid = int(tid)
        self.gate.reset_tid(tid)
        self._measurements.pop(tid, None)
        self._measurement_frames.pop(tid, None)
        self._records.pop(tid, None)

    def reset_all(self) -> None:
        self.gate.reset_all()
        self._measurements.clear()
        self._measurement_frames.clear()
        self._records.clear()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive(value: float | None) -> bool:
    return value is not None and value > 0.0


def _iter_vital_records(payload: Any):
    """Yield mapping-, object-, or NumPy-backed vital records."""
    if payload is None:
        return

    if isinstance(payload, dict):
        if _looks_like_vital_record(payload):
            yield payload
            return
        for value in payload.values():
            yield from _iter_vital_records(value)
        return

    if isinstance(payload, (list, tuple)):
        for value in payload:
            yield from _iter_vital_records(value)
        return

    if isinstance(payload, np.ndarray):
        if payload.dtype.names:
            for value in payload.reshape(-1):
                yield value
            return
        if payload.dtype == object:
            for value in payload.reshape(-1):
                yield from _iter_vital_records(value)
            return
        array = np.asarray(payload)
        if array.ndim == 1 and array.size >= 5:
            yield {
                "id": array[0],
                "rangeBin": array[1],
                "breathDeviation": array[2],
                "heartRate": array[3],
                "breathRate": array[4],
            }
            return
        if array.ndim >= 2:
            for row in array:
                yield from _iter_vital_records(np.asarray(row))
            return

    if isinstance(payload, np.void) or _looks_like_vital_record(payload):
        yield payload


def _looks_like_vital_record(record: Any) -> bool:
    return any(
        _record_value(record, name) is not None
        for name in (
            "id",
            "tid",
            "rangeBin",
            "breathRate",
            "heartRate",
            "breathDeviation",
        )
    )


def _record_value(record: Any, *names: str) -> Any:
    if record is None:
        return None

    if isinstance(record, dict):
        for name in names:
            if name in record and record[name] is not None:
                return record[name]
        lower_keys = {str(key).lower(): key for key in record}
        for name in names:
            key = lower_keys.get(name.lower())
            if key is not None and record[key] is not None:
                return record[key]
        return None

    dtype = getattr(record, "dtype", None)
    dtype_names = getattr(dtype, "names", None)
    if dtype_names:
        lower_names = {str(name).lower(): name for name in dtype_names}
        for name in names:
            field_name = lower_names.get(name.lower())
            if field_name is not None:
                value = record[field_name]
                if value is not None:
                    return value

    for name in names:
        if hasattr(record, name):
            value = getattr(record, name)
            if value is not None:
                return value
    lower_attrs = {name.lower(): name for name in dir(record)}
    for name in names:
        attr_name = lower_attrs.get(name.lower())
        if attr_name is not None:
            value = getattr(record, attr_name)
            if value is not None:
                return value
    return None
