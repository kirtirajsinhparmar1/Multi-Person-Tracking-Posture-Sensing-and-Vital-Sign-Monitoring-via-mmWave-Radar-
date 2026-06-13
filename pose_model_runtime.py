"""ONNX runtime wrapper for TI Pose/Fall style 176-float inputs."""

from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
from typing import Deque, Mapping

import numpy as np


CLASS_NAMES = ["STANDING", "SITTING", "LYING", "FALLING", "WALKING"]
DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent
    / "model_experiments"
    / "outputs"
    / "ti_4class_clean_recording_robust_1600_fast"
    / "ti_pose_model.onnx"
)


def prewarm_onnxruntime(debug: bool = False):
    """Import ONNX Runtime before Qt/PySide can affect Windows DLL load order."""

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ImportError(
            "ONNX Runtime failed to import inside the TI-style UI process. "
            "Standalone import may work, but Qt/PySide DLL load order can break it. "
            "This launcher now preloads ONNX Runtime before Qt; if it still fails, "
            "reinstall onnxruntime or use a torch fallback. "
            f"Original exception: {exc}"
        ) from exc

    if debug:
        print("[pose-runtime] preloading ONNX Runtime before Qt", flush=True)
        print(
            f"[pose-runtime] onnxruntime {ort.__version__} "
            f"providers={ort.get_available_providers()}",
            flush=True,
        )
    return ort


class PoseModelRuntime:
    """Run one 176-float Pose/Fall feature vector through an ONNX model."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        allow_missing_scaler: bool = False,
        debug: bool = False,
    ):
        ort = prewarm_onnxruntime(False)

        self.debug = bool(debug)
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.exists():
            raise FileNotFoundError(f"Pose ONNX model not found: {self.model_path}")

        self.model_dir = self.model_path.parent
        self.metadata_path = self.model_dir / "model_metadata.json"
        self.metadata = self._load_metadata()
        self.class_names = _class_names_from_metadata(self.metadata)
        self.normalization_enabled = bool(
            self.metadata.get("normalization_enabled", self.metadata.get("normalize", False))
        )
        self.scaler_mean: np.ndarray | None = None
        self.scaler_std: np.ndarray | None = None
        self.scaler_path: Path | None = None
        self._load_scaler(allow_missing_scaler)

        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.output_classes = _output_class_count(self.session.get_outputs()[0].shape)

        if self.output_classes is not None and self.output_classes != len(self.class_names):
            raise ValueError(
                f"ONNX output has {self.output_classes} classes, "
                f"but metadata has {len(self.class_names)} class names: {self.class_names}"
            )
        if self.debug:
            print(f"[pose-runtime] class_names={self.class_names}", flush=True)
            print(
                f"[pose-runtime] normalization enabled: {str(self.normalization_enabled).lower()}",
                flush=True,
            )
            scaler_name = self.scaler_path.name if self.scaler_path is not None else "none"
            print(f"[pose-runtime] scaler loaded: {scaler_name}", flush=True)
            print(
                f"[pose-runtime] ONNX output classes: {self.output_classes or 'validated on inference'}",
                flush=True,
            )

    def predict(self, feature176) -> dict:
        vector = np.asarray(feature176, dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != 176:
            raise ValueError(f"Pose model expects 176 floats, got {vector.shape[1]}")
        vector = self._normalize(vector)

        output = self.session.run([self.output_name], {self.input_name: vector})[0]
        scores = np.asarray(output, dtype=np.float32).reshape(-1)
        if scores.size != len(self.class_names):
            raise ValueError(
                f"Pose model output must have {len(self.class_names)} classes, got {scores.size}"
            )

        probabilities = _as_probabilities(scores)
        predicted_id = int(np.argmax(probabilities))
        confidence = float(probabilities[predicted_id])
        return {
            "predicted_id": predicted_id,
            "predicted_label": self.class_names[predicted_id],
            "confidence": confidence,
            "probabilities": {
                name: float(probabilities[index])
                for index, name in enumerate(self.class_names)
            },
        }

    def _load_metadata(self) -> dict:
        if not self.metadata_path.exists():
            print(
                "[pose-runtime] warning: model_metadata.json not found; "
                "using fallback 5-class labels and no required scaler.",
                flush=True,
            )
            return {}
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to read pose model metadata: {self.metadata_path}") from exc

    def _load_scaler(self, allow_missing_scaler: bool) -> None:
        if not self.normalization_enabled:
            return

        candidates = _scaler_candidates(self.model_dir, self.metadata)
        for candidate in candidates:
            if not candidate.exists():
                continue
            mean, std = _load_scaler_file(candidate)
            self.scaler_mean = mean.reshape(1, -1)
            self.scaler_std = np.maximum(std.reshape(1, -1), 1e-6)
            self.scaler_path = candidate
            return

        message = (
            "Pose model metadata requires feature normalization, but no valid "
            f"feature_scaler.npz/json was found next to {self.model_path}."
        )
        if allow_missing_scaler:
            print(f"[pose-runtime] warning: {message}", flush=True)
            return
        raise RuntimeError(message + " Pass --allow-missing-scaler only for debugging.")

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        if not self.normalization_enabled:
            return vector
        if self.scaler_mean is None or self.scaler_std is None:
            raise RuntimeError("Pose normalization is enabled but scaler is not loaded.")
        return ((vector - self.scaler_mean) / self.scaler_std).astype(np.float32)


class PoseSmoother:
    """Average recent probability vectors independently per TID."""

    def __init__(self, window_size: int = 5, class_names: list[str] | None = None):
        self.window_size = max(1, int(window_size))
        self.class_names = list(class_names or CLASS_NAMES)
        self._windows: dict[int, Deque[np.ndarray]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )

    def update(self, tid: int, probabilities: Mapping[str, float] | list[float]) -> dict:
        tid_int = int(tid)
        vector = _probability_vector(probabilities, self.class_names)
        self._windows[tid_int].append(vector)
        smoothed = np.mean(np.stack(list(self._windows[tid_int]), axis=0), axis=0)
        smoothed = _as_probabilities(smoothed)
        predicted_id = int(np.argmax(smoothed))
        return {
            "smoothed_label": self.class_names[predicted_id],
            "smoothed_confidence": float(smoothed[predicted_id]),
            "smoothed_probabilities": {
                name: float(smoothed[index])
                for index, name in enumerate(self.class_names)
            },
        }

    def reset_tid(self, tid: int) -> None:
        self._windows.pop(int(tid), None)

    def reset_all(self) -> None:
        self._windows.clear()


def _class_names_from_metadata(metadata: dict) -> list[str]:
    names = metadata.get("class_names")
    if isinstance(names, list) and names and all(isinstance(name, str) for name in names):
        return [str(name) for name in names]
    print(
        "[pose-runtime] warning: class_names missing from metadata; using fallback labels.",
        flush=True,
    )
    return list(CLASS_NAMES)


def _output_class_count(shape) -> int | None:
    try:
        last = shape[-1]
    except Exception:
        return None
    return int(last) if isinstance(last, int) and last > 0 else None


def _scaler_candidates(model_dir: Path, metadata: dict) -> list[Path]:
    candidates: list[Path] = [model_dir / "feature_scaler.npz", model_dir / "feature_scaler.json"]
    for key in ("scaler_path", "scaler_npz_path", "scaler_json_path"):
        value = metadata.get(key)
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append((model_dir / path.name).resolve())
            candidates.append((Path.cwd() / path).resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if str(resolved) not in seen:
            unique.append(resolved)
            seen.add(str(resolved))
    return unique


def _load_scaler_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if path.suffix.lower() == ".npz":
        with np.load(path) as data:
            mean = _first_array(data, ("mean", "train_mean", "scaler_mean"))
            std = _first_array(data, ("std", "train_std", "scaler_std"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mean = _first_json_array(payload, ("mean", "train_mean", "scaler_mean"))
        std = _first_json_array(payload, ("std", "train_std", "scaler_std"))
    mean = np.asarray(mean, dtype=np.float32).reshape(-1)
    std = np.asarray(std, dtype=np.float32).reshape(-1)
    if mean.size != 176 or std.size != 176:
        raise ValueError(f"Scaler {path} must contain 176 mean/std values.")
    return mean, std


def _first_array(data, keys: tuple[str, ...]) -> np.ndarray:
    for key in keys:
        if key in data:
            return np.asarray(data[key], dtype=np.float32)
    raise KeyError(f"Scaler npz missing one of: {', '.join(keys)}")


def _first_json_array(payload: dict, keys: tuple[str, ...]) -> list[float]:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    raise KeyError(f"Scaler json missing one of: {', '.join(keys)}")


def _probability_vector(
    probabilities: Mapping[str, float] | list[float],
    class_names: list[str] | None = None,
) -> np.ndarray:
    names = list(class_names or CLASS_NAMES)
    if isinstance(probabilities, Mapping):
        values = [float(probabilities.get(name, 0.0)) for name in names]
    else:
        values = [float(value) for value in probabilities]
    if len(values) != len(names):
        raise ValueError(f"Expected {len(names)} probabilities, got {len(values)}")
    return _as_probabilities(np.asarray(values, dtype=np.float32))


def _as_probabilities(scores: np.ndarray) -> np.ndarray:
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    total = float(np.sum(scores))
    if np.all(scores >= 0.0) and 0.99 <= total <= 1.01:
        probabilities = scores / max(total, 1e-12)
    else:
        shifted = scores - np.max(scores)
        exp_scores = np.exp(shifted)
        probabilities = exp_scores / max(float(np.sum(exp_scores)), 1e-12)
    return probabilities.astype(np.float32)
