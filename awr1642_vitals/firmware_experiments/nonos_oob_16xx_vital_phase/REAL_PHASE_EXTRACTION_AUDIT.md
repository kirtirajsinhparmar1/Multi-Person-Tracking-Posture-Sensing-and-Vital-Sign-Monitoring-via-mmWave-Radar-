# AWR1642 Real Phase Extraction Feasibility Audit

## Conclusion

Real complex I/Q is available in the copied DSS firmware. The safest first
implementation is to keep TLV `0xFE01` and the current fake generator intact,
then add a compile-time-selected real mode that reads one configurable range
bin and one virtual-antenna sample from `obj->azimuthStaticHeatMap`.

This buffer is preferable for the first experiment because it is persistent
through output packaging, contains complex zero-Doppler data, has already
integrated the chirps in the frame, and receives RX-channel phase-bias
compensation. No real-phase code was implemented during this audit.

## Verified fake-TLV milestone

The copied non-OS firmware was built, flashed, configured, and verified on an
AWR1642BOOST before this audit:

- CLI/config: COM9, XDS110 Class Application/User UART, 115200 baud
- Data/TLV: COM8, XDS110 Class Auxiliary Data Port, 921600 baud
- Configuration:
  `chirp_config/profile_2d.cfg`
- Custom TLV detected: `0xFE01`
- Live result: 461 samples in 46.20 seconds
- Breathing estimate: approximately 15.62 bpm
- Heart estimate: approximately 72.89 bpm
- Quality: OK

The audit did not open either COM port and did not flash hardware.

## Where the fake phase is generated

The custom output definition is in `src/1642/common/mmw_messages.h`:

- Line 230: `AWR1642_VITAL_PHASE_FAKE_TLV`
- Line 231: `MMWDEMO_OUTPUT_MSG_VITAL_PHASE_TRACE` = `0xFE01U`
- Lines 233-246: 36-byte `VitalPhaseTrace`

The synthetic signal is generated in `src/1642/dss/dss_main.c`:

- Lines 816-819: fake-TLV guard and 20 Hz synthetic sample-rate constant
- Lines 821-850: local wrap/sine/cosine approximations
- Lines 852-878: `MmwDemo_fillFakeVitalPhaseTrace`
- Lines 861-865: 0.25 Hz breathing plus 1.20 Hz heart phase
- Lines 867-877: TLV fields, including fake bin 20 and fake range 1.5 m

The TLV is appended by `MmwDemo_dssSendProcessOutputToMSS`:

- Function starts at line 898
- Lines 1089-1115 allocate and register the custom TLV
- Line 1104 calls `MmwDemo_fillFakeVitalPhaseTrace`
- Line 1108 assigns TLV type `0xFE01`

The call order is safe for reading completed inter-frame data:

- `MmwDemo_waitEndOfChirps`: `dss_main.c:1892`
- `MmwDemo_interFrameProcessing`: `dss_main.c:1900`
- `MmwDemo_dssDataPathOutputLogging`: `dss_main.c:1915`
- `MmwDemo_dssSendProcessOutputToMSS`: called at lines 1176-1178

## Candidate real complex-data buffers

### 1. `azimuthStaticHeatMap` -- recommended first source

Declaration:

- `dss_data_path.h:411-413`
- Type: `cmplx16ImRe_t *`
- Layout:
  `[rangeIdx * numVirtualAntAzim + virtualAzimuthAntennaIdx]`
- Datatype field order is `imag`, then `real`, although named-field access
  (`sample.real`, `sample.imag`) avoids an ordering error.

Population:

- `dss_data_path.c:3010-3202` performs the per-range/per-virtual-antenna
  Doppler processing.
- `dss_data_path.c:3180-3188` applies RX phase-bias compensation when channel
  measurement mode is disabled.
- `dss_data_path.c:3190-3195` stores Doppler-bin-zero complex output after a
  right shift of `log2NumDopplerBins + 4`.
- The BPM path stores equivalent zero-Doppler values at lines 3158-3169.
- L3 allocation is at `dss_data_path.c:4134`.

This buffer is filled unconditionally by the normal inter-frame path; it is not
conditional on UART heatmap output being enabled. Its values are signed
16-bit, scaled complex samples. The common right-shift scaling changes
magnitude but not phase, except for quantization or saturation effects.

Why it is the safest first source:

- It remains valid when the output TLV is assembled.
- It supplies one complex value per frame, range bin, and virtual azimuth
  antenna.
- Doppler bin zero is a natural initial source for slow chest displacement.
- Chirp integration and RX phase compensation are already performed.
- It avoids duplicating radar-cube EDMA/indexing logic in the TLV function.

### 2. `radarCube` -- best raw range-FFT source, but not first patch

Declaration and storage:

- `dss_data_path.h:405-406`
- Type: `cmplx16ReIm_t *` (`real`, then `imag`)
- L3 allocation: `dss_data_path.c:4132`
- 1D FFT output is transferred into it at `dss_data_path.c:3645`.
- `MmwDemo_waitEndOfChirps`, lines 3669-3678, guarantees the final ping/pong
  transfers complete before inter-frame processing.

The 1D range FFT is produced at `dss_data_path.c:2619-2678`; the exact FFT
destination is lines 2663-2668. The persistent radar-cube layout is established
by the 1D-output EDMA setup and the Type-2b EDMA reader:

- `dss_data_path.c:1848-1915`
- `dss_config_edma_util.c:226-298`
- `dss_data_path.c:2995-3002` selects the two-TX pong offset.
- `dss_data_path.c:3025-3038` reads one range-bin sequence for 2D processing.

For the active configuration (four RX, two TDM TX, 32 Doppler bins), direct
radar-cube extraction must correctly select TX, RX, Doppler/chirp, and range
indices. A single raw chirp is more sensitive to timing and TX phase than the
zero-Doppler heatmap. The cube is therefore the canonical raw I/Q source but a
higher-risk first integration point.

### 3. `fftOut1D` -- real I/Q, but unsuitable at output time

- Declared at `dss_data_path.h:348-349`
- Type: `cmplx16ReIm_t *`
- Filled at `dss_data_path.c:2663-2668`
- Allocated as only two ping/pong chirp buffers at `dss_data_path.c:4062`

It contains valid range FFT I/Q during chirp processing, but is transient L2
scratch and does not hold the whole completed frame when the TLV is assembled.
Using it would require capturing/copying a selected sample during every chirp,
which is unnecessary for the first patch.

### 4. `fftOut2D` -- complex zero-Doppler exists transiently

- Declared at `dss_data_path.h:363-364`
- Type: `cmplx32ReIm_t *`
- Generated at `dss_data_path.c:3079-3084`

`fftOut2D[0]` is the higher-precision zero-Doppler complex value used to create
the static heatmap. It is scratch storage and is overwritten for every
range/antenna iteration. Reading it from the TLV packaging function is unsafe;
capturing from it would require modifying the data-path loop.

### 5. `detMatrix` and detected objects -- selection aids, not phase sources

- `detMatrix`: `dss_data_path.h:408-409`, `uint16_t`, range/Doppler log2
  magnitude only; complex phase has been discarded.
- It is written range-major by EDMA configured at
  `dss_data_path.c:1991-2005`.
- `detObj2D` and `detObj2DRaw`: `dss_data_path.h:454-467`; they provide range,
  Doppler, and peak information, not complex I/Q.

These structures can select a bin, but cannot produce phase by themselves.

## Range-bin strategy assessment

### Option A: fixed configurable bin -- recommended first

Use one compile-time-configurable range bin, validate it against
`obj->numRangeBins`, and read one virtual azimuth antenna from
`azimuthStaticHeatMap`.

Advantages:

- Deterministic from frame to frame
- No target-hopping phase discontinuities
- Minimal execution cost and smallest firmware change
- Easy to compare against an intentionally placed stationary target

Do not silently hard-code bin 64. Select the bin from the target distance:

`rangeBinIndexPhase = round(targetRangeMeters / obj->rangeResolution)`

For the active profile (`5500 ksps`, `68 MHz/us`, 256 range bins), the nominal
range resolution derived from the configured bandwidth is approximately
0.04739 m/bin; bin 64 is therefore approximately 3.03 m. The firmware's
existing `obj->rangeResolution` must be used at run time rather than duplicating
this calculation.

### Option B: max-energy range bin -- second stage

After fixed-bin phase is verified, search a bounded human-target range window
and select the strongest bin. Prefer either:

- zero-Doppler `detMatrix[rangeIdx * numDopplerBins]`, which is antenna-summed
  log magnitude, or
- summed squared magnitude of the corresponding `azimuthStaticHeatMap`
  samples.

An unrestricted maximum can select TX leakage, static clutter, or a wall.
Changing bins also changes absolute phase abruptly. A production version needs
a bounded range, hysteresis, minimum hold time, and preferably neighborhood
integration.

### Option C: detected-object range bin -- not recommended first

Normal object detection is optimized for moving targets. A seated, nearly
stationary chest may have no stable CFAR object, and object ordering can change
between frames. This is a useful later tracking integration, not the first
phase-validation source.

### Option D: complex averaging across RX/chirps -- useful after validation

The static heatmap already performs coherent Doppler processing across chirps.
Start with one virtual azimuth channel to avoid cancellation ambiguity.

Later, coherently sum selected `azimuthStaticHeatMap` channels after confirming
RX phase compensation is active. Summing uncorrected complex RX values can
cancel the target. Noncoherent magnitude averaging cannot preserve phase.

## Proposed compile-time modes

Keep `AWR1642_VITAL_PHASE_FAKE_TLV` as the master switch so the proven output
path is not removed. Add mode constants in the copied firmware only:

```c
#define VITAL_PHASE_MODE_FAKE            0U
#define VITAL_PHASE_MODE_REAL_FIXED_BIN  1U
#define VITAL_PHASE_MODE_REAL_MAX_BIN    2U

#ifndef VITAL_PHASE_MODE
#define VITAL_PHASE_MODE VITAL_PHASE_MODE_FAKE
#endif
```

For fixed-bin mode, require an explicit build value instead of guessing:

```c
#if (VITAL_PHASE_MODE == VITAL_PHASE_MODE_REAL_FIXED_BIN)
#ifndef VITAL_PHASE_FIXED_RANGE_BIN
#error "Define VITAL_PHASE_FIXED_RANGE_BIN for the measured target distance"
#endif
#endif
```

The default remains fake mode. This preserves the known-good TLV behavior and
allows immediate fallback by changing one compile-time value.

## Exact recommended patch plan

1. Modify only copied `src/1642/dss/dss_main.c`.
2. Keep `MmwDemo_fillFakeVitalPhaseTrace` unchanged.
3. Add a dispatcher near it, for example
   `MmwDemo_fillVitalPhaseTrace(trace, obj, frameNumber)`.
4. At current line 1104, replace only the direct fake-helper call with the
   dispatcher. Do not alter the 36-byte structure, TLV ID, HSRAM allocation,
   MSS transport, or parser.
5. In `VITAL_PHASE_MODE_REAL_FIXED_BIN`:
   - Validate `VITAL_PHASE_FIXED_RANGE_BIN < obj->numRangeBins`.
   - Initially select virtual azimuth antenna index 0.
   - Read:
     `sample = obj->azimuthStaticHeatMap[bin * obj->numVirtualAntAzim]`.
   - Convert `sample.real` and `sample.imag` to float.
   - Set `iValue = (float)sample.real`.
   - Set `qValue = (float)sample.imag`.
   - Compute `phaseRad = atan2sp(qValue, iValue)`.
   - Compute `magnitude = sqrtsp(iValue*iValue + qValue*qValue)`.
   - Set `rangeMeters = bin * obj->rangeResolution`, optionally subtracting
     the configured range bias consistently with standard object output.
   - Set both range-bin fields to the selected bin.
   - Initially report `snrLike = 0.0f` and `motionDetected = 0U`; do not retain
     synthetic values that imply real measurements.
6. In `VITAL_PHASE_MODE_REAL_MAX_BIN`, initially use the same complex sample
   path but choose the bin from a compile-time-bounded range window. Add
   hysteresis before using this mode for vital estimation.
7. Leave fake mode as the default and call the existing fake helper there.
8. Build DSS and MSS, confirm the TLV remains exactly 36 bytes, then run the
   existing parser against fake mode before any hardware real-mode test.

`dss_main.c` already includes TI Mathlib (`dss_main.c:80-87`), and the DSS
project links `mathlib.ae674` (`mmwNonOS_dss.projectspec:50-51`).
`atan2sp(float y, float x)` and `sqrtsp` are therefore available without adding
a library.

## Sampling-rate issue to correct during real-phase testing

The active configuration has `frameCfg ... 100 ...` at
`chirp_config/profile_2d.cfg:11`, which is a nominal 10 Hz frame/TLV rate. The
live count also gives 461 / 46.20 = approximately 9.98 samples/s.

The fake generator advances its synthetic time using a hard-coded 20 Hz at
`dss_main.c:819` and `dss_main.c:861`. This explains why a parser configured
for 20 Hz can recover the intended synthetic 15/72 bpm even though wall-clock
TLV delivery is about 10 Hz. Real phase must be estimated using the actual
frame rate (nominally 10 Hz for this cfg), or a rate measured from frame
timestamps/counts. Retaining `--fs 20` for real data would double the reported
physiological frequencies.

## Risks

- Fixed-bin selection must match actual target range; the existing fake bin and
  fake `rangeMeters` are synthetic and are not mutually derived.
- Phase wraps at +/-pi and must be unwrapped on the PC before filtering.
- Bin switching in max-bin mode introduces discontinuities unrelated to chest
  motion.
- Static clutter or leakage may dominate an unrestricted max search.
- The 16-bit static heatmap has right-shift quantization; weak targets may need
  a later higher-precision capture from `fftOut2D[0]`.
- RX/virtual-antenna coherent averaging can cancel if phase compensation or
  antenna selection is wrong.
- `atan2sp` argument order must remain `(imaginary, real)`.
- Real phase uses the cfg frame period, not the fake generator's 20 Hz
  constant.
- A direct radar-cube implementation has additional TX/RX/chirp indexing risk
  and should follow, not precede, the static-heatmap experiment.

## Files inspected

- `src/1642/dss/dss_main.c`
- `src/1642/dss/dss_data_path.c`
- `src/1642/dss/dss_data_path.h`
- `src/1642/dss/dss_config_edma_util.c`
- `src/1642/common/mmw_messages.h`
- `src/1642/mmwNonOS_dss.projectspec`
- `chirp_config/profile_2d.cfg`
- SDK `packages/ti/common/sys_common.h` for complex datatype layouts
- TI Mathlib `atan2sp` declarations

## Proceed recommendation

Implementation should proceed as a separate, controlled patch using
`VITAL_PHASE_MODE_REAL_FIXED_BIN` and `azimuthStaticHeatMap`, while preserving
fake mode as the compile-time default. The first real test should use one
explicitly measured target range and one virtual antenna. Max-bin selection and
multi-antenna coherent combining should be separate later milestones.

