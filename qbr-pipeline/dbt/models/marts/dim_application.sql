select
    application_id,
    tenant                          as tenant_id,
    channel,
    application_name
from {{ ref('seed_applications') }}
