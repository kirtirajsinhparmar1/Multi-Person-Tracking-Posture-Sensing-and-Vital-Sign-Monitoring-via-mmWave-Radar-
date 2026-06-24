from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading
import unittest

import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dual_sensor_fusion.run_dual_sensor_fusion_ui import build_arg_parser
from dual_sensor_fusion.ui_performance import (
    AsyncMethodWorker,
    RateLimiter,
    downsample_series,
    drain_latest_by_kind,
)


class _BufferedTarget:
    def __init__(self):
        self.rows = []
        self.flush_count = 0
        self.closed = False
        self.rows_ready = threading.Event()
        self.flushed = threading.Event()

    def append(self, value):
        self.rows.append(value)
        if len(self.rows) >= 5:
            self.rows_ready.set()

    def flush(self):
        self.flush_count += 1
        self.flushed.set()

    def close(self):
        self.closed = True


class UiPerformanceTests(unittest.TestCase):
    def test_downsample_is_bounded_and_preserves_endpoints(self):
        x = np.arange(5000, dtype=float)
        y = x * 2.0
        sampled_x, sampled_y = downsample_series(
            x, y, max_points=1200
        )
        self.assertLessEqual(len(sampled_x), 1200)
        self.assertEqual(sampled_x[0], x[0])
        self.assertEqual(sampled_x[-1], x[-1])
        self.assertEqual(sampled_y[-1], y[-1])

    def test_rate_limiter_uses_configured_interval(self):
        limiter = RateLimiter(5.0)
        self.assertTrue(limiter.due(10.0))
        self.assertFalse(limiter.due(10.1))
        self.assertTrue(limiter.due(10.21))

    def test_queue_drain_keeps_latest_state_and_counts_drops(self):
        source = queue.Queue()
        source.put(("fe02", 1))
        source.put(("fe03", 10))
        source.put(("fe03", 11))
        source.put(("fe02", 2))
        latest, consumed, dropped = drain_latest_by_kind(source)
        self.assertEqual(consumed, 4)
        self.assertEqual(dropped, 2)
        self.assertEqual(latest["fe02"], ("fe02", 2))
        self.assertEqual(latest["fe03"], ("fe03", 11))
        self.assertTrue(source.empty())

    def test_async_writer_flushes_by_batch_not_per_row(self):
        target = _BufferedTarget()
        worker = AsyncMethodWorker(
            target,
            flush_interval_sec=10.0,
            flush_rows=5,
        )
        try:
            for value in range(5):
                self.assertTrue(worker.submit("append", value))
            self.assertTrue(target.rows_ready.wait(1.0))
            self.assertTrue(target.flushed.wait(1.0))
            self.assertEqual(target.rows, list(range(5)))
            self.assertEqual(target.flush_count, 1)
        finally:
            worker.close()
        self.assertTrue(target.closed)

    def test_performance_cli_defaults_are_available(self):
        args = build_arg_parser().parse_args([])
        self.assertEqual(args.ui_update_hz, 10.0)
        self.assertEqual(args.heatmap_update_hz, 5.0)
        self.assertEqual(args.phase_plot_update_hz, 5.0)
        self.assertEqual(args.spectrum_update_hz, 1.0)
        self.assertEqual(args.plot_max_visible_points, 1200)
        self.assertEqual(args.right_panel_width, 420)
        self.assertEqual(args.csv_flush_rows, 50)
        self.assertTrue(args.diagnostics_tabbed)


if __name__ == "__main__":
    unittest.main()
