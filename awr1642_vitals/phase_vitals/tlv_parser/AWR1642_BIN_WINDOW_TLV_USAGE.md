# AWR1642 Bin-Window I/Q TLV

The copied AWR1642 non-OS firmware emits a real zero-Doppler complex range-bin
window as custom TLV `0xFE02`. It is appended after the existing `0xFE01`
VitalPhaseTrace TLV; `0xFE01` remains available in fake and real fixed-bin
modes.

The source is virtual azimuth antenna index zero in
`obj->azimuthStaticHeatMap`. The firmware does not choose a maximum or associate
a person with a range bin. Those decisions remain on the PC side for fusion
with IWR6843 people tracking.

## Payload layout

All integer and floating-point fields are little-endian.

`VitalPhaseBinWindowHeader` is 12 bytes:

| Field | Type |
|---|---|
| `frameNumber` | `uint32_t` |
| `startBin` | `uint16_t` |
| `numBins` | `uint16_t` |
| `rangeResolution` | `float` |

Each following `VitalPhaseBinSample` is 24 bytes:

| Field | Type |
|---|---|
| `binIndex` | `uint16_t` |
| `reserved` | `uint16_t` |
| `rangeMeters` | `float` |
| `iValue` | `float` |
| `qValue` | `float` |
| `phaseRad` | `float` |
| `magnitude` | `float` |

Payload length is:

```text
12 + numBins * 24
```

The default bins 20 through 60 produce a 996-byte payload.

## Firmware build defines

For the existing real fixed-bin `0xFE01` output plus the default `0xFE02`
window, add these DSS predefined symbols:

```text
VITAL_PHASE_MODE=1U
VITAL_PHASE_FIXED_RANGE_BIN=32U
VITAL_PHASE_WINDOW_START_BIN=20U
VITAL_PHASE_WINDOW_NUM_BINS=41U
```

The last two symbols are optional because 20 and 41 are source defaults. Keep
them explicit in CCS so the emitted range window is visible in the build
configuration. The fake `0xFE01` mode remains available by omitting
`VITAL_PHASE_MODE` or setting it to `0U`.

## Live reader

Only the AWR1642 data port is opened by this reader. Send the radar
configuration separately through the CLI/config port before starting it.

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_live_vital_phase_window_reader.py --data-com COM8 --baud 921600 --duration 60 --out logs\awr1642_bin_window
```

The reader prints the frame number, window bounds, and strongest-magnitude bin.
If `0xFE01` is also present, its fixed bin and phase are printed for comparison.

CSV is written to `vital_phase_bin_window_samples.csv` with:

```text
timestamp,frameNumber,binIndex,rangeMeters,iValue,qValue,phaseRad,magnitude
```

## Fusion use

The IWR6843 person track supplies a target range. PC-side fusion should map
that range to the closest AWR1642 bin, optionally search a small neighborhood,
and then use the selected bin's complex phase history. No IWR6843 firmware
change is required.
