# TI Pose/Fall Dataset Audit

## Is the dataset balanced enough?

Total usable windows: 19207
Windows per class: {'STANDING': 5301, 'SITTING': 4745, 'LYING': 3230, 'FALLING': 3260, 'WALKING': 2671}
Recordings per class: {'STANDING': 8, 'SITTING': 9, 'LYING': 6, 'FALLING': 24, 'WALKING': 5}
Class imbalance ratio by windows: 1.98
Recording imbalance ratio: 4.80
Suspicious recordings flagged: 27

The dataset is usable if suspicious recordings are reviewed, but random window split is optimistic because adjacent windows from one CSV recording are highly correlated.

Recommendations:
- For honest validation, use recording-level split.
- For training, use all cleaned windows with class_weighting balanced.
- Avoid random window split for final claims.
- Downsampling can be used for stress testing but may discard useful data.
- Weighted loss or weighted sampler is preferred over throwing data away.
