"""Run the standalone IWR6843 fall logger.

Example:
    python run_fall_logger.py --cli COM7 --data COM6 --out logs/fall_test1
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from cli_sender import DEFAULT_CFG_PATH, CliSenderError, send_config
from csv_logger import CsvLogger
from fall_detector import FallDetector
from serial_reader import RadarSerialReader


def main() -> int:
    args = parse_args()

    if not args.no_send_cfg:
        cfg_path = Path(args.cfg)
        if cfg_path.exists():
            try:
                send_config(args.cli, args.cli_baud, cfg_path)
            except CliSenderError as exc:
                print(f"CLI config send failed: {exc}")
                return 2
        else:
            print(f"Config file not found, skipping cfg send: {cfg_path}")

    detector = FallDetector(
        max_num_tracks=args.max_tracks,
        frame_time_ms=args.frame_time,
        falling_threshold_proportion=args.threshold,
        seconds_in_fall_buffer=args.seconds_in_fall_buffer,
    )

    print(
        "Starting IWR6843 fall logger | "
        f"cli={args.cli} data={args.data} baud={args.baud} out={args.out} "
        f"threshold={args.threshold} frameTime={args.frame_time}ms"
    )

    try:
        with RadarSerialReader(args.data, args.baud, timeout=args.timeout) as reader, CsvLogger(
            args.out, log_points=not args.no_points
        ) as logger:
            frames_seen = 0
            while args.frames <= 0 or frames_seen < args.frames:
                try:
                    frame = reader.read_parsed_frame()
                except TimeoutError as exc:
                    print(
                        f"UART timeout: {exc}\n"
                        "No data frames received. Check: board functional mode, "
                        "COM6/COM7 ports, cfg sent successfully, sensorStart Done, "
                        "and close TI Visualizer/UniFlash."
                    )
                    continue

                timestamp = time.time()
                statuses = detector.step(frame.heights, frame.targets)
                logger.write_frame(frame, timestamp, statuses)
                frames_seen += 1

                if statuses:
                    for status in statuses:
                        print(format_status(frame.frame_num, status))
                elif args.print_empty:
                    print(
                        f"Frame {frame.frame_num} | targets={len(frame.targets)} "
                        f"heights={len(frame.heights)} points={len(frame.points)} "
                        f"presence={frame.presence}"
                    )
    except Exception as exc:
        print(f"Data UART/logging failed: {exc}")
        return 3

    return 0


def format_status(frame_num, status) -> str:
    height = "nan" if status.current_height is None else f"{status.current_height:.2f}"
    text = f"Frame {frame_num} | TID {status.tid} | height {height} m | fall={status.is_fallen}"
    if status.drop_ratio is not None:
        text += f" | drop_ratio={status.drop_ratio:.2f}"
    if status.reason not in ("no_fall", "history_not_ready"):
        text += f" | reason={status.reason}"
    return text


def parse_args():
    parser = argparse.ArgumentParser(description="Standalone IWR6843 fall logger")
    parser.add_argument("--cli", default="COM7", help="CLI/config UART port, default COM7")
    parser.add_argument("--cli-baud", type=int, default=115200, help="CLI/config UART baud rate")
    parser.add_argument("--data", default="COM6", help="Data UART port, default COM6")
    parser.add_argument("--baud", type=int, default=921600, help="Data UART baud rate")
    parser.add_argument(
        "--cfg",
        default=str(DEFAULT_CFG_PATH),
        help="Radar cfg file to send before reading data frames",
    )
    parser.add_argument(
        "--no-send-cfg",
        action="store_true",
        help="Skip COM7 cfg sending and only read the data UART",
    )
    parser.add_argument("--out", default="logs/fall_test1", help="Output log directory")
    parser.add_argument("--max-tracks", type=int, default=10, help="Initial max track slots")
    parser.add_argument("--frame-time", type=int, default=55, help="Frame time in ms")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Fall threshold proportion; TI default is 0.6",
    )
    parser.add_argument(
        "--seconds-in-fall-buffer",
        type=float,
        default=2.5,
        help="Height history window in seconds",
    )
    parser.add_argument("--timeout", type=float, default=0.6, help="Serial read timeout")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N frames; 0 means run forever")
    parser.add_argument("--no-points", action="store_true", help="Do not write points.csv")
    parser.add_argument(
        "--print-empty",
        action="store_true",
        help="Print frame summaries even when no target-height status is produced",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
