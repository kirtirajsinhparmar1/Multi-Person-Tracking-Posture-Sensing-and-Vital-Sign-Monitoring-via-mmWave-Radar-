# Twente / 4TU Sample Inspection

## Scope

Expected sample folder:

```text
custom_iwr6843_fall_logger\awr1642_vitals\external_research\data\twente_4tu_sample
```

Inspection date: 2026-06-13

## Folder Layout

The expected sample folder was not present in this workspace at inspection time.

```text
custom_iwr6843_fall_logger\awr1642_vitals\external_research\data\twente_4tu_sample
  [missing]
```

## File Types Found

| Category | Found | Notes |
|---|---:|---|
| README / metadata | No | Folder is missing. |
| Processed chest displacement | No | No processed sample files are present yet. |
| Range-map files | No | No range-map files are present yet. |
| Raw ADC files | No | No raw ADC files are present yet. |
| Reference heart/respiratory labels | No | No label/reference files are present yet. |
| Radar cfg / capture metadata | No | No cfg or capture metadata is present yet. |

## Immediately Usable Files

None yet. Add the Twente/4TU readme/metadata and a small processed sample under the expected folder, then run the baseline loader.

## Sample Rates

Unknown. No metadata file is present. The baseline runner accepts `--fs` so the sample rate can be supplied manually if it is not discoverable from metadata.

## Radar Config

Unknown. No radar cfg or DCA1000 capture metadata is present.

## Reference-Label Format

Unknown. No Polar H10 or reference-label file is present.

## Processed Displacement Loading

Processed displacement cannot be loaded yet because no sample files are present. The new baseline loader is intentionally flexible and can try common CSV, TXT, JSON, NPY, NPZ, and MAT formats.

## Raw ADC Parsing

Raw ADC parsing is not needed for the first baseline if processed chest displacement is downloaded. Raw ADC parsing should remain a later step and should be implemented from the dataset metadata plus TI SWRA581, not guessed.

## Open Questions

- What is the exact processed displacement filename and format?
- Is the processed displacement in meters, millimeters, phase radians, or normalized units?
- What is the processed signal sample rate?
- Are reference labels stored per sample, per recording, or per scenario?
- Does the small sample include radar cfg and DCA1000 capture metadata?
- Are range maps stored as CSV, MAT, NumPy, or another matrix format?

## Next Inspection Command

After placing the sample files under the expected folder:

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\twente_baseline\run_twente_baseline.py --root custom_iwr6843_fall_logger\awr1642_vitals\external_research\data\twente_4tu_sample --fs 20
```

If metadata contains a reliable sample rate, omit `--fs`.
