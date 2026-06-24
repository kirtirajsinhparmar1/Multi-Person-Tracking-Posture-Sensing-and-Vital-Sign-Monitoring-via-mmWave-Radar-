"""PC-side azimuth beamforming for AWR1642 FE03 virtual-antenna windows.

Initial geometry assumption: virtual azimuth antennas are an ordered uniform
linear array with lambda/2 spacing. Replace this steering model when the exact
TI virtual-antenna order and calibration phases are available.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Optional

import numpy as np


@dataclass(frozen=True)
class BeamformingConfig:
    angleMinDeg: float = -60.0
    angleMaxDeg: float = 60.0
    angleStepDeg: float = 2.0
    antennaSpacingLambda: float = 0.5
    windowType: str = "none"
    useConjugateSteering: bool = True
    normalizeByNumAntennas: bool = True
    hysteresisStrengthRatio: float = 1.15
    scoreMode: str = "magnitude_roi_stability"
    magnitudeWeight: float = 0.65
    rangeClosenessWeight: float = 0.20
    azimuthClosenessWeight: float = 0.15


@dataclass(frozen=True)
class AzimuthBeamSelection:
    selectedRangeBin: int
    selectedRangeMeters: float
    selectedAzimuthDeg: float
    selectedAzimuthBin: int
    selectedComplex: complex
    selectedPhaseRad: float
    selectedMagnitude: float
    expectedRangeBin: int
    expectedAzimuthDeg: float
    strongestOverallRangeBin: int
    strongestOverallRangeMeters: float
    strongestOverallAzimuthDeg: float
    strongestOverallMagnitude: float
    candidateRangeBins: tuple[int, ...]
    candidateAzimuthDeg: tuple[float, ...]
    selectionReason: str
    angleGridDeg: np.ndarray
    beamMap: np.ndarray
    selectedScore: float = 0.0
    selectionChanged: bool = False


def make_angle_grid(config: BeamformingConfig) -> np.ndarray:
    if config.angleStepDeg <= 0:
        raise ValueError("angleStepDeg must be positive")
    if config.angleMaxDeg < config.angleMinDeg:
        raise ValueError("angleMaxDeg must be >= angleMinDeg")
    count = int(
        math.floor(
            (config.angleMaxDeg - config.angleMinDeg) / config.angleStepDeg
        )
    )
    return (
        config.angleMinDeg
        + np.arange(count + 1, dtype=np.float64) * config.angleStepDeg
    )


def steering_vector(
    numAntennas: int,
    angleDeg: float,
    spacingLambda: float = 0.5,
) -> np.ndarray:
    if numAntennas <= 0:
        raise ValueError("numAntennas must be positive")
    antenna_index = np.arange(numAntennas, dtype=np.float64)
    phase = (
        2.0
        * np.pi
        * float(spacingLambda)
        * antenna_index
        * np.sin(np.deg2rad(float(angleDeg)))
    )
    return np.exp(1j * phase)


def _window_weights(num_antennas: int, window_type: str) -> np.ndarray:
    normalized = str(window_type).strip().lower()
    if normalized in ("", "none", "rect", "rectangular"):
        return np.ones(num_antennas, dtype=np.float64)
    if normalized == "hann":
        return np.hanning(num_antennas)
    raise ValueError(f"unsupported windowType={window_type!r}")


def beamform_azimuth(
    antennaVector: np.ndarray,
    angleGridDeg: np.ndarray,
    config: BeamformingConfig,
) -> np.ndarray:
    vector = np.asarray(antennaVector, dtype=np.complex128).reshape(-1)
    angles = np.asarray(angleGridDeg, dtype=np.float64).reshape(-1)
    if vector.size == 0:
        raise ValueError("antennaVector must not be empty")

    weighted = vector * _window_weights(vector.size, config.windowType)
    steering = np.stack(
        [
            steering_vector(
                vector.size,
                angle,
                config.antennaSpacingLambda,
            )
            for angle in angles
        ],
        axis=0,
    )
    if config.useConjugateSteering:
        beams = np.conjugate(steering) @ weighted
    else:
        beams = steering @ weighted
    if config.normalizeByNumAntennas:
        beams = beams / float(vector.size)
    return beams


def beamform_window(
    fe03Window: Any,
    angleGridDeg: np.ndarray,
    config: BeamformingConfig,
) -> np.ndarray:
    samples = np.asarray(fe03Window.samples, dtype=np.complex128)
    if samples.ndim != 2:
        raise ValueError("FE03 samples must have shape [numBins, numAntennas]")
    if samples.shape != (
        int(fe03Window.num_bins),
        int(fe03Window.num_virtual_antennas),
    ):
        raise ValueError(
            "FE03 sample shape does not match declared bins/antennas: "
            f"{samples.shape}"
        )
    return np.stack(
        [beamform_azimuth(row, angleGridDeg, config) for row in samples],
        axis=0,
    )


def _range_bin_values(fe03_window: Any) -> np.ndarray:
    if hasattr(fe03_window, "bin_indices"):
        return np.asarray(fe03_window.bin_indices, dtype=np.int32)
    return np.arange(
        int(fe03_window.start_bin),
        int(fe03_window.start_bin) + int(fe03_window.num_bins),
        dtype=np.int32,
    )


def _range_meter_values(fe03_window: Any) -> np.ndarray:
    if hasattr(fe03_window, "range_meters"):
        return np.asarray(fe03_window.range_meters, dtype=np.float64)
    return _range_bin_values(fe03_window) * float(fe03_window.range_resolution)


def select_range_azimuth_cell(
    fe03Window: Any,
    expectedRangeMeters: float,
    expectedAzimuthDeg: float,
    rangeSearchHalfWidthBins: int,
    azimuthSearchHalfWidthDeg: float,
    previousSelection: Optional[AzimuthBeamSelection] = None,
    config: BeamformingConfig = BeamformingConfig(),
) -> AzimuthBeamSelection:
    """Select a stable FE03 beam inside the IWR-guided chest search ROI.

    The IWR chest point is a prior, not a heart detector. Selection combines
    AWR magnitude with range/azimuth proximity and then applies hysteresis.
    """
    if rangeSearchHalfWidthBins < 0:
        raise ValueError("rangeSearchHalfWidthBins must be non-negative")
    if azimuthSearchHalfWidthDeg < 0:
        raise ValueError("azimuthSearchHalfWidthDeg must be non-negative")

    angle_grid = make_angle_grid(config)
    beam_map = beamform_window(fe03Window, angle_grid, config)
    magnitudes = np.abs(beam_map)
    bin_indices = _range_bin_values(fe03Window)
    ranges = _range_meter_values(fe03Window)
    expected_row = int(np.argmin(np.abs(ranges - float(expectedRangeMeters))))
    expected_range_bin = int(bin_indices[expected_row])

    range_mask = (
        np.abs(bin_indices - expected_range_bin) <= int(rangeSearchHalfWidthBins)
    )
    azimuth_mask = (
        np.abs(angle_grid - float(expectedAzimuthDeg))
        <= float(azimuthSearchHalfWidthDeg) + 1e-9
    )
    range_rows = np.flatnonzero(range_mask)
    angle_cols = np.flatnonzero(azimuth_mask)
    if range_rows.size == 0:
        range_rows = np.asarray([expected_row], dtype=np.int64)
    if angle_cols.size == 0:
        angle_cols = np.asarray(
            [int(np.argmin(np.abs(angle_grid - float(expectedAzimuthDeg))))],
            dtype=np.int64,
        )

    candidate_magnitude = magnitudes[np.ix_(range_rows, angle_cols)]
    magnitude_peak = max(float(np.max(candidate_magnitude)), 1e-12)
    magnitude_score = candidate_magnitude / magnitude_peak
    range_span = max(float(rangeSearchHalfWidthBins), 1.0)
    azimuth_span = max(float(azimuthSearchHalfWidthDeg), config.angleStepDeg, 1.0)
    range_score = 1.0 - np.clip(
        np.abs(bin_indices[range_rows] - expected_range_bin) / range_span,
        0.0,
        1.0,
    )
    azimuth_score = 1.0 - np.clip(
        np.abs(angle_grid[angle_cols] - float(expectedAzimuthDeg)) / azimuth_span,
        0.0,
        1.0,
    )
    if config.scoreMode == "magnitude":
        candidate_score = magnitude_score
    elif config.scoreMode == "magnitude_roi_stability":
        candidate_score = (
            float(config.magnitudeWeight) * magnitude_score
            + float(config.rangeClosenessWeight) * range_score[:, None]
            + float(config.azimuthClosenessWeight) * azimuth_score[None, :]
        )
    else:
        raise ValueError(f"unsupported scoreMode={config.scoreMode!r}")

    local_flat = int(np.argmax(candidate_score))
    local_row, local_col = np.unravel_index(local_flat, candidate_score.shape)
    selected_row = int(range_rows[local_row])
    selected_col = int(angle_cols[local_col])
    selected_score = float(candidate_score[local_row, local_col])
    reason = "best magnitude/proximity score inside IWR chest ROI"
    selection_changed = False

    if previousSelection is not None:
        previous_rows = np.flatnonzero(
            bin_indices == int(previousSelection.selectedRangeBin)
        )
        previous_cols = np.flatnonzero(
            np.isclose(
                angle_grid,
                float(previousSelection.selectedAzimuthDeg),
                atol=max(config.angleStepDeg * 0.25, 1e-6),
            )
        )
        if (
            previous_rows.size
            and previous_cols.size
            and int(previous_rows[0]) in range_rows
            and int(previous_cols[0]) in angle_cols
        ):
            previous_row = int(previous_rows[0])
            previous_col = int(previous_cols[0])
            previous_local_row = int(np.where(range_rows == previous_row)[0][0])
            previous_local_col = int(np.where(angle_cols == previous_col)[0][0])
            previous_score = float(
                candidate_score[previous_local_row, previous_local_col]
            )
            new_score = selected_score
            if (
                new_score
                < previous_score * float(config.hysteresisStrengthRatio)
            ):
                selected_row = previous_row
                selected_col = previous_col
                selected_score = previous_score
                reason = "beam-score hysteresis kept previous chest cell"
            else:
                selection_changed = (
                    int(previousSelection.selectedRangeBin)
                    != int(bin_indices[selected_row])
                    or not np.isclose(
                        float(previousSelection.selectedAzimuthDeg),
                        float(angle_grid[selected_col]),
                    )
                )

    strongest_flat = int(np.argmax(magnitudes))
    strongest_row, strongest_col = np.unravel_index(
        strongest_flat,
        magnitudes.shape,
    )
    selected_complex = complex(beam_map[selected_row, selected_col])

    return AzimuthBeamSelection(
        selectedRangeBin=int(bin_indices[selected_row]),
        selectedRangeMeters=float(ranges[selected_row]),
        selectedAzimuthDeg=float(angle_grid[selected_col]),
        selectedAzimuthBin=selected_col,
        selectedComplex=selected_complex,
        selectedPhaseRad=float(np.angle(selected_complex)),
        selectedMagnitude=float(abs(selected_complex)),
        expectedRangeBin=expected_range_bin,
        expectedAzimuthDeg=float(expectedAzimuthDeg),
        strongestOverallRangeBin=int(bin_indices[strongest_row]),
        strongestOverallRangeMeters=float(ranges[strongest_row]),
        strongestOverallAzimuthDeg=float(angle_grid[strongest_col]),
        strongestOverallMagnitude=float(magnitudes[strongest_row, strongest_col]),
        candidateRangeBins=tuple(int(bin_indices[row]) for row in range_rows),
        candidateAzimuthDeg=tuple(float(angle_grid[col]) for col in angle_cols),
        selectionReason=reason,
        angleGridDeg=angle_grid,
        beamMap=beam_map,
        selectedScore=selected_score,
        selectionChanged=selection_changed,
    )
