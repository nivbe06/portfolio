-- Period-over-period values are computed with a window function, which is easy
-- to get subtly wrong: an off-by-one partition, a bad ordering, and every
-- "down 22% on last quarter" in the narrative is wrong while still looking
-- plausible.
--
-- This recomputes the prior quarter by an independent self-join and fails if it
-- disagrees with the lag() the model published.
with published as (
    select
        tenant_id,
        campaign_id,
        profile_segment,
        quarter_label,
        redemptions,
        prior_redemptions
    from {{ ref('rpt_qbr_campaign_performance') }}
),

-- Deduplicate first, then number. `select distinct x, row_number() over ...`
-- evaluates the window before the distinct, so every quarter would come back
-- with several indexes and the comparison below would silently shift by one.
quarters as (
    select
        quarter_label,
        row_number() over (order by quarter_label) as q_index
    from (select distinct quarter_label from published)
),

recomputed as (
    select
        p.tenant_id,
        p.campaign_id,
        p.profile_segment,
        p.quarter_label,
        p.prior_redemptions,
        prev.redemptions as expected_prior_redemptions
    from published p
    join quarters q      on p.quarter_label = q.quarter_label
    join quarters qprev  on qprev.q_index = q.q_index - 1
    left join published prev
        on  prev.tenant_id = p.tenant_id
        and prev.campaign_id = p.campaign_id
        and prev.profile_segment = p.profile_segment
        and prev.quarter_label = qprev.quarter_label
)

select
    tenant_id,
    campaign_id,
    profile_segment,
    quarter_label,
    prior_redemptions,
    expected_prior_redemptions,
    'lag() prior-quarter value disagrees with an independent self-join' as failure_reason
from recomputed
where coalesce(prior_redemptions, -1) <> coalesce(expected_prior_redemptions, -1)
