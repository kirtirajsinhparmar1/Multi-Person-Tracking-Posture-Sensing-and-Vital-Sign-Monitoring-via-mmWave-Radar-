"""Capture labeled IWR6843 data in TI Pose/Fall feature format."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import time

from cli_sender import DEFAULT_CFG_PATH, CliSenderError, send_config
from frame_types import ParsedFrame, Target, TargetHeight
from pose_data_logger import PoseDataLogger
from pose_feature_extractor import (
    CLASS_NAMES,
    associated_points_for_target,
    build_176_feature_vector,
    build_22_feature_vector,
    get_low_quality_count,
    get_recent_num_points,
    get_window_age,
    is_window_ready,
    reset_all,
    update_8_frame_window,
)
from serial_reader import RadarSerialReader


LABELS = [name.lower() for name in CLASS_NAMES]
LABEL_TO_CLASS_ID = {name.lower(): index for index, name in enumerate(CLASS_NAMES)}


def main() -> int:
    args = parse_args()
    label = args.label.lower()
    cfg_path = Path(args.cfg).expanduser().resolve()
    capture_dir = build_capture_dir(Path(args.out), args.subject, label, args.trial)

    if not args.no_send_cfg:
        try:
            send_config(args.cli, args.cli_baud, cfg_path)
        except CliSenderError as exc:
            print(f"CLI config send failed: {exc}")
            return 2

    metadata = {
        "sensor": "IWR6843ISK-ODS",
        "cfg_path": str(cfg_path),
        "cli_port": args.cli,
        "data_port": args.data,
        "label": label,
        "class_id": LABEL_TO_CLASS_ID[label],
        "class_names": CLASS_NAMES,
        "subject_id": args.subject,
        "trial_id": args.trial,
        "room": args.room,
        "sensor_height": args.sensor_height,
        "sensor_tilt": args.sensor_tilt,
        "date_time": datetime.now().isoformat(timespec="seconds"),
        "notes": args.notes,
        "feature_order_22": [
            "posz",
            "velx",
            "vely",
            "velz",
            "accx",
            "accy",
            "accz",
            "y0",
            "z0",
            "snr0",
            "y1",
            "z1",
            "snr1",
            "y2",
            "z2",
            "snr2",
            "y3",
            "z3",
            "snr3",
            "y4",
            "z4",
            "snr4",
        ],
        "feature_order_176": "channel-major: feature_f0..feature_f7 for each of 22 features",
    }

    print(
        "Starting pose capture | "
        f"label={label} subject={args.subject} trial={args.trial} "
        f"duration={args.duration}s data={args.data} out={capture_dir}"
    )
    reset_all()

    frames_seen = 0
    ready_windows = 0
    low_quality_total = 0
    warned_multi_target = False
    last_status = time.monotonic()
    start = time.monotonic()

    try:
        with RadarSerialReader(args.data, args.baud, timeout=args.timeout) as reader, PoseDataLogger(
            capture_dir, metadata
        ) as logger:
            logger.write_event(0, time.time(), label, "", "capture_start", args.notes)

            while time.monotonic() - start < args.duration:
                try:
                    frame = reader.read_parsed_frame()
                except TimeoutError as exc:
                    print(f"UART timeout: {exc}")
                    continue

                timestamp = time.time()
                frames_seen += 1
                target_count = len(frame.targets)
                point_count = len(frame.points)

                if target_count > 1 and args.target_id is None and not warned_multi_target:
                    print("Warning: multiple targets present; logging all targets. Use --target-id to isolate one.")
                    logger.write_event(
                        frame.frame_num,
                        timestamp,
                        label,
                        "",
                        "multiple_targets",
                        "Logging all targets because --target-id was not provided.",
                    )
                    warned_multi_target = True

                heights_by_tid = {height.tid: height for height in frame.heights}
                targets = select_targets(frame, args.target_id)

                for target in targets:
                    associated_points = associated_points_for_target(target, frame.points)
                    feature_result = build_22_feature_vector(target, associated_points)
                    update_8_frame_window(target.tid, feature_result.feature22, feature_result.quality)
                    feature176 = build_176_feature_vector(target.tid)
                    ready = is_window_ready(target.tid)
                    if ready:
                        ready_windows += 1
                    if feature_result.low_quality:
                        low_quality_total += 1

                    logger.write_raw_points(frame, timestamp, label, target.tid, associated_points)
                    logger.write_target(frame, timestamp, label, target, heights_by_tid.get(target.tid))
                    logger.write_feature22(
                        frame.frame_num,
                        timestamp,
                        label,
                        target.tid,
                        feature_result.feature22,
                        feature_result.num_points,
                        feature_result.low_quality,
                        feature_result.reason,
                    )
                    logger.write_feature176(
                        frame.frame_num,
                        timestamp,
                        label,
                        target.tid,
                        ready,
                        feature176,
                        get_window_age(target.tid),
                        get_recent_num_points(target.tid),
                        get_low_quality_count(target.tid),
                    )

                    if feature_result.num_points < args.min_points:
                        logger.write_event(
                            frame.frame_num,
                            timestamp,
                            label,
                            target.tid,
                            "low_point_count",
                            f"num_points={feature_result.num_points}, min_points={args.min_points}",
                        )

                now = time.monotonic()
                if now - last_status >= 1.0:
                    print(
                        "status "
                        f"elapsed={now - start:.1f}s frames={frames_seen} "
                        f"targets={target_count} points={point_count} "
                        f"ready_176_windows={ready_windows} low_quality_count={low_quality_total}"
                    )
                    logger.flush()
                    last_status = now

            logger.write_event(0, time.time(), label, "", "capture_stop", "duration complete")
            logger.flush()
    except KeyboardInterrupt:
        print("Capture interrupted by user.")
    except Exception as exc:
        print(f"Pose capture failed: {exc}")
        return 3

    print(f"Capture complete: {capture_dir}")
    return 0


def select_targets(frame: ParsedFrame, target_id: int | None) -> list[Target]:
    if target_id is None:
        return frame.targets
    return [target for target in frame.targets if target.tid == target_id]


def build_capture_dir(root: Path, subject: str, label: str, trial: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root.expanduser().resolve() / subject / label / f"{trial}_{stamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture labeled IWR6843 tracks in TI Pose/Fall 22x8 feature format."
    )
    parser.add_argument("--cli", default="COM7", help="CLI/config UART port")
    parser.add_argument("--cli-baud", type=int, default=115200, help="CLI/config UART baud rate")
    parser.add_argument("--data", default="COM6", help="Data UART port")
    parser.add_argument("--baud", type=int, default=921600, help="Data UART baud rate")
    parser.add_argument("--cfg", default=str(DEFAULT_CFG_PATH), help="Radar cfg path")
    parser.add_argument("--label", required=True, choices=LABELS, help="Pose/action label")
    parser.add_argument("--subject", default="S01", help="Subject ID, e.g. S01")
    parser.add_argument("--trial", default="T01", help="Trial ID, e.g. T01")
    parser.add_argument("--duration", type=float, default=60.0, help="Capture duration in seconds")
    parser.add_argument("--out", default="dataset/iwr6843_pose", help="Dataset root output folder")
    parser.add_argument("--notes", default="", help="Optional notes stored in metadata.json")
    parser.add_argument("--no-send-cfg", action="store_true", help="Do not send cfg over the CLI port")
    parser.add_argument("--target-id", type=int, help="Only log one target ID")
    parser.add_argument("--min-points", type=int, default=5, help="Minimum associated points for quality")
    parser.add_argument("--timeout", type=float, default=0.6, help="Data UART frame timeout")
    parser.add_argument("--room", default="", help="Room/location note for metadata")
    parser.add_argument("--sensor-height", type=float, default=0.0, help="Sensor mounting height in meters")
    parser.add_argument("--sensor-tilt", type=float, default=0.0, help="Sensor tilt in degrees")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
