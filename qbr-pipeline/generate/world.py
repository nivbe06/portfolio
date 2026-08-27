"""The fictional world the mock logs describe.

Everything here is deliberate. Uniform random data makes a demo worthless, so
this module fixes the cast (tenants, applications, campaigns) and plants a set
of discoverable stories that the pipeline is supposed to surface. Each planted
story is documented in SIGNALS.md and carries an id (S1..S6) used in comments
below, so a reviewer can trace a claim in the QBR back to the line that made it
true.

Domain vocabulary follows Talon.One: a customer session is a cart evaluation, a
campaign owns rulesets, a ruleset fires effects, effects are what the engine
returns to the integration.
"""

from __future__ import annotations

import datetime as dt

# --------------------------------------------------------------------------
# Reporting window
# --------------------------------------------------------------------------
# Six full quarters. The default QBR compares 2026-Q2 against 2026-Q1, both of
# which are complete and in the past, so no record is dated in the future.
START = dt.date(2025, 1, 1)
END = dt.date(2026, 6, 30)

QBR_QUARTER = "2026-Q2"
QBR_PRIOR_QUARTER = "2026-Q1"


def quarter_of(d: dt.date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


# --------------------------------------------------------------------------
# Tenants
# --------------------------------------------------------------------------
# plan_tier is the account-level segmentation axis (used to compare accounts).
# Shopper-level segmentation is a separate axis, see PROFILE_SEGMENTS.
#
# acme-commerce.com and fastcart.io are carried over from task 1's provider
# seeds, so both take-home tasks describe one coherent fictional world.
TENANTS = [
    {
        "tenant": "acme-commerce",
        "name": "Acme Commerce",
        "domain": "acme-commerce.com",
        "plan_tier": "Enterprise",
        "country": "DE",
        "currency": "EUR",
        "weight": 0.42,
        # S5 counterpart: acme uses loyalty heavily, see S6.
        "entitlements": ["campaigns", "coupons", "loyalty", "referrals"],
    },
    {
        "tenant": "nordwind-retail",
        "name": "Nordwind Retail",
        "domain": "nordwind-retail.de",
        "plan_tier": "Enterprise",
        "country": "DE",
        "currency": "EUR",
        "weight": 0.30,
        # S5: entitled to loyalty, never fires a single loyalty event.
        "entitlements": ["campaigns", "coupons", "loyalty"],
    },
    {
        "tenant": "fastcart",
        "name": "FastCart",
        "domain": "fastcart.io",
        "plan_tier": "Mid-Market",
        "country": "US",
        "currency": "USD",
        "weight": 0.18,
        "entitlements": ["campaigns", "coupons", "loyalty"],
    },
    {
        "tenant": "brightline-grocers",
        "name": "Brightline Grocers",
        "domain": "brightline-grocers.co.uk",
        "plan_tier": "Mid-Market",
        "country": "GB",
        "currency": "GBP",
        "weight": 0.10,
        # S5 variant: entitled to referrals, never used.
        "entitlements": ["campaigns", "coupons", "referrals"],
    },
]

TENANTS_BY_ID = {t["tenant"]: t for t in TENANTS}

# --------------------------------------------------------------------------
# Applications (a tenant's integration points)
# --------------------------------------------------------------------------
APPLICATIONS = []
for _t in TENANTS:
    for _channel in ("web", "mobile"):
        APPLICATIONS.append(
            {
                "application_id": f"{_t['tenant']}-{_channel}",
                "tenant": _t["tenant"],
                "channel": _channel,
                "name": f"{_t['name']} {_channel.capitalize()}",
            }
        )

APPS_BY_TENANT: dict[str, list[dict]] = {}
for _a in APPLICATIONS:
    APPS_BY_TENANT.setdefault(_a["tenant"], []).append(_a)

# --------------------------------------------------------------------------
# Shopper segments (the second segmentation axis)
# --------------------------------------------------------------------------
PROFILE_SEGMENTS = ["new", "returning", "vip"]
PROFILE_SEGMENT_MIX = [0.34, 0.50, 0.16]

# --------------------------------------------------------------------------
# Effect types
# --------------------------------------------------------------------------
# `value_weight` drives the salience ranker: an effect that moves money is
# material, a notification is not. S4 depends on showNotification being cheap.
EFFECT_TYPES = {
    "setDiscount": {"monetary": True, "value_weight": 1.0},
    "acceptCoupon": {"monetary": True, "value_weight": 0.9},
    "rejectCoupon": {"monetary": False, "value_weight": 0.2},
    "addLoyaltyPoints": {"monetary": True, "value_weight": 0.7},
    "showNotification": {"monetary": False, "value_weight": 0.05},
}

# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------
# `paid_feature` marks campaigns that sit behind a paid entitlement, which the
# salience ranker weights up.
CAMPAIGNS = [
    # --- acme-commerce -----------------------------------------------------
    {
        "campaign_id": "acme-winback",
        "tenant": "acme-commerce",
        "name": "Winback Reactivation",
        "campaign_type": "winback",
        "paid_feature": True,
        "share": 0.30,
        "effects": ["acceptCoupon", "rejectCoupon", "setDiscount"],
    },
    {
        "campaign_id": "acme-loyalty-tier",
        "tenant": "acme-commerce",
        "name": "Loyalty Tier Accelerator",
        "campaign_type": "loyalty",
        "paid_feature": True,
        "share": 0.28,
        "effects": ["addLoyaltyPoints", "showNotification"],
    },
    {
        "campaign_id": "acme-basket-boost",
        "tenant": "acme-commerce",
        "name": "Basket Boost",
        "campaign_type": "cart",
        "paid_feature": False,
        "share": 0.42,
        "effects": ["setDiscount", "showNotification"],
    },
    # --- nordwind-retail ---------------------------------------------------
    {
        "campaign_id": "nord-seasonal",
        "tenant": "nordwind-retail",
        "name": "Seasonal Markdown",
        "campaign_type": "cart",
        "paid_feature": False,
        "share": 0.55,
        "effects": ["setDiscount", "showNotification"],
    },
    {
        "campaign_id": "nord-coupon-drop",
        "tenant": "nordwind-retail",
        "name": "Coupon Drop",
        "campaign_type": "coupon",
        "paid_feature": True,
        "share": 0.45,
        "effects": ["acceptCoupon", "rejectCoupon"],
    },
    # --- fastcart ----------------------------------------------------------
    {
        "campaign_id": "fast-free-ship",
        "tenant": "fastcart",
        "name": "Free Shipping Threshold",
        "campaign_type": "cart",
        "paid_feature": False,
        "share": 0.60,
        "effects": ["setDiscount", "showNotification"],
    },
    {
        "campaign_id": "fast-points-launch",
        "tenant": "fastcart",
        "name": "Points Launch",
        "campaign_type": "loyalty",
        "paid_feature": True,
        "share": 0.40,
        # S2: this campaign is the adoption ramp. Before 2025-Q4 it fires
        # nothing at all.
        "effects": ["addLoyaltyPoints", "showNotification"],
    },
    # --- brightline-grocers ------------------------------------------------
    {
        "campaign_id": "bright-weekly",
        "tenant": "brightline-grocers",
        "name": "Weekly Shop Saver",
        "campaign_type": "cart",
        "paid_feature": False,
        "share": 0.70,
        "effects": ["setDiscount", "showNotification"],
    },
    {
        "campaign_id": "bright-notify",
        "tenant": "brightline-grocers",
        "name": "Aisle Reminder",
        "campaign_type": "messaging",
        "paid_feature": False,
        "share": 0.30,
        # S4: the immaterial spike lands here.
        "effects": ["showNotification"],
    },
]

CAMPAIGNS_BY_TENANT: dict[str, list[dict]] = {}
for _c in CAMPAIGNS:
    CAMPAIGNS_BY_TENANT.setdefault(_c["tenant"], []).append(_c)

# Two ruleset versions per campaign, so lineage in int_ has something to resolve.
RULESETS = []
for _c in CAMPAIGNS:
    for _v in (1, 2):
        RULESETS.append(
            {
                "ruleset_id": f"{_c['campaign_id']}-rs{_v}",
                "campaign_id": _c["campaign_id"],
                "version": _v,
                "activated_on": START if _v == 1 else dt.date(2026, 1, 1),
            }
        )

# --------------------------------------------------------------------------
# API surface (integration logs)
# --------------------------------------------------------------------------
ENDPOINTS = [
    "/v2/customer_sessions",
    "/v2/customer_profiles",
    "/v1/coupons/reserve",
    "/v1/loyalty/balances",
    "/v1/events",
]

# --------------------------------------------------------------------------
# Planted signals
# --------------------------------------------------------------------------
# Each entry is (id, description). The multipliers that make them true live in
# the functions below, tagged with the same id. SIGNALS.md documents them for
# the presenter.
SIGNALS = [
    ("S1", "acme-commerce Winback Reactivation coupon redemption rate falls 22% "
           "in 2026-Q2 vs 2026-Q1, concentrated in the 'returning' shopper segment."),
    ("S2", "fastcart Points Launch ramps addLoyaltyPoints from zero in 2025-Q4 "
           "to material volume by 2026-Q2. Feature adoption."),
    ("S3", "nordwind-retail mobile suffers a 5xx integration error spike in the "
           "week of 2026-05-11. Revenue-affecting, so high salience."),
    ("S4", "brightline-grocers Aisle Reminder showNotification volume triples in "
           "2026-Q2. Statistically significant, commercially immaterial. The "
           "salience ranker must demote it."),
    ("S5", "nordwind-retail is entitled to loyalty but fires zero loyalty events. "
           "Expansion signal."),
    ("S6", "acme-commerce loyalty points issued grow faster than points burned. "
           "Rising liability."),
]

# S3: the exact week the integration degrades.
S3_APPLICATION = "nordwind-retail-mobile"
S3_WEEK_START = dt.date(2026, 5, 11)
S3_WEEK_END = dt.date(2026, 5, 17)


def s1_redemption_rate(tenant: str, campaign_id: str, segment: str, d: dt.date) -> float:
    """Coupon acceptance probability. S1 lives here.

    Baseline is 0.62. For the acme winback campaign the rate holds through
    2026-Q1 and then drops in Q2, with the fall concentrated in the 'returning'
    segment so the narrative has something to attribute it to.
    """
    base = 0.62
    if campaign_id != "acme-winback":
        return base
    if quarter_of(d) != QBR_QUARTER:
        return base
    # Overall effect lands at roughly -22% relative.
    if segment == "returning":
        return base * 0.63   # the concentration
    return base * 0.93


def s2_adoption_active(campaign_id: str, d: dt.date) -> bool:
    """S2: Points Launch fires nothing before 2025-Q4, then ramps."""
    if campaign_id != "fast-points-launch":
        return True
    return d >= dt.date(2025, 10, 1)


def s2_adoption_scale(campaign_id: str, d: dt.date) -> float:
    """S2: ramp multiplier once the campaign is live."""
    if campaign_id != "fast-points-launch":
        return 1.0
    q = quarter_of(d)
    return {"2025-Q4": 0.15, "2026-Q1": 0.55, "2026-Q2": 1.0}.get(q, 0.0)


def s3_error_rate(application_id: str, d: dt.date) -> float:
    """S3: integration 5xx rate. Normally under 1%, spikes for one week."""
    if application_id == S3_APPLICATION and S3_WEEK_START <= d <= S3_WEEK_END:
        return 0.18
    return 0.006


def s4_notification_scale(campaign_id: str, d: dt.date) -> float:
    """S4: the immaterial spike. Volume triples, value stays near zero."""
    if campaign_id != "bright-notify":
        return 1.0
    return 3.0 if quarter_of(d) == QBR_QUARTER else 1.0


def s5_loyalty_enabled(tenant: str) -> bool:
    """S5: nordwind is entitled to loyalty but never fires an event."""
    if tenant == "nordwind-retail":
        return False
    return "loyalty" in TENANTS_BY_ID[tenant]["entitlements"]


def s6_burn_ratio(tenant: str, d: dt.date) -> float:
    """S6: share of loyalty events that are burns rather than issues.

    For acme the burn share falls over time, so issued outruns burned and the
    outstanding liability grows.
    """
    if tenant != "acme-commerce":
        return 0.45
    q = quarter_of(d)
    return {
        "2025-Q1": 0.44, "2025-Q2": 0.41, "2025-Q3": 0.38,
        "2025-Q4": 0.34, "2026-Q1": 0.30, "2026-Q2": 0.26,
    }.get(q, 0.40)


def growth_multiplier(d: dt.date) -> float:
    """Gentle organic growth so trends are not flat, plus weekly seasonality."""
    days = (d - START).days
    trend = 1.0 + 0.45 * (days / max((END - START).days, 1))
    weekday = d.weekday()
    seasonal = 0.78 if weekday >= 5 else 1.05
    return trend * seasonal
