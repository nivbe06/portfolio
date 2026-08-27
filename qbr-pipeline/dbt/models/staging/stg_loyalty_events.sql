-- Carries PII (profile_email), same as sessions.
with src as (
    select * from {{ source('raw', 'loyalty_events') }}
),

deduped as (
    select *, row_number() over (partition by event_id order by occurred_at) as _rn
    from src
)

select
    event_id,
    tenant,
    profile_id,
    profile_email,
    programme_id,
    cast(occurred_at as timestamp)  as occurred_at,
    cast(occurred_at as date)       as occurred_on,
    month                           as partition_month,
    points_delta,
    direction,
    tier_before,
    tier_after,
    reason,
    case when direction = 'issue' then points_delta else 0 end       as points_issued,
    case when direction = 'burn'  then abs(points_delta) else 0 end  as points_burned
from deduped
where _rn = 1
