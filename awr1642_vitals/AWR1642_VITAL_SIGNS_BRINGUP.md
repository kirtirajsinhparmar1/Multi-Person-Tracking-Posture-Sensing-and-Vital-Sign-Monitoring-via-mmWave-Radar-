# AWR1642 Vital Signs Bring-Up Notes

## Executive Summary

The local Radar Toolbox tree contains TI vital-sign demos for IWR6843 and IWRL6432, but no AWR1642/xWR16xx vital-sign demo, binary, configuration, or visualizer entry was found.

For AWR1642 vital-sign monitoring, do not flash the local IWR6843 or IWRL6432 vital-sign binaries. The correct next step is to obtain an AWR1642-compatible TI vital-sign lab package, commonly referenced as a legacy Driver Vital Signs or xWR16xx vital-sign lab, then verify its binary, cfg, and UI before flashing.

Best local reference demo:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking`

This is useful for understanding TI's current vital-sign visualizer and TLV parser, but it targets IWR6843ISK/IWR6843AOP, not AWR1642.

## File Map

### Documentation

- `applications\industrial\medical\vital_signs_monitoring.html`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\vital_signs_overview.html`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\docs\vital_signs_with_people_tracking_user_guide.html`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\docs\vital_signs_with_people_tracking_release_notes.html`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\docs\vital_signs_user_guide.html`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\docs\vital_signs_release_notes.html`

### Prebuilt Binaries

IWR6843 vital signs with people tracking:

- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\prebuilt_binaries\vital_signs_tracking_6843ISK_demo.bin`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\prebuilt_binaries\vital_signs_tracking_6843AOP_demo.bin`

IWRL6432 vital signs:

- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\prebuilt_binaries\vital_signs_xwrl64xx_demo.Release.appimage`

AWR1642 binaries found locally are not vital-sign binaries:

- `source\ti\examples\Out_Of_Box_Demo\prebuilt_binaries\out_of_box_1642.bin`
- `source\ti\examples\Fundamentals\CAN_Data_Output\1642_object_data_over_can\prebuilt_binaries\AWR1642BOOST\xwr16xx_odoc_ti_design_lab.bin`

### Configuration Files

IWR6843 vital signs with people tracking:

- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\chirp_configs\vital_signs_ISK_2m.cfg`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\chirp_configs\vital_signs_ISK_6m.cfg`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\chirp_configs\vital_signs_AOP_2m.cfg`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\chirp_configs\vital_signs_AOP_6m.cfg`

IWRL6432 vital signs:

- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\chirp_configs\Vital_Signs_With_Tracking_BOOST.cfg`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\chirp_configs\Vital_Signs_With_Tracking_AOP.cfg`

No AWR1642 vital-sign cfg was found in this local toolbox.

### UI / Visualizer

TI Applications Visualizer:

- Executable: `tools\visualizers\Applications_Visualizer\Industrial_Visualizer\Industrial_Visualizer.exe`
- Python entry point: `tools\visualizers\Applications_Visualizer\Industrial_Visualizer\gui_main.py`
- Vital-sign UI class: `tools\visualizers\Applications_Visualizer\common\Demo_Classes\vital_signs.py`
- Demo definitions: `tools\visualizers\Applications_Visualizer\common\demo_defines.py`
- Dependencies: `tools\visualizers\Applications_Visualizer\requirements.txt`

The visualizer defines `Vital Signs with People Tracking` for xWR6843 and xWRL6432 devices. xWR16/AWR1642 support was not found in the local Applications Visualizer demo list.

### Parser / TLV References

- `tools\visualizers\Applications_Visualizer\common\parseFrame.py`
- `tools\visualizers\Applications_Visualizer\common\parseTLVs.py`
- `tools\visualizers\Applications_Visualizer\common\tlv_defines.py`

### Source Code

IWR6843 vital signs with people tracking is documented locally as binary-only.

IWRL6432 vital signs source is present:

- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\src\6432\vitalsign.c`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\src\6432\vitalsign.h`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\src\6432\vitalsign_with_tracking.c`
- `source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\src\6432\main.c`

No AWR1642 vital-sign source was found locally.

### Matlab Tools

No Matlab vital-sign UI or AWR1642 vital-sign Matlab tool was found in this local toolbox search.

### Python Tools

- `tools\visualizers\Applications_Visualizer\Industrial_Visualizer\gui_main.py`
- `tools\visualizers\Applications_Visualizer\common\Demo_Classes\vital_signs.py`
- `custom_iwr6843_fall_logger\awr1642_vitals\inventory_awr1642_vitals.py`

## Candidate Demo Ranking

1. Required external candidate for AWR1642: legacy AWR1642/xWR16xx Driver Vital Signs lab. This is the correct class of demo to find before flashing AWR1642, but it is not present in this local Radar Toolbox tree.
2. Best local reference: `Vital_Signs_With_People_Tracking` for IWR6843ISK/IWR6843AOP. It includes binary, cfg files, TI visualizer support, and parsed breathing/heart-rate TLV fields.
3. Useful source reference: `IWRL6432_Vital_Signs`. It includes source code, cfg files, prebuilt appimage, and TI visualizer support, but it is not an AWR1642 demo.
4. AWR1642 local demos: Out Of Box, CAN output, short range radar, and other xWR16xx examples. These are not vital-sign demos and should not be used for breathing/heart-rate bring-up.

## Hardware Setup

- Bring up AWR1642 alone first.
- IWR6843 can remain disconnected during first AWR1642 vital-sign validation.
- Place one seated person still and chest-facing toward the radar.
- Expect vital signs to require a still target. The IWRL6432 vital-sign guide notes that accurate measurements require the tracked person to stop moving for about 30 seconds.
- For future fusion, mount IWR6843ISK-ODS and AWR1642 side by side, facing the same direction at approximately the same height. The first fusion version can treat range/angle coordinates as approximately aligned.

## Flashing Steps

No correct AWR1642 vital-sign binary was found in this local toolbox. Do not flash anything until an AWR1642-compatible vital-sign package is located.

When the correct AWR1642 package is available:

1. Confirm the binary explicitly targets AWR1642, IWR1642, xWR1642, or xWR16xx.
2. Confirm the cfg file belongs to that same binary and board.
3. Put the AWR1642 board into flashing mode as described by the AWR1642 EVM or lab guide.
4. Use UniFlash to program only the matching AWR1642 vital-sign binary.
5. Power cycle as directed by the lab guide.
6. Return the board to functional/run mode before launching the visualizer.

Do not flash:

- IWR6843 vital-sign binaries onto AWR1642.
- IWRL6432 appimages onto AWR1642.
- AWR1642 binaries onto IWR6843.
- Non-vital AWR1642 Out Of Box or CAN demos if the goal is breathing/heart-rate vital signs.

## TI UI Launch Steps

For local IWR6843/IWRL6432 vital-sign references, TI's visualizer is:

`tools\visualizers\Applications_Visualizer\Industrial_Visualizer\Industrial_Visualizer.exe`

Python source entry:

`tools\visualizers\Applications_Visualizer\Industrial_Visualizer\gui_main.py`

Python requirements listed locally:

- `PySide2==5.15.2.1`
- `numpy==1.19.4`
- `pyserial==3.5`
- `pyqtgraph==0.11.0`

Expected UI behavior for supported devices:

- Select the supported device and `Vital Signs with People Tracking` demo.
- Select CLI/config and data COM ports.
- Load the matching cfg file.
- Send cfg through the visualizer flow.
- Observe person tracking plus vital-sign widgets.
- Vital-sign panel displays patient status, breath rate, heart rate, range bin, breathing waveform, and heart waveform.

This visualizer support was found for xWR6843 and xWRL6432. AWR1642 support for this vital-sign UI was not found locally.

## Configuration Notes

### IWR6843 Vital Signs With People Tracking

Example short-range ISK cfg:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking\chirp_configs\vital_signs_ISK_2m.cfg`

Key commands found:

- `profileCfg 0 60.75 ...`
- `frameCfg 0 2 48 0 90.00 1 0`
- `staticBoundaryBox -1.5 1.5 0.3 1.75 0 3`
- `boundaryBox -1.5 1.5 0.5 2 0 3`
- `sensorPosition 2 0 15`
- `vitalsign 15 300`
- `VSRangeIdxCfg 0 21`
- `sensorStart`

The 6 m ISK cfg widens the boundary boxes and uses the same vital-sign-specific commands.

Recommendation for local reference testing on IWR6843ISK only: use `vital_signs_ISK_2m.cfg` for first chest-facing, seated, short-range validation.

### IWRL6432 Vital Signs

Example BOOST cfg:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs\chirp_configs\Vital_Signs_With_Tracking_BOOST.cfg`

Key commands found:

- `frameCfg 2 8 580 16 133 0`
- `guiMonitor 2 0 0 0 0 1 0 0 1 0 0`
- `boundaryBox -2 2 0 5 -0.5 3`
- `sensorPosition 0 0 1.1 0 0`
- `staticBoundaryBox -1 1 0.5 3 0 3`
- `baudRate 1250000`
- `sensorStart 0 0 0 0`

### AWR1642

No AWR1642 vital-sign cfg was found. Use only a cfg from the matching AWR1642 vital-sign lab once it is obtained.

## UART / TLV Format

The local TI Applications Visualizer defines vital signs as TLV ID 1040:

`MMWDEMO_OUTPUT_MSG_VITALSIGNS = 1040`

Parser:

`tools\visualizers\Applications_Visualizer\common\parseTLVs.py`

Payload struct:

`2H33f`

Parsed fields:

- `id`: uint16
- `rangeBin`: uint16
- `breathDeviation`: float32
- `heartRate`: float32
- `breathRate`: float32
- `heartWaveform`: 15 float32 samples
- `breathWaveform`: 15 float32 samples

The visualizer uses breath deviation, breath rate, heart rate, and waveform buffers for the UI. The docs state that patient status is derived using breath deviation, and heart rate is smoothed using a median over recent rates.

Important caveat: this TLV format is confirmed for the local IWR6843/IWRL6432 Applications Visualizer vital-sign path. The legacy AWR1642 vital-sign demo may use a different UART payload or visualizer parser. Verify the exact AWR1642 parser after obtaining that package.

## Data / Logging

The TI Applications Visualizer has generic logging support:

- `Save Data to File` writes replay JSON under `tools\visualizers\Applications_Visualizer\Industrial_Visualizer\binData\<timestamp>\`.
- Terminal output logging writes `logfile_...txt` from the visualizer.

No vital-sign-specific CSV logger was found in `vital_signs.py`.

For first AWR1642 validation, use the TI-provided logging mechanism from the AWR1642 lab if it differs from this Applications Visualizer.

## First Validation Test

1. Obtain the AWR1642-compatible vital-sign lab package.
2. Confirm binary, cfg, and UI all target AWR1642/xWR16xx.
3. Flash only the AWR1642 vital-sign binary.
4. Run AWR1642 alone with the matching TI UI.
5. Use one seated, still person with chest facing the radar.
6. Wait at least 30 seconds before judging heart-rate stability.
7. Confirm breathing BPM appears.
8. Confirm heart BPM appears.
9. Move deliberately and confirm the UI quality/status degrades as expected.

## Future Fusion With IWR6843

- IWR6843 remains the master tracking/posture sensor.
- AWR1642 remains the vital-sign specialist.
- Side-by-side mounting allows an initial approximate range/angle alignment.
- Fuse by timestamp plus range/angle proximity.
- Treat vitals as reliable only when the matched IWR6843 target is not MOVING.
- First fusion should be one person.
- Multi-person fusion needs ambiguity handling because AWR1642 vital signs may be single-target or selected-target only depending on the eventual AWR1642 lab.

## Open Questions

- Where is the AWR1642-compatible vital-sign lab package?
- What exact AWR1642 binary and cfg should be used?
- Does the AWR1642 lab use the same TLV 1040 payload as the local Applications Visualizer?
- What CLI/data baud rates does the AWR1642 lab require?
- Which AWR1642 EVM SOP switch pattern is required for flashing and run mode?
- Does the AWR1642 vital-sign UI support logging, and where are logs saved?
- Does the AWR1642 vital-sign algorithm support only one person, a selected person, or multiple people?

## Inventory Script

To rerun the local inventory:

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\inventory_awr1642_vitals.py --root C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05
```
