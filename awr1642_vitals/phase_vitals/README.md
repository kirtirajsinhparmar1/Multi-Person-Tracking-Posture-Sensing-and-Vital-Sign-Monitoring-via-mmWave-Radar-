# AWR1642 Phase Vitals

Current milestone: PC-side breathing and heart-rate estimation from a phase or I/Q trace.

This module exists so the vital-sign algorithm can be validated before editing AWR1642 firmware. It does not open COM ports, flash hardware, or depend on DCA1000.

## Inputs

- Synthetic phase trace.
- CSV phase trace with columns such as `time,phase` or `frame,phase`.
- CSV I/Q trace with columns such as `time,I,Q`, `frame,I,Q`, `i,q`, or `I,Q`.
- Later: custom firmware `VITAL_PHASE_TRACE` TLV from AWR1642.

## Outputs

- `breathingRateEst_FFT`
- `breathingEst_xCorr`
- `breathingEst_peakCount`
- `heartRateEst_FFT`
- `heartRateEst_FFT_4Hz`
- `heartRateEst_xCorr`
- `heartRateEst_peakCount`
- `confidenceMetricBreathOut`
- `confidenceMetricHeartOut`
- `sumEnergyBreathWfm`
- `sumEnergyHeartWfm`
- `motionDetectedFlag`
- `quality_state`

## Synthetic Demo

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\run_phase_vitals_demo.py --synthetic --fs 20
```

## Final Architecture

IWR6843 remains the master people tracking and posture sensor:

- target ID
- 3D position
- posture
- movement state

AWR1642 becomes the vital-sign specialist:

- custom firmware sends phase trace or vital estimates
- PC estimates breathing and heart rate from the chosen range bin

The PC fusion layer later matches AWR1642 vital estimates to IWR6843 tracked targets by time, range, and angle. Vitals should be trusted only when the corresponding IWR6843 target is static or nearly static.
