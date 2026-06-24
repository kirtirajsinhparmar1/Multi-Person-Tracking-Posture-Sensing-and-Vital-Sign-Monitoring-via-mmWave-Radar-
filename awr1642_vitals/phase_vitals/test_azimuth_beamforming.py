"""Offline unit tests for FE03 azimuth beamforming."""

from __future__ import annotations

from pathlib import Path
import sys


TLV_DIR = Path(__file__).resolve().parent / "tlv_parser"
if str(TLV_DIR) not in sys.path:
    sys.path.insert(0, str(TLV_DIR))

from azimuth_beamforming import (  # noqa: E402
    BeamformingConfig,
    make_angle_grid,
    select_range_azimuth_cell,
)
from fake_ti_uart_packet import (  # noqa: E402
    make_fake_vital_phase_virtual_ant_window,
)


def test_known_source_selection() -> None:
    source_angle = 20.0
    window = make_fake_vital_phase_virtual_ant_window(
        frame_number=1,
        source_bin=37,
        source_azimuth_deg=source_angle,
    )
    config = BeamformingConfig(angleStepDeg=2.0)
    selection = select_range_azimuth_cell(
        window,
        expectedRangeMeters=37 * window.range_resolution,
        expectedAzimuthDeg=source_angle,
        rangeSearchHalfWidthBins=4,
        azimuthSearchHalfWidthDeg=15.0,
        config=config,
    )
    assert selection.selectedRangeBin == 37
    assert abs(selection.selectedAzimuthDeg - source_angle) <= config.angleStepDeg
    assert selection.selectedMagnitude > 10000.0
    assert len(make_angle_grid(config)) == 61


def test_roi_score_and_hysteresis_keep_nearby_beam_stable() -> None:
    config = BeamformingConfig(
        angleStepDeg=2.0,
        hysteresisStrengthRatio=1.15,
        scoreMode="magnitude_roi_stability",
    )
    first_window = make_fake_vital_phase_virtual_ant_window(
        frame_number=1,
        source_bin=37,
        source_azimuth_deg=20.0,
    )
    first = select_range_azimuth_cell(
        first_window,
        expectedRangeMeters=37 * first_window.range_resolution,
        expectedAzimuthDeg=20.0,
        rangeSearchHalfWidthBins=4,
        azimuthSearchHalfWidthDeg=20.0,
        config=config,
    )
    second_window = make_fake_vital_phase_virtual_ant_window(
        frame_number=2,
        source_bin=37,
        source_azimuth_deg=22.0,
    )
    second = select_range_azimuth_cell(
        second_window,
        expectedRangeMeters=37 * second_window.range_resolution,
        expectedAzimuthDeg=22.0,
        rangeSearchHalfWidthBins=4,
        azimuthSearchHalfWidthDeg=20.0,
        previousSelection=first,
        config=config,
    )

    assert first.selectedScore > 0.0
    assert second.selectedRangeBin == 37
    assert abs(second.selectedAzimuthDeg - first.selectedAzimuthDeg) <= 2.0
    assert "hysteresis" in second.selectionReason


def main() -> None:
    test_known_source_selection()
    test_roi_score_and_hysteresis_keep_nearby_beam_stable()
    print("Azimuth beamforming tests passed")


if __name__ == "__main__":
    main()
