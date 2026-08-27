{{ config(
    location = env_var('TALON_SERVING_ROOT', '../data/serving') ~ '/rpt_feature_adoption.parquet'
) }}

-- Adoption is entitlement versus actual use. An account paying for a feature it
-- never fires is an expansion conversation, not a usage statistic, so the
-- entitled-but-unused case has to be a row rather than an absence of rows.
with usage as (
    select
        f.tenant_id,
        c.quarter_label,
        f.effect_type                   as feature,
        sum(f.effects_fired)            as usage_count,
        sum(f.discount_value)           as feature_discount_value
    from {{ ref('fct_effects_fired') }} f
    join {{ ref('int_quarter_calendar') }} c on f.fired_on = c.calendar_date
    group by 1, 2, 3
),

-- Every tenant x quarter x known effect type, so gaps are visible.
spine as (
    select t.tenant_id, q.quarter_label, e.effect_type as feature,
           e.is_monetary, e.value_weight
    from {{ ref('dim_tenant') }} t
    cross join (select distinct quarter_label from {{ ref('int_quarter_calendar') }}) q
    cross join {{ ref('dim_effect_type') }} e
),

joined as (
    select
        s.tenant_id,
        s.quarter_label,
        s.feature,
        s.is_monetary,
        s.value_weight,
        coalesce(u.usage_count, 0)              as usage_count,
        coalesce(u.feature_discount_value, 0)   as feature_discount_value
    from spine s
    left join usage u
        on  s.tenant_id = u.tenant_id
        and s.quarter_label = u.quarter_label
        and s.feature = u.feature
),

with_history as (
    select
        j.*,
        lag(j.usage_count) over w                                as prior_usage_count,
        sum(j.usage_count) over (
            partition by j.tenant_id, j.feature
            order by j.quarter_label
            rows between unbounded preceding and 1 preceding
        )                                                        as usage_before_this_quarter
    from joined j
    window w as (partition by j.tenant_id, j.feature order by j.quarter_label)
)

select
    h.tenant_id,
    t.plan_tier,
    h.quarter_label,
    h.feature,
    h.is_monetary,
    h.value_weight,
    h.usage_count,
    h.prior_usage_count,
    h.feature_discount_value,
    -- Is this feature covered by the account's plan?
    case
        when h.feature = 'addLoyaltyPoints' then t.has_loyalty_entitlement
        else true
    end                                                          as is_entitled,
    case
        when h.usage_count = 0 and coalesce(h.usage_before_this_quarter, 0) = 0 then 'never_used'
        when h.usage_count = 0 then 'lapsed'
        when coalesce(h.usage_before_this_quarter, 0) = 0 then 'newly_adopted'
        when h.prior_usage_count > 0 and h.usage_count > h.prior_usage_count * 1.2 then 'growing'
        when h.prior_usage_count > 0 and h.usage_count < h.prior_usage_count * 0.8 then 'declining'
        else 'steady'
    end                                                          as adoption_state,
    case when h.prior_usage_count > 0
         then (h.usage_count - h.prior_usage_count)::double / h.prior_usage_count end as usage_qoq
from with_history h
left join {{ ref('dim_tenant') }} t on h.tenant_id = t.tenant_id
