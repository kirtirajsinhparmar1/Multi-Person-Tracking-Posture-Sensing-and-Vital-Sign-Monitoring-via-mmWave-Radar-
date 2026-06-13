"""Train/export a PC model that matches TI Pose/Fall feature formatting.

This script is intentionally not run automatically. It mirrors the notebook's
feature order and PyTorch architecture, records validation curves, saves the
best model by validation macro F1, and exports ONNX from that best checkpoint.

Example:
    python train_or_export_ti_pose_model.py --classes-zip path/to/classes.zip --epochs 100 --output outputs/ti_100epoch_plots
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
import json
import math
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Iterable, Sequence, Tuple


CLASS_NAMES = ["STANDING", "SITTING", "LYING", "FALLING", "WALKING"]
FEATURE_NAMES_22 = [
    "posz",
    "velx",
    "vely",
    "velz",
    "accx",
    "accy",
    "accz",
    "y0",
    "z0",
    "snr0",
    "y1",
    "z1",
    "snr1",
    "y2",
    "z2",
    "snr2",
    "y3",
    "z3",
    "snr3",
    "y4",
    "z4",
    "snr4",
]

WINDOW_SIZE = 8
MIN_POINTS = 5
INPUT_SIZE = WINDOW_SIZE * len(FEATURE_NAMES_22)
FLATTEN_ORDER = "channel_major: posz_f0..posz_f7, velx_f0..velx_f7, ..., snr4_f0..snr4_f7"
FEATURE_NAMES_176 = [
    f"{feature_name}_f{frame_index}"
    for feature_name in FEATURE_NAMES_22
    for frame_index in range(WINDOW_SIZE)
]
FEATURE_INDEX = {name: index for index, name in enumerate(FEATURE_NAMES_22)}
HEIGHT_FEATURES = ["posz", "z0", "z1", "z2", "z3", "z4"]
RELATIVE_Y_FEATURES = ["y0", "y1", "y2", "y3", "y4"]
VELOCITY_FEATURES = ["velx", "vely", "velz"]
ACCELERATION_FEATURES = ["accx", "accy", "accz"]
SNR_FEATURES = ["snr0", "snr1", "snr2", "snr3", "snr4"]
POINT_TRIPLETS = [("y0", "z0", "snr0"), ("y1", "z1", "snr1"), ("y2", "z2", "snr2"), ("y3", "z3", "snr3"), ("y4", "z4", "snr4")]


def create_model(model_type: str = "mlp", num_classes: int | None = None):
    import torch.nn as nn
    output_size = num_classes if num_classes is not None else len(CLASS_NAMES)

    class LinearModel(nn.Module):
        def __init__(self, input_size: int, output_size: int) -> None:
            super().__init__()
            self.bn1 = nn.BatchNorm1d(num_features=input_size)
            self.fc1 = nn.Linear(input_size, 64)
            self.bn2 = nn.BatchNorm1d(64)
            self.fc2 = nn.Linear(64, 32)
            self.bn3 = nn.BatchNorm1d(32)
            self.fc3 = nn.Linear(32, 16)
            self.bn4 = nn.BatchNorm1d(16)
            self.fc4 = nn.Linear(16, output_size)
            self.relu = nn.ReLU()

        def forward(self, x):
            x = self.relu(self.fc1(self.bn1(x)))
            x = self.relu(self.fc2(self.bn2(x)))
            x = self.bn4(self.fc3(self.bn3(x)))
            return self.fc4(x)

    class TemporalCNN(nn.Module):
        def __init__(self, output_size: int) -> None:
            super().__init__()
            self.conv1 = nn.Conv1d(len(FEATURE_NAMES_22), 64, kernel_size=3, padding=1)
            self.bn1 = nn.BatchNorm1d(64)
            self.conv2 = nn.Conv1d(64, 64, kernel_size=3, padding=1)
            self.bn2 = nn.BatchNorm1d(64)
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.fc1 = nn.Linear(64, 32)
            self.fc2 = nn.Linear(32, output_size)
            self.relu = nn.ReLU()

        def forward(self, x):
            x = x.reshape(-1, len(FEATURE_NAMES_22), WINDOW_SIZE)
            x = self.relu(self.bn1(self.conv1(x)))
            x = self.relu(self.bn2(self.conv2(x)))
            x = self.pool(x).squeeze(-1)
            x = self.relu(self.fc1(x))
            return self.fc2(x)

    if model_type == "mlp":
        return LinearModel(INPUT_SIZE, output_size)
    if model_type == "temporal_cnn":
        return TemporalCNN(output_size)
    raise ValueError(f"Unsupported model type: {model_type}")


def _float(row: dict, name: str, default: float = 0.0) -> float:
    value = row.get(name, "")
    if value == "" or value is None:
        return default
    return float(value)


def _point_columns(row: dict) -> Iterable[Tuple[float, float, float]]:
    pointy_names = [name for name in row if name.startswith("pointy")]
    if pointy_names:
        for pointy_name in pointy_names:
            suffix = pointy_name.removeprefix("pointy")
            pointz_name = f"pointz{suffix}"
            snr_name = f"snr{suffix}"
            if row.get(pointy_name) and row.get(pointz_name) and row.get(snr_name):
                yield float(row[pointy_name]), float(row[pointz_name]), float(row[snr_name])
        return

    idx = 0
    while f"y{idx}" in row and f"z{idx}" in row and f"snr{idx}" in row:
        yield _float(row, f"y{idx}"), _float(row, f"z{idx}"), _float(row, f"snr{idx}")
        idx += 1


def build_frame_features(row: dict) -> list[float] | None:
    points = []
    posy = _float(row, "posy")
    for y_value, z_value, snr in _point_columns(row):
        relative_y = y_value if "y0" in row else y_value - posy
        points.append((z_value, relative_y, z_value, snr))

    points.sort(key=lambda item: item[0])
    points = points[-MIN_POINTS:]
    if len(points) < MIN_POINTS:
        return None

    feature22 = [
        _float(row, "posz"),
        _float(row, "velx"),
        _float(row, "vely"),
        _float(row, "velz"),
        _float(row, "accx"),
        _float(row, "accy"),
        _float(row, "accz"),
    ]
    for _, relative_y, z_value, snr in points:
        feature22.extend([relative_y, z_value, snr])
    return feature22


def flatten_window(frames: Sequence[Sequence[float]]) -> list[float]:
    return [
        frames[frame_index][feature_index]
        for feature_index in range(len(FEATURE_NAMES_22))
        for frame_index in range(WINDOW_SIZE)
    ]


def load_dataset(classes_dir: Path) -> tuple[list[list[float]], list[int], dict]:
    xs = []
    ys = []
    stats = {
        "recordings_per_class": {class_name: 0 for class_name in CLASS_NAMES},
        "usable_windows_per_class": {class_name: 0 for class_name in CLASS_NAMES},
    }
    for class_index, class_name in enumerate(CLASS_NAMES):
        class_dir = classes_dir / class_name.lower()
        for csv_path in sorted(class_dir.glob("*.csv")):
            stats["recordings_per_class"][class_name] += 1
            frames = []
            with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
                for row in csv.DictReader(handle):
                    feature22 = build_frame_features(row)
                    if feature22 is not None:
                        frames.append(feature22)

            usable_windows = max(0, len(frames) - WINDOW_SIZE + 1)
            stats["usable_windows_per_class"][class_name] += usable_windows
            for start in range(usable_windows):
                xs.append(flatten_window(frames[start : start + WINDOW_SIZE]))
                ys.append(class_index)

    stats["total_windows"] = len(xs)
    stats["class_counts"] = {
        class_name: stats["usable_windows_per_class"][class_name]
        for class_name in CLASS_NAMES
    }
    return xs, ys, stats


def load_dataset_from_zip(classes_zip: Path) -> tuple[list[list[float]], list[int], dict]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(classes_zip) as archive:
            archive.extractall(temp_path)
        return load_dataset(temp_path)


def normalize_output_dir(output: Path) -> Path:
    output_dir = Path(output)
    if output_dir.suffix.lower() == ".onnx":
        converted = output_dir.with_suffix("")
        print(
            f"Warning: --output is an output directory, not an ONNX file. "
            f"Using {converted} instead.",
            flush=True,
        )
        output_dir = converted
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def class_count_dict(values: Sequence[int], class_names: Sequence[str] | None = None) -> dict[str, int]:
    names = list(class_names or CLASS_NAMES)
    counts = Counter(values)
    return {class_name: int(counts.get(index, 0)) for index, class_name in enumerate(names)}


def should_print_epoch(epoch: int, total_epochs: int) -> bool:
    if total_epochs <= 10:
        return True
    return epoch == 1 or epoch == total_epochs or epoch % 10 == 0


def print_dataset_stats(stats: dict, y_train: Sequence[int], y_test: Sequence[int], class_names: Sequence[str] | None = None) -> None:
    names = list(class_names or CLASS_NAMES)
    print("Dataset stats:")
    for class_name in names:
        recordings = stats["recordings_per_class"].get(class_name, 0)
        windows = stats["usable_windows_per_class"].get(class_name, 0)
        print(f"  {class_name}: recordings={recordings} usable_windows={windows}")
    print(f"  total_windows={stats['total_windows']}")
    print(f"  train_count={len(y_train)} test_count={len(y_test)}")
    print(f"  train_class_counts={class_count_dict(y_train, names)}")
    print(f"  test_class_counts={class_count_dict(y_test, names)}")


def channel_slice(feature_name: str) -> slice:
    start = FEATURE_INDEX[feature_name] * WINDOW_SIZE
    return slice(start, start + WINDOW_SIZE)


def apply_zero_snr_array(array, enabled: bool) -> None:
    if not enabled:
        return
    for feature_name in SNR_FEATURES:
        array[:, channel_slice(feature_name)] = 0.0


def compute_scaler(train_array, eps: float = 1e-6) -> tuple:
    import numpy as np

    mean = train_array.mean(axis=0).astype(np.float32)
    std = train_array.std(axis=0).astype(np.float32)
    std = np.where(std < eps, eps, std).astype(np.float32)
    return mean, std


def write_scaler_files(json_path: Path, npz_path: Path, mean, std) -> None:
    import numpy as np

    payload = {
        "mean": [float(value) for value in mean.tolist()],
        "std": [float(value) for value in std.tolist()],
        "feature_names_176": FEATURE_NAMES_176,
        "feature_names_22": FEATURE_NAMES_22,
        "flatten_order": FLATTEN_ORDER,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    np.savez(
        npz_path,
        mean=np.asarray(mean, dtype=np.float32),
        std=np.asarray(std, dtype=np.float32),
        feature_names_176=np.asarray(FEATURE_NAMES_176),
        feature_names_22=np.asarray(FEATURE_NAMES_22),
        flatten_order=np.asarray([FLATTEN_ORDER]),
    )


def build_augmentation_config(args: argparse.Namespace) -> dict:
    return {
        "enabled": bool(args.augment),
        "height_scale_min": args.height_scale_min,
        "height_scale_max": args.height_scale_max,
        "height_shift_std": args.height_shift_std,
        "relative_y_scale_min": args.relative_y_scale_min,
        "relative_y_scale_max": args.relative_y_scale_max,
        "relative_y_noise_std": args.relative_y_noise_std,
        "velocity_noise_std": args.velocity_noise_std,
        "acceleration_noise_std": args.acceleration_noise_std,
        "snr_scale_min": args.snr_scale_min,
        "snr_scale_max": args.snr_scale_max,
        "snr_noise_std": args.snr_noise_std,
        "snr_dropout": args.snr_dropout,
        "point_dropout": args.point_dropout,
        "feature_noise_std": args.feature_noise_std,
    }


class PoseWindowDataset:
    def __init__(
        self,
        xs,
        ys,
        *,
        augment: bool,
        augmentation_config: dict,
        normalize: bool,
        mean,
        std,
    ) -> None:
        import torch

        self.xs = torch.tensor(xs, dtype=torch.float32)
        self.ys = torch.tensor(ys, dtype=torch.long)
        self.augment = bool(augment)
        self.augmentation_config = augmentation_config
        self.normalize = bool(normalize)
        self.mean = torch.tensor(mean, dtype=torch.float32) if mean is not None else None
        self.std = torch.tensor(std, dtype=torch.float32) if std is not None else None

    def __len__(self) -> int:
        return int(self.ys.shape[0])

    def __getitem__(self, index: int):
        x = self.xs[index].clone()
        if self.augment:
            x = augment_feature_vector(x, self.augmentation_config)
        if self.normalize:
            x = (x - self.mean) / self.std
        return x, self.ys[index]


def augment_feature_vector(x, config: dict):
    import torch

    frames = x.reshape(len(FEATURE_NAMES_22), WINDOW_SIZE).transpose(0, 1).clone()

    if config["feature_noise_std"] > 0:
        frames = frames + torch.randn_like(frames) * float(config["feature_noise_std"])

    height_scale = _uniform_scalar(torch, config["height_scale_min"], config["height_scale_max"])
    height_shift = torch.randn(1, dtype=frames.dtype, device=frames.device) * float(config["height_shift_std"])
    for name in HEIGHT_FEATURES:
        frames[:, FEATURE_INDEX[name]] = frames[:, FEATURE_INDEX[name]] * height_scale + height_shift

    relative_y_scale = _uniform_scalar(torch, config["relative_y_scale_min"], config["relative_y_scale_max"])
    for name in RELATIVE_Y_FEATURES:
        column = FEATURE_INDEX[name]
        frames[:, column] = frames[:, column] * relative_y_scale
        if config["relative_y_noise_std"] > 0:
            frames[:, column] += torch.randn(WINDOW_SIZE, dtype=frames.dtype, device=frames.device) * float(config["relative_y_noise_std"])

    for name in VELOCITY_FEATURES:
        if config["velocity_noise_std"] > 0:
            frames[:, FEATURE_INDEX[name]] += torch.randn(WINDOW_SIZE, dtype=frames.dtype, device=frames.device) * float(config["velocity_noise_std"])

    for name in ACCELERATION_FEATURES:
        if config["acceleration_noise_std"] > 0:
            frames[:, FEATURE_INDEX[name]] += torch.randn(WINDOW_SIZE, dtype=frames.dtype, device=frames.device) * float(config["acceleration_noise_std"])

    snr_scale = _uniform_scalar(torch, config["snr_scale_min"], config["snr_scale_max"])
    for name in SNR_FEATURES:
        column = FEATURE_INDEX[name]
        frames[:, column] = frames[:, column] * snr_scale
        if config["snr_noise_std"] > 0:
            frames[:, column] += torch.randn(WINDOW_SIZE, dtype=frames.dtype, device=frames.device) * float(config["snr_noise_std"])
        if config["snr_dropout"] > 0:
            mask = torch.rand(WINDOW_SIZE, dtype=frames.dtype, device=frames.device) < float(config["snr_dropout"])
            frames[mask, column] = 0.0

    if config["point_dropout"] > 0:
        point_mask = torch.rand(len(POINT_TRIPLETS), dtype=frames.dtype, device=frames.device) < float(config["point_dropout"])
        if bool(point_mask.all()):
            point_mask[int(torch.randint(0, len(POINT_TRIPLETS), (1,)).item())] = False
        for drop, names in zip(point_mask.tolist(), POINT_TRIPLETS):
            if drop:
                for name in names:
                    frames[:, FEATURE_INDEX[name]] = 0.0

    return frames.transpose(0, 1).reshape(INPUT_SIZE)


def _uniform_batch(torch_module, shape: tuple[int, ...], min_value: float, max_value: float, *, dtype, device):
    low = float(min_value)
    high = float(max_value)
    if high <= low:
        return torch_module.full(shape, low, dtype=dtype, device=device)
    return torch_module.empty(shape, dtype=dtype, device=device).uniform_(low, high)


def augment_feature_batch(x, config: dict):
    """Apply the same augmentation policy as augment_feature_vector to a full batch."""
    import torch

    if x.numel() == 0:
        return x

    batch = x.clone()
    seq = batch.view(batch.shape[0], len(FEATURE_NAMES_22), WINDOW_SIZE)
    dtype = seq.dtype
    device = seq.device
    batch_size = seq.shape[0]

    if config["feature_noise_std"] > 0:
        seq.add_(torch.randn_like(seq) * float(config["feature_noise_std"]))

    height_indices = torch.tensor([FEATURE_INDEX[name] for name in HEIGHT_FEATURES], device=device)
    height_scale = _uniform_batch(torch, (batch_size, 1, 1), config["height_scale_min"], config["height_scale_max"], dtype=dtype, device=device)
    height_shift = torch.randn((batch_size, 1, 1), dtype=dtype, device=device) * float(config["height_shift_std"])
    seq[:, height_indices, :] = seq[:, height_indices, :] * height_scale + height_shift

    relative_y_indices = torch.tensor([FEATURE_INDEX[name] for name in RELATIVE_Y_FEATURES], device=device)
    relative_y_scale = _uniform_batch(torch, (batch_size, 1, 1), config["relative_y_scale_min"], config["relative_y_scale_max"], dtype=dtype, device=device)
    seq[:, relative_y_indices, :] = seq[:, relative_y_indices, :] * relative_y_scale
    if config["relative_y_noise_std"] > 0:
        seq[:, relative_y_indices, :] += (
            torch.randn((batch_size, len(RELATIVE_Y_FEATURES), WINDOW_SIZE), dtype=dtype, device=device)
            * float(config["relative_y_noise_std"])
        )

    velocity_indices = torch.tensor([FEATURE_INDEX[name] for name in VELOCITY_FEATURES], device=device)
    if config["velocity_noise_std"] > 0:
        seq[:, velocity_indices, :] += (
            torch.randn((batch_size, len(VELOCITY_FEATURES), WINDOW_SIZE), dtype=dtype, device=device)
            * float(config["velocity_noise_std"])
        )

    acceleration_indices = torch.tensor([FEATURE_INDEX[name] for name in ACCELERATION_FEATURES], device=device)
    if config["acceleration_noise_std"] > 0:
        seq[:, acceleration_indices, :] += (
            torch.randn((batch_size, len(ACCELERATION_FEATURES), WINDOW_SIZE), dtype=dtype, device=device)
            * float(config["acceleration_noise_std"])
        )

    snr_indices = torch.tensor([FEATURE_INDEX[name] for name in SNR_FEATURES], device=device)
    snr_scale = _uniform_batch(torch, (batch_size, 1, 1), config["snr_scale_min"], config["snr_scale_max"], dtype=dtype, device=device)
    seq[:, snr_indices, :] = seq[:, snr_indices, :] * snr_scale
    if config["snr_noise_std"] > 0:
        seq[:, snr_indices, :] += (
            torch.randn((batch_size, len(SNR_FEATURES), WINDOW_SIZE), dtype=dtype, device=device)
            * float(config["snr_noise_std"])
        )
    if config["snr_dropout"] > 0:
        snr_mask = torch.rand((batch_size, len(SNR_FEATURES), WINDOW_SIZE), dtype=dtype, device=device) < float(config["snr_dropout"])
        seq[:, snr_indices, :] = seq[:, snr_indices, :].masked_fill(snr_mask, 0.0)

    if config["point_dropout"] > 0:
        point_mask = torch.rand((batch_size, len(POINT_TRIPLETS)), dtype=dtype, device=device) < float(config["point_dropout"])
        all_dropped = point_mask.all(dim=1)
        if bool(all_dropped.any()):
            all_dropped_rows = all_dropped.nonzero(as_tuple=False).flatten()
            keep_indices = torch.randint(0, len(POINT_TRIPLETS), (int(all_dropped_rows.numel()),), device=device)
            point_mask[all_dropped_rows, keep_indices] = False
        for point_index, names in enumerate(POINT_TRIPLETS):
            keep = (~point_mask[:, point_index]).to(dtype=dtype).view(batch_size, 1, 1)
            triplet_indices = torch.tensor([FEATURE_INDEX[name] for name in names], device=device)
            seq[:, triplet_indices, :] = seq[:, triplet_indices, :] * keep

    return seq.reshape(batch.shape[0], INPUT_SIZE)


def normalize_feature_batch(x, mean_tensor, std_tensor):
    if mean_tensor is None or std_tensor is None:
        return x
    return (x - mean_tensor) / std_tensor


def resolve_device(torch_module, requested: str):
    if requested == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch_module.cuda.is_available():
        raise SystemExit("--device cuda was requested, but CUDA is not available.")
    return torch_module.device(requested)


def move_state_dict_to_cpu(state_dict: dict) -> dict:
    return {key: value.detach().cpu().clone() for key, value in state_dict.items()}


def format_percent(value) -> str:
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return "NA"
    if math.isnan(value_float):
        return "NA"
    return f"{value_float:.1f}%"


def format_float(value, digits: int = 4) -> str:
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return "NA"
    if math.isnan(value_float):
        return "NA"
    return f"{value_float:.{digits}f}"


def _uniform_scalar(torch_module, min_value: float, max_value: float):
    low = float(min_value)
    high = float(max_value)
    if high <= low:
        return torch_module.tensor(low, dtype=torch_module.float32)
    return torch_module.empty(1).uniform_(low, high)[0]


def evaluate_model(
    model,
    loader,
    loss_fn,
    torch_module,
    *,
    device=None,
    mean_tensor=None,
    std_tensor=None,
    max_samples: int | None = None,
) -> dict:
    from sklearn.metrics import f1_score

    device = device or torch_module.device("cpu")
    model.eval()
    total_loss = 0.0
    total_count = 0
    y_true = []
    y_pred = []
    probs_all = []

    with torch_module.inference_mode():
        for batch_x, batch_y in loader:
            if max_samples is not None:
                remaining = int(max_samples) - total_count
                if remaining <= 0:
                    break
                if int(batch_y.shape[0]) > remaining:
                    batch_x = batch_x[:remaining]
                    batch_y = batch_y[:remaining]
            batch_x = batch_x.to(device, non_blocking=device.type == "cuda")
            batch_y = batch_y.to(device, non_blocking=device.type == "cuda")
            batch_x = normalize_feature_batch(batch_x, mean_tensor, std_tensor)
            logits = model(batch_x)
            loss = loss_fn(logits, batch_y)
            probs = torch_module.softmax(logits, dim=1)
            pred = logits.argmax(dim=1)
            batch_count = int(batch_y.shape[0])
            total_loss += float(loss.item()) * batch_count
            total_count += batch_count
            y_true.extend(int(value) for value in batch_y.cpu().tolist())
            y_pred.extend(int(value) for value in pred.cpu().tolist())
            probs_all.extend(probs.cpu().tolist())

    accuracy = 0.0
    if y_true:
        correct = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == predicted)
        accuracy = (correct / len(y_true)) * 100.0

    return {
        "loss": total_loss / total_count if total_count else math.nan,
        "accuracy": accuracy,
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0) if y_true else 0.0,
        "weighted_f1": f1_score(y_true, y_pred, average="weighted", zero_division=0) if y_true else 0.0,
        "y_true": y_true,
        "y_pred": y_pred,
        "probs": probs_all,
    }


def save_checkpoint(path: Path, state_dict: dict, metadata: dict, class_names: Sequence[str] | None = None) -> None:
    import torch
    names = list(class_names or CLASS_NAMES)

    payload = {
        "model_state_dict": state_dict,
        "class_names": names,
        "num_classes": len(names),
        "feature_names_22": FEATURE_NAMES_22,
        "flatten_order": FLATTEN_ORDER,
        "window_size": WINDOW_SIZE,
        "input_size": INPUT_SIZE,
        **metadata,
    }
    torch.save(payload, path)


def write_history_csv(path: Path, history: list[dict]) -> None:
    fieldnames = [
        "epoch",
        "train_loss",
        "val_loss",
        "train_accuracy",
        "val_accuracy",
        "val_macro_f1",
        "val_weighted_f1",
        "learning_rate",
        "batches",
        "epoch_seconds",
        "train_seconds",
        "train_eval_seconds",
        "val_seconds",
        "batches_per_second",
        "samples_per_second",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(history)


def write_confusion_csv(path: Path, matrix, class_names: Sequence[str] | None = None) -> None:
    names = list(class_names or CLASS_NAMES)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *names])
        for class_name, row in zip(names, matrix):
            writer.writerow([class_name, *[int(value) for value in row.tolist()]])


def write_per_class_metrics_csv(path: Path, precision, recall, f1, support, class_names: Sequence[str] | None = None) -> None:
    names = list(class_names or CLASS_NAMES)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["class_name", "precision", "recall", "f1", "support"],
        )
        writer.writeheader()
        for class_name, p_value, r_value, f_value, s_value in zip(
            names, precision, recall, f1, support
        ):
            writer.writerow(
                {
                    "class_name": class_name,
                    "precision": float(p_value),
                    "recall": float(r_value),
                    "f1": float(f_value),
                    "support": int(s_value),
                }
            )


def write_sample_predictions(path: Path, y_true, y_pred, probs, class_names: Sequence[str] | None = None, limit: int = 100) -> None:
    names = list(class_names or CLASS_NAMES)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "sample_index",
            "actual_id",
            "actual_class",
            "predicted_id",
            "predicted_class",
            "correct",
            "confidence",
            *[f"prob_{name}" for name in names],
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sample_index, (actual, predicted, probabilities) in enumerate(
            zip(y_true[:limit], y_pred[:limit], probs[:limit])
        ):
            confidence = max(probabilities) if probabilities else 0.0
            row = {
                "sample_index": sample_index,
                "actual_id": int(actual),
                "actual_class": names[int(actual)],
                "predicted_id": int(predicted),
                "predicted_class": names[int(predicted)],
                "correct": int(actual == predicted),
                "confidence": float(confidence),
            }
            row.update(
                {
                    f"prob_{class_name}": float(probability)
                    for class_name, probability in zip(names, probabilities)
                }
            )
            writer.writerow(row)


def save_plots(
    plots_dir: Path,
    history: list[dict],
    matrix,
    precision,
    recall,
    f1,
    support,
    y_true,
    y_pred,
    probs,
    class_counts: dict[str, int],
    train_counts: dict[str, int],
    test_counts: dict[str, int],
    class_names: Sequence[str] | None = None,
) -> list[dict]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    names = list(class_names or CLASS_NAMES)

    plots_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    def add_manifest(path: Path, description: str) -> None:
        manifest.append({"file": path.name, "description": description})

    epochs = [row["epoch"] for row in history]

    loss_path = plots_dir / "loss_curve.png"
    plt.figure(figsize=(8, 5))
    plt.plot(epochs, [row["train_loss"] for row in history], label="train_loss")
    plt.plot(epochs, [row["val_loss"] for row in history], label="val_loss")
    plt.xlabel("epoch")
    plt.ylabel("loss")
    plt.title("Training and validation loss")
    plt.legend()
    plt.tight_layout()
    plt.savefig(loss_path, dpi=150)
    plt.close()
    add_manifest(loss_path, "Training loss and validation loss by epoch.")

    accuracy_path = plots_dir / "accuracy_curve.png"
    plt.figure(figsize=(8, 5))
    plt.plot(epochs, [row["train_accuracy"] for row in history], label="train_accuracy")
    plt.plot(epochs, [row["val_accuracy"] for row in history], label="val_accuracy")
    plt.xlabel("epoch")
    plt.ylabel("accuracy percent")
    plt.title("Training and validation accuracy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(accuracy_path, dpi=150)
    plt.close()
    add_manifest(accuracy_path, "Training accuracy and validation accuracy by epoch.")

    f1_path = plots_dir / "f1_curve.png"
    plt.figure(figsize=(8, 5))
    plt.plot(epochs, [row["val_macro_f1"] for row in history], label="val_macro_f1")
    plt.plot(epochs, [row["val_weighted_f1"] for row in history], label="val_weighted_f1")
    plt.xlabel("epoch")
    plt.ylabel("F1")
    plt.title("Validation F1 over epochs")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f1_path, dpi=150)
    plt.close()
    add_manifest(f1_path, "Validation macro F1 and weighted F1 by epoch.")

    counts_path = plots_dir / "confusion_matrix_counts.png"
    plot_confusion_matrix(plt, np.asarray(matrix), counts_path, normalized=False, class_names=names)
    add_manifest(counts_path, "Validation confusion matrix with raw counts.")

    normalized_path = plots_dir / "confusion_matrix_normalized.png"
    plot_confusion_matrix(plt, np.asarray(matrix), normalized_path, normalized=True, class_names=names)
    add_manifest(normalized_path, "Row-normalized validation confusion matrix as percentages.")

    per_class_path = plots_dir / "per_class_metrics.png"
    x = np.arange(len(names))
    width = 0.25
    plt.figure(figsize=(10, 5))
    plt.bar(x - width, precision, width, label="precision")
    plt.bar(x, recall, width, label="recall")
    plt.bar(x + width, f1, width, label="F1")
    plt.xticks(x, names, rotation=20)
    plt.ylim(0, 1.05)
    plt.ylabel("score")
    plt.title("Per-class precision, recall, and F1")
    plt.legend()
    plt.tight_layout()
    plt.savefig(per_class_path, dpi=150)
    plt.close()
    add_manifest(per_class_path, "Grouped per-class precision, recall, and F1 on validation data.")

    class_dist_path = plots_dir / "class_distribution.png"
    total_values = [class_counts.get(name, 0) for name in names]
    train_values = [train_counts.get(name, 0) for name in names]
    test_values = [test_counts.get(name, 0) for name in names]
    plt.figure(figsize=(10, 5))
    plt.bar(x - width, total_values, width, label="total")
    plt.bar(x, train_values, width, label="train")
    plt.bar(x + width, test_values, width, label="test")
    plt.xticks(x, names, rotation=20)
    plt.ylabel("windows")
    plt.title("Class distribution")
    plt.legend()
    plt.tight_layout()
    plt.savefig(class_dist_path, dpi=150)
    plt.close()
    add_manifest(class_dist_path, "Total, train, and validation window counts per class.")

    confidence_path = plots_dir / "confidence_histogram.png"
    max_probs = [max(row) if row else 0.0 for row in probs]
    correct = [conf for conf, actual, pred in zip(max_probs, y_true, y_pred) if actual == pred]
    incorrect = [conf for conf, actual, pred in zip(max_probs, y_true, y_pred) if actual != pred]
    plt.figure(figsize=(8, 5))
    bins = np.linspace(0.0, 1.0, 21)
    if correct:
        plt.hist(correct, bins=bins, alpha=0.7, label="correct")
    if incorrect:
        plt.hist(incorrect, bins=bins, alpha=0.7, label="incorrect")
    else:
        plt.text(0.5, 0.9, "No incorrect predictions", transform=plt.gca().transAxes, ha="center")
    plt.xlabel("max predicted probability")
    plt.ylabel("count")
    plt.title("Prediction confidence histogram")
    plt.legend()
    plt.tight_layout()
    plt.savefig(confidence_path, dpi=150)
    plt.close()
    add_manifest(confidence_path, "Histogram of max predicted probability for correct vs incorrect predictions.")

    combo_path = plots_dir / "loss_accuracy_combo.png"
    fig, axes = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
    axes[0].plot(epochs, [row["train_loss"] for row in history], label="train_loss")
    axes[0].plot(epochs, [row["val_loss"] for row in history], label="val_loss")
    axes[0].set_ylabel("loss")
    axes[0].legend()
    axes[1].plot(epochs, [row["train_accuracy"] for row in history], label="train_accuracy")
    axes[1].plot(epochs, [row["val_accuracy"] for row in history], label="val_accuracy")
    axes[1].set_xlabel("epoch")
    axes[1].set_ylabel("accuracy percent")
    axes[1].legend()
    fig.suptitle("Loss and accuracy over epochs")
    fig.tight_layout()
    fig.savefig(combo_path, dpi=150)
    plt.close(fig)
    add_manifest(combo_path, "Two-panel loss and accuracy summary by epoch.")

    return manifest


def plot_confusion_matrix(plt, matrix, path: Path, normalized: bool, class_names: Sequence[str] | None = None) -> None:
    import numpy as np
    names = list(class_names or CLASS_NAMES)

    values = matrix.astype(float)
    if normalized:
        row_sums = values.sum(axis=1, keepdims=True)
        values = np.divide(values, row_sums, out=np.zeros_like(values), where=row_sums != 0)
        title = "Normalized confusion matrix"
        text = lambda value: f"{value * 100:.1f}%"
    else:
        title = "Confusion matrix counts"
        text = lambda value: str(int(value))

    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(values, interpolation="nearest", cmap="Blues")
    fig.colorbar(image, ax=ax)
    ax.set(
        xticks=np.arange(len(names)),
        yticks=np.arange(len(names)),
        xticklabels=names,
        yticklabels=names,
        ylabel="Actual",
        xlabel="Predicted",
        title=title,
    )
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", rotation_mode="anchor")

    threshold = values.max() / 2.0 if values.size and values.max() > 0 else 0.5
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            ax.text(
                j,
                i,
                text(values[i, j]),
                ha="center",
                va="center",
                color="white" if values[i, j] > threshold else "black",
            )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def check_onnx_runtime(onnx_path: Path, sample_x, pytorch_argmax: int) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("Warning: onnxruntime is not installed; skipping ONNX Runtime check.")
        return

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: sample_x.cpu().numpy()})
    onnx_argmax = int(outputs[0].argmax(axis=1)[0])
    match = onnx_argmax == pytorch_argmax
    print(
        "ONNX Runtime check: "
        f"pytorch_argmax={pytorch_argmax} onnx_argmax={onnx_argmax} match={match}"
    )


def load_checkpoint(path: Path):
    import torch

    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def predict_one(args: argparse.Namespace) -> None:
    if args.model is None:
        raise SystemExit("--predict-one requires --model")
    if args.classes_zip is None:
        raise SystemExit("--predict-one currently requires --classes-zip")

    import torch
    import numpy as np

    xs, ys, _stats = load_dataset_from_zip(args.classes_zip)
    if not xs:
        raise RuntimeError("No usable dataset samples were found")

    checkpoint = load_checkpoint(args.model)
    model_type = checkpoint.get("model_type", "mlp") if isinstance(checkpoint, dict) else "mlp"
    class_names = checkpoint.get("class_names", CLASS_NAMES) if isinstance(checkpoint, dict) else CLASS_NAMES
    model = create_model(model_type, num_classes=len(class_names))
    state_dict = checkpoint.get("model_state_dict", checkpoint)
    model.load_state_dict(state_dict)
    model.eval()

    sample_array = np.asarray([xs[0]], dtype=np.float32)
    if isinstance(checkpoint, dict) and checkpoint.get("zero_snr"):
        apply_zero_snr_array(sample_array, True)
    if isinstance(checkpoint, dict) and checkpoint.get("normalization_enabled"):
        mean = checkpoint.get("scaler_mean")
        std = checkpoint.get("scaler_std")
        if mean is None or std is None:
            raise RuntimeError(
                "Checkpoint was trained with normalization but does not include scaler_mean/scaler_std"
            )
        sample_array = (sample_array - np.asarray(mean, dtype=np.float32)) / np.asarray(std, dtype=np.float32)

    sample_x = torch.tensor(sample_array, dtype=torch.float32)
    actual = int(ys[0])
    with torch.inference_mode():
        logits = model(sample_x)
        probs = torch.softmax(logits, dim=1)[0]
        predicted = int(probs.argmax().item())

    print(f"Actual class: {class_names[actual]}")
    print(f"Predicted class: {class_names[predicted]}")
    print("Probabilities:")
    for class_name, probability in zip(class_names, probs.tolist()):
        print(f"  {class_name}: {probability:.6f}")


def load_prepared_dataset(prepared_dir: Path) -> dict:
    import numpy as np

    x_path = prepared_dir / "X.npy"
    y_path = prepared_dir / "y.npy"
    train_path = prepared_dir / "train_indices.npy"
    test_path = prepared_dir / "test_indices.npy"
    summary_path = prepared_dir / "dataset_summary.json"
    split_summary_path = prepared_dir / "split_summary.json"
    metadata_path = prepared_dir / "metadata.csv"

    for path in [x_path, y_path, train_path, test_path, metadata_path]:
        if not path.exists():
            raise FileNotFoundError(f"Prepared dataset is missing {path.name}: {path}")

    metadata_rows = []
    with metadata_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            metadata_rows.append(row)

    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    split_summary = json.loads(split_summary_path.read_text(encoding="utf-8")) if split_summary_path.exists() else {}
    return {
        "X": np.load(x_path).astype(np.float32),
        "y": np.load(y_path).astype(np.int64),
        "train_indices": np.load(train_path).astype(np.int64),
        "test_indices": np.load(test_path).astype(np.int64),
        "metadata": metadata_rows,
        "summary": summary,
        "split_summary": split_summary,
    }


def recording_count(metadata_rows: list[dict], indices) -> int:
    return len({metadata_rows[int(index)].get("recording_id", "") for index in indices})


def recording_counts_by_class(metadata_rows: list[dict], indices, class_names: Sequence[str] | None = None) -> dict[str, int]:
    names = list(class_names or CLASS_NAMES)
    recordings = {class_name: set() for class_name in names}
    for index in indices:
        row = metadata_rows[int(index)]
        class_name = row.get("class_name")
        if not class_name:
            try:
                class_name = names[int(row.get("class_id", 0))]
            except (TypeError, ValueError, IndexError):
                continue
        recordings.setdefault(class_name, set()).add(row.get("recording_id", ""))
    return {class_name: len(recording_ids) for class_name, recording_ids in recordings.items()}


def compute_balanced_class_weights(labels: Sequence[int], class_names: Sequence[str] | None = None) -> list[float]:
    names = list(class_names or CLASS_NAMES)
    counts = Counter(labels)
    total = len(labels)
    class_count = len(names)
    weights = []
    for class_index in range(class_count):
        count = counts.get(class_index, 0)
        weights.append(float(total / (class_count * count)) if count else 0.0)
    return weights


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classes-zip", type=Path, help="TI classes.zip. Not required when --prepared-dataset is used.")
    parser.add_argument("--prepared-dataset", type=Path, help="Prepared dataset folder containing X.npy/y.npy/train_indices.npy/test_indices.npy.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/ti_pose_pc_model"),
        help="Output directory, not file path.",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--eval-every", type=int, default=1, help="Deprecated alias for --eval-val-every.")
    parser.add_argument("--eval-train-every", type=int, default=10, help="Compute train accuracy every N epochs; 0 disables periodic train accuracy.")
    parser.add_argument("--eval-val-every", type=int, default=1, help="Compute validation metrics every N epochs; default 1.")
    parser.add_argument("--train-eval-max-samples", type=int, default=2000, help="Maximum samples used for periodic train accuracy.")
    parser.add_argument("--profile", action="store_true", help="Print per-epoch timing and throughput.")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="Training device.")
    parser.add_argument("--num-workers", type=int, default=0, help="DataLoader workers; default 0 avoids Windows multiprocessing overhead.")
    parser.add_argument("--patience", type=int, default=0, help="Early stopping patience on val_macro_f1; 0 disables.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--predict-one", action="store_true", help="Load --model and predict one dataset sample")
    parser.add_argument("--model", type=Path, help="Path to ti_pose_model.pt for --predict-one")
    parser.add_argument("--normalize", action="store_true", help="Normalize features using train-set mean/std and save scaler files.")
    parser.add_argument("--augment", action="store_true", help="Apply synthetic sensor-domain augmentation to training batches only.")
    parser.add_argument("--model-type", choices=["mlp", "temporal_cnn"], default="mlp", help="Model architecture to train/export.")
    parser.add_argument("--zero-snr", action="store_true", help="Set snr0..snr4 to zero for train and validation data.")
    parser.add_argument("--height-scale-min", type=float, default=0.85)
    parser.add_argument("--height-scale-max", type=float, default=1.15)
    parser.add_argument("--height-shift-std", type=float, default=0.08)
    parser.add_argument("--relative-y-scale-min", type=float, default=0.85)
    parser.add_argument("--relative-y-scale-max", type=float, default=1.15)
    parser.add_argument("--relative-y-noise-std", type=float, default=0.05)
    parser.add_argument("--velocity-noise-std", type=float, default=0.08)
    parser.add_argument("--acceleration-noise-std", type=float, default=0.12)
    parser.add_argument("--snr-scale-min", type=float, default=0.50)
    parser.add_argument("--snr-scale-max", type=float, default=1.80)
    parser.add_argument("--snr-noise-std", type=float, default=0.05)
    parser.add_argument("--snr-dropout", type=float, default=0.20)
    parser.add_argument("--point-dropout", type=float, default=0.15)
    parser.add_argument("--feature-noise-std", type=float, default=0.01)
    parser.add_argument("--class-weighting", choices=["none", "balanced"], default="none")
    parser.add_argument("--weighted-sampler", action="store_true", help="Use a WeightedRandomSampler for imbalanced training samples.")
    args = parser.parse_args()

    if args.eval_every != 1 and args.eval_val_every == 1:
        args.eval_val_every = args.eval_every
        print("Warning: --eval-every is deprecated; use --eval-val-every.")

    if args.predict_one:
        predict_one(args)
        return
    if args.prepared_dataset is None and args.classes_zip is None:
        raise SystemExit("Provide either --classes-zip or --prepared-dataset")

    output_dir = normalize_output_dir(args.output)
    plots_dir = output_dir / "plots"
    best_model_path = output_dir / "best_model.pt"
    final_model_path = output_dir / "final_model.pt"
    model_path = output_dir / "ti_pose_model.pt"
    onnx_path = output_dir / "ti_pose_model.onnx"
    metrics_path = output_dir / "metrics.json"
    report_path = output_dir / "classification_report.txt"
    confusion_path = output_dir / "confusion_matrix.csv"
    history_path = output_dir / "train_history.csv"
    predictions_path = output_dir / "sample_predictions.csv"
    per_class_path = output_dir / "per_class_metrics.csv"
    plot_manifest_path = output_dir / "plot_manifest.json"
    scaler_json_path = output_dir / "feature_scaler.json"
    scaler_npz_path = output_dir / "feature_scaler.npz"
    metadata_path = output_dir / "model_metadata.json"
    augmentation_config_path = output_dir / "augmentation_config.json"

    import numpy as np
    import torch
    import torch.nn as nn
    from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support
    from sklearn.model_selection import train_test_split
    from torch.optim import SGD
    from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler

    torch.manual_seed(args.seed)
    device = resolve_device(torch, args.device)
    pin_memory = device.type == "cuda"

    active_class_names = list(CLASS_NAMES)
    class_to_id = {class_name: index for index, class_name in enumerate(active_class_names)}
    prepared_summary = {}
    split_summary = {}
    split_mode = "window"
    balance_mode = "none"
    train_recording_count = 0
    test_recording_count = 0
    train_recording_counts_by_class = {class_name: 0 for class_name in active_class_names}
    test_recording_counts_by_class = {class_name: 0 for class_name in active_class_names}
    if args.prepared_dataset is not None:
        prepared = load_prepared_dataset(args.prepared_dataset)
        xs_array = prepared["X"]
        ys_array = prepared["y"]
        train_indices = prepared["train_indices"]
        test_indices = prepared["test_indices"]
        x_train = xs_array[train_indices]
        x_test = xs_array[test_indices]
        y_train = ys_array[train_indices].astype(int).tolist()
        y_test = ys_array[test_indices].astype(int).tolist()
        prepared_summary = prepared["summary"]
        split_summary = prepared["split_summary"]
        active_class_names = list(prepared_summary.get("class_names") or CLASS_NAMES)
        class_to_id = prepared_summary.get("class_to_id") or {
            class_name: index for index, class_name in enumerate(active_class_names)
        }
        if ys_array.size and active_class_names and (ys_array.min() < 0 or ys_array.max() >= len(active_class_names)):
            raise RuntimeError(
                f"Prepared labels contain IDs outside class_names range: "
                f"min={int(ys_array.min())} max={int(ys_array.max())} classes={len(active_class_names)}"
            )
        split_mode = split_summary.get("split_mode", prepared_summary.get("split_mode", "prepared"))
        balance_mode = prepared_summary.get("balance_mode", "none")
        train_recording_count = recording_count(prepared["metadata"], train_indices)
        test_recording_count = recording_count(prepared["metadata"], test_indices)
        train_recording_counts_by_class = recording_counts_by_class(prepared["metadata"], train_indices, active_class_names)
        test_recording_counts_by_class = recording_counts_by_class(prepared["metadata"], test_indices, active_class_names)
        dataset_stats = {
            "recordings_per_class": prepared_summary.get("recordings_per_class", {}),
            "usable_windows_per_class": prepared_summary.get("class_counts", {}),
            "class_counts": prepared_summary.get("class_counts", class_count_dict(ys_array.tolist(), active_class_names)),
            "total_windows": int(len(ys_array)),
        }
        xs = xs_array
        print(f"Loaded prepared dataset: {args.prepared_dataset}")
        print(f"  split_mode={split_mode} balance_mode={balance_mode}")
        print(f"  train_recordings={train_recording_count} test_recordings={test_recording_count}")
        print(f"  train_recordings_per_class={train_recording_counts_by_class}")
        print(f"  test_recordings_per_class={test_recording_counts_by_class}")
    else:
        xs, ys, dataset_stats = load_dataset_from_zip(args.classes_zip)
        if not xs:
            raise RuntimeError("No usable training windows were found")
        x_train, x_test, y_train, y_test = train_test_split(
            xs,
            ys,
            test_size=0.2,
            stratify=ys,
            random_state=args.seed,
        )

    train_class_counts = class_count_dict(y_train, active_class_names)
    test_class_counts = class_count_dict(y_test, active_class_names)
    print_dataset_stats(dataset_stats, y_train, y_test, active_class_names)
    if args.prepared_dataset is not None:
        print(f"  prepared_train_window_counts={train_class_counts}")
        print(f"  prepared_test_window_counts={test_class_counts}")

    x_train_array = np.asarray(x_train, dtype=np.float32)
    x_test_array = np.asarray(x_test, dtype=np.float32)
    apply_zero_snr_array(x_train_array, args.zero_snr)
    apply_zero_snr_array(x_test_array, args.zero_snr)

    scaler_mean = None
    scaler_std = None
    scaler_json_value = None
    scaler_npz_value = None
    if args.normalize:
        scaler_mean, scaler_std = compute_scaler(x_train_array, eps=1e-6)
        write_scaler_files(scaler_json_path, scaler_npz_path, scaler_mean, scaler_std)
        scaler_json_value = str(scaler_json_path)
        scaler_npz_value = str(scaler_npz_path)

    augmentation_config = build_augmentation_config(args)
    augmentation_config_path.write_text(json.dumps(augmentation_config, indent=2) + "\n", encoding="utf-8")
    model_metadata = {
        "normalization_enabled": bool(args.normalize),
        "scaler_path": scaler_json_value,
        "scaler_npz_path": scaler_npz_value,
        "input_size": INPUT_SIZE,
        "window_size": WINDOW_SIZE,
        "feature_names_22": FEATURE_NAMES_22,
        "feature_names_176": FEATURE_NAMES_176,
        "flatten_order": FLATTEN_ORDER,
        "class_names": active_class_names,
        "class_to_id": class_to_id,
        "num_classes": len(active_class_names),
        "walking_removed": "WALKING" not in active_class_names,
        "model_type": args.model_type,
        "zero_snr": bool(args.zero_snr),
        "notes": (
            "WALKING was excluded from ML training. Live walking/moving behavior should be handled with "
            "velocity/motion rules."
            if "WALKING" not in active_class_names
            else "Five-class TI Pose/Fall model metadata."
        ),
    }
    metadata_path.write_text(json.dumps(model_metadata, indent=2) + "\n", encoding="utf-8")

    x_train_tensor = torch.tensor(x_train_array, dtype=torch.float32)
    y_train_tensor = torch.tensor(y_train, dtype=torch.long)
    x_test_tensor = torch.tensor(x_test_array, dtype=torch.float32)
    y_test_tensor = torch.tensor(y_test, dtype=torch.long)
    train_data = TensorDataset(x_train_tensor, y_train_tensor)
    train_eval_data = TensorDataset(x_train_tensor, y_train_tensor)
    test_data = TensorDataset(x_test_tensor, y_test_tensor)
    mean_tensor = torch.tensor(scaler_mean, dtype=torch.float32, device=device) if scaler_mean is not None else None
    std_tensor = torch.tensor(scaler_std, dtype=torch.float32, device=device) if scaler_std is not None else None
    test_x = torch.tensor(x_test_array, dtype=torch.float32)
    if args.normalize:
        test_x = (test_x - torch.tensor(scaler_mean, dtype=torch.float32)) / torch.tensor(scaler_std, dtype=torch.float32)

    print(f"Using device: {device}")
    print(f"Train samples: {len(train_data)}")
    print(f"Test samples: {len(test_data)}")
    print(f"Batch size: {args.batch_size}")

    model = create_model(args.model_type, num_classes=len(active_class_names)).to(device)
    optimizer = SGD(model.parameters(), lr=args.learning_rate)
    class_weights = None
    class_weight_values = None
    if args.class_weighting == "balanced":
        class_weight_values = compute_balanced_class_weights(y_train, active_class_names)
        class_weights = torch.tensor(class_weight_values, dtype=torch.float32, device=device)
        print(f"Using balanced class weights: {dict(zip(active_class_names, class_weight_values))}")
    loss_fn = nn.CrossEntropyLoss(weight=class_weights)
    generator = torch.Generator()
    generator.manual_seed(args.seed)
    sampler = None
    shuffle_train = True
    if args.weighted_sampler:
        sampler_weights = class_weight_values or compute_balanced_class_weights(y_train, active_class_names)
        sample_weights = [sampler_weights[int(label)] for label in y_train]
        sampler = WeightedRandomSampler(
            weights=torch.tensor(sample_weights, dtype=torch.double),
            num_samples=len(sample_weights),
            replacement=True,
            generator=generator,
        )
        shuffle_train = False
        print("Using WeightedRandomSampler for training samples.")
    train_loader = DataLoader(
        train_data,
        batch_size=args.batch_size,
        shuffle=shuffle_train,
        sampler=sampler,
        drop_last=(len(train_data) % args.batch_size == 1),
        generator=generator if sampler is None else None,
        num_workers=args.num_workers,
        pin_memory=pin_memory,
    )
    train_eval_loader = DataLoader(
        train_eval_data,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=pin_memory,
    )
    val_loader = DataLoader(
        test_data,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=pin_memory,
    )

    history: list[dict] = []
    best_state = None
    best_epoch = 0
    best_val_macro_f1 = -1.0
    best_val_accuracy = 0.0
    best_val_loss = math.inf
    epochs_without_improvement = 0
    final_epoch = 0

    for epoch in range(1, args.epochs + 1):
        epoch_start = time.perf_counter()
        model.train()
        epoch_loss = 0.0
        seen = 0
        batches = 0
        train_start = time.perf_counter()
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device, non_blocking=pin_memory)
            batch_y = batch_y.to(device, non_blocking=pin_memory)
            if args.augment:
                batch_x = augment_feature_batch(batch_x, augmentation_config)
            batch_x = normalize_feature_batch(batch_x, mean_tensor, std_tensor)
            logits = model(batch_x)
            loss = loss_fn(logits, batch_y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            batch_count = int(batch_y.shape[0])
            epoch_loss += float(loss.item()) * batch_count
            seen += batch_count
            batches += 1

        train_seconds = time.perf_counter() - train_start
        train_loss = epoch_loss / seen if seen else math.nan
        run_train_eval = (
            args.eval_train_every > 0
            and (epoch == 1 or epoch == args.epochs or epoch % args.eval_train_every == 0)
        )
        train_eval_seconds = 0.0
        if run_train_eval:
            train_eval_start = time.perf_counter()
            train_eval = evaluate_model(
                model,
                train_eval_loader,
                loss_fn,
                torch,
                device=device,
                mean_tensor=mean_tensor,
                std_tensor=std_tensor,
                max_samples=args.train_eval_max_samples,
            )
            train_eval_seconds = time.perf_counter() - train_eval_start
        else:
            train_eval = {
                "loss": math.nan,
                "accuracy": math.nan,
                "macro_f1": math.nan,
                "weighted_f1": math.nan,
                "y_true": [],
                "y_pred": [],
                "probs": [],
            }

        run_val_eval = (
            args.eval_val_every > 0
            and (epoch == 1 or epoch == args.epochs or epoch % args.eval_val_every == 0)
        )
        val_seconds = 0.0
        if run_val_eval:
            val_start = time.perf_counter()
            val_eval = evaluate_model(
                model,
                val_loader,
                loss_fn,
                torch,
                device=device,
                mean_tensor=mean_tensor,
                std_tensor=std_tensor,
            )
            val_seconds = time.perf_counter() - val_start
        else:
            val_eval = {
                "loss": math.nan,
                "accuracy": math.nan,
                "macro_f1": math.nan,
                "weighted_f1": math.nan,
                "y_true": [],
                "y_pred": [],
                "probs": [],
            }
        learning_rate = float(optimizer.param_groups[0]["lr"])
        final_epoch = epoch
        epoch_seconds = time.perf_counter() - epoch_start
        batches_per_second = batches / train_seconds if train_seconds > 0 else 0.0
        samples_per_second = seen / train_seconds if train_seconds > 0 else 0.0

        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_eval["loss"],
            "train_accuracy": train_eval["accuracy"],
            "val_accuracy": val_eval["accuracy"],
            "val_macro_f1": val_eval["macro_f1"],
            "val_weighted_f1": val_eval["weighted_f1"],
            "learning_rate": learning_rate,
            "batches": batches,
            "epoch_seconds": epoch_seconds,
            "train_seconds": train_seconds,
            "train_eval_seconds": train_eval_seconds,
            "val_seconds": val_seconds,
            "batches_per_second": batches_per_second,
            "samples_per_second": samples_per_second,
        }
        history.append(row)

        if run_val_eval and val_eval["macro_f1"] > best_val_macro_f1:
            best_val_macro_f1 = float(val_eval["macro_f1"])
            best_val_accuracy = float(val_eval["accuracy"])
            best_val_loss = float(val_eval["loss"])
            best_epoch = epoch
            best_state = move_state_dict_to_cpu(model.state_dict())
            epochs_without_improvement = 0
        elif run_val_eval:
            epochs_without_improvement += 1

        if args.profile or should_print_epoch(epoch, args.epochs):
            message = (
                f"Epoch {epoch}/{args.epochs} | "
                f"train_loss={train_loss:.4f} | "
                f"val_loss={format_float(val_eval['loss'])} | "
                f"train_acc={format_percent(train_eval['accuracy'])} | "
                f"val_acc={format_percent(val_eval['accuracy'])} | "
                f"val_macro_f1={format_float(val_eval['macro_f1'])} | "
                f"best_epoch={best_epoch}"
            )
            if args.profile:
                message += (
                    f" | epoch_time={epoch_seconds:.2f}s"
                    f" | train={train_seconds:.2f}s"
                    f" | val={val_seconds:.2f}s"
                    f" | batches/s={batches_per_second:.1f}"
                    f" | samples/s={samples_per_second:.0f}"
                )
            print(
                message,
                flush=True,
            )

        if run_val_eval and args.patience > 0 and epochs_without_improvement >= args.patience:
            print(
                f"Early stopping at epoch {epoch}: val_macro_f1 did not improve "
                f"for {args.patience} epochs."
            )
            break

    if best_state is None:
        best_state = move_state_dict_to_cpu(model.state_dict())
        best_epoch = final_epoch

    final_state = move_state_dict_to_cpu(model.state_dict())
    final_row = history[-1]
    common_checkpoint_metadata = {
        "model_type": args.model_type,
        "class_names": active_class_names,
        "class_to_id": class_to_id,
        "num_classes": len(active_class_names),
        "walking_removed": "WALKING" not in active_class_names,
        "normalization_enabled": bool(args.normalize),
        "scaler_path": scaler_json_value,
        "scaler_npz_path": scaler_npz_value,
        "scaler_mean": [float(value) for value in scaler_mean.tolist()] if scaler_mean is not None else None,
        "scaler_std": [float(value) for value in scaler_std.tolist()] if scaler_std is not None else None,
        "augment": bool(args.augment),
        "zero_snr": bool(args.zero_snr),
        "augmentation_config": augmentation_config,
        "feature_names_176": FEATURE_NAMES_176,
        "prepared_dataset": str(args.prepared_dataset) if args.prepared_dataset else None,
        "split_mode": split_mode,
        "balance_mode": balance_mode,
        "class_weighting": args.class_weighting,
        "class_weights": class_weight_values,
        "weighted_sampler": bool(args.weighted_sampler),
        "device": str(device),
        "profile": bool(args.profile),
        "eval_train_every": int(args.eval_train_every),
        "eval_val_every": int(args.eval_val_every),
        "train_eval_max_samples": int(args.train_eval_max_samples),
        "num_workers": int(args.num_workers),
        "pin_memory": bool(pin_memory),
    }
    final_metadata = {
        **common_checkpoint_metadata,
        "checkpoint_type": "final",
        "epoch": final_epoch,
        "val_macro_f1": final_row["val_macro_f1"],
        "val_accuracy": final_row["val_accuracy"],
        "val_loss": final_row["val_loss"],
        "notes": (
            "Model forward returns raw logits. Apply softmax only for reporting/inference. "
            "WALKING was excluded from ML training; live walking/moving behavior should be handled with velocity/motion rules."
            if "WALKING" not in active_class_names
            else "Model forward returns raw logits. Apply softmax only for reporting/inference."
        ),
    }
    save_checkpoint(final_model_path, final_state, final_metadata, active_class_names)

    best_metadata = {
        **common_checkpoint_metadata,
        "checkpoint_type": "best",
        "best_epoch": best_epoch,
        "best_val_macro_f1": best_val_macro_f1,
        "best_val_accuracy": best_val_accuracy,
        "best_val_loss": best_val_loss,
        "notes": (
            "Best checkpoint selected by validation macro F1. Model forward returns raw logits. "
            "WALKING was excluded from ML training; live walking/moving behavior should be handled with velocity/motion rules."
            if "WALKING" not in active_class_names
            else "Best checkpoint selected by validation macro F1. Model forward returns raw logits."
        ),
    }
    save_checkpoint(best_model_path, best_state, best_metadata, active_class_names)
    save_checkpoint(model_path, best_state, best_metadata, active_class_names)

    model.load_state_dict(best_state)
    final_train_eval = evaluate_model(
        model,
        train_eval_loader,
        loss_fn,
        torch,
        device=device,
        mean_tensor=mean_tensor,
        std_tensor=std_tensor,
    )
    best_eval = evaluate_model(
        model,
        val_loader,
        loss_fn,
        torch,
        device=device,
        mean_tensor=mean_tensor,
        std_tensor=std_tensor,
    )
    y_true = best_eval["y_true"]
    y_pred = best_eval["y_pred"]
    prob_rows = best_eval["probs"]
    class_ids = list(range(len(active_class_names)))
    matrix = confusion_matrix(y_true, y_pred, labels=class_ids)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=class_ids,
        zero_division=0,
    )

    model.eval()
    with torch.inference_mode():
        torch.onnx.export(
            model,
            torch.randn(1, INPUT_SIZE, device=device),
            onnx_path,
            opset_version=11,
            input_names=["input_1"],
            output_names=["output"],
        )

    write_history_csv(history_path, history)
    write_confusion_csv(confusion_path, matrix, active_class_names)
    write_per_class_metrics_csv(per_class_path, precision, recall, f1, support, active_class_names)
    write_sample_predictions(predictions_path, y_true, y_pred, prob_rows, active_class_names)
    report_path.write_text(
        classification_report(
            y_true,
            y_pred,
            labels=class_ids,
            target_names=active_class_names,
            zero_division=0,
        ),
        encoding="utf-8",
    )
    plot_manifest = save_plots(
        plots_dir=plots_dir,
        history=history,
        matrix=matrix,
        precision=precision,
        recall=recall,
        f1=f1,
        support=support,
        y_true=y_true,
        y_pred=y_pred,
        probs=prob_rows,
        class_counts=dataset_stats["class_counts"],
        train_counts=train_class_counts,
        test_counts=test_class_counts,
        class_names=active_class_names,
    )
    plot_manifest_path.write_text(json.dumps(plot_manifest, indent=2) + "\n", encoding="utf-8")

    final_val_macro_f1 = float(final_row["val_macro_f1"])
    final_val_accuracy = float(final_row["val_accuracy"])
    metrics = {
        "model_type": args.model_type,
        "normalize": bool(args.normalize),
        "augment": bool(args.augment),
        "zero_snr": bool(args.zero_snr),
        "snr_dropout": float(args.snr_dropout),
        "point_dropout": float(args.point_dropout),
        "augmentation_config": augmentation_config,
        "prepared_dataset": str(args.prepared_dataset) if args.prepared_dataset else None,
        "split_mode": split_mode,
        "balance_mode": balance_mode,
        "class_weighting": args.class_weighting,
        "class_weights": class_weight_values,
        "weighted_sampler": bool(args.weighted_sampler),
        "accuracy_percent": best_val_accuracy,
        "macro_f1": best_val_macro_f1,
        "weighted_f1": float(best_eval["weighted_f1"]),
        "best_epoch": best_epoch,
        "best_val_macro_f1": best_val_macro_f1,
        "best_val_accuracy": best_val_accuracy,
        "best_val_loss": best_val_loss,
        "final_full_train_loss": float(final_train_eval["loss"]),
        "final_full_train_accuracy": float(final_train_eval["accuracy"]),
        "final_full_train_macro_f1": float(final_train_eval["macro_f1"]),
        "final_full_train_weighted_f1": float(final_train_eval["weighted_f1"]),
        "final_epoch": final_epoch,
        "final_val_macro_f1": final_val_macro_f1,
        "final_val_accuracy": final_val_accuracy,
        "num_samples": len(xs),
        "num_train": len(x_train),
        "num_test": len(x_test),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "profile": bool(args.profile),
        "device": str(device),
        "eval_train_every": int(args.eval_train_every),
        "eval_val_every": int(args.eval_val_every),
        "train_eval_max_samples": int(args.train_eval_max_samples),
        "num_workers": int(args.num_workers),
        "pin_memory": bool(pin_memory),
        "classes_zip": str(args.classes_zip) if args.classes_zip else None,
        "class_names": active_class_names,
        "class_to_id": class_to_id,
        "num_classes": len(active_class_names),
        "walking_removed": "WALKING" not in active_class_names,
        "class_counts": dataset_stats["class_counts"],
        "train_class_counts": train_class_counts,
        "test_class_counts": test_class_counts,
        "feature_names_22": FEATURE_NAMES_22,
        "feature_names_176": FEATURE_NAMES_176,
        "flatten_order": FLATTEN_ORDER,
        "window_size": WINDOW_SIZE,
        "input_size": INPUT_SIZE,
        "output_dir": str(output_dir),
        "plots_dir": str(plots_dir),
        "train_recording_count": train_recording_count,
        "test_recording_count": test_recording_count,
        "num_train_recordings": train_recording_count,
        "num_test_recordings": test_recording_count,
        "train_recording_counts_by_class": train_recording_counts_by_class,
        "test_recording_counts_by_class": test_recording_counts_by_class,
        "prepared_dataset_summary": prepared_summary,
        "split_summary": split_summary,
        "feature_scaler_json": scaler_json_value,
        "feature_scaler_npz": scaler_npz_value,
        "model_metadata": str(metadata_path),
        "augmentation_config_path": str(augmentation_config_path),
        "notes": (
            "WALKING was excluded from ML training. Live walking/moving behavior should "
            "be handled with velocity/motion rules. "
            if "WALKING" not in active_class_names
            else ""
        )
        + (
            "This model was trained using TI data only with synthetic sensor-domain "
            "augmentation to improve robustness for IWR6843ISK-ODS. It still must be "
            "validated on live IWR6843 data. Best model and ONNX are selected by "
            "validation macro F1. Random window split can be optimistic because nearby "
            "windows from the same recording can be similar."
        ),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    check_onnx_runtime(onnx_path, test_x[:1], int(y_pred[0]))
    print(
        f"Training complete. best_epoch={best_epoch} "
        f"best_val_macro_f1={best_val_macro_f1:.4f} "
        f"best_val_accuracy={best_val_accuracy:.2f}%"
    )
    print("Output files:")
    for path in [
        best_model_path,
        final_model_path,
        model_path,
        onnx_path,
        metrics_path,
        report_path,
        confusion_path,
        history_path,
        predictions_path,
        per_class_path,
        metadata_path,
        augmentation_config_path,
        *([scaler_json_path, scaler_npz_path] if args.normalize else []),
        plot_manifest_path,
        *[plots_dir / item["file"] for item in plot_manifest],
    ]:
        print(f"  {path}")


if __name__ == "__main__":
    main()
