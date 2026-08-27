-- Calendar spine mapping every observed date to its quarter and to the quarter
-- before it. Period-over-period comparison is the backbone of a QBR, so it is
-- resolved once here rather than re-derived with a self-join in every mart.
with bounds as (
    select min(evaluated_on) as mn, max(evaluated_on) as mx
    from {{ ref('stg_session_evaluations') }}
),

days as (
    select unnest(generate_series(mn, mx, interval 1 day))::date as calendar_date
    from bounds
),

labelled as (
    select
        calendar_date,
        cast(year(calendar_date) as varchar) || '-Q' || cast(quarter(calendar_date) as varchar) as quarter_label,
        date_trunc('quarter', calendar_date) as quarter_start
    from days
)

select
    calendar_date,
    quarter_label,
    quarter_start,
    -- The immediately preceding quarter, as a label, so marts can join on it.
    cast(year(quarter_start - interval 1 day) as varchar)
        || '-Q' || cast(quarter(quarter_start - interval 1 day) as varchar) as prior_quarter_label,
    date_trunc('month', calendar_date) as month_start
from labelled
