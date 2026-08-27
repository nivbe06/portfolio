{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'requested_on', 'application_id']
) }}

with src as (
    select * from {{ ref('stg_integration_requests') }}
    {% if is_incremental() %}
    where requested_on >= (select coalesce(max(requested_on), '1900-01-01') - interval 3 day from {{ this }})
    {% endif %}
)

select
    tenant                                          as tenant_id,
    requested_on,
    application_id,
    count(*)                                        as requests,
    sum(case when is_server_error then 1 else 0 end) as server_errors,
    avg(latency_ms)                                 as avg_latency_ms,
    quantile_cont(latency_ms, 0.95)                 as p95_latency_ms
from src
group by 1, 2, 3
