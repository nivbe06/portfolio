select
    r.ruleset_id,
    r.campaign_id,
    r.ruleset_version,
    cast(r.activated_on as date)    as activated_on,
    c.tenant                        as tenant_id
from {{ ref('seed_rulesets') }} r
join {{ ref('seed_campaigns') }} c using (campaign_id)
