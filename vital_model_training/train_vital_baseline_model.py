from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path

import numpy as np


NON_FEATURE_COLUMNS = {
    "recording_id",
    "source_csv",
    "target_id",
    "phase_segment_id",
    "start_time_sec",
    "end_time_sec",
    "reference_heart_bpm",
    "reference_breath_bpm",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train optional baseline regressors from FE03 feature windows."
    )
    parser.add_argument("--features", required=True)
    parser.add_argument("--labels")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--model-type",
        choices=("random_forest", "gradient_boosting"),
        default="random_forest",
    )
    return parser


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _merge_labels(rows, labels):
    for row in rows:
        if _number(row.get("reference_heart_bpm")) is not None:
            continue
        midpoint = 0.5 * (
            float(row.get("start_time_sec", 0))
            + float(row.get("end_time_sec", 0))
        )
        for label in labels:
            if label.get("recording_id") != row.get("recording_id"):
                continue
            start = _number(label.get("start_time_sec"))
            end = _number(label.get("end_time_sec"))
            start = float("-inf") if start is None else start
            end = float("inf") if end is None else end
            if start <= midpoint <= end:
                row["reference_heart_bpm"] = label.get(
                    "reference_heart_bpm", ""
                )
                row["reference_breath_bpm"] = label.get(
                    "reference_breath_bpm", ""
                )
                break


def train_models(features_path, labels_path, out_dir, model_type):
    output = Path(out_dir).expanduser().resolve()
    model_dir = output / "models"
    plot_dir = output / "plots"
    model_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(Path(features_path).expanduser())
    labels = (
        _read_csv(Path(labels_path).expanduser())
        if labels_path and Path(labels_path).expanduser().exists()
        else []
    )
    _merge_labels(rows, labels)
    labeled = [
        row
        for row in rows
        if _number(row.get("reference_heart_bpm")) is not None
        and _number(row.get("reference_breath_bpm")) is not None
    ]
    if not labeled:
        metrics = {
            "status": "reference_labels_required",
            "feature_rows": len(rows),
            "message": (
                "Feature extraction is complete. Supervised training requires "
                "reference heart/breath labels."
            ),
        }
        (output / "metrics.json").write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )
        (output / "predictions.csv").write_text("", encoding="utf-8")
        return metrics

    try:
        from sklearn.ensemble import (
            GradientBoostingRegressor,
            RandomForestRegressor,
        )
        from sklearn.metrics import mean_absolute_error, mean_squared_error
    except Exception as exc:
        metrics = {
            "status": "sklearn_unavailable",
            "feature_rows": len(rows),
            "labeled_rows": len(labeled),
            "message": str(exc),
        }
        (output / "metrics.json").write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )
        return metrics

    columns = [
        key
        for key in labeled[0]
        if key not in NON_FEATURE_COLUMNS
        and all(_number(row.get(key)) is not None for row in labeled)
    ]
    x = np.asarray(
        [[float(row[column]) for column in columns] for row in labeled],
        dtype=float,
    )
    y_heart = np.asarray(
        [float(row["reference_heart_bpm"]) for row in labeled], dtype=float
    )
    y_breath = np.asarray(
        [float(row["reference_breath_bpm"]) for row in labeled], dtype=float
    )
    split = max(1, min(len(labeled) - 1, int(round(len(labeled) * 0.8))))
    if len(labeled) < 3:
        split = len(labeled)
    train_index = np.arange(split)
    test_index = np.arange(split, len(labeled))
    if test_index.size == 0:
        test_index = train_index

    def new_model():
        if model_type == "gradient_boosting":
            return GradientBoostingRegressor(random_state=42)
        return RandomForestRegressor(
            n_estimators=200, random_state=42, min_samples_leaf=1
        )

    heart_model = new_model()
    breath_model = new_model()
    heart_model.fit(x[train_index], y_heart[train_index])
    breath_model.fit(x[train_index], y_breath[train_index])
    heart_prediction = heart_model.predict(x)
    breath_prediction = breath_model.predict(x)
    for name, model in (
        ("heart_rate_model.pkl", heart_model),
        ("breath_rate_model.pkl", breath_model),
    ):
        with (model_dir / name).open("wb") as handle:
            pickle.dump(
                {"model": model, "feature_columns": columns},
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
    metrics = {
        "status": "trained",
        "model_type": model_type,
        "feature_columns": columns,
        "labeled_rows": len(labeled),
        "heart_mae": float(
            mean_absolute_error(y_heart[test_index], heart_prediction[test_index])
        ),
        "heart_rmse": float(
            mean_squared_error(
                y_heart[test_index],
                heart_prediction[test_index],
            )
            ** 0.5
        ),
        "breath_mae": float(
            mean_absolute_error(
                y_breath[test_index], breath_prediction[test_index]
            )
        ),
        "breath_rmse": float(
            mean_squared_error(
                y_breath[test_index],
                breath_prediction[test_index],
            )
            ** 0.5
        ),
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    prediction_rows = []
    for row, heart, breath in zip(labeled, heart_prediction, breath_prediction):
        prediction_rows.append(
            {
                "recording_id": row.get("recording_id", ""),
                "start_time_sec": row.get("start_time_sec", ""),
                "end_time_sec": row.get("end_time_sec", ""),
                "reference_heart_bpm": row["reference_heart_bpm"],
                "classical_heart_bpm": row.get("heart_peak_bpm", ""),
                "ml_heart_bpm": heart,
                "reference_breath_bpm": row["reference_breath_bpm"],
                "classical_breath_bpm": row.get("breath_peak_bpm", ""),
                "ml_breath_bpm": breath,
            }
        )
    with (output / "predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)

    try:
        import matplotlib.pyplot as plt

        for name, reference, classical, predicted in (
            (
                "classical_vs_ml_hr.png",
                y_heart,
                np.asarray(
                    [float(row.get("heart_peak_bpm", 0)) for row in labeled]
                ),
                heart_prediction,
            ),
            (
                "classical_vs_ml_br.png",
                y_breath,
                np.asarray(
                    [float(row.get("breath_peak_bpm", 0)) for row in labeled]
                ),
                breath_prediction,
            ),
        ):
            figure, axis = plt.subplots(figsize=(7, 5))
            axis.scatter(reference, classical, label="Classical", alpha=0.7)
            axis.scatter(reference, predicted, label="ML", alpha=0.7)
            low = float(min(np.min(reference), np.min(classical), np.min(predicted)))
            high = float(max(np.max(reference), np.max(classical), np.max(predicted)))
            axis.plot([low, high], [low, high], "k--", linewidth=1)
            axis.set_xlabel("Reference BPM")
            axis.set_ylabel("Estimated BPM")
            axis.legend()
            axis.grid(True, alpha=0.25)
            figure.tight_layout()
            figure.savefig(plot_dir / name, dpi=150)
            plt.close(figure)
    except Exception:
        pass
    return metrics


def main() -> int:
    args = build_arg_parser().parse_args()
    metrics = train_models(args.features, args.labels, args.out, args.model_type)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
