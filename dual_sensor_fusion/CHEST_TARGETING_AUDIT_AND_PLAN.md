# Chest Targeting Audit and Implementation Plan

## Executive conclusion

The existing FE02 fusion path is range-only. It exports one complex sample per
range bin from virtual azimuth antenna index 0, so it cannot perform angle
beamforming. This update adds an IWR-derived chest point, a calibrated 3D
IWR-to-AWR transform, expected AWR range/azimuth/elevation metadata, and
chest-guided FE02 range-bin selection.

The current system must be described as **RANGE_ONLY_CHEST_GUIDED**. It is not
range-plus-angle beamforming.

For the current AWR1642BOOST profile and xWR16xx data path:

- Range processing: supported.
- Range + azimuth processing: feasible after exporting all eight azimuth
  virtual-antenna complex samples for the selected range window.
- True range + azimuth + elevation beamforming: not supported by the current
  board aperture/configuration. The local firmware computes
  `numVirtualAntElev = 0`.
- Elevation should remain an IWR-derived chest ROI constraint/metadata field.

No firmware was modified by this task.

## Current range-only limitation

The working FE02 firmware reads:

```c
sampleIndex = rangeBin * obj->numVirtualAntAzim;
complexSample = obj->azimuthStaticHeatMap[sampleIndex];
```

This is antenna index 0 only. See
`awr1642_vitals/firmware_experiments/nonos_oob_16xx_vital_phase/src/1642/dss/dss_main.c`
around lines 960-1020. FE02 therefore preserves real I/Q versus range but
discards the across-antenna phase differences needed for angle estimation.

The prior PC selector used generic target range. A tracked centroid can be
below, above, or displaced from the torso. For seated vital monitoring, that
can choose a range bin that is not centered on the chest.

## Chest point estimator

Implemented in `dual_sensor_fusion/chest_point_estimator.py`.

Inputs:

- IWR target center `(x, y, z)`.
- Stable displayed posture.
- Optional tracker/pose `groundZ`.
- Optional target/person height.
- Configured posture-specific torso heights and small lateral/forward offsets.

Coordinate convention:

- `x`: lateral/right.
- `y`: forward/boresight.
- `z`: up.

Rules:

- `SITTING`: use approximately 70% of available target height, clamped to
  0.65-0.85 m above ground; fallback is 0.85 m.
- `STANDING`/`MOVING`: use approximately 78% of target height, clamped to
  1.20-1.40 m; fallback is 1.35 m.
- `LYING`/`FALLING`: use approximately half the target height, clamped to
  0.25-0.45 m; fallback is 0.35 m.
- `UNKNOWN`: upright fallback with reduced confidence.

The estimator emits `ChestPointEstimate`, including confidence, method, and
notes identifying assumed ground/height values. Vital monitoring remains
controlled by the existing stable-SITTING gate.

## IWR-to-AWR transform

Implemented in `dual_sensor_fusion/coordinate_transform.py`.

`dx`, `dy`, and `dz` specify the AWR origin in IWR coordinates. Yaw, pitch,
and roll specify AWR orientation relative to IWR. With rotation matrix
`R = Rz(yaw) Ry(pitch) Rx(roll)`:

```text
p_awr = transpose(R) * (p_iwr - [dx, dy, dz])
```

For transformed chest point `(X, Y, Z)`:

```text
range = sqrt(X^2 + Y^2 + Z^2)
azimuth = atan2(X, Y)
horizontalRange = sqrt(X^2 + Y^2)
elevation = atan2(Z, horizontalRange)
expectedRangeBin = round(range / rangeResolution)
```

Positive azimuth is toward positive lateral `x`; positive elevation is above
the AWR horizontal plane. Initial calibration assumes sensors are side by
side, level, and pointed in the same direction.

## Implemented data flow

```text
IWR target + stable posture + height/ground metadata
                    |
                    v
          ChestPointEstimate (IWR frame)
                    |
          calibrated rigid transform
                    v
 AwrSpatialTarget(range, azimuth, elevation, expected bin)
                    |
                    v
 FE02 range-window search + existing magnitude hysteresis
                    |
                    v
 selected FE02 range bin, phase, magnitude
```

`dual_sensor_fusion/fusion_types.py` now contains:

- `ChestPointEstimate`
- `AwrSpatialTarget`
- `SpatialBinSelection`

`dual_sensor_fusion/dual_sensor_logger.py` now:

- preserves optional IWR ground/height metadata;
- estimates chest and spatial target for every selected target;
- uses chest-derived range by default;
- preserves legacy target-center selection with
  `--disable-chest-targeting`;
- logs chest confidence, expected azimuth/elevation, selection mode, and the
  FE02 limitation warning;
- leaves posture gating and estimator update rules unchanged.

## UI changes

`dual_sensor_fusion/run_dual_sensor_fusion_ui.py` keeps the existing responsive
IWR/AWR/vital layout and adds:

- a cyan chest ROI marker in the existing IWR `Plot3D` coordinate system;
- chest ROI confidence;
- expected AWR azimuth and elevation;
- selection mode;
- an AWR status strip that explicitly reports the expected angles and
  `RANGE_ONLY_CHEST_GUIDED`.

The marker implementation is in
`ti_style_vendor/common/Common_Tabs/plot_3d.py::updateChestRoi`. Point cloud,
target boxes, human meshes, labels, AWR FE02 display, vital cards, and the
sitting-only estimator gate are otherwise unchanged.

## AWR1642BOOST feasibility evidence

### Local configuration and firmware

- `profile_2d.cfg:4`: `channelCfg 15 3 0` enables four RX and two TX masks.
- `profile_2d.cfg:8-9`: alternating TX1/TX2 chirps.
- `profile_2d.cfg:11`: 100 ms frame period, or 10 Hz.
- `dss_main.c:1826-1849`: `numTxAntElev` remains zero; both enabled TX paths
  contribute to `numTxAntAzim`.
- Result for this profile: 2 azimuth TX x 4 RX = 8 virtual azimuth antennas,
  0 virtual elevation antennas.
- `dss_data_path.h:413,425,428`: persistent complex heatmap pointer and
  separate azimuth/elevation virtual antenna counts.
- `dss_data_path.c:3161-3194`: complex real/imaginary values are stored per
  range and virtual azimuth antenna.

### Board documentation

TI documents AWR1642BOOST as a two-transmitter/four-receiver board with a
one-dimensional onboard antenna aperture. Relevant official references:

- [AWR1642BOOST product page](https://www.ti.com/tool/AWR1642BOOST)
- [AWR1642BOOST user guide, SWRU508](https://www.ti.com/lit/pdf/SWRU508)
- [AWR1642 product page](https://www.ti.com/product/AWR1642)

The board can derive range and one angle dimension from its virtual linear
array. The xWR16xx SDK names that dimension azimuth. There is no independent
orthogonal virtual aperture in the current hardware/configuration for true
two-angle azimuth/elevation beamforming.

## What extra AWR data is required

Range + azimuth requires the complex value for every virtual azimuth antenna
at every exported range bin, not only antenna 0. The existing
`azimuthStaticHeatMap` is the appropriate first source:

```text
azimuthStaticHeatMap[rangeBin * numVirtualAntAzim + antennaIndex]
```

The planned FE03 payload is documented in
`awr1642_vitals/AWR_SPATIAL_TLV_FE03_PLAN.md`.

PC processing would:

1. Calibrate per-antenna phase/gain.
2. Extract the complex 8-element vector for the chest-guided range region.
3. Apply an azimuth FFT or steering-vector beamformer.
4. Search near the IWR expected azimuth rather than globally.
5. Preserve elevation only as IWR metadata.
6. Feed the selected complex beam output into the vital estimator only while
   posture is stable `SITTING`.

## Calibration requirements

Before interpreting vital rates:

1. Measure AWR origin relative to IWR and set `sensor-dx/dy/dz`.
2. Measure relative yaw, pitch, and roll.
3. Verify the chest marker visually follows the torso.
4. Compare expected chest range with FE02 selected range.
5. Record static targets at known lateral positions to determine the AWR
   azimuth sign and boresight offset.
6. After FE03, perform virtual-antenna phase calibration before beamforming.

## Risks

- Tracker target height and ground estimates may be absent or noisy.
- IWR target position is not a torso orientation estimate; lateral/forward
  chest offsets are fixed in the sensor frame.
- Sensor extrinsic errors directly bias expected range and angle.
- FE02 magnitude selection can still lock onto a stronger reflector inside the
  search window.
- Chest confidence is geometric confidence, not proof that the AWR return
  originates at the chest.
- Vital rates must not be described as spatially beamformed until FE03 and PC
  azimuth processing are implemented and calibrated.

## Recommended next sequence

1. Run demo mode and verify chest marker/dashboard fields.
2. Enter measured sensor extrinsics and record a seated single-person run.
3. Inspect chest expected range versus selected FE02 range and bin stability.
4. Do not evaluate vital accuracy yet.
5. Implement FE03 as a separate TLV without changing FE01/FE02.
6. Add offline FE03 parser and synthetic array-angle tests.
7. Implement calibrated range + azimuth beamforming on the PC.
8. Only then evaluate chest-focused breathing/heart estimation.

