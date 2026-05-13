"""P1 — Non-linear progress value curve validation (committed via progress_rule_spec)."""
from __future__ import annotations

from typing import Any


def max_allowed_claimed_value_percent(progress_percent: float, spec: dict[str, Any] | None) -> float:
    """
    Returns the maximum allowed economic (claimed) value % for a given execution progress %.

    spec shapes (JSON object stored alongside progress_rule_hash):
      - null / {} / {"type":"linear"} → claimed must not exceed progress (classic linear cap).
      - {"type":"piecewise","points":[[p1,v1],[p2,v2],...]} with ascending p — piecewise-linear ceiling.
    """
    if not spec or spec.get("type") in (None, "linear"):
        return float(progress_percent)

    if spec.get("type") != "piecewise":
        raise ValueError("unsupported progress_rule_spec.type")

    raw_points = spec.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise ValueError("piecewise progress_rule_spec requires points: list of [progress, value] pairs")

    points: list[tuple[float, float]] = []
    for item in raw_points:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("each piecewise point must be [progress_percent, value_percent]")
        points.append((float(item[0]), float(item[1])))

    points.sort(key=lambda t: t[0])
    if points[0][0] > 1e-9 or points[-1][0] < 100.0 - 1e-9:
        raise ValueError("piecewise points must cover 0..100 on progress axis")
    pp = max(0.0, min(100.0, float(progress_percent)))
    for i in range(len(points) - 1):
        p0, v0 = points[i]
        p1, v1 = points[i + 1]
        if p0 <= pp <= p1 or (i == len(points) - 2 and abs(pp - p1) < 1e-9):
            if abs(p1 - p0) < 1e-12:
                return max(v0, v1)
            t = (pp - p0) / (p1 - p0)
            return v0 + t * (v1 - v0)
    return points[-1][1]


def validate_claimed_against_curve(
    *,
    progress_percent: float,
    claimed_value_percent: float,
    spec: dict[str, Any] | None,
) -> None:
    ceiling = max_allowed_claimed_value_percent(progress_percent, spec)
    if claimed_value_percent - 1e-6 > ceiling:
        raise ValueError(
            f"claimed_value_percent {claimed_value_percent} exceeds curve ceiling {ceiling:.4f} "
            f"at progress_percent {progress_percent}"
        )
