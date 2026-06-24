# AWR1642 Fake VitalPhaseTrace Live Reader

`run_live_vital_phase_reader.py` is for the copied AWR1642 non-OS firmware that emits the synthetic 36-byte `VitalPhaseTrace` payload as TLV `0xFE01`.

The reader opens only the data COM port. It does not send radar configuration commands. Depending on the flashed firmware and selected `.cfg`, the config/CLI port may still need to be configured separately before data frames begin.

Expected result:

- Parsed `TLV 0xFE01` samples are printed with frame, phase, range, magnitude, and motion fields.
- After at least about 10 seconds of samples, estimates should approach 15 bpm breathing and 72 bpm heart rate.
- With `--out`, samples are saved to `vital_phase_samples.csv` and the final estimate to `final_estimates.json`.

Example:

```powershell
python custom_iwr6843_fall_logger\awr1642_vitals\phase_vitals\tlv_parser\run_live_vital_phase_reader.py --data-com COMx --baud 921600 --duration 60 --out logs\awr1642_fake_tlv_live
```

Useful options:

- `--fs 20`: expected TLV sample rate used by the estimator.
- `--print-every 20`: update estimates every 20 parsed samples after enough data exists.
- `--debug`: print UART framing and missing-TLV diagnostics.
- `--no-estimator`: parse and log TLV samples without running the estimator.

Install the runtime serial dependency if needed:

```powershell
python -m pip install pyserial
```

Use the data UART COM port, not the config/CLI COM port. Close TI Visualizer and other programs that may already own the data port before running the reader.
