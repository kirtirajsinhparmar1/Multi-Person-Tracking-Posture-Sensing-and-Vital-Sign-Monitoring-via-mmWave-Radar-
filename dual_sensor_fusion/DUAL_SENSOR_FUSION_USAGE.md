# Dual-Sensor Fusion Usage

This package fuses the existing IWR6843ISK-ODS people-tracking/posture stream
with AWR1642BOOST complex data. It prefers FE03 virtual-antenna windows for
chest-guided range-plus-azimuth selection and falls back to the existing FE02
range-bin window when FE03 is unavailable. Version 1 selects one primary IWR
target, but target-indexed gate, selection, and estimator state are structured
for later multi-person work.

## Fusion behavior

- IWR6843 supplies target ID, 3D position/range, velocity, and PC-side posture.
- AWR1642 FE03 supplies virtual-antenna complex I/Q for bins 20-60. FE02
  remains the range-only fallback.
- The IWR chest ROI supplies an expected range/azimuth prior; it is not a heart
  detector.
- The FE03 selector scores magnitude, distance from the IWR prior, and
  selection stability, with hysteresis before changing beams.
- Phase samples enter the vital estimator only after posture has remained
  `SITTING` for `--sitting-stable-frames`.
- After seated lock, brief `MOVING`, `UNKNOWN`, or `STANDING` flickers use a
  grace state. `LYING`, `FALLING`, sustained motion, and target loss pause.
- The AWR phase estimator runs at `--fs 10`, matching the 100 ms AWR frame
  period.
- BPM output remains preliminary until the observation windows and confidence
  checks are satisfied.

The initial transform assumes the two sensors are side by side, close together,
at the same height, and aimed in the same direction. Start with
`--use-iwr-range-direct`. Use `--dx`, `--dy`, `--dz`, and
`--yaw-offset-deg` only after collecting calibration logs.

## Logger-only command

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_logger.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_test --duration 90 --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --debug
```

The logger sends both cfg files, opens both data streams, runs the existing IWR
pose classifier, parses AWR TLV `0xFE02`, and writes:

- `iwr_targets.csv`
- `awr_bin_window_samples.csv`
- `fused_target_vitals.csv`
- `selected_bin_trace.csv`
- `ui_events.csv`
- `run_config.json`
- `fusion_summary.json`

Use `--primary-target-id N` to lock v1 to a known IWR target. Without it, the
nearest current target becomes primary and remains primary while present.

## UI command

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --debug
```

The left/central area is the existing TI IWR6843 3D tracking and pose UI. The
new right dock shows the AWR bin magnitudes and distinct markers for:

- strongest overall AWR bin
- IWR-guided expected bin
- selected bin used for vitals
- fixed bin 32 reference

The bottom dock always shows target, posture, monitoring state, IWR range,
expected/selected AWR bins, selected range/magnitude, breathing, heart, quality,
motion, update time, and pause/selection reason. It shows
`Vitals paused — target not sitting` outside the stable sitting state.

Every UI run writes the same calibration CSV/JSON files as logger mode, plus
monitoring-state transitions in `ui_events.csv`.

## First test procedure

Physical setup:

1. Mount IWR6843ISK-ODS and AWR1642BOOST side by side.
2. Same direction.
3. Same height if possible.
4. Sensors fixed/taped down.
5. Person starts at 1.5–2.0 m.
6. Single person only.
7. Person first stands, then sits.
8. Vitals should remain paused while standing.
9. Vitals should start only after posture becomes stable SITTING.
10. Capture at least 90 seconds while seated.

Expected behavior:

- Left IWR view tracks the person and shows posture.
- Right AWR view shows bins 20–60.
- IWR expected bin should be near the selected AWR bin.
- Vital panel should show paused while not sitting.
- Vital panel should show breathing/heart only when sitting.
- `fused_target_vitals.csv` should show `monitoringState` transitions.

After the test, compare `iwrRangeMeters`, `expectedAwrBin`,
`selectedAwrRangeMeters`, and `selectedAwrBin` in the fused and selected-bin
logs. A consistently biased range is evidence for sensor offset calibration;
rapid selected-bin changes indicate that hysteresis/search width or physical
alignment needs adjustment.

## Offline verification

No serial ports are opened by this test:

```powershell
python -m unittest custom_iwr6843_fall_logger.dual_sensor_fusion.test_dual_sensor_fusion
```

It verifies a fake 1.75 m IWR target, a fake AWR 20–60 window with strongest bin
37, standing pause behavior, stable-sitting activation, and fused-state output.

## Responsive UI layout

The UI now uses three resizable regions:

- A 300–380 px scrollable sidebar for COM/configuration controls, statistics,
  plot controls, pose status, and a concise fusion summary.
- An upper main splitter with the existing IWR6843 3D tracking/pose view on the
  left and the AWR1642 focus/range-bin view on the right. The default width
  ratio is approximately 68/32.
- A bounded lower dashboard with Target/Posture, AWR Bin Selection, and Vitals
  cards.

The recommended display size is 1600 x 950 or larger. The minimum supported
window size is 1200 x 750. Splitter handles can be dragged to adjust all panel
proportions.

The existing IWR point cloud, grid, target boxes, tracking, and posture
processing remain unchanged. A compact strip above the IWR plot shows labels
such as `ID 13 | MOVING 55%` without relying on a long plot-edge label.

The AWR plot uses cyan for the expected bin, orange/red for the selected bin,
purple for fixed bin 32, and gold for the strongest overall bin. A compact
legend and selected range/magnitude strip remain under the plot.

### Responsive UI command

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --window-width 1600 --window-height 950 --debug
```

### IWR 3D Human Models / Pose Meshes

The fusion UI reuses the existing IWR pose pipeline and
`HumanPoseModelRenderer`; it does not create a separate IWR plot. Human meshes
and the ground plane are enabled by default and are attached through:

```text
run_dual_sensor_fusion_ui.py
  -> _make_ti_args()
  -> run_ti_style_visualizer.attach_pose_manager()
  -> PeopleTracking.setPoseHumanModelRenderer()
  -> Plot3D.updateHumanPoseModels()
```

The default model directory is:

```text
custom_iwr6843_fall_logger\ui_human_pose_models
```

Model selection is:

- `STANDING` and `MOVING`: `human_standing.obj`
- `SITTING`: `human_sitting.obj`
- `LYING` and `FALLING`: `human_lying.obj`

`overlay_box` is the default mode and keeps the TI target box visible with the
mesh. `replace_box` hides a target box only when its mesh is available.
`model_only` suppresses target boxes and is intended for mesh-focused display.

In `overlay_box` mode, the renderer now publishes each scaled mesh's actual
world-space bounds back to the TI tracking widget. The target rectangle uses
those bounds, so the mesh and box share the same target-ID position, X/Y
center, posture-specific dimensions, and ground-plane bottom. This avoids the
old mismatch between TI's fixed 0.5 x 0.5 x 1.0 m box and the independently
scaled 1.7 m standing model. If a mesh is unavailable, the normal TI fixed box
remains the fallback.

Useful options:

```text
--pose-human-models / --no-pose-human-models
--pose-human-model-dir PATH
--pose-human-model-mode overlay_box|replace_box|model_only
--pose-human-model-target-height 1.70
--pose-human-model-sitting-height 1.20
--pose-human-model-lying-length 1.70
--pose-human-model-ground-z 0.0
--pose-ground-plane / --no-pose-ground-plane
--pose-ground-plane-size 8.0
--pose-ground-plane-alpha 0.18
--pose-ground-plane-grid / --no-pose-ground-plane-grid
```

Live command with explicit model flags:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_test --fs 10 --search-half-width 4 --use-iwr-range-direct --sitting-stable-frames 10 --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1600 --window-height 950 --debug
```

Troubleshooting:

- No meshes: verify the three OBJ files exist in the model directory, then run
  with `--pose-human-model-debug`.
- Floating model: adjust `--pose-human-model-ground-z`; OBJ meshes are
  normalized to put their minimum Z on that plane.
- Model outside its rectangle: use `overlay_box`; its box is generated from
  the active mesh bounds. Confirm the target ID is present in both the pose
  table and 3D label, then enable `--pose-human-model-debug`.
- Wrong posture model: inspect the compact pose label first. Mesh selection
  follows the final displayed posture, not the raw per-frame classifier.
- Target box hidden: use `--pose-human-model-mode overlay_box`.
- Labels clipped or panels cramped: use at least `--window-width 1600
  --window-height 950` and resize the splitters.

### Monitoring states

- `MONITORING`: green; phase samples enter the vital estimator.
- `SEATED_LOCK`: green; seated monitoring remains active after the initial
  lock interval.
- `MONITORING_POSE_GRACE`: amber/blue; phase samples continue during a short
  display-pose flicker.
- `WAITING_FOR_SITTING`: blue/gray.
- `PAUSED_NOT_SITTING`: amber; the last estimate may be held briefly and
  marked stale.
- `POSTURE_UNSTABLE`: amber.
- `NO_TARGET` and `TARGET_LOST`: gray.
- `NO_AWR_WINDOW` and `NO_BIN`: red/orange.
- `BIN_SWITCHING`: amber.

Vital estimates start only after posture is stable `SITTING`. `SEATED_LOCK`
and `MONITORING_POSE_GRACE` continue estimator updates. A hard pause stops new
phase samples, while the last display estimate can remain visible for the
configured hold interval.

### Offline layout/demo mode

Demo mode opens no COM ports and does not load the ONNX classifier. Its pose
adapter cycles one synthetic IWR target through all display postures, generates
AWR bins 20–60 with strongest bin 37, and sends synthetic phase through the
normal fusion path. During the stable `SITTING` interval, the dashboard shows
demo breathing/heart values of 15/72 bpm while the estimator receives the
synthetic phase samples. Other postures keep vital monitoring paused.

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --layout-debug --window-width 1600 --window-height 950 --out logs\dual_sensor_fusion_layout_demo
```

The demo pose adapter cycles the same target identity through `STANDING`,
`MOVING`, `SITTING`, `LYING`, and `FALLING`. It emits the same 3D label and
model records as the live pose manager, so the standing, sitting, and lying
meshes can be checked without COM ports:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --pose-human-models --pose-ground-plane --layout-debug --window-width 1600 --window-height 950
```

`--layout-debug` draws dashed panel borders and prints panel dimensions every
three seconds. It is optional and does not affect normal fusion behavior.

## Chest-guided range selection

Chest targeting is enabled by default. The fusion engine estimates a
posture-aware torso point, transforms it into the AWR frame, and uses its range
to guide FE02 bin selection. The UI shows a cyan chest ROI marker plus expected
AWR azimuth/elevation and chest confidence.

Current FE02 data is still one virtual-antenna sample per range bin. The UI
therefore reports `RANGE_ONLY_CHEST_GUIDED`. Expected azimuth/elevation are
calibration metadata, not AWR angle beamforming.

Relevant options:

```text
--use-chest-targeting / --no-use-chest-targeting
--disable-chest-targeting
--chest-sitting-height 0.85
--chest-standing-height 1.35
--sensor-dx 0.0
--sensor-dy 0.0
--sensor-dz 0.0
--sensor-yaw-deg 0.0
--sensor-pitch-deg 0.0
--sensor-roll-deg 0.0
```

`sensor-dx/dy/dz` locate the AWR origin in the IWR frame. Angles describe AWR
orientation relative to IWR. Measure these values for the physical mount.
Use `--disable-chest-targeting` to reproduce legacy target-center range
selection.

Offline chest/UI check:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --demo-mode --use-chest-targeting --pose-human-models --pose-ground-plane --layout-debug --window-width 1600 --window-height 950 --out logs\dual_sensor_chest_demo
```

Live chest-guided command:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fusion_ui_chest --fs 10 --search-half-width 4 --use-chest-targeting --sensor-dx 0 --sensor-dy 0 --sensor-dz 0 --sensor-yaw-deg 0 --sensor-pitch-deg 0 --sensor-roll-deg 0 --sitting-stable-frames 10 --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1600 --window-height 950 --debug
```

## Pose flicker grace filter

Short `SITTING -> MOVING/UNKNOWN/STANDING -> SITTING` label flickers can
occur even when the seated person has not materially moved. After the target
has first reached stable `SITTING`, the gate establishes a seated lock and
tolerates these labels for 3.0 seconds by default.

During `SEATED_LOCK` and `MONITORING_POSE_GRACE`:

- phase samples continue to feed the vital estimator;
- the existing phase buffer and last estimates are preserved;
- the UI shows raw, stable/display, and gate posture separately;
- the UI keeps heart and breathing values visible and shows an amber warning
  during grace;
- target speed above `0.25 m/s` or an AWR selected-bin jump greater than two
  bins pauses immediately;
- `LYING` and `FALLING` pause immediately by default.

Tune or disable the filter with:

```text
--non-sitting-grace-sec 3.0
--max-grace-speed-mps 0.25
--sitting-lock-sec 5.0
--allow-standing-grace
--disable-pose-grace
```

The CSV logs append `poseGraceActive`, `nonSittingStreakSec`,
`graceRemainingSec`, `postureGateReason`, `rawPosture`, `stablePosture`, and
`gatePosture`. Disabling grace restores strict behavior.

## FE03 flicker handling

The fusion process retains the latest FE03 frame across a brief receive gap.
One missed frame no longer causes an immediate switch to FE02.

- FE03 age below `--fe03-stale-timeout-sec` keeps
  `RANGE_AZIMUTH_CHEST_GUIDED` active.
- FE03 older than the timeout uses FE02, if available, and reports
  `STALE_FE02_FALLBACK` plus `RANGE_ONLY_CHEST_GUIDED`.
- If neither FE03 nor FE02 is available, the state is `NO_AWR_WINDOW`.
- The UI shows FE03 age, latest frame number, and estimated FE03 frame rate.

```text
--fe03-stale-timeout-sec 2.0
```

## Chest ROI versus AWR selected beam

The `IWR chest ROI estimate` is an approximate torso prior derived from
tracking, posture, target geometry, and the human-model geometry. It is not a
heart detector.

FE03 provides the AWR virtual-antenna vector. The PC forms a range/azimuth map
and selects an `AWR selected chest beam` inside the IWR-guided ROI. The score
combines magnitude, distance from the expected range and azimuth, and
selection stability. Hysteresis and a switch hold interval reduce rapid
beam changes.

The selected phase is labeled `candidate chest displacement signal`.
Elevation remains IWR metadata only; this path does not claim AWR elevation
beamforming or final vital signs.

```text
--range-search-half-width 4
--azimuth-search-half-width-deg 20
--beam-hysteresis-ratio 1.15
--beam-switch-hold-sec 2.0
--beam-score-mode magnitude_roi_stability
```

The FE03 UI shows the range/azimuth heatmap, expected chest marker, selected
beam, selection score, switch count, selected phase/magnitude, antenna count,
and azimuth error. FE02 remains the automatic range-only fallback.

## Phase Diagnostics Tab

The main phase tab is intentionally limited to three waveform charts:

1. **Wrapped Phase** shows the valid locked-beam phase in radians, normally
   within `[-pi, pi]`.
2. **Unwrapped Phase** shows segment-relative phase. With
   `--phase-chart-mode displacement`, it instead shows chest displacement in
   millimetres derived from that phase.
3. **Breathing and Heartbeat Components** shows the estimated breathing-band
   component in blue and heart-band component in red. These filtered
   components are diagnostics, not guaranteed physiological truth.

The plots retain up to `--phase-plot-window-sec` internally but display only
the latest `--phase-visible-window-sec`. The default visible window is 60
seconds, so the waveform scrolls instead of compressing as a run gets longer.
Visible data is downsampled to `--plot-max-visible-points`.

Unwrapping is performed only on valid `BEAM_LOCKED` or valid `BEAM_HOLD`
samples from one continuity segment. A beam switch, `phaseSegmentId` change,
invalid sample, or FE03 gap longer than `--phase-gap-reset-sec` starts a new
baseline. The UI leaves a gap between segments and never draws a line across
unrelated beams.

```text
--phase-plot-window-sec 120
--phase-visible-window-sec 60
--phase-chart-mode phase
--phase-sign 1
--phase-unwrap-discontinuity-rad 3.14159
--phase-gap-reset-sec 1.0
--component-chart-normalize
```

If phase ramps or jumps unexpectedly, inspect `beamState`, `phaseSegmentId`,
FE03 gaps, locked magnitude, `--phase-sign`, and whether nearby-beam combining
changed the selected signal source. BPM remains available in the compact
metrics panel. PSD and heart-candidate debugging are available through the
offline plotter with `--include-vitals-debug`.

## BPM collection, smoothing, and display hold

The estimator separates collection readiness from display continuity:

- breathing needs at least `--min-vital-window-sec 30`;
- heart needs at least `--min-heart-window-sec 60`;
- BPM is smoothed over approximately `--bpm-smoothing-sec 10`;
- a previous valid estimate remains visible for
  `--vital-display-hold-sec 10` during a brief pause or missing update;
- held output is marked `HOLD`, `STALE`, or low confidence rather than being
  presented as a fresh result.

Recommended seated observation time:

- breathing collection: 30-60 seconds;
- heart collection: 60-120 seconds.

Before these windows are available, the UI reports `collecting...` or
`heart collecting...`. BPM is preliminary diagnostic output. Interpret it
with confidence, quality, beam stability, and the phase/spectrum plots.

## Diagnostic logging

The reliability path adds:

- `selected_chest_beam_trace.csv`: expected/selected range and azimuth,
  raw/unwrapped phase, magnitude, score, selection reason, FE03 age, gate
  state, and raw/stable/gate posture;
- `phase_diagnostics_summary.csv`: buffer duration, breath/heart peaks, peak
  power, confidence, and quality;
- existing FE03 logs including `awr_virtual_ant_window_samples.csv`,
  `awr_range_azimuth_heatmap_summary.csv`, and `selected_beam_phase.csv`.

Use these files to distinguish physiology from pose classification, FE03
staleness, and beam switching.

Live command after FE03 firmware has been built, flashed intentionally, and
verified with the AWR-only reader:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_fe03_phase_debug --fs 10 --search-half-width 4 --azimuth-search-half-width-deg 20 --use-chest-targeting --non-sitting-grace-sec 3.0 --fe03-stale-timeout-sec 2.0 --vital-display-hold-sec 10.0 --phase-plot-window-sec 120 --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1700 --window-height 1000 --debug
```

## AWR chest-height range-and-azimuth architecture

The recommended physical arrangement places the IWR6843ISK-ODS above the
AWR1642BOOST and places the AWR at seated chest height, aimed horizontally at
the subject. Enable this geometry with `--awr-chest-height-mode` (enabled by
default for the fusion UI/logger).

In this mode:

- IWR continues to provide target identity, posture, 3D location, human model,
  chest ROI prior, and IWR elevation metadata.
- The transformed AWR prior uses `sqrt(x_aw^2 + y_aw^2)` for horizontal range
  and `atan2(x_aw, y_aw)` for azimuth.
- IWR `z` and elevation are not used to choose an AWR beam.
- AWR1642BOOST FE03 performs range-and-azimuth selection only.
- Chest height is constrained mechanically by AWR placement. The software
  does not claim AWR elevation estimation.

The transform offsets locate the AWR origin in the IWR coordinate frame. For
an AWR mounted 0.75 m below the IWR, start calibration with:

```text
--sensor-dx 0 --sensor-dy 0 --sensor-dz -0.750 --sensor-yaw-deg 0
```

The aliases `--ignore-iwr-elevation-for-awr` and
`--awr-use-range-azimuth-only` also enable chest-height behavior.

## FE03 stream and beam states

FE03 liveness is determined only by successfully parsed FE03 TLV arrival:

- `FE03_ACTIVE`: a recent FE03 payload is available;
- `FE03_STALE`: a short receive gap is inside the configured hold timeout;
- `FE03_LOST`: the timeout has expired.

Beam acquisition is independent:

- `SEARCHING_BEAM` / `BEAM_CANDIDATE`: candidate may move inside the IWR ROI;
- `BEAM_LOCKED`: stable cell used for phase and vital estimation;
- `BEAM_HOLD`: a brief weak/missing candidate retains the existing lock;
- `BEAM_LOST`: no valid lock remains.

An active FE03 stream may therefore correctly display
`FE03_ACTIVE + SEARCHING_BEAM`. Seated/posture monitoring remains active while
the beam locks; the vital panel reports `beam locking...` instead of treating
beam search as a posture pause.

```text
--beam-lock-sec 2.0
--beam-hold-sec 3.0
--beam-switch-margin 1.5
--beam-switch-confirm-sec 2.0
--beam-max-jump-bins 1
--beam-max-jump-deg 6
```

The AWR plot uses separate markers: the expected IWR prior, a moving candidate
beam, and the stable locked chest beam.

## Locked phase and displacement

Only samples from `BEAM_LOCKED` or valid `BEAM_HOLD` enter the locked phase
trace. Unwrapping is performed independently for each beam-lock segment. A
beam switch starts a new phase segment, and plots never connect the two
segments.

Displacement is calculated as:

```text
displacement_mm = relative_phase_rad * wavelength_mm / (4*pi)
```

The defaults use a 77 GHz carrier, displacement display, 0.5-second display
smoothing, and a 20-second detrend window:

```text
--carrier-frequency-ghz 77
--phase-chart-mode displacement
--phase-smooth-sec 0.5
--phase-detrend-sec 20
--phase-plot-window-sec 120
```

Use the offline plotter after a run:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\plot_phase_diagnostics_from_log.py logs\dual_sensor_chest_height_phase\selected_chest_beam_trace.csv --out logs\dual_sensor_chest_height_phase\locked_phase_diagnostics.png
```

Recommended full-layout command:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\run_dual_sensor_fusion_ui.py --iwr-cli COM7 --iwr-data COM6 --iwr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --awr-cli COM9 --awr-data COM8 --awr-cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\chirp_config\profile_2d.cfg" --out logs\dual_sensor_chest_height_phase --fs 10 --search-half-width 4 --azimuth-search-half-width-deg 15 --use-chest-targeting --awr-chest-height-mode --sensor-dx 0.000 --sensor-dy 0.000 --sensor-dz -0.750 --sensor-yaw-deg 0 --sensor-pitch-deg 0 --sensor-roll-deg 0 --non-sitting-grace-sec 3.0 --fe03-stale-timeout-sec 2.0 --vital-display-hold-sec 10.0 --phase-plot-window-sec 120 --beam-lock-sec 2.0 --beam-hold-sec 3.0 --beam-switch-margin 1.5 --beam-switch-confirm-sec 2.0 --beam-max-jump-bins 1 --beam-max-jump-deg 6 --ui-layout full --phase-chart-mode displacement --pose-human-models --pose-ground-plane --pose-human-model-mode overlay_box --window-width 1700 --window-height 1000 --debug
```

## Thirty-second preliminary vital estimates

Training is not part of the required live workflow. The normal sequence is:

1. Run the UI and confirm `FE03_ACTIVE`.
2. Wait for the AWR chest beam to become `BEAM_LOCKED`.
3. Inspect the locked displacement chart for a continuous breathing-shaped
   waveform.
4. At 30 seconds of valid locked data, review the preliminary classical
   breathing and heart estimates.
5. Continue to 60-120 seconds for more reliable heart-rate stability.

The estimator uses only valid samples from the currently locked FE03 chest
beam. Before 30 seconds of continuous locked data, both rates display
`collecting...`. At 30 seconds it emits breathing and heart estimates marked
`PRELIMINARY_30S`. Heart rate is intentionally preliminary at that point; it
becomes materially more reliable after 60 seconds and should be judged using
its confidence and PSD peak quality.

Estimate states are:

- `COLLECTING`: insufficient continuous locked data;
- `PRELIMINARY_30S`: first estimate, confidence-scored;
- `STABLE`: enough duration and acceptable confidence;
- `HOLD`: a low-confidence or implausible jump was rejected;
- `LOW_CONFIDENCE`: a peak exists but is not trustworthy.

The display applies a rolling median/EMA and rejects low-confidence jumps
larger than 3 BPM/s for breathing or 10 BPM/s for heart rate. A held result
remains visible for `--vital-display-hold-sec`.

Relevant options:

```text
--min-estimation-window-sec 30
--min-vital-window-sec 30
--min-heart-window-sec 30
--breath-stable-window-sec 30
--heart-stable-window-sec 60
--bpm-smoothing-sec 10
--breath-max-jump-bpm-per-sec 3
--heart-max-jump-bpm-per-sec 10
```

## Heart peak tracking and false-drift prevention

Heart rate is not taken from whichever heart-band PSD peak is strongest at
the latest update. The estimator keeps the top heart-band candidates, scores
their SNR, sharpness, persistence, and respiration-harmonic risk, and tracks
the persistent candidate over time.

From 30 to 60 seconds the estimate uses the available recent locked segment
and remains `PRELIMINARY_30S`. After 60 seconds, HR uses only the latest
60-second rolling window. Older transients therefore do not accumulate in an
ever-growing PSD.

A candidate more than 15 BPM from the tracked HR must persist for the switch
confirmation interval and exceed the configured score margin. Until then:

- `SWITCH_PENDING` means a different peak is being evaluated but has not
  replaced the tracked HR.
- `HOLD_LAST_GOOD` means the prior confident HR remains displayed because
  the new candidate is weak, low-SNR, implausible, or not persistent.
- `LIKELY_RESP_HARMONIC` means the candidate is near 2x, 3x, or 4x the
  measured breathing frequency and receives a confidence penalty.

Smoothing is applied only around the same tracked peak. It does not blend
unrelated peaks, so a rejected 55 BPM candidate cannot gradually pull a
tracked 105 BPM result downward.

Relevant options:

```text
--heart-top-k-peaks 5
--heart-peak-persistence-sec 8
--heart-switch-confirm-sec 8
--heart-switch-margin 1.35
--heart-min-snr 3
--heart-min-confidence 0.35
--heart-preliminary-window-sec 30
--heart-window-sec 60
--breath-window-sec 30
```

Pass `phase_diagnostics_summary.csv` to the offline plotter to see the top-K
PSD candidates, respiration harmonic markers, raw candidate HR, tracked HR,
displayed HR, rejected candidates, and confidence history:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\plot_phase_diagnostics_from_log.py --input logs\dual_sensor_chest_height_phase_hr_tracking\selected_chest_beam_trace.csv --summary logs\dual_sensor_chest_height_phase_hr_tracking\phase_diagnostics_summary.csv --out-dir logs\dual_sensor_chest_height_phase_hr_tracking\phase_plots --window-sec 60 --save
```

## Advanced vital diagnostics

The primary phase tab is waveform-focused. For PSD, top-K heart candidates,
respiration-harmonic markers, confidence history, and rejected HR candidates,
run the offline phase plotter with `--include-vitals-debug`. A visible spectral
peak is not sufficient by itself; also check confidence, beam-lock age,
segment duration, and beam-switch count.

### Optional nearby-beam combining

The default signal remains the single locked chest beam. For noisy runs,
nearby-beam combining can phase-align a small range/azimuth neighborhood and
use it only when it preserves or improves signal quality:

```text
--enable-nearby-beam-combining
--nearby-beam-range-radius-bins 1
--nearby-beam-azimuth-radius-deg 6
--beam-combine-mode weighted
```

Modes are `best`, `weighted`, and `coherent`. The UI and CSV logs state
whether the active signal is `single_locked_beam` or a combined
locked-neighborhood signal. Combining never changes the beam-lock identity
and does not combine across people or distant cells.

Generate a complete offline diagnostic plot with:

```powershell
python custom_iwr6843_fall_logger\dual_sensor_fusion\plot_phase_diagnostics_from_log.py --input logs\dual_sensor_chest_height_phase_30s\selected_chest_beam_trace.csv --out-dir logs\dual_sensor_chest_height_phase_30s\phase_plots --window-sec 30 --save
```

## FE03 training-data and optional ML workflow

This section is optional future work. Building training windows is not
required to improve or run the live system, and the user does not need to
collect a labeled dataset now. The physics-based phase/PSD estimate remains
the primary output. Optional ML models operate on features extracted from
this project's UART FE03
`selected_chest_beam_trace.csv`; they do not replace beam locking or the
classical estimate.

Build feature windows:

```powershell
python custom_iwr6843_fall_logger\vital_model_training\build_training_windows_from_logs.py --logs logs\dual_sensor_chest_height_phase_30s --out custom_iwr6843_fall_logger\vital_model_training\outputs\first_dataset --window-sec 30 --stride-sec 5
```

After adding reference heart/breath labels:

```powershell
python custom_iwr6843_fall_logger\vital_model_training\train_vital_baseline_model.py --features custom_iwr6843_fall_logger\vital_model_training\outputs\first_dataset\feature_table.csv --labels path\to\reference_labels.csv --out custom_iwr6843_fall_logger\vital_model_training\outputs\first_model
```

Enable inference by pointing the UI at the generated `models` directory:

```text
--enable-vital-ml --vital-model-dir custom_iwr6843_fall_logger\vital_model_training\outputs\first_model\models
```

If models are absent or no model path is provided, the UI continues normally
with classical estimates and emits no model-required error. Public datasets
are usable only after conversion to the same locked phase/displacement
window representation. This workflow uses AWR1642BOOST UART FE03 output and
does not use DCA1000.

## Full UI layout and performance tuning

The full layout keeps the IWR 3D view, AWR range-azimuth view, status/vital
cards, and phase diagnostics. The overview uses resizable splitters, the
dense status panel is scrollable, and phase diagnostics are placed in their
own tab by default. Requested window dimensions are clamped to the available
desktop, which prevents oversized windows on high-DPI Windows displays.

The UI intentionally renders the latest state instead of replaying every
queued sensor frame. Sensor processing and CSV writes continue independently;
when rendering falls behind, stale display frames are discarded and the
newest FE02/FE03 state is shown. This reduces accumulated visual latency
without changing the recorded sensor data.

Default rendering rates are:

```text
--ui-update-hz 10
--heatmap-update-hz 5
--phase-plot-update-hz 5
--spectrum-update-hz 1
--plot-max-visible-points 1200
```

The phase curves use existing plot items with `setData()` and are downsampled
to the visible-point limit. PSD/filter calculations are cached and recomputed
at the spectrum rate rather than on every FE03 frame. CSV writes run on a
bounded background queue and flush in batches:

```text
--csv-flush-interval-sec 1
--csv-flush-rows 50
```

Layout controls:

```text
--ui-scale 1.0
--right-panel-width 420
--compact-metrics
--diagnostics-tabbed
```

Use `--no-diagnostics-tabbed` only when enough vertical space is available.
The right status panel remains scrollable, so metrics are not clipped when
the window is resized.

The performance section reports FE03 FPS, IWR FPS, UI FPS, UI and processing
latency, rendered plot points, phase-buffer duration, dropped display frames,
CSV backlog, and CSV flush age. Interpret them as follows:

- Low FE03 FPS indicates the input stream or parser is behind.
- Normal FE03 FPS with high processing latency indicates fusion/beam work.
- Normal processing latency with low UI FPS indicates plotting or the Qt
  event loop.
- A growing CSV backlog indicates disk logging is slower than production.
- Increasing dropped display frames with current sensor FPS is acceptable:
  it means stale visual states were skipped instead of accumulating lag.

### Expected controlled seated accuracy

These are engineering targets, not medical specifications:

- Breathing: approximately +/-1-2 BPM when the beam is locked and stable;
  a 30-second preliminary estimate may be +/-2-5 BPM.
- Heart: approximately +/-5-10 BPM after 60-120 seconds when lock and
  confidence are good; a 30-second preliminary estimate may be +/-10-20 BPM.
- Multi-person heart-rate accuracy is not guaranteed yet.

Trust the BPM output only after confirming a stable locked beam, continuous
phase segment, and clean displacement waveform.
