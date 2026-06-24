from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IwrTarget:
    timestamp: float
    frameNumber: int
    targetId: int
    x: float
    y: float
    z: float
    rangeMeters: Optional[float]
    velocityX: Optional[float] = None
    velocityY: Optional[float] = None
    velocityZ: Optional[float] = None
    speed: Optional[float] = None
    posture: str = "UNKNOWN"
    postureConfidence: Optional[float] = None
    trackState: Optional[str] = None
    groundZ: Optional[float] = None
    targetHeight: Optional[float] = None
    rawPosture: str = "UNKNOWN"
    stablePosture: str = "UNKNOWN"
    gatePosture: str = "UNKNOWN"


@dataclass
class ChestPointEstimate:
    timestamp: float
    targetId: int
    sourceFrameNumber: int
    posture: str
    iwrChestX: float
    iwrChestY: float
    iwrChestZ: float
    confidence: float
    method: str
    notes: str = ""


@dataclass
class AwrSpatialTarget:
    timestamp: float
    targetId: int
    awrX: float
    awrY: float
    awrZ: float
    rangeMeters: float
    horizontalRangeMeters: float
    azimuthDeg: float
    elevationDeg: float
    expectedRangeBin: Optional[int] = None
    expectedAzimuthBin: Optional[int] = None
    expectedElevationBin: Optional[int] = None
    confidence: float = 0.0
    chestHeightMode: bool = False
    ignoredIwrElevationDeg: Optional[float] = None


@dataclass
class AwrBinSample:
    timestamp: float
    frameNumber: int
    binIndex: int
    rangeMeters: float
    iValue: float
    qValue: float
    phaseRad: float
    magnitude: float


@dataclass
class AwrBinWindow:
    timestamp: float
    frameNumber: int
    startBin: int
    numBins: int
    bins: list[AwrBinSample] = field(default_factory=list)
    strongestBin: Optional[int] = None
    strongestRangeMeters: Optional[float] = None
    strongestMagnitude: Optional[float] = None


@dataclass
class AwrVirtualAntWindow:
    timestamp: float
    frameNumber: int
    startBin: int
    numBins: int
    numVirtualAntennas: int
    flags: int
    rangeResolution: float
    samples: Any
    binIndices: Any
    rangeMeters: Any

    # The standalone beamformer also accepts the parser's snake_case shape.
    @property
    def frame_number(self) -> int:
        return self.frameNumber

    @property
    def start_bin(self) -> int:
        return self.startBin

    @property
    def num_bins(self) -> int:
        return self.numBins

    @property
    def num_virtual_antennas(self) -> int:
        return self.numVirtualAntennas

    @property
    def range_resolution(self) -> float:
        return self.rangeResolution

    @property
    def bin_indices(self) -> Any:
        return self.binIndices

    @property
    def range_meters(self) -> Any:
        return self.rangeMeters


@dataclass
class AwrAzimuthBeamSelection:
    targetId: int
    expectedRangeMeters: float
    expectedRangeBin: int
    expectedAzimuthDeg: float
    selectedRangeBin: int
    selectedRangeMeters: float
    selectedAzimuthBin: int
    selectedAzimuthDeg: float
    selectedComplexReal: float
    selectedComplexImag: float
    selectedPhaseRad: float
    selectedMagnitude: float
    strongestOverallRangeBin: int
    strongestOverallRangeMeters: float
    strongestOverallAzimuthDeg: float
    strongestOverallMagnitude: float
    candidateRangeBins: list[int] = field(default_factory=list)
    candidateAzimuthDeg: list[float] = field(default_factory=list)
    selectionReason: str = ""
    beamScore: float = 0.0
    beamSwitchCount: int = 0
    selectionChanged: bool = False
    angleGridDeg: Any = None
    beamMap: Any = None


@dataclass
class BinSelection:
    expectedAwrRangeMeters: float
    expectedAwrBin: Optional[int]
    selectedAwrBin: Optional[int]
    selectedAwrRangeMeters: Optional[float]
    selectedPhaseRad: Optional[float]
    selectedMagnitude: Optional[float]
    strongestOverallBin: Optional[int]
    strongestOverallRangeMeters: Optional[float]
    strongestOverallMagnitude: Optional[float]
    candidateBins: list[int] = field(default_factory=list)
    selectionReason: str = ""
    selectedAwrAzimuthDeg: Optional[float] = None
    beamScore: Optional[float] = None
    beamSwitchCount: int = 0
    lockedPhaseUnwrapped: Optional[float] = None
    displacementMm: Optional[float] = None
    phaseSegmentId: Optional[int] = None
    phaseSignalSource: str = "single_locked_beam"
    combinedBeamCount: int = 1
    beamCombineMode: str = "single"
    beamCombineConfidence: float = 0.0


@dataclass
class SpatialBinSelection:
    targetId: int
    expectedRangeMeters: float
    expectedAzimuthDeg: float
    expectedElevationDeg: float
    selectedRangeBin: Optional[int]
    selectedAzimuthBin: Optional[int]
    selectedElevationBin: Optional[int]
    selectedRangeMeters: Optional[float]
    selectedAzimuthDeg: Optional[float]
    selectedElevationDeg: Optional[float]
    selectedMagnitude: Optional[float]
    selectedPhaseRad: Optional[float]
    selectionMode: str
    selectionReason: str


@dataclass
class VitalEstimate:
    breathingBpm: Optional[float] = None
    heartBpm: Optional[float] = None
    quality: str = "INVALID"
    motionDetected: bool = False
    confidenceBreath: float = 0.0
    confidenceHeart: float = 0.0
    notes: str = ""
    estimateAgeSec: Optional[float] = None
    held: bool = False
    breathCollecting: bool = True
    heartCollecting: bool = True
    breathEstimateState: str = "COLLECTING"
    heartEstimateState: str = "COLLECTING"
    breathingBpmMl: Optional[float] = None
    heartBpmMl: Optional[float] = None
    mlEnabled: bool = False
    mlNotes: str = ""
    breathPeakSnr: float = 0.0
    heartPeakSnr: float = 0.0
    breathQualityReason: str = ""
    heartQualityReason: str = ""
    phaseSignalSource: str = "single_locked_beam"
    rawHeartCandidateBpm: Optional[float] = None
    trackedHeartBpm: Optional[float] = None
    displayedHeartBpm: Optional[float] = None
    heartCandidateCount: int = 0
    heartSwitchPending: bool = False
    heartSwitchCandidateBpm: Optional[float] = None
    heartHoldReason: str = ""
    heartWindowSecUsed: float = 0.0
    heartPeakPersistenceSec: float = 0.0
    heartRejectedCandidateBpm: Optional[float] = None
    heartRejectedReason: str = ""


@dataclass
class PhaseDiagnostics:
    targetId: int
    timestamp: float
    sampleCount: int
    bufferLengthSec: float
    effectiveSampleRateHz: float
    timeSec: Any
    rawPhase: Any
    unwrappedPhase: Any
    relativePhase: Any
    displacementMm: Any
    phaseSegmentIds: Any
    breathingFiltered: Any
    heartFiltered: Any
    frequencyHz: Any
    spectrumPower: Any
    breathPeakBpm: Optional[float] = None
    heartPeakBpm: Optional[float] = None
    breathPeakPower: float = 0.0
    heartPeakPower: float = 0.0
    breathConfidence: float = 0.0
    heartConfidence: float = 0.0
    quality: str = "COLLECTING"
    selectedRangeBin: Optional[int] = None
    selectedAzimuthDeg: Optional[float] = None
    selectedMagnitude: Optional[float] = None
    selectedPhaseRad: Optional[float] = None
    beamSwitchedRecently: bool = False
    phaseValid: bool = False
    phaseSegmentId: Optional[int] = None
    validLockedDurationSec: float = 0.0
    breathEstimateState: str = "COLLECTING"
    heartEstimateState: str = "COLLECTING"
    breathPeakSnr: float = 0.0
    heartPeakSnr: float = 0.0
    breathQualityReason: str = ""
    heartQualityReason: str = ""
    phaseSignalSource: str = "single_locked_beam"
    combinedBeamCount: int = 1
    beamCombineMode: str = "single"
    beamCombineConfidence: float = 0.0
    heartFrequencyHz: Any = None
    heartSpectrumPower: Any = None
    heartCandidateBpms: Any = None
    heartCandidatePowers: Any = None
    heartCandidateSnrs: Any = None
    heartCandidateScores: Any = None
    rawHeartCandidateBpm: Optional[float] = None
    trackedHeartBpm: Optional[float] = None
    displayedHeartBpm: Optional[float] = None
    heartCandidateCount: int = 0
    heartSwitchPending: bool = False
    heartSwitchCandidateBpm: Optional[float] = None
    heartHoldReason: str = ""
    heartWindowSecUsed: float = 0.0
    heartPeakPersistenceSec: float = 0.0
    heartRejectedCandidateBpm: Optional[float] = None
    heartRejectedReason: str = ""
    phaseContinuityIds: Any = None


@dataclass
class FusedTargetVital:
    timestamp: float
    targetId: Optional[int]
    iwrFrameNumber: Optional[int]
    awrFrameNumber: Optional[int]
    iwrX: Optional[float]
    iwrY: Optional[float]
    iwrZ: Optional[float]
    iwrRangeMeters: Optional[float]
    posture: str
    postureAllowedForVitals: bool
    monitoringState: str
    expectedAwrRangeMeters: Optional[float]
    expectedAwrBin: Optional[int]
    selectedAwrBin: Optional[int]
    selectedAwrRangeMeters: Optional[float]
    selectedPhaseRad: Optional[float]
    selectedMagnitude: Optional[float]
    breathingBpm: Optional[float]
    heartBpm: Optional[float]
    quality: str
    motionDetected: bool
    selectionReason: str
    chestIwrX: Optional[float] = None
    chestIwrY: Optional[float] = None
    chestIwrZ: Optional[float] = None
    chestConfidence: Optional[float] = None
    chestMethod: Optional[str] = None
    awrExpectedX: Optional[float] = None
    awrExpectedY: Optional[float] = None
    awrExpectedZ: Optional[float] = None
    expectedAwrAzimuthDeg: Optional[float] = None
    expectedAwrElevationDeg: Optional[float] = None
    selectionMode: str = "RANGE_ONLY_TARGET_CENTER"
    spatialWarning: str = ""
    poseGraceActive: bool = False
    nonSittingStreakSec: float = 0.0
    graceRemainingSec: float = 0.0
    postureGateReason: str = ""
    lastStablePosture: str = "UNKNOWN"
    selectedAwrAzimuthDeg: Optional[float] = None
    azimuthErrorDeg: Optional[float] = None
    numVirtualAntennas: Optional[int] = None
    selectedBeamMagnitude: Optional[float] = None
    selectedBeamPhaseRad: Optional[float] = None
    fe03Status: str = "NOT_AVAILABLE"
    rawPosture: str = "UNKNOWN"
    stablePosture: str = "UNKNOWN"
    gatePosture: str = "UNKNOWN"
    fe03AgeSec: Optional[float] = None
    latestFe03FrameNumber: Optional[int] = None
    fe03FramesPerSecond: float = 0.0
    estimateAgeSec: Optional[float] = None
    estimateHeld: bool = False
    breathCollecting: bool = True
    heartCollecting: bool = True
    selectedBeamScore: Optional[float] = None
    beamSwitchCount: int = 0
    iwrAzimuthDeg: Optional[float] = None
    iwrElevationDeg: Optional[float] = None
    awrChestHeightMode: bool = False
    expectedAwrRangeHorizontalMeters: Optional[float] = None
    ignoredIwrElevationDeg: Optional[float] = None
    sensorDx: float = 0.0
    sensorDy: float = 0.0
    sensorDz: float = 0.0
    sensorYawDeg: float = 0.0
    fe03StreamState: str = "FE03_LOST"
    fe03FrameCount: int = 0
    latestFe03PayloadOk: bool = False
    latestFe03ParseError: str = ""
    beamState: str = "BEAM_LOST"
    candidateRangeBin: Optional[int] = None
    candidateRangeMeters: Optional[float] = None
    candidateAzimuthDeg: Optional[float] = None
    candidateMagnitude: Optional[float] = None
    lockedRangeBin: Optional[int] = None
    lockedRangeMeters: Optional[float] = None
    lockedAzimuthDeg: Optional[float] = None
    lockedMagnitude: Optional[float] = None
    lockedPhaseRaw: Optional[float] = None
    lockedPhaseUnwrapped: Optional[float] = None
    displacementMm: Optional[float] = None
    phaseSegmentId: Optional[int] = None
    phaseValid: bool = False
    beamLockAgeSec: float = 0.0
    breathEstimateState: str = "COLLECTING"
    heartEstimateState: str = "COLLECTING"
    breathingBpmMl: Optional[float] = None
    heartBpmMl: Optional[float] = None
    vitalMlEnabled: bool = False
    vitalMlNotes: str = ""
    rawHeartCandidateBpm: Optional[float] = None
    trackedHeartBpm: Optional[float] = None
    displayedHeartBpm: Optional[float] = None
    heartCandidateCount: int = 0
    heartSwitchPending: bool = False
    heartSwitchCandidateBpm: Optional[float] = None
    heartHoldReason: str = ""
    heartQualityReason: str = ""
    heartWindowSecUsed: float = 0.0
    heartPeakPersistenceSec: float = 0.0
    heartRejectedCandidateBpm: Optional[float] = None
    heartRejectedReason: str = ""
