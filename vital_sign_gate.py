"""Per-target posture and motion gate for vital-sign monitoring."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass
class _GateState:
    sitting_stable_count: int = 0
    violation_count: int = 0
    was_eligible: bool = False
    eligible_since: float | None = None
    last_seen_frame: int = 0


class VitalSignGate:
    """Allow vitals only for a continuously tracked, stable sitting target."""

    def __init__(
        self,
        enabled: bool = False,
        required_posture: str = "SITTING",
        sitting_stable_frames: int = 30,
        max_horizontal_speed: float = 0.08,
        min_pose_confidence: float = 0.60,
        grace_frames: int = 15,
        reset_when_not_sitting: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.required_posture = str(required_posture).upper()
        self.sitting_stable_frames = max(1, int(sitting_stable_frames))
        self.max_horizontal_speed = max(0.0, float(max_horizontal_speed))
        self.min_pose_confidence = max(0.0, float(min_pose_confidence))
        self.grace_frames = max(0, int(grace_frames))
        self.reset_when_not_sitting = bool(reset_when_not_sitting)
        self._states: dict[int, _GateState] = {}

    def update(
        self,
        tid: int,
        pose_state: dict[str, Any],
        frame_num: int,
        measurement_available: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        tid = int(tid)
        state = self._states.setdefault(tid, _GateState())
        state.last_seen_frame = int(frame_num)
        now = time.monotonic() if now is None else float(now)

        if not self.enabled:
            return self._result(state, "DISABLED", "vitals gate disabled", False, now)

        label = str(
            pose_state.get("displayed_label", pose_state.get("final_label", ""))
        ).upper()
        confidence = float(
            pose_state.get(
                "displayed_confidence", pose_state.get("final_confidence", 0.0)
            )
            or 0.0
        )
        speed = float(pose_state.get("horizontal_speed", 0.0) or 0.0)
        quality = str(pose_state.get("quality", "OK")).upper()
        target_ready = bool(pose_state.get("window_ready", False))

        posture_ok = label == self.required_posture
        confidence_ok = confidence >= self.min_pose_confidence
        speed_ok = speed <= self.max_horizontal_speed
        quality_ok = quality not in {"NO_POINTS", "LOW_CONF", "WARMUP"}

        if posture_ok and confidence_ok and speed_ok and quality_ok and target_ready:
            state.sitting_stable_count += 1
            state.violation_count = 0
        else:
            state.violation_count += 1
            if self.reset_when_not_sitting and state.violation_count > self.grace_frames:
                state.sitting_stable_count = 0
                state.was_eligible = False
                state.eligible_since = None

        stable = state.sitting_stable_count >= self.sitting_stable_frames
        if stable and posture_ok and confidence_ok and speed_ok and quality_ok:
            if state.eligible_since is None:
                state.eligible_since = now
            state.was_eligible = True
            if measurement_available:
                return self._result(state, "ACTIVE", "vital TLV available", True, now)
            return self._result(
                state, "ELIGIBLE_NO_DATA", "stable sitting; no vital TLV", True, now
            )

        if label in {"MOVING", "FALLING"} or not speed_ok:
            state_name = "PAUSED_MOVING" if state.was_eligible else "WAITING_FOR_SITTING"
            reason = (
                f"horizontal speed {speed:.3f} exceeds "
                f"{self.max_horizontal_speed:.3f}"
            )
        elif not posture_ok:
            state_name = (
                "PAUSED_NOT_SITTING" if state.was_eligible else "WAITING_FOR_SITTING"
            )
            reason = f"requires {self.required_posture}; displayed pose is {label or 'NONE'}"
        elif not target_ready:
            state_name = "WAITING_FOR_STABLE_SITTING"
            reason = "pose window is not ready"
        elif not confidence_ok:
            state_name = "WAITING_FOR_STABLE_SITTING"
            reason = (
                f"pose confidence {confidence:.3f} below "
                f"{self.min_pose_confidence:.3f}"
            )
        elif not quality_ok:
            state_name = "WAITING_FOR_STABLE_SITTING"
            reason = f"pose quality {quality}"
        else:
            state_name = "WAITING_FOR_STABLE_SITTING"
            reason = (
                f"stable sitting {state.sitting_stable_count}/"
                f"{self.sitting_stable_frames}"
            )

        return self._result(state, state_name, reason, False, now)

    def mark_lost(self, tid: int) -> dict[str, Any]:
        state = self._states.get(int(tid), _GateState())
        return self._result(state, "LOST_TARGET", "target is no longer tracked", False)

    def reset_tid(self, tid: int) -> None:
        self._states.pop(int(tid), None)

    def reset_all(self) -> None:
        self._states.clear()

    def _result(
        self,
        state: _GateState,
        state_name: str,
        reason: str,
        eligible: bool,
        now: float | None = None,
    ) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        elapsed = (
            0.0
            if state.eligible_since is None
            else max(0.0, float(now) - state.eligible_since)
        )
        return {
            "vitals_eligible": bool(eligible),
            "vitals_state": state_name,
            "vitals_state_reason": reason,
            "sitting_stable_count": int(state.sitting_stable_count),
            "vitals_required_sitting_frames": self.sitting_stable_frames,
            "vitals_elapsed_sec": elapsed,
        }
