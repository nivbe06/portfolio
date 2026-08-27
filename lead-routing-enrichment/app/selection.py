"""Provider selection = the anti-fire-all cost lever.

Call a provider only if it is primary for at least one needed-and-missing field.
Providers specialise (disjoint coverage), so skipping irrelevant ones is free saving."""
from __future__ import annotations

from . import fields as F


def primary_plan(missing_fields: list[str]) -> dict[str, list[str]]:
    """Map each provider we must call -> the fields we want from it (primary only).
    A provider with no needed-missing field never appears, so it is never called."""
    plan: dict[str, list[str]] = {}
    for fld in missing_fields:
        providers = F.FIELD_REGISTRY[fld]["providers"]
        if not providers:
            continue
        primary = providers[0]
        plan.setdefault(primary, []).append(fld)
    return plan


def fallbacks_for(field: str, already_tried: list[str]) -> list[str]:
    """Ordered fallback providers for a field that failed Gate B."""
    return [p for p in F.FIELD_REGISTRY[field]["providers"] if p not in already_tried]
