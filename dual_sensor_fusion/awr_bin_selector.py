from __future__ import annotations

from dataclasses import dataclass

from .coordinate_transform import TransformConfig, expected_awr_range
from .fusion_types import AwrBinSample, AwrBinWindow, BinSelection, IwrTarget


@dataclass(frozen=True)
class SelectorConfig:
    searchHalfWidth: int = 4
    hysteresisStrengthRatio: float = 1.15


def select_bin(
    expected_range_meters: float,
    awr_window: AwrBinWindow,
    config: SelectorConfig | None = None,
    previous_selection: BinSelection | None = None,
) -> BinSelection:
    config = config or SelectorConfig()
    if config.searchHalfWidth < 0:
        raise ValueError("searchHalfWidth must be nonnegative")
    if config.hysteresisStrengthRatio < 1.0:
        raise ValueError("hysteresisStrengthRatio must be at least 1.0")

    bins = list(awr_window.bins)
    if not bins:
        return BinSelection(
            expectedAwrRangeMeters=expected_range_meters,
            expectedAwrBin=None,
            selectedAwrBin=None,
            selectedAwrRangeMeters=None,
            selectedPhaseRad=None,
            selectedMagnitude=None,
            strongestOverallBin=None,
            strongestOverallRangeMeters=None,
            strongestOverallMagnitude=None,
            candidateBins=[],
            selectionReason="AWR window contains no bins",
        )

    expected_sample = min(
        bins, key=lambda sample: abs(sample.rangeMeters - expected_range_meters)
    )
    strongest = max(bins, key=lambda sample: sample.magnitude)
    candidates = [
        sample
        for sample in bins
        if abs(sample.binIndex - expected_sample.binIndex) <= config.searchHalfWidth
    ]
    candidate = max(candidates, key=lambda sample: sample.magnitude)
    selected = candidate
    reason = (
        f"strongest candidate within expected bin {expected_sample.binIndex} "
        f"+/- {config.searchHalfWidth}"
    )

    if previous_selection and previous_selection.selectedAwrBin is not None:
        previous = _sample_by_bin(candidates, previous_selection.selectedAwrBin)
        if previous is not None and candidate.binIndex != previous.binIndex:
            required = previous.magnitude * config.hysteresisStrengthRatio
            if candidate.magnitude < required:
                selected = previous
                reason = (
                    f"hysteresis kept bin {previous.binIndex}; bin "
                    f"{candidate.binIndex} was less than "
                    f"{config.hysteresisStrengthRatio:.2f}x stronger"
                )
            else:
                reason = (
                    f"switched from bin {previous.binIndex} to {candidate.binIndex}; "
                    "new candidate exceeded hysteresis threshold"
                )
        elif previous is not None:
            reason = f"kept bin {previous.binIndex}; it remains strongest candidate"

    return BinSelection(
        expectedAwrRangeMeters=expected_range_meters,
        expectedAwrBin=expected_sample.binIndex,
        selectedAwrBin=selected.binIndex,
        selectedAwrRangeMeters=selected.rangeMeters,
        selectedPhaseRad=selected.phaseRad,
        selectedMagnitude=selected.magnitude,
        strongestOverallBin=strongest.binIndex,
        strongestOverallRangeMeters=strongest.rangeMeters,
        strongestOverallMagnitude=strongest.magnitude,
        candidateBins=[sample.binIndex for sample in candidates],
        selectionReason=reason,
    )


def select_bin_for_target(
    iwrTarget: IwrTarget,
    awrWindow: AwrBinWindow,
    transformConfig: TransformConfig | None = None,
    selectorConfig: SelectorConfig | None = None,
    previousSelection: BinSelection | None = None,
) -> BinSelection:
    expected_range = expected_awr_range(
        iwrTarget, transformConfig or TransformConfig()
    )
    return select_bin(
        expected_range,
        awrWindow,
        selectorConfig,
        previousSelection,
    )


def _sample_by_bin(
    samples: list[AwrBinSample], bin_index: int
) -> AwrBinSample | None:
    for sample in samples:
        if sample.binIndex == bin_index:
            return sample
    return None

