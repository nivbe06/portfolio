select
    tenant                          as tenant_id,
    tenant_name,
    domain,
    plan_tier,
    country,
    currency,
    entitlements,
    has_loyalty_entitlement,
    has_referrals_entitlement
from {{ ref('seed_tenants') }}
