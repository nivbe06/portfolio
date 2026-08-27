{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'evaluated_on', 'application_id', 'profile_segment']
) }}

-- Daily grain. This is where the volume actually collapses: ~1.26M raw session
-- rows become a few thousand daily aggregates.
--
-- delete+insert rather than merge (merge needs DuckDB >= 1.4.0) and rather than
-- microbatch (dbt-duckdb warns it may not be faster, and it cannot use a
-- unique_key). The lookback predicate below is what makes reruns cheap.
with src as (
    select * from {{ ref('stg_session_evaluations') }}
    {% if is_incremental() %}
    where evaluated_on >= (select coalesce(max(evaluated_on), '1900-01-01') - interval 3 day from {{ this }})
    {% endif %}
)

select
    tenant,
    application_id,
    profile_segment,
    evaluated_on,
    tenant                                              as tenant_id,
    count(*)                                            as sessions_evaluated,
    count(distinct profile_id)                          as distinct_profiles,
    sum(cart_total)                                     as cart_value,
    avg(cart_total)                                     as avg_cart_value,
    sum(cart_item_count)                                as items,
    avg(latency_ms)                                     as avg_latency_ms,
    quantile_cont(latency_ms, 0.95)                     as p95_latency_ms,
    sum(case when state = 'cancelled' then 1 else 0 end) as cancelled_sessions
from src
group by 1, 2, 3, 4
