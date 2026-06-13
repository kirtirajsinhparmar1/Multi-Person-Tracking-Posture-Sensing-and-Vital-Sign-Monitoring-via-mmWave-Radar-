from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .twente_types import VitalReference
except ImportError:
    from twente_types import VitalReference


TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".cfg", ".json", ".yaml", ".yml"}
SIGNAL_EXTENSIONS = {".csv", ".txt", ".npy", ".npz", ".json", ".mat"}
RAW_ADC_EXTENSIONS = {".bin", ".dat", ".adc"}


def find_candidate_files(root: str | Path) -> dict[str, list[str]]:
    root_path = Path(root)
    categories = {
        "all": [],
        "readme_metadata": [],
        "processed_displacement": [],
        "range_maps": [],
        "raw_adc": [],
        "reference_labels": [],
        "cfg_capture_metadata": [],
    }
    if not root_path.exists():
        categories["missing_root"] = [str(root_path)]
        return categories

    for path in sorted(p for p in root_path.rglob("*") if p.is_file()):
        rel = str(path.relative_to(root_path))
        lower = rel.lower()
        suffix = path.suffix.lower()
        categories["all"].append(rel)

        if "readme" in lower or "metadata" in lower or suffix in {".md", ".pdf"}:
            categories["readme_metadata"].append(rel)

        if suffix in SIGNAL_EXTENSIONS and any(
            token in lower
            for token in (
                "displacement",
                "chest",
                "phase",
                "unwrap",
                "vital_signal",
                "vitalsignal",
            )
        ):
            categories["processed_displacement"].append(rel)

        if suffix in SIGNAL_EXTENSIONS and any(
            token in lower for token in ("range_map", "rangemap", "range-map", "rangeprofile", "range_profile")
        ):
            categories["range_maps"].append(rel)

        if suffix in RAW_ADC_EXTENSIONS or ("adc" in lower and suffix in {".bin", ".dat"}):
            categories["raw_adc"].append(rel)

        if any(
            token in lower
            for token in (
                "reference",
                "groundtruth",
                "ground_truth",
                "polar",
                "heart",
                "resp",
                "breath",
                "label",
            )
        ):
            categories["reference_labels"].append(rel)

        if suffix in {".cfg", ".json", ".lua", ".mmwave.json"} or any(
            token in lower for token in ("capture", "config", "profile", "dca1000")
        ):
            categories["cfg_capture_metadata"].append(rel)

    return categories


def load_metadata(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    candidates = find_candidate_files(root_path)
    metadata: dict[str, Any] = {
        "root": str(root_path),
        "root_exists": root_path.exists(),
        "candidate_files": candidates,
        "sample_rate_hz": None,
        "metadata_files": [],
        "notes": [],
    }
    if not root_path.exists():
        metadata["notes"].append("Sample root does not exist.")
        return metadata

    for rel in candidates.get("readme_metadata", []) + candidates.get("cfg_capture_metadata", []):
        path = root_path / rel
        entry: dict[str, Any] = {"path": rel, "type": path.suffix.lower()}
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                entry["keys"] = list(payload.keys())[:50] if isinstance(payload, dict) else []
                sample_rate = _find_sample_rate(payload)
                if sample_rate and metadata["sample_rate_hz"] is None:
                    metadata["sample_rate_hz"] = sample_rate
            except Exception as exc:
                entry["error"] = str(exc)
        elif path.suffix.lower() in TEXT_EXTENSIONS:
            text = _read_small_text(path)
            entry["preview"] = text[:1000]
            sample_rate = _find_sample_rate(text)
            if sample_rate and metadata["sample_rate_hz"] is None:
                metadata["sample_rate_hz"] = sample_rate
        metadata["metadata_files"].append(entry)

    return metadata


def load_processed_displacement(path: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    signal_path = Path(path)
    if not signal_path.exists():
        raise FileNotFoundError(signal_path)

    suffix = signal_path.suffix.lower()
    meta: dict[str, Any] = {"path": str(signal_path), "format": suffix, "selected_key": None}

    if suffix == ".npy":
        data = np.load(signal_path, allow_pickle=False)
        signal = _select_1d_signal(data)
    elif suffix == ".npz":
        archive = np.load(signal_path, allow_pickle=False)
        key, signal = _select_array_from_mapping({k: archive[k] for k in archive.files})
        meta["selected_key"] = key
    elif suffix == ".json":
        payload = json.loads(signal_path.read_text(encoding="utf-8", errors="replace"))
        key, signal = _select_array_from_mapping(_flatten_json_arrays(payload))
        meta["selected_key"] = key
    elif suffix == ".mat":
        try:
            from scipy.io import loadmat
        except Exception as exc:
            raise RuntimeError("Loading .mat files requires scipy.") from exc
        payload = {k: v for k, v in loadmat(signal_path).items() if not k.startswith("__")}
        key, signal = _select_array_from_mapping(payload)
        meta["selected_key"] = key
    elif suffix in {".csv", ".txt"}:
        signal, selected_column = _load_signal_from_text_table(signal_path)
        meta["selected_column"] = selected_column
    else:
        raise ValueError(f"Unsupported processed displacement format: {suffix}")

    signal = np.asarray(signal, dtype=np.float64).reshape(-1)
    finite = np.isfinite(signal)
    if not finite.any():
        raise ValueError(f"No finite samples found in {signal_path}")
    if not finite.all():
        signal = _fill_nonfinite(signal)
        meta["filled_nonfinite"] = True
    meta["num_samples"] = int(signal.size)
    return signal, meta


def load_reference_labels(path: str | Path) -> VitalReference:
    ref_path = Path(path)
    if not ref_path.exists():
        raise FileNotFoundError(ref_path)

    suffix = ref_path.suffix.lower()
    metadata: dict[str, Any] = {"format": suffix}
    values: dict[str, float | None] = {"breathing_bpm": None, "heart_bpm": None}

    if suffix == ".json":
        payload = json.loads(ref_path.read_text(encoding="utf-8", errors="replace"))
        values.update(_extract_reference_values_from_mapping(_flatten_scalars(payload)))
    elif suffix in {".csv", ".txt"}:
        values.update(_extract_reference_values_from_text_or_csv(ref_path, metadata))
    else:
        text = _read_small_text(ref_path)
        values.update(_extract_reference_values_from_text(text))
        metadata["note"] = "Parsed as generic text."

    return VitalReference(
        source_path=str(ref_path),
        breathing_bpm=values.get("breathing_bpm"),
        heart_bpm=values.get("heart_bpm"),
        metadata=metadata,
    )


def _read_small_text(path: Path, max_bytes: int = 65536) -> str:
    with path.open("rb") as f:
        data = f.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def _find_sample_rate(obj: Any) -> float | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = str(key).lower()
            if any(token in lower for token in ("sample_rate", "sampling_rate", "fs", "frame_rate", "fps")):
                try:
                    numeric = float(value)
                    if 0 < numeric < 10000:
                        return numeric
                except Exception:
                    pass
            found = _find_sample_rate(value)
            if found:
                return found
    elif isinstance(obj, str):
        patterns = [
            r"(?:sample[_ ]?rate|sampling[_ ]?rate|fs|frame[_ ]?rate|fps)\D{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"([0-9]+(?:\.[0-9]+)?)\s*(?:hz|fps)",
        ]
        for pattern in patterns:
            match = re.search(pattern, obj, flags=re.IGNORECASE)
            if match:
                value = float(match.group(1))
                if 0 < value < 10000:
                    return value
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = _find_sample_rate(item)
            if found:
                return found
    return None


def _select_array_from_mapping(mapping: dict[str, Any]) -> tuple[str, np.ndarray]:
    preferred = ("displacement", "chest", "phase", "unwrap", "vital")
    arrays: list[tuple[str, np.ndarray]] = []
    for key, value in mapping.items():
        try:
            arr = np.asarray(value, dtype=np.float64)
        except Exception:
            continue
        if arr.size >= 8 and np.isfinite(arr).any():
            arrays.append((key, arr))
    if not arrays:
        raise ValueError("No numeric array candidates found.")

    for token in preferred:
        for key, arr in arrays:
            if token in key.lower():
                return key, _select_1d_signal(arr)
    key, arr = max(arrays, key=lambda item: np.asarray(item[1]).size)
    return key, _select_1d_signal(arr)


def _select_1d_signal(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 1:
        return arr
    arr = np.squeeze(arr)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        finite_counts = np.sum(np.isfinite(arr), axis=0)
        variances = np.nanvar(arr, axis=0)
        score = finite_counts + variances
        col = int(np.nanargmax(score))
        return arr[:, col]
    raise ValueError(f"Cannot select 1D signal from array with shape {arr.shape}")


def _load_signal_from_text_table(path: Path) -> tuple[np.ndarray, str | None]:
    delimiters = [",", "\t", None]
    name_tokens = ("displacement", "chest", "phase", "unwrap", "vital")

    for delimiter in delimiters:
        try:
            table = np.genfromtxt(path, delimiter=delimiter, names=True, dtype=float, encoding=None)
            if table.dtype.names:
                names = list(table.dtype.names)
                for token in name_tokens:
                    for name in names:
                        if token in name.lower():
                            return np.asarray(table[name], dtype=np.float64), name
                best_name = max(names, key=lambda n: np.isfinite(np.asarray(table[n], dtype=float)).sum())
                return np.asarray(table[best_name], dtype=np.float64), best_name
        except Exception:
            pass

    for delimiter in delimiters:
        try:
            arr = np.genfromtxt(path, delimiter=delimiter, dtype=float)
            arr = np.asarray(arr, dtype=np.float64)
            return _select_1d_signal(arr), None
        except Exception:
            pass
    raise ValueError(f"Could not load numeric signal from {path}")


def _fill_nonfinite(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64).copy()
    idx = np.arange(arr.size)
    finite = np.isfinite(arr)
    if finite.sum() == 0:
        return np.zeros_like(arr)
    arr[~finite] = np.interp(idx[~finite], idx[finite], arr[finite])
    return arr


def _flatten_json_arrays(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_json_arrays(value, child))
    elif isinstance(obj, list):
        if obj and all(isinstance(v, (int, float)) or v is None for v in obj):
            out[prefix or "array"] = obj
        else:
            for idx, value in enumerate(obj):
                out.update(_flatten_json_arrays(value, f"{prefix}[{idx}]"))
    return out


def _flatten_scalars(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_scalars(value, child))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj[:20]):
            out.update(_flatten_scalars(value, f"{prefix}[{idx}]"))
    else:
        out[prefix] = obj
    return out


def _extract_reference_values_from_mapping(mapping: dict[str, Any]) -> dict[str, float | None]:
    values: dict[str, float | None] = {"breathing_bpm": None, "heart_bpm": None}
    for key, value in mapping.items():
        lower = key.lower()
        numeric = _coerce_float(value)
        if numeric is None:
            continue
        if values["heart_bpm"] is None and any(token in lower for token in ("heart", "hr", "cardiac")):
            values["heart_bpm"] = _normalize_bpm(numeric)
        if values["breathing_bpm"] is None and any(
            token in lower for token in ("breath", "resp", "respiratory", "rr")
        ):
            values["breathing_bpm"] = _normalize_bpm(numeric)
    return values


def _extract_reference_values_from_text_or_csv(path: Path, metadata: dict[str, Any]) -> dict[str, float | None]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample)
            reader = csv.DictReader(f, dialect=dialect)
            rows = list(reader)
        metadata["rows"] = len(rows)
        column_values: dict[str, list[float]] = {}
        for row in rows:
            for key, value in row.items():
                numeric = _coerce_float(value)
                if numeric is not None:
                    column_values.setdefault(key, []).append(numeric)
        summary = {
            key: float(np.nanmedian(vals)) for key, vals in column_values.items() if vals
        }
        return _extract_reference_values_from_mapping(summary)
    except Exception:
        return _extract_reference_values_from_text(_read_small_text(path))


def _extract_reference_values_from_text(text: str) -> dict[str, float | None]:
    values: dict[str, float | None] = {"breathing_bpm": None, "heart_bpm": None}
    patterns = {
        "heart_bpm": r"(?:heart|hr|cardiac)[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)",
        "breathing_bpm": r"(?:breath|resp|respiratory|rr)[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            values[key] = _normalize_bpm(float(match.group(1)))
    return values


def _coerce_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except Exception:
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _normalize_bpm(value: float) -> float:
    if 0.05 <= value <= 4.0:
        return value * 60.0
    return value
