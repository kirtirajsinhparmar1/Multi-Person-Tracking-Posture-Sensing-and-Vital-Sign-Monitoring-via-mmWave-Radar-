# VitalPhaseTrace Build Audit

This audit covers only the copied firmware experiment:

`custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase`

No original TI source files were modified.

## Packet Integration

The custom TLV is defined in:

`src\1642\common\mmw_messages.h`

The fake TLV is appended in:

`src\1642\dss\dss_main.c`

The MSS UART sender is in:

`src\1642\mss\mss_main.c`

In `MmwDemo_transmitProcessedOutput`, the MSS writes:

1. `MmwDemo_output_message_header`
2. one `MmwDemo_output_message_tl` per TLV
3. each TLV payload
4. segment padding

## Audit Results

| Check | Result |
| --- | --- |
| TLV count incremented | Looks correct. The DSS appends the fake VitalPhaseTrace TLV and increments `tlvIdx`; the final header uses `numTLVs = tlvIdx`. |
| Total packet length updated | Looks correct. The DSS adds `sizeof(MmwDemo_output_message_tl) + sizeof(VitalPhaseTrace)` to `totalPacketLen`, then rounds to `MMWDEMO_OUTPUT_MSG_SEGMENT_LEN`. |
| Payload length | The TLV length is `sizeof(VitalPhaseTrace)` = 36 bytes. The MSS UART path treats TLV length as payload length. |
| Custom TLV type storage | Looks safe. TLV type fields are `uint32_t`, so `0xFE01U` fits. |
| `MMWDEMO_OUTPUT_MSG_MAX` | Needs build-time verification. The copied code includes `ti/demo/io_interface/mmw_output.h` from the SDK, so the exact array capacity is external to this copied folder. If the base demo already uses the maximum number of TLVs, this constant must be increased in the copied experiment or SDK-local include strategy. |
| `sinf`/`cosf` linker risk | Avoided in the copied patch by using a small local approximation/accumulator approach instead of requiring new math-library symbols. |
| Copied experiment only | Yes. The patch exists only under `custom_iwr6843_fall_logger\awr1642_vitals\firmware_experiments\nonos_oob_16xx_vital_phase`. |
| MSS/DSS message struct size | No new DSS-to-MSS message type was added. The existing `MmwDemo_detInfoMsg` TLV array is reused, so only TLV array capacity and output buffer size matter. |
| DSS-to-MSS payload size | Increases by 44 bytes before padding: 8-byte TLV header + 36-byte payload. The existing `totalHsmSize > outputBufSize` check should catch overflow. |
| Endian/alignment | Project specs are little-endian. The C layout is naturally 4-byte aligned and the Python parser uses `<IHHffffffB3s`, also 36 bytes. |
| C struct size confirmation | The planned/implemented field layout is 36 bytes: 4 + 2 + 2 + six 4-byte floats + 1 + 3 reserved bytes. A compile-time assert is recommended during the CCS build if the compiler supports it. |

## Header Layout Used by PC Parser

The copied DSS fills the standard TI mmWave header:

- magic word bytes: `02 01 04 03 06 05 08 07`
- `version`
- `totalPacketLen`
- `platform` = `0xA1642`
- `frameNumber`
- `timeCpuCycles`
- `numDetectedObj`
- `numTLVs`
- `subFrameNumber`

The PC parser implements this 40-byte header and an 8-byte TLV header:

```c
typedef struct MmwDemo_output_message_tl
{
    uint32_t type;
    uint32_t length; /* payload length in this non-OS UART path */
} MmwDemo_output_message_tl;
```

## Build Risk Notes

The main item to verify in CCS is `MMWDEMO_OUTPUT_MSG_MAX`. If the TLV array is too small for one extra custom TLV, the DSS build may fail or the runtime packet may overwrite the local TLV array. The safe fix is to increase the local/copied output-message maximum for this experiment only.

The second item is output-buffer capacity. The fake TLV adds only 44 bytes plus possible segment padding, so capacity risk is low, and the existing code already checks total HSRAM message size.

## CCS Projects

Import these copied project specs:

- `src\1642\mmwNonOS_dss.projectspec`
- `src\1642\mmwNonOS_mss.projectspec`

Recommended order:

1. Build DSS project.
2. Build MSS project.

The MSS post-build step expects the DSS binary and creates the combined non-OS image.

## Current Audit Conclusion

Packet length and TLV count logic look correct for the fake VitalPhaseTrace milestone. `MMWDEMO_OUTPUT_MSG_MAX` is the only unresolved build-readiness item because its definition is pulled from an SDK include outside the copied experiment.
