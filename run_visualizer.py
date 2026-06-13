"""Entry point for the standalone IWR6843 fall visualizer."""

from __future__ import annotations

import argparse
import sys

from cli_sender import DEFAULT_CFG_PATH


def parse_args():
    parser = argparse.ArgumentParser(description="Standalone IWR6843 fall visualizer")
    parser.add_argument("--cli", default="COM7", help="CLI/config UART port")
    parser.add_argument("--cli-baud", type=int, default=115200, help="CLI/config UART baud rate")
    parser.add_argument("--data", default="COM6", help="Data UART port")
    parser.add_argument("--baud", type=int, default=921600, help="Data UART baud rate")
    parser.add_argument("--cfg", default=str(DEFAULT_CFG_PATH), help="Radar cfg path")
    parser.add_argument("--out", default="logs/ui_test1", help="Output log folder")
    parser.add_argument("--max-tracks", type=int, default=10, help="Initial max track slots")
    parser.add_argument("--frame-time", type=int, default=55, help="Frame time in ms")
    parser.add_argument("--timeout", type=float, default=0.6, help="Serial read timeout")
    parser.add_argument("--no-send-cfg", action="store_true", help="Do not send cfg before streaming")
    parser.add_argument("--no-points", action="store_true", help="Do not write points.csv")
    parser.add_argument("--demo", action="store_true", help="Run synthetic demo frames without opening COM ports")
    parser.add_argument("--replay", default="", help="TODO: replay a frames.jsonl or log folder")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from visualizer_app import run_app
    except ImportError as exc:
        print(
            "Could not import visualizer dependencies.\n"
            "Install them with: pip install -r custom_iwr6843_fall_logger/requirements.txt\n"
            f"Import error: {exc}",
            file=sys.stderr,
        )
        return 2
    return run_app(args)


if __name__ == "__main__":
    raise SystemExit(main())
