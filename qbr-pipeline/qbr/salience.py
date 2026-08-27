"""Rank flagged anomalies by how much they matter, not by how unusual they are.

The brief asks for "anomalies worth discussing with the customer". Those are two
different tests and conflating them is the most common way a QBR tool becomes
noise. A z-score answers "is this unusual". It cannot answer "does anyone care",
because it has no idea whether the metric moves money.

Concretely: in this dataset a notification volume spike and a coupon redemption
collapse are both statistically significant. One is worth ninety seconds of a
quarterly review and the other is worth nothing. The difference is not in the
statistics, so it cannot be recovered from them.

This module holds the business judgement, deliberately outside the warehouse, so
it can be retuned without a rebuild and read without SQL.
"""

from __future__ import annotations

from typing import Any

# Weight per metric. This encodes what a CSM conversation is actually about.
# A discount collapse is a revenue conversation; a notification count is not.
METRIC_WEIGHT = {
    "redemption_rate": 1.00,
    "discount_value": 0.90,
    "server_error_rate": 0.95,
    "sessions_evaluated": 0.85,
    "net_points_outstanding": 0.70,
    "effects_fired": 0.45,
}

# Multipliers applied on top of the base weight.
PAID_FEATURE_BOOST = 1.35      # movement on something they pay for
REVENUE_BOOST = 1.20           # movement that touches money
DETERIORATION_BOOST = 1.25     # things getting worse beat things getting better

# Below this, a movement is not worth a slide however unusual it is.
SALIENCE_FLOOR = 0.15

DEFAULT_TOP_N = 5


def _f(row: dict, key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_deterioration(row: dict) -> bool:
    """Is this movement bad news? Direction alone does not tell you."""
    metric = row.get("metric_name")
    increased = bool(row.get("is_increase"))

    # More errors is bad; more sessions is good. More outstanding loyalty
    # liability is bad. A falling redemption rate is bad.
    if metric in ("server_error_rate", "net_points_outstanding"):
        return increased
    if metric in ("redemption_rate", "discount_value", "sessions_evaluated", "effects_fired"):
        return not increased
    return False


def score_row(row: dict) -> dict[str, Any]:
    """Attach a salience score and the reasoning behind it.

    Movement is measured as relative change against the metric's own baseline,
    not as absolute magnitude. Absolute magnitude cannot be compared across
    metrics because the units are not commensurable: a discount is denominated
    in euros and an error rate in failed requests, so ranking them against a
    shared ceiling silently decides that 319 euros outranks a thirty-sevenfold
    increase in customer-visible errors. Relative change is unit-free, which is
    the only basis on which these are comparable at all.
    """
    metric = row.get("metric_name", "")
    base = METRIC_WEIGHT.get(metric, 0.35)

    # The engine's own view of what an effect type is worth, from
    # dim_effect_type. Only meaningful when the thing that moved *is* an effect
    # type; applying it to a campaign or an application would double-count
    # against METRIC_WEIGHT above. This is what demotes a notification spike.
    value_weight = (
        _f(row, "value_weight", 0.5)
        if row.get("entity_type") == "effect_type"
        else 1.0
    )

    # Relative change, saturating rather than capped. A hard cap makes a
    # thirty-sevenfold spike and a not-quite-double one score identically, which
    # loses the distinction that matters most. x/(x+1) keeps the ordering strict
    # while flattening the top end, so "much worse" still beats "worse" without
    # a 37x movement dominating everything else by 37x.
    rel = abs(_f(row, "relative_change"))
    relative_move = rel / (rel + 1.0)

    # A rate computed over forty attempts is noise wearing a z-score. Damp
    # movements on thin volume rather than trusting them equally.
    volume_confidence = min(1.0, _f(row, "volume") / 200.0) if _f(row, "volume") else 0.4

    score = base * value_weight * relative_move * volume_confidence
    reasons = []

    if row.get("is_paid_feature"):
        score *= PAID_FEATURE_BOOST
        reasons.append("sits behind a paid entitlement")
    if row.get("affects_revenue"):
        score *= REVENUE_BOOST
    deteriorating = _is_deterioration(row)
    if deteriorating:
        score *= DETERIORATION_BOOST
        reasons.append("moving in the wrong direction")

    if metric == "server_error_rate":
        reasons.append("customer-visible reliability")
    if value_weight < 0.2:
        reasons.append("low commercial value, demoted")
    if volume_confidence < 1.0:
        reasons.append("thin volume, damped")

    return {
        **row,
        "salience": round(score, 4),
        "salience_reasons": reasons,
        "is_deterioration": deteriorating,
    }


def rank(rows: list[dict], top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """Rank candidates and return both what surfaced and what was suppressed.

    The suppressed list is not decoration. Being able to show a reviewer the
    statistically significant movement the system deliberately dropped, and why,
    is the argument that the ranking is doing real work.
    """
    if not rows:
        return {"ranked": [], "suppressed": [], "candidate_count": 0}

    scored = [score_row(r) for r in rows]
    scored.sort(key=lambda r: r["salience"], reverse=True)

    above_floor = [r for r in scored if r["salience"] >= SALIENCE_FLOOR]
    ranked = above_floor[:top_n]
    ranked_ids = {id(r) for r in ranked}

    # Report the highest-z movements that did not make the cut, since those are
    # the ones a naive z-score-ordered system would have led with.
    by_z = sorted(scored, key=lambda r: abs(_f(r, "z_score")), reverse=True)
    suppressed = [r for r in by_z if id(r) not in ranked_ids][:5]

    return {
        "ranked": ranked,
        "suppressed": suppressed,
        "candidate_count": len(rows),
        "salience_floor": SALIENCE_FLOOR,
    }
