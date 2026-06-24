from __future__ import annotations

import csv
from pathlib import Path


def read_phase_or_displacement_csv(
    path,
    time_column="elapsedSec",
    phase_column="phaseRad",
    displacement_column="displacementMm",
):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "time_sec": float(row[time_column]),
            "phase_rad": (
                float(row[phase_column]) if row.get(phase_column) else None
            ),
            "displacement_mm": (
                float(row[displacement_column])
                if row.get(displacement_column)
                else None
            ),
        }
        for row in rows
    ]
