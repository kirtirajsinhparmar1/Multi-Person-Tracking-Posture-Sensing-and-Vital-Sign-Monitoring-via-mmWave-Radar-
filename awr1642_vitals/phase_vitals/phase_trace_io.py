from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np

try:
    from .phase_vitals_estimator import iq_to_phase
    from .phase_vitals_types import PhaseTraceSample, PhaseTraceWindow
except ImportError:  # pragma: no cover - supports direct script imports
    from phase_vitals_estimator import iq_to_phase
    from phase_vitals_types import PhaseTraceSample, PhaseTraceWindow


PHASE_ALIASES = ("phase", "phase_rad", "unwrapped_phase", "unwrappedphase", "phaserad")
I_ALIASES = ("i", "I", "real", "ivalue", "i_value")
Q_ALIASES = ("q", "Q", "imag", "imaginary", "qvalue", "q_value")
TIME_ALIASES = ("time", "time_s", "timestamp", "t")
FRAME_ALIASES = ("frame", "frame_num", "framenum", "frameNumber")


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in name.strip().lower() if ch.isalnum() or ch == "_")


def _column_lookup(fieldnames: Iterable[str]) -> Dict[str, str]:
    return {_normalize_name(name): name for name in fieldnames}


def _find_column(lookup: Dict[str, str], aliases: Iterable[str]) -> Optional[str]:
    for alias in aliases:
        key = _normalize_name(alias)
        if key in lookup:
            return lookup[key]
    return None


def _float_or_none(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        value = float(value)
        return value if np.isfinite(value) else None
    except Exception:
        return None


def _int_or_none(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _read_csv_rows(path: Path):
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"No CSV header found in {path}")
        rows = list(reader)
        return reader.fieldnames, rows


def _infer_fs(times) -> Optional[float]:
    times = np.asarray([t for t in times if t is not None], dtype=float)
    if times.size < 2:
        return None
    diffs = np.diff(times)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(1.0 / np.median(diffs))


def load_phase_csv(path) -> PhaseTraceWindow:
    path = Path(path)
    fieldnames, rows = _read_csv_rows(path)
    lookup = _column_lookup(fieldnames)
    phase_col = _find_column(lookup, PHASE_ALIASES)
    if phase_col is None:
        raise ValueError(f"No phase column found in {path}")
    time_col = _find_column(lookup, TIME_ALIASES)
    frame_col = _find_column(lookup, FRAME_ALIASES)

    samples = []
    times = []
    for idx, row in enumerate(rows):
        time_s = _float_or_none(row.get(time_col)) if time_col else None
        frame = _int_or_none(row.get(frame_col)) if frame_col else idx
        phase = _float_or_none(row.get(phase_col))
        if phase is None:
            continue
        times.append(time_s)
        samples.append(PhaseTraceSample(frame=frame, time_s=time_s, phase_rad=phase))
    return PhaseTraceWindow(samples=samples, fs_hz=_infer_fs(times), source_path=str(path))


def load_iq_csv(path) -> PhaseTraceWindow:
    path = Path(path)
    fieldnames, rows = _read_csv_rows(path)
    lookup = _column_lookup(fieldnames)
    i_col = _find_column(lookup, I_ALIASES)
    q_col = _find_column(lookup, Q_ALIASES)
    if i_col is None or q_col is None:
        raise ValueError(f"No I/Q columns found in {path}")
    time_col = _find_column(lookup, TIME_ALIASES)
    frame_col = _find_column(lookup, FRAME_ALIASES)

    samples = []
    times = []
    for idx, row in enumerate(rows):
        time_s = _float_or_none(row.get(time_col)) if time_col else None
        frame = _int_or_none(row.get(frame_col)) if frame_col else idx
        i_value = _float_or_none(row.get(i_col))
        q_value = _float_or_none(row.get(q_col))
        if i_value is None or q_value is None:
            continue
        phase = float(iq_to_phase([i_value], [q_value])[0])
        times.append(time_s)
        samples.append(PhaseTraceSample(frame=frame, time_s=time_s, phase_rad=phase, i_value=i_value, q_value=q_value))
    return PhaseTraceWindow(samples=samples, fs_hz=_infer_fs(times), source_path=str(path))


def save_estimates_json(path, estimates) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_dataclass(estimates):
        payload = asdict(estimates)
    elif hasattr(estimates, "to_dict"):
        payload = estimates.to_dict()
    else:
        payload = dict(estimates)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
