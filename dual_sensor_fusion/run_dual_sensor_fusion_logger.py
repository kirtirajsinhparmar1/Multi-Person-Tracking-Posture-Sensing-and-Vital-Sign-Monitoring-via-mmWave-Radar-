"""Run headless IWR6843 + AWR1642 fusion and calibration logging."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import math
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
REPO_ROOT = PROJECT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dual_sensor_fusion.awr_bin_selector import SelectorConfig
from dual_sensor_fusion.beam_lock import BeamLockConfig
from awr1642_vitals.phase_vitals.azimuth_beamforming import BeamformingConfig
from dual_sensor_fusion.chest_point_estimator import ChestEstimatorConfig
from dual_sensor_fusion.coordinate_transform import TransformConfig
from dual_sensor_fusion.dual_sensor_logger import (
    DualSensorCsvLogger,
    Fe03LivenessTracker,
    FusionConfig,
    FusionEngine,
    PrimaryTargetTracker,
    convert_awr_virtual_ant_window,
    convert_awr_window,
    extract_iwr_targets,
    make_status_fused,
)
from dual_sensor_fusion.posture_gate import SittingGateConfig
from dual_sensor_fusion.nearby_beam_combiner import NearbyBeamCombinerConfig
from dual_sensor_fusion.vital_estimator_bridge import VitalEstimatorConfig


DEFAULT_IWR_CFG = (
    REPO_ROOT
    / "source"
    / "ti"
    / "examples"
    / "Industrial_and_Personal_Electronics"
    / "People_Tracking"
    / "3D_People_Tracking"
    / "chirp_configs"
    / "ODS_6m_default.cfg"
)
DEFAULT_AWR_CFG = (
    PROJECT_DIR
    / "awr1642_vitals"
    / "firmware_experiments"
    / "nonos_oob_16xx_vital_phase"
    / "chirp_config"
    / "profile_2d.cfg"
)
DEFAULT_POSE_MODEL = (
    PROJECT_DIR
    / "model_experiments"
    / "outputs"
    / "ti_4class_clean_recording_robust_1600_fast"
    / "ti_pose_model.onnx"
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fuse IWR6843 chest/posture with AWR1642 FE03 azimuth "
            "beamforming and FE02 fallback."
        )
    )
    parser.add_argument("--iwr-cli", default="COM7")
    parser.add_argument("--iwr-data", default="COM6")
    parser.add_argument("--iwr-cfg", default=str(DEFAULT_IWR_CFG))
    parser.add_argument("--awr-cli", default="COM9")
    parser.add_argument("--awr-data", default="COM8")
    parser.add_argument("--awr-cfg", default=str(DEFAULT_AWR_CFG))
    parser.add_argument("--out", default=str(PROJECT_DIR / "logs" / "dual_sensor_fusion_test"))
    parser.add_argument("--duration", type=float, default=90.0)
    parser.add_argument("--fs", type=float, default=10.0)
    parser.add_argument("--search-half-width", type=int, default=4)
    parser.add_argument("--azimuth-search-half-width-deg", type=float, default=20.0)
    parser.add_argument("--angle-min-deg", type=float, default=-60.0)
    parser.add_argument("--angle-max-deg", type=float, default=60.0)
    parser.add_argument("--angle-step-deg", type=float, default=2.0)
    parser.add_argument("--antenna-spacing-lambda", type=float, default=0.5)
    parser.add_argument(
        "--beam-window-type",
        choices=("none", "hann"),
        default="none",
    )
    parser.add_argument("--dx", type=float, default=0.0)
    parser.add_argument("--dy", type=float, default=0.0)
    parser.add_argument("--dz", type=float, default=0.0)
    parser.add_argument("--yaw-offset-deg", type=float, default=0.0)
    parser.add_argument(
        "--use-iwr-range-direct",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--use-chest-targeting",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Use the posture-aware chest range/azimuth for FE03 beam selection "
            "and FE02 range fallback (default: enabled)."
        ),
    )
    parser.add_argument(
        "--disable-chest-targeting",
        action="store_false",
        dest="use_chest_targeting",
        help="Use the legacy target-center/range selection path.",
    )
    parser.add_argument("--chest-sitting-height", type=float, default=0.85)
    parser.add_argument("--chest-standing-height", type=float, default=1.35)
    parser.add_argument("--sensor-dx", type=float, default=None)
    parser.add_argument("--sensor-dy", type=float, default=None)
    parser.add_argument("--sensor-dz", type=float, default=None)
    parser.add_argument("--sensor-yaw-deg", type=float, default=None)
    parser.add_argument("--sensor-pitch-deg", type=float, default=0.0)
    parser.add_argument("--sensor-roll-deg", type=float, default=0.0)
    parser.add_argument(
        "--awr-chest-height-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use AWR horizontal range + azimuth only; elevation is physically constrained.",
    )
    parser.add_argument(
        "--ignore-iwr-elevation-for-awr",
        "--awr-use-range-azimuth-only",
        action="store_true",
        dest="awr_chest_height_mode",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--sitting-stable-frames", type=int, default=10)
    parser.add_argument("--non-sitting-grace-sec", type=float, default=3.0)
    parser.add_argument("--max-grace-speed-mps", type=float, default=0.25)
    parser.add_argument("--sitting-lock-sec", type=float, default=5.0)
    parser.add_argument(
        "--allow-standing-grace",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--disable-pose-grace",
        action="store_false",
        dest="pose_grace_enabled",
        help="Restore strict posture gating with no transient-label grace.",
    )
    parser.set_defaults(pose_grace_enabled=True)
    parser.add_argument(
        "--hard-pause-on-falling",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--hard-pause-on-lying",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--primary-target-id", type=int, default=None)
    parser.add_argument("--pose-model", default=str(DEFAULT_POSE_MODEL))
    parser.add_argument("--iwr-cli-baud", type=int, default=115200)
    parser.add_argument("--iwr-data-baud", type=int, default=921600)
    parser.add_argument("--awr-cli-baud", type=int, default=115200)
    parser.add_argument("--awr-data-baud", type=int, default=921600)
    parser.add_argument("--max-awr-age", type=float, default=1.0)
    parser.add_argument("--fe03-stale-timeout-sec", type=float, default=2.0)
    parser.add_argument("--vital-display-hold-sec", type=float, default=10.0)
    parser.add_argument("--min-estimation-window-sec", type=float, default=30.0)
    parser.add_argument("--min-vital-window-sec", type=float, default=30.0)
    parser.add_argument("--min-heart-window-sec", type=float, default=30.0)
    parser.add_argument("--heart-stable-window-sec", type=float, default=60.0)
    parser.add_argument("--breath-stable-window-sec", type=float, default=30.0)
    parser.add_argument("--bpm-smoothing-sec", type=float, default=10.0)
    parser.add_argument(
        "--breath-max-jump-bpm-per-sec", type=float, default=3.0
    )
    parser.add_argument(
        "--heart-max-jump-bpm-per-sec", type=float, default=10.0
    )
    parser.add_argument("--heart-top-k-peaks", type=int, default=5)
    parser.add_argument("--heart-peak-persistence-sec", type=float, default=8.0)
    parser.add_argument("--heart-switch-confirm-sec", type=float, default=8.0)
    parser.add_argument("--heart-switch-margin", type=float, default=1.35)
    parser.add_argument("--heart-min-snr", type=float, default=3.0)
    parser.add_argument("--heart-min-confidence", type=float, default=0.35)
    parser.add_argument("--heart-window-sec", type=float, default=60.0)
    parser.add_argument("--heart-preliminary-window-sec", type=float, default=30.0)
    parser.add_argument("--breath-window-sec", type=float, default=30.0)
    parser.add_argument("--vital-model-dir")
    parser.add_argument(
        "--enable-vital-ml",
        dest="enable_vital_ml",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--disable-vital-ml",
        dest="enable_vital_ml",
        action="store_false",
    )
    parser.add_argument("--ml-min-window-sec", type=float, default=30.0)
    parser.add_argument("--phase-plot-window-sec", type=float, default=120.0)
    parser.add_argument("--phase-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument(
        "--phase-unwrap-discontinuity-rad",
        type=float,
        default=math.pi,
    )
    parser.add_argument("--phase-gap-reset-sec", type=float, default=1.0)
    parser.add_argument(
        "--phase-reset-on-beam-switch",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--beam-hysteresis-ratio", type=float, default=1.15)
    parser.add_argument("--beam-lock-sec", type=float, default=2.0)
    parser.add_argument("--beam-hold-sec", type=float, default=3.0)
    parser.add_argument("--beam-switch-margin", type=float, default=1.5)
    parser.add_argument("--beam-switch-confirm-sec", type=float, default=2.0)
    parser.add_argument("--beam-max-jump-bins", type=int, default=1)
    parser.add_argument("--beam-max-jump-deg", type=float, default=6.0)
    parser.add_argument("--disable-beam-lock", action="store_true")
    parser.add_argument(
        "--beam-switch-hold-sec",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--carrier-frequency-ghz", type=float, default=77.0)
    parser.add_argument(
        "--phase-chart-mode",
        choices=("displacement", "phase"),
        default="displacement",
    )
    parser.add_argument("--phase-smooth-sec", type=float, default=0.5)
    parser.add_argument("--phase-detrend-sec", type=float, default=20.0)
    parser.add_argument(
        "--enable-nearby-beam-combining",
        action="store_true",
        help=(
            "Optionally phase-align and combine stable FE03 cells near the "
            "locked beam; classical single-beam estimation remains the default."
        ),
    )
    parser.add_argument(
        "--nearby-beam-range-radius-bins", type=int, default=1
    )
    parser.add_argument(
        "--nearby-beam-azimuth-radius-deg", type=float, default=6.0
    )
    parser.add_argument(
        "--beam-combine-mode",
        choices=("best", "weighted", "coherent"),
        default="weighted",
    )
    parser.add_argument(
        "--beam-score-mode",
        choices=("magnitude", "magnitude_roi_stability"),
        default="magnitude_roi_stability",
    )
    parser.add_argument("--debug", action="store_true")
    return parser


def _add_vendor_paths() -> None:
    vendor = PROJECT_DIR / "ti_style_vendor"
    paths = [
        vendor,
        vendor / "common",
        vendor / "Industrial_Visualizer",
        vendor / "common" / "Common_Tabs",
        vendor / "common" / "Demo_Classes",
        vendor / "common" / "Demo_Classes" / "Helper_Classes",
    ]
    for path in reversed(paths):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _put_latest(destination: queue.Queue, item: Any) -> None:
    try:
        destination.put_nowait(item)
    except queue.Full:
        try:
            destination.get_nowait()
        except queue.Empty:
            pass
        destination.put_nowait(item)


def _iwr_worker(
    args: argparse.Namespace,
    destination: queue.Queue,
    stop_event: threading.Event,
) -> None:
    pose_manager = None
    try:
        _add_vendor_paths()
        import serial
        from cli_sender import send_config
        from demo_defines import DEMO_3D_PEOPLE_TRACKING
        from gui_parser import UARTParser
        from pose_model_runtime import prewarm_onnxruntime
        from ti_style_pose_overlay import TiStylePoseManager

        prewarm_onnxruntime(args.debug)
        pose_manager = TiStylePoseManager(
            model_path=Path(args.pose_model).expanduser().resolve(),
            min_associated_points_for_inference=1,
            allow_target_only=True,
            enable_3d_labels=False,
            debug=args.debug,
        )
        parser = UARTParser(type="DoubleCOMPort")
        parser.cfg = str(Path(args.iwr_cfg).expanduser().resolve())
        parser.device = "xWR6843"

        with serial.Serial(
            args.iwr_data,
            args.iwr_data_baud,
            timeout=0.6,
        ) as data_port:
            data_port.reset_input_buffer()
            parser.dataCom = data_port
            send_config(
                cli_port=args.iwr_cli,
                cli_baud=args.iwr_cli_baud,
                cfg_path=args.iwr_cfg,
                output=print if args.debug else None,
            )
            while not stop_event.is_set():
                output = parser.readAndParseUartDoubleCOMPort(
                    DEMO_3D_PEOPLE_TRACKING
                )
                timestamp = time.time()
                pose_results = pose_manager.process_output_dict(output)
                targets = extract_iwr_targets(output, pose_results, timestamp)
                _put_latest(destination, ("targets", timestamp, targets))
    except Exception as exc:
        _put_latest(destination, ("error", time.time(), f"IWR reader: {exc}"))
    finally:
        if pose_manager is not None:
            pose_manager.close()


def _awr_worker(
    args: argparse.Namespace,
    destination: queue.Queue,
    stop_event: threading.Event,
) -> None:
    try:
        import serial
        from cli_sender import send_config
        from awr1642_vitals.phase_vitals.tlv_parser.run_live_vital_phase_virtual_ant_window_reader import (
            _extract_complete_frames,
        )

        buffer = bytearray()
        with serial.Serial(
            args.awr_data,
            args.awr_data_baud,
            timeout=0.25,
        ) as data_port:
            data_port.reset_input_buffer()
            send_config(
                cli_port=args.awr_cli,
                cli_baud=args.awr_cli_baud,
                cfg_path=args.awr_cfg,
                output=print if args.debug else None,
            )
            while not stop_event.is_set():
                waiting = int(getattr(data_port, "in_waiting", 0))
                chunk = data_port.read(min(max(waiting, 1), 65536))
                if not chunk:
                    continue
                buffer.extend(chunk)
                for _header, virtual_windows, windows, _fixed in _extract_complete_frames(
                    buffer, args.debug
                ):
                    timestamp = time.time()
                    for parsed_window in virtual_windows:
                        _put_latest(
                            destination,
                            (
                                "virtual_ant_window",
                                timestamp,
                                convert_awr_virtual_ant_window(
                                    parsed_window,
                                    timestamp,
                                ),
                            ),
                        )
                    for parsed_window in windows:
                        _put_latest(
                            destination,
                            (
                                "window",
                                timestamp,
                                convert_awr_window(parsed_window, timestamp),
                            ),
                        )
    except Exception as exc:
        _put_latest(destination, ("error", time.time(), f"AWR reader: {exc}"))


def _format_rate(value: float | None) -> str:
    return "--" if value is None or not math.isfinite(value) else f"{value:.1f}"


def _print_fused(fused) -> None:
    print(
        "target={} posture={} state={} iwrRange={} expectedBin={} "
        "selectedBin={} selectedRange={} expectedAz={} selectedAz={} "
        "el={} mode={} fe03={} mag={} "
        "breath={} heart={} quality={} graceRemaining={}".format(
            fused.targetId,
            fused.posture,
            fused.monitoringState,
            "--" if fused.iwrRangeMeters is None else f"{fused.iwrRangeMeters:.2f}",
            fused.expectedAwrBin,
            fused.selectedAwrBin,
            (
                "--"
                if fused.selectedAwrRangeMeters is None
                else f"{fused.selectedAwrRangeMeters:.3f}"
            ),
            (
                "--"
                if fused.expectedAwrAzimuthDeg is None
                else f"{fused.expectedAwrAzimuthDeg:.1f}"
            ),
            (
                "--"
                if fused.selectedAwrAzimuthDeg is None
                else f"{fused.selectedAwrAzimuthDeg:.1f}"
            ),
            (
                "--"
                if fused.expectedAwrElevationDeg is None
                else f"{fused.expectedAwrElevationDeg:.1f}"
            ),
            fused.selectionMode,
            fused.fe03Status,
            "--" if fused.selectedMagnitude is None else f"{fused.selectedMagnitude:.0f}",
            _format_rate(fused.breathingBpm),
            _format_rate(fused.heartBpm),
            fused.quality,
            f"{fused.graceRemainingSec:.1f}s" if fused.poseGraceActive else "--",
        ),
        flush=True,
    )


def run(args: argparse.Namespace) -> int:
    if args.duration <= 0:
        raise ValueError("--duration must be positive")
    if args.fs <= 0:
        raise ValueError("--fs must be positive")
    if args.non_sitting_grace_sec < 0:
        raise ValueError("--non-sitting-grace-sec must be non-negative")
    if args.sitting_lock_sec < 0:
        raise ValueError("--sitting-lock-sec must be non-negative")
    if args.max_grace_speed_mps < 0:
        raise ValueError("--max-grace-speed-mps must be non-negative")
    if args.fe03_stale_timeout_sec < 0:
        raise ValueError("--fe03-stale-timeout-sec must be non-negative")
    for option, value in (
        ("--vital-display-hold-sec", args.vital_display_hold_sec),
        ("--min-estimation-window-sec", args.min_estimation_window_sec),
        ("--min-vital-window-sec", args.min_vital_window_sec),
        ("--min-heart-window-sec", args.min_heart_window_sec),
        ("--heart-stable-window-sec", args.heart_stable_window_sec),
        ("--breath-stable-window-sec", args.breath_stable_window_sec),
        ("--bpm-smoothing-sec", args.bpm_smoothing_sec),
        (
            "--breath-max-jump-bpm-per-sec",
            args.breath_max_jump_bpm_per_sec,
        ),
        ("--heart-max-jump-bpm-per-sec", args.heart_max_jump_bpm_per_sec),
        ("--heart-peak-persistence-sec", args.heart_peak_persistence_sec),
        ("--heart-switch-confirm-sec", args.heart_switch_confirm_sec),
        ("--heart-switch-margin", args.heart_switch_margin),
        ("--heart-min-snr", args.heart_min_snr),
        ("--heart-min-confidence", args.heart_min_confidence),
        ("--heart-window-sec", args.heart_window_sec),
        ("--heart-preliminary-window-sec", args.heart_preliminary_window_sec),
        ("--breath-window-sec", args.breath_window_sec),
        ("--ml-min-window-sec", args.ml_min_window_sec),
        ("--phase-plot-window-sec", args.phase_plot_window_sec),
        (
            "--phase-unwrap-discontinuity-rad",
            args.phase_unwrap_discontinuity_rad,
        ),
        ("--phase-gap-reset-sec", args.phase_gap_reset_sec),
        ("--beam-switch-hold-sec", args.beam_switch_hold_sec),
        (
            "--nearby-beam-range-radius-bins",
            args.nearby_beam_range_radius_bins,
        ),
        (
            "--nearby-beam-azimuth-radius-deg",
            args.nearby_beam_azimuth_radius_deg,
        ),
    ):
        if value is None:
            continue
        if value < 0:
            raise ValueError(f"{option} must be non-negative")
    if args.phase_unwrap_discontinuity_rad == 0:
        raise ValueError("--phase-unwrap-discontinuity-rad must be positive")
    if args.heart_top_k_peaks < 1:
        raise ValueError("--heart-top-k-peaks must be at least 1")

    transform = TransformConfig(
        dx=args.dx if args.sensor_dx is None else args.sensor_dx,
        dy=args.dy if args.sensor_dy is None else args.sensor_dy,
        dz=args.dz if args.sensor_dz is None else args.sensor_dz,
        yawOffsetDeg=args.yaw_offset_deg,
        yawDeg=args.sensor_yaw_deg,
        pitchDeg=args.sensor_pitch_deg,
        rollDeg=args.sensor_roll_deg,
        useIwrRangeDirect=args.use_iwr_range_direct,
        awrChestHeightMode=args.awr_chest_height_mode,
    )
    fusion_config = FusionConfig(
        transform=transform,
        selector=SelectorConfig(searchHalfWidth=args.search_half_width),
        gate=SittingGateConfig(
            requiredStableFrames=args.sitting_stable_frames,
            nonSittingGraceSec=args.non_sitting_grace_sec,
            sittingLockSec=args.sitting_lock_sec,
            updateRateHz=args.fs,
            maxGraceSpeedMps=args.max_grace_speed_mps,
            allowStandingGrace=args.allow_standing_grace,
            enablePoseGrace=args.pose_grace_enabled,
            pauseImmediatelyOnFalling=args.hard_pause_on_falling,
            pauseImmediatelyOnLying=args.hard_pause_on_lying,
        ),
        estimator=VitalEstimatorConfig(
            fs=args.fs,
            displayHoldSec=args.vital_display_hold_sec,
            minEstimationWindowSec=args.min_estimation_window_sec,
            minVitalWindowSec=args.min_vital_window_sec,
            minHeartWindowSec=args.min_heart_window_sec,
            breathStableWindowSec=args.breath_stable_window_sec,
            heartStableWindowSec=args.heart_stable_window_sec,
            bpmSmoothingSec=args.bpm_smoothing_sec,
            breathMaxJumpBpmPerSec=args.breath_max_jump_bpm_per_sec,
            heartMaxJumpBpmPerSec=args.heart_max_jump_bpm_per_sec,
            heartTopKPeaks=args.heart_top_k_peaks,
            heartPeakPersistenceSec=args.heart_peak_persistence_sec,
            heartSwitchConfirmSec=args.heart_switch_confirm_sec,
            heartSwitchMargin=args.heart_switch_margin,
            heartMinSnr=args.heart_min_snr,
            heartMinConfidence=args.heart_min_confidence,
            heartWindowSec=args.heart_window_sec,
            heartPreliminaryWindowSec=args.heart_preliminary_window_sec,
            breathWindowSec=args.breath_window_sec,
            phasePlotWindowSec=args.phase_plot_window_sec,
            phaseSign=args.phase_sign,
            phaseUnwrapDiscontinuityRad=args.phase_unwrap_discontinuity_rad,
            phaseGapResetSec=args.phase_gap_reset_sec,
            phaseResetOnBeamSwitch=args.phase_reset_on_beam_switch,
            carrierFrequencyGhz=args.carrier_frequency_ghz,
            enableVitalMl=args.enable_vital_ml,
            vitalModelDir=args.vital_model_dir,
            mlMinWindowSec=args.ml_min_window_sec,
        ),
        chest=ChestEstimatorConfig(
            sittingChestHeightM=args.chest_sitting_height,
            standingChestHeightM=args.chest_standing_height,
        ),
        useChestTargeting=args.use_chest_targeting,
        beamforming=BeamformingConfig(
            angleMinDeg=args.angle_min_deg,
            angleMaxDeg=args.angle_max_deg,
            angleStepDeg=args.angle_step_deg,
            antennaSpacingLambda=args.antenna_spacing_lambda,
            windowType=args.beam_window_type,
            hysteresisStrengthRatio=args.beam_hysteresis_ratio,
            scoreMode=args.beam_score_mode,
        ),
        azimuthSearchHalfWidthDeg=args.azimuth_search_half_width_deg,
        beamLock=BeamLockConfig(
            lockSec=args.beam_lock_sec,
            holdSec=(
                args.beam_switch_hold_sec
                if args.beam_switch_hold_sec is not None
                else args.beam_hold_sec
            ),
            switchMargin=args.beam_switch_margin,
            switchConfirmSec=args.beam_switch_confirm_sec,
            maxJumpBins=args.beam_max_jump_bins,
            maxJumpDeg=args.beam_max_jump_deg,
            enabled=not args.disable_beam_lock,
        ),
        nearbyBeamCombiner=NearbyBeamCombinerConfig(
            enabled=args.enable_nearby_beam_combining,
            rangeRadiusBins=args.nearby_beam_range_radius_bins,
            azimuthRadiusDeg=args.nearby_beam_azimuth_radius_deg,
            mode=args.beam_combine_mode,
        ),
        carrierFrequencyGhz=args.carrier_frequency_ghz,
    )
    engine = FusionEngine(fusion_config)
    primary = PrimaryTargetTracker(args.primary_target_id)
    run_config = vars(args).copy()
    run_config["fusionConfig"] = asdict(fusion_config)
    logger = DualSensorCsvLogger(args.out, run_config)

    iwr_queue: queue.Queue = queue.Queue(maxsize=8)
    awr_queue: queue.Queue = queue.Queue(maxsize=16)
    stop_event = threading.Event()
    threads = [
        threading.Thread(
            target=_iwr_worker,
            args=(args, iwr_queue, stop_event),
            name="iwr-reader",
            daemon=True,
        ),
        threading.Thread(
            target=_awr_worker,
            args=(args, awr_queue, stop_event),
            name="awr-reader",
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    latest_awr = None
    latest_awr_time = 0.0
    fe03_tracker = Fe03LivenessTracker(args.fe03_stale_timeout_sec)
    last_print = 0.0
    start = time.monotonic()
    error: str | None = None
    try:
        while time.monotonic() - start < args.duration:
            while True:
                try:
                    kind, timestamp, payload = awr_queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "error":
                    error = str(payload)
                    break
                if kind == "virtual_ant_window":
                    fe03_tracker.update(payload, timestamp)
                    logger.log_awr_virtual_ant_window(payload)
                else:
                    latest_awr = payload
                    latest_awr_time = timestamp
                    logger.log_awr_window(latest_awr)
            if error:
                break

            try:
                kind, timestamp, payload = iwr_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == "error":
                error = str(payload)
                break

            targets = payload
            logger.log_iwr_targets(targets)
            target = primary.select(targets)
            if target is None:
                missing_id = primary.current_target_id
                state = "TARGET_LOST" if missing_id is not None else "NO_TARGET"
                status = make_status_fused(
                    state,
                    timestamp=timestamp,
                    target_id=missing_id,
                    reason="no primary IWR target in current frame",
                )
                logger.log_fused(status, None)
                if args.debug and time.monotonic() - last_print >= 1.0:
                    print(f"state={state}", flush=True)
                    last_print = time.monotonic()
                continue

            current_awr = latest_awr
            if current_awr and timestamp - latest_awr_time > args.max_awr_age:
                current_awr = None
            fe03 = fe03_tracker.status(timestamp)
            fused, selection = engine.process(
                target,
                current_awr,
                timestamp,
                awr_virtual_ant_window=fe03.window,
                fe03_age_sec=fe03.ageSec,
                latest_fe03_frame_number=fe03.frameNumber,
                fe03_frames_per_second=fe03.framesPerSecond,
                fe03_stream_state=fe03.streamState,
                fe03_frame_count=fe03.frameCount,
                latest_fe03_payload_ok=fe03.payloadOk,
                latest_fe03_parse_error=fe03.parseError,
            )
            logger.log_fused(fused, selection)
            if engine.latest_beam_selection is not None:
                logger.log_beam_selection(fused, engine.latest_beam_selection)
            logger.log_phase_diagnostics(
                fused,
                engine.phase_diagnostics(target.targetId, timestamp),
            )
            if time.monotonic() - last_print >= 1.0:
                _print_fused(fused)
                last_print = time.monotonic()
    except KeyboardInterrupt:
        print("Stopped by user.", flush=True)
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=1.5)
        logger.close({"runtimeError": error})

    if error:
        print(error, file=sys.stderr)
        return 1
    print(f"Fusion logs saved under: {Path(args.out).expanduser().resolve()}")
    return 0


def main() -> int:
    args = build_arg_parser().parse_args()
    try:
        return run(args)
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
