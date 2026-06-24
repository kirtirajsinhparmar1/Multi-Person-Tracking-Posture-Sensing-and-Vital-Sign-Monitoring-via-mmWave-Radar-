# Dataset adapter policy

These adapters accept generic phase/displacement CSV files, generic reference
label CSV files, and this project's `selected_chest_beam_trace.csv` format.

The current workflow uses AWR1642BOOST UART FE03 selected chest-beam samples.
It does not use DCA1000, raw ADC capture, or LVDS dataset parsing.

Public datasets are usable only after conversion to timestamped phase or
displacement windows with compatible heart/breath reference labels.
