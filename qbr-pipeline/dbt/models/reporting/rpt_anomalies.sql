{{ config(
    location = env_var('TALON_SERVING_ROOT', '../data/serving') ~ '/rpt_anomalies.parquet'
) }}

-- Anomaly detection, in SQL, deterministically. No LLM is involved in finding
-- these and none should be: a rolling z-score over 2.18M events is cheap,
-- reproducible and auditable, which is exactly what a model scanning for
-- outliers is not.
--
-- Detection runs at weekly grain. A quarter-grain z-score dilutes a one-week
-- incident across thirteen weeks and misses it entirely.
--
-- This model deliberately stops at "statistically unusual". It also emits the
-- raw inputs a materiality ranker needs (monetary_basis, is_paid_feature,
-- value_weight) but does not itself decide what is worth discussing. That
-- judgement is business logic and lives in qbr/salience.py, so it can be tuned
-- without a warehouse rebuild.

with bounds as (
    select min(calendar_date) as first_date, max(calendar_date) as last_date
    from {{ ref('int_quarter_calendar') }}
),

calendar as (
    select
        c.calendar_date,
        date_trunc('week', c.calendar_date)::date as week_start
    from {{ ref('int_quarter_calendar') }} c
    cross join bounds b
    -- Only whole weeks. The window at either end of the data is partial, and a
    -- two-day week compared against a baseline of seven-day weeks produces a
    -- huge z-score that is an artefact of the cutoff, not a signal. Left in,
    -- these dominate the ranking and bury every real finding.
    where date_trunc('week', c.calendar_date)::date >= b.first_date
      and date_trunc('week', c.calendar_date)::date + 6 <= b.last_date
),

-- ---------------------------------------------------------------- series
-- Each block emits the same shape so they can be unioned into one long series.

campaign_redemption as (
    select
        f.tenant_id,
        c.week_start,
        'redemption_rate'                                   as metric_name,
        'campaign'                                          as entity_type,
        f.campaign_id                                       as entity_id,
        case when sum(f.redemption_attempts) > 0
             then sum(f.redemptions)::double / sum(f.redemption_attempts)
             else null end                                  as metric_value,
        sum(f.redemption_attempts)                          as volume,
        true                                                as affects_revenue
    from {{ ref('fct_coupon_redemptions') }} f
    join calendar c on f.occurred_on = c.calendar_date
    group by 1, 2, 4, 5
),

campaign_discount as (
    select
        f.tenant_id,
        c.week_start,
        'discount_value',
        'campaign',
        f.campaign_id,
        sum(f.discount_value)::double,
        sum(f.effects_fired),
        true
    from {{ ref('fct_effects_fired') }} f
    join calendar c on f.fired_on = c.calendar_date
    group by 1, 2, 4, 5
),

effect_volume as (
    select
        f.tenant_id,
        c.week_start,
        'effects_fired',
        'effect_type',
        f.effect_type,
        sum(f.effects_fired)::double,
        sum(f.effects_fired),
        bool_or(f.is_monetary)
    from {{ ref('fct_effects_fired') }} f
    join calendar c on f.fired_on = c.calendar_date
    group by 1, 2, 4, 5
),

session_volume as (
    select
        f.tenant_id,
        c.week_start,
        'sessions_evaluated',
        'tenant',
        f.tenant_id,
        sum(f.sessions_evaluated)::double,
        sum(f.sessions_evaluated),
        true
    from {{ ref('fct_session_evaluations') }} f
    join calendar c on f.evaluated_on = c.calendar_date
    group by 1, 2, 4, 5
),

integration_errors as (
    select
        f.tenant_id,
        c.week_start,
        'server_error_rate',
        'application',
        f.application_id,
        case when sum(f.requests) > 0
             then sum(f.server_errors)::double / sum(f.requests)
             else null end,
        sum(f.requests),
        true
    from {{ ref('fct_integration_health') }} f
    join calendar c on f.requested_on = c.calendar_date
    group by 1, 2, 4, 5
),

loyalty_liability as (
    select
        f.tenant_id,
        c.week_start,
        'net_points_outstanding',
        'tenant',
        f.tenant_id,
        sum(f.net_points_outstanding)::double,
        sum(f.loyalty_events),
        true
    from {{ ref('fct_loyalty_events') }} f
    join calendar c on f.occurred_on = c.calendar_date
    group by 1, 2, 4, 5
),

series as (
    select * from campaign_redemption
    union all select * from campaign_discount
    union all select * from effect_volume
    union all select * from session_volume
    union all select * from integration_errors
    union all select * from loyalty_liability
),

-- ---------------------------------------------------------------- baseline
-- Trailing eight weeks, excluding the week under test, so a spike cannot
-- inflate the baseline it is being measured against.
scored as (
    select
        s.*,
        avg(s.metric_value) over w      as baseline_mean,
        stddev_samp(s.metric_value) over w as baseline_sd,
        count(*) over w                 as baseline_weeks
    from series s
    where s.metric_value is not null
    window w as (
        partition by s.tenant_id, s.metric_name, s.entity_id
        order by s.week_start
        rows between 8 preceding and 1 preceding
    )
),

flagged as (
    select
        tenant_id,
        week_start,
        metric_name,
        entity_type,
        entity_id,
        metric_value,
        volume,
        affects_revenue,
        baseline_mean,
        baseline_sd,
        baseline_weeks,
        case
            when baseline_sd is null or baseline_sd = 0 then 0
            else (metric_value - baseline_mean) / baseline_sd
        end                                                     as z_score,
        case
            when baseline_mean is null or baseline_mean = 0 then null
            else (metric_value - baseline_mean) / abs(baseline_mean)
        end                                                     as relative_change
    from scored
    -- Need a real baseline before a z-score means anything.
    where baseline_weeks >= 6
)

select
    f.tenant_id,
    t.plan_tier,
    t.currency,
    f.week_start,
    -- Derived from week_start, not aggregated from member days. A week that
    -- straddles a quarter boundary must land in exactly one quarter, and
    -- max(quarter_label) would pick one arbitrarily.
    cast(year(f.week_start) as varchar) || '-Q' || cast(quarter(f.week_start) as varchar)
                                                                as quarter_label,
    f.metric_name,
    f.entity_type,
    f.entity_id,
    coalesce(c.campaign_name, a.application_name, f.entity_id) as entity_label,
    f.metric_value,
    f.baseline_mean,
    f.baseline_sd,
    f.z_score,
    f.relative_change,
    f.volume,
    f.affects_revenue,
    coalesce(c.is_paid_feature, false)                          as is_paid_feature,
    coalesce(e.value_weight, 0.5)                               as value_weight,
    -- Absolute movement expressed in whatever the metric counts. For a rate
    -- this is scaled by volume so a rate change on 12,000 attempts outranks the
    -- same rate change on 40. This is the raw input the ranker weights, not a
    -- verdict.
    case
        when f.metric_name in ('redemption_rate', 'server_error_rate')
            then abs(f.metric_value - f.baseline_mean) * f.volume
        else abs(f.metric_value - f.baseline_mean)
    end                                                         as movement_magnitude,
    f.z_score >= 0                                              as is_increase
from flagged f
left join {{ ref('dim_tenant') }} t      on f.tenant_id = t.tenant_id
left join {{ ref('dim_campaign') }} c    on f.entity_id = c.campaign_id
left join {{ ref('dim_application') }} a on f.entity_id = a.application_id
left join {{ ref('dim_effect_type') }} e on f.entity_id = e.effect_type
where abs(f.z_score) >= 2.5
