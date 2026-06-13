"""Standalone reimplementation of TI's People Tracking fall detector."""

from __future__ import annotations

import copy
from collections import deque
from typing import Iterable

from frame_types import FallStatus, Target, TargetHeight


class FallDetector:
    """Height-drop fall detector matching TI Industrial Visualizer behavior.

    Original source:
    tools\\visualizers\\Applications_Visualizer\\common\\Demo_Classes\\Helper_Classes\\fall_detection.py

    TI defaults are preserved from fall_detection.py:31-40:
    maxNumTracks=10, frameTime=55 ms, fallingThresholdProportion=0.6,
    secondsInFallBuffer=2.5, and fall display hold=100 frames.
    """

    def __init__(
        self,
        max_num_tracks: int = 10,
        frame_time_ms: int = 55,
        falling_threshold_proportion: float = 0.6,
        seconds_in_fall_buffer: float = 2.5,
        num_frames_to_display_fall: int = 100,
    ):
        self.frame_time_ms = frame_time_ms
        self.falling_threshold_proportion = falling_threshold_proportion
        self.seconds_in_fall_buffer = seconds_in_fall_buffer
        self.height_history_len = int(round((seconds_in_fall_buffer * 1000) / frame_time_ms))
        self.height_buffer = [
            deque([-5.0] * self.height_history_len, maxlen=self.height_history_len)
            for _ in range(max_num_tracks)
        ]
        self.tracks_ids_in_previous_frame: list[int] = []
        self.fall_buffer_display = [0 for _ in range(max_num_tracks)]
        self.num_frames_to_display_fall = num_frames_to_display_fall

    def set_fall_sensitivity(self, falling_threshold_proportion: float) -> None:
        """Set threshold directly, matching fall_detection.py:42-44."""
        self.falling_threshold_proportion = falling_threshold_proportion

    def set_slider_sensitivity(self, slider_value: int, slider_maximum: int = 100) -> None:
        """Apply TI UI mapping from people_tracking.py:224-225.

        Slider range 0..100 maps to threshold proportion 0.4..0.8.
        Larger values are more sensitive because a smaller height drop triggers.
        """
        if slider_maximum <= 0:
            raise ValueError("slider_maximum must be positive")
        self.set_fall_sensitivity(((slider_value / slider_maximum) * 0.4) + 0.4)

    def step(
        self,
        heights: Iterable[TargetHeight],
        tracks: Iterable[Target],
    ) -> list[FallStatus]:
        """Update fall state for one frame.

        TI decrements display counters, appends current maxZ per matched TID,
        triggers when current maxZ < threshold * oldest buffered maxZ, and
        resets stale track buffers in fall_detection.py:47-75.
        """
        for idx, result in enumerate(self.fall_buffer_display):
            self.fall_buffer_display[idx] = max(result - 1, 0)

        tracks_by_tid = {int(track.tid): track for track in tracks}
        track_ids_in_current_frame: list[int] = []
        statuses: list[FallStatus] = []

        for height in heights:
            tid = int(height.tid)
            if tid not in tracks_by_tid:
                continue

            self._ensure_track_capacity(tid)
            current_height = float(height.max_z)
            self.height_buffer[tid].appendleft(current_height)
            old_height = float(self.height_buffer[tid][-1])
            track_ids_in_current_frame.append(tid)

            threshold_height = self.falling_threshold_proportion * old_height
            just_triggered = current_height < threshold_height
            if just_triggered:
                self.fall_buffer_display[tid] = self.num_frames_to_display_fall

            is_fallen = self.fall_buffer_display[tid] > 0
            if old_height > 0:
                drop_ratio = current_height / old_height
            else:
                drop_ratio = None

            if just_triggered:
                reason = "current_height_below_threshold_times_old_height"
            elif is_fallen:
                reason = "fall_display_hold"
            elif old_height <= 0:
                reason = "history_not_ready"
            else:
                reason = "no_fall"

            statuses.append(
                FallStatus(
                    tid=tid,
                    is_fallen=is_fallen,
                    current_height=current_height,
                    old_height=old_height,
                    drop_ratio=drop_ratio,
                    threshold=self.falling_threshold_proportion,
                    hold_frames_remaining=self.fall_buffer_display[tid],
                    reason=reason,
                )
            )

        tracks_to_reset = set(self.tracks_ids_in_previous_frame) - set(track_ids_in_current_frame)
        for tid in tracks_to_reset:
            if tid < len(self.height_buffer):
                for _ in range(self.height_history_len):
                    self.height_buffer[tid].appendleft(-5.0)

        self.tracks_ids_in_previous_frame = copy.deepcopy(track_ids_in_current_frame)
        return statuses

    def _ensure_track_capacity(self, tid: int) -> None:
        while tid >= len(self.height_buffer):
            self.height_buffer.append(
                deque([-5.0] * self.height_history_len, maxlen=self.height_history_len)
            )
            self.fall_buffer_display.append(0)

