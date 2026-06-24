# Full Project Context Audit

Audit date: June 20, 2026  
Repository root: `C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05`  
Project root: `custom_iwr6843_fall_logger`

## 1. Purpose and audit constraints

This document records the current state of the combined IWR6843ISK-ODS
tracking/posture system, AWR1642BOOST phase/vital-sign system, and the newer
dual-sensor fusion logger/UI.

The immediate issue is that the dual-sensor fusion UI no longer visibly shows
the posture-specific per-person 3D human meshes that were available in the
IWR-only visualizer.

This was a read-only audit:

- No COM port was opened.
- No board was flashed.
- No live hardware script was run.
- No source file was modified.
- Generated caches, logs, binaries, and large model files were not scanned
  except where a specific artifact or metadata file was needed to establish the
  current state.

## 2. Executive diagnosis

The initial diagnosis was close, but one important detail is different:

**The fusion UI does reuse the original TI `PeopleTracking` 3D widget. It does
not replace it with a completely separate simplified IWR plot.**

The regression is in feature activation:

- `run_dual_sensor_fusion_ui.py::_reflow_ti_window()` removes the existing
  `window.demoTabs` widget from the TI window's original grid and embeds that
  same widget in the fusion UI's left panel.
- The normal fusion run also creates and attaches the existing
  `TiStylePoseManager`, so posture inference and pose records remain available.
- However, `_make_ti_args()` enables pose inference and 3D text labels but does
  **not** pass `--pose-human-models` or `--pose-ground-plane`.
- `run_ti_style_visualizer.py::attach_pose_manager()` creates
  `HumanPoseModelRenderer` only when `args.pose_human_models` is true. It creates
  the ground plane only when `args.pose_ground_plane` is true.

Therefore:

1. Point cloud, target boxes, target identity, and posture inference can still
   work in the fusion UI.
2. 3D pose text labels can still work.
3. The posture-specific standing/sitting/lying human meshes and ground plane
   are never attached by the fusion launcher.
4. Demo mode has a second limitation: it injects `_fusionDemoPose` for fusion
   status, but deliberately uses no live `pose_manager`, so the vendor
   `PeopleTracking` update path cannot produce its normal mesh/label records.

The safest repair is not a renderer rewrite. It is to expose and propagate the
existing human-model options through the fusion UI, attach the existing
renderer to the already-embedded `PeopleTracking` widget, and add a
pose-manager-compatible demo injection path.

## 3. Relevant repository structure

### 3.1 Project-root applications and support modules

The following files under `custom_iwr6843_fall_logger` are directly relevant:

| File/folder | Purpose |
|---|---|
| `run_ti_style_visualizer.py` | Main TI-style IWR-only UI launcher. Owns CLI options, pre-Qt ONNX initialization, TI window startup, pose-manager attachment, human-model renderer attachment, ground-plane setup, and output interception. |
| `ti_style_pose_overlay.py` | Per-target pose inference orchestration, smoothing, physical gates, display stability, 3D label/model records, pose logs, and optional IWR-only vital gate integration. |
| `human_model_renderer.py` | Loads OBJ meshes and maintains one pyqtgraph OpenGL body mesh per target ID. |
| `pose_feature_extractor.py` | Builds the 22-feature frame and eight-frame/176-value pose model input. |
| `pose_model_runtime.py` | Loads ONNX/scaler metadata, performs inference, and smooths probability vectors by target ID. |
| `pose_data_logger.py` | Pose-related CSV/metadata logging support. |
| `frame_types.py` | Project-level parsed frame/data classes used by the older custom parser/UI path. |
| `parser.py`, `serial_reader.py` | Earlier/custom serial parsing and acquisition path, separate from the vendored TI-style parser. |
| `visualizer_app.py`, `visualizer_widgets.py`, `visualizer_worker.py`, `run_visualizer.py` | Earlier non-TI-style visualization application. These are not the primary current IWR UI used by the fusion launcher. |
| `fall_detector.py`, `run_fall_logger.py` | Earlier fall-detection/logging path. |
| `run_pose_capture.py` | Pose data collection/capture entry point. |
| `csv_logger.py` | General CSV logging support. |
| `cfg_parser.py`, `cli_sender.py`, `send_cfg.py` | Configuration parsing/sending utilities. `send_cfg.py` is used for AWR CLI configuration. |
| `vital_sign_gate.py`, `vital_signs_runtime.py` | Optional IWR-only vital-TLV gating/runtime. This is distinct from the AWR dual-sensor `posture_gate.py` and `vital_estimator_bridge.py`. |
| `inspect_vital_people_tracking_stream.py` | Stream inspection/debugging for the IWR people-tracking/vital combination. |
| `ui_human_pose_models/` | Standing, sitting, and lying OBJ/GLB assets plus README/license. |
| `ti_style_vendor/` | Local copy/adaptation of the TI visualizer framework and parser. |
| `model_experiments/` | Pose dataset preparation, training, comparison, export, metadata, and selected ONNX model. |
| `awr1642_vitals/` | AWR1642 phase/vital estimators, UART parsers, copied firmware experiment, and bring-up documentation. |
| `dual_sensor_fusion/` | New IWR+AWR fusion types, selection/gating/estimation logic, logger, UI, tests, and usage guide. |

### 3.2 TI-style visualizer implementation

The active visualizer code is under:

`custom_iwr6843_fall_logger\ti_style_vendor\common`

Important files:

| File | Role |
|---|---|
| `gui_core.py` | TI main-window/application wiring and demo selection. |
| `gui_parser.py` | `UARTParser`, double-COM parsing, byte acquisition, and standard frame dispatch. |
| `parseFrame.py` | `parseStandardFrame()` parses the TI frame header and dispatches TLVs. |
| `parseTLVs.py` | Point-cloud, target-list, target-index, height, and other TLV decoders. |
| `gui_threads.py` | Qt update threads, including `updateQTTargetThread3D`. |
| `Demo_Classes/people_tracking.py` | Active people-tracking demo, point cloud, target boxes, pose table, 3D labels, and human-model updates. |
| `Common_Tabs/plot_3d.py` | `Plot3D` OpenGL scene, grid, EVM, target boxes, 3D labels, human renderer attachment, and ground plane. |

### 3.3 Pose model experiments

`model_experiments` contains:

- `prepare_ti_pose_dataset.py`: builds model-ready TI-derived datasets.
- `ti_pose_feature_extractor.py`: experiment-side feature implementation.
- `train_or_export_ti_pose_model.py`: model training/export.
- `compare_pose_models.py`: comparison/evaluation.
- `audit_ti_pose_dataset.py`: dataset quality audit.
- `README_MODEL.md` and `TI_POSE_MODEL_REUSE_REPORT.md`: model documentation.
- `outputs\ti_4class_clean_recording_robust_1600_fast\ti_pose_model.onnx`:
  current selected model.
- `model_metadata.json`: confirms a 176-value channel-major input and four
  classes: `STANDING`, `SITTING`, `LYING`, `FALLING`.

The metadata explicitly says `WALKING` was removed from ML training. Live
walking/moving behavior is handled by velocity and motion rules. The recorded
held-out evaluation is approximately 97.76% accuracy and 0.977 macro F1, but
the metadata also warns that live IWR6843 validation is still required.

### 3.4 AWR1642 phase/vital system

`awr1642_vitals` contains:

- `phase_vitals\phase_vitals_estimator.py`: PC-side phase-to-breath/heart
  estimator.
- `phase_vitals\tlv_parser\`: custom FE01/FE02 payload parsers, TI packet
  parser, live readers, fake packet generator, and offline tests.
- `firmware_experiments\nonos_oob_16xx_vital_phase\`: copied AWR1642 non-OS
  firmware experiment. This is the only firmware source intended for custom
  modification.
- `firmware_experiments\built_bins\`: copied output binaries.
- `firmware_experiments\copy_latest_fake_vital_bin.ps1`: binary-copy helper.
- `AWR1642_VITAL_SIGNS_BRINGUP.md`: bring-up/status documentation.
- `external_research\`: third-party dataset/repository inventory.

### 3.5 Dual-sensor fusion system

`dual_sensor_fusion` contains:

- `fusion_types.py`
- `coordinate_transform.py`
- `awr_bin_selector.py`
- `posture_gate.py`
- `vital_estimator_bridge.py`
- `dual_sensor_logger.py`
- `run_dual_sensor_fusion_logger.py`
- `run_dual_sensor_fusion_ui.py`
- `test_dual_sensor_fusion.py`
- `DUAL_SENSOR_FUSION_USAGE.md`

These are described in detail in section 7.

### 3.6 Documentation already present

Relevant existing Markdown documents include:

- `README.md`
- `FIRMWARE_MERGE_AUDIT_3D_TRACKING_PLUS_VITALS.md`
- `VITAL_SIGNS_WITH_PEOPLE_TRACKING_COMPATIBILITY.md`
- `model_experiments\README_MODEL.md`
- `model_experiments\TI_POSE_MODEL_REUSE_REPORT.md`
- `dual_sensor_fusion\DUAL_SENSOR_FUSION_USAGE.md`
- `awr1642_vitals\AWR1642_VITAL_SIGNS_BRINGUP.md`
- `awr1642_vitals\phase_vitals\tlv_parser\LIVE_READER_USAGE.md`
- `awr1642_vitals\phase_vitals\tlv_parser\AWR1642_BIN_WINDOW_TLV_USAGE.md`
- firmware experiment build, patch, and real-phase audit notes.

The repository also contains existing user logs and generated outputs. They
were not generally inspected because they are runtime evidence, not source of
truth, and some are currently modified/untracked.

## 4. IWR6843ISK-ODS tracking and posture system

### 4.1 Known working hardware configuration

- Board: IWR6843ISK-ODS.
- CLI/config port: COM7.
- Data port: COM6.
- Working configuration:
  `C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg`
- No IWR firmware changes are required by the current fusion design.

Known IWR-only command:

```powershell
python run_ti_style_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs\ti_pose_ui_warmup_debug --enable-pose --pose-model "model_experiments\outputs\ti_4class_clean_recording_robust_1600_fast\ti_pose_model.onnx" --pose-log --pose-debug --pose-3d-labels --pose-3d-label-debug --pose-min-associated-points-for-inference 1 --pose-allow-target-only
```

Important qualification: this exact command explicitly enables 3D text labels,
but it does not contain `--pose-human-models` or `--pose-ground-plane`. Those
two features are opt-in in the current source. If meshes were visible in a
previous run, either additional flags were used, another wrapper supplied them,
or the command history differs from the command recorded above.

### 4.2 UART parser and decoded data

`ti_style_vendor\common\gui_parser.py`

- `UARTParser` begins near line 25.
- The people-tracking setup uses the double-COM path: CLI/config on one port,
  binary data on the other.
- Received frames are passed to
  `parseFrame.py::parseStandardFrame()` near line 104.

`parseStandardFrame()`:

- Validates/parses the TI frame header.
- Initializes the point-cloud matrix, including the per-point target-index
  column.
- Dispatches each TLV to a decoder in `parseTLVs.py`.
- Produces an `outputDict` consumed by the TI demo.

Important `parseTLVs.py` functions:

- Point-cloud decoders populate Cartesian `x`, `y`, `z`, Doppler, SNR, and
  noise fields.
- `parseTrackTLV()` near line 294 decodes the 3D target list into `trackData`.
- `parseTrackHeightTLV()` near line 362 decodes target-height records.
- Target-index TLVs associate points with tracks. Unassociated points use the
  TI convention (typically index 255).

Typical target rows include the target ID, position, velocity, acceleration,
and track covariance/state fields defined by the TI demo output.

### 4.3 Active tracking renderer

`ti_style_vendor\common\Demo_Classes\people_tracking.py`

- `PeopleTracking` begins near line 88 and inherits `Plot3D` and `Plot1D`.
- `setupGUI()` near line 108 creates the plot tabs and sidebar controls.
- `updateGraph()` near line 127 is the central frame-rendering method.

`updateGraph()`:

1. Processes pose results.
2. Updates the pose/status table.
3. Updates the point cloud.
4. Applies configured sensor rotation and height.
5. Handles target boxes, IDs, height information, and optional fall display.
6. Calls `updatePose3DLabels()`.
7. Calls `updatePoseHumanModels()`.
8. Starts `updateQTTargetThread3D`, which updates the OpenGL point cloud and
   track boxes without blocking the parser path.

There is specific handling for the xWR6843 delayed target-index behavior:
target associations can refer to the preceding target-list frame, so copied
track/point data must be handled carefully. The fusion UI also copies track
arrays before the vendor update mutates/transforms them.

### 4.4 Pose feature pipeline

`pose_feature_extractor.py` constructs a 22-value feature vector per frame:

- target `posZ`
- velocity X/Y/Z
- acceleration X/Y/Z
- for up to five highest-Z associated points:
  - relative Y
  - Z
  - SNR

Missing point slots are zero-padded. Point quality is considered weak when too
few points are associated. Eight frames are accumulated and flattened in
channel-major order to produce 176 model inputs.

`pose_model_runtime.py`:

- Loads the ONNX model and optional feature scaler.
- Uses `CPUExecutionProvider`.
- Prewarms ONNX before Qt initialization to avoid DLL/load-order problems.
- Reads class names from model metadata.
- Smooths class-probability vectors independently by target ID.

The current ONNX metadata defines:

```text
STANDING
SITTING
LYING
FALLING
```

`MOVING` is a display/runtime state, not an ONNX class in this model.

### 4.5 Pose manager, smoothing, and physical gates

`ti_style_pose_overlay.py::TiStylePoseManager` begins near line 33.

`process_output_dict()` near line 176:

- Accepts useful decoded fields even if the parser reports a nonzero error
  elsewhere in the frame.
- Reads `trackData`, `pointCloud`, and `heightData`.
- Computes target speed/motion and height-drop evidence.
- Associates points with each target.
- Maintains an eight-frame history by TID.
- Runs ONNX when the feature window and quality rules permit it.
- Smooths probabilities.
- Applies physical sitting/falling rules.
- Applies display hysteresis/stability.
- Stores latest records by target ID.

Key methods:

| Method | Approx. line | Role |
|---|---:|---|
| `get_3d_label_records()` | 419 | Converts per-TID pose results and current tracks into OpenGL text-label records. |
| `get_3d_model_records()` | 474 | Converts per-TID results into mesh records with position, posture, target height, and ground Z. |
| `_evaluate_sitting_gate()` | 713 | Combines smoothed pose confidence, sitting probability, and speed/stability. |
| `_evaluate_fall_gate()` | 736 | Requires physical evidence and protects slow/stable sitting from false FALLING. |
| `_final_label()` | 780 | Maps ML result plus motion/physical gates to final display label. |
| `_display_requirements()` | 825 | Selects label-specific confidence/stability requirements. |
| `_update_display_state()` | 856 | Per-target hysteresis; retains a previous stable label until a new label is stable. |
| `_label_z_for_pose()` | 988 | Places 3D text above standing/sitting/lying bodies without floating arbitrarily. |

Observed/known operational behavior:

- A standing model with sufficient horizontal speed is displayed as `MOVING`.
- A model prediction of FALLING is suppressed unless physical fall evidence is
  present.
- Stable sitting is protected from a transient false-fall transition.
- Low associated-point count can lead to low-quality/no-points behavior.
- `--pose-allow-target-only` allows degraded inference/continuity where target
  data exists but associated points are sparse.
- The source contains a TODO around perfect alignment of delayed xWR6843
  target-index associations for pose features. This can contribute to unstable
  labels or occasional MOVING/no-points quality.

### 4.6 IWR pose gate versus dual-sensor posture gate

There are two different concepts:

1. `ti_style_pose_overlay.py` contains pose display stability and optional
   IWR-only vital eligibility information.
2. `dual_sensor_fusion\posture_gate.py` independently gates AWR phase updates
   for fusion.

The dual-sensor gate is the authoritative rule for whether AWR phase enters the
PC vital estimator. It requires stable `SITTING` for the configured number of
frames. Other postures pause updates.

## 5. Previous IWR-only 3D visualization behavior

### 5.1 OpenGL scene

`ti_style_vendor\common\Common_Tabs\plot_3d.py::Plot3D` begins near line 22.

The scene uses pyqtgraph OpenGL objects:

- `GLViewWidget`: main 3D viewport.
- `GLGridItem`: scene/background grid.
- `GLScatterPlotItem`: point cloud and cluster points.
- `GLMeshItem`: sensor/EVM model, ground plane, and human meshes.
- `GLLinePlotItem` or equivalent line items in the TI target-box path.
- `GLTextItem`: per-target posture/identity labels.

Important methods:

| Method | Approx. line | Behavior |
|---|---:|---|
| `setHumanModelRenderer()` | 93 | Attaches the external per-TID mesh renderer and display mode. |
| `updateHumanPoseModels()` | 98 | Passes current pose records to the renderer. |
| `clearHumanPoseModels()` | 111 | Hides/removes active human models. |
| `setPoseGroundPlane()` | 118 | Creates/removes a translucent floor mesh and optional floor grid. |
| `setTargetBoxesVisible()` | 177 | Supports overlay, replacement, or model-only display modes. |
| `updatePoseLabels()` | 184 | Maintains one color-coded 3D text item per active TID. |

Label colors are posture-specific:

- standing: green
- sitting: blue
- lying: purple
- falling: red
- moving: amber
- unknown: gray

Inactive target labels are hidden rather than globally recreated, which helps
preserve identity and reduce OpenGL churn.

### 5.2 Per-person human renderer

`human_model_renderer.py`

- `load_obj_mesh()` near line 35 parses vertices and faces, triangulates faces,
  centers the model in X/Y, and shifts the minimum Z to zero.
- That minimum-Z normalization is the explicit non-floating-body fix.
- `HumanPoseModelRenderer` begins near line 94.
- `update_models()` near line 128 maintains records by target ID.
- `_item_for_tid()` near line 243 creates a `GLMeshItem` for a TID/model pair.
- `_model_name_for_label()` near line 273 selects the asset.

Asset mapping:

| Display posture | Mesh |
|---|---|
| `SITTING` | `human_sitting.obj` |
| `LYING`, `FALLING` | `human_lying.obj` |
| `STANDING`, `MOVING`, other active upright labels | `human_standing.obj` |
| unknown/warmup | hidden unless fallback-standing behavior is enabled |

The renderer applies physical target sizes:

- standing target height: approximately 1.70 m
- sitting target height: approximately 1.20 m
- lying target horizontal length: approximately 1.70 m

Every frame, an active mesh is reset, scaled, and translated to the target's
current `(x, y, ground_z)`. Items are keyed by TID. A mesh is replaced only
when that target changes model type, so identity persists while a person moves.

Rendering modes:

- `overlay_box`: body mesh and TI target box are both visible.
- `replace_box`: body mesh replaces the box.
- `model_only`: only body models are emphasized.

If mesh rendering fails, `PeopleTracking.updatePoseHumanModels()` clears the
models and restores target boxes as a fail-safe.

### 5.3 Mesh assets

`ui_human_pose_models` contains:

- `human_standing.obj` and `.glb`
- `human_sitting.obj` and `.glb`
- `human_lying.obj` and `.glb`
- a combined GLB
- README/license files

The active renderer loads OBJ files. GLB files are not the primary runtime
format in the current implementation. The documented coordinate convention is
meters, Z up, +Y forward, with the body bottom normalized to Z=0.

### 5.4 Attachment lifecycle

The mesh feature requires all of these steps:

1. `run_ti_style_visualizer.py` parses `--pose-human-models`.
2. `create_pose_manager_before_qt()` near line 689 creates the pose manager and
   propagates human-model configuration.
3. `attach_pose_manager()` near line 785 attaches the pose manager to the
   `PeopleTracking` demo.
4. Inside `attach_pose_manager()`, only when
   `args.pose_human_models` is true, a `HumanPoseModelRenderer` is constructed
   and passed to `PeopleTracking.setPoseHumanModelRenderer()`.
5. Only when `args.pose_ground_plane` is true,
   `PeopleTracking.setPoseGroundPlane()` is called.
6. Each `PeopleTracking.updateGraph()` call obtains per-TID records and updates
   the renderer.

The command-line declarations are near:

- `--pose-human-models`: `run_ti_style_visualizer.py` line 206.
- `--pose-ground-plane`: line 274.
- ground-plane size/grid/alpha options: approximately lines 279-292.

## 6. Why the human models disappeared in the fusion UI

### 6.1 What the fusion UI actually reuses

`dual_sensor_fusion\run_dual_sensor_fusion_ui.py::_reflow_ti_window()` begins
near line 1019.

It:

1. Takes the already-created TI main window.
2. Removes `window.demoTabs` from its original grid layout.
3. Places that exact `demoTabs` object into the new left-side IWR panel.
4. Adds the AWR range-bin panel and vital dashboard around it.

Therefore, the left panel is not a replacement point-cloud implementation. It
is the original TI demo tab widget, including the original `PeopleTracking`
OpenGL scene.

### 6.2 Missing feature propagation

`_make_ti_args()` near line 94 builds an argument list for the reused
`run_ti_style_visualizer` launcher. It enables:

- pose inference
- model path
- pose logging/debug options
- 3D pose labels
- minimum associated points = 1
- target-only fallback

It does not enable:

- `--pose-human-models`
- `--pose-human-model-dir`
- `--pose-human-model-mode`
- human-model scale/ground-Z options
- `--pose-ground-plane`
- ground-plane size/grid/alpha options

As a result, `attach_pose_manager()` skips both renderer construction and
ground-plane creation. The existing scene has no renderer to update.

### 6.3 Demo mode limitation

`_make_demo_iwr_output()` near line 1225 creates fake IWR frames and includes a
fusion-specific pose record. `_start_demo()` near line 1268 drives the offline
layout.

However, demo mode does not create a normal `TiStylePoseManager`. The fusion
controller can read the injected `_fusionDemoPose`, but the vendor
`PeopleTracking.processPoseResults()` path has no attached manager from which
to call `get_3d_label_records()` and `get_3d_model_records()`.

Consequently, demo mode is currently useful for layout, AWR bars, posture gate,
and vital dashboard testing, but not for verifying the complete old human-mesh
rendering path.

### 6.4 Confirmed answer to the problem statement

The statement “the fusion UI implemented a simplified IWR display instead of
reusing the exact old widget” is **not fully true**.

The confirmed cause is:

> The fusion UI reuses the exact TI 3D widget but constructs an incomplete
> IWR-only argument/configuration set, leaving the existing optional human mesh
> renderer and ground plane disabled.

This is a smaller and safer repair than porting or duplicating the renderer.

## 7. Dual-sensor fusion implementation

### 7.1 `fusion_types.py`

Defines shared dataclasses:

- `IwrTarget` near line 8
- `AwrBinSample` near line 26
- `AwrBinWindow` near line 38
- `BinSelection` near line 50
- `VitalEstimate` near line 65
- `FusedTargetVital` near line 76

These types form the boundary between vendor parser output, AWR parser output,
selection/gating logic, UI, and CSV logging.

### 7.2 `coordinate_transform.py`

- `TransformConfig` near line 10.
- `expected_awr_range()` near line 18.

Default v1 behavior uses the IWR target's reported range directly. If it is
unavailable, it rotates X/Y by the configured yaw and computes Euclidean range
with `dx`, `dy`, and `dz` offsets.

Assumption: sensors are side by side, close together, at approximately the
same height, and pointing in the same direction. Direct range is therefore a
first-order calibration, not a full extrinsic transform.

### 7.3 `awr_bin_selector.py`

- `SelectorConfig` near line 10.
- `select_bin()` near line 15.
- `select_bin_for_target()` near line 93.

Algorithm:

1. Find the AWR sample closest to expected IWR range.
2. Build a candidate window of expected bin ± `searchHalfWidth`.
3. Choose the largest magnitude in that window.
4. Retain the previous bin if still valid unless a new bin is at least the
   configured hysteresis ratio (default 1.15) stronger.

The output records expected, selected, strongest-overall, candidate bins, and
selection reason.

### 7.4 `posture_gate.py`

- `SittingGateConfig` near line 17.
- `GateDecision` near line 27.
- `SittingGate` near line 42.

The gate tracks state independently by target ID and requires stable
`SITTING`. Default stable-frame count is 10. Moving/falling/unknown or any
non-sitting posture pauses updates.

Main states:

- `MONITORING`
- `WAITING_FOR_SITTING`
- `POSTURE_UNSTABLE`
- `PAUSED_NOT_SITTING`
- `NO_TARGET`
- `TARGET_LOST`

### 7.5 `vital_estimator_bridge.py`

- `VitalEstimatorConfig` near line 16.
- `VitalEstimatorBridge` near line 23.

It:

- maintains per-target rolling phase buffers
- defaults to 10 Hz
- appends phase only while the posture gate is `MONITORING`
- preserves the last estimate during pauses but allows the UI/logger to hide
  rates
- resets the phase buffer on a selected-bin change because phase from two bins
  is not continuous
- marks frequent selection changes as `BIN_SWITCHING`
- calls the existing AWR phase-vital estimator instead of duplicating it

### 7.6 `dual_sensor_logger.py`

- `FusionConfig` near line 40.
- `FusionEngine` near line 47.
- `make_status_fused()` near line 145.
- `PrimaryTargetTracker` near line 177.
- `convert_awr_window()` near line 206.
- `extract_iwr_targets()` near line 234.
- `DualSensorCsvLogger` near line 285.

`FusionEngine` is the core non-UI fusion path. It runs the posture gate, range
transform, bin selection, and vital estimator. It emits a
`FusedTargetVital`.

The logger writes:

- `iwr_targets.csv`
- `awr_bin_window_samples.csv`
- `fused_target_vitals.csv`
- `selected_bin_trace.csv`
- event/UI CSV where applicable
- `run_config.json`
- `fusion_summary.json`

The primary-target policy supports a requested TID. Otherwise it keeps the
current target when possible and falls back to a nearest/available target.
This is structured for multiple tracks, but vital estimation is intentionally
single-primary-target in v1.

### 7.7 `run_dual_sensor_fusion_logger.py`

Key functions:

- `build_arg_parser()` near line 65
- `_iwr_worker()` near line 126
- `_awr_worker()` near line 181
- `run()` near line 257

The IWR worker:

- opens/sends the IWR configuration in live mode
- uses the vendored TI `UARTParser`
- runs `TiStylePoseManager`
- converts tracks/pose records to `IwrTarget`

The AWR worker:

- sends the AWR configuration
- reads AWR binary frames
- reuses `_extract_complete_frames()` from
  `run_live_vital_phase_window_reader.py`
- converts FE02 records to fusion types

The main loop consumes the newest frames and logs periodic fused status.

### 7.8 `run_dual_sensor_fusion_ui.py`

Key blocks:

| Function/class | Approx. line | Role |
|---|---:|---|
| `build_arg_parser()` | 46 | Fusion UI CLI, including ports, configs, transform, window size, `--layout-debug`, and `--demo-mode`. |
| `_make_ti_args()` | 94 | Adapts fusion CLI options into IWR-only visualizer arguments. This is where human-model options are currently omitted. |
| `_awr_worker()` | 140 | Non-blocking AWR reader thread. |
| `_build_widgets()` | 208 | Earlier/basic panel classes. |
| `_build_responsive_widgets()` | 421 | Current responsive AWR and vital dashboard widgets. |
| `FusionUiController` | 819 | Receives IWR/AWR updates, runs fusion, updates panels, and logs UI runs. |
| `_reflow_ti_window()` | 1019 | Embeds the original TI tabs into the fusion splitters and adds AWR/vitals/sidebar regions. |
| `_install_layout_debug()` | 1173 | Panel borders and periodic size output. |
| `_make_demo_awr_window()` | 1190 | Fake bins 20-60 and moving magnitude peak. |
| `_make_demo_iwr_output()` | 1225 | Fake target and posture transitions. |
| `_start_demo()` | 1268 | Starts offline demo timer. |
| `run()` | 1289 | Creates the TI window, pose manager in live mode, fusion panels, and reader thread. |

The live wrapper preserves the vendor update ordering and copies track arrays
before the TI renderer transforms/mutates them. This is important for correct
fusion coordinates.

Current UI:

- Left: embedded TI IWR 3D tracking tab.
- Right: AWR bins 20-60 with expected, selected, fixed, and strongest markers.
- Bottom: target/posture, bin selection, and vital cards.
- Sidebar: existing connection/config/plot/pose controls plus fusion summary.
- Splitters and minimum sizes support high-DPI/window resizing.
- Status colors distinguish monitoring, waiting, paused, unstable, no data,
  no bin, and bin switching.

What it does not currently preserve:

- automatic activation of human mesh models
- automatic activation of the pose ground plane
- mesh-model verification in demo mode

### 7.9 `test_dual_sensor_fusion.py`

The offline unit test defines:

- fake bins 20-60
- strongest bin 37
- target range around 1.75 m
- standing and sitting target records

It verifies:

- IWR-guided selection reaches bin 37
- standing is paused
- monitoring starts after the configured stable-sitting frames
- leaving sitting returns to paused state

This tests fusion logic, not Qt/OpenGL mesh rendering.

## 8. Old IWR UI versus fusion UI

| Capability | IWR-only TI UI | Fusion UI |
|---|---|---|
| TI point cloud | Yes | Yes; same embedded widget |
| TI target boxes | Yes | Yes |
| Target IDs/identity | Yes | Yes |
| ONNX posture inference | Yes with `--enable-pose` | Yes in normal live mode |
| Pose status table | Yes | Yes through reused demo |
| 3D pose text labels | Optional with `--pose-3d-labels` | Enabled by `_make_ti_args()` |
| Standing/sitting/lying meshes | Optional with `--pose-human-models` | Renderer code is available but not enabled |
| Falling visual | Lying mesh with red falling color plus label/box logic | Missing mesh because renderer is not attached |
| Moving visual | Standing mesh with amber color | Missing mesh because renderer is not attached |
| Ground plane | Optional with `--pose-ground-plane` | Not enabled |
| AWR range bins | No | Yes |
| Sitting-only AWR vital gate | No/independent IWR gate | Yes |
| Vital dashboard | No | Yes |
| Offline layout demo | No equivalent complete fusion demo | Yes, but no normal pose mesh path |

### Files/functions to reuse

No new mesh implementation should be created. Reuse:

- `human_model_renderer.py::HumanPoseModelRenderer`
- `ti_style_pose_overlay.py::get_3d_model_records()`
- `ti_style_pose_overlay.py::get_3d_label_records()`
- `PeopleTracking.setPoseHumanModelRenderer()`
- `PeopleTracking.setPoseGroundPlane()`
- `PeopleTracking.updatePoseHumanModels()`
- `Plot3D.setHumanModelRenderer()`
- `Plot3D.updateHumanPoseModels()`

The primary modification point in a future task is
`dual_sensor_fusion\run_dual_sensor_fusion_ui.py`, especially
`build_arg_parser()`, `_make_ti_args()`, and demo startup.

## 9. AWR1642BOOST vital-sign system

### 9.1 Known working hardware configuration

- Board: AWR1642BOOST.
- CLI/config port: COM9 at 115200.
- Data/TLV port: COM8 at 921600.
- Configuration:
  `custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg`
- Real AWR frame period: 100 ms, so PC estimator `fs` should be 10 Hz.

SOP note: repository documentation does not contain an authoritative switch
pattern for every board revision. It records programming/flashing mode versus
functional/run mode as distinct phases but leaves the exact SOP switch pattern
as an item to confirm from the AWR1642BOOST hardware guide. This report does
not infer switch positions.

### 9.2 FE01 VitalPhaseTrace

ID: `0xFE01`

Payload is 36 bytes:

```text
uint32 frameNumber
uint16 rangeBinIndexMax
uint16 rangeBinIndexPhase
float  rangeMeters
float  iValue
float  qValue
float  phaseRad
float  magnitude
float  snrLike
uint8  motionDetected
uint8  reserved[3]
```

Firmware type: `VitalPhaseTrace` in
`src\1642\common\mmw_messages.h`, approximately lines 241-254.

PC parser:

- `parse_vital_phase_tlv.py`
- struct format: `<IHHffffffB3s`
- payload constant: 36 bytes

Modes:

- Fake: synthetic 15 bpm breathing and 72 bpm heart.
- Real fixed bin: zero-Doppler complex sample from
  `obj->azimuthStaticHeatMap`.
- Real max bin: declared but currently falls back safely to fake rather than
  implementing an unsafe selector in firmware.

Verified fake live result:

- 461 samples
- 46.20 seconds
- breathing approximately 15.62 bpm
- heart approximately 72.89 bpm
- quality OK

Verified real fixed-bin result:

- bin 32
- range approximately 1.5170 m
- variable real magnitude
- real phase from `azimuthStaticHeatMap`

### 9.3 FE02 bin-window TLV

ID: `0xFE02`

Header, 12 bytes:

```text
uint32 frameNumber
uint16 startBin
uint16 numBins
float  rangeResolution
```

Sample, 24 bytes:

```text
uint16 binIndex
uint16 reserved
float  rangeMeters
float  iValue
float  qValue
float  phaseRad
float  magnitude
```

Default payload:

- start bin 20
- 41 bins
- bins 20 through 60 inclusive
- total payload = `12 + 41 * 24 = 996` bytes

PC parser:

- `parse_vital_phase_bin_window_tlv.py`
- header format `<IHHf`
- sample format `<HHfffff`
- validates exact payload size

Verified live result:

- start bin 20
- 41 bins
- strongest bin around 37
- strongest range around 1.7541 m
- strongest magnitude around 2400-2500
- FE01 fixed bin 32 remained present for comparison

### 9.4 AWR UART parser and readers

`phase_vitals\tlv_parser\ti_uart_packet_parser.py`:

- parses the TI magic word and frame header
- enumerates TLV headers
- `extract_vital_phase_tlvs()` near line 141 extracts FE01
- `extract_vital_phase_bin_window_tlvs()` near line 155 extracts FE02
- stream helpers resynchronize after garbage/partial packets

`run_live_vital_phase_reader.py`:

- reads FE01
- prints phase/range/magnitude/motion
- runs the PC estimator
- writes sample CSV and estimate JSON

`run_live_vital_phase_window_reader.py`:

- `_extract_complete_frames()` near line 47 is reused by the fusion readers
- parses FE02 and optionally FE01
- reports start/count and strongest bin/range/magnitude
- writes one CSV row per bin sample

Offline packet support:

- `fake_ti_uart_packet.py`
- `test_ti_uart_packet_parser.py`
- `test_vital_phase_tlv_parser.py`
- `test_vital_phase_bin_window_parser.py`
- fake replay scripts

### 9.5 Known AWR limitations

- `azimuthStaticHeatMap` is zero-Doppler complex range data, suitable as a safe
  first real phase source but not a complete vital-sign isolation algorithm.
- Current firmware uses virtual azimuth antenna index 0 rather than coherent
  multi-antenna combining.
- Motion, multipath, clutter, and phase wrapping can make the selected phase
  noisy.
- Fixed bin 32 is not person-aware.
- FE02 enables PC-side person-range selection, but range alone cannot separate
  multiple people at nearly the same range.
- Selected-bin changes introduce phase discontinuities; the bridge resets its
  phase history and can report `BIN_SWITCHING`.
- The strongest-magnitude bin is not always the chest/vital-optimal bin.

## 10. AWR firmware modifications and build state

### 10.1 Copied source location

Only this copied experiment is intended for modification:

`custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase`

Original TI SDK/source folders must remain unchanged.

### 10.2 Message header changes

`src\1642\common\mmw_messages.h`

Near lines 231-278:

- FE01 remains `0xFE01U`.
- FE02 is `0xFE02U`.
- `VitalPhaseTrace` is defined.
- `VitalPhaseBinSample` is defined and compile-time checked as 24 bytes.
- `VitalPhaseBinWindowHeader` is defined and checked as 12 bytes.
- Output descriptor capacity was increased to allow the additional custom TLV.

### 10.3 DSS changes

`src\1642\dss\dss_main.c`

Key locations:

| Block | Approx. line | Purpose |
|---|---:|---|
| mode constants | 817-825 | fake, real fixed-bin, real max-bin; default fake |
| fixed-bin guard | 828 | requires `VITAL_PHASE_FIXED_RANGE_BIN` in fixed mode |
| FE02 defaults | 834-839 | start 20, count 41 |
| `MmwDemo_fillFakeVitalPhaseTrace()` | 877 | known-good synthetic FE01 |
| `MmwDemo_fillVitalPhaseTrace()` | 905 | compile-time dispatcher |
| real sample read | 918-946 | reads `azimuthStaticHeatMap[bin * numVirtualAntAzim]`, antenna 0, computes `atan2sp` and `sqrtsp` |
| `MmwDemo_fillVitalPhaseBinWindow()` | 960 | clamps the requested range and serializes FE02 |
| FE01 packaging | 1251-1273 | appends FE01 unchanged |
| FE02 packaging | 1283-1300 | appends FE02 only when descriptor and HSRAM capacity allow |

Real I/Q generation:

```text
sample index = bin * obj->numVirtualAntAzim
iValue       = sample.real
qValue       = sample.imag
phaseRad     = atan2sp(qValue, iValue)
magnitude    = sqrtsp(iValue*iValue + qValue*qValue)
rangeMeters  = bin * obj->rangeResolution
```

The source is persistent zero-Doppler complex data available during output
packaging. This was chosen instead of reading transient radar-cube data.

### 10.4 Compile-time modes

```c
#define VITAL_PHASE_MODE_FAKE            0U
#define VITAL_PHASE_MODE_REAL_FIXED_BIN  1U
#define VITAL_PHASE_MODE_REAL_MAX_BIN    2U
```

Default source behavior remains fake unless the build defines
`VITAL_PHASE_MODE`.

The working real fixed-bin build used:

```text
VITAL_PHASE_MODE=1U
VITAL_PHASE_FIXED_RANGE_BIN=32U
```

FE02 is additive and does not replace FE01.

### 10.5 CCS workspace and binary

CCS workspace:

`C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\ccs_workspace_awr1642_vital_phase`

Current inspected output includes:

- `AWR16xx_dss_nonOS\Debug\xwr16xx_mmw_dss_nonOS.xe674`
- `AWR16xx_dss_nonOS\Debug\xwr16xx_mmw_dss_nonOS.bin`
- `AWR16xx_mss_nonOS\Debug\xwr16xx_mmw_mss_nonOS.xer4f`
- `AWR16xx_mss_nonOS\Debug\xwr16xx_mmw_mss_nonOS.bin`
- `AWR16xx_mss_nonOS\Debug\xwr16xx_mmw_nonOS.bin`

At audit time the combined binary was 201,796 bytes and timestamped June 20,
2026 1:14:44 PM. The user's live verification is the stronger evidence that
the current FE02 firmware is functional.

### 10.6 Workspace-copy/stale-source issue

The CCS projects contain physical file copies, not guaranteed live links to
the copied experiment. A prior failure mode was:

1. Codex patched the experiment source.
2. CCS built older copies inside the workspace.
3. The resulting image did not contain the expected latest behavior.

Verified workspace copies:

```text
ccs_workspace_awr1642_vital_phase\AWR16xx_dss_nonOS\dss_main.c
ccs_workspace_awr1642_vital_phase\AWR16xx_dss_nonOS\common\mmw_messages.h
ccs_workspace_awr1642_vital_phase\AWR16xx_mss_nonOS\common\mmw_messages.h
```

If the workspace is stale, the following is the reconstructed minimum copy
sequence from the verified source and workspace paths. Close/suspend the CCS
build first, then run from the toolbox root:

```powershell
Copy-Item -LiteralPath "custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\src\1642\dss\dss_main.c" -Destination "ccs_workspace_awr1642_vital_phase\AWR16xx_dss_nonOS\dss_main.c" -Force

Copy-Item -LiteralPath "custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\src\1642\common\mmw_messages.h" -Destination "ccs_workspace_awr1642_vital_phase\AWR16xx_dss_nonOS\common\mmw_messages.h" -Force

Copy-Item -LiteralPath "custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\src\1642\common\mmw_messages.h" -Destination "ccs_workspace_awr1642_vital_phase\AWR16xx_mss_nonOS\common\mmw_messages.h" -Force
```

These commands are documented recovery steps, not actions performed by this
audit. A clean re-import from the copied experiment is preferable when CCS
project metadata itself is suspect.

### 10.7 Build-history documentation caveat

`BUILT_BINARY_NOTES.md` records an earlier fake-image CRC `4c604852` and
200,708 bytes. `REAL_PHASE_PATCH_NOTES.md` records another intermediate build.
Those notes predate the user's later verified real fixed-bin and FE02 live
tests. Treat them as build history, not the current binary identity.

## 11. End-to-end data-flow diagrams

### A. IWR-only tracking/posture UI

```text
IWR6843ISK-ODS
  COM7 CLI  <--- ODS_6m_default.cfg
  COM6 data ---> UARTParser
                  |
                  v
             parseStandardFrame
                  |
          +-------+--------+----------------+
          |                |                |
       pointCloud       trackData       heightData
          |                |                |
          +----------------+----------------+
                           |
                           v
                 TiStylePoseManager
          feature history -> ONNX -> smoothing
             -> physical gates -> stable label
                           |
              +------------+-------------+
              |                          |
       3D label records           3D model records
              |                          |
              v                          v
        Plot3D GLTextItem     HumanPoseModelRenderer
                                     GLMeshItem/TID
              \                          /
               \                        /
                +-- PeopleTracking UI -+
                    point cloud, boxes,
                    IDs, table, ground
```

### B. AWR-only fixed-bin vital flow

```text
AWR1642 ADC/chirps
        |
        v
range processing / zero-Doppler integration
        |
        v
obj->azimuthStaticHeatMap
        |
fixed bin * numVirtualAntAzim, antenna 0
        |
real/imag -> atan2sp + sqrtsp
        |
FE01 VitalPhaseTrace (36 bytes)
        |
COM8 at 921600
        |
TI UART packet parser
        |
phase_vitals_estimator at 10 Hz
        |
breathing / heart / quality
```

### C. AWR FE02 bin-window flow

```text
obj->azimuthStaticHeatMap
        |
bins 20..60, virtual azimuth antenna 0
        |
for each bin:
  range, I, Q, phase, magnitude
        |
FE02 header + 41 sample records
        |
COM8 data stream
        |
parse_vital_phase_bin_window_tlv.py
        |
AwrBinWindow
        |
strongest overall + PC-side IWR-guided selection
```

### D. Current dual-sensor fusion flow

```text
IWR COM6 ---------------------> TI parser + pose manager
                                      |
                                      v
                                  IwrTarget
                                      |
                                      +------ posture gate
                                      |
                                      +------ expected AWR range/bin
                                                     |
AWR COM8 -> FE02 parser -> latest AwrBinWindow ------+
                                                     |
                                      candidate magnitude search
                                      + bin hysteresis
                                                     |
                                           selected phase sample
                                                     |
                              only if stable SITTING: estimator update
                                                     |
                                           FusedTargetVital
                                    /              |              \
                               CSV logs       AWR panel       vital cards

IWR rendering branch:
same PeopleTracking demoTabs -> fusion left panel
but human renderer/ground plane currently not enabled
```

### E. Desired final fusion UI flow

```text
IWR parser + TiStylePoseManager
        |
        +--> unchanged FusionEngine -----------------------------+
        |                                                        |
        +--> get_3d_label_records()                               |
        +--> get_3d_model_records()                               |
                 |                                                |
        existing HumanPoseModelRenderer                           |
        + existing ground plane                                   |
                 |                                                |
        embedded original PeopleTracking GL widget                |
                 |                                                |
       LEFT: full old IWR view                                    |
                                                                  |
AWR FE02 -> unchanged selector/estimator -------------------------+
                 |
       RIGHT: unchanged AWR panel
                 |
       BOTTOM: unchanged vital dashboard

No duplicate renderer, no firmware change, no fusion-algorithm change.
```

## 12. Known/expected commands

All commands below are documentation only. They were not executed during this
audit.

### 12.1 IWR-only UI

```powershell
python custom_iwr6843_fall_logger\run_ti_style_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs\ti_pose_ui_warmup_debug --enable-pose --pose-model "custom_iwr6843_fall_logger\model_experiments\outputs\ti_4class_clean_recording_robust_1600_fast\ti_pose_model.onnx" --pose-log --pose-debug --pose-3d-labels --pose-3d-label-debug --pose-min-associated-points-for-inference 1 --pose-allow-target-only
```

To explicitly enable the existing posture meshes and floor in the IWR-only UI,
append:

```text
--pose-human-models --pose-human-model-dir custom_iwr6843_fall_logger\ui_human_pose_models --pose-human-model-mode overlay_box --pose-ground-plane
```

### 12.2 Send AWR configuration

```powershell
python custom_iwr6843_fall_logger\send_cfg.py --cli COM9 --baud 115200 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg"
```

### 12.3 AWR FE01 reader

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_live_vital_phase_reader.py --data-com COM8 --baud 921600 --duration 60 --fs 10 --out logs\awr1642_real_fixed_bin_live
```

For the old synthetic 20 Hz fake stream, use `--fs 20`. The current real
profile uses 10 Hz.

### 12.4 AWR FE02 reader

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_live_vital_phase_window_reader.py --data-com COM8 --baud 921600 --duration 60 --out logs\awr1642_bin_window_live --debug
```

### 12.5 Dual-sensor logger

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_logger.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_test --duration 90 --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --debug
```

### 12.6 Current dual-sensor UI

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --debug
```

This current command does not expose/enable the human mesh options.

### 12.7 Demo/layout-debug UI

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --layout-debug --window-width 1600 --window-height 950 --out logs\dual_sensor_fusion_layout_demo
```

Current demo mode does not exercise the normal human-mesh renderer.

## 13. Recommended next fix plan

Do not alter firmware, parsers, fusion selection, posture gate, estimator, CSV
schemas, AWR panel, or vital dashboard for this repair.

### Step 1: expose the old renderer options in the fusion UI CLI

Modify only `dual_sensor_fusion\run_dual_sensor_fusion_ui.py` initially.

Add optional arguments matching the IWR-only launcher:

- `--pose-human-models` / optionally default it on for the fusion UI
- `--pose-human-model-dir`
- `--pose-human-model-mode`
- `--pose-human-model-target-height`
- `--pose-human-model-sitting-height`
- `--pose-human-model-lying-length`
- `--pose-human-model-ground-z`
- `--pose-human-model-fallback-standing`
- `--pose-ground-plane`
- ground-plane size/grid/alpha options

Safer compatibility choice:

- Preserve IWR-only defaults.
- In the fusion UI, enable meshes and ground plane by default only if this is
  explicitly desired as the product behavior, while providing
  `--no-pose-human-models` and `--no-pose-ground-plane` escape hatches.
- Otherwise require explicit flags and update the standard fusion command.

### Step 2: propagate options through `_make_ti_args()`

Update `_make_ti_args()` near line 94 to append the same argument names and
values accepted by `run_ti_style_visualizer.py`.

Do not directly instantiate a second renderer in `_reflow_ti_window()`.
`attach_pose_manager()` already owns correct construction and attachment.

### Step 3: verify the existing attachment path

Leave these implementations unchanged unless testing reveals a real defect:

- `run_ti_style_visualizer.py::create_pose_manager_before_qt()`
- `run_ti_style_visualizer.py::attach_pose_manager()`
- `PeopleTracking.setPoseHumanModelRenderer()`
- `PeopleTracking.updatePoseHumanModels()`
- `Plot3D.setHumanModelRenderer()`
- `HumanPoseModelRenderer`

Confirm after startup:

- `PeopleTracking.poseManager` is non-null.
- `PeopleTracking.poseHumanModelRenderer` is non-null.
- model mode is `overlay_box` for the first restoration test, so target boxes
  remain visible.
- the ground plane is attached once.

### Step 4: preserve target identity and coordinate behavior

Do not change track extraction or coordinate transforms.

The old renderer already:

- keys mesh items by TID
- maps model position from current TI track X/Y
- uses ground Z for body contact
- retains/replaces the item only when the posture requires another mesh
- colors MOVING/FALLING appropriately
- scales standing/sitting/lying assets separately

The fusion wrapper must continue copying `trackData` before the vendor update
mutates it for rendering. This protects fusion range calculations while the
renderer uses the normal TI transformed scene.

### Step 5: keep labels readable

Retain existing 3D labels. If clipping remains:

- use the existing compact format (for example `ID 13 | MOVING 55%`)
- adjust label Z offset or camera margins through existing pose settings
- do not replace mesh identity with a global label

### Step 6: extend demo mode for mesh verification

Current demo mode should be enhanced without COM ports.

Preferred approach:

1. Construct a lightweight demo pose-manager adapter implementing:
   - `process_output_dict()`
   - `get_3d_label_records()`
   - `get_3d_model_records()`
2. Attach it through the same `PeopleTracking.setPoseManager()` and
   `setPoseHumanModelRenderer()` path.
3. Cycle one stable TID through:
   - STANDING
   - MOVING
   - SITTING
   - LYING
   - FALLING
4. Keep the target position fixed or move it slowly so scaling, ground
   alignment, item reuse, and identity are visually testable.

Alternative: add a supported override hook in `TiStylePoseManager` for demo
records. Avoid special-case direct OpenGL item creation in the fusion UI.

### Step 7: non-hardware validation

Run:

```powershell
python -m py_compile custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --help
python -m unittest custom_iwr6843_fall_logger.dual_sensor_fusion.test_dual_sensor_fusion
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --layout-debug --pose-human-models --pose-ground-plane
```

The demo command opens a local UI but no COM ports. Verify:

- one mesh per TID
- posture-specific mesh changes
- body bottom remains on the ground
- boxes remain visible in `overlay_box`
- AWR panel and vital cards continue updating
- splitters/layout remain responsive
- closing the window terminates timers cleanly

### Step 8: live validation

Only after offline checks:

1. Run the IWR-only UI with explicit mesh and ground-plane flags and confirm
   the renderer works independently.
2. Run the fusion UI with the same propagated options.
3. Use one person at 1.5-2.0 m.
4. Confirm the same TID keeps its mesh while standing, moving, and sitting.
5. Confirm mesh posture matches the displayed posture label.
6. Confirm vitals remain paused while not stably sitting.
7. Confirm stable sitting activates AWR phase accumulation without changing
   the IWR visualization.
8. Review UI event and fused CSV logs for state transitions.

### Step 9: documentation update

After implementation, update `DUAL_SENSOR_FUSION_USAGE.md` with:

- human-model CLI options
- ground-plane options
- recommended `overlay_box` first-run mode
- demo-mode posture cycle
- expected difference between ONNX classes and display `MOVING`

## 14. File/function action matrix

| File / symbol | Action in next task | Reason |
|---|---|---|
| `dual_sensor_fusion\run_dual_sensor_fusion_ui.py::build_arg_parser()` | Modify | Expose model/ground-plane options. |
| `dual_sensor_fusion\run_dual_sensor_fusion_ui.py::_make_ti_args()` | Modify | Propagate options to the existing IWR launcher. |
| `dual_sensor_fusion\run_dual_sensor_fusion_ui.py::_start_demo()` and demo helpers | Modify | Exercise normal label/mesh path offline. |
| `dual_sensor_fusion\run_dual_sensor_fusion_ui.py::_reflow_ti_window()` | Usually leave alone | It already embeds the correct original widget. Only adjust if attachment ordering proves wrong. |
| `run_ti_style_visualizer.py::attach_pose_manager()` | Reuse | Already owns renderer and ground-plane setup. |
| `human_model_renderer.py::HumanPoseModelRenderer` | Reuse unchanged | Existing TID, model selection, scaling, color, and ground behavior are correct. |
| `ti_style_pose_overlay.py::get_3d_model_records()` | Reuse unchanged | Already maps stable per-TID pose results to renderer records. |
| `PeopleTracking.updateGraph()` | Leave alone | Already invokes labels and models every frame. |
| `Plot3D` | Leave alone | Existing OpenGL scene already supports all required layers. |
| `FusionEngine`, selector, gate, estimator | Leave alone | UI regression is not in fusion logic. |
| AWR parsers and firmware | Leave alone | FE01/FE02 are working and unrelated to missing meshes. |

## 15. Current project state

### Works now

- IWR6843ISK-ODS multi-person tracking.
- IWR point cloud, target boxes, IDs, and posture inference.
- Four-class ONNX pose model plus runtime MOVING state.
- Pose smoothing, stability, sitting protection, and physical fall gate.
- AWR1642 real fixed-bin FE01 phase.
- AWR1642 FE02 bins 20-60 from `azimuthStaticHeatMap`.
- FE01 and FE02 PC parsers/readers.
- IWR-guided AWR range-bin selection with hysteresis.
- Sitting-only phase accumulation.
- Dual-sensor CSV logger.
- Responsive dual-sensor UI with IWR, AWR, and vital panels.
- Offline fusion logic tests and a no-COM layout demo.

### Partially working

- The fusion UI retains the underlying TI 3D pose-capable widget and normal
  pose inference, but does not attach the optional human mesh renderer or
  ground plane.
- Demo mode validates layout and fusion status but not the full old
  pose-rendering lifecycle.
- Single-person range fusion works as v1; same-range multi-person separation is
  not solved.
- Vital estimates depend on phase stability, selected-bin stability, and
  seated motion.

### Broken or missing

- Posture-specific per-person standing/sitting/lying meshes are absent from the
  fusion UI.
- Moving/falling mesh color/model behavior is consequently absent.
- Ground-plane/body-contact visualization is absent.
- There is no fusion-UI CLI path to request those existing features.

### What must be fixed next

Propagate the existing IWR human-model and ground-plane configuration through
the fusion UI, then make demo mode feed the standard pose-renderer interface.
Do not rewrite the renderer and do not alter firmware or fusion logic.

### Recommended next Codex prompt topic

> Restore the existing `HumanPoseModelRenderer` and pose ground plane in
> `run_dual_sensor_fusion_ui.py` by exposing and forwarding the IWR-only
> human-model options through `_make_ti_args()`. Preserve the embedded original
> `PeopleTracking` widget, AWR panel, vital dashboard, fusion engine, and
> logger. Extend `--demo-mode` so one stable target cycles through standing,
> moving, sitting, lying, and falling using the same
> `get_3d_label_records()`/`get_3d_model_records()` attachment path. Run only
> non-hardware syntax, unit, help, and demo UI checks.

