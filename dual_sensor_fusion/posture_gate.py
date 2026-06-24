from __future__ import annotations

from dataclasses import dataclass

from .fusion_types import IwrTarget


MONITORING = "MONITORING"
MONITORING_POSE_GRACE = "MONITORING_POSE_GRACE"
SEATED_LOCK = "SEATED_LOCK"
WAITING_FOR_SITTING = "WAITING_FOR_SITTING"
POSTURE_UNSTABLE = "POSTURE_UNSTABLE"
PAUSED_NOT_SITTING = "PAUSED_NOT_SITTING"
NO_TARGET = "NO_TARGET"
TARGET_LOST = "TARGET_LOST"


@dataclass(frozen=True)
class SittingGateConfig:
    requiredPosture: str = "SITTING"
    requiredStableFrames: int = 10
    allowUnknown: bool = False
    pauseOnMoving: bool = True
    pauseOnFalling: bool = True
    maxStableSpeed: float = 0.25
    nonSittingGraceSec: float = 3.0
    updateRateHz: float = 10.0
    sittingLockSec: float = 5.0
    allowStandingGrace: bool = True
    graceLabels: tuple[str, ...] = ("MOVING", "UNKNOWN", "STANDING")
    hardPauseLabels: tuple[str, ...] = ("LYING", "FALLING")
    requireStableBeforeGrace: bool = True
    pauseImmediatelyOnFalling: bool = True
    pauseImmediatelyOnLying: bool = True
    pauseImmediatelyOnHighMotion: bool = True
    maxGraceSpeedMps: float = 0.25
    pauseOnBinSwitchDuringGrace: bool = True
    maxAllowedBinJumpDuringGrace: int = 2
    enablePoseGrace: bool = True

    @property
    def maxGraceFrames(self) -> int:
        return max(0, int(round(self.nonSittingGraceSec * self.updateRateHz)))

    @property
    def sittingLockFrames(self) -> int:
        return max(0, int(round(self.sittingLockSec * self.updateRateHz)))


@dataclass(frozen=True)
class GateDecision:
    state: str
    allowed: bool
    stableFrames: int
    reason: str
    poseGraceActive: bool = False
    nonSittingStreakSec: float = 0.0
    graceRemainingSec: float = 0.0
    lastStablePosture: str = "UNKNOWN"


@dataclass
class _TargetGateState:
    stable_frames: int = 0
    last_posture: str = "UNKNOWN"
    seen: bool = False
    was_monitoring: bool = False
    non_sitting_frames: int = 0
    last_selected_bin: int | None = None
    last_stable_posture: str = "UNKNOWN"
    monitoring_frames: int = 0


class SittingGate:
    def __init__(self, config: SittingGateConfig | None = None):
        self.config = config or SittingGateConfig()
        if self.config.requiredStableFrames < 1:
            raise ValueError("requiredStableFrames must be at least 1")
        if self.config.nonSittingGraceSec < 0:
            raise ValueError("nonSittingGraceSec cannot be negative")
        if self.config.updateRateHz <= 0:
            raise ValueError("updateRateHz must be positive")
        if self.config.sittingLockSec < 0:
            raise ValueError("sittingLockSec cannot be negative")
        if self.config.maxAllowedBinJumpDuringGrace < 0:
            raise ValueError("maxAllowedBinJumpDuringGrace cannot be negative")
        self._targets: dict[int, _TargetGateState] = {}

    def update(
        self,
        target: IwrTarget | None,
        target_id: int | None = None,
        selected_bin: int | None = None,
    ) -> GateDecision:
        if target is None:
            if target_id is None:
                return GateDecision(NO_TARGET, False, 0, "no IWR target")
            prior = self._targets.get(int(target_id))
            if prior is None or not prior.seen:
                return GateDecision(NO_TARGET, False, 0, "no IWR target")
            prior.stable_frames = 0
            prior.was_monitoring = False
            prior.non_sitting_frames = 0
            prior.monitoring_frames = 0
            return GateDecision(
                TARGET_LOST,
                False,
                0,
                "previous target is no longer present",
                lastStablePosture=prior.last_stable_posture,
            )

        tid = int(target.targetId)
        if tid < 0:
            return GateDecision(NO_TARGET, False, 0, "invalid negative target ID")
        state = self._targets.setdefault(tid, _TargetGateState())
        posture = (target.posture or "UNKNOWN").strip().upper()
        required = self.config.requiredPosture.strip().upper()
        state.seen = True
        state.last_posture = posture

        if posture == required:
            if state.was_monitoring:
                state.stable_frames = max(
                    self.config.requiredStableFrames,
                    state.stable_frames + 1,
                )
                state.monitoring_frames += 1
            else:
                state.stable_frames += 1
            state.non_sitting_frames = 0
            state.last_stable_posture = required
            self._remember_bin(state, selected_bin)

            speed_reason = self._high_motion_reason(target, self.config.maxStableSpeed)
            if speed_reason:
                state.stable_frames = 0
                state.was_monitoring = False
                state.monitoring_frames = 0
                return self._decision(state, POSTURE_UNSTABLE, False, speed_reason)

            if state.stable_frames >= self.config.requiredStableFrames:
                if not state.was_monitoring:
                    state.monitoring_frames = 1
                state.was_monitoring = True
                if (
                    self.config.sittingLockFrames > 0
                    and state.monitoring_frames <= self.config.sittingLockFrames
                ):
                    return self._decision(
                        state,
                        SEATED_LOCK,
                        True,
                        (
                            f"{required} accepted; seated lock "
                            f"{state.monitoring_frames / self.config.updateRateHz:.1f}/"
                            f"{self.config.sittingLockSec:.1f}s"
                        ),
                    )
                return self._decision(
                    state,
                    MONITORING,
                    True,
                    f"{required} stable for {state.stable_frames} frame(s)",
                )
            state.was_monitoring = False
            state.monitoring_frames = 0
            return self._decision(
                state,
                WAITING_FOR_SITTING,
                False,
                f"waiting for {self.config.requiredStableFrames} stable {required} frames",
            )

        state.non_sitting_frames += 1
        streak_sec = state.non_sitting_frames / self.config.updateRateHz

        if self._is_hard_pause(posture):
            return self._pause(
                state,
                PAUSED_NOT_SITTING,
                f"posture {posture} requires an immediate pause",
            )

        speed_reason = self._high_motion_reason(target, self.config.maxGraceSpeedMps)
        if self.config.pauseImmediatelyOnHighMotion and speed_reason:
            return self._pause(state, POSTURE_UNSTABLE, speed_reason)

        bin_reason = self._grace_bin_reason(state, selected_bin)
        if bin_reason:
            return self._pause(state, POSTURE_UNSTABLE, bin_reason)

        grace_labels = {label.strip().upper() for label in self.config.graceLabels}
        if not self.config.allowStandingGrace:
            grace_labels.discard("STANDING")
        monitoring_eligible = (
            state.was_monitoring
            or not self.config.requireStableBeforeGrace
        )
        if not self.config.enablePoseGrace:
            if posture == "MOVING" and self.config.pauseOnMoving:
                return self._pause(
                    state,
                    POSTURE_UNSTABLE,
                    "target posture is MOVING and pose grace is disabled",
                )
            if posture in {"UNKNOWN", "WARMUP", ""} and not self.config.allowUnknown:
                return self._pause(
                    state,
                    POSTURE_UNSTABLE,
                    f"posture is {posture or 'UNKNOWN'} and pose grace is disabled",
                )
        elif not monitoring_eligible:
            if posture == "MOVING" and self.config.pauseOnMoving:
                return self._pause(
                    state,
                    POSTURE_UNSTABLE,
                    "target posture is MOVING before stable sitting",
                )
            if posture in {"UNKNOWN", "WARMUP", ""} and not self.config.allowUnknown:
                return self._pause(
                    state,
                    POSTURE_UNSTABLE,
                    f"posture is {posture or 'UNKNOWN'} before stable sitting",
                )
        within_grace = state.non_sitting_frames <= self.config.maxGraceFrames
        if (
            self.config.enablePoseGrace
            and posture in grace_labels
            and monitoring_eligible
            and within_grace
        ):
            state.was_monitoring = True
            self._remember_bin(state, selected_bin)
            remaining = max(0.0, self.config.nonSittingGraceSec - streak_sec)
            return self._decision(
                state,
                MONITORING_POSE_GRACE,
                True,
                (
                    f"brief {posture} label tolerated for {streak_sec:.1f}s; "
                    f"{remaining:.1f}s grace remaining"
                ),
                pose_grace=True,
            )

        state.stable_frames = 0
        state.was_monitoring = False
        state.monitoring_frames = 0
        state.last_selected_bin = selected_bin
        reason = (
            f"posture {posture} exceeded {self.config.nonSittingGraceSec:.1f}s grace"
            if posture in grace_labels and state.non_sitting_frames > self.config.maxGraceFrames
            else f"posture is {posture}, required posture is {required}"
        )
        return self._decision(
            state,
            PAUSED_NOT_SITTING,
            False,
            reason,
        )

    def _is_hard_pause(self, posture: str) -> bool:
        hard_labels = {label.strip().upper() for label in self.config.hardPauseLabels}
        hard_labels.discard("FALLING")
        hard_labels.discard("LYING")
        if posture == "FALLING":
            return self.config.pauseImmediatelyOnFalling
        if posture == "LYING":
            return self.config.pauseImmediatelyOnLying
        return posture in hard_labels

    @staticmethod
    def _high_motion_reason(target: IwrTarget, threshold: float) -> str | None:
        if target.speed is not None and target.speed > threshold:
            return (
                f"target speed {target.speed:.3f} m/s exceeds "
                f"{threshold:.3f} m/s"
            )
        return None

    def _grace_bin_reason(
        self,
        state: _TargetGateState,
        selected_bin: int | None,
    ) -> str | None:
        if (
            not self.config.pauseOnBinSwitchDuringGrace
            or selected_bin is None
            or state.last_selected_bin is None
        ):
            return None
        jump = abs(int(selected_bin) - int(state.last_selected_bin))
        if jump > self.config.maxAllowedBinJumpDuringGrace:
            return (
                f"selected AWR bin jumped by {jump}, exceeding grace limit "
                f"{self.config.maxAllowedBinJumpDuringGrace}"
            )
        return None

    @staticmethod
    def _remember_bin(state: _TargetGateState, selected_bin: int | None) -> None:
        if selected_bin is not None:
            state.last_selected_bin = int(selected_bin)

    def _pause(
        self,
        state: _TargetGateState,
        monitoring_state: str,
        reason: str,
    ) -> GateDecision:
        state.stable_frames = 0
        state.was_monitoring = False
        state.monitoring_frames = 0
        return self._decision(state, monitoring_state, False, reason)

    def _decision(
        self,
        state: _TargetGateState,
        monitoring_state: str,
        allowed: bool,
        reason: str,
        pose_grace: bool = False,
    ) -> GateDecision:
        streak_sec = state.non_sitting_frames / self.config.updateRateHz
        remaining = (
            max(0.0, self.config.nonSittingGraceSec - streak_sec)
            if pose_grace
            else 0.0
        )
        return GateDecision(
            state=monitoring_state,
            allowed=allowed,
            stableFrames=state.stable_frames,
            reason=reason,
            poseGraceActive=pose_grace,
            nonSittingStreakSec=streak_sec,
            graceRemainingSec=remaining,
            lastStablePosture=state.last_stable_posture,
        )
