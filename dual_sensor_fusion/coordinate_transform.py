from __future__ import annotations

from dataclasses import dataclass
import math

from .fusion_types import AwrSpatialTarget, ChestPointEstimate, IwrTarget


@dataclass(frozen=True)
class TransformConfig:
    """Rigid transform from IWR coordinates to AWR coordinates.

    Both frames use x=lateral/right, y=forward/boresight, z=up. ``dx/dy/dz``
    locate the AWR origin in the IWR frame. Yaw/pitch/roll describe the AWR
    frame orientation relative to IWR; point conversion applies the inverse
    rotation after subtracting that translation.
    """

    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    yawOffsetDeg: float = 0.0
    yawDeg: float | None = None
    pitchDeg: float = 0.0
    rollDeg: float = 0.0
    useIwrRangeDirect: bool = True
    awrChestHeightMode: bool = False


def _rotation_awr_to_iwr(config: TransformConfig) -> tuple[tuple[float, ...], ...]:
    yaw = math.radians(
        config.yawOffsetDeg if config.yawDeg is None else config.yawDeg
    )
    pitch = math.radians(config.pitchDeg)
    roll = math.radians(config.rollDeg)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)

    # Rz(yaw) * Ry(pitch) * Rx(roll)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def transform_iwr_point_to_awr(
    iwrX: float,
    iwrY: float,
    iwrZ: float,
    config: TransformConfig,
) -> tuple[float, float, float]:
    translated = (
        float(iwrX) - config.dx,
        float(iwrY) - config.dy,
        float(iwrZ) - config.dz,
    )
    rotation = _rotation_awr_to_iwr(config)
    # p_awr = R^T * (p_iwr - t)
    return tuple(
        sum(rotation[row][column] * translated[row] for row in range(3))
        for column in range(3)
    )


def _transform_iwr_xy_to_awr_chest_height(
    iwrX: float,
    iwrY: float,
    iwrZ: float,
    config: TransformConfig,
) -> tuple[float, float, float]:
    """Apply only planar translation/yaw for chest-height AWR targeting.

    AWR elevation is mechanically constrained in this mode. Pitch, roll, and
    the target's vertical coordinate must not leak into range/azimuth beam
    selection. The returned z value is retained only as display metadata.
    """
    translated_x = float(iwrX) - config.dx
    translated_y = float(iwrY) - config.dy
    yaw = math.radians(
        config.yawOffsetDeg if config.yawDeg is None else config.yawDeg
    )
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return (
        cosine * translated_x + sine * translated_y,
        -sine * translated_x + cosine * translated_y,
        float(iwrZ) - config.dz,
    )


def compute_awr_spatial_target(
    chestPoint: ChestPointEstimate,
    transformConfig: TransformConfig,
    rangeResolution: float | None = None,
) -> AwrSpatialTarget:
    transform = (
        _transform_iwr_xy_to_awr_chest_height
        if transformConfig.awrChestHeightMode
        else transform_iwr_point_to_awr
    )
    awr_x, awr_y, awr_z = transform(
        chestPoint.iwrChestX,
        chestPoint.iwrChestY,
        chestPoint.iwrChestZ,
        transformConfig,
    )
    horizontal_range = math.hypot(awr_x, awr_y)
    slant_range = math.hypot(horizontal_range, awr_z)
    range_m = horizontal_range if transformConfig.awrChestHeightMode else slant_range
    elevation_deg = math.degrees(math.atan2(awr_z, horizontal_range))
    expected_range_bin = None
    if (
        rangeResolution is not None
        and math.isfinite(rangeResolution)
        and rangeResolution > 0.0
    ):
        expected_range_bin = int(round(range_m / rangeResolution))
    return AwrSpatialTarget(
        timestamp=chestPoint.timestamp,
        targetId=chestPoint.targetId,
        awrX=awr_x,
        awrY=awr_y,
        awrZ=awr_z,
        rangeMeters=range_m,
        horizontalRangeMeters=horizontal_range,
        azimuthDeg=math.degrees(math.atan2(awr_x, awr_y)),
        elevationDeg=elevation_deg,
        expectedRangeBin=expected_range_bin,
        confidence=chestPoint.confidence,
        chestHeightMode=transformConfig.awrChestHeightMode,
        ignoredIwrElevationDeg=(
            elevation_deg if transformConfig.awrChestHeightMode else None
        ),
    )


def expected_awr_range(target: IwrTarget, config: TransformConfig) -> float:
    """Estimate target range from the AWR sensor origin.

    The first physical setup assumes both sensors are side by side, at nearly
    the same height, aimed in the same direction, and close enough that direct
    IWR range is a useful initial calibration.
    """
    if config.awrChestHeightMode:
        awr_x, awr_y, _awr_z = _transform_iwr_xy_to_awr_chest_height(
            target.x,
            target.y,
            target.z,
            config,
        )
        return math.hypot(awr_x, awr_y)

    if (
        config.useIwrRangeDirect
        and target.rangeMeters is not None
        and math.isfinite(target.rangeMeters)
        and target.rangeMeters >= 0.0
    ):
        return float(target.rangeMeters)

    awr_x, awr_y, awr_z = transform_iwr_point_to_awr(
        target.x,
        target.y,
        target.z,
        config,
    )
    return math.sqrt(awr_x * awr_x + awr_y * awr_y + awr_z * awr_z)
