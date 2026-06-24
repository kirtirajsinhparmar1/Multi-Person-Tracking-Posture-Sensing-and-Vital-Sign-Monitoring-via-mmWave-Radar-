from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Iterable

import numpy as np


BREATH_BAND_HZ = (0.1, 0.5)
HEART_BAND_HZ = (0.8, 2.0)
ACTIVE_BEAM_STATES = {"BEAM_LOCKED", "BEAM_HOLD"}
ACTIVE_MONITORING_STATES = {
    "MONITORING",
    "MONITORING_POSE_GRACE",
    "SEATED_LOCK",
}


def as_float(value, default=float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_trace(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def elapsed_seconds(rows: list[dict[str, str]]) -> np.ndarray:
    elapsed = np.asarray(
        [as_float(row.get("elapsedSec")) for row in rows], dtype=float
    )
    if np.all(np.isfinite(elapsed)):
        return elapsed
    timestamp = np.asarray(
        [as_float(row.get("timestamp")) for row in rows], dtype=float
    )
    finite = timestamp[np.isfinite(timestamp)]
    if finite.size:
        timestamp -= finite[0]
    return timestamp


def valid_locked_row(row: dict[str, str]) -> bool:
    beam_ok = row.get("beamState", "") in ACTIVE_BEAM_STATES
    monitor = row.get("monitoringState") or row.get("gateState", "")
    posture = (
        row.get("gatePosture")
        or row.get("stablePosture")
        or row.get("rawPosture", "")
    )
    stream = row.get("fe03StreamState", "")
    return (
        beam_ok
        and as_bool(row.get("phaseValid"))
        and monitor in ACTIVE_MONITORING_STATES
        # MONITORING_POSE_GRACE is intentionally usable: the seated gate has
        # already accepted this short classifier flicker. Hard non-seated
        # postures remain excluded.
        and posture not in {"LYING", "FALLING"}
        and stream not in {"FE03_LOST", "LOST"}
        and math.isfinite(as_float(row.get("phaseSegmentId")))
        and math.isfinite(as_float(row.get("displacementMm")))
    )


def infer_sample_rate(time_sec: np.ndarray, fallback: float = 10.0) -> float:
    differences = np.diff(time_sec[np.isfinite(time_sec)])
    differences = differences[differences > 1e-6]
    if differences.size == 0:
        return fallback
    return float(1.0 / np.median(differences))


def detrend(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.size < 3:
        return values - np.mean(values)
    x = np.arange(values.size, dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    return values - (slope * x + intercept)


def fft_bandpass(
    values: np.ndarray, fs: float, low_hz: float, high_hz: float
) -> np.ndarray:
    centered = detrend(values)
    if centered.size < 2:
        return centered
    frequencies = np.fft.rfftfreq(centered.size, d=1.0 / fs)
    spectrum = np.fft.rfft(centered)
    spectrum[(frequencies < low_hz) | (frequencies > high_hz)] = 0
    return np.fft.irfft(spectrum, n=centered.size)


def spectrum(values: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    centered = detrend(values)
    if centered.size < 2:
        return np.asarray([]), np.asarray([])
    window = np.hanning(centered.size)
    transform = np.fft.rfft(centered * window)
    return (
        np.fft.rfftfreq(centered.size, d=1.0 / fs),
        np.square(np.abs(transform)),
    )


def band_peaks(
    frequencies: np.ndarray,
    power: np.ndarray,
    low_hz: float,
    high_hz: float,
    count: int = 3,
) -> list[tuple[float, float]]:
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    ordered = indices[np.argsort(power[indices])[::-1]]
    selected: list[int] = []
    for index in ordered:
        if all(abs(int(index) - prior) > 1 for prior in selected):
            selected.append(int(index))
        if len(selected) >= count:
            break
    return [
        (float(frequencies[index] * 60.0), float(power[index]))
        for index in selected
    ]


def peak_snr(
    frequencies: np.ndarray, power: np.ndarray, low_hz: float, high_hz: float
) -> float:
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    band = power[mask]
    if band.size == 0:
        return 0.0
    return float(np.max(band) / max(float(np.median(band)), 1e-12))


def spectral_entropy(power: np.ndarray) -> float:
    values = np.asarray(power, dtype=float)
    total = float(np.sum(values))
    if values.size < 2 or total <= 0:
        return 0.0
    probabilities = values / total
    probabilities = probabilities[probabilities > 0]
    return float(
        -np.sum(probabilities * np.log(probabilities)) / np.log(values.size)
    )


def extract_features(
    displacement: np.ndarray,
    raw_phase: np.ndarray,
    unwrapped_phase: np.ndarray,
    magnitude: np.ndarray,
    range_m: np.ndarray,
    azimuth_deg: np.ndarray,
    fs: float,
    metadata: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, np.ndarray]]:
    displacement = np.asarray(displacement, dtype=float)
    frequencies, power = spectrum(displacement, fs)
    breath = fft_bandpass(displacement, fs, *BREATH_BAND_HZ)
    heart = fft_bandpass(displacement, fs, *HEART_BAND_HZ)
    breath_peaks = band_peaks(frequencies, power, *BREATH_BAND_HZ)
    heart_peaks = band_peaks(frequencies, power, *HEART_BAND_HZ)

    def peak_value(peaks, index, part):
        return float(peaks[index][part]) if len(peaks) > index else 0.0

    features = {
        "breath_peak_bpm": peak_value(breath_peaks, 0, 0),
        "breath_peak_power": peak_value(breath_peaks, 0, 1),
        "breath_snr": peak_snr(frequencies, power, *BREATH_BAND_HZ),
        "heart_peak_bpm": peak_value(heart_peaks, 0, 0),
        "heart_peak_power": peak_value(heart_peaks, 0, 1),
        "heart_snr": peak_snr(frequencies, power, *HEART_BAND_HZ),
        "spectral_entropy": spectral_entropy(power),
        "phase_variance": float(np.var(unwrapped_phase)),
        "displacement_std": float(np.std(displacement)),
        "magnitude_mean": float(np.mean(magnitude)),
        "magnitude_std": float(np.std(magnitude)),
        "selected_range_std": float(np.std(range_m)),
        "selected_azimuth_std": float(np.std(azimuth_deg)),
        "sample_rate_hz": float(fs),
        "sample_count": float(displacement.size),
    }
    for prefix, peaks in (("breath", breath_peaks), ("heart", heart_peaks)):
        for index in range(3):
            features[f"{prefix}_candidate_{index + 1}_bpm"] = peak_value(
                peaks, index, 0
            )
            features[f"{prefix}_candidate_{index + 1}_power"] = peak_value(
                peaks, index, 1
            )
    if metadata:
        features.update({key: float(value) for key, value in metadata.items()})
    signals = {
        "raw_phase": np.asarray(raw_phase, dtype=float),
        "unwrapped_phase": np.asarray(unwrapped_phase, dtype=float),
        "displacement": displacement,
        "breathing_filtered": breath,
        "heart_filtered": heart,
        "frequency_hz": frequencies,
        "spectrum_power": power,
    }
    return features, signals


def discover_trace_files(log_paths: Iterable[str | Path]) -> list[Path]:
    discovered: list[Path] = []
    for value in log_paths:
        path = Path(value).expanduser()
        if path.is_file():
            discovered.append(path)
        elif path.is_dir():
            discovered.extend(path.rglob("selected_chest_beam_trace.csv"))
    return sorted(set(path.resolve() for path in discovered))
