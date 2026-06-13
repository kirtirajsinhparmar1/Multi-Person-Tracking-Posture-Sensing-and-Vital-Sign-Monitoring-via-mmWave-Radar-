from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TwenteSampleInfo:
    root: str
    files_by_kind: dict[str, list[str]] = field(default_factory=dict)
    sample_rate_hz: float | None = None
    radar_config_path: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class VitalReference:
    source_path: str | None = None
    breathing_bpm: float | None = None
    heart_bpm: float | None = None
    timestamp_s: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalQuality:
    num_samples: int
    duration_s: float | None = None
    finite_fraction: float = 0.0
    detrended_std: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class VitalEstimate:
    breathing_bpm: float | None
    heart_bpm: float | None
    breathing_peak_hz: float | None
    heart_peak_hz: float | None
    fs_hz: float
    duration_s: float
    quality: SignalQuality
