# Custom AWR1642 Vital TLV Spec

This is a planning spec only. Do not finalize TLV IDs until the chosen AWR1642 firmware base has been inspected for existing `MMWDEMO_OUTPUT_MSG_*` IDs and any lab-specific TLV ranges.

## TLV 1: `MMWDEMO_OUTPUT_MSG_VITAL_PHASE_TRACE`

Purpose: first firmware milestone. The AWR1642 sends one compact phase/IQ/range-bin sample per frame. The PC estimates breathing and heart rate over slow time.

```c
typedef struct VitalPhaseTrace_t
{
    uint32_t frameNumber;
    uint16_t rangeBinIndexMax;
    uint16_t rangeBinIndexPhase;
    float rangeMeters;
    float iValue;
    float qValue;
    float phaseRad;
    float magnitude;
    float snrLike;
    uint8_t motionDetected;
    uint8_t reserved[3];
} VitalPhaseTrace;
```

Parser notes:

- `iValue` and `qValue` should come from the selected range bin after range FFT.
- `phaseRad` can be sent as `atan2(qValue, iValue)` if available; otherwise the PC can compute it.
- `rangeBinIndexMax` can indicate the strongest chest candidate.
- `rangeBinIndexPhase` can indicate the bin chosen for slow-time phase tracking.
- `motionDetected` should be a conservative firmware-side flag if the base project already exposes motion or clutter metrics.

## TLV 2: `MMWDEMO_OUTPUT_MSG_VITAL_ESTIMATE`

Purpose: later firmware milestone. The AWR1642 estimates vitals onboard and sends compact estimates over UART.

```c
typedef struct VitalEstimate_t
{
    uint32_t frameNumber;
    uint16_t rangeBinIndexPhase;
    uint16_t reserved0;
    float rangeMeters;
    float breathingRateFftBpm;
    float breathingRateXcorrBpm;
    float breathingRatePeakCountBpm;
    float heartRateFftBpm;
    float heartRateFft4HzBpm;
    float heartRateXcorrBpm;
    float heartRatePeakCountBpm;
    float confidenceBreath;
    float confidenceHeart;
    float breathEnergy;
    float heartEnergy;
    uint8_t motionDetected;
    uint8_t qualityState;
    uint8_t reserved[2];
} VitalEstimate;
```

Parser notes:

- Use little-endian layout to match TI mmWave UART packets on Windows hosts.
- Keep structs 4-byte aligned.
- `qualityState` should be an enum in firmware and mirrored in Python.
- Breath and heart estimates should be computed over a rolling buffer, not from a single frame.

## TLV ID Guidance

Before choosing TLV IDs, inspect the selected firmware base files such as `mmw_output.h`, `mmw_messages.h`, `tlv_defines`, or equivalent output packet headers. Use a custom ID that cannot collide with TI object/point/range-profile TLVs in that exact demo.
