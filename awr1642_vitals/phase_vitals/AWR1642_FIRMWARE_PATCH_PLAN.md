# AWR1642 Firmware Patch Plan

This note is inspection and planning only. No firmware files were modified, no board was flashed, and no COM ports were opened.

## Candidate Folders Inspected

### 1. `source\ti\examples\Out_Of_Box_Demo\src\xwr1642`

- Target: xWR1642/AWR1642-style out-of-box demo.
- Source present locally: project specs only in this Radar Toolbox folder.
- Project specs: `out_of_box_1642_mss.projectspec`, `out_of_box_1642_dss.projectspec`.
- Runtime model: MSS + DSS SDK-style demo.
- SDK dependency: project specs reference SDK-installed source paths rather than carrying all source locally here.
- UART/TLV output definitions: expected in the SDK xWR16xx mmw demo source imported by the project specs.
- Range processing: expected in DSS data path from SDK mmw demo.
- Difficulty to add `VITAL_PHASE_TRACE`: good architecture if the matching SDK source/build environment is installed, because the OOB demo already has the standard UART TLV packet flow. The local toolbox copy does not include all source in this folder.

### 2. `source\ti\examples\Fundamentals\nonos_oob\nonos_oob_16xx`

- Target: AWR1642/xWR16xx non-OS OOB.
- Source present locally: yes.
- Project specs: `src\1642\mmwNonOS_mss.projectspec`, `src\1642\mmwNonOS_dss.projectspec`.
- Runtime model: MSS + DSS, non-OS.
- UART/TLV output definitions: common message headers and MSS files under `src\1642\common` and `src\1642\mss`.
- Frame/result packets: MSS output path is expected in `mss_main.c`; DSS/MSS message exchange is defined in common headers.
- Range processing/range FFT: likely in `src\1642\dss\dss_data_path.c`.
- Difficulty to add `VITAL_PHASE_TRACE`: best self-contained local starting point because the source is present. It may use older SDK assumptions, so build setup must match its documented toolchain.

### 3. `source\ti\examples\Automotive_ADAS_and_Parking\short_range_radar\src\1642`

- Target: AWR1642 short range radar.
- Source present locally: yes, including common, MSS, and DSS folders.
- Project specs: present in the 1642 source root.
- Runtime model: MSS + DSS.
- UART/TLV output definitions: automotive/SRR-specific common output and message headers.
- Range processing/range FFT: yes, but tied to SRR automotive processing and object detection.
- Difficulty to add `VITAL_PHASE_TRACE`: technically feasible but more invasive. Treat as range-processing and packetization reference, not the first base for vitals.

### 4. `source\ti\examples\Fundamentals\CAN_Data_Output\1642_object_data_over_can`

- Target: AWR1642 object data over CAN.
- Source present locally: yes.
- Runtime model: object data output focused on CAN, with DSS/MSS source.
- UART/TLV output definitions: useful as an output-transport reference, but the primary data path is CAN-oriented.
- Range processing/range FFT: inherited from object data demo path.
- Difficulty to add `VITAL_PHASE_TRACE`: not ideal for first UART vital phase output because output transport is not the same goal.

## Firmware Base Ranking

1. Best first base if the matching SDK source/build environment is available: `Out_Of_Box_Demo\src\xwr1642`.
   - Reason: standard mmWave OOB packet/TLV architecture is the cleanest place to add a custom UART TLV.
2. Best self-contained local base: `Fundamentals\nonos_oob\nonos_oob_16xx`.
   - Reason: full local MSS/DSS source is present, including range data path and message plumbing.
3. Reference only: `short_range_radar\src\1642`.
   - Reason: useful range-processing reference, but automotive-specific and more complex.
4. Reference only: `CAN_Data_Output\1642_object_data_over_can`.
   - Reason: useful transport/reference code, but CAN-oriented.

## Proposed Minimal Patch Location

The first firmware milestone should add `MMWDEMO_OUTPUT_MSG_VITAL_PHASE_TRACE` after range processing has produced a complex range-bin value for the selected chest range bin:

1. DSS range processing selects or exposes candidate range-bin complex samples.
2. DSS sends compact vital phase data or selected range-bin data to MSS.
3. MSS UART packet code appends the custom TLV.
4. PC estimates breathing/heart over slow time with `phase_vitals_estimator.py`.

## Practical Recommendation

Start with the xWR1642 OOB demo if the SDK source imported by the project specs is available on this PC. If build/source resolution is painful, use `nonos_oob_16xx` as the first local patch base because the relevant C files are present in the toolbox.

Do not attempt onboard BPM estimation first. Send phase/IQ per frame, verify the PC estimator, then add onboard rolling buffers and vital estimation once the phase trace is validated.
