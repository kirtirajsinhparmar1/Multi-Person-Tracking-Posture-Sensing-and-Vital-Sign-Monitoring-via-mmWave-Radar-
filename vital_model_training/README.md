# Vital model training from selected FE03 chest beams

This directory is optional future tooling. It is not a prerequisite for the
live UI, the classical breathing/heart estimator, or current algorithm
improvements. No new dataset or supervised training is required to run the
system.

This pipeline builds quality-controlled phase/displacement windows from the
AWR1642BOOST UART FE03 beam selected by the dual-sensor fusion system. The
classical phase/PSD estimator remains the baseline; ML is optional.

This workflow does not use DCA1000, raw ADC capture, or LVDS parsing.

## Inputs

Each recording folder should contain `selected_chest_beam_trace.csv`.
`phase_diagnostics_summary.csv` can remain beside it for review. Accepted
windows require:

- `BEAM_LOCKED` or valid `BEAM_HOLD`;
- valid phase and one unchanged phase segment;
- active seated monitoring, including accepted pose-grace intervals;
- sufficient FE03-active samples;
- no beam switch inside the window.

The builder extracts wrapped phase, unwrapped phase, displacement, filtered
breathing/heart components, PSD peaks, SNR, spectral entropy, magnitude,
range/azimuth stability, and gate/beam quality metadata.

## Build training windows

Run this only when you intentionally want to prepare existing FE03 logs for
later ML training or evaluation. It slices valid locked-beam logs into
30-second windows; it is not a required next step.

```powershell
python custom_iwr6843_fall_logger\vital_model_training\build_training_windows_from_logs.py --logs logs\dual_sensor_chest_height_phase_30s --out custom_iwr6843_fall_logger\vital_model_training\outputs\first_dataset --window-sec 30 --stride-sec 5
```

Add `--include-60-sec` to create both 30- and 60-second windows. Useful quality
controls include:

```text
--min-valid-fraction 0.9
--min-fe03-active-fraction 0.8
--min-selected-magnitude 0
```

Outputs:

- `training_windows.npz`
- `training_windows.csv`
- `feature_table.csv`
- `dataset_summary.json`

## Reference labels

Supervised labels use:

```csv
recording_id,start_time_sec,end_time_sec,reference_heart_bpm,reference_breath_bpm
dual_sensor_chest_height_phase_30s,0,120,72,15
```

Use synchronized reference instruments and preserve their timing. Without
labels, feature extraction succeeds and model training reports
`reference_labels_required`.

## Train baseline models

```powershell
python custom_iwr6843_fall_logger\vital_model_training\train_vital_baseline_model.py --features custom_iwr6843_fall_logger\vital_model_training\outputs\first_dataset\feature_table.csv --labels path\to\reference_labels.csv --out custom_iwr6843_fall_logger\vital_model_training\outputs\first_model
```

When scikit-learn is available, the script trains separate random-forest or
gradient-boosting regressors for heart and breathing rates. It writes models,
metrics, predictions, and classical-versus-ML plots.

## Evaluate on logs

```powershell
python custom_iwr6843_fall_logger\vital_model_training\evaluate_vital_model_on_logs.py --model-dir custom_iwr6843_fall_logger\vital_model_training\outputs\first_model\models --logs logs\another_recording --out custom_iwr6843_fall_logger\vital_model_training\outputs\evaluation
```

## Optional UI inference

```text
--enable-vital-ml
--vital-model-dir custom_iwr6843_fall_logger\vital_model_training\outputs\first_model\models
--ml-min-window-sec 30
```

The UI always shows the classical estimate. ML values appear only when valid
models and enough locked data are available.

## Generic adapters

`public_dataset_adapters` supports generic phase/displacement CSV, generic
reference-label CSV, and this project's selected chest-beam trace format.
Public data must first be converted to phase/displacement windows. Do not
train on beam-searching, switched, lost, or posture-paused intervals.
