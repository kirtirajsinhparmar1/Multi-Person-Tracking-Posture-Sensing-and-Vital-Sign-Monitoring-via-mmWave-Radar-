# AWR1642 FE03 Reader Usage

## Purpose

`run_live_vital_phase_virtual_ant_window_reader.py` validates AWR TLV
`0xFE03`. FE03 contains raw int16 complex I/Q for every virtual azimuth
antenna over bins 20 through 60.

The reader performs PC-side azimuth beamforming. It does not configure or
flash the radar and it opens only the AWR data COM port.

## Payload

```text
Header: <IHHHHf
    frameNumber
    startBin
    numBins
    numVirtualAntennas
    flags
    rangeResolution

Samples: numBins * numVirtualAntennas records of <hh
    iValue
    qValue
```

Samples are ordered by range bin, then virtual antenna.

## Command

After the FE03 firmware has been built, flashed intentionally, and configured
through the separate CLI port:

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_live_vital_phase_virtual_ant_window_reader.py --data-com COM8 --baud 921600 --duration 30 --out logs\awr1642_fe03_check --debug --expected-range 1.75 --expected-azimuth 0
```

Useful beam-search options:

```text
--range-search-half-width 4
--azimuth-search-half-width-deg 15
--angle-min-deg -60
--angle-max-deg 60
--angle-step-deg 2
--antenna-spacing-lambda 0.5
--window-type none
```

## Output

- `virtual_ant_window_samples.csv`: raw I/Q by frame, range bin, and antenna.
- `range_azimuth_beam_trace.csv`: strongest and selected beam cells.
- `selected_beam_phase.csv`: selected complex beam, phase, and magnitude.
- `final_summary.json`: run counts and final selection.

The console prints frame dimensions, strongest range/azimuth, and the
chest-guided selected cell when expected range/azimuth are supplied.

## Assumption and calibration

The initial beamformer assumes an ordered lambda/2 uniform linear array.
Verify channel order, steering sign, angular bias, and per-channel complex
calibration with known reflectors before treating the reported angle as a
calibrated physical azimuth.

This is azimuth beamforming only. AWR elevation remains unavailable in the
active aperture/configuration.

