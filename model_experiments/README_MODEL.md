# TI Pose/Fall Model Training

This folder contains the PC training/export path for TI Pose/Fall style
176-feature windows.

## Commands

Quick plot test:

```powershell
python train_or_export_ti_pose_model.py --classes-zip "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\Pose_And_Fall_Detection\retraining_resources\dataset\classes.zip" --epochs 5 --output outputs\quick_plot_test
```

100-epoch plot test:

```powershell
python train_or_export_ti_pose_model.py --classes-zip "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\Pose_And_Fall_Detection\retraining_resources\dataset\classes.zip" --epochs 100 --output outputs\ti_100epoch_plots
```

Full 1600-epoch training:

```powershell
python train_or_export_ti_pose_model.py --classes-zip "C:\Users\UBESC\Desktop\radar_toolbox_4_00_00_05\source\ti\examples\Industrial_and_Personal_Electronics\Pose_And_Fall_Detection\retraining_resources\dataset\classes.zip" --epochs 1600 --patience 0 --output outputs\ti_full_1600
```

## Outputs

The `--output` argument is an output directory. The script writes:

- `best_model.pt`: best checkpoint by validation macro F1
- `final_model.pt`: final epoch checkpoint
- `ti_pose_model.pt`: best checkpoint copied to the stable model name
- `ti_pose_model.onnx`: ONNX export from the best checkpoint
- `metrics.json`: final metrics and training metadata
- `train_history.csv`: per-epoch loss, accuracy, F1, learning rate, and batch count
- `classification_report.txt`: scikit-learn classification report
- `confusion_matrix.csv`: confusion matrix counts
- `per_class_metrics.csv`: precision, recall, F1, and support by class
- `sample_predictions.csv`: sample prediction probabilities
- `plot_manifest.json`: generated plot list and descriptions
- `plots\*.png`: training and validation figures

## Plots To Inspect

- `plots\loss_curve.png`: training loss and validation loss
- `plots\accuracy_curve.png`: training accuracy and validation accuracy
- `plots\f1_curve.png`: validation macro and weighted F1
- `plots\confusion_matrix_counts.png`: raw class confusion counts
- `plots\confusion_matrix_normalized.png`: row-normalized confusion percentages
- `plots\per_class_metrics.png`: precision, recall, and F1 by class
- `plots\class_distribution.png`: total, train, and test windows by class
- `plots\confidence_histogram.png`: prediction confidence for correct and incorrect windows
- `plots\loss_accuracy_combo.png`: loss and accuracy in one figure

## Interpreting Curves

Training loss down while validation loss rises means overfitting.

Both losses dropping and then plateauing is usually healthy.

If validation F1 plateaus early, use the best epoch checkpoint rather than the
final epoch. The script selects `best_model.pt` and exports ONNX using validation
macro F1.

The current split is a random window split. It can be optimistic because nearby
windows from the same recording can be very similar and may appear in both train
and test sets. A future improvement should use a recording-level split so all
windows from a recording stay entirely in train or test.
