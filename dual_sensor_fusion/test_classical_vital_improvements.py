from __future__ import annotations

import csv
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dual_sensor_fusion.fusion_types import AwrVirtualAntWindow
from dual_sensor_fusion.dual_sensor_logger import DualSensorCsvLogger
from dual_sensor_fusion.nearby_beam_combiner import (
    NearbyBeamCombiner,
    NearbyBeamCombinerConfig,
)
from dual_sensor_fusion.plot_phase_diagnostics_from_log import create_plot
from dual_sensor_fusion.run_dual_sensor_fusion_ui import build_arg_parser
from dual_sensor_fusion.vital_estimator_bridge import (
    ClassicalVitalAnalysis,
    HeartPeakCandidate,
    VitalEstimatorBridge,
    VitalEstimatorConfig,
    analyze_locked_vital_signal,
)


def _heart_candidate(
    bpm: float,
    *,
    score: float = 2.0,
    confidence: float = 0.75,
    snr: float = 8.0,
    reason: str = "OK",
) -> HeartPeakCandidate:
    return HeartPeakCandidate(
        bpm=bpm,
        frequencyHz=bpm / 60.0,
        power=100.0 * score,
        snr=snr,
        sharpness=2.0,
        confidence=confidence,
        harmonicPenalty=0.22 if reason == "LIKELY_RESP_HARMONIC" else 1.0,
        persistenceScore=0.0,
        totalScore=score,
        qualityReason=reason,
    )


def _heart_analysis(
    *candidates: HeartPeakCandidate,
) -> ClassicalVitalAnalysis:
    empty = np.asarray([], dtype=float)
    return ClassicalVitalAnalysis(
        breathingBpm=15.0,
        heartBpm=candidates[0].bpm if candidates else None,
        confidenceBreath=0.8,
        confidenceHeart=candidates[0].confidence if candidates else 0.0,
        breathPeakPower=100.0,
        heartPeakPower=candidates[0].power if candidates else 0.0,
        breathPeakSnr=8.0,
        heartPeakSnr=candidates[0].snr if candidates else 0.0,
        breathReason="clear breathing-band peak",
        heartReason="test candidates",
        detrended=empty,
        breathingFiltered=empty,
        heartFiltered=empty,
        frequencyHz=empty,
        spectrumPower=empty,
        heartFrequencyHz=empty,
        heartSpectrumPower=empty,
        heartCandidates=tuple(candidates),
        heartWindowSecUsed=60.0,
    )


class ClassicalVitalAnalysisTests(unittest.TestCase):
    def test_synthetic_breath_and_heart_are_recovered(self):
        fs = 10.0
        time_sec = np.arange(300, dtype=float) / fs
        signal = 2.0 * np.sin(2.0 * math.pi * 0.25 * time_sec)
        signal += 0.18 * np.sin(2.0 * math.pi * 1.20 * time_sec)

        analysis = analyze_locked_vital_signal(signal, fs)

        self.assertAlmostEqual(analysis.breathingBpm, 15.0, delta=1.0)
        self.assertAlmostEqual(analysis.heartBpm, 72.0, delta=2.0)
        self.assertGreater(analysis.confidenceBreath, 0.2)
        self.assertGreater(analysis.confidenceHeart, 0.2)

    def test_true_heart_peak_is_preferred_over_respiration_harmonic(self):
        fs = 10.0
        time_sec = np.arange(600, dtype=float) / fs
        signal = 1.5 * np.sin(2.0 * math.pi * 0.30 * time_sec)
        signal += 0.20 * np.sin(2.0 * math.pi * 0.90 * time_sec)
        signal += 0.16 * np.sin(2.0 * math.pi * 1.20 * time_sec)

        analysis = analyze_locked_vital_signal(signal, fs)

        self.assertAlmostEqual(analysis.breathingBpm, 18.0, delta=1.0)
        self.assertAlmostEqual(analysis.heartBpm, 72.0, delta=3.0)
        self.assertIn("harmonic rejected", analysis.heartReason)

    def test_latest_sixty_second_window_ignores_old_transient(self):
        fs = 10.0
        time_sec = np.arange(1200, dtype=float) / fs
        signal = 0.20 * np.sin(2.0 * math.pi * 1.75 * time_sec)
        signal[600:] = 0.20 * np.sin(
            2.0 * math.pi * 1.20 * time_sec[600:]
        )
        signal += 1.5 * np.sin(2.0 * math.pi * 0.25 * time_sec)

        analysis = analyze_locked_vital_signal(
            signal,
            fs,
            breath_window_sec=30.0,
            heart_window_sec=60.0,
        )

        self.assertAlmostEqual(analysis.heartBpm, 72.0, delta=2.0)
        self.assertAlmostEqual(analysis.heartWindowSecUsed, 60.0, delta=0.1)

    def test_respiration_harmonic_candidate_is_penalized(self):
        fs = 10.0
        time_sec = np.arange(600, dtype=float) / fs
        signal = 1.5 * np.sin(2.0 * math.pi * 0.30 * time_sec)
        signal += 0.30 * np.sin(2.0 * math.pi * 0.90 * time_sec)
        signal += 0.16 * np.sin(2.0 * math.pi * 1.20 * time_sec)

        analysis = analyze_locked_vital_signal(signal, fs, heart_top_k=5)

        harmonic = min(
            analysis.heartCandidates,
            key=lambda item: abs(item.bpm - 54.0),
        )
        self.assertEqual(harmonic.qualityReason, "LIKELY_RESP_HARMONIC")
        self.assertLess(harmonic.harmonicPenalty, 0.5)


class HeartPeakTrackerTests(unittest.TestCase):
    def setUp(self):
        self.bridge = VitalEstimatorBridge(
            VitalEstimatorConfig(
                heartPeakPersistenceSec=8.0,
                heartSwitchConfirmSec=8.0,
                heartSwitchMargin=1.35,
                heartMinSnr=3.0,
                heartMinConfidence=0.35,
            )
        )

    def test_distant_peak_is_held_without_ema_drift(self):
        initial = self.bridge._track_heart_candidates(
            1, _heart_analysis(_heart_candidate(105.0)), 0.0
        )
        self.assertAlmostEqual(initial.trackedBpm, 105.0)

        states = []
        for second in range(1, 8):
            states.append(
                self.bridge._track_heart_candidates(
                    1,
                    _heart_analysis(_heart_candidate(55.0, score=2.2)),
                    float(second),
                )
            )

        self.assertTrue(states[-1].switchPending)
        self.assertEqual(states[-1].holdReason, "SWITCH_PENDING")
        self.assertAlmostEqual(states[-1].trackedBpm, 105.0)
        self.assertNotAlmostEqual(states[-1].trackedBpm, 80.0)

    def test_persistent_stronger_peak_switches_discretely(self):
        self.bridge._track_heart_candidates(
            2, _heart_analysis(_heart_candidate(105.0, score=1.0)), 0.0
        )
        state = None
        for second in range(1, 11):
            state = self.bridge._track_heart_candidates(
                2,
                _heart_analysis(_heart_candidate(72.0, score=2.0)),
                float(second),
            )

        self.assertIsNotNone(state)
        self.assertFalse(state.switchPending)
        self.assertAlmostEqual(state.trackedBpm, 72.0)

    def test_low_confidence_lower_peak_holds_last_good(self):
        self.bridge._track_heart_candidates(
            3, _heart_analysis(_heart_candidate(72.0)), 0.0
        )
        state = self.bridge._track_heart_candidates(
            3,
            _heart_analysis(
                _heart_candidate(
                    55.0,
                    confidence=0.20,
                    snr=1.5,
                )
            ),
            1.0,
        )

        self.assertAlmostEqual(state.trackedBpm, 72.0)
        self.assertEqual(state.holdReason, "HOLD_LAST_GOOD")
        self.assertEqual(state.rejectedReason, "LOW_SNR")

    def test_candidate_switch_requires_confirmation_time(self):
        self.bridge._track_heart_candidates(
            4, _heart_analysis(_heart_candidate(105.0, score=1.0)), 0.0
        )
        before = self.bridge._track_heart_candidates(
            4, _heart_analysis(_heart_candidate(72.0, score=2.0)), 7.0
        )
        before_pending = before.switchPending
        before_bpm = before.trackedBpm
        after = self.bridge._track_heart_candidates(
            4, _heart_analysis(_heart_candidate(72.0, score=2.0)), 15.0
        )

        self.assertTrue(before_pending)
        self.assertAlmostEqual(before_bpm, 105.0)
        self.assertFalse(after.switchPending)
        self.assertAlmostEqual(after.trackedBpm, 72.0)

    def test_early_transient_switches_to_true_peak_without_false_slide(self):
        self.bridge._track_heart_candidates(
            5, _heart_analysis(_heart_candidate(105.0, score=1.2)), 0.0
        )
        observed = []
        for second in range(1, 18):
            analysis = _heart_analysis(
                _heart_candidate(72.0, score=2.2),
                _heart_candidate(55.0, score=1.0, confidence=0.40),
            )
            observed.append(
                self.bridge._track_heart_candidates(
                    5, analysis, float(second)
                ).trackedBpm
            )

        self.assertTrue(all(value in (105.0, 72.0) for value in observed))
        self.assertAlmostEqual(observed[-1], 72.0)
        self.assertNotIn(55.0, observed)

    def test_cli_exposes_heart_tracking_defaults(self):
        args = build_arg_parser().parse_args([])
        self.assertEqual(args.heart_top_k_peaks, 5)
        self.assertEqual(args.heart_peak_persistence_sec, 8.0)
        self.assertEqual(args.heart_switch_confirm_sec, 8.0)
        self.assertEqual(args.heart_window_sec, 60.0)


class HeartDiagnosticsOutputTests(unittest.TestCase):
    def test_csv_headers_include_tracker_diagnostics(self):
        required = {
            "rawHeartCandidateBpm",
            "trackedHeartBpm",
            "displayedHeartBpm",
            "heartCandidateCount",
            "heartSwitchPending",
            "heartSwitchCandidateBpm",
            "heartHoldReason",
            "heartQualityReason",
            "heartWindowSecUsed",
            "heartPeakPersistenceSec",
            "heartRejectedCandidateBpm",
            "heartRejectedReason",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = DualSensorCsvLogger(temp_dir, {})
            try:
                self.assertTrue(
                    required.issubset(
                        logger._writers["phase_diagnostics"].fieldnames
                    )
                )
                self.assertTrue(
                    required.issubset(
                        logger._writers["chest_beam_trace"].fieldnames
                    )
                )
            finally:
                logger.close()

    def test_offline_plot_accepts_tracker_summary_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "selected_chest_beam_trace.csv"
            summary_path = Path(temp_dir) / "phase_diagnostics_summary.csv"
            with trace_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "elapsedSec",
                        "lockedPhaseRaw",
                        "lockedPhaseUnwrapped",
                        "displacementMm",
                        "phaseSegmentId",
                        "phaseValid",
                    ],
                )
                writer.writeheader()
                fs = 10.0
                phase = 0.5 * np.sin(
                    2.0 * math.pi * 0.25 * np.arange(300) / fs
                )
                phase += 0.04 * np.sin(
                    2.0 * math.pi * 1.20 * np.arange(300) / fs
                )
                for index, value in enumerate(phase):
                    writer.writerow(
                        {
                            "elapsedSec": index / fs,
                            "lockedPhaseRaw": math.atan2(
                                math.sin(value), math.cos(value)
                            ),
                            "lockedPhaseUnwrapped": value,
                            "displacementMm": value,
                            "phaseSegmentId": 1,
                            "phaseValid": True,
                        }
                    )
            with summary_path.open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "elapsedSec",
                        "rawHeartCandidateBpm",
                        "trackedHeartBpm",
                        "displayedHeartBpm",
                        "heartConfidence",
                        "breathEstimateState",
                        "heartEstimateState",
                        "breathConfidence",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "elapsedSec": 29.9,
                        "rawHeartCandidateBpm": 72.0,
                        "trackedHeartBpm": 72.0,
                        "displayedHeartBpm": 72.0,
                        "heartConfidence": 0.75,
                        "breathEstimateState": "PRELIMINARY_30S",
                        "heartEstimateState": "PRELIMINARY_30S",
                        "breathConfidence": 0.8,
                    }
                )
            figure = create_plot(
                trace_path,
                window_sec=30.0,
                summary_path=summary_path,
            )
            try:
                self.assertEqual(len(figure.axes), 3)
            finally:
                import matplotlib.pyplot as plt

                plt.close(figure)
            debug_figure = create_plot(
                trace_path,
                window_sec=30.0,
                summary_path=summary_path,
                include_vitals_debug=True,
            )
            try:
                self.assertEqual(len(debug_figure.axes), 5)
            finally:
                import matplotlib.pyplot as plt

                plt.close(debug_figure)


class NearbyBeamCombinerTests(unittest.TestCase):
    def test_stable_neighborhood_is_combined_without_moving_lock(self):
        config = NearbyBeamCombinerConfig(
            enabled=True,
            rangeRadiusBins=1,
            azimuthRadiusDeg=6.0,
            mode="weighted",
            minHistorySamples=4,
        )
        combiner = NearbyBeamCombiner(config)
        bins = np.asarray([36, 37, 38], dtype=int)
        angles = np.asarray([-6.0, 0.0, 6.0], dtype=float)
        window = AwrVirtualAntWindow(
            timestamp=0.0,
            frameNumber=1,
            startBin=36,
            numBins=3,
            numVirtualAntennas=8,
            flags=0,
            rangeResolution=0.05,
            samples=np.zeros((3, 8), dtype=np.complex64),
            binIndices=bins,
            rangeMeters=bins.astype(float) * 0.05,
        )

        result = None
        for frame in range(8):
            common_phase = 0.2 * math.sin(frame * 0.2)
            beam_map = np.empty((3, 3), dtype=np.complex128)
            for row in range(3):
                for column in range(3):
                    static_offset = 0.25 * (row - 1) - 0.18 * (column - 1)
                    amplitude = 100.0 - 5.0 * (
                        abs(row - 1) + abs(column - 1)
                    )
                    beam_map[row, column] = amplitude * np.exp(
                        1j * (common_phase + static_offset)
                    )
            result = combiner.combine(
                target_id=1,
                window=window,
                beam_map=beam_map,
                angle_grid_deg=angles,
                locked_range_bin=37,
                locked_azimuth_deg=0.0,
                phase_segment_id=4,
            )

        self.assertIsNotNone(result)
        self.assertTrue(result.usedCombined)
        self.assertGreater(result.cellCount, 1)
        self.assertEqual(result.source, "combined_locked_neighborhood")
        self.assertAlmostEqual(result.phaseRad, common_phase, delta=0.08)

    def test_combining_is_optional_and_disabled_by_default(self):
        defaults = build_arg_parser().parse_args([])
        enabled = build_arg_parser().parse_args(
            [
                "--enable-nearby-beam-combining",
                "--beam-combine-mode",
                "coherent",
            ]
        )

        self.assertFalse(defaults.enable_nearby_beam_combining)
        self.assertEqual(defaults.beam_combine_mode, "weighted")
        self.assertTrue(enabled.enable_nearby_beam_combining)
        self.assertEqual(enabled.beam_combine_mode, "coherent")


if __name__ == "__main__":
    unittest.main()
