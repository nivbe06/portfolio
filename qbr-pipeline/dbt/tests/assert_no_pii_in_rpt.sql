-- The design doc claims the reduction pipeline is also a PII firewall: raw logs
-- carry profile identifiers and emails, and nothing personal survives to the
-- layer an LLM can reach. That is a claim until something enforces it.
--
-- This test enforces it. It inspects the actual column names of every published
-- rpt_ model and fails if any of them looks like a personal identifier. Adding
-- profile_email to an rpt_ model breaks the build, not the customer's trust.
--
-- Returns one row per offending column, so a failure names the exact problem.
with published_columns as (
    select
        table_name,
        column_name
    from information_schema.columns
    where table_schema = 'main_reporting'
),

banned as (
    select unnest([
        'profile_id',
        'profile_email',
        'email',
        'coupon_code',
        'session_id',
        'cart_items'
    ]) as column_name
)

select
    p.table_name,
    p.column_name,
    'personal or session-level identifier reached the published serving layer' as failure_reason
from published_columns p
join banned b on lower(p.column_name) = b.column_name
