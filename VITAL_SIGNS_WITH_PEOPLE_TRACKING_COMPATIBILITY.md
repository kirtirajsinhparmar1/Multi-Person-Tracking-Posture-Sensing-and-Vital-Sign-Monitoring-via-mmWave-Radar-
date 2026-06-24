# TI Vital Signs With People Tracking Compatibility

## Executive Summary

The Radar Toolbox contains TI's `Vital_Signs_With_People_Tracking` example for
IWR6843ISK and IWR6843AOP. It provides people tracking plus vital-sign output,
but the supplied release notes describe vital-sign extraction for one person.

There is no supplied IWR6843ISK-ODS binary or ODS chirp configuration in this
example. The existing IWR6843ISK-ODS 3D People Tracking firmware therefore
cannot be assumed to produce vital signs, even though the vendored TI parser
already recognizes vital-sign TLV type 1040.

The custom UI now treats vital-sign availability separately from posture:
a tracked person must be stably `SITTING` before becoming eligible, and heart
or breathing values remain empty until an actual vital-sign TLV is received.

## TI Example File Map

Example root:

`source\ti\examples\Industrial_and_Personal_Electronics\Vital_Signs\Vital_Signs_With_People_Tracking`

Documentation:

- `docs\vital_signs_with_people_tracking_user_guide.html`
- `docs\vital_signs_with_people_tracking_release_notes.html`

Prebuilt binaries:

- `prebuilt_binaries\vital_signs_tracking_6843ISK_demo.bin`
- `prebuilt_binaries\vital_signs_tracking_6843AOP_demo.bin`

Chirp configurations:

- `chirp_configs\vital_signs_ISK_6m.cfg`
- `chirp_configs\vital_signs_ISK_2m.cfg`
- `chirp_configs\vital_signs_AOP_6m.cfg`
- `chirp_configs\vital_signs_AOP_2m.cfg`

The configurations include a vital-sign command such as:

`vitalsign 15 300`

## Board Compatibility

The supplied artifacts explicitly target:

- IWR6843ISK
- IWR6843AOP

No IWR6843ISK-ODS binary or ODS configuration was found. The ISK binary and
configuration must not be treated as proven compatible with the ODS antenna
geometry.

## Tracking and Vital-Sign Scope

The example combines people tracking with vital-sign processing. However, the
release notes state that tracking/localization extracts data for heart and
breathing measurement for one person. This is evidence for one vital-sign
target, not simultaneous vital measurements for every tracked person.

The TI visualizer source contains UI capacity for more than one patient, but
that does not prove that this firmware emits independent vital measurements
for multiple TIDs. Any mapping between the vital payload `id` and a tracker TID
must be validated with the actual firmware.

TI documentation also indicates that the selected person should remain stable
and that range-bin stabilization can take approximately 30 seconds.

## UART TLV

The TI visualizer parser defines:

`MMWDEMO_OUTPUT_MSG_VITALSIGNS = 1040`

The payload parser uses the equivalent of `2H33f` and exposes:

- `id`
- `rangeBin`
- `breathDeviation`
- `heartRate`
- `breathRate`
- 15 heart-waveform samples
- 15 breathing-waveform samples

The custom vendored parser already contains TLV 1040 handling in:

- `ti_style_vendor\common\tlv_defines.py`
- `ti_style_vendor\common\parseFrame.py`
- `ti_style_vendor\common\parseTLVs.py`

Parsed data is placed in `outputDict["vitals"]`.

## Answers

1. **Is there a prebuilt binary for IWR6843?**

   Yes, for IWR6843ISK and IWR6843AOP. No ODS-specific binary was found.

2. **Is there an ODS configuration?**

   No. Only ISK and AOP configurations were found.

3. **Does it support multi-person tracking?**

   It uses people tracking, but that does not imply multi-person vital-sign
   estimation.

4. **Does it support multi-person vital signs?**

   The release notes describe vital-sign measurement for one person. Treat it
   as selected/single-target vital signs until hardware tests prove otherwise.

5. **What vital TLV does it output?**

   TLV 1040 with target/range-bin identification, breathing and heart rates,
   waveform samples, and breathing deviation.

6. **Can the current COM6/COM7 UI parse it directly?**

   The vendored parser can decode TLV 1040. The currently flashed
   `3D_people_track_6843_demo.bin` does not emit that TLV, so the current
   firmware/config combination cannot provide vital values.

7. **What must change?**

   A compatible firmware/configuration must emit TLV 1040 or another documented
   vital TLV. For ODS, firmware and antenna/config compatibility must be
   established first. The UI must also validate whether the TLV `id` maps to a
   tracker TID or represents only one selected target.

## Custom UI Gating

The custom integration now:

- tracks eligibility independently for each TID;
- requires stable `SITTING`, sufficient pose confidence, and low horizontal
  speed;
- pauses or resets eligibility after posture/motion violations;
- keeps pose confidence separate from vital quality;
- never invents breathing or heart rates;
- reports `ELIGIBLE_NO_DATA` and `NO_VITAL_TLV` when posture gating passes but
  no actual measurement exists.

This gating is software readiness only. It does not make the current People
Tracking firmware produce vital signs.

## Recommended Next Step

Keep using the current IWR6843ISK-ODS firmware to validate the sitting gate and
UI states. Separately determine whether TI's ISK vital-sign firmware can be
ported safely to ODS or whether the planned AWR1642 vital-sign stream will be
the production source. Only mark a TID `ACTIVE` after a real measurement is
received and its target association has been validated.
