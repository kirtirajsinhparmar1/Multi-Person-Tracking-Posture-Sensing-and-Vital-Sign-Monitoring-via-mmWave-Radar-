# AWR1642 Spatial TLV FE03 Plan

## Scope and status

The plan has now been implemented in the copied firmware experiment and PC
software. Firmware was modified but not built or flashed in this task.
Existing FE01 and FE02 remain compatible.

Implemented TLV:

```c
#define MMWDEMO_OUTPUT_MSG_VITAL_PHASE_VIRTUAL_ANT_WINDOW 0xFE03U
```

Purpose: export the complex zero-Doppler value for every virtual azimuth
antenna across the bounded range window, allowing PC-side range + azimuth
beamforming guided by the IWR chest point.

## Source buffer

Use:

```c
obj->azimuthStaticHeatMap[
    rangeBin * obj->numVirtualAntAzim + virtualAntennaIndex
]
```

Evidence:

- `src/1642/dss/dss_data_path.h:413` declares the persistent
  `cmplx16ImRe_t *azimuthStaticHeatMap`.
- `dss_data_path.c:3161-3194` fills real/imaginary complex values.
- `dss_main.c:1193-1196` already knows the standard full heatmap payload size.
- Current FE02 at `dss_main.c:1019-1020` selects antenna index 0 only.

For the active profile, `numVirtualAntAzim = 8` and
`numVirtualAntElev = 0`.

## Recommended compact payload

Do not transmit redundant float phase and magnitude. Preserve raw int16 I/Q
and let the PC calculate derived values.

```c
typedef struct VitalPhaseVirtualAntWindowHeader_t
{
    uint32_t frameNumber;
    uint16_t startBin;
    uint16_t numBins;
    uint16_t numVirtualAntennas;
    uint16_t flags;
    float    rangeResolution;
} VitalPhaseVirtualAntWindowHeader; /* 16 bytes */

typedef struct VitalPhaseVirtualAntSample_t
{
    int16_t iValue;
    int16_t qValue;
} VitalPhaseVirtualAntSample; /* 4 bytes */
```

Records are implicit row-major order:

```text
for rangeBin in [startBin, startBin + numBins):
    for antenna in [0, numVirtualAntAzim):
        append I/Q
```

The header supplies dimensions, so per-record bin and antenna indexes are not
needed.

## Payload and bandwidth

For bins 20-60:

```text
numBins = 41
numVirtualAntAzim = 8
header = 16 bytes
I/Q = 41 * 8 * 4 = 1312 bytes
payload = 1328 bytes/frame
at 10 Hz = 13,280 bytes/s before TI TLV/packet framing
```

At 921600 baud with 8-N-1 framing, the theoretical byte throughput is about
92,160 bytes/s. The compact FE03 payload is therefore reasonable alongside
FE01 and FE02, subject to measurement of all enabled standard TLVs.

A float-heavy record containing bin, antenna, I, Q, phase, and magnitude would
be roughly 4-5 KB/frame and is unnecessary. Raw int16 I/Q is preferable.

## HSRAM/message constraints

The SDK defines `SOC_XWR16XX_DSS_HSRAM_SIZE = 0x8000`, or 32 KB, in
`C:/ti/mmwave_sdk_02_01_00_04/packages/ti/common/sys_common_xwr16xx_dss.h`.
The compact 1328-byte FE03 payload is small enough in isolation.

The implementation:

1. Adds another TLV descriptor slot.
2. Includes FE03 after FE01 and FE02.
3. Checks the remaining HSRAM/message capacity before writing.
4. Omits FE03 safely when it does not fit.
5. Preserves the existing FE01/FE02 append and alignment style.

## Firmware implementation

Copied experiment only:

- FE03 ID and size-checked structs were added in
  `src/1642/common/mmw_messages.h`.
- Compile-time defaults are:
  `VITAL_PHASE_FE03_ENABLE`,
  `VITAL_PHASE_FE03_START_BIN`,
  `VITAL_PHASE_FE03_NUM_BINS`.
- `MmwDemo_fillVitalPhaseVirtualAntWindow()` was added near
  `MmwDemo_fillVitalPhaseBinWindow()` in `src/1642/dss/dss_main.c`.
- It validates the heatmap pointer, antenna count, bin bounds, and output
  capacity.
- FE03 is appended after FE02 in
  `MmwDemo_dssSendProcessOutputToMSS()`.
- FE01 and FE02 generation were not removed or replaced.

## PC parser

The separate FE03 parser validates:

- payload length equals
  `headerSize + numBins * numVirtualAntAzim * sizeof(IQ)`;
- dimensions are nonzero and bounded;
- bin window is consistent with FE02;
- all samples are decoded using the firmware's `cmplx16ImRe_t` field order.

Convert each frame to a complex matrix shaped:

```text
[numBins, numVirtualAntAzim]
```

Keep raw values in calibration logs.

## PC range + azimuth beamforming

Implemented initial processing:

1. Apply measured complex calibration coefficients per virtual antenna.
2. Use IWR chest range to choose a small range-bin neighborhood.
3. Use IWR chest azimuth to define a constrained angle search.
4. Compute an angle FFT or steering-vector response.
5. Select the range/angle cell near the IWR prediction with the strongest
   coherent response.
6. Form a complex beam output:

   ```text
   y = conjugate(w(theta)) dot x
   ```

7. Use `phase(y)` for the vital phase stream.
8. Apply bin/beam hysteresis and pause updates unless posture is stable
   `SITTING`.

The current beamformer uses an explicit ordered lambda/2 ULA assumption.
The exact virtual-array element order, phase convention, and complex channel
calibration still require live verification.

## Elevation conclusion

The active xWR16xx path reports:

```text
numVirtualAntAzim = 8
numVirtualAntElev = 0
```

The AWR1642BOOST onboard two-TX/four-RX layout provides a one-dimensional
virtual aperture. FE03 can support range + one angle dimension (the SDK calls
it azimuth), but not an independent elevation FFT/beamformer.

Therefore:

- Full range + azimuth + elevation: **No for the current AWR1642BOOST
  aperture/configuration.**
- Range + azimuth: **Yes, after FE03 and calibrated PC processing.**
- Elevation from IWR as ROI metadata: **Yes and recommended.**

Official board references:

- [AWR1642BOOST](https://www.ti.com/tool/AWR1642BOOST)
- [AWR1642BOOST user guide](https://www.ti.com/lit/pdf/SWRU508)

## Validation stages

Completed:

1. Synthetic parser test with known complex matrix.
2. Synthetic steering-vector test with known azimuth.
3. Fusion FE03 preference and FE02 fallback tests.

Remaining:

1. Firmware build; no flashing until explicitly authorized.
2. UART packet-size inspection.
3. Static reflector at known range/lateral offsets.
4. Compare IWR chest azimuth against AWR beam peak.
5. Seated chest phase capture.
6. Vital evaluation only after stable spatial selection is demonstrated.
