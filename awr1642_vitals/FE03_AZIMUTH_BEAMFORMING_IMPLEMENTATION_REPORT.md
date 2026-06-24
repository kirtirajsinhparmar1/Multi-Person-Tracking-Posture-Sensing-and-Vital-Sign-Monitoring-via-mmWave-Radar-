# FE03 Azimuth Beamforming Implementation Report

## Result

The copied AWR1642 non-OS experiment now defines and packages TLV `0xFE03`.
It exports the zero-Doppler complex value for every virtual azimuth antenna
over the configured range window. The PC parser reconstructs a
`[range bin, virtual antenna]` complex matrix and performs chest-guided
range-plus-azimuth beam selection.

FE01 and FE02 remain present and unchanged. The fusion engine prefers FE03
when available and falls back to the existing FE02
`RANGE_ONLY_CHEST_GUIDED` path otherwise.

No firmware was built or flashed during this task. No COM port was opened.

## Why FE02 was insufficient

FE02 exports one complex sample per range bin:

```text
azimuthStaticHeatMap[rangeBin * numVirtualAntAzim + 0]
```

This preserves range-bin phase but discards the spatial information across
the virtual antenna aperture. It cannot form or select an azimuth beam.

FE03 exports all `numVirtualAntAzim` samples for each requested range bin.
The PC can therefore evaluate a range-by-azimuth response and select the cell
nearest the IWR-derived chest range and azimuth.

## Firmware changes

Copied experiment only:

- `firmware_experiments/nonos_oob_16xx_vital_phase/src/1642/common/mmw_messages.h`
- `firmware_experiments/nonos_oob_16xx_vital_phase/src/1642/dss/dss_main.c`

New TLV:

```c
#define MMWDEMO_OUTPUT_MSG_VITAL_PHASE_VIRTUAL_ANT_WINDOW 0xFE03U
```

Compile-time defaults:

```c
#define VITAL_PHASE_FE03_ENABLE   1U
#define VITAL_PHASE_FE03_START_BIN 20U
#define VITAL_PHASE_FE03_NUM_BINS  41U
```

Set `VITAL_PHASE_FE03_ENABLE=0U` in the copied project if packet capacity or
UART loading must be isolated during troubleshooting.

## FE03 payload

Header, little-endian, 16 bytes:

| Field | Type |
|---|---|
| frameNumber | `uint32_t` |
| startBin | `uint16_t` |
| numBins | `uint16_t` |
| numVirtualAntennas | `uint16_t` |
| flags | `uint16_t` |
| rangeResolution | `float` |

Each sample is 4 bytes:

| Field | Type |
|---|---|
| iValue | `int16_t` |
| qValue | `int16_t` |

Samples are row-major:

```text
for range bin:
    for virtual azimuth antenna:
        int16 I, int16 Q
```

The source is:

```c
obj->azimuthStaticHeatMap[
    rangeBin * obj->numVirtualAntAzim + virtualAntennaIndex
]
```

`sample.real` is transmitted as `iValue`; `sample.imag` is transmitted as
`qValue`. Firmware performs no phase, magnitude, FFT, or beam selection.

## Size, bandwidth, and packet risk

For 41 bins and 8 virtual azimuth antennas:

```text
16 + 41 * 8 * 4 = 1328 bytes/frame
1328 * 10 Hz = 13,280 bytes/s
```

At 921600 baud with 8-N-1 framing, the theoretical payload ceiling is about
92,160 bytes/s. FE03 alone consumes about 14.4 percent of that ceiling.
FE01, FE02, TI packet/TLV headers, alignment, and any enabled standard OOB
TLVs also consume bandwidth.

The xWR16xx DSS HSRAM is 32 KB. The implementation checks the remaining
message-buffer capacity before writing FE03. If FE03 does not fit, it is
omitted while the already packed FE01/FE02 data remains valid. This prevents
an overwrite, but the host must treat missing FE03 as a fallback condition.

## PC parser

Created:

- `phase_vitals/tlv_parser/parse_vital_phase_virtual_ant_window_tlv.py`

Updated:

- `phase_vitals/tlv_parser/ti_uart_packet_parser.py`
- `phase_vitals/tlv_parser/fake_ti_uart_packet.py`

The parser uses:

```text
header: <IHHHHf
sample: <hh
```

It validates:

```text
payload length == 16 + numBins * numVirtualAntennas * 4
```

The resulting NumPy complex array has shape:

```text
[numBins, numVirtualAntennas]
```

FE01 and FE02 extraction APIs were not changed.

## PC azimuth beamforming

Created:

- `phase_vitals/azimuth_beamforming.py`

The initial beamformer:

1. Generates an angle grid, default `-60` to `+60` degrees in 2-degree steps.
2. Treats the virtual azimuth channels as an ordered uniform linear array.
3. Uses default spacing `0.5 lambda`.
4. Optionally applies a Hann aperture window.
5. Computes a complex beam response for every range/angle cell.
6. Restricts selection to the IWR chest-guided range and azimuth search area.
7. Selects the strongest cell and applies previous-selection hysteresis.
8. Uses the selected complex beam phase for the vital estimator.

Critical assumption:

> The current implementation assumes virtual azimuth antennas are ordered as
> a uniform linear array with lambda/2 spacing.

This is adequate for synthetic validation, but the channel order, steering
sign, and per-channel complex calibration must be verified against the
AWR1642BOOST/TI processing convention before interpreting live azimuth as
calibrated physical angle.

## AWR-only reader

Created:

- `phase_vitals/tlv_parser/run_live_vital_phase_virtual_ant_window_reader.py`
- `phase_vitals/tlv_parser/FE03_READER_USAGE.md`

It writes:

- `virtual_ant_window_samples.csv`
- `range_azimuth_beam_trace.csv`
- `selected_beam_phase.csv`
- `final_summary.json`

The script was syntax checked only. It was not run against a COM port.

## Fusion integration

Updated:

- `dual_sensor_fusion/fusion_types.py`
- `dual_sensor_fusion/dual_sensor_logger.py`
- `dual_sensor_fusion/run_dual_sensor_fusion_logger.py`
- `dual_sensor_fusion/run_dual_sensor_fusion_ui.py`
- `dual_sensor_fusion/test_dual_sensor_fusion.py`

Behavior:

```text
FE03 + valid chest ROI
    -> RANGE_AZIMUTH_CHEST_GUIDED
    -> beamformed selected complex phase

FE03 unavailable + FE02 available
    -> RANGE_ONLY_CHEST_GUIDED
    -> existing FE02 selected-bin phase

neither FE03 nor FE02
    -> NO_AWR_WINDOW
```

The sitting-only posture gate, pose-glitch grace state, chest ROI marker,
human models, AWR panel, and vital dashboard remain active.

New fusion logs:

- `awr_virtual_ant_window_samples.csv`
- `awr_range_azimuth_heatmap_summary.csv`
- `selected_beam_phase.csv`

New appended fused fields include selection mode, expected/selected azimuth,
azimuth error, antenna count, selected beam magnitude, and selected beam
phase.

The UI displays a range-azimuth heatmap when FE03 is current. If FE03 is
absent or stale, the existing FE02 range-bin display remains.

## Elevation limitation

The active AWR1642 path exposes `numVirtualAntAzim` and reports no independent
elevation virtual aperture. FE03 therefore supports one AWR angle dimension:
azimuth.

- Range: supported.
- Range plus azimuth: implemented, pending live geometry/calibration checks.
- Independent AWR elevation beamforming: not supported by the active aperture.
- Elevation: retained as IWR chest-ROI metadata only.

The correct mode name is `RANGE_AZIMUTH_CHEST_GUIDED`, not
range-azimuth-elevation.

## Offline tests

Passed:

- FE03 payload parser and FE01/FE02 coexistence.
- Synthetic 8-channel azimuth source recovery.
- Range/azimuth cell selection within the configured angular tolerance.
- Dual-sensor FE03 preference.
- FE02 fallback when FE03 is absent.
- Existing dual-sensor posture, chest, UI-argument, and human-model tests.

Hardware tests were intentionally not run.

## CCS source synchronization and build

The CCS projects contain copied source files. If the workspace is stale, copy
the modified files before rebuilding:

```powershell
$root = "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05"
$src = "$root\custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase\src\1642"
$ws = "$root\ccs_workspace_awr1642_vital_phase"

Copy-Item "$src\dss\dss_main.c" "$ws\AWR16xx_dss_nonOS\dss_main.c" -Force
Copy-Item "$src\common\mmw_messages.h" "$ws\AWR16xx_dss_nonOS\common\mmw_messages.h" -Force
Copy-Item "$src\common\mmw_messages.h" "$ws\AWR16xx_mss_nonOS\common\mmw_messages.h" -Force
```

Then in CCS:

1. Clean `AWR16xx_dss_nonOS`.
2. Build `AWR16xx_dss_nonOS`.
3. Clean `AWR16xx_mss_nonOS`.
4. Build `AWR16xx_mss_nonOS`.
5. Confirm the combined image exists at:

```text
ccs_workspace_awr1642_vital_phase\AWR16xx_mss_nonOS\Debug\xwr16xx_mmw_nonOS.bin
```

Only that final combined MSS image is the flash image. Flashing was not
performed by Codex.

## Recommended validation order

1. Build DSS/MSS and inspect packet size/build output.
2. Intentionally flash the new combined image.
3. Send the existing AWR cfg.
4. Run the AWR-only FE03 reader at broadside.
5. Move a strong reflector through known lateral positions to determine
   steering sign and angle bias.
6. Add per-antenna complex calibration if required.
7. Verify the dual-sensor UI changes from FE02 fallback to
   `RANGE_AZIMUTH_CHEST_GUIDED`.
8. Confirm range/azimuth selection remains stable while seated.
9. Only then evaluate the selected beam phase for vital signs.

