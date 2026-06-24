# Firmware Merge Audit: 3D People Tracking and Vital Signs

## Executive Summary

The local Radar Toolbox contains complete, buildable IWR6843 source for **3D People Tracking**, including MSS, DSS, DPC/DPU integration, tracker output, CLI handling, CCS project specifications, linker files, configurations, and a prebuilt binary.

The local **Vital Signs With People Tracking** package is different: it contains only IWR6843ISK/IWR6843AOP prebuilt binaries, configurations, and documentation. It does **not** contain the IWR6843 MSS/DSS source or CCS projects needed for a source-level merge.

Consequently:

- **A direct source merge cannot be completed from the locally available Vital Signs With People Tracking package.**
- The best current operational choice is **Strategy C: maintain two radars/firmwares**.
- If TI supplies the missing IWR6843 vital-sign source, the recommended single-radar path becomes **Strategy B: use 3D People Tracking as the base and port vital-sign processing into it**. This preserves known IWR6843ISK-ODS antenna support and the TLVs consumed by the existing posture UI.
- Flashing the supplied ISK or AOP vital-sign binary onto IWR6843ISK-ODS is not supported by the local documentation and carries substantial antenna-geometry and phase-processing risk.

The supplied vital-sign demo is documented as tracking/localizing and measuring vital signs for **one person**. True simultaneous multi-person vital signs would require independent signal-processing state for every selected tracker TID.

## Projects Inspected

### 3D People Tracking

Path:

`source\ti\examples\Industrial_and_Personal_Electronics\People_Tracking\3D_People_Tracking`

### Vital Signs With People Tracking

Path:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking`

## 1. Source Availability

### 1.1 3D People Tracking

This project includes complete application source for the IWR6843 MSS and DSS.

Source folders:

- `src\6843\common`
- `src\6843\mss`
- `src\6843\dss`

Common source:

- `src\6843\common\mmwdemo_adcconfig.c`
- `src\6843\common\mmwdemo_adcconfig.h`
- `src\6843\common\mmwdemo_rfparser.c`
- `src\6843\common\mmwdemo_rfparser.h`
- `src\6843\common\pcount3D_config.h`
- `src\6843\common\pcount3D_hwres.h`

MSS source:

- `src\6843\mss\mss_main.c`
- `src\6843\mss\pcount3D_cli.c`
- `src\6843\mss\pcount3D_mss.h`
- `src\6843\mss\tracker_utils.c`
- `src\6843\mss\tracker_utils.h`

DSS source:

- `src\6843\dss\dss_main.c`
- `src\6843\dss\pcount3D_dss.h`

CCS project files:

- `src\6843\3D_people_track_6843_mss.projectspec`
- `src\6843\3D_people_track_6843_dss.projectspec`

Linker and SYS/BIOS configuration files:

- `src\6843\mss\r4f_linker.cmd`
- `src\6843\mss\pcount3D_mss_linker.cmd`
- `src\6843\mss\pcount3D_mss.cfg`
- `src\6843\dss\c674x_linker.cmd`
- `src\6843\dss\pcount3D_dss_linker.cmd`
- `src\6843\dss\pcount3D_dss.cfg`

No standalone makefiles were found in this project. The CCS project specifications contain the source imports, product dependencies, compiler settings, and post-build commands.

Prebuilt binary:

- `prebuilt_binaries\3D_people_track_6843_demo.bin`

Configurations:

- `chirp_configs\AOP_6m_default.cfg`
- `chirp_configs\AOP_6m_staticRetention.cfg`
- `chirp_configs\AOP_9m_default.cfg`
- `chirp_configs\AOP_9m_sensitive.cfg`
- `chirp_configs\ISK_14m_extended.cfg`
- `chirp_configs\ISK_6m_default.cfg`
- `chirp_configs\ISK_6m_staticRetention.cfg`
- `chirp_configs\ISK_6m_staticRetention_45deg.cfg`
- `chirp_configs\ODS_6m_default.cfg`
- `chirp_configs\ODS_6m_staticRetention.cfg`

Documentation:

- `docs\3d_people_tracking_user_guide.html`
- `docs\3d_people_tracking_release_notes.html`

### 1.2 Vital Signs With People Tracking

The local project does **not** contain IWR6843 firmware source.

No MSS source, DSS source, CCS project specifications, linker files, SYS/BIOS configuration files, or makefiles were found under this project.

Prebuilt binaries:

- `prebuilt_binaries\vital_signs_tracking_6843ISK_demo.bin`
- `prebuilt_binaries\vital_signs_tracking_6843AOP_demo.bin`

Configurations:

- `chirp_configs\vital_signs_ISK_2m.cfg`
- `chirp_configs\vital_signs_ISK_6m.cfg`
- `chirp_configs\vital_signs_AOP_2m.cfg`
- `chirp_configs\vital_signs_AOP_6m.cfg`

Documentation:

- `docs\vital_signs_with_people_tracking_user_guide.html`
- `docs\vital_signs_with_people_tracking_release_notes.html`

There is vital-sign source elsewhere in the toolbox for:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\IWRL6432_Vital_Signs`

That code targets IWRL6432 and a different architecture. It is useful for understanding algorithm structure, but it is not the missing IWR6843 Vital Signs With People Tracking implementation and cannot be treated as drop-in IWR6843 source.

## 2. Board Targets

### 2.1 3D People Tracking

Explicitly supported configurations exist for:

- IWR6843ISK
- IWR6843AOP
- IWR6843ISK-ODS

ODS support is explicit through:

- `chirp_configs\ODS_6m_default.cfg`
- `chirp_configs\ODS_6m_staticRetention.cfg`

The ODS configuration contains ODS-specific virtual antenna geometry and phase rotation:

```text
antGeometry0 0 0 -1 -1 -2 -2 -3 -3 -2 -2 -3 -3
antGeometry1 0 -1 -1 0 0 -1 -1 0 -2 -3 -3 -2
antPhaseRot 1 -1 -1 1 1 -1 -1 1 1 -1 -1 1
```

It also contains ODS-specific scenery, tracker, sensor-position, and calibration commands.

### 2.2 Vital Signs With People Tracking

Explicit local binary/config support exists for:

- IWR6843ISK
- IWR6843AOP

No IWR6843ISK-ODS binary or ODS vital-sign configuration was found.

This absence matters because vital-sign phase extraction is sensitive to:

- antenna arrangement
- virtual antenna ordering
- phase rotation/sign
- receive-channel phase calibration
- beam/range-bin selection
- frame timing

An ISK binary should not be assumed compatible with ODS merely because both use an IWR6843 device.

## 3. Firmware Architecture

### 3.1 3D People Tracking Architecture

The firmware uses the normal IWR6843 split architecture:

- R4F MSS for control, CLI, HWA range processing, tracking, height processing, and UART output
- C674x DSS for the Capon 3D object-detection data path

Important application functions:

- `MmwDemo_uartTxTask()` in `src\6843\mss\mss_main.c`
- `MmwDemo_trackerDPUTask()` in `src\6843\mss\mss_main.c`
- `MmwDemo_trackerConfig()` in `src\6843\mss\mss_main.c`
- CLI registration and handlers in `src\6843\mss\pcount3D_cli.c`

Imported MSS processing modules listed by the project specification:

- `custom_sdk_files\sdk3\dpc\objdetrangehwa\src\objdetrangehwa.c`
- `custom_sdk_files\sdk3\dpu\rangeprochwa\src\rangeprochwa.c`
- `custom_sdk_files\sdk3\dpu\trackerproc_overhead\src\trackerproc_3d.c`
- `custom_sdk_files\sdk3\dpu\trackerproc_overhead\src\height_detection.c`

Tracker library:

- `libgtrack3D.aer4f`

Imported DSS processing modules include:

- `custom_sdk_files\sdk3\dpc\capon3d\src\objectdetection.c`
- `custom_sdk_files\sdk3\dpu\capon3d\src\radarProcess.c`
- `custom_sdk_files\sdk3\dpu\capon3d\src\copyTranspose.c`
- Capon beamforming, CFAR, matrix, and utility modules referenced by the DSS project specification

CLI commands include:

- `trackingCfg`
- `staticBoundaryBox`
- `boundaryBox`
- `sensorPosition`
- `presenceBoundaryBox`
- the standard sensor/profile/chirp/frame and GUI monitor commands

`pcount3D_cli.c` ultimately starts the CLI with `CLI_open()`.

### 3.2 Vital Signs With People Tracking Architecture

The exact IWR6843 architecture cannot be audited at source level because its source is absent.

The binaries and configurations establish that the application combines:

- people tracking
- target localization
- vital-sign range-bin selection
- phase/waveform processing
- breathing-rate output
- heart-rate output
- UART TLV output

However, the following cannot be identified from the local package:

- MSS source files and functions
- DSS source files and functions
- DPC/DPU module ownership
- exact tracker implementation
- exact vital processing state structures
- exact range-bin selection function
- exact phase extraction function
- exact CLI handler for `vitalsign`
- exact packet-construction code

The IWRL6432 reference implementation contains:

- `vitalsign.c`
- `vitalsign.h`
- `vitalsign_with_tracking.c`
- `dpc.c`

Useful reference symbols include:

- `MmwDemo_computeVitalSignProcessing()`
- `MmwDemo_runVitalSigns()`
- a global `vsFeature vitalSignsOutput`

That implementation performs phase unwrapping, breathing/heart filtering and estimation, and selected-range-bin reporting. It appears to maintain one global vital-sign processing state, but this finding applies only to the IWRL6432 reference.

## 4. UART and TLV Outputs

### 4.1 3D People Tracking TLVs

Shared definitions are in:

`source\ti\common\mmwdemo_tlv.h`

Relevant types:

| ID | Definition | Purpose |
|---:|---|---|
| 1000 | `MMWDEMO_OUTPUT_MSG_SPHERICAL_POINTS` | Spherical point representation |
| 1010 | `MMWDEMO_OUTPUT_MSG_TRACKERPROC_3D_TARGET_LIST` | 3D tracker target list |
| 1011 | `MMWDEMO_OUTPUT_MSG_TRACKERPROC_TARGET_INDEX` | Point-to-target association |
| 1012 | `MMWDEMO_OUTPUT_MSG_TRACKERPROC_TARGET_HEIGHT` | Target height |
| 1020 | `MMWDEMO_OUTPUT_MSG_COMPRESSED_POINTS` | Compressed point cloud |
| 1021 | `MMWDEMO_OUTPUT_MSG_PRESCENCE_INDICATION` | Presence state |
| 1030 | `MMWDEMO_OUTPUT_MSG_OCCUPANCY_STATE_MACHINE` | Occupancy state |
| 1031 | `MMWDEMO_OUTPUT_MSG_SURFACE_CLASSIFICATION_PROBABILITY` | Surface classification |

`MmwDemo_uartTxTask()` constructs and transmits:

- compressed point cloud, normally type 1020
- target list, type 1010
- target height, type 1012
- target index, type 1011
- presence indication, type 1021

The task increments the TLV count, adds each TLV header and payload to the packet length, sets `header.numTLVs`, pads to the UART segment size, and transmits the header/TLVs.

### 4.2 Vital Signs TLV

The Industrial Visualizer defines:

`MMWDEMO_OUTPUT_MSG_VITALSIGNS = 1040`

Relevant files:

- `tools\visualizers\Applications_Visualizer\common\tlv_defines.py`
- `tools\visualizers\Applications_Visualizer\common\parseFrame.py`
- `tools\visualizers\Applications_Visualizer\common\parseTLVs.py`
- `tools\visualizers\Applications_Visualizer\common\Demo_Classes\vital_signs.py`

`parseVitalSignsTLV()` parses the payload with format:

```text
2H33f
```

Decoded fields are:

- `uint16 id`
- `uint16 rangeBin`
- `float breathDeviation`
- `float heartRate`
- `float breathRate`
- 15 heart-waveform float samples
- 15 breath-waveform float samples

The visualizer treats `id` as a patient index. Without the missing IWR6843 firmware source, it is not possible to prove whether this field is:

- the GTRACK TID
- an internal selected-target index
- a zero-based vital patient slot

This ambiguity is a critical integration risk.

### 4.3 Does Vital Firmware Emit Tracking TLVs?

The visualizer and demo purpose indicate that target tracking information is present, but the exact firmware packet-generation code is unavailable. The local parser can handle the standard People Tracking TLVs and TLV 1040.

Before replacing the current 3D firmware, a captured vital-firmware UART frame must be checked for:

- 1020 compressed point cloud
- 1010 target list
- 1011 target indexes
- 1012 target height
- 1021 presence
- 1040 vital signs

The current posture UI depends particularly on 1010, 1011, 1012, and 1020. Documentation alone is insufficient to guarantee identical output structures and update timing.

## 5. Vital-Sign Processing

### Verified for the IWR6843 Demo

From the local binary/config/documentation package:

- vital-sign processing is combined with people tracking
- it reports breathing and heart rates
- its configuration includes a `vitalsign` command
- the 6 m ISK configuration includes `vitalsign 15 300`
- the demo is described as operating on one person
- approximately 30 seconds may be required for stable range-bin/vital estimates
- TLV 1040 contains a selected range bin, rate values, and waveform samples

### Not Verifiable Without Missing IWR6843 Source

The local project does not reveal:

- where the target range bin is selected
- whether angular position is used in vital extraction
- which antenna/channel supplies the complex phase
- where phase is unwrapped
- which exact filters/estimators compute rates
- whether processing executes on MSS or DSS
- whether tracker TID directly owns the vital state
- whether one or multiple state objects are allocated

### Algorithm Reference from IWRL6432

The separate IWRL6432 source shows the expected high-level flow:

1. Select target/range data.
2. Read real and imaginary data.
3. Derive and unwrap phase.
4. Update slow-time buffers.
5. Filter breathing and heart bands.
6. Estimate rates and quality metrics.
7. populate a vital-sign output object.

It uses a global `vitalSignsOutput` object and assigns an ID in that output. It also contains antenna-specific real/imaginary handling and sign conventions. This reinforces that an ODS port must explicitly handle ODS antenna geometry rather than copying ISK assumptions.

## 6. People Tracking Comparison

| Question | Finding |
|---|---|
| Same tracker? | Not provable. The 3D project uses `libgtrack3D.aer4f` and `trackerproc_3d.c`. The vital IWR6843 source is absent. |
| Same target-list format? | The TI visualizer supports the standard target TLVs, but binary output must be captured or source obtained before identical layout is assumed. |
| Same UART output structs? | TLV 1040 is known. Exact vital firmware packet construction and tracker structures are not locally available. |
| Enough 3D data for posture UI? | Possibly, but not guaranteed. Verify that the vital binary emits 1020, 1010, 1011, and 1012 with compatible payloads. |
| Same frame timing? | No. The inspected 3D ODS configuration uses a 55 ms frame period; the vital ISK 6 m configuration uses 90 ms. |

The 3D project is the safer base for preserving the current UI because its data path and all required posture-input TLVs are directly inspectable and already proven on IWR6843ISK-ODS.

## 7. IWR6843ISK-ODS Porting Requirements

Making Vital Signs With People Tracking work correctly on ODS requires a source rebuild. A configuration-only substitution is not sufficient evidence of compatibility.

### Antenna Geometry

Port the ODS virtual antenna layout and phase rotation from the working ODS people-tracking configuration:

- `antGeometry0`
- `antGeometry1`
- `antPhaseRot`

Any vital phase extraction that selects a physical/virtual antenna must be reviewed for ODS channel ordering and phase sign.

### Chirp and Frame Configuration

The existing vital ISK 6 m configuration uses:

- TX masks 5, 2, 5
- 48 loops
- 90 ms frame period

The existing 3D ODS configuration uses:

- TX masks 1, 2, 4
- 96 loops
- 55 ms frame period

The ODS vital configuration must preserve:

- sufficient tracking performance
- suitable slow-time sampling for breathing and heart bands
- suitable coherent phase behavior
- valid antenna multiplexing for ODS

Blindly using the ODS tracking configuration may alter the vital algorithm's expected sample rate and antenna data. Blindly using the ISK vital configuration may produce invalid ODS angle/phase processing.

### Elevation and Azimuth

Revalidate:

- virtual array geometry
- azimuth/elevation channel mapping
- Capon/beamforming steering assumptions
- target angle-to-range-bin association
- any antenna selected for chest displacement

### Tracker and Scenery

Port and tune:

- `boundaryBox`
- `staticBoundaryBox`
- `sensorPosition`
- `trackingCfg`
- presence boundary configuration if used

The tracker update period must match the selected frame period.

### GUI Monitor and TLVs

Ensure the merged firmware continues emitting:

- 1020 point cloud
- 1010 target list
- 1011 association indexes
- 1012 height
- 1021 presence, if required
- 1040 or a replacement multi-target vital TLV

### Calibration

Run or supply valid ODS:

- range-bias calibration
- RX channel phase compensation

The unity placeholder `compRangeBiasAndRxChanPhase` entry is not a substitute for a board-specific calibration when accurate phase is required.

### Memory and Build

Review:

- L2/L3 memory allocation
- radar-cube ownership and lifetime
- phase-history buffers
- filter/FFT workspaces
- MSS/DSS processing deadlines
- inter-core messaging bandwidth
- UART packet size

Multi-person vital processing multiplies the state and compute requirements.

## 8. Merge Strategy Recommendation

### Current Recommendation: C and D

**D. A source-level merge is not feasible from the locally available IWR6843 vital package.**

The blocking item is the missing IWR6843 Vital Signs With People Tracking source and build project.

Therefore the practical current architecture is:

**C. Maintain two separate radars/firmwares.**

- IWR6843ISK-ODS: current 3D tracking, posture, TID, motion, and UI
- second radar or development path: vital-sign specialist
- PC: associate vital results with IWR6843 TIDs by synchronized range, angle, time, and motion gating

### Conditional Recommendation if TI Vital Source Is Obtained: B

Use **3D People Tracking as the base and port vital-sign processing into it**.

Reasons:

- complete buildable source is present
- ODS antenna geometry/configuration is present
- the firmware is already proven with the current hardware
- all posture UI TLVs are known and working
- tracker TIDs and target indexes are available at the source level
- adding a vital output is lower risk than reconstructing the current 3D data path in an opaque binary project

Modules/files likely requiring changes:

- `src\6843\mss\mss_main.c`
  - allocate and run vital processing
  - associate vital state with tracker TIDs
  - append vital TLV(s) in `MmwDemo_uartTxTask()`
- `src\6843\mss\pcount3D_mss.h`
  - vital state/config/output structures
- `src\6843\mss\pcount3D_cli.c`
  - register and parse vital configuration commands
- `src\6843\common\pcount3D_config.h`
  - vital configuration structures and limits
- `src\6843\common\pcount3D_hwres.h`
  - memory/resource changes if new buffers require them
- `src\6843\3D_people_track_6843_mss.projectspec`
  - import vital algorithm source and libraries
- `src\6843\3D_people_track_6843_dss.projectspec`
  - only if phase/radar-cube extraction must run on DSS
- shared/custom TLV definition header
  - add a collision-free multi-target vital output definition
- ODS chirp configuration
  - add vital CLI command and validate timing/antenna behavior

The missing TI source is still needed to identify which parts can be reused rather than reimplemented.

### Why Strategy A Is Not Recommended

Using Vital Signs With People Tracking as the base would require:

- obtaining its missing source
- proving it emits all current posture UI TLVs
- adding ODS antenna and calibration support
- reconciling its tracker and target formats with the current UI

That path starts from an unverified ODS baseline, whereas the 3D project already works on ODS.

## 9. Multi-Person Vital Signs Feasibility

### Current Capability

The supplied IWR6843 vital-sign demo is documented for **one person**. The visualizer reserves two patient displays, but visualizer capacity does not prove simultaneous two-person firmware processing.

TLV 1040 carries one `id` and one vital record per payload. Multiple 1040 TLVs could theoretically be emitted, but the missing firmware source prevents verification that this happens.

### Required Changes for True Multi-Person Vitals

Each vital-enabled tracker TID needs independent:

- target-to-range/angle association
- selected range bin
- complex phase history
- unwrapped phase state
- breathing filter state
- heart filter state
- FFT/autocorrelation workspace or scheduling
- motion rejection state
- confidence and quality state
- lifecycle/reset handling when the TID disappears or is reused

Processing should be gated to stable, low-motion targets. The first implementation should support **one selected sitting target**. After validating identity stability and compute margins, increase to two simultaneous sitting targets.

### Recommended New TLV

Do not assign a numeric ID until all output IDs in the final firmware base have been audited.

Suggested semantic name:

`MMWDEMO_OUTPUT_MSG_MULTI_TARGET_VITALSIGNS`

Suggested packet organization:

```text
uint16 numTargets
uint16 recordSize

repeated record:
    uint32 trackerTid
    uint16 rangeBin
    uint16 qualityState
    float rangeMeters
    float breathingRateBpm
    float heartRateBpm
    float breathingConfidence
    float heartConfidence
    float phaseDeviation
    float horizontalSpeed
    uint32 motionFlags
```

The tracker TID must be explicit. A patient-slot index is insufficient because TIDs can appear, disappear, and be reused.

## 10. Build Requirements

### 3D People Tracking

Project specifications identify:

- device: IWR6843
- MSS target: Cortex-R4F
- DSS target: C674x
- mmWave SDK: `03.05.00.04`
- SYS/BIOS: `6.73.01.01`
- TI ARM and C6000 compiler products referenced by CCS project settings
- modified SDK data path: `custom_sdk_files\sdk3`

CCS projects:

- `src\6843\3D_people_track_6843_dss.projectspec`
- `src\6843\3D_people_track_6843_mss.projectspec`

Expected build order:

1. DSS project
2. MSS project

The DSS post-build creates the DSS binary. The MSS post-build invokes the image creator and combines the MSS, RadarSS, and DSS images.

Expected final output:

`3D_people_track_6843_demo.bin`

The distributed copy is:

`prebuilt_binaries\3D_people_track_6843_demo.bin`

### Vital Signs With People Tracking

The documentation indicates an IWR6843 SDK 3.5 generation application, but the local package does not contain:

- CCS project specifications
- compiler/linker settings
- source imports
- linker command files
- post-build command
- source-level output path

Only the prebuilt ISK/AOP binaries can be used directly.

## 11. Risk Assessment

### ISK Binary on ODS: High Risk

The package does not claim ODS support. Even if the binary starts, antenna and phase assumptions can invalidate tracking or vital estimates.

### ODS Antenna Mismatch: High Risk

Vital signs depend on small phase changes. Incorrect antenna ordering, phase rotation, or RX compensation can create plausible-looking but incorrect waveforms and rates.

### Single-Target Vital Limitation: High Risk for Multi-Person Claims

The distributed demo is documented for one person. It must not be presented as multi-person vital monitoring without source confirmation and controlled validation.

### CPU and Memory Load: Medium to High Risk

One target requires long slow-time buffers and repeated filtering/rate estimation. Replicating this for multiple TIDs may exceed real-time or memory margins, particularly alongside Capon 3D processing and tracking.

### TID/Patient-ID Mismatch: High Risk

The 1040 payload contains an `id`, but its relation to GTRACK TID is not verifiable. Incorrect assumptions can assign one person's vital signs to another person.

### Frame-Rate and Signal-Processing Mismatch: High Risk

The known 3D ODS and vital ISK configurations use different frame periods and chirp patterns. Vital filter coefficients, buffer lengths, and estimator intervals must use the actual frame rate.

### UART Bandwidth: Low to Medium Risk

Compact per-target rates are inexpensive. Multiple waveform arrays per target can materially increase UART traffic and should be optional.

### Calibration and Environmental Motion: High Risk

Posture transitions, multipath, sensor vibration, and subject movement can dominate chest phase. Vital processing must be gated by motion and quality, especially when associated with tracker TIDs.

## Recommended Next Actions

1. Request or locate the IWR6843 Vital Signs With People Tracking source package matching mmWave SDK 3.5.
2. Before any firmware change, capture and inspect UART frames from the unmodified supported ISK/AOP demo on supported hardware to confirm its emitted TLVs and the meaning of TLV 1040 `id`.
3. Keep IWR6843ISK-ODS on the proven 3D People Tracking firmware for the current system.
4. Validate vital estimation independently using the existing second-sensor/AWR1642 work.
5. If the missing IWR6843 source is obtained, port one-target vital processing into the 3D ODS source first.
6. Emit an explicit tracker-TID-bearing vital TLV.
7. Validate one stable sitting target before attempting two simultaneous vital targets.

## Final Decision

From the source currently available:

- **3D People Tracking is a valid, buildable IWR6843ISK-ODS firmware base.**
- **Vital Signs With People Tracking is binary-only for IWR6843ISK/AOP and cannot currently be source-merged.**
- **Use separate radars now.**
- **If the missing vital source becomes available, port vital processing into the 3D People Tracking ODS base rather than treating the ISK vital binary as an ODS firmware.**
