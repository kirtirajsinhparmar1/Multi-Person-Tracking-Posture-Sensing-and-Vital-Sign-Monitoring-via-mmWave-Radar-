"""Inspect TI Vital Signs With People Tracking UART output.

This utility sends a radar configuration over the CLI port, reads complete
binary frames from the data port, and reports tracking and vital-sign TLVs.
It intentionally has no GUI dependencies and does not modify firmware.
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_DIR = Path(__file__).resolve().parent
VENDOR_COMMON_DIR = PROJECT_DIR / "ti_style_vendor" / "common"

MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
FRAME_HEADER = struct.Struct("<Q8I")
TLV_HEADER = struct.Struct("<II")
TRACK_STRUCT = struct.Struct("<I27f")
VITAL_STRUCT = struct.Struct("<2H33f")
MAX_PACKET_BYTES = 2 * 1024 * 1024

TLV_NAMES = {
    1: "pointCloud",
    2: "rangeProfile",
    3: "noiseProfile",
    4: "azimuthStaticHeatMap",
    5: "rangeDopplerHeatMap",
    6: "stats",
    7: "sideInfo",
    1000: "pointCloud",
    1010: "targetList",
    1011: "targetIndex",
    1012: "targetHeight",
    1020: "pointCloud",
    1021: "presence",
    1040: "vitals",
}

CSV_COLUMNS = [
    "time",
    "frame",
    "tlv_names",
    "num_points",
    "num_targets",
    "target_ids",
    "num_heights",
    "num_vitals",
    "vital_id",
    "rangeBin",
    "breathRate",
    "heartRate",
    "breathDeviation",
    "parser_error",
]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send a cfg and inspect TI People Tracking/Vital Signs UART frames "
            "(including vital-sign TLV 1040)."
        )
    )
    parser.add_argument("--cli", required=True, help="CLI/config COM port, for example COM7.")
    parser.add_argument("--data", required=True, help="Binary data COM port, for example COM6.")
    parser.add_argument("--cfg", required=True, help="Path to the firmware-compatible cfg file.")
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=60.0,
        help="Capture duration in seconds (default: 60).",
    )
    parser.add_argument(
        "--out",
        default=r"logs\vital_stream_inspect",
        help=r"Output directory (default: logs\vital_stream_inspect).",
    )
    parser.add_argument("--csv", action="store_true", help="Save frame summaries to CSV.")
    parser.add_argument("--debug", action="store_true", help="Print parser and TLV details.")
    parser.add_argument("--cli-baud", type=int, default=115200, help="CLI baud rate.")
    parser.add_argument("--data-baud", type=int, default=921600, help="Data baud rate.")
    return parser


def import_ti_parser():
    """Import the vendored non-GUI parser after command-line processing."""
    common_path = str(VENDOR_COMMON_DIR)
    if common_path not in sys.path:
        sys.path.insert(0, common_path)
    from demo_defines import DEMO_VITALS  # type: ignore
    from parseFrame import parseStandardFrame  # type: ignore

    return parseStandardFrame, DEMO_VITALS


def _read_exact(port: Any, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = port.read(count - len(data))
        if not chunk:
            raise TimeoutError(f"Timed out after {len(data)}/{count} bytes")
        data.extend(chunk)
    return bytes(data)


def read_frame_bytes(port: Any) -> bytes:
    """Synchronize to the TI magic word and read one complete packet."""
    matched = 0
    while matched < len(MAGIC_WORD):
        chunk = port.read(1)
        if not chunk:
            raise TimeoutError("Timed out waiting for frame magic word")
        byte = chunk[0]
        if byte == MAGIC_WORD[matched]:
            matched += 1
        else:
            matched = 1 if byte == MAGIC_WORD[0] else 0

    version_and_length = _read_exact(port, 8)
    _, total_packet_len = struct.unpack("<II", version_and_length)
    if total_packet_len < FRAME_HEADER.size:
        raise ValueError(f"Invalid packet length {total_packet_len}")
    if total_packet_len > MAX_PACKET_BYTES:
        raise ValueError(f"Packet length {total_packet_len} exceeds safety limit")

    prefix = MAGIC_WORD + version_and_length
    return prefix + _read_exact(port, total_packet_len - len(prefix))


def scan_raw_tlvs(packet: bytes) -> tuple[dict[str, int], list[dict[str, Any]], list[str]]:
    """Read the frame header and TLV boundaries without interpreting payloads."""
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    if len(packet) < FRAME_HEADER.size:
        return {}, records, ["packet shorter than 40-byte frame header"]

    fields = FRAME_HEADER.unpack_from(packet)
    header = {
        "magic": fields[0],
        "version": fields[1],
        "total_packet_len": fields[2],
        "platform": fields[3],
        "frame_number": fields[4],
        "time_cpu_cycles": fields[5],
        "num_detected_obj": fields[6],
        "num_tlvs": fields[7],
        "subframe_number": fields[8],
    }
    packet_limit = min(len(packet), header["total_packet_len"])
    if header["total_packet_len"] > len(packet):
        errors.append(
            f"header packet length {header['total_packet_len']} exceeds received {len(packet)}"
        )

    offset = FRAME_HEADER.size
    for index in range(header["num_tlvs"]):
        if offset + TLV_HEADER.size > packet_limit:
            errors.append(f"TLV {index} header truncated at offset {offset}")
            break
        tlv_type, declared_length = TLV_HEADER.unpack_from(packet, offset)
        offset += TLV_HEADER.size

        payload_length = declared_length
        if offset + payload_length > packet_limit:
            # Some SDK packet variants include the 8-byte TLV header in length.
            alternate_length = declared_length - TLV_HEADER.size
            if declared_length >= TLV_HEADER.size and offset + alternate_length <= packet_limit:
                payload_length = alternate_length
                errors.append(f"TLV {tlv_type} length appears to include its header")
            else:
                errors.append(
                    f"TLV {tlv_type} payload truncated: length={declared_length}, "
                    f"remaining={packet_limit - offset}"
                )
                break

        payload = packet[offset : offset + payload_length]
        records.append(
            {
                "index": index,
                "type": tlv_type,
                "name": TLV_NAMES.get(tlv_type, f"type_{tlv_type}"),
                "declared_length": declared_length,
                "payload": payload,
            }
        )
        offset += payload_length

    return header, records, errors


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        lowered = {str(key).lower(): item for key, item in value.items()}
        for name in names:
            if name in value:
                return value[name]
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None
    dtype = getattr(value, "dtype", None)
    dtype_names = getattr(dtype, "names", None)
    if dtype_names:
        lower_names = {name.lower(): name for name in dtype_names}
        for name in names:
            actual = lower_names.get(name.lower())
            if actual is not None:
                return value[actual]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _looks_like_vital_record(value: Any) -> bool:
    return any(
        _field(value, name) is not None
        for name in ("id", "rangeBin", "breathRate", "heartRate", "breathDeviation")
    )


def normalize_vitals(value: Any) -> list[dict[str, Any]]:
    """Normalize dict/list/numpy/object vital outputs into dictionaries."""
    if value is None:
        return []
    if _looks_like_vital_record(value):
        candidates: Iterable[Any] = [value]
    elif isinstance(value, dict):
        candidates = list(value.values())
    elif isinstance(value, (str, bytes, bytearray)):
        return []
    else:
        try:
            if getattr(value, "ndim", 0) == 0 and hasattr(value, "item"):
                candidates = [value.item()]
            else:
                candidates = list(value)
        except (TypeError, ValueError):
            candidates = [value]

    records: list[dict[str, Any]] = []
    for candidate in candidates:
        if not _looks_like_vital_record(candidate):
            continue
        records.append(
            {
                "id": _field(candidate, "id", "tid", "targetId", "target_id"),
                "rangeBin": _field(candidate, "rangeBin", "range_bin"),
                "breathRate": _field(
                    candidate, "breathRate", "breathingRate", "breathing_rate_bpm"
                ),
                "heartRate": _field(candidate, "heartRate", "heart_rate_bpm"),
                "breathDeviation": _field(
                    candidate, "breathDeviation", "breath_deviation"
                ),
            }
        )
    return records


def parse_raw_vital_payload(payload: bytes) -> tuple[dict[str, Any] | None, str | None]:
    if len(payload) < VITAL_STRUCT.size:
        return None, f"vital payload is {len(payload)} bytes; expected at least {VITAL_STRUCT.size}"
    values = VITAL_STRUCT.unpack_from(payload)
    return (
        {
            "id": values[0],
            "rangeBin": values[1],
            "breathDeviation": values[2],
            "heartRate": values[3],
            "breathRate": values[4],
        },
        None,
    )


def target_ids_from_output(output: dict[str, Any], tlvs: list[dict[str, Any]]) -> list[int]:
    track_data = output.get("trackData")
    ids: list[int] = []
    if track_data is not None:
        try:
            for row in track_data:
                ids.append(int(row[0]))
        except (TypeError, ValueError, IndexError):
            ids = []
    if ids:
        return ids

    for tlv in tlvs:
        if tlv["type"] != 1010:
            continue
        payload = tlv["payload"]
        for offset in range(0, len(payload) - TRACK_STRUCT.size + 1, TRACK_STRUCT.size):
            ids.append(int(TRACK_STRUCT.unpack_from(payload, offset)[0]))
    return ids


def safe_len(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except (TypeError, ValueError):
        return 0


def number_from_output(output: dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(output.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def format_value(value: Any, decimals: int = 1) -> str:
    number = _finite_number(value)
    if number is None:
        return "-"
    return f"{number:.{decimals}f}"


def join_values(records: list[dict[str, Any]], field_name: str, decimals: int | None = None) -> str:
    values: list[str] = []
    for record in records:
        value = record.get(field_name)
        if decimals is None:
            if value is None:
                values.append("")
            else:
                try:
                    values.append(str(int(value)))
                except (TypeError, ValueError):
                    values.append(str(value))
        else:
            values.append(format_value(value, decimals))
    return ";".join(values)


def summarize_frame(
    packet: bytes,
    parse_standard_frame: Any,
    demo_vitals: Any,
    debug: bool,
) -> tuple[str, dict[str, Any]]:
    header, tlvs, raw_errors = scan_raw_tlvs(packet)
    parser_errors = list(raw_errors)
    output: dict[str, Any] = {}
    try:
        parsed = parse_standard_frame(bytearray(packet), demo_vitals)
        if isinstance(parsed, dict):
            output = parsed
        else:
            parser_errors.append(f"TI parser returned {type(parsed).__name__}, not dict")
    except Exception as exc:  # Parser must not terminate stream inspection.
        parser_errors.append(f"TI parser: {type(exc).__name__}: {exc}")

    parser_error_code = output.get("error")
    if parser_error_code not in (None, 0):
        parser_errors.append(f"TI parser error={parser_error_code}")

    raw_vitals: list[dict[str, Any]] = []
    for tlv in tlvs:
        if tlv["type"] != 1040:
            continue
        vital, error = parse_raw_vital_payload(tlv["payload"])
        if vital is not None:
            raw_vitals.append(vital)
        if error:
            parser_errors.append(error)
    vitals = raw_vitals or normalize_vitals(output.get("vitals"))

    target_ids = target_ids_from_output(output, tlvs)
    frame_number = number_from_output(
        output, "frameNum", int(header.get("frame_number", -1))
    )
    num_targets = number_from_output(
        output, "numDetectedTracks", safe_len(output.get("trackData"))
    )
    if not num_targets:
        num_targets = len(target_ids)
    num_heights = number_from_output(
        output, "numDetectedHeights", safe_len(output.get("heightData"))
    )
    num_points = number_from_output(
        output,
        "numDetectedPoints",
        safe_len(output.get("pointCloud"))
        or int(header.get("num_detected_obj", 0)),
    )
    tlv_names = [str(tlv["name"]) for tlv in tlvs]

    parts = [
        f"Frame {frame_number}",
        f"TLVs=[{', '.join(tlv_names)}]",
        f"points={num_points}",
        f"targets={num_targets} ids={target_ids}",
    ]
    if num_heights:
        parts.append(f"heights={num_heights}")
    if vitals:
        vital_text = []
        for vital in vitals:
            vital_text.append(
                "id={id} rangeBin={range_bin} BR={br} HR={hr} dev={dev}".format(
                    id=vital.get("id", "-"),
                    range_bin=vital.get("rangeBin", "-"),
                    br=format_value(vital.get("breathRate")),
                    hr=format_value(vital.get("heartRate")),
                    dev=format_value(vital.get("breathDeviation"), 3),
                )
            )
        parts.append(f"vitals={len(vitals)} " + "; ".join(vital_text))
    else:
        parts.append("NO_VITAL_TLV")
    if parser_errors:
        parts.append("parser_error=" + " | ".join(parser_errors))
    if debug:
        parts.append(
            "raw_tlvs="
            + str([(tlv["type"], tlv["declared_length"]) for tlv in tlvs])
        )

    row = {
        "time": datetime.now(timezone.utc).isoformat(),
        "frame": frame_number,
        "tlv_names": ";".join(tlv_names),
        "num_points": num_points,
        "num_targets": num_targets,
        "target_ids": ";".join(str(tid) for tid in target_ids),
        "num_heights": num_heights,
        "num_vitals": len(vitals),
        "vital_id": join_values(vitals, "id"),
        "rangeBin": join_values(vitals, "rangeBin"),
        "breathRate": join_values(vitals, "breathRate", 4),
        "heartRate": join_values(vitals, "heartRate", 4),
        "breathDeviation": join_values(vitals, "breathDeviation", 6),
        "parser_error": " | ".join(parser_errors),
    }
    return " | ".join(parts), row


def _quiet_cli_output(message: str) -> None:
    lowered = message.lower()
    if any(token in lowered for token in ("warning", "error", "opened", "sending")):
        print(message, flush=True)


def run(args: argparse.Namespace) -> int:
    cfg_path = Path(args.cfg).expanduser().resolve()
    if not cfg_path.is_file():
        print(f"Configuration file not found: {cfg_path}", file=sys.stderr)
        return 2
    if args.duration_sec <= 0:
        print("--duration-sec must be greater than zero", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = PROJECT_DIR / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "vital_stream_frames.csv"

    try:
        import serial  # type: ignore
        from cli_sender import CliSenderError, send_config
    except ImportError as exc:
        print(
            f"Missing runtime dependency: {exc}. Install pyserial with "
            "'python -m pip install pyserial'.",
            file=sys.stderr,
        )
        return 2

    try:
        parse_standard_frame, demo_vitals = import_ti_parser()
    except Exception as exc:
        print(f"Unable to import vendored TI parser: {exc}", file=sys.stderr)
        return 2

    print(
        f"Sending cfg over {args.cli} at {args.cli_baud}: {cfg_path}",
        flush=True,
    )
    try:
        send_config(
            cli_port=args.cli,
            cli_baud=args.cli_baud,
            cfg_path=str(cfg_path),
            output=print if args.debug else _quiet_cli_output,
        )
    except (CliSenderError, serial.SerialException, OSError) as exc:
        print(f"CLI configuration failed: {exc}", file=sys.stderr)
        return 1

    csv_file = None
    writer = None
    frames = 0
    vital_frames = 0
    parser_error_frames = 0
    try:
        if args.csv:
            csv_file = csv_path.open("w", newline="", encoding="utf-8")
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()

        print(
            f"Opening data port {args.data} at {args.data_baud} for "
            f"{args.duration_sec:g} seconds...",
            flush=True,
        )
        with serial.Serial(args.data, args.data_baud, timeout=0.5) as data_port:
            data_port.reset_input_buffer()
            deadline = time.monotonic() + args.duration_sec
            while time.monotonic() < deadline:
                try:
                    packet = read_frame_bytes(data_port)
                    summary, row = summarize_frame(
                        packet, parse_standard_frame, demo_vitals, args.debug
                    )
                except TimeoutError as exc:
                    if args.debug:
                        print(f"[debug] {exc}", flush=True)
                    continue
                except (ValueError, struct.error) as exc:
                    parser_error_frames += 1
                    print(f"Frame parse error: {exc}", flush=True)
                    continue

                frames += 1
                if row["num_vitals"]:
                    vital_frames += 1
                if row["parser_error"]:
                    parser_error_frames += 1
                print(summary, flush=True)
                if writer is not None:
                    writer.writerow(row)
                    csv_file.flush()
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    except (serial.SerialException, OSError) as exc:
        print(f"Data port failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if csv_file is not None:
            csv_file.close()

    print(
        f"Inspection complete: frames={frames}, vital_frames={vital_frames}, "
        f"parser_error_frames={parser_error_frames}",
        flush=True,
    )
    if args.csv:
        print(f"CSV saved: {csv_path}", flush=True)
    return 0


def main() -> int:
    args = build_arg_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
