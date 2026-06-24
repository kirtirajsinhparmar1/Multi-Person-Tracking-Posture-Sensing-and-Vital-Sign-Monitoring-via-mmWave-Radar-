from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math

import numpy as np

from .fusion_types import AwrVirtualAntWindow


@dataclass(frozen=True)
class NearbyBeamCombinerConfig:
    enabled: bool = False
    rangeRadiusBins: int = 1
    azimuthRadiusDeg: float = 6.0
    mode: str = "weighted"
    historySamples: int = 30
    minHistorySamples: int = 8
    minCoherence: float = 0.55


@dataclass(frozen=True)
class NearbyBeamCombineResult:
    complexValue: complex
    phaseRad: float
    magnitude: float
    usedCombined: bool
    cellCount: int
    confidence: float
    source: str
    reason: str


class NearbyBeamCombiner:
    """Phase-align a small neighborhood to the locked beam.

    Each neighboring cell gets a slowly learned static phase offset relative
    to the locked center cell. Removing that offset preserves common chest
    displacement while avoiding destructive averaging of unrelated carrier
    phase. The lock location itself is never changed by this class.
    """

    def __init__(self, config: NearbyBeamCombinerConfig | None = None):
        self.config = config or NearbyBeamCombinerConfig()
        if self.config.rangeRadiusBins < 0:
            raise ValueError("rangeRadiusBins must be non-negative")
        if self.config.azimuthRadiusDeg < 0:
            raise ValueError("azimuthRadiusDeg must be non-negative")
        if self.config.mode not in {"best", "weighted", "coherent"}:
            raise ValueError("mode must be best, weighted, or coherent")
        self._relative_phase = defaultdict(
            lambda: deque(maxlen=max(2, self.config.historySamples))
        )
        self._active_key: dict[int, tuple[int, float, int]] = {}

    def reset(self, target_id: int) -> None:
        tid = int(target_id)
        self._active_key.pop(tid, None)
        for key in [key for key in self._relative_phase if key[0] == tid]:
            del self._relative_phase[key]

    def combine(
        self,
        target_id: int,
        window: AwrVirtualAntWindow,
        beam_map: np.ndarray,
        angle_grid_deg: np.ndarray,
        locked_range_bin: int,
        locked_azimuth_deg: float,
        phase_segment_id: int,
    ) -> NearbyBeamCombineResult:
        beam_map = np.asarray(beam_map, dtype=np.complex128)
        angles = np.asarray(angle_grid_deg, dtype=float)
        bins = np.asarray(window.binIndices, dtype=int)
        row_matches = np.flatnonzero(bins == int(locked_range_bin))
        if (
            row_matches.size == 0
            or beam_map.ndim != 2
            or beam_map.shape != (bins.size, angles.size)
        ):
            return self._single(0j, "locked beam is absent from FE03 map")
        row = int(row_matches[0])
        col = int(np.argmin(np.abs(angles - float(locked_azimuth_deg))))
        center = complex(beam_map[row, col])
        if not self.config.enabled or abs(center) <= 0:
            return self._single(center, "nearby combining disabled")

        tid = int(target_id)
        active_key = (
            int(locked_range_bin),
            round(float(angles[col]), 3),
            int(phase_segment_id),
        )
        if self._active_key.get(tid) != active_key:
            self.reset(tid)
            self._active_key[tid] = active_key

        row_mask = np.abs(bins - int(locked_range_bin)) <= self.config.rangeRadiusBins
        col_mask = (
            np.abs(angles - float(locked_azimuth_deg))
            <= self.config.azimuthRadiusDeg
        )
        cells: list[tuple[complex, float, float]] = []
        center_phase = center / max(abs(center), 1e-12)
        for rr in np.flatnonzero(row_mask):
            for cc in np.flatnonzero(col_mask):
                value = complex(beam_map[int(rr), int(cc)])
                if abs(value) <= 0:
                    continue
                history_key = (tid, int(bins[rr]), round(float(angles[cc]), 3))
                relative = (value / abs(value)) * np.conj(center_phase)
                history = self._relative_phase[history_key]
                history.append(relative)
                if int(rr) == row and int(cc) == col:
                    cells.append((value, 1.0, 1.0))
                    continue
                if len(history) < self.config.minHistorySamples:
                    continue
                mean_relative = complex(np.mean(np.asarray(history)))
                coherence = min(1.0, abs(mean_relative))
                if coherence < self.config.minCoherence:
                    continue
                offset = mean_relative / max(abs(mean_relative), 1e-12)
                aligned = value * np.conj(offset)
                relative_magnitude = min(2.0, abs(value) / max(abs(center), 1e-12))
                cells.append((aligned, coherence, relative_magnitude))

        if len(cells) < 2:
            return self._single(center, "nearby cells are not phase-stable yet")

        if self.config.mode == "best":
            selected = max(cells, key=lambda item: item[1] * item[2])
            combined = selected[0]
        else:
            values = np.asarray([item[0] for item in cells], dtype=np.complex128)
            if self.config.mode == "weighted":
                weights = np.asarray(
                    [item[1] * math.sqrt(max(item[2], 0.0)) for item in cells],
                    dtype=float,
                )
            else:
                weights = np.ones(len(cells), dtype=float)
            combined = complex(np.sum(values * weights) / max(np.sum(weights), 1e-12))

        confidence = float(np.mean([item[1] for item in cells]))
        # A poorly aligned neighborhood is less useful than the center beam.
        if abs(combined) < 0.8 * abs(center):
            return self._single(center, "combined magnitude did not preserve center quality")
        return NearbyBeamCombineResult(
            complexValue=combined,
            phaseRad=float(np.angle(combined)),
            magnitude=float(abs(combined)),
            usedCombined=True,
            cellCount=len(cells),
            confidence=confidence,
            source="combined_locked_neighborhood",
            reason=f"{self.config.mode} combination of {len(cells)} stable cells",
        )

    @staticmethod
    def _single(value: complex, reason: str) -> NearbyBeamCombineResult:
        return NearbyBeamCombineResult(
            complexValue=complex(value),
            phaseRad=float(np.angle(value)) if abs(value) else 0.0,
            magnitude=float(abs(value)),
            usedCombined=False,
            cellCount=1,
            confidence=1.0 if abs(value) else 0.0,
            source="single_locked_beam",
            reason=reason,
        )
