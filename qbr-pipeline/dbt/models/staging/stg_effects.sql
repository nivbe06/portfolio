-- One row per effect returned to the integration.
with src as (
    select * from {{ source('raw', 'effects') }}
),

deduped as (
    select *, row_number() over (partition by event_id order by occurred_at) as _rn
    from src
)

select
    event_id,
    session_id,
    tenant,
    campaign_id,
    ruleset_id,
    effect_type,
    cast(occurred_at as timestamp)      as fired_at,
    cast(occurred_at as date)           as fired_on,
    month                               as partition_month,
    coalesce(discount_value, 0.0)       as discount_value,
    coalesce(points, 0)                 as points,
    currency,
    coupon_code,
    -- Whether the effect moves money. Drives materiality downstream, and is
    -- the reason a notification spike cannot outrank a discount collapse.
    effect_type in ('setDiscount', 'acceptCoupon', 'addLoyaltyPoints') as is_monetary
from deduped
where _rn = 1
