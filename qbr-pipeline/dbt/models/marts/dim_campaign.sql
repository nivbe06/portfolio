select
    campaign_id,
    tenant                          as tenant_id,
    campaign_name,
    campaign_type,
    is_paid_feature
from {{ ref('seed_campaigns') }}
