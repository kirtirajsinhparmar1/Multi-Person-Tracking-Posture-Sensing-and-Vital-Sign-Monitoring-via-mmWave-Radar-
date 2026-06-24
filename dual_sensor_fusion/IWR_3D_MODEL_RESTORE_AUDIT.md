# IWR 3D Human Model Restore Audit

## Result

The reference repository was cloned successfully into:

```text
custom_iwr6843_fall_logger_external_reference\old_multitracking_pose_repo
```

Reference commit:

```text
f95e65719d3342d61fb2519d09b69f7cad058582
2026-06-16T18:35:24-04:00
Update latest pose UI log
```

The missing meshes were not caused by absent assets, an absent renderer, or a
replacement IWR plot. The current fusion UI already embeds the existing TI
`PeopleTracking` 3D widget. It failed to request the human-model renderer and
ground plane when it built the embedded TI launch arguments. Demo mode also
passed no pose manager, so it could not produce model records.

The safe repair was therefore:

1. Keep the current TI widget, pose pipeline, AWR panel, fusion controller,
   vital dashboard, logger, and sitting gate.
2. Forward the existing human-model and ground-plane options through
   `_make_ti_args()`.
3. Enable both features by default in the fusion launcher.
4. Add a pose-manager-compatible demo adapter for offline mesh validation.

No firmware, parser, AWR panel, fusion algorithm, or vital estimator code was
changed.

## Files compared

Current repository:

- `custom_iwr6843_fall_logger\human_model_renderer.py`
- `custom_iwr6843_fall_logger\ti_style_pose_overlay.py`
- `custom_iwr6843_fall_logger\run_ti_style_visualizer.py`
- `custom_iwr6843_fall_logger\ti_style_vendor\common\Demo_Classes\people_tracking.py`
- `custom_iwr6843_fall_logger\ti_style_vendor\common\Common_Tabs\plot_3d.py`
- `custom_iwr6843_fall_logger\ui_human_pose_models\`
- `custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py`
- `custom_iwr6843_fall_logger\dual_sensor_fusion\test_dual_sensor_fusion.py`

Reference repository:

- `human_model_renderer.py`
- `ti_style_pose_overlay.py`
- `run_ti_style_visualizer.py`
- `ti_style_vendor\common\Demo_Classes\people_tracking.py`
- `ti_style_vendor\common\Common_Tabs\plot_3d.py`
- `ui_human_posture_models_free.zip`

The reference repository has no `dual_sensor_fusion` implementation. Its
IWR-only components cannot replace the current fusion UI without losing the
AWR range view, vital dashboard, fusion state, responsive layout, and logging.

## Asset inventory

The current model directory already contains:

| File | Bytes | Purpose |
|---|---:|---|
| `human_standing.obj` | 102,685 | `STANDING`, `MOVING`, and normal fallback mesh |
| `human_sitting.obj` | 102,499 | `SITTING` mesh |
| `human_lying.obj` | 102,833 | `LYING` and `FALLING` mesh |
| `human_standing.glb` | 42,764 | alternate/export asset; not required by the current OBJ renderer |
| `human_sitting.glb` | 42,760 | alternate/export asset |
| `human_lying.glb` | 42,756 | alternate/export asset |
| `human_posture_set_all_poses.glb` | 69,508 | combined alternate asset |
| `README.txt`, `LICENSE.txt` | present | asset documentation/license |
| pose preview PNGs | present | visual reference only |

These names and byte sizes match the files inside the reference
`ui_human_posture_models_free.zip`. No assets were copied or overwritten, and
no backup directory was required.

## Renderer comparison

### Current functionality already present

`human_model_renderer.py`:

- `HumanPoseModelRenderer` starts near line 94.
- `update_models()` starts near line 128 and maintains one `GLMeshItem` per
  target ID.
- `clear()` starts near line 184 and safely removes/hides target mesh items.
- `_model_name_for_label()` starts near line 273:
  - `SITTING` selects the sitting OBJ.
  - `LYING`/`FALLING` select the lying OBJ.
  - `STANDING`/`MOVING` select the standing OBJ.
- Model transforms use target X/Y, the configured ground Z, posture-specific
  target dimensions, and cached mesh geometry.
- Colors distinguish normal, sitting, lying, falling, moving, and degraded
  quality states.
- OBJ loading normalizes model geometry to a zero minimum-Z base. Applying the
  configured ground Z therefore implements the non-floating/ground-contact
  behavior.

The current and reference `human_model_renderer.py` are semantically the same;
only line-ending/hash differences were observed.

### Current code is newer than the reference in other areas

A whitespace-insensitive comparison shows that the current
`ti_style_pose_overlay.py` has about 124 added lines and five changed/removed
lines relative to the reference. The current `run_ti_style_visualizer.py` also
has about 60 added lines. These current versions include later project work and
must not be replaced by the older reference copies.

No renderer or overlay algorithm was copied from the reference.

## Existing live attachment path

The complete model path was already implemented:

```text
run_ti_style_visualizer.py
  parse_args()                         around line 206
  attach_pose_manager()                around line 785
    HumanPoseModelRenderer(...)        around line 798
    PeopleTracking.setPoseHumanModelRenderer(...)
    PeopleTracking.setPoseGroundPlane(...) around line 824

ti_style_vendor\common\Demo_Classes\people_tracking.py
  updateGraph()                        around line 127
  setPoseManager()                     around line 273
  setPoseHumanModelRenderer()          around line 283
  updatePoseHumanModels()              around line 331

ti_style_pose_overlay.py
  get_3d_label_records()               around line 419
  get_3d_model_records()               around line 474

ti_style_vendor\common\Common_Tabs\plot_3d.py
  setHumanModelRenderer()              around line 93
  updateHumanPoseModels()              around line 98
  setPoseGroundPlane()                 around line 118
```

Target identity is preserved because pose/model records carry the TI target
ID, and the renderer caches mesh items by that ID. Mesh placement is refreshed
from each target's current track coordinates.

## Root cause in the fusion UI

Before this repair,
`dual_sensor_fusion\run_dual_sensor_fusion_ui.py::_make_ti_args()` enabled:

- ONNX pose inference
- pose logging
- 3D text labels
- target-only inference fallback

It did not add:

- `--pose-human-models`
- `--pose-human-model-dir`
- `--pose-human-model-mode`
- model scale/height/ground settings
- `--pose-ground-plane`
- ground-plane size/grid/alpha settings

The underlying IWR launcher defaults human models and the ground plane to off,
so `attach_pose_manager()` correctly skipped both.

The fusion layout itself was not the cause. `_reflow_ti_window()` embeds the
existing TI `demoTabs`/`PeopleTracking` content in the left panel rather than
constructing a replacement 3D plot.

Demo mode had a second issue: `run()` explicitly used `pose_manager = None`.
It placed `_fusionDemoPose` data in synthetic frames for the fusion controller,
but `PeopleTracking` had no manager capable of returning
`get_3d_label_records()` or `get_3d_model_records()`.

## Implemented integration

### Fusion CLI and TI argument propagation

Modified:

```text
custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py
```

Key locations after the change:

- `DEFAULT_HUMAN_MODEL_DIR`: near line 21.
- model/ground CLI options: near lines 76-121.
- `_make_ti_args()`: near line 142.
- model and ground argument forwarding: near lines 166-205.
- input validation and model-directory resolution: near lines 1530-1555.

Defaults:

- human models: enabled
- ground plane: enabled
- model directory:
  `custom_iwr6843_fall_logger\ui_human_pose_models`
- mode: `overlay_box`
- standing target height: 1.70 m
- sitting target height: 1.20 m
- lying target length: 1.70 m
- ground Z: 0.0 m
- ground-plane size: 8.0 m
- ground-plane alpha: 0.18
- ground grid: enabled

`overlay_box` preserves the current TI target boxes while adding meshes.
`--no-pose-human-models` and `--no-pose-ground-plane` restore the prior
disabled behavior when needed.

The fusion launcher still uses the single established renderer path:

```text
fusion _make_ti_args()
  -> TI parse_args()
  -> create_pose_manager_before_qt()
  -> attach_pose_manager()
  -> HumanPoseModelRenderer
  -> PeopleTracking
  -> Plot3D
```

It does not instantiate a second live renderer.

### Offline demo adapter

`DemoPoseManager` starts near line 1314 in
`run_dual_sensor_fusion_ui.py`. It implements:

- `process_output_dict()`
- `get_3d_label_records()`
- `get_3d_model_records()`
- `close()`

The adapter is attached through the same `attach_pose_manager()` path as the
live manager. One stable target ID cycles every four seconds through:

```text
STANDING -> MOVING -> SITTING -> LYING -> FALLING
```

Mesh mapping is standing, standing, sitting, lying, lying respectively.
The existing synthetic AWR window and fusion dashboard remain active. No COM
port is opened in demo mode.

## What was intentionally not copied

- No reference Python file replaced a current Python file.
- No reference TI vendor directory replaced the current vendor directory.
- No AWR parser, firmware, TLV, fusion, logger, gate, estimator, or dashboard
  code was copied or changed.
- No GLB or preview asset was added because all reference assets are already
  present.
- No old top-level UI was substituted for the responsive fusion layout.

## Preserved behavior

- IWR point cloud, grid, target IDs, target boxes, and posture labels.
- ONNX classes `STANDING`, `SITTING`, `LYING`, and `FALLING`.
- Derived `MOVING` display state.
- Existing pose smoothing/stability and target identity.
- Current responsive left-IWR/right-AWR/bottom-vitals layout.
- AWR TLV `0xFE02` parsing and range-bin display.
- Expected/selected/fixed/strongest-bin markers.
- Fusion CSV logging and standalone dual-sensor logger.
- Sitting-only vital gate. Non-sitting postures still pause estimator updates.

## Tests added

`dual_sensor_fusion\test_dual_sensor_fusion.py` now verifies:

- meshes and ground plane are enabled by default;
- the default model directory is `ui_human_pose_models`;
- `overlay_box` is the default;
- negative flags disable models, ground plane, and grid;
- the demo adapter returns the expected standing, sitting, and lying OBJ names
  for all five display states.

## Validation commands

No hardware commands were run. Completed:

```powershell
python -m py_compile custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py custom_iwr6843_fall_logger\dual_sensor_fusion\test_dual_sensor_fusion.py

python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --help

python -m unittest custom_iwr6843_fall_logger.dual_sensor_fusion.test_dual_sensor_fusion -v

$env:QT_QPA_PLATFORM='offscreen'
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --pose-human-models --pose-ground-plane --window-width 1200 --window-height 750 --duration 2 --out "$env:TEMP\dual_fusion_demo_smoke"
```

All seven offline unit tests passed. The two-second demo process also exited
successfully without serial access. The offscreen Qt platform cannot create an
OpenGL context, so that smoke test validates startup, attachment, timers, and
shutdown but cannot visually validate mesh rendering. The visual mesh check
must be run on the normal desktop Qt platform.

## Recommended offline visual check

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --pose-human-models --pose-ground-plane --layout-debug --window-width 1600 --window-height 950
```

Expected:

- one target remains ID 1;
- target box and mesh are both visible;
- the mesh changes standing -> standing/moving -> sitting -> lying -> falling;
- the model base remains on the ground plane;
- AWR range-bin and vital/fusion panels continue updating;
- vitals are active only during the stable sitting interval.

## Recommended live check

After the offline visual check:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1600 --window-height 950 --debug
```

This live command is intentionally documented but was not executed during this
task.
