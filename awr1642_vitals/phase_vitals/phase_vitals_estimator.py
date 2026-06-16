from __future__ import annotations

import math
import warnings
from typing import Optional, Tuple

import numpy as np

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        from scipy import signal as scipy_signal
except Exception:  # pragma: no cover - exercised on systems without scipy
    scipy_signal = None

try:
    from .phase_vitals_types import MotionMetrics, VitalEstimates
except ImportError:  # pragma: no cover - supports direct script imports
    from phase_vitals_types import MotionMetrics, VitalEstimates


BREATH_LOW_HZ = 0.1
BREATH_HIGH_HZ = 0.5
HEART_LOW_HZ = 0.8
HEART_HIGH_HZ = 2.0
HEART_4HZ_HIGH_HZ = 4.0


def _as_float_array(x) -> np.ndarray:
    arr = np.asarray(x, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def iq_to_phase(i, q) -> np.ndarray:
    return np.arctan2(np.asarray(q, dtype=float), np.asarray(i, dtype=float))


def unwrap_phase(phase) -> np.ndarray:
    return np.unwrap(_as_float_array(phase))


def phase_to_displacement_mm(phase, wavelength_m: float) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    return np.asarray(phase, dtype=float) * wavelength_m * 1000.0 / (4.0 * math.pi)


def detrend_signal(x) -> np.ndarray:
    arr = _as_float_array(x)
    if arr.size == 0:
        return arr
    if arr.size < 3:
        return arr - np.mean(arr)
    if scipy_signal is not None:
        return scipy_signal.detrend(arr, type="linear")
    t = np.arange(arr.size, dtype=float)
    slope, intercept = np.polyfit(t, arr, deg=1)
    return arr - (slope * t + intercept)


def _fft_bandpass(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    if x.size < 2:
        return x.copy()
    freqs = np.fft.rfftfreq(x.size, d=1.0 / fs)
    spectrum = np.fft.rfft(detrend_signal(x))
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    spectrum[~mask] = 0
    return np.fft.irfft(spectrum, n=x.size)


def bandpass_signal(x, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    arr = detrend_signal(x)
    if arr.size < 4:
        return arr
    if fs <= 0:
        raise ValueError("fs must be positive")
    nyq = 0.5 * fs
    if high_hz >= nyq:
        high_hz = nyq * 0.95
    if low_hz <= 0 or low_hz >= high_hz:
        return arr
    if scipy_signal is not None and arr.size >= 24:
        b, a = scipy_signal.butter(4, [low_hz / nyq, high_hz / nyq], btype="band")
        padlen = min(arr.size - 1, 3 * max(len(a), len(b)))
        if padlen > 0:
            return scipy_signal.filtfilt(b, a, arr, padlen=padlen)
    return _fft_bandpass(arr, fs, low_hz, high_hz)


def _band_spectrum(x, fs: float, low_hz: float, high_hz: float) -> Tuple[np.ndarray, np.ndarray]:
    arr = detrend_signal(x)
    if arr.size < 2:
        return np.array([]), np.array([])
    window = np.hanning(arr.size)
    spectrum = np.abs(np.fft.rfft(arr * window))
    freqs = np.fft.rfftfreq(arr.size, d=1.0 / fs)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return freqs[mask], spectrum[mask]


def estimate_fft_bpm(x, fs: float, low_hz: float, high_hz: float) -> Optional[float]:
    freqs, spectrum = _band_spectrum(x, fs, low_hz, high_hz)
    if freqs.size == 0 or np.max(spectrum) <= 0:
        return None
    return float(freqs[int(np.argmax(spectrum))] * 60.0)


def estimate_xcorr_bpm(x, fs: float, low_hz: float, high_hz: float) -> Optional[float]:
    filtered = bandpass_signal(x, fs, low_hz, high_hz)
    if filtered.size < 4:
        return None
    filtered = filtered - np.mean(filtered)
    denom = np.dot(filtered, filtered)
    if denom <= 0:
        return None
    corr = np.correlate(filtered, filtered, mode="full")[filtered.size - 1 :] / denom
    min_lag = max(1, int(fs / high_hz))
    max_lag = min(corr.size - 1, int(fs / low_hz))
    if max_lag <= min_lag:
        return None
    search = corr[min_lag : max_lag + 1]
    if search.size == 0:
        return None
    lag = min_lag + int(np.argmax(search))
    return float(60.0 * fs / lag)


def estimate_peak_count_bpm(x, fs: float, low_hz: float, high_hz: float) -> Optional[float]:
    filtered = bandpass_signal(x, fs, low_hz, high_hz)
    if filtered.size < 4:
        return None
    min_distance = max(1, int(0.8 * fs / high_hz))
    centered = filtered - np.mean(filtered)
    if scipy_signal is not None:
        prominence = max(float(np.std(centered) * 0.25), 1e-9)
        peaks, _ = scipy_signal.find_peaks(centered, distance=min_distance, prominence=prominence)
    else:
        candidates = np.where((centered[1:-1] > centered[:-2]) & (centered[1:-1] > centered[2:]))[0] + 1
        peaks = []
        last = -min_distance
        threshold = float(np.std(centered) * 0.15)
        for idx in candidates:
            if idx - last >= min_distance and centered[idx] > threshold:
                peaks.append(idx)
                last = idx
        peaks = np.asarray(peaks, dtype=int)
    if peaks.size >= 2:
        periods_s = np.diff(peaks) / fs
        mean_period = float(np.mean(periods_s))
        if mean_period > 0:
            return float(60.0 / mean_period)
    duration_s = filtered.size / fs
    if duration_s <= 0 or peaks.size == 0:
        return None
    return float(peaks.size * 60.0 / duration_s)


def compute_energy(x) -> float:
    arr = _as_float_array(x)
    if arr.size == 0:
        return 0.0
    return float(np.sum(np.square(arr)))


def compute_peak_confidence(x, fs: float, low_hz: float, high_hz: float) -> float:
    freqs, spectrum = _band_spectrum(x, fs, low_hz, high_hz)
    if freqs.size == 0:
        return 0.0
    power = np.square(spectrum)
    total = float(np.sum(power))
    if total <= 0:
        return 0.0
    peak_idx = int(np.argmax(power))
    lo = max(0, peak_idx - 1)
    hi = min(power.size, peak_idx + 2)
    return float(np.clip(np.sum(power[lo:hi]) / total, 0.0, 1.0))


def detect_motion_from_phase(phase, fs: float) -> MotionMetrics:
    unwrapped = unwrap_phase(phase)
    if unwrapped.size < 3:
        return MotionMetrics(False, 0.0, 0.0, 0.0, "too_short")
    diff = np.diff(unwrapped)
    max_abs_step = float(np.max(np.abs(diff)))
    step_std = float(np.std(diff))
    median = float(np.median(diff))
    mad = float(np.median(np.abs(diff - median)))
    adaptive_limit = max(1.5, 8.0 * mad, 5.0 * step_std)
    motion = bool(max_abs_step > adaptive_limit and max_abs_step > 1.5)
    notes = f"adaptive_limit={adaptive_limit:.3f}"
    return MotionMetrics(motion, max_abs_step, step_std, mad, notes)


def estimate_vitals_from_phase(phase, fs: float, wavelength_m: Optional[float] = None) -> VitalEstimates:
    if fs <= 0:
        raise ValueError("fs must be positive")
    unwrapped = unwrap_phase(phase)
    if unwrapped.size < int(max(8, fs * 10)):
        return VitalEstimates(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            False,
            "INVALID",
            "need at least about 10 seconds of phase data",
        )

    signal = phase_to_displacement_mm(unwrapped, wavelength_m) if wavelength_m else unwrapped
    signal = detrend_signal(signal)
    breath_wfm = bandpass_signal(signal, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ)
    heart_wfm = bandpass_signal(signal, fs, HEART_LOW_HZ, HEART_HIGH_HZ)
    heart_4hz_wfm = bandpass_signal(signal, fs, HEART_LOW_HZ, min(HEART_4HZ_HIGH_HZ, fs * 0.45))
    motion = detect_motion_from_phase(unwrapped, fs)

    confidence_breath = compute_peak_confidence(breath_wfm, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ)
    confidence_heart = compute_peak_confidence(heart_wfm, fs, HEART_LOW_HZ, HEART_HIGH_HZ)
    breath_energy = compute_energy(breath_wfm)
    heart_energy = compute_energy(heart_wfm)

    notes = []
    quality = "OK"
    if motion.motion_detected:
        quality = "MOTION"
        notes.append("phase motion/jump detected")
    if confidence_breath < 0.15 and confidence_heart < 0.10:
        quality = "LOW_CONFIDENCE" if quality == "OK" else quality
        notes.append("weak spectral peaks")

    return VitalEstimates(
        breathing_rate_fft_bpm=estimate_fft_bpm(breath_wfm, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ),
        breathing_rate_xcorr_bpm=estimate_xcorr_bpm(breath_wfm, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ),
        breathing_rate_peak_count_bpm=estimate_peak_count_bpm(breath_wfm, fs, BREATH_LOW_HZ, BREATH_HIGH_HZ),
        heart_rate_fft_bpm=estimate_fft_bpm(heart_wfm, fs, HEART_LOW_HZ, HEART_HIGH_HZ),
        heart_rate_fft_4hz_bpm=estimate_fft_bpm(heart_4hz_wfm, fs, HEART_LOW_HZ, min(HEART_4HZ_HIGH_HZ, fs * 0.45)),
        heart_rate_xcorr_bpm=estimate_xcorr_bpm(heart_wfm, fs, HEART_LOW_HZ, HEART_HIGH_HZ),
        heart_rate_peak_count_bpm=estimate_peak_count_bpm(heart_wfm, fs, HEART_LOW_HZ, HEART_HIGH_HZ),
        confidence_breath=confidence_breath,
        confidence_heart=confidence_heart,
        breath_energy=breath_energy,
        heart_energy=heart_energy,
        motion_detected=motion.motion_detected,
        quality_state=quality,
        notes="; ".join(notes),
    )
