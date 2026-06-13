# AWR1642 External Datasets And Repos

## A. Executive Summary

The most useful dataset found is the University of Twente / 4TU dataset titled **"Comprehensive mm-Wave FMCW Radar Dataset for Vital Sign Monitoring in Diverse Physiological Scenarios"**, DOI `10.4121/48acba04-96bc-4131-b52f-9e18458ad92b`. It is directly relevant because it uses **TI AWR1642BOOST with DCA1000EVM** and includes raw ADC data, processed chest displacement/range-map data, and reference breathing/heart-rate measurements.

The most useful live-code reference is **ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2**. It is directly AWR1642/IWR1642-oriented, includes serial configuration/parsing code, and includes a Driver Vital Signs demo cfg plus parser fields for breathing and heart estimates.

**KylinC/mmVital-Signs** is useful as an API and algorithm reference for TI mmWave vital-sign workflows. Its README claims support for AWR1642BOOST/IWR1642BOOST and other TI mmWave boards, but it appears to depend on already-flashed TI Vital Signs firmware and UART/TLV output. Treat it as reference code until we verify compatible firmware/config for our AWR1642.

**TI SWRA581** is required reference material if we use AWR1642 + DCA1000 raw ADC capture. It is not a model or parser by itself; it defines how to interpret raw ADC binary/lane/IQ data.

Recommended next step: first decide whether a **DCA1000** is available. If yes, start offline with the Twente/4TU processed sample/readme and build `ADC -> range FFT -> phase -> breathing/heart` on known data. If no, pursue the UART Driver Vital Signs path using the ibaiGorordo cfg/parser style and locate/flash a compatible AWR1642 vital-sign binary.

## B. Dataset: University of Twente / 4TU AWR1642 Vital-Sign Dataset

**Exact title:** Comprehensive mm-Wave FMCW Radar Dataset for Vital Sign Monitoring in Diverse Physiological Scenarios

**DOI:** `10.4121/48acba04-96bc-4131-b52f-9e18458ad92b`

**Device used:** TI **AWR1642BOOST**.

**DCA1000 usage:** Yes. The dataset records raw ADC samples using AWR1642BOOST with **DCA1000EVM**.

**Data types included:**

- Raw ADC data samples.
- 1D chest displacement signals.
- Chest range-map matrices.
- Heart-rate and respiratory-rate reference measurements.

**Labels/reference sensors:** The dataset was validated against a **Polar H10** reference sensor, with ECG-derived heart-rate and respiratory-rate measurements reported in the associated paper.

**Participant/scenario info:** The paper describes 20 participants, three radar distances, and five physiological scenarios. The documented distances are 1 m, 1.5 m, and 2 m. The physiological cases include normal breathing, breath hold, deep breathing, normal heart rate, and post-exercise elevated heart rate.

**License:** CC BY-NC-SA 4.0 on the 4TU dataset page.

**Expected download/access steps:**

1. Open the 4TU DOI page.
2. Download only the readme/metadata and a small processed sample first.
3. Avoid downloading the full raw archive initially because the dataset is very large, about 5 TB.
4. Inspect folder layout, cfg/capture metadata, sampling rates, chirp settings, and processed signal formats.

**Why it is useful for this project:**

- It is directly AWR1642BOOST-based.
- It provides real vital-sign reference labels.
- It includes both raw ADC and processed intermediate signals, so we can validate each stage of the pipeline.
- It is suitable for offline algorithm development before touching live hardware.

**Limitations:**

- The raw data path likely requires DCA1000-compatible parsing and significant storage.
- The dataset is offline; it does not directly solve live UART parsing.
- It may not match our final mounting, room, subject posture, or side-by-side IWR6843/AWR1642 setup.
- The license is non-commercial/share-alike; reuse constraints must be respected.

## C. Repo: KylinC/mmVital-Signs

**Repo purpose:** Python package/API for TI mmWave vital-sign sensing workflows.

**Supported TI hardware claims:** The README says the package is designed for TI mmWave sensors including IWR6843ISK-ODS, IWR6843ISK, IWR6843AOP, AWR1642BOOST, IWR1642BOOST, and related xWR6843/xWR1843/xWR1642/xWR1443 families.

**AWR1642/xWR16xx mention:** Yes, AWR1642BOOST/IWR1642BOOST and xWR1642 are explicitly mentioned in the README.

**Algorithm type:** Reference for TI mmWave vital-sign UART/API workflows. The exposed API retrieves headers, vital-sign status, vital-sign signals, and range-bin data. It is useful for phase/range-bin based vital-sign extraction ideas, but the repo should be inspected locally before relying on any exact processing details.

**Dependencies:** The README documents installation via `pip install mmVital-Signs` or installing from GitHub. Full dependency details should be checked from the repo packaging files when cloned.

**Useful files/functions:**

- `mmVS/main.py`
- `mmVS/utility.py`
- `mmVS.VitalSign(...)`
- `start_sensor()`
- `tlv_read(...)`
- `getHeader()`
- `getVitalSignStatus()`
- `getVitalSignSignals()`
- `getRangeBin()`

**What needs adaptation:**

- Confirm the exact UART packet/TLV format expected by this package.
- Confirm that our AWR1642 firmware produces matching output.
- Add our COM-port/cfg handling only after standalone AWR1642 bring-up works.
- Avoid coupling it to the current IWR6843 posture UI until the vital-sign path is independently validated.

**Raw ADC, UART TLV, or processed data:** The README says the radar must be flashed with Vital Signs binaries and shows UART-style sensor interaction. Treat this as **UART/TLV or firmware-output oriented**, not a DCA1000 raw ADC reader.

## D. Repo: ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2

**Repo purpose:** Python examples for reading and plotting real-time data from AWR1642/IWR1642 boards using TI mmWave SDK 2-era UART output.

**AWR1642/IWR1642 support:** Directly supports AWR1642/IWR1642. The README states it was tested with AWR1642BOOST.

**Serial parser functions:** The repo includes scripts for reading object-detection data and a Driver Vital Signs lab parser. The Driver Vital Signs parser includes fields such as:

- `rangeBinIndexMax`
- `rangeBinIndexPhase`
- `unwrapPhasePeak_mm`
- `outputFilterBreathOut`
- `outputFilterHeartOut`
- `heartRateEst_FFT`
- `heartRateEst_FFT_4Hz`
- `heartRateEst_xCorr`
- `heartRateEst_peakCount`
- `breathingRateEst_FFT`
- `breathingEst_xCorr`
- `breathingEst_peakCount`
- breath/heart confidence metrics
- breath/heart waveform energy
- `motionDetectedFlag`

**Cfg sender functions:** The general repo includes serial setup/config sender examples for AWR1642-style demos. These are useful references for a future custom AWR1642 runner, but we are not creating that runner now.

**Driver vital signs cfg path:** `Driver vital signs demo/xwr1642_profile_VitalSigns_20fps_Front.cfg`

Important cfg lines from that file include:

```text
sensorStop
flushCfg
dfeDataOutputMode 1
channelCfg 15 3 0
adcCfg 2 1
adcbufCfg -1 0 1 1 1
profileCfg 0 77 7 6 57 0 0 70 1 200 4000 0 0 30
chirpCfg 0 0 0 0 0 0 0 1
chirpCfg 1 1 0 0 0 0 0 2
frameCfg 0 0 2 0 50 1 0
guiMonitor -1 1 0 0 0 0 0
vitalSignsCfg 0.3 0.9 256 512 4 0.1 0.05 100000 300000
motionDetection 1 20 2.0 0
sensorStart
```

**Binary or only cfg/parser:** The repo provides cfg/parser/reference code. It does not appear to provide a TI firmware binary.

**How we can reuse it:**

- Use the Driver Vital Signs cfg as a starting point for AWR1642 UART vital-sign bring-up.
- Use the parser field order as a reference for breathing/heart-rate output.
- Use config-send and serial-read style later if we build a custom runner.
- Do not integrate it into the IWR6843 UI until AWR1642 vital signs works standalone.

## E. TI SWRA581 Raw ADC Guide

**Document:** TI SWRA581, "mmWave Radar Device ADC Raw Data Capture".

**xWR16xx + DCA1000 format:** This guide is the key TI reference for raw ADC capture from mmWave devices through DCA1000. It covers device/DCA1000 capture flow and raw binary interpretation.

**Complex IQ layout:** For AWR1642 raw ADC work, the parser must respect the capture configuration: complex-vs-real mode, ADC sample count, chirps per frame, RX channels, lane layout, interleaving mode, IQ sample width, and DCA1000 packetization. The exact parser should be derived from SWRA581 plus the dataset/capture cfg metadata, not guessed.

**Receiver/lane assumptions:** The parser must know:

- number of enabled RX antennas
- number of TX/chirps per frame
- number of ADC samples
- complex or real output
- LVDS lane configuration
- interleaved/non-interleaved data
- frame/chirp ordering

**What fields we need in capture config:**

- `channelCfg`
- `adcCfg`
- `adcbufCfg`
- `profileCfg`
- `chirpCfg`
- `frameCfg`
- DCA1000 capture JSON or equivalent capture-card settings

**How this affects our parser:** The Twente raw ADC files and any future AWR1642+DCA1000 captures should be parsed with a config-driven reader. Hard-coding the layout would be fragile and likely wrong when cfg/lane settings change.

## F. Recommended Implementation Plan

### Milestone 1: Download/inspect a small Twente/4TU sample

Download only metadata/readme and, if available, a small processed sample. Confirm file structure, sample rates, cfg metadata, reference-label format, and whether processed chest displacement can be read without parsing raw ADC.

### Milestone 2: Write reader for dataset format

Build a local offline reader for the processed data first. The first validation target should be loading a chest displacement signal and matching its reference respiratory/heart-rate labels.

### Milestone 3: Build baseline signal chain

Implement:

```text
ADC -> range FFT -> select chest range bin -> unwrap phase -> displacement -> breathing/heart estimate
```

Start from the processed dataset files if possible, then move downward to raw ADC parsing with SWRA581.

### Milestone 4: Use mmVital-Signs algorithms as reference

Inspect `KylinC/mmVital-Signs` locally later for its API, signal extraction choices, filters, and range-bin/vital-sign status handling. Reuse ideas only after confirming license and firmware compatibility.

### Milestone 5: Use ibaiGorordo code for AWR1642 serial/cfg style if needed

If a compatible Driver Vital Signs firmware is available, use the ibaiGorordo cfg/parser as the fastest live AWR1642 UART bring-up reference.

### Milestone 6: Collect our own AWR1642+DCA1000 data

If DCA1000 is available, collect controlled chest-facing data with known posture and a reference sensor. Keep this independent of the IWR6843 UI first.

### Milestone 7: Fuse with IWR6843 posture output

Keep IWR6843 as the master tracker/posture sensor. Use AWR1642 as a vital-sign specialist. For first fusion, assume side-by-side alignment and match by time/range/angle. Vitals should be trusted mainly when the IWR6843 target is static or mostly static.

## G. Decision Points

**Do we have DCA1000?**

- Yes: use Twente/4TU + SWRA581 as the main offline path.
- No: focus on AWR1642 UART Driver Vital Signs firmware/config/parser.

**Can we download the dataset?**

- The full dataset is very large. Start with readme/processed files only.
- If download access is limited, use repo code and our own captures instead.

**Offline first or live first?**

- Offline first is safer for algorithm development and repeatability.
- Live first is faster only if a compatible AWR1642 vital-sign binary is already available.

**Do we need a ground-truth sensor?**

- Yes for validation. Polar H10 or another reliable reference is strongly recommended before claiming accuracy.

**Single-person or multi-person?**

- Start single-person. AWR1642 vital signs are most reliable for a selected/static chest target.
- Multi-person fusion should be treated as a later ambiguity-resolution problem using IWR6843 track IDs plus range/angle gating.

## References

- 4TU dataset page: https://data.4tu.nl/datasets/48acba04-96bc-4131-b52f-9e18458ad92b/1
- Dataset DOI: https://doi.org/10.4121/48acba04-96bc-4131-b52f-9e18458ad92b
- Associated arXiv paper: https://arxiv.org/abs/2405.12659
- KylinC/mmVital-Signs: https://github.com/KylinC/mmVital-Signs
- ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2: https://github.com/ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2
- Driver Vital Signs demo folder: https://github.com/ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2/tree/master/Driver%20vital%20signs%20demo
- Driver vital-sign cfg: https://github.com/ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2/blob/master/Driver%20vital%20signs%20demo/xwr1642_profile_VitalSigns_20fps_Front.cfg
- TI SWRA581B ADC raw data capture guide: https://www.ti.com/lit/an/swra581b/swra581b.pdf
