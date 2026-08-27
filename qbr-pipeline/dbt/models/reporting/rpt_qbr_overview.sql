{{ config(
    location = env_var('TALON_SERVING_ROOT', '../data/serving') ~ '/rpt_qbr_overview.parquet'
) }}

-- Account-level context, one row per tenant x quarter x shopper segment.
-- Feeds the wizard's account picker and the usage and health bundles.
with sessions as (
    select
        f.tenant_id,
        c.quarter_label,
        f.profile_segment,
        sum(f.sessions_evaluated)       as sessions_evaluated,
        sum(f.distinct_profiles)        as distinct_profiles,
        sum(f.cart_value)               as cart_value,
        sum(f.items)                    as items,
        sum(f.cancelled_sessions)       as cancelled_sessions,
        avg(f.avg_latency_ms)           as avg_latency_ms
    from {{ ref('fct_session_evaluations') }} f
    join {{ ref('int_quarter_calendar') }} c on f.evaluated_on = c.calendar_date
    group by 1, 2, 3
),

-- Health and loyalty have no shopper-segment grain, so they are attached at
-- tenant x quarter and repeated. Kept as separate columns rather than unioned
-- rows so the semantic layer does not have to disambiguate grains.
health as (
    select
        f.tenant_id,
        c.quarter_label,
        sum(f.requests)                 as api_requests,
        sum(f.server_errors)            as api_server_errors,
        avg(f.p95_latency_ms)           as api_p95_latency_ms
    from {{ ref('fct_integration_health') }} f
    join {{ ref('int_quarter_calendar') }} c on f.requested_on = c.calendar_date
    group by 1, 2
),

loyalty as (
    select
        f.tenant_id,
        c.quarter_label,
        sum(f.points_issued)            as points_issued,
        sum(f.points_burned)            as points_burned,
        sum(f.net_points_outstanding)   as net_points_outstanding,
        sum(f.distinct_members)         as loyalty_member_events
    from {{ ref('fct_loyalty_events') }} f
    join {{ ref('int_quarter_calendar') }} c on f.occurred_on = c.calendar_date
    group by 1, 2
),

joined as (
    select
        s.*,
        h.api_requests,
        h.api_server_errors,
        h.api_p95_latency_ms,
        coalesce(l.points_issued, 0)            as points_issued,
        coalesce(l.points_burned, 0)            as points_burned,
        coalesce(l.net_points_outstanding, 0)   as net_points_outstanding
    from sessions s
    left join health h  on s.tenant_id = h.tenant_id and s.quarter_label = h.quarter_label
    left join loyalty l on s.tenant_id = l.tenant_id and s.quarter_label = l.quarter_label
),

with_prior as (
    select
        j.*,
        lag(j.sessions_evaluated) over w as prior_sessions_evaluated,
        lag(j.cart_value) over w         as prior_cart_value
    from joined j
    window w as (partition by j.tenant_id, j.profile_segment order by j.quarter_label)
)

select
    p.tenant_id,
    t.tenant_name,
    t.plan_tier,
    t.country,
    t.currency,
    t.has_loyalty_entitlement,
    t.has_referrals_entitlement,
    p.quarter_label,
    p.profile_segment,
    p.sessions_evaluated,
    p.distinct_profiles,
    p.cart_value,
    p.items,
    p.cancelled_sessions,
    p.avg_latency_ms,
    p.api_requests,
    p.api_server_errors,
    p.api_p95_latency_ms,
    p.points_issued,
    p.points_burned,
    p.net_points_outstanding,
    p.prior_sessions_evaluated,
    p.prior_cart_value,
    case when p.prior_sessions_evaluated > 0
         then (p.sessions_evaluated - p.prior_sessions_evaluated)::double / p.prior_sessions_evaluated
    end                                                     as sessions_qoq,
    case when p.api_requests > 0
         then p.api_server_errors::double / p.api_requests
    end                                                     as api_error_rate
from with_prior p
left join {{ ref('dim_tenant') }} t on p.tenant_id = t.tenant_id
