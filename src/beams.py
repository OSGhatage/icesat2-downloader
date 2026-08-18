"""Beam selection. Strong/weak is orientation-dependent — do not hide that."""

from __future__ import annotations

from src.config import ALL_BEAMS, LEFT_BEAMS, RIGHT_BEAMS


def resolve_beams(mode: str, custom: list[str] | None = None) -> list[str]:
    if mode == "custom" and custom:
        chosen = [b for b in ALL_BEAMS if b in custom]
        return chosen or list(ALL_BEAMS)
    if mode == "left":
        return list(LEFT_BEAMS)
    if mode == "right":
        return list(RIGHT_BEAMS)
    return list(ALL_BEAMS)


def confidence_api_values(min_confidence: int) -> list[str] | None:
    """Map ATL03 slider to OpenAltimetry photonConfidence names.

    None means 'do not send the parameter' (all photons).
    """
    if min_confidence <= -2:
        return None
    table = [
        (0, "noise"),
        (1, "buffer"),
        (2, "low"),
        (3, "medium"),
        (4, "high"),
    ]
    return [name for code, name in table if code >= min_confidence]
