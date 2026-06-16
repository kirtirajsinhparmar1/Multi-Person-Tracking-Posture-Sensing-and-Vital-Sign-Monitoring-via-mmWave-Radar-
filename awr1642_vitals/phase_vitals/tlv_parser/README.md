# AWR1642 VitalPhaseTrace TLV Parser

This folder is the PC-side companion for the first custom AWR1642 firmware milestone.

The copied non-OS firmware experiment appends a fake custom TLV:

`MMWDEMO_OUTPUT_MSG_VITAL_PHASE_TRACE = 0xFE01`

Payload:

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

The first milestone sends synthetic phase over the normal TI UART TLV path. The PC parser extracts `phaseRad`, then the existing phase vital estimator computes breathing and heart metrics.

Run the payload-only replay test:

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_vital_phase_tlv_replay.py --fake --fs 20 --duration 50
```

This does not open COM ports. It only validates the payload struct, byte order, fake phase formula, and estimator path.

Next firmware milestone: replace the fake phase fields with real selected range-bin I/Q after range FFT, while keeping the same TLV payload format.
