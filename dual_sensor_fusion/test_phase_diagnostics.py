from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dual_sensor_fusion.run_dual_sensor_fusion_ui import (
    PHASE_PRIMARY_CHART_TITLES,
    rolling_visible_series,
)
from dual_sensor_fusion.vital_estimator_bridge import (
    analyze_locked_vital_signal,
    build_segment_safe_phase,
)


class SegmentSafePhaseTests(unittest.TestCase):
    def test_wrapped_phase_is_bounded_and_unwraps_continuously(self):
        time_sec = np.arange(0.0, 20.0, 0.1)
        original = 0.8 * time_sec
        wrapped_input = np.angle(np.exp(1j * original))
        result = build_segment_safe_phase(
            wrapped_input,
            time_sec,
            np.zeros(time_sec.size, dtype=int),
        )
        self.assertTrue(np.all(result.wrapped <= math.pi))
        self.assertTrue(np.all(result.wrapped >= -math.pi))
        np.testing.assert_allclose(
            result.relative,
            original - original[0],
            atol=1e-9,
        )

    def test_segment_beam_and_gap_changes_reset_unwrap_baseline(self):
        time_sec = np.asarray([0.0, 0.1, 0.2, 0.3, 2.0, 2.1])
        raw = np.asarray([3.0, -3.0, -2.8, -2.6, 2.5, 2.7])
        segments = np.asarray([1, 1, 2, 2, 2, 2])
        beam_keys = ["a", "a", "a", "b", "b", "b"]
        result = build_segment_safe_phase(
            raw,
            time_sec,
            segments,
            beam_keys=beam_keys,
            gap_reset_sec=1.0,
        )
        self.assertEqual(result.continuityIds.tolist(), [0, 0, 1, 2, 3, 3])
        for index in (0, 2, 3, 4):
            self.assertAlmostEqual(result.relative[index], 0.0)


class PhasePresentationTests(unittest.TestCase):
    def test_rolling_window_and_downsampling_are_bounded(self):
        time_sec = np.arange(0.0, 200.0, 0.01)
        values = np.sin(time_sec)
        visible_time, visible_values = rolling_visible_series(
            time_sec,
            values,
            visible_window_sec=60.0,
            max_points=1200,
        )
        self.assertLessEqual(visible_time.size, 1200)
        self.assertGreaterEqual(float(visible_time[0]), -60.01)
        self.assertAlmostEqual(float(visible_time[-1]), 0.0)
        self.assertEqual(visible_time.size, visible_values.size)

    def test_main_phase_tab_declares_exactly_three_waveform_charts(self):
        self.assertEqual(
            PHASE_PRIMARY_CHART_TITLES,
            (
                "Wrapped Phase",
                "Unwrapped Phase",
                "Breathing and Heartbeat Components",
            ),
        )
        combined = " ".join(PHASE_PRIMARY_CHART_TITLES).lower()
        self.assertNotIn("bpm", combined)
        self.assertNotIn("psd", combined)

    def test_component_filters_separate_breath_and_heart_frequencies(self):
        fs = 10.0
        time_sec = np.arange(0.0, 60.0, 1.0 / fs)
        signal = (
            np.sin(2.0 * math.pi * 0.24 * time_sec)
            + 0.18 * np.sin(2.0 * math.pi * 1.2 * time_sec)
        )
        analysis = analyze_locked_vital_signal(signal, fs)

        def dominant_frequency(values):
            frequency = np.fft.rfftfreq(values.size, d=1.0 / fs)
            spectrum = np.abs(np.fft.rfft(values))
            return float(frequency[np.argmax(spectrum[1:]) + 1])

        self.assertAlmostEqual(
            dominant_frequency(analysis.breathingFiltered),
            0.24,
            delta=0.03,
        )
        self.assertAlmostEqual(
            dominant_frequency(analysis.heartFiltered),
            1.2,
            delta=0.05,
        )


if __name__ == "__main__":
    unittest.main()
