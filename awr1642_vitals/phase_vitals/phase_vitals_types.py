from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class PhaseTraceSample:
    frame: Optional[int] = None
    time_s: Optional[float] = None
    phase_rad: Optional[float] = None
    i_value: Optional[float] = None
    q_value: Optional[float] = None
    range_bin: Optional[int] = None
    range_m: Optional[float] = None
    magnitude: Optional[float] = None
    snr_like: Optional[float] = None


@dataclass
class PhaseTraceWindow:
    samples: List[PhaseTraceSample] = field(default_factory=list)
    fs_hz: Optional[float] = None
    source_path: Optional[str] = None


@dataclass
class MotionMetrics:
    motion_detected: bool
    max_abs_phase_step_rad: float
    phase_step_std_rad: float
    phase_step_mad_rad: float
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VitalQuality:
    quality_state: str
    confidence_breath: float
    confidence_heart: float
    motion_detected: bool
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VitalEstimates:
    breathing_rate_fft_bpm: Optional[float]
    breathing_rate_xcorr_bpm: Optional[float]
    breathing_rate_peak_count_bpm: Optional[float]
    heart_rate_fft_bpm: Optional[float]
    heart_rate_fft_4hz_bpm: Optional[float]
    heart_rate_xcorr_bpm: Optional[float]
    heart_rate_peak_count_bpm: Optional[float]
    confidence_breath: float
    confidence_heart: float
    breath_energy: float
    heart_energy: float
    motion_detected: bool
    quality_state: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
