from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable

from awr1642_vitals.phase_vitals.azimuth_beamforming import (
    AzimuthBeamSelection,
    BeamformingConfig,
    select_range_azimuth_cell,
)

from .awr_bin_selector import SelectorConfig, select_bin, select_bin_for_target
from .beam_lock import (
    BEAM_HOLD,
    BEAM_LOCKED,
    BEAM_LOST,
    BeamLockConfig,
    BeamLockManager,
    BeamLockResult,
    LockedPhaseTracker,
)
from .chest_point_estimator import ChestEstimatorConfig, estimate_chest_point
from .coordinate_transform import (
    TransformConfig,
    compute_awr_spatial_target,
)
from .fusion_types import (
    AwrBinSample,
    AwrBinWindow,
    AwrAzimuthBeamSelection,
    AwrVirtualAntWindow,
    BinSelection,
    FusedTargetVital,
    IwrTarget,
    PhaseDiagnostics,
    SpatialBinSelection,
)
from .nearby_beam_combiner import (
    NearbyBeamCombiner,
    NearbyBeamCombinerConfig,
)
from .posture_gate import (
    MONITORING,
    MONITORING_POSE_GRACE,
    NO_TARGET,
    PAUSED_NOT_SITTING,
    POSTURE_UNSTABLE,
    TARGET_LOST,
    WAITING_FOR_SITTING,
    SittingGate,
    SittingGateConfig,
    SEATED_LOCK,
)
from .vital_estimator_bridge import VitalEstimatorBridge, VitalEstimatorConfig


NO_AWR_WINDOW = "NO_AWR_WINDOW"
NO_BIN = "NO_BIN"
BIN_SWITCHING = "BIN_SWITCHING"
FE03_ACTIVE = "FE03_ACTIVE"
FE03_STALE = "FE03_STALE"
FE03_LOST = "FE03_LOST"
ACTIVE_MONITORING_STATES = {
    MONITORING,
    MONITORING_POSE_GRACE,
    SEATED_LOCK,
}


@dataclass(frozen=True)
class Fe03Status:
    window: AwrVirtualAntWindow | None
    ageSec: float | None
    frameNumber: int | None
    framesPerSecond: float
    streamState: str
    frameCount: int
    payloadOk: bool
    parseError: str


class Fe03LivenessTracker:
    """Retain the last FE03 frame across brief receive gaps."""

    def __init__(self, stale_timeout_sec: float = 2.0):
        if stale_timeout_sec < 0:
            raise ValueError("stale_timeout_sec must be non-negative")
        self.stale_timeout_sec = float(stale_timeout_sec)
        self.latest_window: AwrVirtualAntWindow | None = None
        self.latest_received_at: float | None = None
        self._receive_times: deque[float] = deque(maxlen=30)
        self.frame_count = 0
        self.latest_payload_ok = False
        self.latest_parse_error = ""

    def update(
        self,
        window: AwrVirtualAntWindow,
        received_at: float | None = None,
    ) -> None:
        now = time.time() if received_at is None else float(received_at)
        self.latest_window = window
        self.latest_received_at = now
        self._receive_times.append(now)
        self.frame_count += 1
        self.latest_payload_ok = True
        self.latest_parse_error = ""

    def record_parse_error(self, error: Exception | str) -> None:
        self.latest_payload_ok = False
        self.latest_parse_error = str(error)

    def snapshot(
        self, now: float | None = None
    ) -> tuple[AwrVirtualAntWindow | None, float | None, int | None, float]:
        current = time.time() if now is None else float(now)
        age = (
            None
            if self.latest_received_at is None
            else max(0.0, current - self.latest_received_at)
        )
        active = (
            self.latest_window
            if age is not None and age <= self.stale_timeout_sec
            else None
        )
        frame = (
            None
            if self.latest_window is None
            else int(self.latest_window.frameNumber)
        )
        fps = 0.0
        if len(self._receive_times) >= 2:
            elapsed = self._receive_times[-1] - self._receive_times[0]
            if elapsed > 0:
                fps = (len(self._receive_times) - 1) / elapsed
        return active, age, frame, fps

    def status(self, now: float | None = None) -> Fe03Status:
        active, age, frame, fps = self.snapshot(now)
        if self.latest_received_at is None:
            stream_state = FE03_LOST
        elif age is not None and age <= self.stale_timeout_sec * 0.5:
            stream_state = FE03_ACTIVE
        elif active is not None:
            stream_state = FE03_STALE
        else:
            stream_state = FE03_LOST
        return Fe03Status(
            window=active,
            ageSec=age,
            frameNumber=frame,
            framesPerSecond=fps,
            streamState=stream_state,
            frameCount=self.frame_count,
            payloadOk=self.latest_payload_ok,
            parseError=self.latest_parse_error,
        )


def _window_range_resolution(
    window: AwrBinWindow | AwrVirtualAntWindow | None,
) -> float | None:
    if isinstance(window, AwrVirtualAntWindow):
        return float(window.rangeResolution)
    if window is None or not window.bins:
        return None
    nonzero = [sample for sample in window.bins if sample.binIndex > 0]
    if not nonzero:
        return None
    sample = nonzero[0]
    return sample.rangeMeters / sample.binIndex


@dataclass(frozen=True)
class FusionConfig:
    transform: TransformConfig = TransformConfig()
    selector: SelectorConfig = SelectorConfig()
    gate: SittingGateConfig = SittingGateConfig()
    estimator: VitalEstimatorConfig = VitalEstimatorConfig()
    chest: ChestEstimatorConfig = ChestEstimatorConfig()
    useChestTargeting: bool = True
    beamforming: BeamformingConfig = BeamformingConfig()
    azimuthSearchHalfWidthDeg: float = 15.0
    beamLock: BeamLockConfig = BeamLockConfig()
    nearbyBeamCombiner: NearbyBeamCombinerConfig = NearbyBeamCombinerConfig()
    carrierFrequencyGhz: float = 77.0
    # Deprecated compatibility field retained for callers from the earlier
    # candidate-only beam selector. BeamLockConfig now owns hold timing.
    beamSwitchHoldSec: float | None = None


class FusionEngine:
    def __init__(self, config: FusionConfig | None = None):
        self.config = config or FusionConfig()
        self.gate = SittingGate(self.config.gate)
        self.estimator = VitalEstimatorBridge(self.config.estimator)
        self._previous_selection: dict[int, BinSelection] = {}
        self.beam_lock = BeamLockManager(self.config.beamLock)
        self.nearby_beam_combiner = NearbyBeamCombiner(
            self.config.nearbyBeamCombiner
        )
        self.phase_tracker = LockedPhaseTracker(self.config.carrierFrequencyGhz)
        self.latest_chest = None
        self.latest_spatial_target = None
        self.latest_spatial_selection: SpatialBinSelection | None = None
        self.latest_beam_selection: AwrAzimuthBeamSelection | None = None
        self.latest_candidate_beam_selection: AwrAzimuthBeamSelection | None = None
        self.latest_locked_beam_selection: AwrAzimuthBeamSelection | None = None
        self.latest_beam_lock: BeamLockResult | None = None

    def process(
        self,
        target: IwrTarget,
        awr_window: AwrBinWindow | None,
        timestamp: float | None = None,
        awr_virtual_ant_window: AwrVirtualAntWindow | None = None,
        fe03_age_sec: float | None = None,
        latest_fe03_frame_number: int | None = None,
        fe03_frames_per_second: float = 0.0,
        fe03_stream_state: str = FE03_LOST,
        fe03_frame_count: int = 0,
        latest_fe03_payload_ok: bool = False,
        latest_fe03_parse_error: str = "",
    ) -> tuple[FusedTargetVital, BinSelection | None]:
        now = time.time() if timestamp is None else float(timestamp)
        if (
            awr_virtual_ant_window is not None
            and fe03_stream_state == FE03_LOST
        ):
            # Direct/offline callers may provide a valid FE03 window without
            # a liveness tracker. A present parsed TLV is independently active.
            fe03_stream_state = FE03_ACTIVE
            latest_fe03_payload_ok = True
            if latest_fe03_frame_number is None:
                latest_fe03_frame_number = awr_virtual_ant_window.frameNumber
        chest = estimate_chest_point(target, self.config.chest)
        range_resolution = _window_range_resolution(
            awr_virtual_ant_window or awr_window
        )
        spatial_target = compute_awr_spatial_target(
            chest,
            self.config.transform,
            range_resolution,
        )
        self.latest_chest = chest
        self.latest_spatial_target = spatial_target
        selection = None
        selection_mode = "RANGE_ONLY_TARGET_CENTER"
        beam_selection: AzimuthBeamSelection | None = None
        candidate_beam: AzimuthBeamSelection | None = None
        locked_beam: AzimuthBeamSelection | None = None
        phase_sample = None
        combined_beam = None
        beam_lock = self.beam_lock.update(
            target.targetId, None, None, timestamp=now
        )
        self.latest_beam_selection = None
        self.latest_candidate_beam_selection = None
        self.latest_locked_beam_selection = None
        if (
            awr_virtual_ant_window is not None
            and self.config.useChestTargeting
            and chest.confidence >= self.config.chest.minConfidenceForVitals
        ):
            candidate_beam = select_range_azimuth_cell(
                awr_virtual_ant_window,
                spatial_target.rangeMeters,
                spatial_target.azimuthDeg,
                self.config.selector.searchHalfWidth,
                self.config.azimuthSearchHalfWidthDeg,
                None,
                self.config.beamforming,
            )
            beam_lock = self.beam_lock.update(
                target.targetId,
                candidate_beam,
                awr_virtual_ant_window,
                timestamp=now,
            )
            locked_beam = beam_lock.locked
            beam_selection = locked_beam
            display_beam = locked_beam or candidate_beam
            if locked_beam is not None and beam_lock.state in {
                BEAM_LOCKED,
                BEAM_HOLD,
            }:
                combined_beam = self.nearby_beam_combiner.combine(
                    target.targetId,
                    awr_virtual_ant_window,
                    candidate_beam.beamMap,
                    candidate_beam.angleGridDeg,
                    locked_beam.selectedRangeBin,
                    locked_beam.selectedAzimuthDeg,
                    beam_lock.segmentId,
                )
                phase_sample = self.phase_tracker.update(
                    target.targetId,
                    combined_beam.phaseRad,
                    beam_lock.segmentId,
                )
            selection = BinSelection(
                expectedAwrRangeMeters=spatial_target.rangeMeters,
                expectedAwrBin=candidate_beam.expectedRangeBin,
                selectedAwrBin=(
                    locked_beam.selectedRangeBin if locked_beam else None
                ),
                selectedAwrRangeMeters=(
                    locked_beam.selectedRangeMeters if locked_beam else None
                ),
                selectedPhaseRad=(
                    combined_beam.phaseRad
                    if combined_beam is not None
                    else locked_beam.selectedPhaseRad
                    if locked_beam
                    else None
                ),
                selectedMagnitude=(
                    combined_beam.magnitude
                    if combined_beam is not None
                    else locked_beam.selectedMagnitude
                    if locked_beam
                    else None
                ),
                strongestOverallBin=display_beam.strongestOverallRangeBin,
                strongestOverallRangeMeters=(
                    display_beam.strongestOverallRangeMeters
                ),
                strongestOverallMagnitude=(
                    display_beam.strongestOverallMagnitude
                ),
                candidateBins=list(candidate_beam.candidateRangeBins),
                selectionReason=(
                    f"{beam_lock.reason}; {combined_beam.reason}"
                    if combined_beam is not None
                    else beam_lock.reason
                ),
                selectedAwrAzimuthDeg=(
                    locked_beam.selectedAzimuthDeg if locked_beam else None
                ),
                beamScore=candidate_beam.selectedScore,
                beamSwitchCount=beam_lock.switchCount,
                lockedPhaseUnwrapped=(
                    phase_sample.unwrappedPhaseRad if phase_sample else None
                ),
                displacementMm=(
                    phase_sample.displacementMm if phase_sample else None
                ),
                phaseSegmentId=(
                    phase_sample.segmentId if phase_sample else None
                ),
                phaseSignalSource=(
                    combined_beam.source
                    if combined_beam is not None
                    else "single_locked_beam"
                ),
                combinedBeamCount=(
                    combined_beam.cellCount if combined_beam is not None else 1
                ),
                beamCombineMode=(
                    self.config.nearbyBeamCombiner.mode
                    if combined_beam is not None
                    and combined_beam.usedCombined
                    else "single"
                ),
                beamCombineConfidence=(
                    combined_beam.confidence
                    if combined_beam is not None
                    else 0.0
                ),
            )
            selection_mode = "RANGE_AZIMUTH_CHEST_GUIDED"
            self.latest_candidate_beam_selection = self._make_beam_record(
                target.targetId,
                spatial_target,
                candidate_beam,
                beam_lock,
            )
            if locked_beam is not None:
                self.latest_locked_beam_selection = self._make_beam_record(
                    target.targetId,
                    spatial_target,
                    locked_beam,
                    beam_lock,
                )
            self.latest_beam_selection = (
                self.latest_locked_beam_selection
                or self.latest_candidate_beam_selection
            )
            self.latest_beam_lock = beam_lock
        elif awr_window is not None:
            if (
                self.config.useChestTargeting
                and chest.confidence >= self.config.chest.minConfidenceForVitals
            ):
                selection = select_bin(
                    spatial_target.rangeMeters,
                    awr_window,
                    self.config.selector,
                    self._previous_selection.get(target.targetId),
                )
                selection_mode = "RANGE_ONLY_CHEST_GUIDED"
            else:
                selection = select_bin_for_target(
                    target,
                    awr_window,
                    self.config.transform,
                    self.config.selector,
                    self._previous_selection.get(target.targetId),
                )
                if self.config.useChestTargeting:
                    selection_mode = "RANGE_ONLY_CHEST_LOW_CONFIDENCE_FALLBACK"
            if selection.selectedAwrBin is not None:
                self._previous_selection[target.targetId] = selection
        gate = self.gate.update(
            target,
            selected_bin=selection.selectedAwrBin if selection else None,
        )

        if awr_virtual_ant_window is None and awr_window is None:
            monitoring_state = NO_AWR_WINDOW
        elif (
            awr_virtual_ant_window is not None
            and beam_lock.state not in {BEAM_LOCKED, BEAM_HOLD}
        ):
            # Person/posture monitoring is independent from beam acquisition.
            # The estimator simply receives no phase until a beam is locked.
            monitoring_state = gate.state
        elif selection is None or selection.selectedAwrBin is None:
            monitoring_state = NO_BIN
        else:
            monitoring_state = gate.state

        estimate = self.estimator.update(
            target.targetId,
            selection,
            monitoring_state,
            timestamp=now,
            source_frame_number=(
                awr_virtual_ant_window.frameNumber
                if awr_virtual_ant_window is not None
                else awr_window.frameNumber
                if awr_window is not None
                else None
            ),
        )
        if (
            monitoring_state in ACTIVE_MONITORING_STATES
            and estimate.quality == BIN_SWITCHING
        ):
            monitoring_state = BIN_SWITCHING

        show_rates = (
            monitoring_state in ACTIVE_MONITORING_STATES or estimate.held
        )
        if show_rates:
            quality = estimate.quality
        elif monitoring_state in {
            PAUSED_NOT_SITTING,
            WAITING_FOR_SITTING,
            POSTURE_UNSTABLE,
            TARGET_LOST,
            NO_TARGET,
        }:
            quality = "PAUSED"
        else:
            quality = monitoring_state
        selection_reason = (
            selection.selectionReason
            if selection
            else "no recent AWR bin-window frame"
        )
        if monitoring_state not in ACTIVE_MONITORING_STATES:
            selection_reason = f"{gate.reason}; {selection_reason}"
        elif monitoring_state == MONITORING_POSE_GRACE:
            selection_reason = f"{gate.reason}; {selection_reason}"
        if awr_virtual_ant_window is not None:
            spatial_warning = (
                "FE03 azimuth beamforming assumes ordered lambda/2 ULA "
                "virtual antennas. AWR uses range+azimuth only; chest height "
                "is physically constrained by sensor placement."
            )
        else:
            spatial_warning = (
                "FE02 exports one virtual-antenna sample per range bin; "
                "azimuth/elevation are IWR-guided metadata, not AWR "
                "beamforming."
            )
        if selection is not None:
            selection_reason = (
                f"{selection_mode}: {selection_reason}; {spatial_warning}"
            )

        self.latest_spatial_selection = SpatialBinSelection(
            targetId=target.targetId,
            expectedRangeMeters=spatial_target.rangeMeters,
            expectedAzimuthDeg=spatial_target.azimuthDeg,
            expectedElevationDeg=spatial_target.elevationDeg,
            selectedRangeBin=selection.selectedAwrBin if selection else None,
            selectedAzimuthBin=(
                locked_beam.selectedAzimuthBin
                if locked_beam is not None
                else None
            ),
            selectedElevationBin=None,
            selectedRangeMeters=(
                selection.selectedAwrRangeMeters if selection else None
            ),
            selectedAzimuthDeg=(
                locked_beam.selectedAzimuthDeg
                if locked_beam is not None
                else None
            ),
            selectedElevationDeg=None,
            selectedMagnitude=selection.selectedMagnitude if selection else None,
            selectedPhaseRad=selection.selectedPhaseRad if selection else None,
            selectionMode=selection_mode,
            selectionReason=selection_reason,
        )

        fused = FusedTargetVital(
            timestamp=now,
            targetId=target.targetId,
            iwrFrameNumber=target.frameNumber,
            awrFrameNumber=(
                awr_virtual_ant_window.frameNumber
                if awr_virtual_ant_window is not None
                else awr_window.frameNumber if awr_window else None
            ),
            iwrX=target.x,
            iwrY=target.y,
            iwrZ=target.z,
            iwrRangeMeters=target.rangeMeters,
            posture=target.posture,
            postureAllowedForVitals=gate.allowed,
            monitoringState=monitoring_state,
            expectedAwrRangeMeters=(
                selection.expectedAwrRangeMeters if selection else None
            ),
            expectedAwrBin=selection.expectedAwrBin if selection else None,
            selectedAwrBin=selection.selectedAwrBin if selection else None,
            selectedAwrRangeMeters=(
                selection.selectedAwrRangeMeters if selection else None
            ),
            selectedPhaseRad=selection.selectedPhaseRad if selection else None,
            selectedMagnitude=selection.selectedMagnitude if selection else None,
            breathingBpm=estimate.breathingBpm if show_rates else None,
            heartBpm=estimate.heartBpm if show_rates else None,
            quality=quality,
            motionDetected=estimate.motionDetected if show_rates else False,
            selectionReason=selection_reason,
            chestIwrX=chest.iwrChestX,
            chestIwrY=chest.iwrChestY,
            chestIwrZ=chest.iwrChestZ,
            chestConfidence=chest.confidence,
            chestMethod=chest.method,
            awrExpectedX=spatial_target.awrX,
            awrExpectedY=spatial_target.awrY,
            awrExpectedZ=spatial_target.awrZ,
            expectedAwrAzimuthDeg=spatial_target.azimuthDeg,
            expectedAwrElevationDeg=(
                None
                if self.config.transform.awrChestHeightMode
                else spatial_target.elevationDeg
            ),
            selectionMode=selection_mode,
            spatialWarning=spatial_warning,
            poseGraceActive=gate.poseGraceActive,
            nonSittingStreakSec=gate.nonSittingStreakSec,
            graceRemainingSec=gate.graceRemainingSec,
            postureGateReason=gate.reason,
            lastStablePosture=gate.lastStablePosture,
            selectedAwrAzimuthDeg=(
                locked_beam.selectedAzimuthDeg
                if locked_beam is not None
                else None
            ),
            azimuthErrorDeg=(
                locked_beam.selectedAzimuthDeg - spatial_target.azimuthDeg
                if locked_beam is not None
                else None
            ),
            numVirtualAntennas=(
                awr_virtual_ant_window.numVirtualAntennas
                if awr_virtual_ant_window is not None
                else None
            ),
            selectedBeamMagnitude=(
                selection.selectedMagnitude if selection is not None else None
            ),
            selectedBeamPhaseRad=(
                selection.selectedPhaseRad if selection is not None else None
            ),
            fe03Status=fe03_stream_state,
            rawPosture=target.rawPosture,
            stablePosture=target.stablePosture,
            gatePosture=target.gatePosture or target.posture,
            fe03AgeSec=fe03_age_sec,
            latestFe03FrameNumber=latest_fe03_frame_number,
            fe03FramesPerSecond=fe03_frames_per_second,
            estimateAgeSec=estimate.estimateAgeSec,
            estimateHeld=estimate.held,
            breathCollecting=estimate.breathCollecting,
            heartCollecting=estimate.heartCollecting,
            breathEstimateState=estimate.breathEstimateState,
            heartEstimateState=estimate.heartEstimateState,
            breathingBpmMl=estimate.breathingBpmMl,
            heartBpmMl=estimate.heartBpmMl,
            vitalMlEnabled=estimate.mlEnabled,
            vitalMlNotes=estimate.mlNotes,
            selectedBeamScore=(
                candidate_beam.selectedScore
                if candidate_beam is not None
                else None
            ),
            beamSwitchCount=beam_lock.switchCount,
            iwrAzimuthDeg=math.degrees(math.atan2(target.x, target.y)),
            iwrElevationDeg=math.degrees(
                math.atan2(target.z, math.hypot(target.x, target.y))
            ),
            awrChestHeightMode=self.config.transform.awrChestHeightMode,
            expectedAwrRangeHorizontalMeters=spatial_target.horizontalRangeMeters,
            ignoredIwrElevationDeg=spatial_target.ignoredIwrElevationDeg,
            sensorDx=self.config.transform.dx,
            sensorDy=self.config.transform.dy,
            sensorDz=self.config.transform.dz,
            sensorYawDeg=(
                self.config.transform.yawOffsetDeg
                if self.config.transform.yawDeg is None
                else self.config.transform.yawDeg
            ),
            fe03StreamState=fe03_stream_state,
            fe03FrameCount=fe03_frame_count,
            latestFe03PayloadOk=latest_fe03_payload_ok,
            latestFe03ParseError=latest_fe03_parse_error,
            beamState=beam_lock.state,
            candidateRangeBin=(
                candidate_beam.selectedRangeBin if candidate_beam else None
            ),
            candidateRangeMeters=(
                candidate_beam.selectedRangeMeters if candidate_beam else None
            ),
            candidateAzimuthDeg=(
                candidate_beam.selectedAzimuthDeg if candidate_beam else None
            ),
            candidateMagnitude=(
                candidate_beam.selectedMagnitude if candidate_beam else None
            ),
            lockedRangeBin=(
                locked_beam.selectedRangeBin if locked_beam else None
            ),
            lockedRangeMeters=(
                locked_beam.selectedRangeMeters if locked_beam else None
            ),
            lockedAzimuthDeg=(
                locked_beam.selectedAzimuthDeg if locked_beam else None
            ),
            lockedMagnitude=(
                selection.selectedMagnitude
                if locked_beam is not None and selection is not None
                else None
            ),
            lockedPhaseRaw=(
                selection.selectedPhaseRad
                if locked_beam is not None and selection is not None
                else None
            ),
            lockedPhaseUnwrapped=(
                phase_sample.unwrappedPhaseRad if phase_sample else None
            ),
            displacementMm=phase_sample.displacementMm if phase_sample else None,
            phaseSegmentId=phase_sample.segmentId if phase_sample else None,
            phaseValid=bool(phase_sample and phase_sample.valid),
            beamLockAgeSec=beam_lock.lockAgeSec,
            rawHeartCandidateBpm=estimate.rawHeartCandidateBpm,
            trackedHeartBpm=estimate.trackedHeartBpm,
            displayedHeartBpm=estimate.displayedHeartBpm,
            heartCandidateCount=estimate.heartCandidateCount,
            heartSwitchPending=estimate.heartSwitchPending,
            heartSwitchCandidateBpm=estimate.heartSwitchCandidateBpm,
            heartHoldReason=estimate.heartHoldReason,
            heartQualityReason=estimate.heartQualityReason,
            heartWindowSecUsed=estimate.heartWindowSecUsed,
            heartPeakPersistenceSec=estimate.heartPeakPersistenceSec,
            heartRejectedCandidateBpm=estimate.heartRejectedCandidateBpm,
            heartRejectedReason=estimate.heartRejectedReason,
        )
        return fused, selection

    @staticmethod
    def _make_beam_record(
        target_id: int,
        spatial_target,
        selection: AzimuthBeamSelection,
        lock: BeamLockResult,
    ) -> AwrAzimuthBeamSelection:
        return AwrAzimuthBeamSelection(
            targetId=target_id,
            expectedRangeMeters=spatial_target.rangeMeters,
            expectedRangeBin=selection.expectedRangeBin,
            expectedAzimuthDeg=spatial_target.azimuthDeg,
            selectedRangeBin=selection.selectedRangeBin,
            selectedRangeMeters=selection.selectedRangeMeters,
            selectedAzimuthBin=selection.selectedAzimuthBin,
            selectedAzimuthDeg=selection.selectedAzimuthDeg,
            selectedComplexReal=float(selection.selectedComplex.real),
            selectedComplexImag=float(selection.selectedComplex.imag),
            selectedPhaseRad=selection.selectedPhaseRad,
            selectedMagnitude=selection.selectedMagnitude,
            strongestOverallRangeBin=selection.strongestOverallRangeBin,
            strongestOverallRangeMeters=selection.strongestOverallRangeMeters,
            strongestOverallAzimuthDeg=selection.strongestOverallAzimuthDeg,
            strongestOverallMagnitude=selection.strongestOverallMagnitude,
            candidateRangeBins=list(selection.candidateRangeBins),
            candidateAzimuthDeg=list(selection.candidateAzimuthDeg),
            selectionReason=lock.reason,
            beamScore=selection.selectedScore,
            beamSwitchCount=lock.switchCount,
            selectionChanged=False,
            angleGridDeg=selection.angleGridDeg,
            beamMap=selection.beamMap,
        )

    def phase_diagnostics(
        self, target_id: int, timestamp: float | None = None
    ) -> PhaseDiagnostics:
        return self.estimator.diagnostics(target_id, timestamp)

    def target_lost(self, target_id: int) -> str:
        return self.gate.update(None, target_id=target_id).state


def make_status_fused(
    state: str,
    timestamp: float | None = None,
    target_id: int | None = None,
    reason: str = "",
) -> FusedTargetVital:
    return FusedTargetVital(
        timestamp=time.time() if timestamp is None else float(timestamp),
        targetId=target_id,
        iwrFrameNumber=None,
        awrFrameNumber=None,
        iwrX=None,
        iwrY=None,
        iwrZ=None,
        iwrRangeMeters=None,
        posture="UNKNOWN",
        postureAllowedForVitals=False,
        monitoringState=state,
        expectedAwrRangeMeters=None,
        expectedAwrBin=None,
        selectedAwrBin=None,
        selectedAwrRangeMeters=None,
        selectedPhaseRad=None,
        selectedMagnitude=None,
        breathingBpm=None,
        heartBpm=None,
        quality="PAUSED",
        motionDetected=False,
        selectionReason=reason or state,
    )


class PrimaryTargetTracker:
    """Keep one primary TID stable while leaving the API ready for multiple TIDs."""

    def __init__(self, requested_target_id: int | None = None):
        self.requested_target_id = requested_target_id
        self.current_target_id: int | None = requested_target_id

    def select(self, targets: Iterable[IwrTarget]) -> IwrTarget | None:
        targets = list(targets)
        if not targets:
            return None
        if self.current_target_id is not None:
            for target in targets:
                if target.targetId == self.current_target_id:
                    return target
            if self.requested_target_id is not None:
                return None

        target = min(
            targets,
            key=lambda item: (
                math.inf if item.rangeMeters is None else item.rangeMeters,
                item.targetId,
            ),
        )
        self.current_target_id = target.targetId
        return target


def convert_awr_window(parsed_window: Any, timestamp: float | None = None) -> AwrBinWindow:
    now = time.time() if timestamp is None else float(timestamp)
    bins = [
        AwrBinSample(
            timestamp=now,
            frameNumber=int(parsed_window.frame_number),
            binIndex=int(sample.bin_index),
            rangeMeters=float(sample.range_meters),
            iValue=float(sample.i_value),
            qValue=float(sample.q_value),
            phaseRad=float(sample.phase_rad),
            magnitude=float(sample.magnitude),
        )
        for sample in parsed_window.samples
    ]
    strongest = max(bins, key=lambda sample: sample.magnitude) if bins else None
    return AwrBinWindow(
        timestamp=now,
        frameNumber=int(parsed_window.frame_number),
        startBin=int(parsed_window.start_bin),
        numBins=int(parsed_window.num_bins),
        bins=bins,
        strongestBin=strongest.binIndex if strongest else None,
        strongestRangeMeters=strongest.rangeMeters if strongest else None,
        strongestMagnitude=strongest.magnitude if strongest else None,
    )


def convert_awr_virtual_ant_window(
    parsed_window: Any,
    timestamp: float | None = None,
) -> AwrVirtualAntWindow:
    now = time.time() if timestamp is None else float(timestamp)
    return AwrVirtualAntWindow(
        timestamp=now,
        frameNumber=int(parsed_window.frame_number),
        startBin=int(parsed_window.start_bin),
        numBins=int(parsed_window.num_bins),
        numVirtualAntennas=int(parsed_window.num_virtual_antennas),
        flags=int(parsed_window.flags),
        rangeResolution=float(parsed_window.range_resolution),
        samples=parsed_window.samples,
        binIndices=parsed_window.bin_indices,
        rangeMeters=parsed_window.range_meters,
    )


def extract_iwr_targets(
    output_dict: dict[str, Any],
    pose_results: dict[int, dict[str, Any]] | None = None,
    timestamp: float | None = None,
) -> list[IwrTarget]:
    now = time.time() if timestamp is None else float(timestamp)
    frame_number = int(output_dict.get("frameNum", 0) or 0)
    pose_results = pose_results or {}
    height_by_tid: dict[int, float] = {}
    height_data = output_dict.get("heightData")
    if height_data is not None:
        for row in height_data:
            if len(row) >= 2:
                height_by_tid[int(row[0])] = float(row[1])
    tracks = output_dict.get("trackData")
    if tracks is None:
        return []

    targets = []
    for row in tracks:
        if len(row) < 7:
            continue
        tid = int(row[0])
        x, y, z = float(row[1]), float(row[2]), float(row[3])
        vx, vy, vz = float(row[4]), float(row[5]), float(row[6])
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        pose = pose_results.get(tid, {})
        raw_posture = str(
            pose.get("raw_label")
            or pose.get("candidate_label")
            or "UNKNOWN"
        ).upper()
        stable_posture = str(
            pose.get("displayed_label")
            or pose.get("final_label")
            or pose.get("smoothed_label")
            or pose.get("candidate_label")
            or "UNKNOWN"
        ).upper()
        # The pose manager's displayed label already includes its smoothing and
        # identity-aware stability logic. The vital gate adds a second, slower
        # safety state machine on this stable label rather than raw ML output.
        gate_posture = stable_posture
        confidence = pose.get("displayed_confidence")
        target_height = pose.get("target_height", height_by_tid.get(tid))
        ground_z = pose.get("ground_z")
        targets.append(
            IwrTarget(
                timestamp=now,
                frameNumber=frame_number,
                targetId=tid,
                x=x,
                y=y,
                z=z,
                rangeMeters=math.sqrt(x * x + y * y + z * z),
                velocityX=vx,
                velocityY=vy,
                velocityZ=vz,
                speed=speed,
                posture=gate_posture,
                postureConfidence=(
                    float(confidence) if confidence is not None else None
                ),
                trackState=str(pose.get("display_status", "")) or None,
                groundZ=float(ground_z) if ground_z is not None else None,
                targetHeight=(
                    float(target_height) if target_height is not None else None
                ),
                rawPosture=raw_posture,
                stablePosture=stable_posture,
                gatePosture=gate_posture,
            )
        )
    return targets


class DualSensorCsvLogger:
    def __init__(
        self,
        out_dir: str | Path,
        run_config: dict[str, Any],
        *,
        flush_interval_sec: float = 1.0,
        flush_rows: int = 50,
    ):
        self.out_dir = Path(out_dir).expanduser().resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.started_at = time.time()
        self.flush_interval_sec = max(0.05, float(flush_interval_sec))
        self.flush_rows = max(1, int(flush_rows))
        self._pending_flush_rows = 0
        self._last_flush_at = time.monotonic()
        self.counts = Counter()
        self.state_counts = Counter()
        self.target_ids: set[int] = set()
        self._files: list[Any] = []
        self._writers: dict[str, csv.DictWriter] = {}

        self._create_writer("iwr", "iwr_targets.csv", list(IwrTarget.__annotations__))
        self._create_writer(
            "awr",
            "awr_bin_window_samples.csv",
            [
                "timestamp",
                "frameNumber",
                "binIndex",
                "rangeMeters",
                "iValue",
                "qValue",
                "phaseRad",
                "magnitude",
            ],
        )
        self._create_writer(
            "fused",
            "fused_target_vitals.csv",
            list(FusedTargetVital.__annotations__),
        )
        self._create_writer(
            "awr_virtual",
            "awr_virtual_ant_window_samples.csv",
            [
                "timestamp",
                "frameNumber",
                "binIndex",
                "rangeMeters",
                "virtualAntennaIndex",
                "iValue",
                "qValue",
            ],
        )
        self._create_writer(
            "beam_summary",
            "awr_range_azimuth_heatmap_summary.csv",
            [
                "timestamp",
                "elapsedSec",
                "targetId",
                "awrFrameNumber",
                "expectedRangeMeters",
                "expectedRangeBin",
                "expectedAzimuthDeg",
                "selectedRangeBin",
                "selectedRangeMeters",
                "selectedAzimuthDeg",
                "selectedMagnitude",
                "strongestOverallRangeBin",
                "strongestOverallRangeMeters",
                "strongestOverallAzimuthDeg",
                "strongestOverallMagnitude",
                "selectionReason",
            ],
        )
        self._create_writer(
            "beam_phase",
            "selected_beam_phase.csv",
            [
                "timestamp",
                "elapsedSec",
                "targetId",
                "awrFrameNumber",
                "selectedRangeBin",
                "selectedRangeMeters",
                "selectedAzimuthDeg",
                "selectedComplexReal",
                "selectedComplexImag",
                "selectedPhaseRad",
                "selectedMagnitude",
                "monitoringState",
            ],
        )
        self._create_writer(
            "chest_beam_trace",
            "selected_chest_beam_trace.csv",
            [
                "timestamp",
                "elapsedSec",
                "targetId",
                "fe03FrameNumber",
                "fe03StreamState",
                "beamState",
                "candidateRangeBin",
                "candidateRangeMeters",
                "candidateAzimuthDeg",
                "candidateMagnitude",
                "lockedRangeBin",
                "lockedRangeMeters",
                "lockedAzimuthDeg",
                "lockedMagnitude",
                "beamLockAgeSec",
                "lockedPhaseRaw",
                "lockedPhaseUnwrapped",
                "displacementMm",
                "phaseSegmentId",
                "beamScore",
                "selectionReason",
                "beamSwitchCount",
                "phaseValid",
                "fe03AgeSec",
                "gateState",
                "monitoringState",
                "rawPosture",
                "stablePosture",
                "gatePosture",
                "postureGateReason",
                "awrChestHeightMode",
                "expectedAwrRangeHorizontalMeters",
                "expectedAwrAzimuthDeg",
                "phaseSignalSource",
                "combinedBeamCount",
                "beamCombineMode",
                "beamCombineConfidence",
                "rawHeartCandidateBpm",
                "trackedHeartBpm",
                "displayedHeartBpm",
                "heartCandidateCount",
                "heartSwitchPending",
                "heartSwitchCandidateBpm",
                "heartHoldReason",
                "heartQualityReason",
                "heartWindowSecUsed",
                "heartPeakPersistenceSec",
                "heartRejectedCandidateBpm",
                "heartRejectedReason",
            ],
        )
        self._create_writer(
            "phase_diagnostics",
            "phase_diagnostics_summary.csv",
            [
                "timestamp",
                "elapsedSec",
                "targetId",
                "validLockedDurationSec",
                "bufferLengthSec",
                "sampleCount",
                "effectiveSampleRateHz",
                "breathBpmClassical",
                "heartBpmClassical",
                "breathPeakBpm",
                "heartPeakBpm",
                "breathPeakPower",
                "heartPeakPower",
                "breathConfidence",
                "heartConfidence",
                "breathEstimateState",
                "heartEstimateState",
                "breathPeakSnr",
                "heartPeakSnr",
                "beamState",
                "phaseSegmentId",
                "quality",
                "beamSwitchedRecently",
                "breathQualityReason",
                "heartQualityReason",
                "phaseSignalSource",
                "combinedBeamCount",
                "beamCombineMode",
                "beamCombineConfidence",
                "rawHeartCandidateBpm",
                "trackedHeartBpm",
                "displayedHeartBpm",
                "heartCandidateCount",
                "heartSwitchPending",
                "heartSwitchCandidateBpm",
                "heartHoldReason",
                "heartWindowSecUsed",
                "heartPeakPersistenceSec",
                "heartRejectedCandidateBpm",
                "heartRejectedReason",
            ],
        )
        self._create_writer(
            "selected",
            "selected_bin_trace.csv",
            [
                "timestamp",
                "targetId",
                "iwrFrameNumber",
                "awrFrameNumber",
                "expectedAwrRangeMeters",
                "expectedAwrBin",
                "selectedAwrBin",
                "selectedAwrRangeMeters",
                "selectedPhaseRad",
                "selectedMagnitude",
                "strongestOverallBin",
                "strongestOverallRangeMeters",
                "strongestOverallMagnitude",
                "candidateBins",
                "selectionReason",
                "monitoringState",
                "chestConfidence",
                "expectedAwrAzimuthDeg",
                "expectedAwrElevationDeg",
                "selectedAwrAzimuthDeg",
                "azimuthErrorDeg",
                "numVirtualAntennas",
                "selectedBeamMagnitude",
                "selectedBeamPhaseRad",
                "fe03Status",
                "selectionMode",
                "spatialWarning",
                "poseGraceActive",
                "nonSittingStreakSec",
                "graceRemainingSec",
                "postureGateReason",
                "rawPosture",
                "stablePosture",
                "gatePosture",
                "fe03AgeSec",
                "latestFe03FrameNumber",
                "fe03FramesPerSecond",
                "estimateAgeSec",
                "estimateHeld",
                "breathCollecting",
                "heartCollecting",
                "selectedBeamScore",
                "beamSwitchCount",
                "awrChestHeightMode",
                "expectedAwrRangeHorizontalMeters",
                "ignoredIwrElevationDeg",
                "sensorDx",
                "sensorDy",
                "sensorDz",
                "sensorYawDeg",
                "fe03StreamState",
                "fe03FrameCount",
                "latestFe03PayloadOk",
                "latestFe03ParseError",
                "beamState",
                "candidateRangeBin",
                "candidateRangeMeters",
                "candidateAzimuthDeg",
                "candidateMagnitude",
                "lockedRangeBin",
                "lockedRangeMeters",
                "lockedAzimuthDeg",
                "lockedMagnitude",
                "lockedPhaseRaw",
                "lockedPhaseUnwrapped",
                "displacementMm",
                "phaseSegmentId",
                "phaseValid",
                "beamLockAgeSec",
            ],
        )
        self._create_writer(
            "events",
            "ui_events.csv",
            ["timestamp", "event", "targetId", "details"],
        )
        self._write_json("run_config.json", run_config)

    def log_iwr_targets(self, targets: Iterable[IwrTarget]) -> None:
        for target in targets:
            self._writers["iwr"].writerow(asdict(target))
            self.counts["iwr_targets"] += 1
            self.target_ids.add(target.targetId)

    def log_awr_window(self, window: AwrBinWindow) -> None:
        for sample in window.bins:
            self._writers["awr"].writerow(asdict(sample))
            self.counts["awr_bin_samples"] += 1
        self.counts["awr_windows"] += 1

    def log_awr_virtual_ant_window(
        self,
        window: AwrVirtualAntWindow,
    ) -> None:
        for row, bin_index in enumerate(window.binIndices):
            for antenna_index in range(window.numVirtualAntennas):
                value = complex(window.samples[row, antenna_index])
                self._writers["awr_virtual"].writerow(
                    {
                        "timestamp": window.timestamp,
                        "frameNumber": window.frameNumber,
                        "binIndex": int(bin_index),
                        "rangeMeters": float(window.rangeMeters[row]),
                        "virtualAntennaIndex": antenna_index,
                        "iValue": float(value.real),
                        "qValue": float(value.imag),
                    }
                )
                self.counts["awr_virtual_ant_samples"] += 1
        self.counts["awr_virtual_ant_windows"] += 1

    def log_beam_selection(
        self,
        fused: FusedTargetVital,
        selection: AwrAzimuthBeamSelection,
    ) -> None:
        common = {
            "timestamp": fused.timestamp,
            "elapsedSec": max(0.0, fused.timestamp - self.started_at),
            "targetId": fused.targetId,
            "awrFrameNumber": fused.awrFrameNumber,
        }
        self._writers["beam_summary"].writerow(
            {
                **common,
                "expectedRangeMeters": selection.expectedRangeMeters,
                "expectedRangeBin": selection.expectedRangeBin,
                "expectedAzimuthDeg": selection.expectedAzimuthDeg,
                "selectedRangeBin": selection.selectedRangeBin,
                "selectedRangeMeters": selection.selectedRangeMeters,
                "selectedAzimuthDeg": selection.selectedAzimuthDeg,
                "selectedMagnitude": selection.selectedMagnitude,
                "strongestOverallRangeBin": (
                    selection.strongestOverallRangeBin
                ),
                "strongestOverallRangeMeters": (
                    selection.strongestOverallRangeMeters
                ),
                "strongestOverallAzimuthDeg": (
                    selection.strongestOverallAzimuthDeg
                ),
                "strongestOverallMagnitude": (
                    selection.strongestOverallMagnitude
                ),
                "selectionReason": selection.selectionReason,
            }
        )
        self._writers["beam_phase"].writerow(
            {
                **common,
                "selectedRangeBin": selection.selectedRangeBin,
                "selectedRangeMeters": selection.selectedRangeMeters,
                "selectedAzimuthDeg": selection.selectedAzimuthDeg,
                "selectedComplexReal": selection.selectedComplexReal,
                "selectedComplexImag": selection.selectedComplexImag,
                "selectedPhaseRad": selection.selectedPhaseRad,
                "selectedMagnitude": selection.selectedMagnitude,
                "monitoringState": fused.monitoringState,
            }
        )
        self.counts["beam_selection_rows"] += 1

    def log_phase_diagnostics(
        self,
        fused: FusedTargetVital,
        diagnostics: PhaseDiagnostics,
    ) -> None:
        trace = self._writers["chest_beam_trace"]
        trace.writerow(
            {
                "timestamp": fused.timestamp,
                "elapsedSec": max(0.0, fused.timestamp - self.started_at),
                "targetId": fused.targetId,
                "fe03FrameNumber": fused.latestFe03FrameNumber,
                "fe03StreamState": fused.fe03StreamState,
                "beamState": fused.beamState,
                "candidateRangeBin": fused.candidateRangeBin,
                "candidateRangeMeters": fused.candidateRangeMeters,
                "candidateAzimuthDeg": fused.candidateAzimuthDeg,
                "candidateMagnitude": fused.candidateMagnitude,
                "lockedRangeBin": fused.lockedRangeBin,
                "lockedRangeMeters": fused.lockedRangeMeters,
                "lockedAzimuthDeg": fused.lockedAzimuthDeg,
                "lockedMagnitude": fused.lockedMagnitude,
                "beamLockAgeSec": fused.beamLockAgeSec,
                "lockedPhaseRaw": fused.lockedPhaseRaw,
                "lockedPhaseUnwrapped": fused.lockedPhaseUnwrapped,
                "displacementMm": fused.displacementMm,
                "phaseSegmentId": fused.phaseSegmentId,
                "beamScore": fused.selectedBeamScore,
                "selectionReason": fused.selectionReason,
                "beamSwitchCount": fused.beamSwitchCount,
                "phaseValid": fused.phaseValid,
                "fe03AgeSec": fused.fe03AgeSec,
                "gateState": fused.monitoringState,
                "monitoringState": fused.monitoringState,
                "rawPosture": fused.rawPosture,
                "stablePosture": fused.stablePosture,
                "gatePosture": fused.gatePosture,
                "postureGateReason": fused.postureGateReason,
                "awrChestHeightMode": fused.awrChestHeightMode,
                "expectedAwrRangeHorizontalMeters": (
                    fused.expectedAwrRangeHorizontalMeters
                ),
                "expectedAwrAzimuthDeg": fused.expectedAwrAzimuthDeg,
                "phaseSignalSource": diagnostics.phaseSignalSource,
                "combinedBeamCount": diagnostics.combinedBeamCount,
                "beamCombineMode": diagnostics.beamCombineMode,
                "beamCombineConfidence": diagnostics.beamCombineConfidence,
                "rawHeartCandidateBpm": diagnostics.rawHeartCandidateBpm,
                "trackedHeartBpm": diagnostics.trackedHeartBpm,
                "displayedHeartBpm": diagnostics.displayedHeartBpm,
                "heartCandidateCount": diagnostics.heartCandidateCount,
                "heartSwitchPending": diagnostics.heartSwitchPending,
                "heartSwitchCandidateBpm": (
                    diagnostics.heartSwitchCandidateBpm
                ),
                "heartHoldReason": diagnostics.heartHoldReason,
                "heartQualityReason": diagnostics.heartQualityReason,
                "heartWindowSecUsed": diagnostics.heartWindowSecUsed,
                "heartPeakPersistenceSec": diagnostics.heartPeakPersistenceSec,
                "heartRejectedCandidateBpm": (
                    diagnostics.heartRejectedCandidateBpm
                ),
                "heartRejectedReason": diagnostics.heartRejectedReason,
            }
        )
        self._writers["phase_diagnostics"].writerow(
            {
                "timestamp": diagnostics.timestamp,
                "elapsedSec": max(
                    0.0, diagnostics.timestamp - self.started_at
                ),
                "targetId": diagnostics.targetId,
                "validLockedDurationSec": diagnostics.validLockedDurationSec,
                "bufferLengthSec": diagnostics.bufferLengthSec,
                "sampleCount": diagnostics.sampleCount,
                "effectiveSampleRateHz": diagnostics.effectiveSampleRateHz,
                "breathBpmClassical": fused.breathingBpm,
                "heartBpmClassical": fused.heartBpm,
                "breathPeakBpm": diagnostics.breathPeakBpm,
                "heartPeakBpm": diagnostics.heartPeakBpm,
                "breathPeakPower": diagnostics.breathPeakPower,
                "heartPeakPower": diagnostics.heartPeakPower,
                "breathConfidence": diagnostics.breathConfidence,
                "heartConfidence": diagnostics.heartConfidence,
                "breathEstimateState": diagnostics.breathEstimateState,
                "heartEstimateState": diagnostics.heartEstimateState,
                "breathPeakSnr": diagnostics.breathPeakSnr,
                "heartPeakSnr": diagnostics.heartPeakSnr,
                "beamState": fused.beamState,
                "phaseSegmentId": diagnostics.phaseSegmentId,
                "quality": diagnostics.quality,
                "beamSwitchedRecently": diagnostics.beamSwitchedRecently,
                "breathQualityReason": diagnostics.breathQualityReason,
                "heartQualityReason": diagnostics.heartQualityReason,
                "phaseSignalSource": diagnostics.phaseSignalSource,
                "combinedBeamCount": diagnostics.combinedBeamCount,
                "beamCombineMode": diagnostics.beamCombineMode,
                "beamCombineConfidence": diagnostics.beamCombineConfidence,
                "rawHeartCandidateBpm": diagnostics.rawHeartCandidateBpm,
                "trackedHeartBpm": diagnostics.trackedHeartBpm,
                "displayedHeartBpm": diagnostics.displayedHeartBpm,
                "heartCandidateCount": diagnostics.heartCandidateCount,
                "heartSwitchPending": diagnostics.heartSwitchPending,
                "heartSwitchCandidateBpm": (
                    diagnostics.heartSwitchCandidateBpm
                ),
                "heartHoldReason": diagnostics.heartHoldReason,
                "heartWindowSecUsed": diagnostics.heartWindowSecUsed,
                "heartPeakPersistenceSec": diagnostics.heartPeakPersistenceSec,
                "heartRejectedCandidateBpm": (
                    diagnostics.heartRejectedCandidateBpm
                ),
                "heartRejectedReason": diagnostics.heartRejectedReason,
            }
        )
        self.counts["chest_beam_trace_rows"] += 1
        self.counts["phase_diagnostic_rows"] += 1

    def log_fused(
        self,
        fused: FusedTargetVital,
        selection: BinSelection | None,
    ) -> None:
        self._writers["fused"].writerow(asdict(fused))
        self.counts["fused_rows"] += 1
        self.state_counts[fused.monitoringState] += 1
        if fused.targetId is not None:
            self.target_ids.add(fused.targetId)
        if selection is not None:
            self._writers["selected"].writerow(
                {
                    "timestamp": fused.timestamp,
                    "targetId": fused.targetId,
                    "iwrFrameNumber": fused.iwrFrameNumber,
                    "awrFrameNumber": fused.awrFrameNumber,
                    "expectedAwrRangeMeters": selection.expectedAwrRangeMeters,
                    "expectedAwrBin": selection.expectedAwrBin,
                    "selectedAwrBin": selection.selectedAwrBin,
                    "selectedAwrRangeMeters": selection.selectedAwrRangeMeters,
                    "selectedPhaseRad": selection.selectedPhaseRad,
                    "selectedMagnitude": selection.selectedMagnitude,
                    "strongestOverallBin": selection.strongestOverallBin,
                    "strongestOverallRangeMeters": (
                        selection.strongestOverallRangeMeters
                    ),
                    "strongestOverallMagnitude": (
                        selection.strongestOverallMagnitude
                    ),
                    "candidateBins": json.dumps(selection.candidateBins),
                    "selectionReason": selection.selectionReason,
                    "monitoringState": fused.monitoringState,
                    "chestConfidence": fused.chestConfidence,
                    "expectedAwrAzimuthDeg": fused.expectedAwrAzimuthDeg,
                    "expectedAwrElevationDeg": fused.expectedAwrElevationDeg,
                    "selectedAwrAzimuthDeg": fused.selectedAwrAzimuthDeg,
                    "azimuthErrorDeg": fused.azimuthErrorDeg,
                    "numVirtualAntennas": fused.numVirtualAntennas,
                    "selectedBeamMagnitude": fused.selectedBeamMagnitude,
                    "selectedBeamPhaseRad": fused.selectedBeamPhaseRad,
                    "fe03Status": fused.fe03Status,
                    "selectionMode": fused.selectionMode,
                    "spatialWarning": fused.spatialWarning,
                    "poseGraceActive": fused.poseGraceActive,
                    "nonSittingStreakSec": fused.nonSittingStreakSec,
                    "graceRemainingSec": fused.graceRemainingSec,
                    "postureGateReason": fused.postureGateReason,
                    "rawPosture": fused.rawPosture,
                    "stablePosture": fused.stablePosture,
                    "gatePosture": fused.gatePosture,
                    "fe03AgeSec": fused.fe03AgeSec,
                    "latestFe03FrameNumber": fused.latestFe03FrameNumber,
                    "fe03FramesPerSecond": fused.fe03FramesPerSecond,
                    "estimateAgeSec": fused.estimateAgeSec,
                    "estimateHeld": fused.estimateHeld,
                    "breathCollecting": fused.breathCollecting,
                    "heartCollecting": fused.heartCollecting,
                    "selectedBeamScore": fused.selectedBeamScore,
                    "beamSwitchCount": fused.beamSwitchCount,
                    "awrChestHeightMode": fused.awrChestHeightMode,
                    "expectedAwrRangeHorizontalMeters": (
                        fused.expectedAwrRangeHorizontalMeters
                    ),
                    "ignoredIwrElevationDeg": fused.ignoredIwrElevationDeg,
                    "sensorDx": fused.sensorDx,
                    "sensorDy": fused.sensorDy,
                    "sensorDz": fused.sensorDz,
                    "sensorYawDeg": fused.sensorYawDeg,
                    "fe03StreamState": fused.fe03StreamState,
                    "fe03FrameCount": fused.fe03FrameCount,
                    "latestFe03PayloadOk": fused.latestFe03PayloadOk,
                    "latestFe03ParseError": fused.latestFe03ParseError,
                    "beamState": fused.beamState,
                    "candidateRangeBin": fused.candidateRangeBin,
                    "candidateRangeMeters": fused.candidateRangeMeters,
                    "candidateAzimuthDeg": fused.candidateAzimuthDeg,
                    "candidateMagnitude": fused.candidateMagnitude,
                    "lockedRangeBin": fused.lockedRangeBin,
                    "lockedRangeMeters": fused.lockedRangeMeters,
                    "lockedAzimuthDeg": fused.lockedAzimuthDeg,
                    "lockedMagnitude": fused.lockedMagnitude,
                    "lockedPhaseRaw": fused.lockedPhaseRaw,
                    "lockedPhaseUnwrapped": fused.lockedPhaseUnwrapped,
                    "displacementMm": fused.displacementMm,
                    "phaseSegmentId": fused.phaseSegmentId,
                    "phaseValid": fused.phaseValid,
                    "beamLockAgeSec": fused.beamLockAgeSec,
                }
            )
            self.counts["selected_bin_rows"] += 1
        self._pending_flush_rows += 1
        self._maybe_flush()

    def log_ui_event(
        self,
        event: str,
        target_id: int | None = None,
        details: str = "",
        timestamp: float | None = None,
    ) -> None:
        self._writers["events"].writerow(
            {
                "timestamp": time.time() if timestamp is None else timestamp,
                "event": event,
                "targetId": target_id,
                "details": details,
            }
        )
        self.counts["ui_events"] += 1

    def flush(self) -> None:
        for handle in self._files:
            handle.flush()
        self._pending_flush_rows = 0
        self._last_flush_at = time.monotonic()

    def _maybe_flush(self) -> None:
        if (
            self._pending_flush_rows >= self.flush_rows
            or time.monotonic() - self._last_flush_at
            >= self.flush_interval_sec
        ):
            self.flush()

    def close(self, extra_summary: dict[str, Any] | None = None) -> None:
        if not self._files:
            return
        summary = {
            "startedAtUnix": self.started_at,
            "endedAtUnix": time.time(),
            "elapsedSeconds": time.time() - self.started_at,
            "counts": dict(self.counts),
            "monitoringStateCounts": dict(self.state_counts),
            "targetIds": sorted(self.target_ids),
        }
        if extra_summary:
            summary.update(extra_summary)
        self._write_json("fusion_summary.json", summary)
        self.flush()
        for handle in self._files:
            handle.close()
        self._files.clear()

    def _create_writer(
        self, key: str, filename: str, fieldnames: list[str]
    ) -> None:
        handle = (self.out_dir / filename).open(
            "w", newline="", encoding="utf-8"
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        self._files.append(handle)
        self._writers[key] = writer

    def _write_json(self, filename: str, payload: dict[str, Any]) -> None:
        with (self.out_dir / filename).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
