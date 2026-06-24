from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
import math
import pickle
from pathlib import Path
import time

import numpy as np

from awr1642_vitals.phase_vitals.phase_vitals_estimator import (
    BREATH_HIGH_HZ,
    BREATH_LOW_HZ,
    HEART_HIGH_HZ,
    HEART_LOW_HZ,
    bandpass_signal,
    detrend_signal,
    estimate_vitals_from_phase,
)

from .fusion_types import BinSelection, PhaseDiagnostics, VitalEstimate
from .posture_gate import MONITORING, MONITORING_POSE_GRACE, SEATED_LOCK


ACTIVE_MONITORING_STATES = {
    MONITORING,
    MONITORING_POSE_GRACE,
    SEATED_LOCK,
}


@dataclass(frozen=True)
class VitalEstimatorConfig:
    fs: float = 10.0
    bufferSeconds: float = 120.0
    switchingWindowSamples: int = 10
    maxSwitchesInWindow: int = 3
    displayHoldSec: float = 10.0
    minEstimationWindowSec: float = 30.0
    minVitalWindowSec: float = 30.0
    minHeartWindowSec: float = 30.0
    breathStableWindowSec: float = 30.0
    heartStableWindowSec: float = 60.0
    bpmSmoothingSec: float = 10.0
    breathMaxJumpBpmPerSec: float = 3.0
    heartMaxJumpBpmPerSec: float = 10.0
    heartTopKPeaks: int = 5
    heartPeakPersistenceSec: float = 8.0
    heartSwitchConfirmSec: float = 8.0
    heartSwitchMargin: float = 1.35
    heartMinSnr: float = 3.0
    heartMinConfidence: float = 0.35
    heartWindowSec: float = 60.0
    heartPreliminaryWindowSec: float = 30.0
    breathWindowSec: float = 30.0
    phasePlotWindowSec: float = 120.0
    phaseSign: float = 1.0
    phaseUnwrapDiscontinuityRad: float = math.pi
    phaseGapResetSec: float = 1.0
    phaseResetOnBeamSwitch: bool = True
    carrierFrequencyGhz: float = 77.0
    requireLockedPhaseSegment: bool = True
    enableVitalMl: bool = False
    vitalModelDir: str | None = None
    mlMinWindowSec: float = 30.0
    analysisUpdateHz: float = 1.0


@dataclass(frozen=True)
class SegmentSafePhase:
    wrapped: np.ndarray
    unwrapped: np.ndarray
    relative: np.ndarray
    displacementMm: np.ndarray
    continuityIds: np.ndarray


def build_segment_safe_phase(
    raw_phase,
    timestamps,
    segment_ids,
    *,
    valid_mask=None,
    beam_keys=None,
    phase_sign: float = 1.0,
    discontinuity_rad: float = math.pi,
    gap_reset_sec: float = 1.0,
    reset_on_beam_switch: bool = True,
    carrier_frequency_ghz: float = 77.0,
) -> SegmentSafePhase:
    """Wrap and unwrap phase without crossing invalid lock boundaries."""
    raw = np.asarray(raw_phase, dtype=np.float64)
    times = np.asarray(timestamps, dtype=np.float64)
    segments = np.asarray(segment_ids)
    if raw.size != times.size or raw.size != segments.size:
        raise ValueError("phase, timestamp, and segment arrays must match")
    if phase_sign not in (-1, -1.0, 1, 1.0):
        raise ValueError("phase_sign must be 1 or -1")
    if discontinuity_rad <= 0:
        raise ValueError("discontinuity_rad must be positive")
    if carrier_frequency_ghz <= 0:
        raise ValueError("carrier_frequency_ghz must be positive")

    valid = (
        np.ones(raw.size, dtype=bool)
        if valid_mask is None
        else np.asarray(valid_mask, dtype=bool)
    )
    if valid.size != raw.size:
        raise ValueError("valid_mask must match phase length")
    keys = None if beam_keys is None else list(beam_keys)
    if keys is not None and len(keys) != raw.size:
        raise ValueError("beam_keys must match phase length")

    wrapped = np.angle(np.exp(1j * float(phase_sign) * raw))
    unwrapped = np.full(raw.size, np.nan, dtype=np.float64)
    relative = np.full(raw.size, np.nan, dtype=np.float64)
    continuity = np.full(raw.size, -1, dtype=np.int64)
    run_id = -1
    offset = 0.0
    baseline = 0.0
    previous_index = None

    for index in range(raw.size):
        if (
            not valid[index]
            or not np.isfinite(wrapped[index])
            or not np.isfinite(times[index])
        ):
            previous_index = None
            continue
        reset = previous_index is None
        if previous_index is not None:
            reset = bool(segments[index] != segments[previous_index])
            if gap_reset_sec > 0:
                reset = reset or bool(
                    times[index] - times[previous_index] > gap_reset_sec
                )
            if reset_on_beam_switch and keys is not None:
                reset = reset or bool(keys[index] != keys[previous_index])
        if reset:
            run_id += 1
            offset = 0.0
            unwrapped[index] = wrapped[index]
            baseline = unwrapped[index]
        else:
            delta = wrapped[index] - wrapped[previous_index]
            if delta > discontinuity_rad:
                offset -= 2.0 * math.pi
            elif delta < -discontinuity_rad:
                offset += 2.0 * math.pi
            unwrapped[index] = wrapped[index] + offset
        relative[index] = unwrapped[index] - baseline
        continuity[index] = run_id
        previous_index = index

    wavelength_mm = (
        299_792_458.0 / (float(carrier_frequency_ghz) * 1.0e9) * 1000.0
    )
    displacement = relative * wavelength_mm / (4.0 * math.pi)
    return SegmentSafePhase(
        wrapped=wrapped,
        unwrapped=unwrapped,
        relative=relative,
        displacementMm=displacement,
        continuityIds=continuity,
    )


@dataclass(frozen=True)
class ClassicalVitalAnalysis:
    breathingBpm: float | None
    heartBpm: float | None
    confidenceBreath: float
    confidenceHeart: float
    breathPeakPower: float
    heartPeakPower: float
    breathPeakSnr: float
    heartPeakSnr: float
    breathReason: str
    heartReason: str
    detrended: np.ndarray
    breathingFiltered: np.ndarray
    heartFiltered: np.ndarray
    frequencyHz: np.ndarray
    spectrumPower: np.ndarray
    heartFrequencyHz: np.ndarray
    heartSpectrumPower: np.ndarray
    heartCandidates: tuple["HeartPeakCandidate", ...] = ()
    heartWindowSecUsed: float = 0.0


@dataclass(frozen=True)
class HeartPeakCandidate:
    bpm: float
    frequencyHz: float
    power: float
    snr: float
    sharpness: float
    confidence: float
    harmonicPenalty: float
    persistenceScore: float
    totalScore: float
    qualityReason: str = "OK"


@dataclass
class HeartTrackerState:
    trackedBpm: float | None = None
    trackedScore: float = 0.0
    trackedConfidence: float = 0.0
    trackedSnr: float = 0.0
    trackedPower: float = 0.0
    trackedAt: float | None = None
    pendingBpm: float | None = None
    pendingSince: float | None = None
    pendingScore: float = 0.0
    rejectedBpm: float | None = None
    rejectedReason: str = ""
    holdReason: str = ""
    qualityReason: str = "COLLECTING"
    rawCandidateBpm: float | None = None
    candidateCount: int = 0
    switchPending: bool = False
    persistenceSec: float = 0.0


def _band_psd(
    signal: np.ndarray,
    fs: float,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(signal, dtype=np.float64)
    if values.size < 2:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    nfft = 1 << int(math.ceil(math.log2(max(values.size * 4, 256))))
    spectrum = np.fft.rfft(values * np.hanning(values.size), n=nfft)
    return (
        np.fft.rfftfreq(nfft, d=1.0 / fs),
        np.square(np.abs(spectrum)),
    )


def _local_peak_candidates(
    frequency_hz: np.ndarray,
    power: np.ndarray,
    low_hz: float,
    high_hz: float,
) -> list[tuple[int, float, float]]:
    mask = (frequency_hz >= low_hz) & (frequency_hz <= high_hz)
    indices = np.flatnonzero(mask)
    candidates: list[tuple[int, float, float]] = []
    for index in indices:
        left = power[index - 1] if index > 0 else -np.inf
        right = power[index + 1] if index + 1 < power.size else -np.inf
        if power[index] >= left and power[index] >= right:
            candidates.append((int(index), float(frequency_hz[index]), float(power[index])))
    return sorted(candidates, key=lambda item: item[2], reverse=True)


def _peak_metrics(
    frequency_hz: np.ndarray,
    power: np.ndarray,
    index: int,
    low_hz: float,
    high_hz: float,
    duration_sec: float,
) -> tuple[float, float, float]:
    mask = (frequency_hz >= low_hz) & (frequency_hz <= high_hz)
    band_indices = np.flatnonzero(mask)
    peak = float(power[index])
    exclusion = band_indices[np.abs(band_indices - int(index)) > 2]
    noise = (
        float(np.median(power[exclusion]))
        if exclusion.size
        else float(np.median(power[band_indices]))
    )
    snr = peak / max(noise, 1e-12)
    neighbors = power[max(0, index - 2) : min(power.size, index + 3)]
    sharpness = peak / max(float(np.mean(neighbors)), 1e-12)
    confidence = (
        0.55 * min(1.0, math.log10(max(snr, 1.0)) / 2.0)
        + 0.25 * min(1.0, max(0.0, sharpness - 1.0) / 2.0)
        + 0.20 * min(1.0, duration_sec / 60.0)
    )
    return float(snr), float(sharpness), float(np.clip(confidence, 0.0, 1.0))


def analyze_locked_vital_signal(
    signal: np.ndarray | list[float],
    fs: float,
    *,
    breath_window_sec: float | None = None,
    heart_window_sec: float | None = None,
    heart_top_k: int = 5,
) -> ClassicalVitalAnalysis:
    """Classical locked-beam breath/heart analysis without ML dependencies."""

    values = np.asarray(signal, dtype=np.float64)
    if values.size < 2:
        empty = np.asarray([], dtype=float)
        return ClassicalVitalAnalysis(
            breathingBpm=None,
            heartBpm=None,
            confidenceBreath=0.0,
            confidenceHeart=0.0,
            breathPeakPower=0.0,
            heartPeakPower=0.0,
            breathPeakSnr=0.0,
            heartPeakSnr=0.0,
            breathReason="insufficient locked duration",
            heartReason="insufficient locked duration",
            detrended=empty,
            breathingFiltered=empty,
            heartFiltered=empty,
            frequencyHz=empty,
            spectrumPower=empty,
            heartFrequencyHz=empty,
            heartSpectrumPower=empty,
        )
    duration_sec = values.size / float(fs)
    detrended = detrend_signal(values)
    breathing = bandpass_signal(
        detrended, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ
    )
    # Suppress the dominant respiratory component before looking for the much
    # smaller cardiac ripple. The heart band-pass then rejects residual drift.
    heart_input = detrended - breathing
    heart = bandpass_signal(heart_input, fs, HEART_LOW_HZ, HEART_HIGH_HZ)
    breath_samples = values.size
    if breath_window_sec is not None and breath_window_sec > 0:
        breath_samples = min(
            values.size, max(2, int(round(float(breath_window_sec) * fs)))
        )
    heart_samples = values.size
    if heart_window_sec is not None and heart_window_sec > 0:
        heart_samples = min(
            values.size, max(2, int(round(float(heart_window_sec) * fs)))
        )
    breath_psd_signal = detrended[-breath_samples:]
    heart_psd_signal = heart[-heart_samples:]
    frequency_hz, spectrum_power = _band_psd(breath_psd_signal, fs)
    heart_frequency_hz, heart_power_spectrum = _band_psd(
        heart_psd_signal, fs
    )

    breath_candidates = _local_peak_candidates(
        frequency_hz, spectrum_power, BREATH_LOW_HZ, BREATH_HIGH_HZ
    )
    breath_bpm = None
    breath_power = breath_snr = breath_confidence = 0.0
    breath_reason = "no clear breathing-band peak"
    if breath_candidates:
        index, frequency, breath_power = breath_candidates[0]
        breath_bpm = frequency * 60.0
        breath_snr, _, breath_confidence = _peak_metrics(
            frequency_hz,
            spectrum_power,
            index,
            BREATH_LOW_HZ,
            BREATH_HIGH_HZ,
            duration_sec,
        )
        breath_reason = (
            "clear breathing-band peak"
            if breath_confidence >= 0.20
            else "weak or broad breathing-band peak"
        )

    heart_candidates = _local_peak_candidates(
        heart_frequency_hz,
        heart_power_spectrum,
        HEART_LOW_HZ,
        HEART_HIGH_HZ,
    )
    scored_candidates: list[HeartPeakCandidate] = []
    harmonic_rejected = False
    heart_band_mask = (
        (heart_frequency_hz >= HEART_LOW_HZ)
        & (heart_frequency_hz <= HEART_HIGH_HZ)
    )
    heart_band_peak_power = (
        float(np.max(heart_power_spectrum[heart_band_mask]))
        if np.any(heart_band_mask)
        else 0.0
    )
    for candidate in heart_candidates:
        index, frequency, peak_power = candidate
        bpm = frequency * 60.0
        snr, sharpness, confidence = _peak_metrics(
            heart_frequency_hz,
            heart_power_spectrum,
            index,
            HEART_LOW_HZ,
            HEART_HIGH_HZ,
            heart_samples / float(fs),
        )
        harmonic_multiple = None
        if breath_bpm is not None:
            for multiple in (2, 3, 4):
                if abs(bpm - multiple * breath_bpm) <= 2.5:
                    harmonic_multiple = multiple
                    break
        lower_edge_penalty = 0.65 if frequency <= HEART_LOW_HZ + 0.08 else 1.0
        # Lower respiration harmonics are common false-heart peaks. The
        # fourth harmonic is penalized less aggressively because a plausible
        # adult heart rate can naturally coincide with it (for example,
        # 18 BPM breathing and 72 BPM heart rate).
        harmonic_penalty = (
            {2: 0.18, 3: 0.30, 4: 0.55}.get(harmonic_multiple, 1.0)
            if harmonic_multiple is not None
            else 1.0
        )
        harmonic_penalty *= lower_edge_penalty
        # SNR alone can rank tiny numerical side-lobes above a physically
        # meaningful peak when the local median noise floor is near zero.
        # Relative band power keeps those artifacts from taking over.
        relative_power = peak_power / max(heart_band_peak_power, 1e-12)
        score = confidence * math.log1p(snr) * math.sqrt(relative_power)
        score *= harmonic_penalty
        if harmonic_multiple is not None:
            harmonic_rejected = True
        reason = (
            "LIKELY_RESP_HARMONIC"
            if harmonic_multiple is not None
            else ("LOW_EDGE_LEAKAGE" if lower_edge_penalty < 1.0 else "OK")
        )
        scored_candidates.append(
            HeartPeakCandidate(
                bpm=float(bpm),
                frequencyHz=float(frequency),
                power=float(peak_power),
                snr=float(snr),
                sharpness=float(sharpness),
                confidence=float(confidence),
                harmonicPenalty=float(harmonic_penalty),
                persistenceScore=0.0,
                totalScore=float(score),
                qualityReason=reason,
            )
        )
    scored_candidates.sort(key=lambda item: item.totalScore, reverse=True)
    scored_candidates = scored_candidates[: max(1, int(heart_top_k))]

    heart_bpm = None
    heart_power = heart_snr = heart_confidence = 0.0
    heart_reason = "no clear heart-band peak"
    if scored_candidates:
        chosen_heart = scored_candidates[0]
        heart_bpm = chosen_heart.bpm
        heart_power = chosen_heart.power
        heart_snr = chosen_heart.snr
        _, _, heart_confidence = _peak_metrics(
            heart_frequency_hz,
            heart_power_spectrum,
            int(np.argmin(np.abs(heart_frequency_hz - chosen_heart.frequencyHz))),
            HEART_LOW_HZ,
            HEART_HIGH_HZ,
            heart_samples / float(fs),
        )
        if chosen_heart.qualityReason == "LIKELY_RESP_HARMONIC":
            heart_confidence *= 0.45
            heart_reason = (
                "respiration harmonic rejected; alternate heart peak selected"
                if chosen_heart.power < heart_band_peak_power
                else "likely respiration harmonic"
            )
        elif chosen_heart.qualityReason == "LOW_EDGE_LEAKAGE":
            heart_confidence *= 0.70
            heart_reason = "heart-band lower-edge leakage"
        elif heart_confidence < 0.16:
            heart_reason = "weak or broad heart-band peak"
        elif harmonic_rejected:
            heart_reason = "respiration harmonic rejected; alternate heart peak selected"
        else:
            heart_reason = "clear heart-band peak after respiration suppression"

    return ClassicalVitalAnalysis(
        breathingBpm=breath_bpm,
        heartBpm=heart_bpm,
        confidenceBreath=breath_confidence,
        confidenceHeart=heart_confidence,
        breathPeakPower=breath_power,
        heartPeakPower=heart_power,
        breathPeakSnr=breath_snr,
        heartPeakSnr=heart_snr,
        breathReason=breath_reason,
        heartReason=heart_reason,
        detrended=detrended,
        breathingFiltered=breathing,
        heartFiltered=heart,
        frequencyHz=frequency_hz,
        spectrumPower=spectrum_power,
        heartFrequencyHz=heart_frequency_hz,
        heartSpectrumPower=heart_power_spectrum,
        heartCandidates=tuple(scored_candidates),
        heartWindowSecUsed=heart_samples / float(fs),
    )


class VitalEstimatorBridge:
    """Maintain selected chest-beam phase and display state per IWR target."""

    def __init__(self, config: VitalEstimatorConfig | None = None):
        self.config = config or VitalEstimatorConfig()
        if self.config.fs <= 0:
            raise ValueError("fs must be positive")
        if self.config.analysisUpdateHz <= 0:
            raise ValueError("analysisUpdateHz must be positive")
        if min(
            self.config.displayHoldSec,
            self.config.minEstimationWindowSec,
            self.config.minVitalWindowSec,
            self.config.minHeartWindowSec,
            self.config.breathStableWindowSec,
            self.config.heartStableWindowSec,
            self.config.bpmSmoothingSec,
            self.config.breathMaxJumpBpmPerSec,
            self.config.heartMaxJumpBpmPerSec,
            self.config.heartPeakPersistenceSec,
            self.config.heartSwitchConfirmSec,
            self.config.heartSwitchMargin,
            self.config.heartMinSnr,
            self.config.heartMinConfidence,
            self.config.heartWindowSec,
            self.config.heartPreliminaryWindowSec,
            self.config.breathWindowSec,
            self.config.phasePlotWindowSec,
            self.config.mlMinWindowSec,
        ) < 0:
            raise ValueError("vital estimator durations must be non-negative")
        if self.config.heartTopKPeaks < 1:
            raise ValueError("heartTopKPeaks must be at least 1")
        if self.config.phaseSign not in (-1, -1.0, 1, 1.0):
            raise ValueError("phaseSign must be 1 or -1")
        if self.config.phaseUnwrapDiscontinuityRad <= 0:
            raise ValueError(
                "phaseUnwrapDiscontinuityRad must be positive"
            )
        if self.config.carrierFrequencyGhz <= 0:
            raise ValueError("carrierFrequencyGhz must be positive")

        max_seconds = max(
            self.config.bufferSeconds,
            self.config.phasePlotWindowSec,
            self.config.minHeartWindowSec,
            self.config.heartWindowSec,
        )
        max_samples = max(16, int(math.ceil(self.config.fs * max_seconds)))
        self._phase = defaultdict(lambda: deque(maxlen=max_samples))
        self._trace = defaultdict(lambda: deque(maxlen=max_samples))
        self._recent_bins = defaultdict(
            lambda: deque(maxlen=max(2, self.config.switchingWindowSamples))
        )
        self._last_selection_key: dict[int, tuple[int, float | None]] = {}
        self._last_phase_segment: dict[int, int | None] = {}
        self._last_phase_sample_time: dict[int, float] = {}
        self._last_source_frame: dict[int, int] = {}
        self._last_estimate: dict[int, VitalEstimate] = {}
        self._last_valid_estimate_time: dict[int, float] = {}
        self._smoothed_breath: dict[int, float] = {}
        self._smoothed_heart: dict[int, float] = {}
        self._last_rate_time: dict[tuple[int, str], float] = {}
        self._estimate_history = defaultdict(lambda: deque(maxlen=5))
        self._beam_switched_at: dict[int, float] = {}
        self._last_analysis_at: dict[int, float] = {}
        self._analysis_cache: dict[int, tuple[int, ClassicalVitalAnalysis]] = {}
        self._heart_candidate_history = defaultdict(
            lambda: deque(
                maxlen=max(
                    8,
                    int(
                        math.ceil(
                            self.config.analysisUpdateHz
                            * max(
                                self.config.heartPeakPersistenceSec,
                                self.config.heartSwitchConfirmSec,
                                1.0,
                            )
                            * 3.0
                        )
                    ),
                )
            )
        )
        self._heart_tracker: dict[int, HeartTrackerState] = {}
        self._ml_models, self._ml_notes = self._load_ml_models()

    def update(
        self,
        target_id: int,
        selection: BinSelection | None,
        monitoring_state: str,
        timestamp: float | None = None,
        source_frame_number: int | None = None,
    ) -> VitalEstimate:
        tid = int(target_id)
        sample_time = time.time() if timestamp is None else float(timestamp)
        if selection is None or selection.selectedAwrBin is None:
            return self._status_estimate(
                tid, "NO_BIN", "no valid AWR chest beam selected", sample_time
            )

        if monitoring_state not in ACTIVE_MONITORING_STATES:
            return self._status_estimate(
                tid,
                monitoring_state,
                "phase buffer preserved; no sample added while vitals are paused",
                sample_time,
            )

        selected_bin = int(selection.selectedAwrBin)
        selected_azimuth = selection.selectedAwrAzimuthDeg
        selection_key = (
            selected_bin,
            None if selected_azimuth is None else round(float(selected_azimuth), 3),
        )
        recent = self._recent_bins[tid]
        recent.append(selected_bin)
        prior_key = self._last_selection_key.get(tid)
        current_segment = selection.phaseSegmentId
        prior_segment = self._last_phase_segment.get(tid)
        gap_reset = bool(
            tid in self._last_phase_sample_time
            and self.config.phaseGapResetSec > 0
            and (
                source_frame_number is None
                or self._last_source_frame.get(tid) != int(source_frame_number)
            )
            and sample_time - self._last_phase_sample_time[tid]
            > self.config.phaseGapResetSec
        )
        segment_reset = bool(
            prior_segment is not None
            and current_segment is not None
            and prior_segment != current_segment
        )
        beam_reset = bool(
            self.config.phaseResetOnBeamSwitch
            and prior_key is not None
            and prior_key != selection_key
        )
        if beam_reset or segment_reset or gap_reset:
            # Different range/azimuth cells have unrelated phase offsets. Keep
            # the prior displayed BPM briefly, but start a clean phase window.
            # Long gaps and explicit phase-segment changes have the same rule.
            self._phase[tid].clear()
            self._trace[tid].clear()
            self._beam_switched_at[tid] = sample_time
            self._analysis_cache.pop(tid, None)
            self._last_analysis_at.pop(tid, None)
            self._heart_candidate_history[tid].clear()
            self._heart_tracker.pop(tid, None)
        self._last_selection_key[tid] = selection_key
        self._last_phase_segment[tid] = current_segment

        if self._switch_count(recent) > self.config.maxSwitchesInWindow:
            return self._status_estimate(
                tid,
                "BIN_SWITCHING",
                "selected chest beam is changing too frequently",
                sample_time,
            )

        phase = selection.selectedPhaseRad
        if phase is None:
            return self._status_estimate(
                tid, "NO_BIN", "selected chest beam has no phase", sample_time
            )
        if (
            self.config.requireLockedPhaseSegment
            and selection.phaseSegmentId is None
        ):
            return self._status_estimate(
                tid,
                "HOLD",
                "waiting for a valid locked FE03 phase segment",
                sample_time,
            )

        # A retained FE03 window may be reused during its stale timeout. Do not
        # turn one radar frame into repeated phase samples at the IWR rate.
        if source_frame_number is not None:
            source_frame = int(source_frame_number)
            if self._last_source_frame.get(tid) == source_frame:
                return self._status_estimate(
                    tid,
                    "HOLD",
                    "waiting for a new AWR frame; last estimate retained",
                    sample_time,
                )
            self._last_source_frame[tid] = source_frame

        self._phase[tid].append(float(phase))
        self._last_phase_sample_time[tid] = sample_time
        self._trace[tid].append(
            {
                "timestamp": sample_time,
                "binIndex": selected_bin,
                "rangeMeters": selection.selectedAwrRangeMeters,
                "azimuthDeg": selected_azimuth,
                "phaseRad": float(phase),
                "magnitude": selection.selectedMagnitude,
                "beamScore": selection.beamScore,
                "beamSwitchCount": selection.beamSwitchCount,
                "sourceFrameNumber": source_frame_number,
                "phaseUnwrapped": selection.lockedPhaseUnwrapped,
                "displacementMm": selection.displacementMm,
                "phaseSegmentId": selection.phaseSegmentId,
                "phaseSignalSource": selection.phaseSignalSource,
                "combinedBeamCount": selection.combinedBeamCount,
                "beamCombineMode": selection.beamCombineMode,
                "beamCombineConfidence": selection.beamCombineConfidence,
            }
        )

        sample_count = len(self._phase[tid])
        duration_sec = sample_count / self.config.fs
        analysis_interval = 1.0 / self.config.analysisUpdateHz
        last_analysis_at = self._last_analysis_at.get(tid, float("-inf"))
        readiness_samples = {
            int(math.ceil(self.config.fs * value))
            for value in (
                self.config.minEstimationWindowSec,
                self.config.minVitalWindowSec,
                self.config.minHeartWindowSec,
                self.config.breathStableWindowSec,
                self.config.heartStableWindowSec,
            )
            if value > 0
        }
        if (
            sample_count not in readiness_samples
            and sample_time - last_analysis_at < analysis_interval
            and tid in self._last_estimate
        ):
            return self._with_monitoring_state(
                self._last_estimate[tid], monitoring_state
            )

        phase_values = np.asarray(self._phase[tid], dtype=float)
        max_analysis_window = max(
            self.config.breathWindowSec,
            (
                self.config.heartPreliminaryWindowSec
                if duration_sec < self.config.heartWindowSec
                else self.config.heartWindowSec
            ),
            self.config.minEstimationWindowSec,
        )
        analysis_samples = min(
            phase_values.size,
            max(2, int(math.ceil(max_analysis_window * self.config.fs))),
        )
        analysis_values = phase_values[-analysis_samples:]
        raw = estimate_vitals_from_phase(
            list(analysis_values), fs=self.config.fs
        )
        analysis = analyze_locked_vital_signal(
            analysis_values,
            self.config.fs,
            breath_window_sec=self.config.breathWindowSec,
            heart_window_sec=(
                self.config.heartPreliminaryWindowSec
                if duration_sec < self.config.heartWindowSec
                else self.config.heartWindowSec
            ),
            heart_top_k=self.config.heartTopKPeaks,
        )
        self._last_analysis_at[tid] = sample_time
        self._analysis_cache[tid] = (analysis_samples, analysis)
        minimum_window = max(
            self.config.minEstimationWindowSec,
            min(self.config.minVitalWindowSec, self.config.minHeartWindowSec),
        )
        breath_ready = duration_sec >= max(
            minimum_window, self.config.minVitalWindowSec
        )
        heart_ready = duration_sec >= max(
            minimum_window, self.config.minHeartWindowSec
        )
        breath, breath_held = (
            self._stabilize_value(
                tid,
                analysis.breathingBpm,
                analysis.confidenceBreath,
                "breath",
                sample_time,
            )
            if breath_ready
            else (None, False)
        )
        heart_tracker = (
            self._track_heart_candidates(tid, analysis, sample_time)
            if heart_ready
            else HeartTrackerState(qualityReason="COLLECTING")
        )
        heart = heart_tracker.trackedBpm if heart_ready else None
        heart_held = bool(heart_ready and heart_tracker.holdReason)
        breath_state = self._estimate_state(
            duration_sec,
            breath_ready,
            analysis.confidenceBreath,
            self.config.breathStableWindowSec,
            breath_held,
        )
        heart_state = self._estimate_state(
            duration_sec,
            heart_ready,
            heart_tracker.trackedConfidence,
            self.config.heartStableWindowSec,
            heart_held,
        )

        quality = raw.quality_state
        notes = (
            f"breath: {analysis.breathReason}; heart: {analysis.heartReason}"
        )
        if not breath_ready:
            quality = "COLLECTING"
            notes = (
                f"breathing collecting: {duration_sec:.1f}/"
                f"{self.config.minVitalWindowSec:.1f}s"
            )
        elif not heart_ready:
            quality = "BREATH_READY_HEART_COLLECTING"
            notes = (
                f"heart collecting: {duration_sec:.1f}/"
                f"{self.config.minHeartWindowSec:.1f}s"
            )
        elif breath_state == "LOW_CONFIDENCE" or heart_state == "LOW_CONFIDENCE":
            quality = "LOW_CONFIDENCE"
            notes = "locked phase estimate available but spectral confidence is low"
        elif breath_held or heart_held:
            quality = "HOLD"
            notes = "rate jump/low-confidence update rejected; last good BPM retained"
        elif heart_state == "PRELIMINARY_30S":
            quality = "PRELIMINARY_30S"
            notes = "30-second preliminary breath/heart estimate"

        ml_breath, ml_heart = self._predict_ml(
            duration_sec,
            analysis,
            breath,
            heart,
            tid,
        )

        if monitoring_state == MONITORING_POSE_GRACE:
            quality = "MONITORING_POSE_GRACE"
            notes = "vitals active during brief pose-label grace" + (
                f"; {notes}" if notes else ""
            )
        elif monitoring_state == SEATED_LOCK:
            quality = "SEATED_LOCK"
            notes = "stable seated lock active; phase sampling continues" + (
                f"; {notes}" if notes else ""
            )

        estimate = VitalEstimate(
            breathingBpm=breath,
            heartBpm=heart,
            quality=quality,
            motionDetected=raw.motion_detected,
            confidenceBreath=analysis.confidenceBreath if breath_ready else 0.0,
            confidenceHeart=(
                heart_tracker.trackedConfidence if heart_ready else 0.0
            ),
            notes=notes,
            estimateAgeSec=0.0,
            held=False,
            breathCollecting=not breath_ready,
            heartCollecting=not heart_ready,
            breathEstimateState=breath_state,
            heartEstimateState=heart_state,
            breathingBpmMl=ml_breath,
            heartBpmMl=ml_heart,
            mlEnabled=bool(self._ml_models),
            mlNotes=self._ml_notes,
            breathPeakSnr=analysis.breathPeakSnr,
            heartPeakSnr=heart_tracker.trackedSnr,
            breathQualityReason=analysis.breathReason,
            heartQualityReason=heart_tracker.qualityReason,
            phaseSignalSource=selection.phaseSignalSource,
            rawHeartCandidateBpm=heart_tracker.rawCandidateBpm,
            trackedHeartBpm=heart_tracker.trackedBpm,
            displayedHeartBpm=heart,
            heartCandidateCount=heart_tracker.candidateCount,
            heartSwitchPending=heart_tracker.switchPending,
            heartSwitchCandidateBpm=heart_tracker.pendingBpm,
            heartHoldReason=heart_tracker.holdReason,
            heartWindowSecUsed=analysis.heartWindowSecUsed,
            heartPeakPersistenceSec=heart_tracker.persistenceSec,
            heartRejectedCandidateBpm=heart_tracker.rejectedBpm,
            heartRejectedReason=heart_tracker.rejectedReason,
        )
        if breath is not None or heart is not None:
            self._last_valid_estimate_time[tid] = sample_time
        self._last_estimate[tid] = estimate
        return estimate

    @staticmethod
    def _with_monitoring_state(
        estimate: VitalEstimate, monitoring_state: str
    ) -> VitalEstimate:
        if monitoring_state == MONITORING_POSE_GRACE:
            return replace(
                estimate,
                quality="MONITORING_POSE_GRACE",
                notes=(
                    "vitals active during brief pose-label grace"
                    + (f"; {estimate.notes}" if estimate.notes else "")
                ),
            )
        if monitoring_state == SEATED_LOCK:
            return replace(
                estimate,
                quality="SEATED_LOCK",
                notes=(
                    "stable seated lock active; phase sampling continues"
                    + (f"; {estimate.notes}" if estimate.notes else "")
                ),
            )
        return estimate

    def sample_count(self, target_id: int) -> int:
        return len(self._phase[int(target_id)])

    def debug_trace(self, target_id: int) -> list[dict]:
        return list(self._trace[int(target_id)])

    def diagnostics(
        self, target_id: int, timestamp: float | None = None
    ) -> PhaseDiagnostics:
        tid = int(target_id)
        now = time.time() if timestamp is None else float(timestamp)
        raw_phase = np.asarray(self._phase[tid], dtype=np.float64)
        trace = list(self._trace[tid])
        count = int(raw_phase.size)
        timestamps = np.asarray(
            [item.get("timestamp", np.nan) for item in trace],
            dtype=np.float64,
        )
        if count and np.all(np.isfinite(timestamps)):
            time_sec = timestamps - timestamps[0]
        else:
            time_sec = (
                np.arange(count, dtype=np.float64) / self.config.fs
                if count
                else np.asarray([], dtype=np.float64)
            )
        segment_ids = np.asarray(
            [
                0
                if item.get("phaseSegmentId") is None
                else int(item["phaseSegmentId"])
                for item in trace
            ],
            dtype=np.int64,
        )
        beam_keys = [
            (
                item.get("binIndex"),
                None
                if item.get("azimuthDeg") is None
                else round(float(item["azimuthDeg"]), 3),
            )
            for item in trace
        ]
        phase_result = build_segment_safe_phase(
            raw_phase,
            timestamps if count and np.all(np.isfinite(timestamps)) else time_sec,
            segment_ids,
            valid_mask=np.isfinite(raw_phase),
            beam_keys=beam_keys,
            phase_sign=self.config.phaseSign,
            discontinuity_rad=self.config.phaseUnwrapDiscontinuityRad,
            gap_reset_sec=self.config.phaseGapResetSec,
            reset_on_beam_switch=self.config.phaseResetOnBeamSwitch,
            carrier_frequency_ghz=self.config.carrierFrequencyGhz,
        )
        wrapped_phase = phase_result.wrapped
        tracked_unwrapped = phase_result.unwrapped
        relative = phase_result.relative
        displacement = phase_result.displacementMm
        continuity_ids = phase_result.continuityIds
        # Never filter or FFT across beam changes. Each lock segment has an
        # independent phase origin, so joining segments creates false motion
        # and spectral peaks.
        breathing = np.full(count, np.nan, dtype=np.float64)
        heart = np.full(count, np.nan, dtype=np.float64)
        analysis_signal = np.asarray([], dtype=np.float64)
        analysis_mask = np.zeros(count, dtype=bool)
        analysis = analyze_locked_vital_signal([], self.config.fs)
        if count:
            current_segment = continuity_ids[-1]
            segment_mask = continuity_ids == current_segment
            segment_indices = np.flatnonzero(segment_mask)
            max_window_sec = max(
                self.config.breathWindowSec,
                self.config.heartWindowSec,
                self.config.minEstimationWindowSec,
            )
            max_window_samples = max(
                2, int(math.ceil(max_window_sec * self.config.fs))
            )
            analysis_indices = segment_indices[-max_window_samples:]
            analysis_mask[analysis_indices] = True
            segment_displacement = displacement[analysis_mask]
            if segment_displacement.size and np.all(np.isfinite(segment_displacement)):
                analysis_signal = segment_displacement
            else:
                analysis_signal = relative[analysis_mask]
            cached = self._analysis_cache.get(tid)
            if cached is not None and cached[0] == analysis_signal.size:
                analysis = cached[1]
            else:
                analysis = analyze_locked_vital_signal(
                    analysis_signal,
                    self.config.fs,
                    breath_window_sec=self.config.breathWindowSec,
                    heart_window_sec=(
                        self.config.heartPreliminaryWindowSec
                        if segment_indices.size / self.config.fs
                        < self.config.heartWindowSec
                        else self.config.heartWindowSec
                    ),
                    heart_top_k=self.config.heartTopKPeaks,
                )
                self._analysis_cache[tid] = (int(analysis_signal.size), analysis)
            breathing[analysis_mask] = analysis.breathingFiltered
            heart[analysis_mask] = analysis.heartFiltered

        frequency_hz = analysis.frequencyHz
        spectrum_power = analysis.spectrumPower
        analysis_count = int(analysis_signal.size)
        breath_bpm = analysis.breathingBpm
        tracker = self._heart_tracker.get(tid, HeartTrackerState())
        heart_bpm = tracker.trackedBpm
        breath_power = analysis.breathPeakPower
        heart_power = analysis.heartPeakPower
        latest = trace[-1] if trace else {}
        switched_at = self._beam_switched_at.get(tid)
        switched_recently = bool(
            switched_at is not None and now - switched_at <= 5.0
        )
        duration_sec = (
            int(np.count_nonzero(continuity_ids == continuity_ids[-1]))
            / self.config.fs
            if count
            else 0.0
        )
        quality = "COLLECTING"
        breath_ready = duration_sec >= max(
            self.config.minEstimationWindowSec,
            self.config.minVitalWindowSec,
        )
        heart_ready = duration_sec >= max(
            self.config.minEstimationWindowSec,
            self.config.minHeartWindowSec,
        )
        breath_confidence = analysis.confidenceBreath
        heart_confidence = tracker.trackedConfidence
        breath_state = self._estimate_state(
            duration_sec,
            breath_ready,
            breath_confidence,
            self.config.breathStableWindowSec,
            False,
        )
        heart_state = self._estimate_state(
            duration_sec,
            heart_ready,
            heart_confidence,
            self.config.heartStableWindowSec,
            bool(tracker.holdReason),
        )
        if breath_ready and heart_ready:
            quality = (
                "STABLE"
                if breath_state == "STABLE" and heart_state == "STABLE"
                else "PRELIMINARY_30S"
            )
        elif breath_ready:
            quality = "BREATH_READY_HEART_COLLECTING"

        return PhaseDiagnostics(
            targetId=tid,
            timestamp=now,
            sampleCount=count,
            bufferLengthSec=duration_sec,
            effectiveSampleRateHz=self.config.fs,
            timeSec=time_sec,
            rawPhase=wrapped_phase,
            unwrappedPhase=tracked_unwrapped,
            relativePhase=relative,
            displacementMm=displacement,
            phaseSegmentIds=segment_ids,
            breathingFiltered=breathing,
            heartFiltered=heart,
            frequencyHz=frequency_hz,
            spectrumPower=spectrum_power,
            breathPeakBpm=breath_bpm,
            heartPeakBpm=heart_bpm,
            breathPeakPower=breath_power,
            heartPeakPower=heart_power,
            breathConfidence=breath_confidence,
            heartConfidence=heart_confidence,
            quality=quality,
            selectedRangeBin=latest.get("binIndex"),
            selectedAzimuthDeg=latest.get("azimuthDeg"),
            selectedMagnitude=latest.get("magnitude"),
            selectedPhaseRad=latest.get("phaseRad"),
            beamSwitchedRecently=switched_recently,
            phaseValid=bool(count and latest.get("phaseSegmentId") is not None),
            phaseSegmentId=latest.get("phaseSegmentId"),
            validLockedDurationSec=duration_sec,
            breathEstimateState=breath_state,
            heartEstimateState=heart_state,
            breathPeakSnr=analysis.breathPeakSnr,
            heartPeakSnr=tracker.trackedSnr,
            breathQualityReason=analysis.breathReason,
            heartQualityReason=tracker.qualityReason,
            phaseSignalSource=latest.get(
                "phaseSignalSource", "single_locked_beam"
            ),
            combinedBeamCount=int(latest.get("combinedBeamCount", 1) or 1),
            beamCombineMode=latest.get("beamCombineMode", "single"),
            beamCombineConfidence=float(
                latest.get("beamCombineConfidence", 0.0) or 0.0
            ),
            heartFrequencyHz=analysis.heartFrequencyHz,
            heartSpectrumPower=analysis.heartSpectrumPower,
            heartCandidateBpms=np.asarray(
                [candidate.bpm for candidate in analysis.heartCandidates],
                dtype=np.float64,
            ),
            heartCandidatePowers=np.asarray(
                [candidate.power for candidate in analysis.heartCandidates],
                dtype=np.float64,
            ),
            heartCandidateSnrs=np.asarray(
                [candidate.snr for candidate in analysis.heartCandidates],
                dtype=np.float64,
            ),
            heartCandidateScores=np.asarray(
                [candidate.totalScore for candidate in analysis.heartCandidates],
                dtype=np.float64,
            ),
            rawHeartCandidateBpm=tracker.rawCandidateBpm,
            trackedHeartBpm=tracker.trackedBpm,
            displayedHeartBpm=tracker.trackedBpm,
            heartCandidateCount=tracker.candidateCount,
            heartSwitchPending=tracker.switchPending,
            heartSwitchCandidateBpm=tracker.pendingBpm,
            heartHoldReason=tracker.holdReason,
            heartWindowSecUsed=analysis.heartWindowSecUsed,
            heartPeakPersistenceSec=tracker.persistenceSec,
            heartRejectedCandidateBpm=tracker.rejectedBpm,
            heartRejectedReason=tracker.rejectedReason,
            phaseContinuityIds=continuity_ids,
        )

    def _status_estimate(
        self, target_id: int, quality: str, notes: str, now: float
    ) -> VitalEstimate:
        prior = self._last_estimate.get(target_id)
        valid_at = self._last_valid_estimate_time.get(target_id)
        age = None if valid_at is None else max(0.0, now - valid_at)
        can_hold = (
            prior is not None
            and age is not None
            and age <= self.config.displayHoldSec
        )
        if not can_hold:
            return VitalEstimate(
                quality=quality,
                notes=notes,
                estimateAgeSec=age,
                held=False,
            )
        return VitalEstimate(
            breathingBpm=prior.breathingBpm,
            heartBpm=prior.heartBpm,
            quality=f"{quality}_HOLD",
            motionDetected=prior.motionDetected,
            confidenceBreath=prior.confidenceBreath,
            confidenceHeart=prior.confidenceHeart,
            notes=f"{notes}; displayed estimate held for {age:.1f}s",
            estimateAgeSec=age,
            held=True,
            breathCollecting=prior.breathCollecting,
            heartCollecting=prior.heartCollecting,
            breathEstimateState="HOLD",
            heartEstimateState="HOLD",
            breathingBpmMl=prior.breathingBpmMl,
            heartBpmMl=prior.heartBpmMl,
            mlEnabled=prior.mlEnabled,
            mlNotes=prior.mlNotes,
            breathPeakSnr=prior.breathPeakSnr,
            heartPeakSnr=prior.heartPeakSnr,
            breathQualityReason=prior.breathQualityReason,
            heartQualityReason=prior.heartQualityReason,
            phaseSignalSource=prior.phaseSignalSource,
            rawHeartCandidateBpm=prior.rawHeartCandidateBpm,
            trackedHeartBpm=prior.trackedHeartBpm,
            displayedHeartBpm=prior.displayedHeartBpm,
            heartCandidateCount=prior.heartCandidateCount,
            heartSwitchPending=prior.heartSwitchPending,
            heartSwitchCandidateBpm=prior.heartSwitchCandidateBpm,
            heartHoldReason=prior.heartHoldReason,
            heartWindowSecUsed=prior.heartWindowSecUsed,
            heartPeakPersistenceSec=prior.heartPeakPersistenceSec,
            heartRejectedCandidateBpm=prior.heartRejectedCandidateBpm,
            heartRejectedReason=prior.heartRejectedReason,
        )

    def _track_heart_candidates(
        self,
        target_id: int,
        analysis: ClassicalVitalAnalysis,
        timestamp: float,
    ) -> HeartTrackerState:
        """Track one persistent heart peak without blending unrelated peaks."""

        tid = int(target_id)
        history = self._heart_candidate_history[tid]
        history.append((float(timestamp), tuple(analysis.heartCandidates)))
        cutoff = timestamp - max(
            self.config.heartPeakPersistenceSec,
            self.config.heartSwitchConfirmSec,
            1.0,
        ) * 2.0
        while history and history[0][0] < cutoff:
            history.popleft()

        scored: list[HeartPeakCandidate] = []
        tolerance_bpm = 3.0
        for candidate in analysis.heartCandidates:
            matching_times = [
                observed_at
                for observed_at, candidates in history
                if any(
                    abs(observed.bpm - candidate.bpm) <= tolerance_bpm
                    for observed in candidates
                )
            ]
            persistence_sec = (
                max(0.0, timestamp - min(matching_times))
                if matching_times
                else 0.0
            )
            persistence_score = min(
                1.0,
                persistence_sec
                / max(self.config.heartPeakPersistenceSec, 1e-6),
            )
            scored.append(
                replace(
                    candidate,
                    persistenceScore=persistence_score,
                    totalScore=(
                        candidate.totalScore
                        * (0.65 + 0.35 * persistence_score)
                    ),
                )
            )
        scored.sort(key=lambda item: item.totalScore, reverse=True)

        state = self._heart_tracker.setdefault(tid, HeartTrackerState())
        state.candidateCount = len(scored)
        state.rawCandidateBpm = scored[0].bpm if scored else None
        state.rejectedBpm = None
        state.rejectedReason = ""
        state.holdReason = ""
        state.switchPending = False

        def acceptable(candidate: HeartPeakCandidate) -> bool:
            harmonic_extra = (
                candidate.qualityReason == "LIKELY_RESP_HARMONIC"
            )
            return bool(
                candidate.snr
                >= self.config.heartMinSnr * (1.5 if harmonic_extra else 1.0)
                and candidate.confidence
                >= self.config.heartMinConfidence
                + (0.15 if harmonic_extra else 0.0)
            )

        if not scored:
            state.holdReason = "HOLD_LAST_GOOD" if state.trackedBpm else "LOW_SNR"
            state.qualityReason = state.holdReason
            return state

        best = scored[0]
        state.persistenceSec = (
            best.persistenceScore * self.config.heartPeakPersistenceSec
        )
        if state.trackedBpm is None:
            if acceptable(best):
                self._accept_heart_candidate(state, best, timestamp)
                state.qualityReason = (
                    "LIKELY_RESP_HARMONIC"
                    if best.qualityReason == "LIKELY_RESP_HARMONIC"
                    else "OK"
                )
            else:
                state.rejectedBpm = best.bpm
                state.rejectedReason = (
                    "LIKELY_RESP_HARMONIC"
                    if best.qualityReason == "LIKELY_RESP_HARMONIC"
                    else ("LOW_SNR" if best.snr < self.config.heartMinSnr else "WEAK_PEAK")
                )
                state.qualityReason = state.rejectedReason
            return state

        nearby = min(
            scored,
            key=lambda item: abs(item.bpm - float(state.trackedBpm)),
        )
        if (
            abs(nearby.bpm - float(state.trackedBpm)) <= 8.0
            and acceptable(nearby)
        ):
            elapsed = max(
                timestamp
                - (
                    state.trackedAt
                    if state.trackedAt is not None
                    else timestamp
                ),
                1.0 / self.config.fs,
            )
            allowed_jump = self.config.heartMaxJumpBpmPerSec * elapsed
            if abs(nearby.bpm - float(state.trackedBpm)) <= max(
                allowed_jump, 3.0
            ):
                # Smooth only within the same spectral peak. Never blend a
                # distant candidate into the currently displayed heart rate.
                alpha = min(
                    0.35,
                    1.0
                    - math.exp(
                        -elapsed / max(self.config.bpmSmoothingSec, 1e-6)
                    ),
                )
                state.trackedBpm = float(
                    state.trackedBpm
                    + alpha * (nearby.bpm - state.trackedBpm)
                )
                state.trackedScore = nearby.totalScore
                state.trackedConfidence = nearby.confidence
                state.trackedSnr = nearby.snr
                state.trackedPower = nearby.power
                state.trackedAt = timestamp
                state.pendingBpm = None
                state.pendingSince = None
                state.pendingScore = 0.0
                state.qualityReason = (
                    "LIKELY_RESP_HARMONIC"
                    if nearby.qualityReason == "LIKELY_RESP_HARMONIC"
                    else "OK"
                )
                return state

        if not acceptable(best):
            state.rejectedBpm = best.bpm
            state.rejectedReason = (
                "LIKELY_RESP_HARMONIC"
                if best.qualityReason == "LIKELY_RESP_HARMONIC"
                else ("LOW_SNR" if best.snr < self.config.heartMinSnr else "WEAK_PEAK")
            )
            state.holdReason = "HOLD_LAST_GOOD"
            state.qualityReason = state.rejectedReason
            return state

        if (
            state.pendingBpm is None
            or abs(best.bpm - state.pendingBpm) > tolerance_bpm
        ):
            state.pendingBpm = best.bpm
            state.pendingSince = timestamp
            state.pendingScore = best.totalScore
        else:
            state.pendingScore = max(state.pendingScore, best.totalScore)
        pending_sec = max(
            0.0,
            timestamp
            - (
                state.pendingSince
                if state.pendingSince is not None
                else timestamp
            ),
        )
        state.persistenceSec = max(
            state.persistenceSec,
            pending_sec,
        )
        state.switchPending = True
        state.holdReason = "SWITCH_PENDING"
        state.qualityReason = "SWITCH_PENDING"

        score_margin_met = (
            best.totalScore
            >= max(state.trackedScore, 1e-9) * self.config.heartSwitchMargin
        )
        tracked_peak_missing = abs(
            nearby.bpm - float(state.trackedBpm)
        ) > 8.0
        persistent_replacement = bool(
            tracked_peak_missing
            and best.persistenceScore >= 1.0
            and best.snr >= self.config.heartMinSnr * 1.5
        )
        if (
            pending_sec >= self.config.heartSwitchConfirmSec
            and (score_margin_met or persistent_replacement)
        ):
            self._accept_heart_candidate(state, best, timestamp)
            state.qualityReason = (
                "LIKELY_RESP_HARMONIC"
                if best.qualityReason == "LIKELY_RESP_HARMONIC"
                else "OK"
            )
            return state

        state.rejectedBpm = best.bpm
        state.rejectedReason = (
            "PEAK_NOT_PERSISTENT"
            if pending_sec < self.config.heartSwitchConfirmSec
            else "REJECTED_JUMP"
        )
        return state

    @staticmethod
    def _accept_heart_candidate(
        state: HeartTrackerState,
        candidate: HeartPeakCandidate,
        timestamp: float,
    ) -> None:
        state.trackedBpm = candidate.bpm
        state.trackedScore = candidate.totalScore
        state.trackedConfidence = candidate.confidence
        state.trackedSnr = candidate.snr
        state.trackedPower = candidate.power
        state.trackedAt = timestamp
        state.pendingBpm = None
        state.pendingSince = None
        state.pendingScore = 0.0
        state.switchPending = False
        state.holdReason = ""

    def _stabilize_value(
        self,
        target_id: int,
        value: float | None,
        confidence: float,
        kind: str,
        timestamp: float,
    ) -> tuple[float | None, bool]:
        if value is None or not math.isfinite(float(value)):
            previous = (
                self._smoothed_breath
                if kind == "breath"
                else self._smoothed_heart
            ).get(target_id)
            return previous, previous is not None
        store = self._smoothed_breath if kind == "breath" else self._smoothed_heart
        current = float(value)
        previous = store.get(target_id)
        if previous is None or self.config.bpmSmoothingSec <= 0:
            store[target_id] = current
            self._last_rate_time[(target_id, kind)] = timestamp
            self._estimate_history[(target_id, kind)].append(current)
            return current, False
        last_time = self._last_rate_time.get((target_id, kind), timestamp - 1.0)
        elapsed = max(timestamp - last_time, 1.0 / self.config.fs)
        max_jump_rate = (
            self.config.breathMaxJumpBpmPerSec
            if kind == "breath"
            else self.config.heartMaxJumpBpmPerSec
        )
        if (
            abs(current - previous) > max_jump_rate * elapsed
            and confidence < 0.75
        ):
            return previous, True
        if confidence < (0.08 if kind == "heart" else 0.10):
            return previous, True
        history = self._estimate_history[(target_id, kind)]
        history.append(current)
        current = float(np.median(np.asarray(history, dtype=float)))
        alpha = 1.0 - math.exp(
            -elapsed / max(self.config.bpmSmoothingSec, 1e-6)
        )
        smoothed = previous + alpha * (current - previous)
        store[target_id] = smoothed
        self._last_rate_time[(target_id, kind)] = timestamp
        return smoothed, False

    @staticmethod
    def _estimate_state(
        duration_sec: float,
        ready: bool,
        confidence: float,
        stable_window_sec: float,
        held: bool,
    ) -> str:
        if not ready:
            return "COLLECTING"
        if held:
            return "HOLD"
        if confidence < 0.08:
            return "LOW_CONFIDENCE"
        # The first estimate at the threshold is still preliminary. It becomes
        # stable only after accumulating data beyond the configured window.
        if duration_sec <= stable_window_sec:
            return "PRELIMINARY_30S"
        return "STABLE"

    @staticmethod
    def _peak_snr(
        frequencies: np.ndarray,
        power: np.ndarray,
        low_hz: float,
        high_hz: float,
    ) -> float:
        mask = (frequencies >= low_hz) & (frequencies <= high_hz)
        band = np.asarray(power[mask], dtype=float)
        if band.size == 0:
            return 0.0
        peak = float(np.max(band))
        noise = float(np.median(band))
        return peak / max(noise, 1e-12)

    def _load_ml_models(self):
        if not self.config.enableVitalMl or not self.config.vitalModelDir:
            return {}, "ML disabled; classical locked-phase estimator active"
        model_dir = Path(self.config.vitalModelDir).expanduser()
        models = {}
        for name, filename in (
            ("heart", "heart_rate_model.pkl"),
            ("breath", "breath_rate_model.pkl"),
        ):
            path = model_dir / filename
            if path.exists():
                try:
                    with path.open("rb") as handle:
                        models[name] = pickle.load(handle)
                except Exception as exc:
                    return {}, f"ML model load failed: {exc}"
        if not models:
            return {}, f"no baseline models found in {model_dir}"
        return models, f"loaded optional models from {model_dir}"

    def _predict_ml(self, duration_sec, raw, breath, heart, target_id):
        if not self._ml_models or duration_sec < self.config.mlMinWindowSec:
            return None, None
        trace = list(self._trace[target_id])
        try:
            from vital_model_training.features import extract_features

            phase = np.asarray(
                [float(item.get("phaseRad", 0.0)) for item in trace], dtype=float
            )
            unwrapped = np.unwrap(phase)
            displacement = np.asarray(
                [
                    float(item.get("displacementMm"))
                    if item.get("displacementMm") is not None
                    else float(unwrapped[index])
                    for index, item in enumerate(trace)
                ],
                dtype=float,
            )
            magnitude = np.asarray(
                [float(item.get("magnitude", 0.0) or 0.0) for item in trace]
            )
            range_m = np.asarray(
                [float(item.get("rangeMeters", 0.0) or 0.0) for item in trace]
            )
            azimuth = np.asarray(
                [float(item.get("azimuthDeg", 0.0) or 0.0) for item in trace]
            )
            features, _ = extract_features(
                displacement,
                phase,
                unwrapped,
                magnitude,
                range_m,
                azimuth,
                self.config.fs,
                {
                    "window_sec": duration_sec,
                    "beam_lock_duration_sec": duration_sec,
                    "beam_switch_count": 0.0,
                    "fe03_active_fraction": 1.0,
                    "seated_fraction": 1.0,
                },
            )
        except Exception:
            features = {
                "breath_peak_bpm": 0.0 if breath is None else float(breath),
                "heart_peak_bpm": 0.0 if heart is None else float(heart),
                "phase_variance": float(np.var(self._phase[target_id])),
                "window_sec": float(duration_sec),
            }
        features.update(
            {
                "breath_confidence": float(raw.confidenceBreath),
                "heart_confidence": float(raw.confidenceHeart),
                "valid_locked_duration_sec": float(duration_sec),
            }
        )

        def predict(name):
            artifact = self._ml_models.get(name)
            if artifact is None:
                return None
            model = artifact.get("model", artifact) if isinstance(artifact, dict) else artifact
            columns = (
                artifact.get("feature_columns", list(features))
                if isinstance(artifact, dict)
                else list(features)
            )
            vector = np.asarray(
                [[float(features.get(column, 0.0)) for column in columns]],
                dtype=float,
            )
            return float(model.predict(vector)[0])

        try:
            return predict("breath"), predict("heart")
        except Exception as exc:
            self._ml_notes = f"ML inference failed; classical retained: {exc}"
            return None, None

    @staticmethod
    def _peak_in_band(
        frequencies: np.ndarray,
        power: np.ndarray,
        low_hz: float,
        high_hz: float,
    ) -> tuple[float | None, float]:
        mask = (frequencies >= low_hz) & (frequencies <= high_hz)
        if not np.any(mask):
            return None, 0.0
        band_frequency = frequencies[mask]
        band_power = power[mask]
        if band_power.size == 0 or float(np.max(band_power)) <= 0:
            return None, 0.0
        peak_index = int(np.argmax(band_power))
        return (
            float(band_frequency[peak_index] * 60.0),
            float(band_power[peak_index]),
        )

    @staticmethod
    def _switch_count(bins: deque[int]) -> int:
        values = list(bins)
        return sum(left != right for left, right in zip(values, values[1:]))
