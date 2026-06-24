"""Read AWR1642 FE03 virtual-antenna windows and beamform them on the PC."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Iterable

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
PHASE_VITALS_DIR = THIS_DIR.parent
for import_dir in (THIS_DIR, PHASE_VITALS_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from azimuth_beamforming import (  # noqa: E402
    BeamformingConfig,
    beamform_window,
    make_angle_grid,
    select_range_azimuth_cell,
)
from ti_uart_packet_parser import (  # noqa: E402
    FRAME_HEADER_SIZE,
    FRAME_HEADER_STRUCT,
    MAGIC_WORD,
    extract_vital_phase_bin_window_tlvs,
    extract_vital_phase_tlvs,
    extract_vital_phase_virtual_ant_window_tlvs,
    find_magic_word,
    parse_frame_header,
)


MAX_PACKET_SIZE = 1024 * 1024


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}", flush=True)


def _extract_complete_frames(
    buffer: bytearray,
    debug: bool,
) -> Iterable[tuple[object, list, list, list]]:
    """Yield header, FE03 windows, FE02 windows, and FE01 records."""
    while True:
        magic_index = find_magic_word(buffer)
        if magic_index < 0:
            keep = min(len(buffer), len(MAGIC_WORD) - 1)
            if len(buffer) > keep:
                del buffer[: len(buffer) - keep]
            return
        if magic_index:
            del buffer[:magic_index]
        if len(buffer) < FRAME_HEADER_SIZE:
            return

        fields = FRAME_HEADER_STRUCT.unpack_from(buffer, 0)
        total_packet_len = int(fields[2])
        if not FRAME_HEADER_SIZE <= total_packet_len <= MAX_PACKET_SIZE:
            _debug(debug, f"invalid totalPacketLen={total_packet_len}")
            del buffer[0]
            continue
        if len(buffer) < total_packet_len:
            return

        packet = bytes(buffer[:total_packet_len])
        del buffer[:total_packet_len]
        try:
            header = parse_frame_header(packet)
            fe03_windows = extract_vital_phase_virtual_ant_window_tlvs(packet)
            fe02_windows = extract_vital_phase_bin_window_tlvs(packet)
            fixed_samples = extract_vital_phase_tlvs(packet)
        except ValueError as exc:
            _debug(debug, f"packet parse error: {exc}")
            continue
        yield header, fe03_windows, fe02_windows, fixed_samples


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and azimuth-beamform AWR1642 FE03 virtual-antenna data."
    )
    parser.add_argument("--data-com", required=True)
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--expected-range", type=float, default=None)
    parser.add_argument("--expected-azimuth", type=float, default=None)
    parser.add_argument("--range-search-half-width", type=int, default=4)
    parser.add_argument("--azimuth-search-half-width-deg", type=float, default=15.0)
    parser.add_argument("--angle-min-deg", type=float, default=-60.0)
    parser.add_argument("--angle-max-deg", type=float, default=60.0)
    parser.add_argument("--angle-step-deg", type=float, default=2.0)
    parser.add_argument("--antenna-spacing-lambda", type=float, default=0.5)
    parser.add_argument("--window-type", choices=("none", "hann"), default="none")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.baud <= 0 or args.duration <= 0:
        raise ValueError("--baud and --duration must be positive")
    if (args.expected_range is None) != (args.expected_azimuth is None):
        raise ValueError(
            "--expected-range and --expected-azimuth must be supplied together"
        )

    try:
        import serial  # type: ignore
    except ImportError:
        print("pyserial is required: python -m pip install pyserial", file=sys.stderr)
        return 2

    config = BeamformingConfig(
        angleMinDeg=args.angle_min_deg,
        angleMaxDeg=args.angle_max_deg,
        angleStepDeg=args.angle_step_deg,
        antennaSpacingLambda=args.antenna_spacing_lambda,
        windowType=args.window_type,
    )
    angle_grid = make_angle_grid(config)
    writers = {}
    files = []
    out_dir = None
    if args.out:
        out_dir = args.out.expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        specs = {
            "samples": (
                "virtual_ant_window_samples.csv",
                (
                    "timestamp",
                    "frameNumber",
                    "binIndex",
                    "rangeMeters",
                    "virtualAntennaIndex",
                    "iValue",
                    "qValue",
                ),
            ),
            "beam": (
                "range_azimuth_beam_trace.csv",
                (
                    "timestamp",
                    "frameNumber",
                    "strongestRangeBin",
                    "strongestRangeMeters",
                    "strongestAzimuthDeg",
                    "strongestMagnitude",
                    "selectedRangeBin",
                    "selectedRangeMeters",
                    "selectedAzimuthDeg",
                    "selectedMagnitude",
                ),
            ),
            "phase": (
                "selected_beam_phase.csv",
                (
                    "timestamp",
                    "frameNumber",
                    "rangeBin",
                    "rangeMeters",
                    "azimuthDeg",
                    "phaseRad",
                    "magnitude",
                ),
            ),
        }
        for key, (name, columns) in specs.items():
            handle = (out_dir / name).open("w", newline="", encoding="utf-8")
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            files.append(handle)
            writers[key] = writer

    buffer = bytearray()
    start = time.monotonic()
    frame_count = 0
    previous_selection = None
    final_record = {}
    print(
        f"Opening data port {args.data_com} at {args.baud}; waiting for FE03...",
        flush=True,
    )
    try:
        with serial.Serial(args.data_com, args.baud, timeout=0.25) as data_port:
            while time.monotonic() - start < args.duration:
                waiting = int(getattr(data_port, "in_waiting", 0))
                chunk = data_port.read(min(max(waiting, 1), 65536))
                if not chunk:
                    continue
                buffer.extend(chunk)
                for _, windows, _, _ in _extract_complete_frames(buffer, args.debug):
                    for window in windows:
                        timestamp = datetime.now(timezone.utc).isoformat()
                        beam_map = beamform_window(window, angle_grid, config)
                        magnitude_map = np.abs(beam_map)
                        strongest_row, strongest_col = np.unravel_index(
                            int(np.argmax(magnitude_map)),
                            magnitude_map.shape,
                        )
                        selected = None
                        if args.expected_range is not None:
                            selected = select_range_azimuth_cell(
                                window,
                                args.expected_range,
                                args.expected_azimuth,
                                args.range_search_half_width,
                                args.azimuth_search_half_width_deg,
                                previous_selection,
                                config,
                            )
                            previous_selection = selected

                        strongest_bin = int(window.bin_indices[strongest_row])
                        strongest_range = float(window.range_meters[strongest_row])
                        strongest_angle = float(angle_grid[strongest_col])
                        strongest_magnitude = float(
                            magnitude_map[strongest_row, strongest_col]
                        )
                        suffix = ""
                        if selected is not None:
                            suffix = (
                                f" selectedBin={selected.selectedRangeBin}"
                                f" selectedRange={selected.selectedRangeMeters:.4f}"
                                f" selectedAzimuth={selected.selectedAzimuthDeg:.1f}"
                                f" selectedPhase={selected.selectedPhaseRad:.6f}"
                                f" selectedMagnitude={selected.selectedMagnitude:.1f}"
                            )
                        print(
                            f"frameNumber={window.frame_number} "
                            f"startBin={window.start_bin} numBins={window.num_bins} "
                            f"numVirtualAntennas={window.num_virtual_antennas} "
                            f"strongestBin={strongest_bin} "
                            f"strongestRange={strongest_range:.4f} "
                            f"strongestAzimuth={strongest_angle:.1f} "
                            f"strongestMagnitude={strongest_magnitude:.1f}{suffix}",
                            flush=True,
                        )
                        frame_count += 1
                        final_record = {
                            "frameNumber": window.frame_number,
                            "numVirtualAntennas": window.num_virtual_antennas,
                            "strongestRangeBin": strongest_bin,
                            "strongestRangeMeters": strongest_range,
                            "strongestAzimuthDeg": strongest_angle,
                            "strongestMagnitude": strongest_magnitude,
                            "selectedRangeBin": (
                                selected.selectedRangeBin if selected else None
                            ),
                            "selectedAzimuthDeg": (
                                selected.selectedAzimuthDeg if selected else None
                            ),
                            "selectedPhaseRad": (
                                selected.selectedPhaseRad if selected else None
                            ),
                        }

                        if writers:
                            for row, bin_index in enumerate(window.bin_indices):
                                for ant in range(window.num_virtual_antennas):
                                    value = complex(window.samples[row, ant])
                                    writers["samples"].writerow(
                                        {
                                            "timestamp": timestamp,
                                            "frameNumber": window.frame_number,
                                            "binIndex": int(bin_index),
                                            "rangeMeters": float(
                                                window.range_meters[row]
                                            ),
                                            "virtualAntennaIndex": ant,
                                            "iValue": value.real,
                                            "qValue": value.imag,
                                        }
                                    )
                            writers["beam"].writerow(
                                {
                                    "timestamp": timestamp,
                                    "frameNumber": window.frame_number,
                                    "strongestRangeBin": strongest_bin,
                                    "strongestRangeMeters": strongest_range,
                                    "strongestAzimuthDeg": strongest_angle,
                                    "strongestMagnitude": strongest_magnitude,
                                    "selectedRangeBin": (
                                        selected.selectedRangeBin
                                        if selected
                                        else ""
                                    ),
                                    "selectedRangeMeters": (
                                        selected.selectedRangeMeters
                                        if selected
                                        else ""
                                    ),
                                    "selectedAzimuthDeg": (
                                        selected.selectedAzimuthDeg
                                        if selected
                                        else ""
                                    ),
                                    "selectedMagnitude": (
                                        selected.selectedMagnitude
                                        if selected
                                        else ""
                                    ),
                                }
                            )
                            if selected is not None:
                                writers["phase"].writerow(
                                    {
                                        "timestamp": timestamp,
                                        "frameNumber": window.frame_number,
                                        "rangeBin": selected.selectedRangeBin,
                                        "rangeMeters": selected.selectedRangeMeters,
                                        "azimuthDeg": selected.selectedAzimuthDeg,
                                        "phaseRad": selected.selectedPhaseRad,
                                        "magnitude": selected.selectedMagnitude,
                                    }
                                )
                            for handle in files:
                                handle.flush()
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    except (serial.SerialException, OSError) as exc:
        print(f"Data port failed: {exc}", file=sys.stderr)
        return 1
    finally:
        for handle in files:
            handle.close()

    elapsed = time.monotonic() - start
    summary = {
        "frames": frame_count,
        "elapsedSec": elapsed,
        "beamformingAssumption": "ordered lambda/2 uniform linear array",
        "final": final_record,
    }
    if out_dir is not None:
        summary_path = out_dir / "final_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary saved: {summary_path}", flush=True)
    print(f"Complete: frames={frame_count} elapsed={elapsed:.2f}s", flush=True)
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
