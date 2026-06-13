"""Compare TI Pose/Fall training run folders.

Example:
    python compare_pose_models.py --runs outputs/ti_full_1600 outputs/ti_robust_augmented_1600 --output outputs/model_comparison
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FIELDNAMES = [
    "run",
    "model_type",
    "normalize",
    "augment",
    "zero_snr",
    "split_mode",
    "balance_mode",
    "class_weighting",
    "weighted_sampler",
    "num_classes",
    "class_names",
    "accuracy",
    "macro_f1",
    "weighted_f1",
    "best_epoch",
    "best_val_loss",
    "num_train_recordings",
    "num_test_recordings",
]


def load_metrics(run_dir: Path) -> dict:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise FileNotFoundError(f"Missing metrics.json: {metrics_path}")
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def row_for_run(run_dir: Path) -> dict:
    metrics = load_metrics(run_dir)
    class_names = metrics.get("class_names") or []
    if isinstance(class_names, str):
        class_names_text = class_names
        num_classes = int(metrics.get("num_classes", 0))
    else:
        class_names_text = "|".join(str(name) for name in class_names)
        num_classes = int(metrics.get("num_classes", len(class_names)))
    return {
        "run": str(run_dir),
        "model_type": metrics.get("model_type", "unknown"),
        "normalize": bool(metrics.get("normalize", False)),
        "augment": bool(metrics.get("augment", False)),
        "zero_snr": bool(metrics.get("zero_snr", False)),
        "split_mode": metrics.get("split_mode", "unknown"),
        "balance_mode": metrics.get("balance_mode", "unknown"),
        "class_weighting": metrics.get("class_weighting", "none"),
        "weighted_sampler": bool(metrics.get("weighted_sampler", False)),
        "num_classes": num_classes,
        "class_names": class_names_text,
        "accuracy": float(metrics.get("accuracy_percent", 0.0)),
        "macro_f1": float(metrics.get("macro_f1", 0.0)),
        "weighted_f1": float(metrics.get("weighted_f1", 0.0)),
        "best_epoch": int(metrics.get("best_epoch", 0)),
        "best_val_loss": float(metrics.get("best_val_loss", 0.0)),
        "num_train_recordings": metrics.get("num_train_recordings", metrics.get("train_recording_count", "")),
        "num_test_recordings": metrics.get("num_test_recordings", metrics.get("test_recording_count", "")),
    }


def print_table(rows: list[dict]) -> None:
    widths = {
        field: max(len(field), *(len(format_value(row[field])) for row in rows))
        for field in FIELDNAMES
    }
    header = "  ".join(field.ljust(widths[field]) for field in FIELDNAMES)
    print(header)
    print("  ".join("-" * widths[field] for field in FIELDNAMES))
    for row in rows:
        print("  ".join(format_value(row[field]).ljust(widths[field]) for field in FIELDNAMES))


def format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_macro_f1_plot(path: Path, rows: list[dict]) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed; skipping model_comparison_macro_f1.png")
        return False

    labels = [Path(row["run"]).name for row in rows]
    values = [float(row["macro_f1"]) for row in rows]
    plt.figure(figsize=(max(8, len(rows) * 2.0), 5))
    plt.bar(labels, values)
    plt.ylabel("macro F1")
    plt.ylim(0, 1.05)
    plt.title("Model comparison by validation macro F1")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True, help="Training output folders to compare.")
    parser.add_argument("--output", type=Path, default=Path("outputs/model_comparison"), help="Output directory for comparison files.")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    rows = [row_for_run(run_dir) for run_dir in args.runs]
    print_table(rows)

    csv_path = args.output / "model_comparison.csv"
    write_csv(csv_path, rows)
    print(f"Saved: {csv_path}")

    plot_path = args.output / "model_comparison_macro_f1.png"
    if write_macro_f1_plot(plot_path, rows):
        print(f"Saved: {plot_path}")


if __name__ == "__main__":
    main()
