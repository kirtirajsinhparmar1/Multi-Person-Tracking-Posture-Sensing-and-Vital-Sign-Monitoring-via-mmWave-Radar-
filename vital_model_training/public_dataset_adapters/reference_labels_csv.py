from __future__ import annotations

import csv
from pathlib import Path


REQUIRED_COLUMNS = {
    "recording_id",
    "start_time_sec",
    "end_time_sec",
    "reference_heart_bpm",
    "reference_breath_bpm",
}


def read_reference_labels(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Reference label CSV missing columns: {sorted(missing)}")
        return list(reader)
