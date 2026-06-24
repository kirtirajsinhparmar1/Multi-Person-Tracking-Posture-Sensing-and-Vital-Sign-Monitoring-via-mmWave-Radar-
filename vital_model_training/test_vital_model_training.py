from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from vital_model_training.build_training_windows_from_logs import build_dataset
from vital_model_training.train_vital_baseline_model import train_models
from dual_sensor_fusion.plot_phase_diagnostics_from_log import create_plot


TRACE_COLUMNS = [
    "timestamp",
    "elapsedSec",
    "targetId",
    "fe03FrameNumber",
    "fe03StreamState",
    "monitoringState",
    "gateState",
    "rawPosture",
    "stablePosture",
    "gatePosture",
    "beamState",
    "phaseValid",
    "phaseSegmentId",
    "lockedRangeBin",
    "lockedRangeMeters",
    "lockedAzimuthDeg",
    "lockedMagnitude",
    "lockedPhaseRaw",
    "lockedPhaseUnwrapped",
    "displacementMm",
    "beamLockAgeSec",
    "beamSwitchCount",
    "expectedAwrRangeHorizontalMeters",
    "expectedAwrAzimuthDeg",
    "candidateRangeBin",
    "candidateAzimuthDeg",
    "candidateMagnitude",
]


def write_synthetic_trace(path: Path, duration_sec=40.0, switch_at=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACE_COLUMNS)
        writer.writeheader()
        sample_count = int(duration_sec * 10)
        for index in range(sample_count):
            elapsed = index / 10.0
            segment = 1 if switch_at is None or elapsed < switch_at else 2
            displacement = 3.0 * math.sin(2.0 * math.pi * 0.25 * elapsed)
            displacement += 0.25 * math.sin(2.0 * math.pi * 1.2 * elapsed)
            phase = displacement * (4.0 * math.pi) / 3.8934
            writer.writerow(
                {
                    "timestamp": 1000.0 + elapsed,
                    "elapsedSec": elapsed,
                    "targetId": 1,
                    "fe03FrameNumber": index,
                    "fe03StreamState": "FE03_ACTIVE",
                    "monitoringState": "MONITORING",
                    "gateState": "MONITORING",
                    "rawPosture": "SITTING",
                    "stablePosture": "SITTING",
                    "gatePosture": "SITTING",
                    "beamState": "BEAM_LOCKED",
                    "phaseValid": True,
                    "phaseSegmentId": segment,
                    "lockedRangeBin": 37,
                    "lockedRangeMeters": 1.7541,
                    "lockedAzimuthDeg": 4.0,
                    "lockedMagnitude": 2500.0,
                    "lockedPhaseRaw": math.atan2(math.sin(phase), math.cos(phase)),
                    "lockedPhaseUnwrapped": phase,
                    "displacementMm": displacement,
                    "beamLockAgeSec": elapsed,
                    "beamSwitchCount": segment - 1,
                    "expectedAwrRangeHorizontalMeters": 1.75,
                    "expectedAwrAzimuthDeg": 3.0,
                    "candidateRangeBin": 37,
                    "candidateAzimuthDeg": 4.0,
                    "candidateMagnitude": 2550.0,
                }
            )


class VitalModelTrainingTests(unittest.TestCase):
    def test_builds_thirty_second_windows_from_locked_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / "recording_a" / "selected_chest_beam_trace.csv"
            write_synthetic_trace(trace)
            output = root / "dataset"
            summary = build_dataset(
                [trace.parent],
                output,
                window_sec=30.0,
                stride_sec=5.0,
            )
            self.assertGreaterEqual(summary["window_count"], 2)
            self.assertTrue((output / "training_windows.npz").exists())
            with (output / "feature_table.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                feature_rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(feature_rows), 2)
            self.assertAlmostEqual(
                float(feature_rows[0]["breath_peak_bpm"]), 14.0, delta=3.0
            )
            self.assertAlmostEqual(
                float(feature_rows[0]["heart_peak_bpm"]), 72.0, delta=6.0
            )

    def test_window_builder_does_not_cross_beam_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / "recording_b" / "selected_chest_beam_trace.csv"
            write_synthetic_trace(trace, duration_sec=40.0, switch_at=20.0)
            output = root / "dataset"
            summary = build_dataset(
                [trace.parent],
                output,
                window_sec=30.0,
                stride_sec=5.0,
            )
            self.assertEqual(summary["window_count"], 0)

    def test_training_without_reference_labels_is_graceful(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            features = root / "feature_table.csv"
            with features.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "recording_id",
                        "start_time_sec",
                        "end_time_sec",
                        "heart_peak_bpm",
                        "breath_peak_bpm",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "recording_id": "recording_a",
                        "start_time_sec": 0,
                        "end_time_sec": 30,
                        "heart_peak_bpm": 72,
                        "breath_peak_bpm": 15,
                    }
                )
            output = root / "model"
            metrics = train_models(features, None, output, "random_forest")
            self.assertEqual(metrics["status"], "reference_labels_required")
            saved = json.loads((output / "metrics.json").read_text())
            self.assertEqual(saved["status"], "reference_labels_required")

    def test_training_with_synthetic_labels_when_sklearn_is_available(self):
        try:
            import sklearn  # noqa: F401
        except Exception:
            self.skipTest("scikit-learn is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            features = root / "feature_table.csv"
            fieldnames = [
                "recording_id",
                "start_time_sec",
                "end_time_sec",
                "heart_peak_bpm",
                "breath_peak_bpm",
                "heart_snr",
                "breath_snr",
                "reference_heart_bpm",
                "reference_breath_bpm",
            ]
            with features.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for index in range(6):
                    writer.writerow(
                        {
                            "recording_id": "synthetic",
                            "start_time_sec": index * 5,
                            "end_time_sec": index * 5 + 30,
                            "heart_peak_bpm": 68 + index,
                            "breath_peak_bpm": 14 + 0.2 * index,
                            "heart_snr": 4 + index,
                            "breath_snr": 6 + index,
                            "reference_heart_bpm": 69 + index,
                            "reference_breath_bpm": 14.5 + 0.2 * index,
                        }
                    )
            output = root / "model"
            metrics = train_models(features, None, output, "random_forest")
            self.assertEqual(metrics["status"], "trained")
            self.assertTrue(
                (output / "models" / "heart_rate_model.pkl").exists()
            )
            self.assertTrue(
                (output / "models" / "breath_rate_model.pkl").exists()
            )

    def test_offline_phase_plotter_saves_plot(self):
        try:
            import matplotlib  # noqa: F401
        except Exception:
            self.skipTest("matplotlib is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / "selected_chest_beam_trace.csv"
            write_synthetic_trace(trace)
            output = root / "phase.png"
            figure = create_plot(trace, output, window_sec=30.0)
            self.assertTrue(output.exists())
            import matplotlib.pyplot as plt

            plt.close(figure)


if __name__ == "__main__":
    unittest.main()
