-- One row per cart evaluation, typed and deduped.
-- PII (profile_email) is carried at this layer on purpose; the whole point of
-- the reduction is that it does not survive to rpt_. See tests/assert_no_pii_in_rpt.sql.
with src as (
    select * from {{ source('raw', 'session_evaluations') }}
),

deduped as (
    select
        *,
        row_number() over (partition by event_id order by occurred_at) as _rn
    from src
)

select
    event_id,
    session_id,
    tenant,
    application_id,
    profile_id,
    profile_email,
    profile_segment,
    cast(occurred_at as timestamp)              as evaluated_at,
    cast(occurred_at as date)                   as evaluated_on,
    month                                       as partition_month,
    cart_total,
    currency,
    cart_item_count,
    evaluated_campaigns,
    ruleset_version,
    latency_ms,
    state
from deduped
where _rn = 1
