"""CSV logging for IWR6843 targets, heights, points, and fall status."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from frame_types import FallStatus, ParsedFrame


class CsvLogger:
    def __init__(self, out_dir: str | Path, log_points: bool = True):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_points = log_points
        self._files = []

        self.targets = self._writer(
            "targets.csv",
            [
                "frame",
                "time",
                "tid",
                "pos_x",
                "pos_y",
                "pos_z",
                "vel_x",
                "vel_y",
                "vel_z",
                "acc_x",
                "acc_y",
                "acc_z",
                "g",
                "confidence",
            ],
        )
        self.heights = self._writer("heights.csv", ["frame", "time", "tid", "max_z", "min_z"])
        self.fall_events = self._writer(
            "fall_events.csv",
            [
                "frame",
                "time",
                "tid",
                "is_fallen",
                "current_height",
                "old_height",
                "drop_ratio",
                "threshold",
                "reason",
            ],
        )
        self.frames_summary = self._writer(
            "frames_summary.csv",
            [
                "frame",
                "time",
                "num_detected_obj",
                "num_tlvs",
                "num_targets",
                "num_heights",
                "num_points",
                "presence",
                "parse_error",
                "total_packet_len",
            ],
        )
        self.points = None
        if log_points:
            self.points = self._writer(
                "points.csv",
                [
                    "frame",
                    "time",
                    "index",
                    "x",
                    "y",
                    "z",
                    "doppler",
                    "snr",
                    "range",
                    "azimuth",
                    "elevation",
                    "track_index",
                ],
            )

    def close(self) -> None:
        for f in self._files:
            f.flush()
            f.close()

    def __enter__(self) -> "CsvLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def write_frame(
        self,
        frame: ParsedFrame,
        timestamp: float,
        fall_statuses: Iterable[FallStatus],
    ) -> None:
        frame_num = frame.frame_num

        self.frames_summary.writerow(
            {
                "frame": frame_num,
                "time": timestamp,
                "num_detected_obj": frame.header.num_detected_obj,
                "num_tlvs": frame.header.num_tlvs,
                "num_targets": len(frame.targets),
                "num_heights": len(frame.heights),
                "num_points": len(frame.points),
                "presence": "" if frame.presence is None else frame.presence,
                "parse_error": frame.parse_error or "",
                "total_packet_len": frame.header.total_packet_len,
            }
        )

        for target in frame.targets:
            self.targets.writerow(
                {
                    "frame": frame_num,
                    "time": timestamp,
                    "tid": target.tid,
                    "pos_x": target.pos_x,
                    "pos_y": target.pos_y,
                    "pos_z": target.pos_z,
                    "vel_x": target.vel_x,
                    "vel_y": target.vel_y,
                    "vel_z": target.vel_z,
                    "acc_x": target.acc_x,
                    "acc_y": target.acc_y,
                    "acc_z": target.acc_z,
                    "g": target.g,
                    "confidence": target.confidence,
                }
            )

        for height in frame.heights:
            self.heights.writerow(
                {
                    "frame": frame_num,
                    "time": timestamp,
                    "tid": height.tid,
                    "max_z": height.max_z,
                    "min_z": height.min_z,
                }
            )

        for status in fall_statuses:
            self.fall_events.writerow(
                {
                    "frame": frame_num,
                    "time": timestamp,
                    "tid": status.tid,
                    "is_fallen": int(status.is_fallen),
                    "current_height": _none_to_empty(status.current_height),
                    "old_height": _none_to_empty(status.old_height),
                    "drop_ratio": _none_to_empty(status.drop_ratio),
                    "threshold": status.threshold,
                    "reason": status.reason,
                }
            )

        if self.points is not None:
            for point in frame.points:
                self.points.writerow(
                    {
                        "frame": frame_num,
                        "time": timestamp,
                        "index": point.index,
                        "x": point.x,
                        "y": point.y,
                        "z": point.z,
                        "doppler": point.doppler,
                        "snr": point.snr,
                        "range": point.range_m,
                        "azimuth": point.azimuth,
                        "elevation": point.elevation,
                        "track_index": point.track_index,
                    }
                )

        self.flush()

    def flush(self) -> None:
        for f in self._files:
            f.flush()

    def _writer(self, filename: str, fieldnames: list[str]) -> csv.DictWriter:
        f = (self.out_dir / filename).open("w", newline="")
        self._files.append(f)
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        return writer


def _none_to_empty(value):
    return "" if value is None else value

