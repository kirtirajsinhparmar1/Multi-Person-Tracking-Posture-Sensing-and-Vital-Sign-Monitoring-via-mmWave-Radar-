"""Read AWR1642 real-I/Q bin-window TLV 0xFE02 from the data UART."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ti_uart_packet_parser import (  # noqa: E402
    FRAME_HEADER_SIZE,
    FRAME_HEADER_STRUCT,
    MAGIC_WORD,
    extract_vital_phase_bin_window_tlvs,
    extract_vital_phase_tlvs,
    find_magic_word,
    parse_frame_header,
)


MAX_PACKET_SIZE = 1024 * 1024
CSV_COLUMNS = (
    "timestamp",
    "frameNumber",
    "binIndex",
    "rangeMeters",
    "iValue",
    "qValue",
    "phaseRad",
    "magnitude",
)


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}", flush=True)


def _extract_complete_frames(
    buffer: bytearray, debug: bool
) -> Iterable[tuple[object, list, list]]:
    """Consume complete packets and yield header, 0xFE02 windows, and 0xFE01."""
    while True:
        magic_index = find_magic_word(buffer)
        if magic_index < 0:
            keep = min(len(buffer), len(MAGIC_WORD) - 1)
            dropped = len(buffer) - keep
            if dropped:
                del buffer[:dropped]
                _debug(debug, f"discarded {dropped} byte(s) before magic word")
            return

        if magic_index:
            del buffer[:magic_index]
            _debug(debug, f"discarded {magic_index} byte(s) before packet")

        if len(buffer) < FRAME_HEADER_SIZE:
            return

        fields = FRAME_HEADER_STRUCT.unpack_from(buffer, 0)
        total_packet_len = int(fields[2])
        if not FRAME_HEADER_SIZE <= total_packet_len <= MAX_PACKET_SIZE:
            _debug(debug, f"invalid totalPacketLen={total_packet_len}; resynchronizing")
            del buffer[0]
            continue

        if len(buffer) < total_packet_len:
            return

        packet = bytes(buffer[:total_packet_len])
        del buffer[:total_packet_len]
        try:
            header = parse_frame_header(packet)
            windows = extract_vital_phase_bin_window_tlvs(packet)
            fixed_samples = extract_vital_phase_tlvs(packet)
        except ValueError as exc:
            _debug(debug, f"packet parse error: {exc}")
            continue

        if not windows:
            _debug(
                debug,
                f"frame {header.frame_number}: no TLV 0xFE02 "
                f"(numTLVs={header.num_tlvs})",
            )
        yield header, windows, fixed_samples


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read AWR1642 real-I/Q VitalPhaseBinWindow TLV 0xFE02."
    )
    parser.add_argument("--data-com", required=True, help="Data UART, for example COM8.")
    parser.add_argument("--baud", type=int, default=921600, help="Data UART baud rate.")
    parser.add_argument("--duration", type=float, default=None, help="Optional run time in seconds.")
    parser.add_argument("--out", type=Path, default=None, help="Optional CSV output folder.")
    parser.add_argument("--debug", action="store_true", help="Print packet diagnostics.")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.baud <= 0:
        raise ValueError("--baud must be positive")
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration must be positive")

    try:
        import serial  # type: ignore
    except ImportError:
        print(
            "pyserial is required. Install it with: python -m pip install pyserial",
            file=sys.stderr,
        )
        return 2

    csv_file = None
    csv_writer = None
    csv_path = None
    if args.out:
        out_dir = args.out.expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "vital_phase_bin_window_samples.csv"
        csv_file = csv_path.open("w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        csv_writer.writeheader()

    buffer = bytearray()
    start = time.monotonic()
    window_count = 0
    sample_count = 0
    print(
        f"Opening data port {args.data_com} at {args.baud}. "
        "Waiting for TLV 0xFE02...",
        flush=True,
    )

    try:
        with serial.Serial(args.data_com, args.baud, timeout=0.25) as data_port:
            while args.duration is None or time.monotonic() - start < args.duration:
                waiting = int(getattr(data_port, "in_waiting", 0))
                chunk = data_port.read(min(max(waiting, 1), 65536))
                if not chunk:
                    continue
                buffer.extend(chunk)

                for header, windows, fixed_samples in _extract_complete_frames(
                    buffer, args.debug
                ):
                    fixed_suffix = ""
                    if fixed_samples:
                        fixed = fixed_samples[0]
                        fixed_suffix = (
                            f" fixedBin={fixed.range_bin_index_phase}"
                            f" fixedPhase={fixed.phase_rad:.6f}"
                        )

                    for window in windows:
                        window_count += 1
                        strongest = max(
                            window.samples, key=lambda sample: sample.magnitude
                        )
                        print(
                            f"frameNumber={window.frame_number} "
                            f"startBin={window.start_bin} "
                            f"numBins={window.num_bins} "
                            f"strongestBin={strongest.bin_index} "
                            f"strongestRange={strongest.range_meters:.4f} "
                            f"strongestMagnitude={strongest.magnitude:.3f}"
                            f"{fixed_suffix}",
                            flush=True,
                        )

                        if csv_writer is not None:
                            timestamp = datetime.now(timezone.utc).isoformat()
                            for sample in window.samples:
                                csv_writer.writerow(
                                    {
                                        "timestamp": timestamp,
                                        "frameNumber": window.frame_number,
                                        "binIndex": sample.bin_index,
                                        "rangeMeters": sample.range_meters,
                                        "iValue": sample.i_value,
                                        "qValue": sample.q_value,
                                        "phaseRad": sample.phase_rad,
                                        "magnitude": sample.magnitude,
                                    }
                                )
                                sample_count += 1
                            csv_file.flush()
                        else:
                            sample_count += len(window.samples)

                    if not windows:
                        _debug(
                            args.debug,
                            f"frame {header.frame_number} contained no bin window",
                        )
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    except (serial.SerialException, OSError) as exc:
        print(f"Data port failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if csv_file is not None:
            csv_file.close()

    elapsed = time.monotonic() - start
    print(
        f"Complete: windows={window_count} samples={sample_count} "
        f"elapsed={elapsed:.2f}s",
        flush=True,
    )
    if csv_path is not None:
        print(f"CSV saved: {csv_path}", flush=True)
    return 0


def main() -> int:
    args = _build_arg_parser().parse_args()
    try:
        return run(args)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
