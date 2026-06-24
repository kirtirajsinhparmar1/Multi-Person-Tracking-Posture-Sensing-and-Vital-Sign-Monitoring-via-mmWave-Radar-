from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dual_sensor_fusion.awr_bin_selector import SelectorConfig
from dual_sensor_fusion.beam_lock import (
    BEAM_HOLD,
    BEAM_LOCKED,
    BEAM_CANDIDATE,
    BeamLockConfig,
    BeamLockManager,
    LockedPhaseTracker,
)
from dual_sensor_fusion.chest_point_estimator import (
    ChestEstimatorConfig,
    estimate_chest_point,
)
from dual_sensor_fusion.coordinate_transform import (
    TransformConfig,
    compute_awr_spatial_target,
    expected_awr_range,
    transform_iwr_point_to_awr,
)
from dual_sensor_fusion.dual_sensor_logger import (
    FE03_ACTIVE,
    FE03_LOST,
    FE03_STALE,
    Fe03LivenessTracker,
    FusionConfig,
    FusionEngine,
    convert_awr_virtual_ant_window,
)
from dual_sensor_fusion.fusion_types import (
    AwrBinSample,
    AwrBinWindow,
    BinSelection,
    IwrTarget,
)
from dual_sensor_fusion.posture_gate import (
    MONITORING,
    MONITORING_POSE_GRACE,
    PAUSED_NOT_SITTING,
    SEATED_LOCK,
    WAITING_FOR_SITTING,
    SittingGateConfig,
)
from dual_sensor_fusion.run_dual_sensor_fusion_ui import (
    DEFAULT_HUMAN_MODEL_DIR,
    DemoPoseManager,
    _make_demo_iwr_output,
    _make_ti_args,
    build_arg_parser,
)
from dual_sensor_fusion.vital_estimator_bridge import (
    VitalEstimatorBridge,
    VitalEstimatorConfig,
)
from awr1642_vitals.phase_vitals.azimuth_beamforming import (
    BeamformingConfig,
    select_range_azimuth_cell,
)
from awr1642_vitals.phase_vitals.tlv_parser.fake_ti_uart_packet import (
    make_fake_vital_phase_virtual_ant_window,
)
from human_model_renderer import ObjMesh, _mesh_world_bounds


def fake_window(frame_number: int = 100) -> AwrBinWindow:
    timestamp = 1000.0 + frame_number / 10.0
    resolution = 1.7541 / 37.0
    bins = []
    for bin_index in range(20, 61):
        magnitude = 2500.0 if bin_index == 37 else 500.0 + bin_index
        phase = 0.2 * math.sin(frame_number * 0.1)
        bins.append(
            AwrBinSample(
                timestamp=timestamp,
                frameNumber=frame_number,
                binIndex=bin_index,
                rangeMeters=bin_index * resolution,
                iValue=magnitude * math.cos(phase),
                qValue=magnitude * math.sin(phase),
                phaseRad=phase,
                magnitude=magnitude,
            )
        )
    return AwrBinWindow(
        timestamp=timestamp,
        frameNumber=frame_number,
        startBin=20,
        numBins=41,
        bins=bins,
        strongestBin=37,
        strongestRangeMeters=37 * resolution,
        strongestMagnitude=2500.0,
    )


def fake_target(posture: str, frame_number: int) -> IwrTarget:
    return IwrTarget(
        timestamp=1000.0 + frame_number / 10.0,
        frameNumber=frame_number,
        targetId=1,
        x=0.0,
        y=1.75,
        z=0.0,
        rangeMeters=1.75,
        velocityX=0.0,
        velocityY=0.0,
        velocityZ=0.0,
        speed=0.0,
        posture=posture,
        postureConfidence=0.95,
        trackState="STABLE",
    )


def fake_selection(
    phase_rad: float,
    bin_index: int = 37,
    azimuth_deg: float = 10.0,
) -> BinSelection:
    return BinSelection(
        expectedAwrRangeMeters=1.75,
        expectedAwrBin=37,
        selectedAwrBin=bin_index,
        selectedAwrRangeMeters=1.7541,
        selectedPhaseRad=phase_rad,
        selectedMagnitude=2500.0,
        strongestOverallBin=37,
        strongestOverallRangeMeters=1.7541,
        strongestOverallMagnitude=2500.0,
        candidateBins=list(range(33, 42)),
        selectionReason="offline synthetic chest beam",
        selectedAwrAzimuthDeg=azimuth_deg,
        beamScore=0.95,
        phaseSegmentId=1,
    )


class DualSensorFusionTests(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine(
            FusionConfig(
                transform=TransformConfig(useIwrRangeDirect=True),
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(
                    requiredStableFrames=3,
                    sittingLockSec=0.0,
                ),
                estimator=VitalEstimatorConfig(
                    fs=10.0, requireLockedPhaseSegment=False
                ),
                useChestTargeting=False,
            )
        )

    def test_selects_strongest_bin_near_iwr_range(self):
        fused, selection = self.engine.process(
            fake_target("STANDING", 1), fake_window(1)
        )
        self.assertIsNotNone(selection)
        self.assertEqual(selection.expectedAwrBin, 37)
        self.assertEqual(selection.selectedAwrBin, 37)
        self.assertAlmostEqual(fused.selectedAwrRangeMeters, 1.7541, places=3)

    def test_standing_pauses_vitals(self):
        fused, _selection = self.engine.process(
            fake_target("STANDING", 1), fake_window(1)
        )
        self.assertEqual(fused.monitoringState, PAUSED_NOT_SITTING)
        self.assertFalse(fused.postureAllowedForVitals)
        self.assertEqual(self.engine.estimator.sample_count(1), 0)
        self.assertIsNone(fused.breathingBpm)
        self.assertIsNone(fused.heartBpm)

    def test_sitting_stability_starts_phase_updates(self):
        states = []
        for frame_number in range(1, 4):
            fused, _selection = self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
            states.append(fused.monitoringState)
        self.assertEqual(
            states,
            [WAITING_FOR_SITTING, WAITING_FOR_SITTING, MONITORING],
        )
        self.assertEqual(self.engine.estimator.sample_count(1), 1)
        self.assertTrue(fused.postureAllowedForVitals)

    def test_brief_standing_uses_pose_grace_after_monitoring(self):
        for frame_number in range(1, 4):
            self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        fused, _selection = self.engine.process(
            fake_target("STANDING", 4), fake_window(4)
        )
        self.assertEqual(fused.monitoringState, MONITORING_POSE_GRACE)
        self.assertTrue(fused.postureAllowedForVitals)
        self.assertEqual(self.engine.estimator.sample_count(1), 2)
        self.assertEqual(fused.quality, "MONITORING_POSE_GRACE")

    def test_pose_grace_returns_to_monitoring_without_buffer_reset(self):
        for frame_number in range(1, 4):
            self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        for frame_number in range(4, 14):
            fused, _ = self.engine.process(
                fake_target("MOVING", frame_number),
                fake_window(frame_number),
            )
            self.assertEqual(fused.monitoringState, MONITORING_POSE_GRACE)
        count_during_grace = self.engine.estimator.sample_count(1)
        fused, _ = self.engine.process(
            fake_target("SITTING", 14),
            fake_window(14),
        )
        self.assertEqual(fused.monitoringState, MONITORING)
        self.assertEqual(
            self.engine.estimator.sample_count(1),
            count_during_grace + 1,
        )

    def test_pose_grace_expires_after_three_seconds(self):
        for frame_number in range(1, 4):
            self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        for frame_number in range(4, 35):
            fused, _ = self.engine.process(
                fake_target("MOVING", frame_number),
                fake_window(frame_number),
            )
        self.assertEqual(fused.monitoringState, PAUSED_NOT_SITTING)
        self.assertFalse(fused.postureAllowedForVitals)
        self.assertEqual(self.engine.estimator.sample_count(1), 31)

    def test_falling_pauses_immediately(self):
        for frame_number in range(1, 4):
            self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        fused, _ = self.engine.process(
            fake_target("FALLING", 4),
            fake_window(4),
        )
        self.assertEqual(fused.monitoringState, PAUSED_NOT_SITTING)
        self.assertFalse(fused.postureAllowedForVitals)
        self.assertEqual(self.engine.estimator.sample_count(1), 1)

    def test_high_speed_bypasses_pose_grace(self):
        for frame_number in range(1, 4):
            self.engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        moving = fake_target("MOVING", 4)
        moving.speed = 0.30
        fused, _ = self.engine.process(moving, fake_window(4))
        self.assertEqual(fused.monitoringState, "POSTURE_UNSTABLE")
        self.assertFalse(fused.postureAllowedForVitals)
        self.assertIn("speed", fused.postureGateReason)

    def test_disable_pose_grace_restores_strict_behavior(self):
        engine = FusionEngine(
            FusionConfig(
                transform=TransformConfig(useIwrRangeDirect=True),
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(
                    requiredStableFrames=3,
                    sittingLockSec=0.0,
                    enablePoseGrace=False,
                ),
                estimator=VitalEstimatorConfig(
                    fs=10.0, requireLockedPhaseSegment=False
                ),
                useChestTargeting=False,
            )
        )
        for frame_number in range(1, 4):
            engine.process(
                fake_target("SITTING", frame_number),
                fake_window(frame_number),
            )
        fused, _ = engine.process(fake_target("MOVING", 4), fake_window(4))
        self.assertEqual(fused.monitoringState, "POSTURE_UNSTABLE")
        self.assertFalse(fused.postureAllowedForVitals)

    def test_seated_lock_is_active_and_tolerates_standing_flicker(self):
        engine = FusionEngine(
            FusionConfig(
                transform=TransformConfig(useIwrRangeDirect=True),
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(
                    requiredStableFrames=2,
                    sittingLockSec=1.0,
                    updateRateHz=10.0,
                ),
                estimator=VitalEstimatorConfig(
                    fs=10.0, requireLockedPhaseSegment=False
                ),
                useChestTargeting=False,
            )
        )
        first, _ = engine.process(fake_target("SITTING", 1), fake_window(1))
        locked, _ = engine.process(fake_target("SITTING", 2), fake_window(2))
        flicker, _ = engine.process(fake_target("STANDING", 3), fake_window(3))
        returned, _ = engine.process(fake_target("SITTING", 4), fake_window(4))

        self.assertEqual(first.monitoringState, WAITING_FOR_SITTING)
        self.assertEqual(locked.monitoringState, SEATED_LOCK)
        self.assertTrue(locked.postureAllowedForVitals)
        self.assertEqual(flicker.monitoringState, MONITORING_POSE_GRACE)
        self.assertTrue(flicker.postureAllowedForVitals)
        self.assertEqual(returned.monitoringState, SEATED_LOCK)
        self.assertEqual(engine.estimator.sample_count(1), 3)


class ReliabilityTests(unittest.TestCase):
    def test_fe03_liveness_retains_short_gap_then_expires(self):
        tracker = Fe03LivenessTracker(stale_timeout_sec=1.0)
        first = convert_awr_virtual_ant_window(
            make_fake_vital_phase_virtual_ant_window(frame_number=10),
            timestamp=100.0,
        )
        second = convert_awr_virtual_ant_window(
            make_fake_vital_phase_virtual_ant_window(frame_number=11),
            timestamp=100.1,
        )
        tracker.update(first, received_at=100.0)
        tracker.update(second, received_at=100.1)

        active, age, frame, fps = tracker.snapshot(now=100.8)
        self.assertIs(active, second)
        self.assertAlmostEqual(age, 0.7)
        self.assertEqual(frame, 11)
        self.assertAlmostEqual(fps, 10.0)

        stale, age, frame, _fps = tracker.snapshot(now=101.2)
        self.assertIsNone(stale)
        self.assertAlmostEqual(age, 1.1)
        self.assertEqual(frame, 11)

    def test_fe03_stream_state_is_independent_of_beam_lock(self):
        tracker = Fe03LivenessTracker(stale_timeout_sec=2.0)
        window = convert_awr_virtual_ant_window(
            make_fake_vital_phase_virtual_ant_window(frame_number=10),
            timestamp=100.0,
        )
        tracker.update(window, received_at=100.0)
        active = tracker.status(now=100.5)
        stale = tracker.status(now=101.5)
        lost = tracker.status(now=102.1)

        self.assertEqual(active.streamState, FE03_ACTIVE)
        self.assertIs(active.window, window)
        self.assertEqual(stale.streamState, FE03_STALE)
        self.assertIs(stale.window, window)
        self.assertEqual(lost.streamState, FE03_LOST)
        self.assertIsNone(lost.window)

    def test_fe03_lost_status_reports_fe02_fallback(self):
        engine = FusionEngine(FusionConfig())
        fused, selection = engine.process(
            fake_target("SITTING", 1),
            fake_window(),
            timestamp=1000.1,
            fe03_age_sec=1.2,
            latest_fe03_frame_number=11,
            fe03_frames_per_second=9.8,
            fe03_stream_state=FE03_LOST,
        )
        self.assertIsNotNone(selection)
        self.assertEqual(fused.fe03Status, FE03_LOST)
        self.assertEqual(fused.selectionMode, "RANGE_ONLY_CHEST_GUIDED")

    def test_vital_estimate_is_held_and_phase_spectrum_finds_breathing(self):
        bridge = VitalEstimatorBridge(
            VitalEstimatorConfig(
                fs=10.0,
                minEstimationWindowSec=2.0,
                minVitalWindowSec=2.0,
                minHeartWindowSec=2.0,
                bpmSmoothingSec=0.0,
                displayHoldSec=10.0,
            )
        )
        estimate = None
        for index in range(200):
            t = index / 10.0
            phase = 0.8 * math.sin(2.0 * math.pi * 0.25 * t)
            phase += 0.05 * math.sin(2.0 * math.pi * 1.2 * t)
            estimate = bridge.update(
                1,
                fake_selection(phase),
                MONITORING,
                timestamp=t,
                source_frame_number=index,
            )

        self.assertIsNotNone(estimate)
        self.assertIsNotNone(estimate.breathingBpm)
        diagnostics = bridge.diagnostics(1, timestamp=20.0)
        self.assertEqual(diagnostics.sampleCount, 200)
        self.assertAlmostEqual(diagnostics.breathPeakBpm, 15.0, delta=3.0)

        held = bridge.update(
            1,
            fake_selection(0.0),
            PAUSED_NOT_SITTING,
            timestamp=20.0,
        )
        self.assertTrue(held.held)
        self.assertEqual(held.breathingBpm, estimate.breathingBpm)

        expired = bridge.update(
            1,
            fake_selection(0.0),
            PAUSED_NOT_SITTING,
            timestamp=31.0,
        )
        self.assertFalse(expired.held)
        self.assertIsNone(expired.breathingBpm)

    def test_vital_estimator_ignores_phase_without_locked_segment(self):
        bridge = VitalEstimatorBridge(VitalEstimatorConfig(fs=10.0))
        selection = fake_selection(0.25)
        selection.phaseSegmentId = None

        estimate = bridge.update(
            1,
            selection,
            MONITORING,
            timestamp=0.0,
            source_frame_number=1,
        )

        self.assertEqual(estimate.quality, "HOLD")
        self.assertEqual(bridge.sample_count(1), 0)

    def test_thirty_seconds_produces_preliminary_breath_and_heart(self):
        bridge = VitalEstimatorBridge(
            VitalEstimatorConfig(
                fs=10.0,
                minEstimationWindowSec=30.0,
                minVitalWindowSec=30.0,
                minHeartWindowSec=30.0,
                breathStableWindowSec=30.0,
                heartStableWindowSec=60.0,
                bpmSmoothingSec=0.0,
            )
        )
        estimate = None
        for index in range(300):
            timestamp = index / 10.0
            phase = 0.9 * math.sin(2.0 * math.pi * 0.25 * timestamp)
            phase += 0.18 * math.sin(2.0 * math.pi * 1.2 * timestamp)
            estimate = bridge.update(
                1,
                fake_selection(phase),
                MONITORING,
                timestamp=timestamp,
                source_frame_number=index,
            )

        self.assertIsNotNone(estimate.breathingBpm)
        self.assertIsNotNone(estimate.heartBpm)
        self.assertEqual(estimate.breathEstimateState, "PRELIMINARY_30S")
        self.assertEqual(estimate.heartEstimateState, "PRELIMINARY_30S")
        self.assertAlmostEqual(estimate.breathingBpm, 15.0, delta=3.0)
        self.assertAlmostEqual(estimate.heartBpm, 72.0, delta=6.0)

    def test_less_than_thirty_seconds_remains_collecting(self):
        bridge = VitalEstimatorBridge(
            VitalEstimatorConfig(
                fs=10.0,
                minEstimationWindowSec=30.0,
                minVitalWindowSec=30.0,
                minHeartWindowSec=30.0,
            )
        )
        estimate = None
        for index in range(299):
            timestamp = index / 10.0
            phase = math.sin(2.0 * math.pi * 0.25 * timestamp)
            estimate = bridge.update(
                1,
                fake_selection(phase),
                MONITORING,
                timestamp=timestamp,
                source_frame_number=index,
            )

        self.assertIsNone(estimate.breathingBpm)
        self.assertIsNone(estimate.heartBpm)
        self.assertEqual(estimate.breathEstimateState, "COLLECTING")
        self.assertEqual(estimate.heartEstimateState, "COLLECTING")

    def test_rate_smoothing_rejects_low_confidence_impossible_jump(self):
        bridge = VitalEstimatorBridge(
            VitalEstimatorConfig(
                fs=10.0,
                bpmSmoothingSec=10.0,
                heartMaxJumpBpmPerSec=10.0,
            )
        )
        first, held = bridge._stabilize_value(
            1, 72.0, 0.8, "heart", timestamp=10.0
        )
        second, held_second = bridge._stabilize_value(
            1, 110.0, 0.2, "heart", timestamp=11.0
        )
        self.assertFalse(held)
        self.assertTrue(held_second)
        self.assertEqual(second, first)


class ChestTargetingTests(unittest.TestCase):
    def test_sitting_chest_point_uses_upper_torso_height(self):
        target = fake_target("SITTING", 1)
        target.groundZ = 0.10
        target.targetHeight = 1.20
        chest = estimate_chest_point(target)
        self.assertAlmostEqual(chest.iwrChestX, 0.0)
        self.assertAlmostEqual(chest.iwrChestY, 1.75)
        self.assertAlmostEqual(chest.iwrChestZ, 0.94)
        self.assertGreater(chest.confidence, 0.5)
        self.assertIn("box_height", chest.method)

    def test_iwr_to_awr_transform_subtracts_sensor_origin(self):
        point = transform_iwr_point_to_awr(
            0.20,
            2.00,
            1.00,
            TransformConfig(dx=0.20, dy=0.10, dz=0.25),
        )
        self.assertAlmostEqual(point[0], 0.0)
        self.assertAlmostEqual(point[1], 1.90)
        self.assertAlmostEqual(point[2], 0.75)

    def test_spatial_target_calculates_range_azimuth_elevation(self):
        target = fake_target("SITTING", 1)
        target.x = 1.0
        target.y = 1.0
        target.groundZ = 0.0
        chest = estimate_chest_point(
            target,
            ChestEstimatorConfig(sittingChestHeightM=1.0),
        )
        spatial = compute_awr_spatial_target(
            chest,
            TransformConfig(),
            rangeResolution=0.05,
        )
        self.assertAlmostEqual(spatial.rangeMeters, math.sqrt(3.0))
        self.assertAlmostEqual(spatial.azimuthDeg, 45.0)
        self.assertAlmostEqual(
            spatial.elevationDeg,
            math.degrees(math.atan2(1.0, math.sqrt(2.0))),
        )
        self.assertEqual(spatial.expectedRangeBin, 35)

    def test_chest_height_mode_uses_horizontal_range_and_ignores_elevation(self):
        target = fake_target("SITTING", 1)
        target.x = 0.50
        target.y = 2.00
        target.z = 1.60
        target.groundZ = 0.0
        chest = estimate_chest_point(
            target,
            ChestEstimatorConfig(sittingChestHeightM=0.85),
        )
        config = TransformConfig(
            dx=0.10,
            dy=0.20,
            dz=-0.75,
            pitchDeg=25.0,
            rollDeg=-10.0,
            useIwrRangeDirect=True,
            awrChestHeightMode=True,
        )
        spatial = compute_awr_spatial_target(chest, config, 0.05)
        expected_horizontal = math.hypot(0.40, 1.80)

        self.assertAlmostEqual(spatial.rangeMeters, expected_horizontal)
        self.assertAlmostEqual(
            spatial.azimuthDeg,
            math.degrees(math.atan2(0.40, 1.80)),
        )
        self.assertTrue(spatial.chestHeightMode)
        self.assertIsNotNone(spatial.ignoredIwrElevationDeg)
        self.assertAlmostEqual(expected_awr_range(target, config), expected_horizontal)

    def test_chest_guided_selection_is_explicit_and_legacy_remains_available(self):
        chest_engine = FusionEngine(
            FusionConfig(
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(requiredStableFrames=1),
                chest=ChestEstimatorConfig(sittingChestHeightM=0.85),
                useChestTargeting=True,
            )
        )
        fused, selection = chest_engine.process(
            fake_target("SITTING", 1),
            fake_window(1),
        )
        self.assertIsNotNone(selection)
        self.assertEqual(fused.selectionMode, "RANGE_ONLY_CHEST_GUIDED")
        self.assertIsNotNone(fused.expectedAwrAzimuthDeg)
        self.assertIsNotNone(fused.expectedAwrElevationDeg)
        self.assertIn("not AWR beamforming", fused.spatialWarning)

        legacy_engine = FusionEngine(
            FusionConfig(
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(requiredStableFrames=1),
                useChestTargeting=False,
            )
        )
        legacy, legacy_selection = legacy_engine.process(
            fake_target("SITTING", 1),
            fake_window(1),
        )
        self.assertEqual(legacy.selectionMode, "RANGE_ONLY_TARGET_CENTER")
        self.assertEqual(legacy_selection.expectedAwrBin, 37)

    def test_fe03_selects_chest_guided_range_and_azimuth(self):
        target = fake_target("SITTING", 1)
        target.x = 0.50
        target.y = 1.50
        target.rangeMeters = math.hypot(target.x, target.y)
        chest = estimate_chest_point(
            target,
            ChestEstimatorConfig(sittingChestHeightM=0.85),
        )
        spatial = compute_awr_spatial_target(chest, TransformConfig())
        range_resolution = 0.04739
        source_bin = int(round(spatial.rangeMeters / range_resolution))
        raw_window = make_fake_vital_phase_virtual_ant_window(
            frame_number=1,
            source_bin=source_bin,
            source_azimuth_deg=spatial.azimuthDeg,
            range_resolution=range_resolution,
        )
        virtual_window = convert_awr_virtual_ant_window(
            raw_window,
            timestamp=target.timestamp,
        )
        engine = FusionEngine(
            FusionConfig(
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(requiredStableFrames=1),
                chest=ChestEstimatorConfig(sittingChestHeightM=0.85),
                useChestTargeting=True,
                beamforming=BeamformingConfig(angleStepDeg=2.0),
                azimuthSearchHalfWidthDeg=15.0,
                beamLock=BeamLockConfig(enabled=False),
            )
        )

        fused, selection = engine.process(
            target,
            fake_window(1),
            timestamp=target.timestamp,
            awr_virtual_ant_window=virtual_window,
        )

        self.assertIsNotNone(selection)
        self.assertEqual(fused.selectionMode, "RANGE_AZIMUTH_CHEST_GUIDED")
        self.assertEqual(selection.selectedAwrBin, source_bin)
        self.assertAlmostEqual(
            fused.selectedAwrAzimuthDeg,
            spatial.azimuthDeg,
            delta=2.0,
        )
        self.assertEqual(fused.numVirtualAntennas, 8)
        self.assertEqual(fused.fe03Status, FE03_ACTIVE)
        self.assertIsNotNone(fused.selectedBeamPhaseRad)

    def test_fe02_fallback_remains_when_fe03_is_missing(self):
        engine = FusionEngine(
            FusionConfig(
                selector=SelectorConfig(searchHalfWidth=4),
                gate=SittingGateConfig(requiredStableFrames=1),
                chest=ChestEstimatorConfig(sittingChestHeightM=0.85),
                useChestTargeting=True,
            )
        )
        fused, selection = engine.process(
            fake_target("SITTING", 1),
            fake_window(1),
        )

        self.assertIsNotNone(selection)
        self.assertEqual(fused.selectionMode, "RANGE_ONLY_CHEST_GUIDED")
        self.assertEqual(fused.fe03Status, FE03_LOST)
        self.assertIsNone(fused.selectedAwrAzimuthDeg)

    def test_seated_monitoring_stays_active_while_beam_is_searching(self):
        target = fake_target("SITTING", 1)
        virtual_window = convert_awr_virtual_ant_window(
            make_fake_vital_phase_virtual_ant_window(
                frame_number=1,
                source_bin=37,
                source_azimuth_deg=0.0,
            ),
            timestamp=target.timestamp,
        )
        engine = FusionEngine(
            FusionConfig(
                gate=SittingGateConfig(
                    requiredStableFrames=1,
                    sittingLockSec=5.0,
                ),
                beamLock=BeamLockConfig(lockSec=2.0),
            )
        )

        fused, selection = engine.process(
            target,
            None,
            timestamp=target.timestamp,
            awr_virtual_ant_window=virtual_window,
        )

        self.assertIsNotNone(selection)
        self.assertEqual(fused.beamState, BEAM_CANDIDATE)
        self.assertIn(fused.monitoringState, {MONITORING, SEATED_LOCK})
        self.assertTrue(fused.postureAllowedForVitals)
        self.assertIsNone(fused.lockedRangeBin)

    def test_beam_lock_rejects_one_frame_spike_and_segments_switches(self):
        config = BeamformingConfig(angleStepDeg=2.0)
        lock = BeamLockManager(
            BeamLockConfig(
                lockSec=1.0,
                holdSec=3.0,
                switchMargin=1.2,
                switchConfirmSec=1.0,
                maxJumpBins=1,
                maxJumpDeg=4.0,
            )
        )

        def candidate(frame, source_bin, source_azimuth):
            window = convert_awr_virtual_ant_window(
                make_fake_vital_phase_virtual_ant_window(
                    frame_number=frame,
                    source_bin=source_bin,
                    source_azimuth_deg=source_azimuth,
                ),
                timestamp=float(frame),
            )
            selection = select_range_azimuth_cell(
                window,
                source_bin * window.rangeResolution,
                source_azimuth,
                4,
                20.0,
                None,
                config,
            )
            return window, selection

        window, stable = candidate(1, 37, 0.0)
        first = lock.update(1, stable, window, timestamp=0.0)
        locked = lock.update(1, stable, window, timestamp=1.1)
        spike_window, spike = candidate(2, 40, 14.0)
        held = lock.update(1, spike, spike_window, timestamp=1.2)

        self.assertEqual(first.state, BEAM_CANDIDATE)
        self.assertEqual(locked.state, BEAM_LOCKED)
        self.assertEqual(held.state, BEAM_HOLD)
        self.assertEqual(held.locked.selectedRangeBin, 37)
        self.assertEqual(held.switchCount, 0)

        phase = LockedPhaseTracker(77.0)
        segment_one = phase.update(1, 3.0, locked.segmentId)
        continued = phase.update(1, -3.0, locked.segmentId)
        segment_two = phase.update(1, 1.0, locked.segmentId + 1)
        self.assertGreater(continued.unwrappedPhaseRad, segment_one.unwrappedPhaseRad)
        self.assertEqual(segment_two.relativePhaseRad, 0.0)
        self.assertEqual(segment_two.segmentId, segment_one.segmentId + 1)

    def test_locked_phase_tracker_preserves_smooth_sinusoidal_displacement(self):
        tracker = LockedPhaseTracker(77.0)
        phases = 0.25 * np.sin(
            2.0 * np.pi * 0.25 * np.arange(100, dtype=np.float64) / 10.0
        )
        samples = [tracker.update(1, float(value), 1) for value in phases]
        displacement = np.asarray(
            [sample.displacementMm for sample in samples], dtype=np.float64
        )

        self.assertTrue(np.isfinite(displacement).all())
        self.assertEqual(samples[0].relativePhaseRad, 0.0)
        self.assertLess(np.max(np.abs(np.diff(displacement))), 0.1)


class FusionUiHumanModelTests(unittest.TestCase):
    def test_pose_grace_cli_defaults_and_disable_flag(self):
        defaults = build_arg_parser().parse_args([])
        strict = build_arg_parser().parse_args(["--disable-pose-grace"])

        self.assertEqual(defaults.non_sitting_grace_sec, 3.0)
        self.assertAlmostEqual(defaults.max_grace_speed_mps, 0.25)
        self.assertEqual(defaults.sitting_lock_sec, 5.0)
        self.assertEqual(defaults.fe03_stale_timeout_sec, 2.0)
        self.assertEqual(defaults.vital_display_hold_sec, 10.0)
        self.assertEqual(defaults.min_vital_window_sec, 30.0)
        self.assertEqual(defaults.min_heart_window_sec, 30.0)
        self.assertTrue(defaults.pose_grace_enabled)
        self.assertTrue(defaults.allow_standing_grace)
        self.assertTrue(defaults.awr_chest_height_mode)
        self.assertEqual(defaults.ui_layout, "full")
        self.assertEqual(defaults.beam_lock_sec, 2.0)
        self.assertEqual(defaults.beam_hold_sec, 3.0)
        self.assertFalse(strict.pose_grace_enabled)

    def test_human_models_and_ground_plane_are_enabled_by_default(self):
        args = build_arg_parser().parse_args([])
        ti_args = _make_ti_args(args)

        self.assertTrue(args.pose_human_models)
        self.assertTrue(args.pose_ground_plane)
        self.assertTrue(ti_args.pose_human_models)
        self.assertTrue(ti_args.pose_ground_plane)
        self.assertEqual(
            Path(ti_args.pose_human_model_dir).resolve(),
            DEFAULT_HUMAN_MODEL_DIR.resolve(),
        )
        self.assertEqual(ti_args.pose_human_model_mode, "overlay_box")

    def test_human_models_and_ground_plane_can_be_disabled(self):
        args = build_arg_parser().parse_args(
            [
                "--no-pose-human-models",
                "--no-pose-ground-plane",
                "--no-pose-ground-plane-grid",
            ]
        )
        ti_args = _make_ti_args(args)

        self.assertFalse(ti_args.pose_human_models)
        self.assertFalse(ti_args.pose_ground_plane)
        self.assertFalse(ti_args.pose_ground_plane_grid)

    def test_demo_pose_manager_generates_posture_specific_model_records(self):
        args = build_arg_parser().parse_args([])
        manager = DemoPoseManager(_make_ti_args(args))

        expected_assets = {
            0.0: "human_standing.obj",
            4.0: "human_standing.obj",
            8.0: "human_sitting.obj",
            12.0: "human_lying.obj",
            16.0: "human_lying.obj",
        }
        for elapsed, asset in expected_assets.items():
            output = _make_demo_iwr_output(1, elapsed)
            manager.process_output_dict(output)
            records = manager.get_3d_model_records(output["trackData"])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["model_asset_used"], asset)
            self.assertEqual(records[0]["tid"], 1)

    def test_mesh_bounds_share_target_center_and_ground(self):
        vertices = np.array(
            [
                [-0.25, -0.10, 0.0],
                [0.25, 0.10, 1.0],
                [0.0, 0.0, 0.5],
            ],
            dtype=np.float32,
        )
        mesh = ObjMesh(
            name="test",
            vertices=vertices,
            faces=np.array([[0, 1, 2]], dtype=np.int32),
            bounds_min=vertices.min(axis=0),
            bounds_max=vertices.max(axis=0),
            size=vertices.max(axis=0) - vertices.min(axis=0),
            width=0.5,
            depth=0.2,
            height=1.0,
            horizontal_length=0.5,
        )

        bounds = _mesh_world_bounds(
            mesh, scale=2.0, x=1.0, y=2.0, ground_z=0.15, padding=0.0
        )

        for actual, expected in zip(bounds, (0.5, 1.8, 0.15, 1.5, 2.2, 2.15)):
            self.assertAlmostEqual(actual, expected, places=6)


if __name__ == "__main__":
    unittest.main()
