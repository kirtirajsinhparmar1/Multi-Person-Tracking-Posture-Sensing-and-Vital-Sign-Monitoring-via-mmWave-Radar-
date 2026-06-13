# IWR6843 Standalone Fall Logger And Visualizer

This project is a standalone Python implementation for the IWR6843ISK-ODS 3D People Tracking demo. It sends the radar cfg over the CLI/config port, reads people-tracking UART frames from the data port, reproduces TI Industrial Visualizer's height-drop fall-detection behavior, shows a live 3D view, and writes CSV logs for future posture classification.

No TI source files are modified or imported at runtime.

## Relationship To TI Visualizer Fall Detection

TI's visualizer fall detector is implemented in:

- `tools\visualizers\Applications_Visualizer\common\Demo_Classes\Helper_Classes\fall_detection.py`
- `tools\visualizers\Applications_Visualizer\common\Demo_Classes\people_tracking.py`

The original algorithm uses `heightData` and `trackData`. The UI only evaluates a height record when its TID matches a track TID (`people_tracking.py:119-135`). The detector keeps one height history deque per TID, with defaults `maxNumTracks=10`, `frameTime=55 ms`, `fallingThresholdProportion=0.6`, and `secondsInFallBuffer=2.5` (`fall_detection.py:31-40`). It appends current `maxZ` and triggers a fall when:

```text
current_height < fallingThresholdProportion * oldest_height
```

That is the same check used by TI (`fall_detection.py:60-65`). Once triggered, the display hold counter remains active for 100 frames (`fall_detection.py:39-40`, `fall_detection.py:65`). Track histories are reset when a previously seen TID disappears (`fall_detection.py:68-73`).

The sensitivity slider maps 0..100 to a threshold proportion of 0.4..0.8, matching TI's UI mapping (`people_tracking.py:224-225`). Larger values are more sensitive.

## Hardware Setup

Hardware:

```text
IWR6843ISK-ODS
```

Working firmware:

```text
source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\prebuilt_binaries\3D_people_track_6843_demo.bin
```

Working config:

```text
source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg
```

Board mode:

```text
IWR6843ISK-ODS must be in functional mode: OFF OFF ON ON OFF
```

COM ports:

```text
COM7 = Enhanced / CLI / config, 115200 baud
COM6 = Standard / data, 921600 baud
```

The terminal logger and UI can send the cfg over COM7 before reading COM6. This fixes the common magic-word timeout caused by reading the data port before `sensorStart`.

## Install

From the Radar Toolbox root:

```powershell
cd C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05
pip install -r custom_iwr6843_fall_logger\requirements.txt
```

The default `requirements.txt` supports the custom PyQt5 logger/visualizer path. The TI-style vendored UI keeps TI's PySide2 imports, but this project provides a local PySide2 compatibility shim backed by PySide6:

```powershell
python -m pip install -r custom_iwr6843_fall_logger\requirements_ti_style.txt
```

Python 3.11 is supported for the TI-style UI through the vendored `ti_style_vendor\PySide2` shim.

Dependencies:

- `pyserial`
- `numpy`
- `PyQt5`
- `pyqtgraph`

## Terminal Logger

From the Radar Toolbox root:

```powershell
python custom_iwr6843_fall_logger\run_fall_logger.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out custom_iwr6843_fall_logger\logs\fall_test1
```

From inside this folder:

```powershell
python run_fall_logger.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs/fall_test1
```

Skip cfg sending only when the radar is already running:

```powershell
python run_fall_logger.py --no-send-cfg --data COM6 --baud 921600 --out logs/fall_test1
```

Example live output:

```text
Frame 1234 | TID 1 | height 1.62 m | fall=False
Frame 1300 | TID 1 | height 0.62 m | fall=True | drop_ratio=0.38
```

## TI-style visualizer mode

Recommended UI:

```powershell
python custom_iwr6843_fall_logger\run_ti_style_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs/ti_style_ui_test1
```

`run_ti_style_visualizer.py` uses TI's vendored PySide2-style UI through the local PySide6 compatibility shim. It runs a vendored copy of TI's Industrial Visualizer code from:

```text
custom_iwr6843_fall_logger\ti_style_vendor
```

It uses TI's `gui_core.Window`, `Demo_Classes.people_tracking.PeopleTracking`, `Common_Tabs.plot_3d.Plot3D`, `gui_parser.UARTParser`, `parseFrame.py`, `parseTLVs.py`, and `tlv_defines.py`. The launcher preselects `xWR6843` and `3D People Tracking`, fills in COM7/COM6, loads `ODS_6m_default.cfg`, and by default calls TI's own Connect and Start/Send Configuration callbacks after the window opens.

Install dependencies:

```powershell
python -m pip install -r custom_iwr6843_fall_logger\requirements_ti_style.txt
```

Recommended Python: Python 3.11 with `requirements_ti_style.txt`. The vendored TI files still import `PySide2`, and `ti_style_vendor\PySide2` redirects those imports to PySide6.

Useful options:

```powershell
python custom_iwr6843_fall_logger\run_ti_style_visualizer.py --help
python custom_iwr6843_fall_logger\run_ti_style_visualizer.py --no-auto-start --debug
```

If `--no-auto-start` is used, the UI is prefilled but does not open COM ports. Manual steps:

1. Confirm Device is `xWR6843`.
2. Confirm Demo is `3D People Tracking`.
3. Confirm CLI is `COM7`, data is `COM6`, and the cfg path is `ODS_6m_default.cfg`.
4. Click `Connect`.
5. Click `Start and Send Configuration`.

Troubleshooting:

- Close the original TI Visualizer before using this.
- Close UniFlash and any serial terminals.
- Board must be in functional mode: `OFF OFF ON ON OFF`.
- `COM7` is Enhanced/CLI/config at 115200 baud.
- `COM6` is Standard/data at 921600 baud.
- The cfg must end with `sensorStart`.
- If no point cloud appears, verify the terminal logger receives frames.
- If UI import fails, check dependencies and vendored image/resource paths.

## TI-style UI with live pose labels

Install the ONNX runtime dependency:

```powershell
python -m pip install onnxruntime
```

Run the vendored TI-style UI with one posture prediction per tracked TID:

```powershell
python run_ti_style_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs\ti_pose_ui_4class --enable-pose --pose-model "model_experiments\outputs\ti_4class_clean_recording_robust_1600_fast\ti_pose_model.onnx" --pose-log --pose-debug
```

The pose model is disabled unless `--enable-pose` is passed. When enabled, the
left-side `Live Posture / Pose` table is the reliable display:

- Each tracked person gets an independent TID history and independent smoothed posture prediction.
- The first 8 frames per TID are warmup while the 176-feature window fills.
- The 4-class ONNX model returns `STANDING`, `SITTING`, `LYING`, and `FALLING`.
- `MOVING` is derived from target horizontal speed, not from the ML output.
- The table shows `TID`, `Final`, `PostureML`, `Motion`, `Conf`, `Points`, `Speed`, `HeightDrop`, `Quality`, and `Window`.
- `LOW POINTS` means the target had fewer than five associated point-cloud points for that frame.
- `LOW CONF` means the smoothed confidence is below `--pose-min-confidence`.
- Optional 3D text labels can be requested with `--pose-3d-labels`, but the Qt table is the primary display because GL text can be unstable under the PySide6 shim.

Close other programs using `COM6` or `COM7` before launching. First validate with
one person in the scene, then test two people. The model was trained on TI
IWRL6432 Pose/Fall data, so live IWR6843ISK-ODS accuracy must be validated.
Walking and falling can be confused; the smoothed label is more reliable than
the raw label. Do not perform unsafe falls; use controlled lie-down motion.
Point association quality matters, and low-quality rows should be treated
cautiously.

When `--pose-log` is used, these files are written under `--out`:

- `pose_predictions_ui.csv`
- `pose_ui_metadata.json`

## Experimental custom visualizer UI

`run_visualizer.py` uses the custom PyQt5 UI. It is retained as the older standalone/custom UI and can be used as a fallback while visual parity work focuses on the TI-style vendored mode.

From the Radar Toolbox root:

```powershell
python custom_iwr6843_fall_logger\run_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out custom_iwr6843_fall_logger\logs\ui_test1
```

From inside this folder:

```powershell
python run_visualizer.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --out logs/ui_test1
```

Default command:

```powershell
python custom_iwr6843_fall_logger\run_visualizer.py
```

Demo command, no radar hardware or COM ports:

```powershell
python custom_iwr6843_fall_logger\run_visualizer.py --demo
```

From inside this folder:

```powershell
python run_visualizer.py --demo
```

The UI provides:

- CLI and data port controls.
- Config file picker.
- Output log folder picker.
- Send Config button.
- Start Streaming and Stop buttons.
- Logging enable checkbox.
- Fall detection enable checkbox.
- Fall threshold/sensitivity slider.
- Left status panel with connection, frame, FPS, points, targets, presence, and warnings.
- Main 3D point cloud and target/trail view.
- Floor grid and X/Y/Z orientation axes.
- Wireframe boxes parsed from `boundaryBox`, `staticBoundaryBox`, and `presenceBoundaryBox`.
- Sensor marker and boresight indicator from `sensorPosition`.
- Target markers, target ID labels, target trails, and velocity vectors.
- Red target marker, `FALL` text, and alert panel when fall detection is active.
- Right target table with transformed position, velocity, height, fall status, and drop ratio/reason.
- Bottom console for CLI responses, parser errors, fall alerts, and log paths.

Demo mode generates a fake point cloud and two fake targets. One target falls after the history buffer warms up, so you should see point clusters, target labels, trails, boundary boxes, and the red fall alert without radar hardware.

Replay mode is a TODO. The `--replay` argument is accepted by the UI entry point but is not implemented yet.

## Stage 2: Pose Data Capture

`run_pose_capture.py` records labeled IWR6843ISK-ODS people-tracking data in TI Pose/Fall feature format:

- 22 features per frame.
- 8-frame per-target window.
- 176 float columns in channel-major order: `posz_f0..posz_f7`, `velx_f0..velx_f7`, through `snr4_f0..snr4_f7`.
- Labels: `standing`, `sitting`, `lying`, `falling`, `walking`.

The capture runner uses TLV `1011` target indexes to associate TLV `1020` points with each TLV `1010` target. It selects the five highest-z associated points per target and pads missing points with zeros. Low point-count rows are marked in `features_22.csv` and summarized by the dataset inspection tool.

Standing:

```powershell
python run_pose_capture.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --label standing --subject S01 --trial T01 --duration 60 --out dataset/iwr6843_pose
```

Sitting:

```powershell
python run_pose_capture.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --label sitting --subject S01 --trial T01 --duration 60 --out dataset/iwr6843_pose
```

Lying:

```powershell
python run_pose_capture.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --label lying --subject S01 --trial T01 --duration 60 --out dataset/iwr6843_pose
```

Walking:

```powershell
python run_pose_capture.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --label walking --subject S01 --trial T01 --duration 60 --out dataset/iwr6843_pose
```

Falling:

```powershell
python run_pose_capture.py --cli COM7 --data COM6 --cfg "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking\chirp_configs\ODS_6m_default.cfg" --label falling --subject S01 --trial T01 --duration 30 --out dataset/iwr6843_pose
```

Useful options:

```powershell
python run_pose_capture.py --help
python run_pose_capture.py --no-send-cfg --data COM6 --label standing --subject S01 --trial T01 --duration 60
python run_pose_capture.py --cli COM7 --data COM6 --label standing --subject S01 --trial T01 --target-id 1
```

Inspect captured data:

```powershell
python dataset_tools\inspect_pose_dataset.py --root dataset/iwr6843_pose
```

First capture rules:

- Use the same sensor mounting for all first captures.
- Start with one person in the scene.
- Keep the subject inside the configured boundary box.
- Capture at least 3 trials per label first.
- Later capture more subjects, angles, ranges, and rooms.
- Close TI Visualizer before running the capture script because COM6/COM7 are exclusive.

Each capture creates a self-contained folder:

```text
dataset\iwr6843_pose\S01\standing\T01_YYYYMMDD_HHMMSS
  metadata.json
  raw_points.csv
  targets.csv
  features_22.csv
  features_176.csv
  events.csv
```

## Required TLVs

The parser is standalone but mirrors TI's struct formats from `parseTLVs.py` and TLV IDs from `tlv_defines.py`.

Required for fall detection:

- `1010` target list, parsed as `I27f`
- `1012` target height, parsed as `I2f`

Useful for logging and future classification:

- `1011` target index, parsed as one unsigned byte per point
- `1020` compressed point cloud, parsed as `5f` units plus `2bh2H` point records
- `1021` presence, parsed as a 32-bit integer when present

## Logged Files

When logging is enabled, the output folder contains:

- `points.csv`: Cartesian point, spherical point, Doppler, SNR, and target index.
- `targets.csv`: target ID, position, velocity, acceleration, gain, and confidence.
- `heights.csv`: target ID, maxZ, and minZ from TLV `1012`.
- `fall_events.csv`: `frame,time,tid,is_fallen,current_height,old_height,drop_ratio,threshold,reason`.
- `frames_summary.csv`: frame counts, presence value, parse error, and total packet length.

## Troubleshooting

Magic word timeout usually means the cfg was not sent or `sensorStart` failed. Check:

- IWR6843ISK-ODS is in functional mode: `OFF OFF ON ON OFF`.
- COM7 is the Enhanced/CLI/config port and COM6 is the Standard/data port.
- The cfg sent successfully and `sensorStart` returned `Done`.
- TI Visualizer, UniFlash, PuTTY, TeraTerm, and other Python scripts are closed.
- Press S2 reset and rerun if the board is stuck.
- Confirm the flashed firmware is `3D_people_track_6843_demo.bin`.

If COM7 or COM6 is busy, close any program using that port and retry.

If the UI opens but no points appear:

1. Run demo mode first:

   ```powershell
   python custom_iwr6843_fall_logger\run_visualizer.py --demo
   ```

   If demo mode draws points, boxes, target labels, and trails, the UI render path is working.

2. Run the terminal logger and verify frames are received on COM6.

3. Check COM7/COM6 mapping.

4. Check that `sensorStart` returned `Done` in the console.

5. Close TI Visualizer, UniFlash, PuTTY, TeraTerm, and other Python scripts.

6. Verify parser stats in the bottom console show TLV `1020` point counts and TLV `1010` target counts. If points and targets are zero, the radar output is empty or the cfg did not enable those TLVs.

## Current Limitations

- Fall detection is TI-style height-drop heuristic, not a full activity classifier.
- Standing/sitting/lying/walking classification is not implemented yet.
- Target-height TLV `1012` is required for fall detection.
- The first 2.5 seconds are warm-up because TI initializes the height buffer with `-5`.
- The 3D view follows TI's display transform and scene concepts, but it is not a pixel-perfect copy of TI Industrial Visualizer.
- Replay mode is not implemented yet.

## Next Step

Use the CSV logs to build posture classification:

1. Start with rule-based standing/sitting/lying/walking states using target height, vertical spread, target velocity, and horizontal spread.
2. Label CSV segments as standing, sitting, lying, falling, walking, and unknown.
3. Train a small classifier using short temporal windows.
4. Add state smoothing and confidence thresholds before presenting posture labels in the GUI.
