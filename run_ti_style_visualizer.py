"""Launch the vendored TI Industrial Visualizer in People Tracking mode.

This file intentionally keeps the visualization path TI-owned: it imports the
vendored TI `gui_core.Window`, selects xWR6843 / 3D People Tracking, and calls
the same connect/config callbacks that the TI buttons use.
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parent
VENDOR_ROOT = PROJECT_DIR / "ti_style_vendor"
VENDOR_COMMON = VENDOR_ROOT / "common"
VENDOR_INDUSTRIAL = VENDOR_ROOT / "Industrial_Visualizer"
DEFAULT_CFG = (
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
DEFAULT_POSE_MODEL = (
    PROJECT_DIR
    / "model_experiments"
    / "outputs"
    / "ti_4class_clean_recording_robust_1600_fast"
    / "ti_pose_model.onnx"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the vendored TI Industrial Visualizer People Tracking UI."
    )
    parser.add_argument("--cli", default="COM7", help="CLI/config COM port.")
    parser.add_argument("--data", default="COM6", help="Data COM port.")
    parser.add_argument("--cfg", default=str(DEFAULT_CFG), help="Path to .cfg file.")
    parser.add_argument(
        "--out",
        default=str(PROJECT_DIR / "logs" / "ti_style_ui_test1"),
        help="Output directory reserved for logs/saved TI data.",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Only prefill the TI UI; do not open COM ports or send the cfg.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print vendored paths, defaults, parser frames, and plot update calls.",
    )
    parser.add_argument(
        "--disable-gl-text",
        dest="disable_gl_text",
        action="store_true",
        default=None,
        help="Disable TI GLTextItem labels. Defaults on when the PySide6 shim is used.",
    )
    parser.add_argument(
        "--enable-gl-text",
        dest="disable_gl_text",
        action="store_false",
        help="Try TI GLTextItem labels even when the PySide6 shim is used.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Launch UI without hardware auto-start. Synthetic frames are not implemented.",
    )
    parser.add_argument(
        "--enable-pose",
        action="store_true",
        help="Enable live ONNX pose classification per tracker TID.",
    )
    parser.add_argument(
        "--pose-model",
        default=str(DEFAULT_POSE_MODEL),
        help="Path to TI Pose/Fall ONNX model.",
    )
    parser.add_argument(
        "--pose-smoothing-window",
        type=int,
        default=7,
        help="Number of recent probability vectors to average per TID.",
    )
    parser.add_argument(
        "--pose-min-confidence",
        type=float,
        default=0.55,
        help="Minimum smoothed confidence before quality is marked LOW_CONF.",
    )
    parser.add_argument(
        "--pose-unknown-confidence",
        type=float,
        default=0.45,
        help="Smoothed confidence below this becomes UNKNOWN in the final pose label.",
    )
    parser.add_argument(
        "--pose-moving-speed-threshold",
        type=float,
        default=0.18,
        help="Horizontal speed threshold in m/s for derived MOVING state.",
    )
    parser.add_argument(
        "--pose-moving-confirm-frames",
        type=int,
        default=4,
        help="Consecutive frames above speed threshold before final label becomes MOVING.",
    )
    parser.add_argument(
        "--pose-fall-height-drop-threshold",
        type=float,
        default=0.35,
        help="Recent z-height drop threshold in meters for FALLING safety override.",
    )
    parser.add_argument(
        "--pose-fall-vertical-speed-threshold",
        type=float,
        default=0.35,
        help="Vertical speed threshold in m/s used to allow FALLING display.",
    )
    parser.add_argument(
        "--pose-fall-high-confidence",
        type=float,
        default=0.85,
        help="High ML confidence threshold used with mild height drop for FALLING.",
    )
    parser.add_argument(
        "--pose-fall-min-height-drop-with-high-confidence",
        type=float,
        default=0.20,
        help="Minimum height drop required when FALLING is accepted by high confidence.",
    )
    parser.add_argument(
        "--pose-min-associated-points-for-inference",
        type=int,
        default=1,
        help="Minimum associated points needed to add a frame to the pose window.",
    )
    parser.add_argument(
        "--pose-allow-target-only",
        action="store_true",
        help="Allow pose inference with zero associated points by zero-padding point slots.",
    )
    parser.add_argument(
        "--pose-3d-labels",
        action="store_true",
        help="Show per-TID posture labels above tracked targets in the 3D plot.",
    )
    parser.add_argument(
        "--pose-3d-label-format",
        default="{tid} | {final_label} {confidence_percent}%",
        help="Format string for 3D pose labels.",
    )
    parser.add_argument(
        "--pose-3d-label-z-offset",
        type=float,
        default=0.35,
        help="Meters to place the 3D pose label above the target/height box.",
    )
    parser.add_argument(
        "--pose-3d-label-min-confidence",
        type=float,
        default=0.45,
        help="Compatibility option; pose labels still show available predictions.",
    )
    parser.add_argument(
        "--pose-3d-label-max-distance",
        type=float,
        default=None,
        help="Optional maximum 3D distance in meters for showing pose labels.",
    )
    parser.add_argument(
        "--pose-3d-label-debug",
        action="store_true",
        help="Show warmup/extra confidence detail in 3D pose labels.",
    )
    parser.add_argument(
        "--pose-debug",
        action="store_true",
        help="Print pose classification status every 30 frames.",
    )
    parser.add_argument(
        "--pose-log",
        action="store_true",
        help="Write pose_predictions_ui.csv and pose_ui_metadata.json under --out.",
    )
    parser.add_argument(
        "--allow-missing-scaler",
        action="store_true",
        help="Allow a normalized pose model to run without scaler files. Debug use only.",
    )
    parser.add_argument(
        "--pose-human-models",
        action="store_true",
        help="Draw simple 3D human posture OBJ models for tracked people.",
    )
    parser.add_argument(
        "--pose-human-model-dir",
        default="ui_human_pose_models",
        help="Directory containing human_standing.obj, human_sitting.obj, and human_lying.obj.",
    )
    parser.add_argument(
        "--pose-human-model-mode",
        choices=["replace_box", "overlay_box", "model_only"],
        default="overlay_box",
        help="How human models relate to TI target boxes.",
    )
    parser.add_argument(
        "--pose-human-model-scale",
        type=float,
        default=1.0,
        help="Global scale multiplier for human posture models.",
    )
    parser.add_argument(
        "--pose-human-model-target-height",
        type=float,
        default=1.70,
        help="Standing/MOVING model target height in meters before global scale.",
    )
    parser.add_argument(
        "--pose-human-model-target-sitting-height",
        type=float,
        default=1.20,
        help="Sitting model target height in meters before global scale.",
    )
    parser.add_argument(
        "--pose-human-model-target-lying-length",
        type=float,
        default=1.70,
        help="Lying/FALLING model target body length in meters before global scale.",
    )
    parser.add_argument(
        "--pose-human-model-height-scale",
        default="auto",
        help="Use 'auto' for per-pose physical scaling, or provide an extra numeric multiplier.",
    )
    parser.add_argument(
        "--pose-human-model-debug",
        action="store_true",
        help="Print per-frame human model placement details.",
    )
    parser.add_argument(
        "--pose-human-model-opacity",
        type=float,
        default=1.0,
        help="Human model opacity from 0.0 to 1.0.",
    )
    parser.add_argument(
        "--pose-human-model-fallback",
        choices=["box", "standing", "none"],
        default="box",
        help="Fallback for unknown/warmup labels or model-load failure.",
    )
    parser.add_argument(
        "--pose-ground-z",
        type=float,
        default=0.0,
        help="World Z coordinate of the floor/ground used to anchor human models.",
    )
    parser.add_argument(
        "--pose-ground-plane",
        action="store_true",
        help="Draw a subtle ground plane/floor at --pose-ground-z.",
    )
    parser.add_argument(
        "--pose-ground-plane-size",
        type=float,
        default=8.0,
        help="Ground plane size in meters.",
    )
    parser.add_argument(
        "--no-pose-ground-plane-grid",
        dest="pose_ground_plane_grid",
        action="store_false",
        default=True,
        help="Disable the grid overlay on the pose ground plane.",
    )
    parser.add_argument(
        "--pose-ground-plane-alpha",
        type=float,
        default=0.18,
        help="Ground plane opacity from 0.0 to 1.0.",
    )
    parser.add_argument(
        "--pose-display-stability-frames",
        type=int,
        default=16,
        help="Frames used for display-only pose stability/hysteresis.",
    )
    parser.add_argument(
        "--pose-display-min-confidence",
        type=float,
        default=0.55,
        help="Minimum confidence for a candidate pose to become the stable displayed pose.",
    )
    parser.add_argument(
        "--no-pose-display-hysteresis",
        dest="pose_display_hysteresis",
        action="store_false",
        default=True,
        help="Disable display-only pose hysteresis.",
    )
    parser.add_argument(
        "--pose-display-stability-ratio",
        type=float,
        default=0.70,
        help="Majority ratio required over the display-stability window.",
    )
    parser.add_argument(
        "--no-pose-falling-fast-update",
        dest="pose_falling_fast_update",
        action="store_false",
        default=True,
        help="Disable the shorter display threshold for high-confidence FALLING.",
    )
    parser.add_argument(
        "--pose-fall-stability-frames",
        "--pose-falling-stability-frames",
        dest="pose_fall_stability_frames",
        type=int,
        default=6,
        help="Display-stability frames required for high-confidence FALLING.",
    )
    parser.add_argument(
        "--pose-sitting-stability-frames",
        type=int,
        default=8,
        help="Display-stability frames required for SITTING.",
    )
    parser.add_argument(
        "--pose-sitting-stability-ratio",
        type=float,
        default=0.50,
        help="Majority ratio required for SITTING display updates.",
    )
    parser.add_argument(
        "--pose-sitting-min-confidence",
        type=float,
        default=0.40,
        help="Minimum confidence for SITTING display updates.",
    )
    parser.add_argument(
        "--pose-sitting-max-speed",
        type=float,
        default=0.25,
        help="Maximum horizontal speed in m/s for accepting SITTING.",
    )
    parser.add_argument(
        "--pose-standing-min-confidence",
        type=float,
        default=0.50,
        help="Minimum confidence for STANDING display updates.",
    )
    parser.add_argument(
        "--pose-lying-min-confidence",
        type=float,
        default=0.50,
        help="Minimum confidence for LYING display updates.",
    )
    parser.add_argument(
        "--vitals-enable-gate",
        action="store_true",
        help="Enable posture-gated vital-sign eligibility per tracked TID.",
    )
    parser.add_argument(
        "--vitals-required-posture",
        default="SITTING",
        help="Displayed posture required before vital monitoring is eligible.",
    )
    parser.add_argument(
        "--vitals-sitting-stable-frames",
        type=int,
        default=30,
        help="Continuous eligible sitting frames required before vitals activate.",
    )
    parser.add_argument(
        "--vitals-max-horizontal-speed",
        type=float,
        default=0.08,
        help="Maximum horizontal speed in m/s for vital-sign eligibility.",
    )
    parser.add_argument(
        "--vitals-min-pose-confidence",
        type=float,
        default=0.60,
        help="Minimum displayed-pose confidence for vital-sign eligibility.",
    )
    parser.add_argument(
        "--vitals-grace-frames",
        type=int,
        default=15,
        help="Frames tolerated before an eligible TID is reset or paused.",
    )
    parser.add_argument(
        "--vitals-reset-when-not-sitting",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reset sitting eligibility after the grace period when posture/speed is invalid.",
    )
    parser.add_argument(
        "--vitals-labels",
        action="store_true",
        help="Append compact vital eligibility or real vital rates to 3D labels.",
    )
    parser.add_argument(
        "--vitals-log",
        action="store_true",
        help="Add vital eligibility and real TLV measurements to pose_predictions_ui.csv.",
    )
    return parser.parse_args()


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[ti-style-debug] {message}", flush=True)


def add_import_paths(debug: bool) -> list[Path]:
    paths = [
        VENDOR_ROOT,
        VENDOR_COMMON,
        VENDOR_INDUSTRIAL,
        VENDOR_COMMON / "Common_Tabs",
        VENDOR_COMMON / "Demo_Classes",
        VENDOR_COMMON / "Demo_Classes" / "Helper_Classes",
    ]
    added: list[Path] = []
    for path in reversed(paths):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            added.append(path)
    for path in added:
        debug_print(debug, f"sys.path added: {path}")
    return added


def check_pyside2_shim(debug: bool) -> bool:
    try:
        import PySide2
        from PySide2 import QtCore
        from PySide6 import __version__ as pyside6_version
    except ModuleNotFoundError as exc:
        missing_name = exc.name or ""
        if missing_name.startswith("PySide6"):
            raise SystemExit(
                "PySide6 is required for the local PySide2 compatibility shim. "
                "Install it with: python -m pip install -r requirements_ti_style.txt"
            ) from exc
        raise

    print(f"PySide2 compatibility shim resolved to PySide6 {pyside6_version}", flush=True)
    pyside2_path = Path(PySide2.__file__).resolve()
    qtcore_path = Path(QtCore.__file__).resolve()
    debug_print(debug, f"PySide2 shim package: {pyside2_path}")
    debug_print(debug, f"PySide2.QtCore shim: {qtcore_path}")
    return VENDOR_ROOT in pyside2_path.parents


def configure_gl_text(args: argparse.Namespace, using_pyside2_shim: bool, debug: bool) -> bool:
    disable_gl_text = args.disable_gl_text
    if disable_gl_text is None:
        disable_gl_text = using_pyside2_shim

    os.environ["TI_STYLE_DISABLE_GL_TEXT"] = "1" if disable_gl_text else "0"
    if disable_gl_text:
        debug_print(debug, "GL text labels disabled for PySide6 compatibility.")
    else:
        debug_print(debug, "GL text labels enabled.")
    return disable_gl_text


def safe_len(obj) -> int:
    if obj is None:
        return 0
    try:
        return len(obj)
    except Exception:
        return 0


def ensure_vendor_runtime_dirs() -> None:
    (VENDOR_INDUSTRIAL / "cache").mkdir(parents=True, exist_ok=True)
    (VENDOR_INDUSTRIAL / "binData").mkdir(parents=True, exist_ok=True)


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_DIR / path).resolve()


def normalize_windows_com(value: str) -> str:
    text = value.strip()
    if os.name == "nt" and text.upper().startswith("COM"):
        return text[3:]
    return text


def set_combo_text(combo, text: str) -> bool:
    index = combo.findText(text)
    if index >= 0:
        combo.setCurrentIndex(index)
        return True
    return False


def configure_business_demo_list() -> None:
    from demo_defines import BUSINESS_DEMOS, DEVICE_DEMO_DICT

    for device_name in DEVICE_DEMO_DICT:
        DEVICE_DEMO_DICT[device_name]["demos"] = [
            demo
            for demo in DEVICE_DEMO_DICT[device_name]["demos"]
            if demo in BUSINESS_DEMOS["Industrial"]
        ]


def install_debug_hooks(debug: bool, gl_text_disabled: bool) -> None:
    if not debug:
        return

    from Common_Tabs.plot_3d import Plot3D
    from Demo_Classes.people_tracking import PeopleTracking
    from gui_parser import UARTParser
    from gui_threads import updateQTTargetThread3D

    original_send_cfg = UARTParser.sendCfg
    original_read_double = UARTParser.readAndParseUartDoubleCOMPort
    original_update_graph = PeopleTracking.updateGraph
    original_update_point_cloud = Plot3D.updatePointCloud
    original_run = updateQTTargetThread3D.run

    def visual_status(self, output_dict):
        if not isinstance(output_dict, dict):
            return
        frame_num = output_dict.get("frameNum")
        try:
            should_log = int(frame_num) % 30 == 0
        except Exception:
            should_log = False
        if not should_log:
            return

        points = safe_len(output_dict.get("pointCloud"))
        targets = safe_len(output_dict.get("trackData"))
        heights = safe_len(output_dict.get("heightData"))
        point_item = "yes" if getattr(self, "scatter", None) is not None else "no"
        target_markers = "yes" if safe_len(getattr(self, "ellipsoids", None)) else "no"
        boxes = "yes" if (
            safe_len(getattr(self, "boundaryBoxList", None))
            or safe_len(getattr(self, "boundaryBoxViz", None))
        ) else "no"
        gl_text = "disabled" if gl_text_disabled else "enabled"
        print(
            "[ti-style-debug] visual status "
            f"frame={frame_num} points={points} targets={targets} heights={heights} "
            f"pointItem={point_item} targetMarkers={target_markers} boxes={boxes} "
            f"glText={gl_text}",
            flush=True,
        )

    def send_cfg_debug(self, cfg):
        print(f"[ti-style-debug] UARTParser.sendCfg lines={len(cfg)}", flush=True)
        result = original_send_cfg(self, cfg)
        print(
            f"[ti-style-debug] UARTParser.sendCfg complete comError={self.comError}",
            flush=True,
        )
        return result

    def read_double_debug(self, demo):
        output = original_read_double(self, demo)
        frame = output[0] if isinstance(output, tuple) else output
        if isinstance(frame, dict):
            points = safe_len(frame.get("pointCloud"))
            targets = safe_len(frame.get("trackData"))
            heights = safe_len(frame.get("heightData"))
            print(
                "[ti-style-debug] frame "
                f"num={frame.get('frameNum', 'n/a')} points={points} "
                f"targets={targets} heights={heights}",
                flush=True,
            )
        return output

    def update_graph_debug(self, output_dict):
        points = safe_len(output_dict.get("pointCloud")) if isinstance(output_dict, dict) else 0
        targets = safe_len(output_dict.get("trackData")) if isinstance(output_dict, dict) else 0
        print(
            f"[ti-style-debug] PeopleTracking.updateGraph points={points} targets={targets}",
            flush=True,
        )
        result = original_update_graph(self, output_dict)
        visual_status(self, output_dict)
        return result

    def update_point_cloud_debug(self, output_dict):
        points = safe_len(output_dict.get("pointCloud")) if isinstance(output_dict, dict) else 0
        print(f"[ti-style-debug] Plot3D.updatePointCloud points={points}", flush=True)
        return original_update_point_cloud(self, output_dict)

    def run_debug(self):
        points = safe_len(getattr(self, "pointCloud", None))
        targets = safe_len(getattr(self, "targets", None))
        heights = safe_len(getattr(self, "heightData", None))
        print(
            "[ti-style-debug] updateQTTargetThread3D.run "
            f"points={points} targets={targets} heights={heights}",
            flush=True,
        )
        return original_run(self)

    UARTParser.sendCfg = send_cfg_debug
    UARTParser.readAndParseUartDoubleCOMPort = read_double_debug
    PeopleTracking.updateGraph = update_graph_debug
    Plot3D.updatePointCloud = update_point_cloud_debug
    updateQTTargetThread3D.run = run_debug


def import_ti_qt():
    from PySide2.QtCore import QTimer
    from PySide2.QtGui import QColor, QPalette
    from PySide2.QtWidgets import QApplication

    from demo_defines import DEMO_3D_PEOPLE_TRACKING
    from gui_core import Window

    return QApplication, QTimer, QPalette, QColor, Window, DEMO_3D_PEOPLE_TRACKING


def apply_ti_dark_palette(app, QPalette, QColor) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)


def configure_window(window, args: argparse.Namespace, demo_name: str, debug: bool) -> None:
    cfg_path = resolve_project_path(args.cfg)
    out_dir = resolve_project_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    set_combo_text(window.deviceList, "xWR6843")
    window.onChangeDevice()
    set_combo_text(window.demoList, demo_name)
    window.onChangeDemo()

    window.cliCom.setText(normalize_windows_com(args.cli))
    window.dataCom.setText(normalize_windows_com(args.data))
    window.filename_edit.setText(str(cfg_path))
    window.core.parser.filepath = out_dir.name
    window.core.parseCfg(str(cfg_path))

    debug_print(debug, f"CLI port default: {args.cli}")
    debug_print(debug, f"Data port default: {args.data}")
    debug_print(debug, f"Cfg path: {cfg_path}")
    debug_print(debug, f"Output directory: {out_dir}")
    debug_print(debug, f"Selected device: {window.core.device}")
    debug_print(debug, f"Selected demo: {window.core.demo}")
    debug_print(debug, f"Selected demo class: {type(window.core.demoClassDict[window.core.demo]).__name__}")


def create_pose_manager_before_qt(args: argparse.Namespace, debug: bool):
    if not args.enable_pose:
        debug_print(debug, "pose model disabled")
        return None

    model_path = resolve_project_path(args.pose_model)
    out_dir = resolve_project_path(args.out)
    pose_debug = args.pose_debug or debug
    if pose_debug:
        print(f"[pose-runtime] resolved model path: {model_path}", flush=True)

    try:
        from pose_model_runtime import prewarm_onnxruntime

        prewarm_onnxruntime(pose_debug)
        from ti_style_pose_overlay import TiStylePoseManager

        pose_manager = TiStylePoseManager(
            model_path=model_path,
            smoothing_window=args.pose_smoothing_window,
            min_confidence=args.pose_min_confidence,
            unknown_confidence=args.pose_unknown_confidence,
            moving_speed_threshold=args.pose_moving_speed_threshold,
            moving_confirm_frames=args.pose_moving_confirm_frames,
            fall_height_drop_threshold=args.pose_fall_height_drop_threshold,
            fall_vertical_speed_threshold=args.pose_fall_vertical_speed_threshold,
            fall_high_confidence=args.pose_fall_high_confidence,
            fall_min_height_drop_with_high_confidence=(
                args.pose_fall_min_height_drop_with_high_confidence
            ),
            min_associated_points_for_inference=(
                args.pose_min_associated_points_for_inference
            ),
            allow_target_only=args.pose_allow_target_only,
            enable_3d_labels=args.pose_3d_labels,
            label_format=args.pose_3d_label_format,
            label_z_offset=args.pose_3d_label_z_offset,
            label_min_confidence=args.pose_3d_label_min_confidence,
            label_max_distance=args.pose_3d_label_max_distance,
            label_debug=args.pose_3d_label_debug,
            enable_human_models=args.pose_human_models,
            human_model_debug=args.pose_human_model_debug,
            display_stability_frames=args.pose_display_stability_frames,
            display_min_confidence=args.pose_display_min_confidence,
            display_hysteresis=args.pose_display_hysteresis,
            display_stability_ratio=args.pose_display_stability_ratio,
            falling_fast_update=args.pose_falling_fast_update,
            fall_stability_frames=args.pose_fall_stability_frames,
            sitting_stability_frames=args.pose_sitting_stability_frames,
            sitting_stability_ratio=args.pose_sitting_stability_ratio,
            sitting_min_confidence=args.pose_sitting_min_confidence,
            sitting_max_speed=args.pose_sitting_max_speed,
            standing_min_confidence=args.pose_standing_min_confidence,
            lying_min_confidence=args.pose_lying_min_confidence,
            ground_z=args.pose_ground_z,
            human_model_target_height=args.pose_human_model_target_height,
            human_model_target_sitting_height=args.pose_human_model_target_sitting_height,
            human_model_target_lying_length=args.pose_human_model_target_lying_length,
            vitals_enable_gate=args.vitals_enable_gate,
            vitals_required_posture=args.vitals_required_posture,
            vitals_sitting_stable_frames=args.vitals_sitting_stable_frames,
            vitals_max_horizontal_speed=args.vitals_max_horizontal_speed,
            vitals_min_pose_confidence=args.vitals_min_pose_confidence,
            vitals_grace_frames=args.vitals_grace_frames,
            vitals_reset_when_not_sitting=args.vitals_reset_when_not_sitting,
            vitals_labels=args.vitals_labels,
            debug=pose_debug,
            log_dir=out_dir if (args.pose_log or args.vitals_log) else None,
            cfg_path=resolve_project_path(args.cfg),
            cli_port=args.cli,
            data_port=args.data,
            allow_missing_scaler=args.allow_missing_scaler,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        message = str(exc)
        if getattr(exc, "name", "") == "onnxruntime":
            message = (
                "onnxruntime is required for --enable-pose. "
                "Install it with: python -m pip install onnxruntime"
            )
        else:
            message = (
                "ONNX Runtime failed to import inside the TI-style UI process. "
                "Standalone import may work, but Qt/PySide DLL load order can break it. "
                "This launcher now preloads ONNX Runtime before Qt; if it still fails, "
                "reinstall onnxruntime or use a torch fallback. "
                f"Original exception: {exc}"
            )
        raise SystemExit(message) from exc

    debug_print(pose_debug, f"pose model loaded before Qt: {model_path}")
    if args.pose_log or args.vitals_log:
        debug_print(pose_debug, f"pose logging directory: {out_dir}")
    return pose_manager


def attach_pose_manager(window, pose_manager, args: argparse.Namespace, debug: bool):
    if pose_manager is None:
        return None

    demo_instance = window.core.demoClassDict.get(window.core.demo)
    if demo_instance is None or not hasattr(demo_instance, "setPoseManager"):
        raise RuntimeError("Selected TI demo class does not support pose manager attachment")

    demo_instance.setPoseManager(pose_manager)
    if args.pose_human_models:
        try:
            from human_model_renderer import HumanPoseModelRenderer

            renderer = HumanPoseModelRenderer(
                getattr(demo_instance, "plot_3d"),
                model_dir=resolve_project_path(args.pose_human_model_dir),
                scale=args.pose_human_model_scale,
                height_scale=args.pose_human_model_height_scale,
                target_height=args.pose_human_model_target_height,
                target_sitting_height=args.pose_human_model_target_sitting_height,
                target_lying_length=args.pose_human_model_target_lying_length,
                ground_z=args.pose_ground_z,
                opacity=args.pose_human_model_opacity,
                fallback=args.pose_human_model_fallback,
                debug=args.pose_human_model_debug or debug,
            )
            demo_instance.setPoseHumanModelRenderer(
                renderer,
                mode=args.pose_human_model_mode,
            )
            debug_print(
                debug or args.pose_human_model_debug,
                f"human posture models attached: {resolve_project_path(args.pose_human_model_dir)}",
            )
        except Exception as exc:
            print(
                f"[human-model] disabled; keeping TI target boxes. Reason: {exc}",
                flush=True,
            )
    if args.pose_ground_plane and hasattr(demo_instance, "setPoseGroundPlane"):
        demo_instance.setPoseGroundPlane(
            enabled=True,
            ground_z=args.pose_ground_z,
            size=args.pose_ground_plane_size,
            grid=args.pose_ground_plane_grid,
            alpha=args.pose_ground_plane_alpha,
        )
        debug_print(
            debug or args.pose_debug,
            "[ground-plane] enabled z={} size={}".format(
                args.pose_ground_z,
                args.pose_ground_plane_size,
            ),
        )
    atexit.register(pose_manager.close)
    debug_print(debug or getattr(pose_manager, "debug", False), "[pose-runtime] pose manager attached")
    debug_print(debug or getattr(pose_manager, "debug", False), f"pose manager attached to: {type(demo_instance).__name__}")
    return pose_manager


def auto_start(window, debug: bool) -> None:
    debug_print(debug, "auto-start: connecting COM ports via TI Window.onConnect()")
    window.onConnect()
    connected = window.connectStatus.text() == "Connected"
    debug_print(debug, f"auto-start: connectStatus={window.connectStatus.text()}")
    if not connected:
        debug_print(debug, "auto-start: config not sent because COM connection failed")
        return

    debug_print(debug, "auto-start: sending cfg via TI Window.sendCfg()")
    window.sendCfg()
    debug_print(debug, "auto-start: cfg send requested; TI parse timer should now be active")


def main() -> int:
    args = parse_args()
    pose_manager = create_pose_manager_before_qt(args, args.debug)
    add_import_paths(args.debug)
    using_pyside2_shim = check_pyside2_shim(args.debug)
    gl_text_disabled = configure_gl_text(args, using_pyside2_shim, args.debug)
    ensure_vendor_runtime_dirs()

    original_cwd = Path.cwd()
    os.chdir(VENDOR_INDUSTRIAL)
    debug_print(args.debug, f"cwd changed from {original_cwd} to {VENDOR_INDUSTRIAL}")

    configure_business_demo_list()
    install_debug_hooks(args.debug, gl_text_disabled)

    QApplication, QTimer, QPalette, QColor, Window, demo_name = import_ti_qt()
    app = QApplication(sys.argv[:1])
    apply_ti_dark_palette(app, QPalette, QColor)

    screen = app.primaryScreen()
    size = screen.size() if screen is not None else []
    window = Window(size=size, title="Industrial Visualizer - TI Style (Vendored)")
    configure_window(window, args, demo_name, args.debug)
    attach_pose_manager(window, pose_manager, args, args.debug)
    window.show()

    auto_start_enabled = not args.no_auto_start and not args.demo
    if auto_start_enabled:
        QTimer.singleShot(500, lambda: auto_start(window, args.debug))
    else:
        debug_print(args.debug, "auto-start disabled; use Connect then Start and Send Configuration")

    try:
        return app.exec_()
    finally:
        if pose_manager is not None:
            pose_manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
