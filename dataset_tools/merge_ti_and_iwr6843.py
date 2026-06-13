"""Skeleton for combining TI Pose/Fall data with IWR6843 captures.

This is intentionally not a full merge implementation yet.

Planned merge approach:
1. Extract TI ``classes.zip`` into a read-only staging folder.
2. Convert TI samples into the same 176-column channel-major CSV schema used by
   ``features_176.csv``.
3. Keep source-domain metadata for every row: ``source=ti_iwrl6432`` or
   ``source=iwr6843_ods``.
4. Train baseline models on TI only, IWR6843 only, and mixed data.
5. Compare validation metrics by subject, class, and sensor domain before using
   a mixed model live.

Sensor-domain warning:
TI's Pose/Fall model and data came from IWRL6432 with its own mounting,
coordinate orientation, radar front end, and point-cloud distribution. Mixing
that data with IWR6843ISK-ODS captures should be treated as domain adaptation,
not simple row concatenation.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    args = parse_args()
    print("Merge skeleton only. No files were modified.")
    print(f"TI classes.zip: {Path(args.ti_classes_zip)}")
    print(f"IWR6843 root:   {Path(args.iwr6843_root)}")
    print(f"Output root:    {Path(args.out)}")
    print()
    print("Next implementation step: write converters that normalize both sources")
    print("to the same 176-column channel-major schema plus source metadata.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Skeleton for future TI classes.zip + IWR6843 capture merge."
    )
    parser.add_argument("--ti-classes-zip", default="classes.zip", help="TI Pose/Fall classes.zip")
    parser.add_argument("--iwr6843-root", default="dataset/iwr6843_pose", help="IWR6843 dataset root")
    parser.add_argument("--out", default="dataset/merged_pose", help="Future merged output folder")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
