# TI Pose/Fall Model Reuse Report

## Scope

Investigated TI's Pose/Fall demo under:

`source/ti/examples/Industrial_and_Personal_Electronics/Pose_And_Fall_Detection`

No TI source files were modified. Created experiment files only under:

`custom_iwr6843_fall_logger/model_experiments`

## Model Artifacts Found

| Location | Type | Size | PC-loadable? | Notes |
| --- | --- | ---: | --- | --- |
| `src/xWRL6432/model/pose_model.a` | Static archive | 63,656 bytes | No | ARM ELF relocatable objects built by TI clang for Cortex-M4. Not a Windows DLL/shared library. |
| `src/xWRL6432/model/tvmgen_default.h` | C header | 884 bytes | N/A | Declares the TVM model C ABI. |
| `retraining_resources/pose_and_fall_model_training.ipynb` | Notebook | 38,830 bytes | Yes | PyTorch training notebook with an ONNX export cell. |
| `retraining_resources/modules/helper_functions.py` | Python helper | 10,451 bytes | Yes | Generic helper functions; no model weights. |
| `retraining_resources/dataset/classes.zip` | Dataset zip | 3,128,206 bytes | Yes | Contains 52 CSV recordings across falling, lying, sitting, standing, walking. |

Search result for requested model formats:

- Present in tree: `.a` only (`pose_model.a`).
- Present inside `classes.zip`: `.csv` only.
- Not found: `.onnx`, `.tflite`, `.pt`, `.pth`, `.keras`, `.pkl`, `.joblib`, `.h5`, `.npy`, `.npz`, `.json`, `.pb`.

## `pose_model.a` Feasibility

`pose_model.a` is a SysV-style archive containing `lib0.obj` and `lib1.obj`.

Observed object evidence:

- Member objects start with ELF magic.
- ELF machine is `0x28`, which is ARM.
- Strings include `TI clang version 14.0.6`, `aeabi`, `cortex-m4`, and `.ARM.attributes`.
- TVM symbols are present, including:
  - `tvmgen_default_run`
  - `tvmgen_default___tvm_main__`
  - `tvmgen_default_fused_nn_softmax`
  - dense/relu helper symbols

Conclusion:

- It is ARM Cortex-M4 embedded object code, not x86/x64 Windows code.
- It cannot realistically be loaded from Python on Windows via `ctypes`, `onnxruntime`, PyTorch, or normal dynamic loading.
- It is intended to be linked into the xWRL6432 embedded firmware build.
- It should not be expected to link directly into an IWR6843 build. IWR6843 uses a different device/software stack and processor/toolchain assumptions than xWRL6432. A port would require a compatible embedded build flow and ABI, not just copying the archive.

## `tvmgen_default.h`

The header declares:

- Input: `Tensor[(1, 176), float32]`
- Output: `Tensor[(1, 5), float32]`
- Input struct: `struct tvmgen_default_inputs { void* input_1; }`
- Output struct: `struct tvmgen_default_outputs { void* output; }`
- Entrypoint: `int32_t tvmgen_default_run(struct tvmgen_default_inputs*, struct tvmgen_default_outputs*)`

No explicit workspace struct or workspace pointer is declared in this header. Any workspace/static memory is internal to the generated object code.

## Notebook Findings

Class map:

```python
{0: "STANDING", 1: "SITTING", 2: "LYING", 3: "FALLING", 4: "WALKING"}
```

Feature settings:

- `WINDOW_SIZE = 8`
- `MIN_POINTS = 5`
- `FEATURE_COUNT = 22`

- Input size: `WINDOW_SIZE * FEATURE_COUNT = 176`
- Filtering in training:
  - `MAX_HEIGHT = 3`
  - `MIN_HEIGHT = -4`
  - `MAX_DISTANCE = 5`
  - `MIN_DISTANCE = -4`
  - require at least 5 usable points

Per-frame feature order from notebook and `pose.h`:

```text
posz,
velx, vely, velz,
accx, accy, accz,
y0, z0, snr0,
y1, z1, snr1,
y2, z2, snr2,
y3, z3, snr3,
y4, z4, snr4
```

Point extraction:

- For each row, collect point cloud points with `pointy`, `pointz`, and `snr`.
- Convert point `y` to target-relative `y`: `pointy - posy`.
- Sort points by `pointz`.
- With `LOWEST_POINTS_INCLUDED = False`, keep the 5 highest `pointz` points.
- Append each selected point as `relative_y, pointz, snr`.

Window/input ordering:

The notebook uses:

```python
df_dataList[j].loc[i:i + WINDOW_SIZE - 1, :].unstack().to_frame().T.values.tolist()
```

The deployed C `CreateFeatureVector()` performs the same channel-major interleave. Therefore the 176-float order is:

```text
posz_f0, posz_f1, ..., posz_f7,
velx_f0, velx_f1, ..., velx_f7,
...
snr4_f0, snr4_f1, ..., snr4_f7
```

This is not frame-major order.

Model architecture:

- PyTorch `nn.Module`
- BatchNorm1d(176)
- Linear 176 -> 64, ReLU
- BatchNorm1d(64)
- Linear 64 -> 32, ReLU
- BatchNorm1d(32)
- Linear 32 -> 16
- BatchNorm1d(16)
- Linear 16 -> 5
- Softmax over class dimension

Training procedure:

- Train/test split: 80/20
- DataLoader batch size: 64
- Optimizer: SGD
- Learning rate: `0.0001`
- Epochs: `1600`
- Loss: `CrossEntropyLoss`
- Metrics/plots: accuracy, multiclass F1, confusion matrix

Export procedure:

- The notebook exports ONNX with `torch.onnx.export(..., opset_version=11)`.
- The repo does not include a ready-made ONNX file or PyTorch checkpoint.
- Rebuilding a PC model requires rerunning training from the CSV dataset, then exporting.

Normalization/scaling:

- The markdown says feature data is normalized to `0 < X < 1`, but the visible code does not actually apply a scaler or normalization transform before training.
- CSV-derived values appear to be used as raw `float32`.
- SNR and coordinate units must therefore match the training data as closely as possible.

## Direct Answers

Can we directly load `pose_model.a` on PC?

No. It is ARM Cortex-M4 ELF object code in a static archive. It is not a PC model format and is not loadable from Python on Windows.

Can we export/rebuild a PC model from the notebook?

Yes, but not from the existing `.a` alone. The notebook defines a PyTorch model and ONNX export path. Because no checkpoint is present, the practical PC path is to retrain from the CSV dataset and export ONNX.

Can we use TI's dataset to train a PC model?

Yes. `classes.zip` contains CSV recordings for all five classes. The dataset is directly usable with a PC PyTorch training script after extracting or reading the zip.

Can we feed IWR6843 176-feature vectors to the TI model?

Structurally yes: the model expects `float32[1,176]` made from 22 features over 8 frames. Practically, the deployed `.a` cannot run on PC, so this is useful for a retrained/exported PC model or for comparing feature construction. Accuracy is uncertain until validated with IWR6843 data.

What exact feature order should the IWR6843 extractor produce?

Per frame:

```text
posz, velx, vely, velz, accx, accy, accz,
y0, z0, snr0, y1, z1, snr1, y2, z2, snr2, y3, z3, snr3, y4, z4, snr4
```

For 8 frames, flatten channel-major:

```text
for feature in FEATURE_NAMES_22:
    append feature over oldest-to-newest 8-frame window
```

Coordinate assumption for IWR6843:

- Use `z` as vertical height.
- Use point `y - target.y` as the relative lateral/range-like point feature only after confirming the local parser's coordinate convention.
- Do not copy the xWRL6432 demo mapping blindly: that code assigns `posX` into feature slot 0 and point `x` into the slot commented as `z`, which indicates a board-orientation transform.

## Sensor and Porting Risks

- IWRL6432 and IWR6843ISK-ODS differ in radar front end, antenna pattern, point-cloud density, tracker behavior, coordinate conventions, and mounting assumptions.
- The TI training code appears tied to the xWRL6432 demo's orientation. ODS normally reports `z` as vertical, so axis mapping must be validated with real captures.
- The model uses only five high points per frame. If the IWR6843 point cloud has different vertical spread or SNR scaling, class boundaries may shift.
- The notebook's normalization comment is not backed by visible scaler code, so unit mismatches go straight into the model.
- Target association matters. The 22 features should be built from points associated with the same tracked target, not all detected points in the scene.
- Falling/lying classes are especially sensitive to mounting height, tilt, room geometry, and tracker height estimates.

## Files Created

- `custom_iwr6843_fall_logger/model_experiments/TI_POSE_MODEL_REUSE_REPORT.md`
- `custom_iwr6843_fall_logger/model_experiments/ti_pose_feature_extractor.py`
- `custom_iwr6843_fall_logger/model_experiments/train_or_export_ti_pose_model.py`

## Recommended Next Step

Generate logged IWR6843 per-target CSV rows with the exact 22-feature order, build 8-frame channel-major vectors, then train/export a PC ONNX model from TI's dataset plus a small IWR6843 validation set. The first practical runtime target on PC should be ONNX Runtime, not `pose_model.a`.
