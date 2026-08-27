with src as (
    select * from {{ source('raw', 'integration_requests') }}
),

deduped as (
    select *, row_number() over (partition by event_id order by occurred_at) as _rn
    from src
)

select
    event_id,
    tenant,
    application_id,
    endpoint,
    cast(occurred_at as timestamp)  as requested_at,
    cast(occurred_at as date)       as requested_on,
    month                           as partition_month,
    http_status,
    error_code,
    latency_ms,
    http_status >= 500              as is_server_error
from deduped
where _rn = 1
