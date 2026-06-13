from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import numpy as np

try:
    from .twente_types import SignalQuality, VitalEstimate
except ImportError:
    from twente_types import SignalQuality, VitalEstimate


BREATH_BAND_HZ = (0.1, 0.5)
HEART_BAND_HZ = (0.8, 2.0)


def detrend_signal(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64).reshape(-1)
    arr = _fill_nonfinite(arr)
    if arr.size < 2:
        return arr - np.nanmean(arr)
    try:
        from scipy.signal import detrend

        return np.asarray(detrend(arr, type="linear"), dtype=np.float64)
    except Exception:
        idx = np.arange(arr.size, dtype=np.float64)
        coeff = np.polyfit(idx, arr, deg=1)
        return arr - np.polyval(coeff, idx)


def bandpass_or_fft_filter(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    arr = detrend_signal(x)
    if arr.size < 4:
        return arr
    nyquist = fs / 2.0
    low = max(low_hz, 1e-6)
    high = min(high_hz, nyquist * 0.95)
    if not (0 < low < high < nyquist):
        raise ValueError(f"Invalid band {low_hz}-{high_hz} Hz for fs={fs}")

    try:
        from scipy.signal import butter, sosfiltfilt

        sos = butter(4, [low / nyquist, high / nyquist], btype="bandpass", output="sos")
        padlen = min(arr.size - 1, 3 * (2 * sos.shape[0] + 1))
        if padlen > 0:
            return np.asarray(sosfiltfilt(sos, arr, padlen=padlen), dtype=np.float64)
    except Exception:
        pass

    return _fft_bandpass(arr, fs, low, high)


def estimate_peak_bpm(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> float | None:
    bpm, _peak_hz, _info = _estimate_peak(x, fs, low_hz, high_hz)
    return bpm


def estimate_breath_and_heart_from_displacement(displacement: np.ndarray, fs: float) -> VitalEstimate:
    arr = np.asarray(displacement, dtype=np.float64).reshape(-1)
    if fs <= 0:
        raise ValueError("fs must be positive.")
    if arr.size < max(8, int(fs * 5)):
        raise ValueError("Signal is too short for a useful vital-sign estimate.")

    finite_fraction = float(np.isfinite(arr).sum() / arr.size)
    detrended = detrend_signal(arr)
    duration_s = float(arr.size / fs)
    quality = SignalQuality(
        num_samples=int(arr.size),
        duration_s=duration_s,
        finite_fraction=finite_fraction,
        detrended_std=float(np.nanstd(detrended)),
        notes=[],
    )
    if duration_s < 30.0:
        quality.notes.append("Short recording; heart estimate may be unstable.")

    breath_bpm, breath_hz, _breath_info = _estimate_peak(detrended, fs, *BREATH_BAND_HZ)
    heart_bpm, heart_hz, _heart_info = _estimate_peak(detrended, fs, *HEART_BAND_HZ)

    if breath_bpm is None:
        quality.notes.append("No breathing peak found in default band.")
    if heart_bpm is None:
        quality.notes.append("No heart peak found in default band.")

    return VitalEstimate(
        breathing_bpm=breath_bpm,
        heart_bpm=heart_bpm,
        breathing_peak_hz=breath_hz,
        heart_peak_hz=heart_hz,
        fs_hz=float(fs),
        duration_s=duration_s,
        quality=quality,
    )


def estimate_to_dict(estimate: VitalEstimate) -> dict[str, Any]:
    return asdict(estimate)


def _estimate_peak(
    x: np.ndarray, fs: float, low_hz: float, high_hz: float
) -> tuple[float | None, float | None, dict[str, Any]]:
    filtered = bandpass_or_fft_filter(x, fs, low_hz, high_hz)
    filtered = detrend_signal(filtered)
    if filtered.size < 4 or not np.isfinite(filtered).any():
        return None, None, {"reason": "empty_or_invalid"}

    window = np.hanning(filtered.size)
    spectrum = np.fft.rfft(filtered * window)
    freqs = np.fft.rfftfreq(filtered.size, d=1.0 / fs)
    power = np.abs(spectrum) ** 2
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not mask.any():
        return None, None, {"reason": "no_bins_in_band"}
    band_freqs = freqs[mask]
    band_power = power[mask]
    if band_power.size == 0 or float(np.nanmax(band_power)) <= 0:
        return None, None, {"reason": "no_power_in_band"}

    peak_idx = int(np.nanargmax(band_power))
    peak_hz = float(band_freqs[peak_idx])
    return peak_hz * 60.0, peak_hz, {
        "peak_power": float(band_power[peak_idx]),
        "band_low_hz": low_hz,
        "band_high_hz": high_hz,
    }


def _fft_bandpass(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64).reshape(-1)
    spectrum = np.fft.rfft(arr)
    freqs = np.fft.rfftfreq(arr.size, d=1.0 / fs)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    spectrum[~mask] = 0
    return np.fft.irfft(spectrum, n=arr.size)


def _fill_nonfinite(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64).copy()
    finite = np.isfinite(arr)
    if finite.all():
        return arr
    if not finite.any():
        return np.zeros_like(arr)
    idx = np.arange(arr.size)
    arr[~finite] = np.interp(idx[~finite], idx[finite], arr[finite])
    return arr
