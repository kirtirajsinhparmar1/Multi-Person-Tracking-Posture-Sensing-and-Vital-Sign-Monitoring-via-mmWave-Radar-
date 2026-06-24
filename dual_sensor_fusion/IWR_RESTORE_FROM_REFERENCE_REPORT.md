# IWR Visualization Restore from Reference Repository

## Scope and safety

This work restores the IWR-side human-model/target-box visual relationship
inside the existing dual-sensor fusion UI. It does not change firmware, serial
configuration, AWR parsing, bin selection, vital estimation, posture gating,
or CSV schemas. No COM ports were opened and no hardware scripts were run.

Backup created before source changes:

```text
custom_iwr6843_fall_logger_backup_before_iwr_restore_20260620_152453
```

The backup contains the requested IWR/fusion UI files plus `gui_threads.py`,
which became part of the alignment fix.

## Reference repository

Reference path:

```text
custom_iwr6843_fall_logger_external_reference\old_multitracking_pose_repo
```

Clone/update status: successful and clean.

```text
commit: f95e65719d3342d61fb2519d09b69f7cad058582
date:   2026-06-16T18:35:24-04:00
title:  Update latest pose UI log
branch: main, aligned with origin/main
```

The reference repository was treated as read-only.

## Files compared

### Pose and posture algorithm

- `pose_feature_extractor.py`
- `pose_model_runtime.py`
- `fall_detector.py`
- `ti_style_pose_overlay.py`

`pose_feature_extractor.py`, `pose_model_runtime.py`, and `fall_detector.py`
are identical between the current and reference repositories. The core
classifier, feature windows, target association, smoothing, posture
transitions, MOVING derivation, sitting handling, and fall handling therefore
already match the reference.

The current `ti_style_pose_overlay.py` retains the reference pose logic and
adds later vital-sign manager integration and parser-error tolerance. Its
reference behavior is present in:

- `get_3d_label_records()` near line 419
- `get_3d_model_records()` near line 474
- `_model_asset_for_label()` near line 1000
- `_reset_stale_tracks()` near line 1016

Replacing this file with the reference version would remove newer vital
integration and was intentionally rejected.

### Human model renderer and assets

- `human_model_renderer.py`
- `ui_human_pose_models\human_standing.obj`
- `ui_human_pose_models\human_sitting.obj`
- `ui_human_pose_models\human_lying.obj`

Before this patch, `human_model_renderer.py` was identical to the reference.
Both versions:

- load OBJ vertices/faces with `load_obj_mesh()`;
- center each mesh in local X/Y;
- shift the mesh minimum Z to zero;
- cache one `GLMeshItem` per target ID;
- map STANDING/MOVING to the standing mesh;
- map SITTING to the sitting mesh;
- map LYING/FALLING to the lying mesh;
- use posture colors and hide stale target items;
- scale standing, sitting, and lying models from the configured target
  dimensions.

The current and reference OBJ files have identical vertex counts, face counts,
and geometric bounds. Their byte hashes differ because the text files are
formatted differently, but the loaded geometry is equivalent. No assets were
copied or overwritten.

### TI visualizer integration

- `run_ti_style_visualizer.py`
- `ti_style_vendor\common\Demo_Classes\people_tracking.py`
- `ti_style_vendor\common\Common_Tabs\plot_3d.py`
- `ti_style_vendor\common\gui_threads.py`

The current launcher is the reference launcher plus newer integration
features. The model attachment path remains:

```text
run_dual_sensor_fusion_ui.py
  -> _make_ti_args()
  -> run_ti_style_visualizer.attach_pose_manager()
  -> PeopleTracking.setPoseHumanModelRenderer()
  -> Plot3D.updateHumanPoseModels()
  -> HumanPoseModelRenderer.update_models()
```

`plot_3d.py` was identical to the reference before this patch.

`people_tracking.py` retains reference point-cloud, target transform, target
ID, 3D label, and model update behavior. Its visible pose table was modernized
for vital status. That table was not reverted because the fusion UI has a
dedicated vital workflow and the rendering pipeline itself is unchanged.

The dual-sensor fusion UI embeds this same TI `PeopleTracking`/`Plot3D`
instance. It does not create a simplified replacement IWR plot.

### Fusion and AWR components inspected but intentionally unchanged

- `dual_sensor_fusion\run_dual_sensor_fusion_ui.py`
- `dual_sensor_fusion\dual_sensor_logger.py`
- `dual_sensor_fusion\fusion_types.py`
- `dual_sensor_fusion\posture_gate.py`
- `dual_sensor_fusion\vital_estimator_bridge.py`
- `dual_sensor_fusion\awr_bin_selector.py`
- `awr1642_vitals` and FE01/FE02 parser code

The fusion UI already forwards human-model and ground-plane options, enables
both by default, and provides an offline `DemoPoseManager`. No AWR or fusion
logic change was needed for model alignment.

## Root cause of the model/box misalignment

The defect is present in both the reference and pre-patch current code.

The TI target thread drew every normal target with fixed half-extents:

```text
x radius = 0.25 m
y radius = 0.25 m
z radius = 0.50 m
```

This produced a fixed 0.50 x 0.50 x 1.00 m box centered on the tracker-reported
X/Y/Z. See:

- `graph_utilities.getBoxLinesCoords()` near line 259
- `gui_threads.updateQTTargetThread3D.drawTrack()` near line 97

The human renderer separately:

- centered the OBJ in local X/Y;
- placed its bottom at configured `ground_z`;
- scaled standing to about 1.70 m;
- scaled sitting to about 1.20 m;
- scaled lying to about 1.70 m horizontal length.

The box and model shared target X/Y, but they did not share vertical origin,
posture dimensions, or actual mesh bounds. A grounded 1.70 m model therefore
could not fit inside a fixed 1.00 m box centered on tracker Z. This was not a
pose-classification error and was not caused by the fusion UI embedding.

## Implemented alignment fix

### `human_model_renderer.py`

Modified:

- `HumanPoseModelRenderer.update_models()` near line 129
- `HumanPoseModelRenderer.get_world_bounds()` near line 316
- `_mesh_world_bounds()` near line 343

After each target mesh is scaled and translated, the renderer computes its
actual world-space bounds:

```text
(x-left, y-near, ground-bottom, x-right, y-far, model-top)
```

The normalized OBJ origin convention is documented in code:

- local X/Y are centered on the target;
- local minimum Z is zero;
- world X/Y use the tracked-person center;
- world bottom Z uses the configured ground plane;
- the bounds include a small visual padding.

Bounds are keyed by target ID and removed when that target/model is hidden.
This preserves model identity while targets move or change posture.

### `plot_3d.py`

Modified:

- `updateHumanPoseModels()` near line 98
- new `getHumanPoseModelBounds()`

The plot now returns active renderer bounds to the tracking layer. Existing
renderer failure handling remains intact.

### `people_tracking.py`

Modified:

- constructor state near line 89
- `updateGraph()` near line 128
- `updatePoseHumanModels()` near line 350

In `overlay_box` mode, the active model bounds are passed to the existing TI
target drawing thread. `replace_box` and `model_only` behavior is unchanged.
If no model is available, the normal TI fixed target box remains the fallback.

Point cloud drawing, target transforms, IDs, labels, pose processing, and
fusion callbacks were not changed.

### `gui_threads.py`

Modified:

- `updateQTTargetThread3D.__init__()` near line 74
- `drawTrack()` near line 97

The target thread accepts an optional per-target bounds map. For a target with
an active mesh, it draws the rectangle from the mesh's world-space bounds.
Otherwise, it calls the original `getBoxLinesCoords()` path.

## Resulting posture/model behavior

- STANDING: standing OBJ, configured upright height, grounded box/model.
- MOVING: standing OBJ with MOVING color, same grounded alignment.
- SITTING: sitting OBJ, configured sitting height, box follows sitting mesh.
- LYING: lying OBJ, configured horizontal length, box follows lying footprint.
- FALLING: lying OBJ with FALLING color, same target identity and grounding.
- Unknown/low-quality: original fallback policy remains in effect.
- Missing/stale target: renderer item and bounds are hidden/removed by TID.

The fix aligns the rectangle to the rendered body rather than forcing all
postures into TI's fixed one-meter target cube.

## Pose estimation and smoothing decision

Pose estimation logic was not changed.

Reason:

1. The reference and current feature extractor, model runtime, and fall
   detector are identical.
2. The current pose overlay contains the reference smoothing/display logic.
3. Current-only additions support vital-sign state and error tolerance.
4. The observed defect was geometric, not an algorithm difference.

The fusion vital gate continues to use stable displayed posture. It does not
consume raw unstable classifier output.

## Current CLI and demo behavior

The fusion UI retains:

- `--pose-human-models` / `--no-pose-human-models`
- `--pose-ground-plane` / `--no-pose-ground-plane`
- `--pose-human-model-mode overlay_box|replace_box|model_only`
- model directory, standing/sitting/lying scale options, ground Z, fallback,
  window size, layout debug, demo mode, and all existing IWR/AWR/fusion args.

Human models, ground plane, and `overlay_box` remain the defaults.

Demo mode uses one stable target ID and cycles:

```text
STANDING -> MOVING -> SITTING -> LYING -> FALLING
```

The same renderer/bounds/box path is used in demo and live modes. Demo mode
does not open COM ports.

## Tests added or extended

`dual_sensor_fusion\test_dual_sensor_fusion.py` now also verifies:

- posture-specific demo model selection;
- target ID remains stable in generated model records;
- computed mesh bounds share the requested target X/Y center;
- mesh and target-box bottom share the configured ground Z.

Existing fusion tests continue to cover bin selection, standing pause,
stable-sitting activation, and return to paused state.

## Validation completed

- `python -m py_compile` passed for every modified Python file.
- `python -m unittest custom_iwr6843_fall_logger.dual_sensor_fusion.test_dual_sensor_fusion -v`
  passed all 8 tests.
- `run_dual_sensor_fusion_ui.py --help` completed successfully and exposes
  the human-model, ground-plane, layout, demo, IWR, AWR, and fusion options.
- A two-second `--demo-mode` startup/shutdown smoke test completed with exit
  code 0 using Qt's offscreen platform. It did not open COM ports.
- The offscreen Qt backend cannot create an OpenGL context, so actual mesh,
  box, and ground-plane appearance still requires the documented local demo
  command or a live hardware run.

## Intentionally not copied from the reference

- No whole UI replacement: the current responsive fusion layout is newer.
- No reference pose-overlay replacement: it would remove current vital logic.
- No reference pose-table replacement: current status fields are needed.
- No asset overwrite: loaded mesh geometry is already equivalent.
- No AWR code: FE01, FE02, focus panel, bin selection, vitals, and logs were
  outside the alignment defect.

## Remaining assumptions and live verification

The renderer assumes the configured ground plane represents the physical floor
in the transformed IWR coordinate system. If the radar's sensor-height/tilt
configuration makes floor Z differ from zero, set:

```text
--pose-human-model-ground-z <floor-z>
```

The first live check should confirm:

1. box and model share the target's X/Y motion;
2. box bottom and feet/body bottom stay on the ground plane;
3. posture transitions replace mesh and box dimensions without changing TID;
4. target labels remain associated with the same person;
5. AWR expected/selected bins and vital gating behave exactly as before.

## Files modified in this restore

- `custom_iwr6843_fall_logger\human_model_renderer.py`
- `custom_iwr6843_fall_logger\ti_style_vendor\common\Common_Tabs\plot_3d.py`
- `custom_iwr6843_fall_logger\ti_style_vendor\common\gui_threads.py`
- `custom_iwr6843_fall_logger\ti_style_vendor\common\Demo_Classes\people_tracking.py`
- `custom_iwr6843_fall_logger\dual_sensor_fusion\test_dual_sensor_fusion.py`
- `custom_iwr6843_fall_logger\dual_sensor_fusion\DUAL_SENSOR_FUSION_USAGE.md`
- this report

No firmware, AWR parser, fusion engine, posture gate, vital estimator, or
logger schema file was modified.

## Commands

Offline visual validation:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --layout-debug --window-width 1600 --window-height 950
```

Expected live command:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1600 --window-height 950 --debug
```
