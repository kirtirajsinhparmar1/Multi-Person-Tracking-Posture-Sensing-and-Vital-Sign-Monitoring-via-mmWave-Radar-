"""Read the custom AWR1642 VitalPhaseTrace TLV from a live data UART."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
PHASE_DIR = THIS_DIR.parent
for path in (THIS_DIR, PHASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from phase_vitals_estimator import estimate_vitals_from_phase  # noqa: E402
from ti_uart_packet_parser import (  # noqa: E402
    FRAME_HEADER_SIZE,
    FRAME_HEADER_STRUCT,
    MAGIC_WORD,
    extract_vital_phase_tlvs,
    find_magic_word,
    parse_frame_header,
)


MAX_PACKET_SIZE = 1024 * 1024
CSV_COLUMNS = (
    "sampleIndex",
    "elapsedSeconds",
    "frameNumber",
    "rangeBinIndexMax",
    "rangeBinIndexPhase",
    "rangeMeters",
    "iValue",
    "qValue",
    "phaseRad",
    "magnitude",
    "snrLike",
    "motionDetected",
)


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}", flush=True)


def _estimate_to_dict(estimates) -> dict:
    return {
        "breathingRateEst_FFT": estimates.breathing_rate_fft_bpm,
        "breathingEst_xCorr": estimates.breathing_rate_xcorr_bpm,
        "breathingEst_peakCount": estimates.breathing_rate_peak_count_bpm,
        "heartRateEst_FFT": estimates.heart_rate_fft_bpm,
        "heartRateEst_FFT_4Hz": estimates.heart_rate_fft_4hz_bpm,
        "heartRateEst_xCorr": estimates.heart_rate_xcorr_bpm,
        "heartRateEst_peakCount": estimates.heart_rate_peak_count_bpm,
        "confidenceMetricBreathOut": estimates.confidence_breath,
        "confidenceMetricHeartOut": estimates.confidence_heart,
        "sumEnergyBreathWfm": estimates.breath_energy,
        "sumEnergyHeartWfm": estimates.heart_energy,
        "motionDetectedFlag": int(estimates.motion_detected),
        "quality_state": estimates.quality_state,
        "notes": estimates.notes,
    }


def _format_bpm(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _print_estimate(sample_count: int, estimates) -> None:
    print(
        "estimate "
        f"samples={sample_count} "
        f"breathing={_format_bpm(estimates.breathing_rate_fft_bpm)} bpm "
        f"heart={_format_bpm(estimates.heart_rate_fft_bpm)} bpm "
        f"quality={estimates.quality_state}",
        flush=True,
    )


def _extract_complete_records(buffer: bytearray, debug: bool) -> Iterable:
    """Consume complete TI packets and yield their VitalPhaseTrace records."""
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
            records = extract_vital_phase_tlvs(packet)
        except ValueError as exc:
            _debug(debug, f"packet parse error: {exc}")
            continue

        if not records:
            _debug(
                debug,
                f"frame {header.frame_number}: no TLV 0xFE01 "
                f"(numTLVs={header.num_tlvs})",
            )
        yield from records


def _sample_row(sample, sample_index: int, elapsed_seconds: float) -> dict:
    return {
        "sampleIndex": sample_index,
        "elapsedSeconds": f"{elapsed_seconds:.6f}",
        "frameNumber": sample.frame_number,
        "rangeBinIndexMax": sample.range_bin_index_max,
        "rangeBinIndexPhase": sample.range_bin_index_phase,
        "rangeMeters": sample.range_meters,
        "iValue": sample.i_value,
        "qValue": sample.q_value,
        "phaseRad": sample.phase_rad,
        "magnitude": sample.magnitude,
        "snrLike": sample.snr_like,
        "motionDetected": sample.motion_detected,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read AWR1642 fake VitalPhaseTrace TLV 0xFE01 from the data UART."
    )
    parser.add_argument("--data-com", required=True, help="Data UART port, for example COM5.")
    parser.add_argument("--baud", type=int, default=921600, help="Data UART baud rate.")
    parser.add_argument("--duration", type=float, default=None, help="Optional run time in seconds.")
    parser.add_argument("--fs", type=float, default=20.0, help="Expected sample rate in Hz.")
    parser.add_argument("--out", type=Path, default=None, help="Optional output folder.")
    parser.add_argument(
        "--print-every",
        type=int,
        default=20,
        help="Run and print the estimator every N parsed samples.",
    )
    parser.add_argument("--debug", action="store_true", help="Print framing diagnostics.")
    parser.add_argument("--no-estimator", action="store_true", help="Disable vital estimation.")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.baud <= 0:
        raise ValueError("--baud must be positive")
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration must be positive")
    if args.fs <= 0:
        raise ValueError("--fs must be positive")
    if args.print_every <= 0:
        raise ValueError("--print-every must be positive")

    try:
        import serial  # type: ignore
    except ImportError:
        print(
            "pyserial is required. Install it with: python -m pip install pyserial",
            file=sys.stderr,
        )
        return 2

    out_dir = args.out.expanduser().resolve() if args.out else None
    csv_file = None
    csv_writer = None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_file = (out_dir / "vital_phase_samples.csv").open(
            "w", newline="", encoding="utf-8"
        )
        csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        csv_writer.writeheader()

    samples = []
    final_estimates = None
    buffer = bytearray()
    start = time.monotonic()
    minimum_estimator_samples = int(math.ceil(args.fs * 10.0))

    print(
        f"Opening data port {args.data_com} at {args.baud}. "
        "Waiting for VitalPhaseTrace TLV 0xFE01...",
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

                for sample in _extract_complete_records(buffer, args.debug):
                    samples.append(sample)
                    sample_count = len(samples)
                    elapsed = time.monotonic() - start
                    print(
                        f"frameNumber={sample.frame_number} "
                        f"phaseRad={sample.phase_rad:.6f} "
                        f"rangeMeters={sample.range_meters:.4f} "
                        f"magnitude={sample.magnitude:.3f} "
                        f"motionDetected={sample.motion_detected}",
                        flush=True,
                    )

                    if csv_writer is not None:
                        csv_writer.writerow(_sample_row(sample, sample_count, elapsed))
                        csv_file.flush()

                    should_estimate = (
                        not args.no_estimator
                        and sample_count >= minimum_estimator_samples
                        and sample_count % args.print_every == 0
                    )
                    if should_estimate:
                        phase = np.asarray(
                            [record.phase_rad for record in samples], dtype=float
                        )
                        final_estimates = estimate_vitals_from_phase(phase, args.fs)
                        _print_estimate(sample_count, final_estimates)
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    except (serial.SerialException, OSError) as exc:
        print(f"Data port failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if csv_file is not None:
            csv_file.close()

    if (
        not args.no_estimator
        and len(samples) >= minimum_estimator_samples
        and (
            final_estimates is None
            or len(samples) % args.print_every != 0
        )
    ):
        phase = np.asarray([record.phase_rad for record in samples], dtype=float)
        final_estimates = estimate_vitals_from_phase(phase, args.fs)
        _print_estimate(len(samples), final_estimates)

    elapsed = time.monotonic() - start
    print(f"Complete: samples={len(samples)} elapsed={elapsed:.2f}s", flush=True)

    if out_dir:
        result = {
            "dataCom": args.data_com,
            "baud": args.baud,
            "fs": args.fs,
            "elapsedSeconds": elapsed,
            "samples": len(samples),
            "tlvId": "0xFE01",
            "estimatorEnabled": not args.no_estimator,
            "estimates": (
                _estimate_to_dict(final_estimates) if final_estimates is not None else None
            ),
        }
        estimates_path = out_dir / "final_estimates.json"
        estimates_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"CSV saved: {out_dir / 'vital_phase_samples.csv'}", flush=True)
        print(f"Estimates saved: {estimates_path}", flush=True)

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
