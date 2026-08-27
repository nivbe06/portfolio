{{ config(
    location = env_var('TALON_SERVING_ROOT', '../data/serving') ~ '/rpt_qbr_campaign_performance.parquet'
) }}

-- QBR grain: tenant x quarter x campaign x shopper segment.
-- Period-over-period values are resolved here, not in the semantic layer, so a
-- narrative can never be handed a delta the warehouse did not compute.
with effects as (
    select
        f.tenant_id,
        c.quarter_label,
        f.campaign_id,
        f.profile_segment,
        sum(f.effects_fired)            as effects_fired,
        sum(f.discount_value)           as discount_value,
        sum(f.points_awarded)           as points_awarded,
        sum(f.sessions_with_effect)     as sessions_with_effect
    from {{ ref('fct_effects_fired') }} f
    join {{ ref('int_quarter_calendar') }} c on f.fired_on = c.calendar_date
    group by 1, 2, 3, 4
),

coupons as (
    select
        f.tenant_id,
        c.quarter_label,
        f.campaign_id,
        f.profile_segment,
        sum(f.redemptions)              as redemptions,
        sum(f.redemption_attempts)      as redemption_attempts,
        sum(f.rejections)               as rejections
    from {{ ref('fct_coupon_redemptions') }} f
    join {{ ref('int_quarter_calendar') }} c on f.occurred_on = c.calendar_date
    group by 1, 2, 3, 4
),

joined as (
    select
        coalesce(e.tenant_id, k.tenant_id)              as tenant_id,
        coalesce(e.quarter_label, k.quarter_label)      as quarter_label,
        coalesce(e.campaign_id, k.campaign_id)          as campaign_id,
        coalesce(e.profile_segment, k.profile_segment)  as profile_segment,
        coalesce(e.effects_fired, 0)                    as effects_fired,
        coalesce(e.discount_value, 0)                   as discount_value,
        coalesce(e.points_awarded, 0)                   as points_awarded,
        coalesce(e.sessions_with_effect, 0)             as sessions_with_effect,
        coalesce(k.redemptions, 0)                      as redemptions,
        coalesce(k.redemption_attempts, 0)              as redemption_attempts,
        coalesce(k.rejections, 0)                       as rejections
    from effects e
    full outer join coupons k
        on  e.tenant_id = k.tenant_id
        and e.quarter_label = k.quarter_label
        and e.campaign_id = k.campaign_id
        and e.profile_segment = k.profile_segment
),

with_prior as (
    select
        j.*,
        lag(j.redemptions) over w        as prior_redemptions,
        lag(j.redemption_attempts) over w as prior_redemption_attempts,
        lag(j.discount_value) over w     as prior_discount_value,
        lag(j.effects_fired) over w      as prior_effects_fired
    from joined j
    window w as (
        partition by j.tenant_id, j.campaign_id, j.profile_segment
        order by j.quarter_label
    )
)

select
    p.tenant_id,
    p.quarter_label,
    p.campaign_id,
    d.campaign_name,
    d.campaign_type,
    d.is_paid_feature,
    t.plan_tier,
    t.currency,
    p.profile_segment,
    p.effects_fired,
    p.discount_value,
    p.points_awarded,
    p.sessions_with_effect,
    p.redemptions,
    p.redemption_attempts,
    p.rejections,
    p.prior_redemptions,
    p.prior_redemption_attempts,
    p.prior_discount_value,
    p.prior_effects_fired,
    -- Rates are exposed alongside their components. The components are what the
    -- semantic layer aggregates; the rate is here so a single row is readable.
    case when p.redemption_attempts > 0
         then p.redemptions::double / p.redemption_attempts end as redemption_rate,
    case when p.prior_redemption_attempts > 0
         then p.prior_redemptions::double / p.prior_redemption_attempts end as prior_redemption_rate,
    case when p.prior_discount_value > 0
         then (p.discount_value - p.prior_discount_value) / p.prior_discount_value end as discount_value_qoq
from with_prior p
left join {{ ref('dim_campaign') }} d on p.campaign_id = d.campaign_id
left join {{ ref('dim_tenant') }} t on p.tenant_id = t.tenant_id
