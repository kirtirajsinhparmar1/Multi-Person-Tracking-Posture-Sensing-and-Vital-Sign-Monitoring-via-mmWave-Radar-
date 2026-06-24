from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vital_model_training.build_training_windows_from_logs import (  # noqa: E402
    build_dataset,
)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate optional baseline vital models on FE03 log folders."
    )
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--logs", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--window-sec", type=float, default=30.0)
    parser.add_argument("--stride-sec", type=float, default=5.0)
    return parser


def evaluate(model_dir, logs, out_dir, window_sec=30.0, stride_sec=5.0):
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    windows_dir = output / "windows"
    summary = build_dataset(
        logs, windows_dir, window_sec=window_sec, stride_sec=stride_sec
    )
    feature_path = windows_dir / "feature_table.csv"
    if not feature_path.exists() or not feature_path.read_text(encoding="utf-8"):
        report = {"status": "no_valid_windows", **summary}
        (output / "report.md").write_text(
            "# Vital model evaluation\n\nNo valid locked-phase windows.\n",
            encoding="utf-8",
        )
        return report
    with feature_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    def load(name):
        path = Path(model_dir).expanduser() / name
        with path.open("rb") as handle:
            return pickle.load(handle)

    heart = load("heart_rate_model.pkl")
    breath = load("breath_rate_model.pkl")

    def predict(artifact, row):
        model = artifact.get("model", artifact)
        columns = artifact.get("feature_columns", [])
        vector = np.asarray(
            [[float(row.get(column, 0.0) or 0.0) for column in columns]]
        )
        return float(model.predict(vector)[0])

    predictions = []
    for row in rows:
        predictions.append(
            {
                "recording_id": row.get("recording_id", ""),
                "start_time_sec": row.get("start_time_sec", ""),
                "end_time_sec": row.get("end_time_sec", ""),
                "classical_heart_bpm": float(row.get("heart_peak_bpm", 0.0) or 0.0),
                "ml_heart_bpm": predict(heart, row),
                "classical_breath_bpm": float(
                    row.get("breath_peak_bpm", 0.0) or 0.0
                ),
                "ml_breath_bpm": predict(breath, row),
                "heart_snr": row.get("heart_snr", ""),
                "breath_snr": row.get("breath_snr", ""),
            }
        )
    for vital_name in ("heart", "breath"):
        values = np.asarray(
            [float(row[f"ml_{vital_name}_bpm"]) for row in predictions],
            dtype=float,
        )
        for index, row in enumerate(predictions):
            start = max(0, index - 2)
            row[f"smoothed_ml_{vital_name}_bpm"] = float(
                np.median(values[start : index + 1])
            )
    with (output / "predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    try:
        import matplotlib.pyplot as plt

        x = np.arange(len(predictions))
        figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for axis, vital_name, snr_name in (
            (axes[0], "breath", "breath_snr"),
            (axes[1], "heart", "heart_snr"),
        ):
            axis.plot(
                x,
                [row[f"classical_{vital_name}_bpm"] for row in predictions],
                label="Classical",
                alpha=0.7,
            )
            axis.plot(
                x,
                [row[f"smoothed_ml_{vital_name}_bpm"] for row in predictions],
                label="ML smoothed",
                linewidth=1.5,
            )
            confidence_axis = axis.twinx()
            confidence_axis.plot(
                x,
                [float(row.get(snr_name, 0.0) or 0.0) for row in predictions],
                color="#777777",
                alpha=0.35,
                label="Peak SNR",
            )
            confidence_axis.set_ylabel("Peak SNR")
            axis.set_ylabel(f"{vital_name.title()} BPM")
            axis.grid(True, alpha=0.25)
            axis.legend(loc="upper left")
        axes[-1].set_xlabel("Window index")
        figure.tight_layout()
        figure.savefig(output / "confidence_predictions.png", dpi=150)
        plt.close(figure)
    except Exception:
        pass
    report = {
        "status": "evaluated",
        "window_count": len(predictions),
        "model_dir": str(Path(model_dir).expanduser()),
    }
    (output / "report.md").write_text(
        "# Vital model evaluation\n\n"
        f"- Windows: {len(predictions)}\n"
        "- Classical and optional ML estimates are in `predictions.csv`.\n"
        "- Treat results as preliminary until compared with reference labels.\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    args = build_arg_parser().parse_args()
    print(
        json.dumps(
            evaluate(
                args.model_dir,
                args.logs,
                args.out,
                args.window_sec,
                args.stride_sec,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
