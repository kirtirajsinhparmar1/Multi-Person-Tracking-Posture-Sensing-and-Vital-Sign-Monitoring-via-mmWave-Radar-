# External Repo/Data Inventory Commands

These commands are for later manual use. They were not executed while creating this research note.

## Recommended Local Layout

```text
custom_iwr6843_fall_logger/
  awr1642_vitals/
    external_research/
      repos/
      data/
        twente_4tu_sample/
```

## Clone Small Code Repos Later

```powershell
cd C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\custom_iwr6843_fall_logger\awr1642_vitals\external_research
mkdir repos
cd repos
git clone https://github.com/KylinC/mmVital-Signs.git
git clone https://github.com/ibaiGorordo/AWR1642-Read-Data-Python-MMWAVE-SDK-2.git
```

## Dataset Links

Do not download the full Twente/4TU raw dataset until storage and time are planned. Start with readme/metadata and a small processed sample if the portal allows selecting individual files.

- 4TU dataset page: https://data.4tu.nl/datasets/48acba04-96bc-4131-b52f-9e18458ad92b/1
- DOI: https://doi.org/10.4121/48acba04-96bc-4131-b52f-9e18458ad92b
- Associated paper: https://arxiv.org/abs/2405.12659

Suggested manual folder for a first small sample:

```text
custom_iwr6843_fall_logger\awr1642_vitals\external_research\data\twente_4tu_sample
```

## TI Raw ADC Reference

Download/open this reference when implementing raw ADC parsing:

- https://www.ti.com/lit/an/swra581b/swra581b.pdf

Parser implementation should be driven by the radar cfg plus any DCA1000 capture JSON/metadata, not by hard-coded assumptions.
