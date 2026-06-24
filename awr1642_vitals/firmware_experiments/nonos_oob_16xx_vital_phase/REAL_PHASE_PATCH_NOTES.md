# AWR1642 Real Fixed-Bin Phase Patch Notes

## Result

A controlled real fixed-bin phase mode was added to the copied AWR1642 DSS
firmware. The verified fake `VitalPhaseTrace` path remains present and remains
the compile-time default.

The custom TLV ID remains `0xFE01`, and the 36-byte `VitalPhaseTrace` layout was
not changed.

No COM port was opened and no firmware was flashed.

## Files modified

- `src/1642/dss/dss_main.c`
- `REAL_PHASE_PATCH_NOTES.md`

No Python parser or reader file was modified. No original TI source folder was
modified.

## Compile-time modes

The following modes were added near the existing fake-TLV implementation:

```c
#define VITAL_PHASE_MODE_FAKE            0U
#define VITAL_PHASE_MODE_REAL_FIXED_BIN  1U
#define VITAL_PHASE_MODE_REAL_MAX_BIN    2U

#ifndef VITAL_PHASE_MODE
#define VITAL_PHASE_MODE VITAL_PHASE_MODE_FAKE
#endif
```

The default is therefore still `VITAL_PHASE_MODE_FAKE`.

Real fixed-bin mode requires an explicit bin:

```c
#if (VITAL_PHASE_MODE == VITAL_PHASE_MODE_REAL_FIXED_BIN)
#ifndef VITAL_PHASE_FIXED_RANGE_BIN
#error "Define VITAL_PHASE_FIXED_RANGE_BIN for real fixed-bin vital phase mode"
#endif
#endif
```

`VITAL_PHASE_MODE_REAL_MAX_BIN` is reserved but not implemented. It safely
falls back to the known-good fake generator.

## Dispatcher behavior

`MmwDemo_fillFakeVitalPhaseTrace` was left unchanged.

The new `MmwDemo_fillVitalPhaseTrace` dispatcher is called from
`MmwDemo_dssSendProcessOutputToMSS` in place of the previous direct fake-helper
call.

- Fake mode calls `MmwDemo_fillFakeVitalPhaseTrace`.
- Real fixed-bin mode reads one complex zero-Doppler sample from
  `obj->azimuthStaticHeatMap`.
- Unimplemented max-bin mode calls the fake helper.
- An invalid fixed bin, null heatmap, or zero azimuth-antenna count also falls
  back to fake output instead of emitting invalid memory.

## Real fixed-bin extraction

Real mode selects virtual azimuth antenna index 0:

```c
sample = obj->azimuthStaticHeatMap[
    VITAL_PHASE_FIXED_RANGE_BIN * obj->numVirtualAntAzim];
```

Named fields avoid the `cmplx16ImRe_t` storage-order ambiguity:

```c
iValue = (float)sample.real;
qValue = (float)sample.imag;
```

The output fields are populated as follows:

```c
phaseRad   = atan2sp(qValue, iValue);
magnitude  = sqrtsp(iValue * iValue + qValue * qValue);
rangeMeters = rangeBin * obj->rangeResolution;
snrLike = 0.0f;
motionDetected = 0U;
```

Both range-bin fields contain the selected fixed bin.

## First real test recommendation

For `chirp_config/profile_2d.cfg`, nominal range resolution is approximately
0.04739 m/bin. A target near 1.5 m should therefore start with bin 32:

```text
VITAL_PHASE_MODE=1U
VITAL_PHASE_FIXED_RANGE_BIN=32U
```

The configuration uses a 100 ms frame period, so the live reader/estimator
must use `--fs 10`, not `--fs 20`, for real phase.

## Build verification

The patched `dss_main.c` was compile-checked with TI C6000 compiler 8.1.3 and
mmWave SDK 2.0.0.04 in both configurations:

- Default fake mode: passed
- Real fixed-bin mode with bin 32: passed

The default-fake image was then linked using the generated CCS makefiles:

- DSS build: passed
- MSS build and multicore image generation: passed
- Combined binary:
  `ccs_workspace_awr1642_vital_phase/AWR16xx_mss_nonOS/Debug/xwr16xx_mmw_nonOS.bin`
- Generated size: 200772 bytes
- Generated CRC32: `10df56b9`

The makefiles printed ignored Windows `rm` pre-build warnings, and the CRC tool
reported that it could not remove its temporary file. These messages did not
prevent successful linking or final image generation.

The generated combined image is still fake mode because no real-mode build
defines were applied to the linked DSS object. Real-bin-32 mode was
compile-checked but was not linked into a combined firmware image.

## Exact manual CCS build steps

The existing CCS workspace contains imported physical copies of the source
files rather than links to this experiment directory. Use a fresh CCS workspace
or re-import the project specifications so the patched `dss_main.c` is copied
into the CCS project before building.

1. Open Code Composer Studio without connecting to or flashing the board.
2. Select a fresh workspace, or remove/re-import the generated projects without
   deleting the copied firmware experiment.
3. Import:
   - `src/1642/mmwNonOS_dss.projectspec`
   - `src/1642/mmwNonOS_mss.projectspec`
4. Confirm the DSS project's `dss_main.c` contains
   `MmwDemo_fillVitalPhaseTrace`.
5. For another fake build, add no new predefined symbols.
6. For the first real build, open DSS project properties and add these C6000
   compiler predefined symbols:
   - `VITAL_PHASE_MODE=1U`
   - `VITAL_PHASE_FIXED_RANGE_BIN=32U`
7. Clean and build `AWR16xx_dss_nonOS`.
8. Confirm
   `AWR16xx_dss_nonOS/Debug/xwr16xx_mmw_dss_nonOS.bin` was regenerated.
9. Clean and build `AWR16xx_mss_nonOS`.
10. Confirm
    `AWR16xx_mss_nonOS/Debug/xwr16xx_mmw_nonOS.bin` was regenerated.
11. Do not flash automatically. Review the build log and preserve the previous
    known-good fake binary before intentionally proceeding.
12. When real-mode hardware testing is intentionally authorized, run the live
    reader with `--fs 10`.

