"""CSV/JSON writer for labeled IWR6843 Pose/Fall capture trials."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from frame_types import ParsedFrame, Point, Target, TargetHeight
from pose_feature_extractor import FEATURE_NAMES_22, WINDOW_SIZE


FEATURE_176_COLUMNS = [
    f"{name}_f{frame_index}"
    for name in FEATURE_NAMES_22
    for frame_index in range(WINDOW_SIZE)
]


class PoseDataLogger:
    def __init__(self, out_dir: str | Path, metadata: dict[str, Any]):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._files = []

        self.raw_points = self._writer(
            "raw_points.csv",
            [
                "frame",
                "time",
                "label",
                "tid",
                "point_index",
                "x",
                "y",
                "z",
                "doppler",
                "snr",
                "track_index",
            ],
        )
        self.targets = self._writer(
            "targets.csv",
            [
                "frame",
                "time",
                "label",
                "tid",
                "x",
                "y",
                "z",
                "vx",
                "vy",
                "vz",
                "ax",
                "ay",
                "az",
                "maxZ",
                "minZ",
                "confidence",
            ],
        )
        self.features_22 = self._writer(
            "features_22.csv",
            ["frame", "time", "label", "tid", *FEATURE_NAMES_22, "num_points", "low_quality", "reason"],
        )
        self.features_176 = self._writer(
            "features_176.csv",
            [
                "frame",
                "time",
                "label",
                "tid",
                "ready",
                *FEATURE_176_COLUMNS,
                "window_age",
                "num_points_recent",
                "low_quality_count",
            ],
        )
        self.events = self._writer("events.csv", ["frame", "time", "label", "tid", "event", "notes"])
        self.write_metadata(metadata)

    def close(self) -> None:
        for handle in self._files:
            handle.close()

    def __enter__(self) -> "PoseDataLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        payload = dict(metadata)
        payload.setdefault("date_time", datetime.now().isoformat(timespec="seconds"))
        with (self.out_dir / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    def write_event(self, frame: int, timestamp: float, label: str, tid: int | str, event: str, notes: str = "") -> None:
        self.events.writerow(
            {
                "frame": frame,
                "time": timestamp,
                "label": label,
                "tid": tid,
                "event": event,
                "notes": notes,
            }
        )

    def write_raw_points(
        self,
        frame: ParsedFrame,
        timestamp: float,
        label: str,
        tid: int,
        associated_points: Iterable[Point],
    ) -> None:
        for point in associated_points:
            self.raw_points.writerow(
                {
                    "frame": frame.frame_num,
                    "time": timestamp,
                    "label": label,
                    "tid": tid,
                    "point_index": point.index,
                    "x": point.x,
                    "y": point.y,
                    "z": point.z,
                    "doppler": point.doppler,
                    "snr": point.snr,
                    "track_index": point.track_index,
                }
            )

    def write_target(
        self,
        frame: ParsedFrame,
        timestamp: float,
        label: str,
        target: Target,
        height: TargetHeight | None,
    ) -> None:
        self.targets.writerow(
            {
                "frame": frame.frame_num,
                "time": timestamp,
                "label": label,
                "tid": target.tid,
                "x": target.pos_x,
                "y": target.pos_y,
                "z": target.pos_z,
                "vx": target.vel_x,
                "vy": target.vel_y,
                "vz": target.vel_z,
                "ax": target.acc_x,
                "ay": target.acc_y,
                "az": target.acc_z,
                "maxZ": "" if height is None else height.max_z,
                "minZ": "" if height is None else height.min_z,
                "confidence": target.confidence,
            }
        )

    def write_feature22(
        self,
        frame_num: int,
        timestamp: float,
        label: str,
        tid: int,
        feature22: list[float],
        num_points: int,
        low_quality: bool,
        reason: str,
    ) -> None:
        row = {
            "frame": frame_num,
            "time": timestamp,
            "label": label,
            "tid": tid,
            "num_points": num_points,
            "low_quality": int(low_quality),
            "reason": reason,
        }
        row.update(dict(zip(FEATURE_NAMES_22, feature22)))
        self.features_22.writerow(row)

    def write_feature176(
        self,
        frame_num: int,
        timestamp: float,
        label: str,
        tid: int,
        ready: bool,
        feature176: list[float],
        window_age: int,
        num_points_recent: int,
        low_quality_count: int,
    ) -> None:
        row = {
            "frame": frame_num,
            "time": timestamp,
            "label": label,
            "tid": tid,
            "ready": int(ready),
            "window_age": window_age,
            "num_points_recent": num_points_recent,
            "low_quality_count": low_quality_count,
        }
        row.update(dict(zip(FEATURE_176_COLUMNS, feature176)))
        self.features_176.writerow(row)

    def flush(self) -> None:
        for handle in self._files:
            handle.flush()

    def _writer(self, filename: str, fieldnames: list[str]) -> csv.DictWriter:
        handle = (self.out_dir / filename).open("w", newline="", encoding="utf-8")
        self._files.append(handle)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        return writer
