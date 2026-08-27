-- The funnel in the design doc is an argument, so it should be a test rather
-- than a slide. If the published serving layer stops being small, the claim
-- that an LLM can reason over it stops being true, and this fails.
with published as (
    select count(*) as n from {{ ref('rpt_qbr_campaign_performance') }}
    union all
    select count(*) from {{ ref('rpt_feature_adoption') }}
    union all
    select count(*) from {{ ref('rpt_qbr_overview') }}
    union all
    select count(*) from {{ ref('rpt_anomalies') }}
),

total as (
    select sum(n) as rpt_rows from published
)

select
    rpt_rows,
    {{ var('max_rpt_rows') }} as max_allowed,
    'published serving layer exceeded its row budget; the LLM payload assumption no longer holds' as failure_reason
from total
where rpt_rows > {{ var('max_rpt_rows') }}
