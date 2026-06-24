from __future__ import annotations

from dataclasses import dataclass
import math

from .fusion_types import ChestPointEstimate, IwrTarget


@dataclass(frozen=True)
class ChestEstimatorConfig:
    """Posture-aware chest geometry in the IWR coordinate frame.

    IWR coordinates are x=lateral, y=forward, z=up. Offsets are applied in
    those axes; they do not rotate with target heading because the tracker does
    not currently provide a reliable torso orientation.
    """

    sittingChestHeightM: float = 0.85
    standingChestHeightM: float = 1.35
    lyingChestHeightM: float = 0.35
    chestForwardOffsetM: float = 0.0
    chestLateralOffsetM: float = 0.0
    groundZ: float = 0.0
    minConfidenceForVitals: float = 0.5


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def _posture_height(
    posture: str,
    target_height: float | None,
    config: ChestEstimatorConfig,
) -> tuple[float, str]:
    if posture == "SITTING":
        if _finite(target_height) and float(target_height) > 0.0:
            return min(0.85, max(0.65, 0.70 * float(target_height))), "box_height"
        return config.sittingChestHeightM, "configured_height"
    if posture in {"LYING", "FALLING"}:
        if _finite(target_height) and float(target_height) > 0.0:
            return min(0.45, max(0.25, 0.50 * float(target_height))), "box_height"
        return config.lyingChestHeightM, "configured_height"

    # MOVING and UNKNOWN use the upright geometry because posture gating still
    # prevents their samples from entering the vital estimator.
    if _finite(target_height) and float(target_height) > 0.0:
        return min(1.40, max(1.20, 0.78 * float(target_height))), "box_height"
    return config.standingChestHeightM, "configured_height"


def estimate_chest_point(
    target: IwrTarget,
    config: ChestEstimatorConfig | None = None,
) -> ChestPointEstimate:
    config = config or ChestEstimatorConfig()
    posture = str(target.posture or "UNKNOWN").upper()
    ground_z = float(target.groundZ) if _finite(target.groundZ) else config.groundZ
    chest_height, height_method = _posture_height(
        posture,
        target.targetHeight,
        config,
    )

    confidence = (
        float(target.postureConfidence)
        if _finite(target.postureConfidence)
        else 0.65
    )
    confidence = min(1.0, max(0.0, confidence))
    notes: list[str] = []
    if height_method == "configured_height":
        confidence *= 0.90
        notes.append("target height unavailable; used configured posture height")
    if not _finite(target.groundZ):
        confidence *= 0.90
        notes.append("ground unavailable; used configured groundZ")
    if posture == "UNKNOWN":
        confidence *= 0.70
        notes.append("unknown posture uses upright fallback geometry")

    return ChestPointEstimate(
        timestamp=target.timestamp,
        targetId=target.targetId,
        sourceFrameNumber=target.frameNumber,
        posture=posture,
        iwrChestX=float(target.x) + config.chestLateralOffsetM,
        iwrChestY=float(target.y) + config.chestForwardOffsetM,
        iwrChestZ=ground_z + chest_height,
        confidence=confidence,
        method=f"posture_{posture.lower()}_{height_method}",
        notes="; ".join(notes),
    )
