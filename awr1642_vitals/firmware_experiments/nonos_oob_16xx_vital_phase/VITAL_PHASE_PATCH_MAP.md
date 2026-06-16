# AWR1642 Non-OS Vital Phase TLV Patch Map

This folder is a copied firmware experiment based on:

`source\ti\examples\Fundamentals\nonos_oob\nonos_oob_16xx`

Original TI source outside this copied experiment was not modified.

## Firmware Files Inspected

- `src\1642\common\mmw_messages.h`
- `src\1642\dss\dss_main.c`
- `src\1642\dss\dss_data_path.c`
- `src\1642\dss\dss_data_path.h`
- `src\1642\dss\dss_mmw.h`
- `src\1642\mss\mss_main.c`
- `src\1642\mss\mss_mmw.h`
- `src\1642\mss\cli.c`
- `src\1642\mmwNonOS_dss.projectspec`
- `src\1642\mmwNonOS_mss.projectspec`

## Output Message / TLV IDs

Standard output TLV IDs are pulled in through:

`src\1642\common\mmw_messages.h`

via:

```c
#include <ti/demo/io_interface/mmw_output.h>
```

That SDK header defines the standard OOB output packet structures and low-number TLV IDs such as detected points, range profile, noise profile, heat maps, and stats.

For this copied experiment, the custom vital phase TLV is defined locally in:

`src\1642\common\mmw_messages.h`

```c
#define AWR1642_VITAL_PHASE_FAKE_TLV              1
#define MMWDEMO_OUTPUT_MSG_VITAL_PHASE_TRACE      0xFE01U
```

`0xFE01U` was chosen as a lab-local high value to avoid collision with the standard low-number OOB TLV IDs. Before production firmware, inspect the exact SDK `mmw_output.h` used by the CCS build and reserve a final project-specific ID.

## Output Packet Structs

Packet header and UART TLV header structs are provided by the SDK header:

`ti/demo/io_interface/mmw_output.h`

Key types used by this firmware:

- `MmwDemo_output_message_header`
- `MmwDemo_output_message_tl`
- `MmwDemo_output_message_dataObjDescr`

Mailbox-side TLV descriptors are local:

`src\1642\common\mmw_messages.h`

- `MmwDemo_msgTlv`
- `MmwDemo_detInfoMsg`
- `MmwDemo_message_body`
- `MmwDemo_message`

The custom payload struct is local:

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

Payload size is 36 bytes with 4-byte alignment.

## UART Output Code

UART packets are sent by the MSS in:

`src\1642\mss\mss_main.c`

Mailbox switch case:

`MMWDEMO_DSS2MSS_DETOBJ_READY`

The MSS writes:

1. `MmwDemo_output_message_header`
2. each `MmwDemo_output_message_tl`
3. each TLV payload translated from DSS address space with `SOC_translateAddress(...)`
4. packet padding to `MMWDEMO_OUTPUT_MSG_SEGMENT_LEN`

## TLV Append Code

TLV descriptors are assembled by the DSS in:

`src\1642\dss\dss_main.c`

Function:

`MmwDemo_dssSendProcessOutputToMSS(uint8_t *ptrHsmBuffer, uint32_t outputBufSize, MmwDemo_DSS_DataPathObj *obj)`

This function appends standard TLVs based on `guiMonitor` settings, then sets:

- `message.body.detObj.header.numTLVs`
- `message.body.detObj.header.totalPacketLen`
- `message.body.detObj.header.frameNumber`

## Fake VitalPhaseTrace TLV Insertion Point

The fake TLV is appended in:

`src\1642\dss\dss_main.c`

after the standard stats TLV block and before the final output header fields are assigned.

This is the right first-milestone location because it validates the existing DSS-to-MSS mailbox and MSS UART TLV path without touching real range FFT/radar-cube data.

## Fake Phase Generation

Compile-time switch:

```c
#define AWR1642_VITAL_PHASE_FAKE_TLV 1
```

The helper in `dss_main.c` generates synthetic slow-time phase at an assumed 20 Hz frame rate:

- breathing: 0.25 Hz / 15 bpm
- heart: 1.2 Hz / 72 bpm
- `iValue = cos(phaseRad)`
- `qValue = sin(phaseRad)`
- `rangeBinIndexPhase = 20`
- `rangeMeters = 1.5`
- `snrLike = 30`
- `motionDetected = 0`

The helper uses small polynomial sine/cosine approximations instead of `sinf`/`cosf` to avoid linker/library changes in this first patch.

## Build / Project Files Found

- `src\1642\mmwNonOS_dss.projectspec`
- `src\1642\mmwNonOS_mss.projectspec`
- `src\1642\dss\dss_mmw_linker.cmd`
- `src\1642\mss\mss_mmw_linker.cmd`
- `prebuilt_binaries\xwr16xx_mmw_nonOS.bin`

The prebuilt binary is unchanged and does not include the fake TLV patch.

## Range Processing / Real I/Q References

Likely real range-bin I/Q integration points are in:

- `src\1642\dss\dss_data_path.c`
- `src\1642\dss\dss_data_path.h`
- `src\1642\dss\dss_mmw.h`

Relevant symbols include range FFT calls, radar cube buffers, range profiles, and heat map generation. This fake TLV milestone deliberately does not use them yet.

## Risks / Open Questions

- The firmware has not been built in CCS yet.
- `MMWDEMO_OUTPUT_MSG_MAX` comes from the external SDK header. If the enabled standard TLVs already fill the array, adding one extra fake TLV may require increasing the TLV descriptor capacity.
- The custom TLV ID `0xFE01U` should be verified against the exact SDK and any project-specific TLV IDs before final firmware.
- The fake phase generator assumes 20 Hz. If the configured frame rate differs, the replayed BPM will differ unless the helper is updated to derive frame rate from config.
- This patch validates packet plumbing only. It does not prove real chest phase extraction.
- Next firmware milestone is to replace the fake phase values with complex I/Q from the selected range bin after range FFT.
