# CCS Build Notes

These notes apply only to the copied experiment:

`custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase`

Do not flash hardware from this milestone. The goal is only to build and verify that the fake VitalPhaseTrace TLV compiles.

## Projects To Import

Import these project specs into Code Composer Studio:

- `src\1642\mmwNonOS_dss.projectspec`
- `src\1642\mmwNonOS_mss.projectspec`

Expected project names from the project specs:

- DSS: `AWR16xx_dss_nonOS`
- MSS: `AWR16xx_mss_nonOS`

## Toolchain / SDK Expectations

The project specs reference:

- mmWave SDK product: `com.ti.MMWAVE_SDK:2.0.0.04`
- MSS/R4F compiler: `TI ARM Compiler 16.9.3.LTS`
- DSS/C674x compiler: `TI C6000 Compiler 8.1.3`
- `COM_TI_MMWAVE_SDK_INSTALL_DIR`
- `TI_DSPLIB_BASE`, default `C:/ti/dsplib_c64Px_3_4_0_0`
- `TI_MATHLIB_BASE`, default `C:/ti/mathlib_c674x_3_1_2_1`

The DSS project links TI DSPLIB/MATHLIB libraries already used by the original demo.

## Build Order

1. Build `AWR16xx_dss_nonOS`.
2. Build `AWR16xx_mss_nonOS`.

The MSS post-build step expects the DSS binary in the workspace and creates the combined image:

- `xwr16xx_mmw_dss_nonOS.bin`
- `xwr16xx_mmw_nonOS.bin`

## What A Successful Build Means

A successful build means the copied firmware experiment can emit the fake custom TLV in the existing UART packet path. It does not mean the TLV has been tested on hardware, and it does not mean real radar I/Q phase has been wired yet.

## Common Failure Causes

- mmWave SDK 2.0.0.04 not installed or not registered with CCS.
- ARM/C6000 compiler versions not installed.
- `TI_DSPLIB_BASE` or `TI_MATHLIB_BASE` points to a missing install.
- DSS binary output path does not match the MSS post-build script expectation.
- `MMWDEMO_OUTPUT_MSG_MAX` is too small for one extra TLV.
- A copied experiment include still resolves to an SDK header that must be locally overridden for this experiment.

## Do Not Flash Yet

This build is for parser and packet-integration validation only. Flashing should wait until:

1. CCS build succeeds.
2. The generated UART packet is reviewed against the Python parser.
3. The custom TLV ID is confirmed not to collide with the chosen firmware base.
4. A rollback path to a known-good AWR1642 image is ready.
