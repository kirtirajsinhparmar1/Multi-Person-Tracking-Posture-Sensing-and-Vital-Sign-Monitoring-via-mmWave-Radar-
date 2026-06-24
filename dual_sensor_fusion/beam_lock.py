from __future__ import annotations

from dataclasses import dataclass
import math
import time

import numpy as np

from awr1642_vitals.phase_vitals.azimuth_beamforming import AzimuthBeamSelection


SEARCHING_BEAM = "SEARCHING_BEAM"
BEAM_CANDIDATE = "BEAM_CANDIDATE"
BEAM_LOCKED = "BEAM_LOCKED"
BEAM_HOLD = "BEAM_HOLD"
BEAM_LOST = "BEAM_LOST"


@dataclass(frozen=True)
class BeamLockConfig:
    lockSec: float = 2.0
    holdSec: float = 3.0
    switchMargin: float = 1.5
    switchConfirmSec: float = 2.0
    maxJumpBins: int = 1
    maxJumpDeg: float = 6.0
    enabled: bool = True


@dataclass
class BeamLockResult:
    state: str
    candidate: AzimuthBeamSelection | None
    locked: AzimuthBeamSelection | None
    lockAgeSec: float = 0.0
    switchCount: int = 0
    segmentId: int = 0
    reason: str = ""


@dataclass
class _TargetLock:
    candidate: AzimuthBeamSelection | None = None
    candidate_since: float | None = None
    locked_bin: int | None = None
    locked_azimuth: float | None = None
    locked_since: float | None = None
    last_valid_at: float | None = None
    switch_candidate: AzimuthBeamSelection | None = None
    switch_since: float | None = None
    switch_count: int = 0
    segment_id: int = 0


def _same_cell(
    left: AzimuthBeamSelection | None,
    right: AzimuthBeamSelection | None,
    config: BeamLockConfig,
) -> bool:
    if left is None or right is None:
        return False
    return (
        abs(left.selectedRangeBin - right.selectedRangeBin)
        <= config.maxJumpBins
        and abs(left.selectedAzimuthDeg - right.selectedAzimuthDeg)
        <= config.maxJumpDeg
    )


def _selection_at_locked_cell(
    candidate: AzimuthBeamSelection,
    range_bin: int,
    azimuth_deg: float,
    fe03_window,
) -> AzimuthBeamSelection | None:
    bins = np.asarray(fe03_window.bin_indices, dtype=np.int32)
    rows = np.flatnonzero(bins == int(range_bin))
    cols = np.flatnonzero(
        np.isclose(
            np.asarray(candidate.angleGridDeg, dtype=float),
            float(azimuth_deg),
            atol=1e-6,
        )
    )
    if rows.size == 0 or cols.size == 0:
        return None
    row, col = int(rows[0]), int(cols[0])
    value = complex(candidate.beamMap[row, col])
    return AzimuthBeamSelection(
        selectedRangeBin=int(range_bin),
        selectedRangeMeters=float(fe03_window.range_meters[row]),
        selectedAzimuthDeg=float(candidate.angleGridDeg[col]),
        selectedAzimuthBin=col,
        selectedComplex=value,
        selectedPhaseRad=float(np.angle(value)),
        selectedMagnitude=float(abs(value)),
        expectedRangeBin=candidate.expectedRangeBin,
        expectedAzimuthDeg=candidate.expectedAzimuthDeg,
        strongestOverallRangeBin=candidate.strongestOverallRangeBin,
        strongestOverallRangeMeters=candidate.strongestOverallRangeMeters,
        strongestOverallAzimuthDeg=candidate.strongestOverallAzimuthDeg,
        strongestOverallMagnitude=candidate.strongestOverallMagnitude,
        candidateRangeBins=candidate.candidateRangeBins,
        candidateAzimuthDeg=candidate.candidateAzimuthDeg,
        selectionReason="sampled persistent locked chest beam",
        angleGridDeg=candidate.angleGridDeg,
        beamMap=candidate.beamMap,
        selectedScore=candidate.selectedScore,
        selectionChanged=False,
    )


class BeamLockManager:
    """Separate a movable FE03 candidate from the phase-producing locked cell."""

    def __init__(self, config: BeamLockConfig | None = None):
        self.config = config or BeamLockConfig()
        self._targets: dict[int, _TargetLock] = {}

    def update(
        self,
        target_id: int,
        candidate: AzimuthBeamSelection | None,
        fe03_window=None,
        timestamp: float | None = None,
    ) -> BeamLockResult:
        now = time.time() if timestamp is None else float(timestamp)
        state = self._targets.setdefault(int(target_id), _TargetLock())
        cfg = self.config

        if candidate is None or fe03_window is None:
            if (
                state.locked_bin is not None
                and state.last_valid_at is not None
                and now - state.last_valid_at <= cfg.holdSec
            ):
                return BeamLockResult(
                    BEAM_HOLD,
                    None,
                    None,
                    self._lock_age(state, now),
                    state.switch_count,
                    state.segment_id,
                    "locked cell retained while FE03 sample is temporarily absent",
                )
            return BeamLockResult(
                BEAM_LOST,
                None,
                None,
                0.0,
                state.switch_count,
                state.segment_id,
                "no valid FE03 beam candidate",
            )

        if not cfg.enabled:
            changed = (
                state.locked_bin != candidate.selectedRangeBin
                or state.locked_azimuth != candidate.selectedAzimuthDeg
            )
            if changed:
                state.segment_id += 1
                state.switch_count += int(state.locked_bin is not None)
            state.locked_bin = candidate.selectedRangeBin
            state.locked_azimuth = candidate.selectedAzimuthDeg
            state.locked_since = now
            state.last_valid_at = now
            return BeamLockResult(
                BEAM_LOCKED,
                candidate,
                candidate,
                0.0,
                state.switch_count,
                state.segment_id,
                "beam lock disabled; raw candidate used",
            )

        if state.locked_bin is None:
            if not _same_cell(state.candidate, candidate, cfg):
                state.candidate = candidate
                state.candidate_since = now
            candidate_since = (
                now if state.candidate_since is None else state.candidate_since
            )
            stable_for = max(0.0, now - candidate_since)
            if stable_for < cfg.lockSec:
                return BeamLockResult(
                    BEAM_CANDIDATE,
                    candidate,
                    None,
                    0.0,
                    state.switch_count,
                    state.segment_id,
                    f"candidate stable for {stable_for:.2f}/{cfg.lockSec:.2f}s",
                )
            self._lock(state, candidate, now, switched=False)

        locked = _selection_at_locked_cell(
            candidate,
            int(state.locked_bin),
            float(state.locked_azimuth),
            fe03_window,
        )
        if locked is None:
            return BeamLockResult(
                BEAM_HOLD,
                candidate,
                None,
                self._lock_age(state, now),
                state.switch_count,
                state.segment_id,
                "locked cell is outside the current FE03 window",
            )
        state.last_valid_at = now

        if _same_cell(locked, candidate, cfg):
            state.switch_candidate = None
            state.switch_since = None
            return BeamLockResult(
                BEAM_LOCKED,
                candidate,
                locked,
                self._lock_age(state, now),
                state.switch_count,
                state.segment_id,
                "candidate agrees with persistent locked chest beam",
            )

        strong_enough = (
            candidate.selectedMagnitude
            >= locked.selectedMagnitude * cfg.switchMargin
        )
        if strong_enough:
            if not _same_cell(state.switch_candidate, candidate, cfg):
                state.switch_candidate = candidate
                state.switch_since = now
            switch_since = (
                now if state.switch_since is None else state.switch_since
            )
            confirm_for = max(0.0, now - switch_since)
            if confirm_for >= cfg.switchConfirmSec:
                self._lock(state, candidate, now, switched=True)
                return BeamLockResult(
                    BEAM_LOCKED,
                    candidate,
                    candidate,
                    0.0,
                    state.switch_count,
                    state.segment_id,
                    "stronger candidate persisted; locked beam switched",
                )
        else:
            state.switch_candidate = None
            state.switch_since = None

        return BeamLockResult(
            BEAM_HOLD,
            candidate,
            locked,
            self._lock_age(state, now),
            state.switch_count,
            state.segment_id,
            "candidate may move; previous chest beam remains locked",
        )

    @staticmethod
    def _lock_age(state: _TargetLock, now: float) -> float:
        return 0.0 if state.locked_since is None else max(0.0, now - state.locked_since)

    @staticmethod
    def _lock(
        state: _TargetLock,
        selection: AzimuthBeamSelection,
        now: float,
        switched: bool,
    ) -> None:
        state.locked_bin = selection.selectedRangeBin
        state.locked_azimuth = selection.selectedAzimuthDeg
        state.locked_since = now
        state.last_valid_at = now
        state.segment_id += 1
        if switched:
            state.switch_count += 1
        state.candidate = selection
        state.candidate_since = now
        state.switch_candidate = None
        state.switch_since = None


@dataclass
class LockedPhaseSample:
    rawPhaseRad: float
    unwrappedPhaseRad: float
    relativePhaseRad: float
    displacementMm: float
    segmentId: int
    valid: bool


class LockedPhaseTracker:
    """Unwrap phase only inside one persistent locked-beam segment."""

    def __init__(self, carrier_frequency_ghz: float = 77.0):
        if carrier_frequency_ghz <= 0:
            raise ValueError("carrier_frequency_ghz must be positive")
        self.wavelength_mm = 299792458.0 / (carrier_frequency_ghz * 1e9) * 1000.0
        self._state: dict[int, dict[str, float | int]] = {}

    def update(
        self,
        target_id: int,
        raw_phase_rad: float,
        segment_id: int,
    ) -> LockedPhaseSample:
        tid = int(target_id)
        raw = float(raw_phase_rad)
        state = self._state.get(tid)
        if state is None or int(state["segment"]) != int(segment_id):
            state = {
                "segment": int(segment_id),
                "raw": raw,
                "unwrapped": raw,
                "origin": raw,
            }
            self._state[tid] = state
        else:
            delta = math.atan2(
                math.sin(raw - float(state["raw"])),
                math.cos(raw - float(state["raw"])),
            )
            state["unwrapped"] = float(state["unwrapped"]) + delta
            state["raw"] = raw
        relative = float(state["unwrapped"]) - float(state["origin"])
        displacement = relative * self.wavelength_mm / (4.0 * math.pi)
        return LockedPhaseSample(
            raw,
            float(state["unwrapped"]),
            relative,
            displacement,
            int(segment_id),
            True,
        )
