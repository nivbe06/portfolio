# DAG guide: the 21 models, the reduction, and the business behind them

Companion to [`README.md`](README.md) and [`DESIGN.md`](DESIGN.md).
The design doc argues the architecture. This file explains what each model
actually is, what business question it answers, and how every number in the pack
is arrived at.

Internal working document: written to build the presentation from and to know
the system cold before a hostile Q&A. Not a handout. It describes the system as
it stands, including where it is wrong or thin — §13 is the list of things that
would be caught by someone who knows the platform.

**Contents.** §1–2 shape and reduction · §3 the Talon.One domain and where the
data comes from · §4 raw → staging, then all 21 models · §5–6 the serving layer ·
§7 redemption rate · §8 materialisation and the nightly run · §9 anomaly
detection · §10 salience · §11 tests · §12 planted signals · §13 known traps ·
§14 reproducing the numbers.

---

## 1. The shape in one paragraph

Four raw event streams land as gzipped JSONL. `stg_` types and dedupes them one
row per event. `int_` builds the lineage, the coupon projection and the calendar
spine that the `fct_` models are assembled from, and reduces nothing. `dim_`/`fct_`
collapse the grain to daily, which is where the volume actually disappears.
`rpt_` reshapes the daily facts into the four QBR-shaped tables a semantic layer
and an LLM can reason over, and publishes them as Parquet. 2,068,975 events in,
496 rows out.

```
raw JSONL ──► stg_ (4 views) ──► int_ (3 views) ──► fct_ / dim_ (10 tables) ──► rpt_ (4 parquet)
2,068,975        2,068,975        no reduction           49,523 + 44                  496
                     1x                1x                     42x                   4,171x
```

`int_` is the helper layer the `fct_` models are built from, in the usual
medallion order. It carries three things: the session → campaign → ruleset →
effect lineage; `int_coupon_events`, which projects the coupon lifecycle out of
that lineage because Talon.One has no coupon feed (§3); and the date spine the
four `rpt_` models join to. Sessions, loyalty and integration requests need no
join before aggregating, so those three `fct_` models read `stg_` directly
rather than being handed a pass-through view that adds a hop and no logic.

---

## 2. The reduction story, with real numbers

Every row count below is a count from the built warehouse, not an estimate.
Reproduce with `duckdb data/warehouse.duckdb -c "select count(*) from ..."`.
The token figure is the one exception and is marked as such.

| Stage           | Rows                                                                                  | Where the drop happens                                                     |
| --------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Raw / `stg_`    | **2,068,975**                                                                         | None. Format compaction only: JSONL → typed columns, dedupe on `event_id`. |
| `fct_` + `dim_` | **49,523** + 44                                                                       | Grain collapse to daily. **42x**.                                          |
| `rpt_`          | **496**                                                                               | Grain collapse to quarterly + QBR shape. **4,171x** cumulative.            |
| LLM payload     | Estimated a few thousand tokens (negligible costs. <$0.1 per QBR if executed plainly) | Top-N salience ranking on top of `rpt_`.                                   |

**On the token figure, precisely.** Nothing in this repo counts tokens.
`build_qbr.py` prints characters, and the number above is measured characters
with a 4-chars-per-token estimate laid over it, so treat it as an order of
magnitude and not a measurement. The real file is
`qbr/created-qbrs/payloads-acme-commerce-2026-Q2.json`: 13,211 characters as
written, 9,200 minified, of which the three section payloads are 5,201
(campaign performance 2,972, anomalies 1,376, feature adoption 853) and the rest
is account context, the registry, and the per-section writing rules. If asked
for a token count, say it has not been measured with a real tokeniser and give
the character counts, which have.

`int_` is a layer of the DAG but not a row of this funnel, and the distinction
matters. It reduces nothing: `int_session_campaign_lineage` is 1:1 with
`stg_effects` (510,080 in, 510,080 out), `int_coupon_events` is a filtered
projection of that lineage (115,924 coupon effects), and `int_quarter_calendar`
is a 546-row date spine. Its total, 626,550, is also not comparable to the
`stg_` and `fct_` totals either side of it, because it is not carrying all four
streams — those
that need no join reach `fct_` from `stg_`. Put that number in the Rows column
and the table reads as a 3x reduction between `stg_` and `int_` that never
happens; the missing volume has not been reduced, it is still in `stg_` waiting
for `fct_`.

Per-stream detail:

| Stream | `stg_` rows | Collapses into | `fct_` rows | Ratio |
|---|---|---|---|---|
| Customer sessions | 1,261,229 | `fct_session_evaluations` | 13,104 | 96x |
| Effects | 510,080 | `fct_effects_fired` | 27,683 | 18x |
| ↳ coupon projection | *(115,924 of the effects above)* | `fct_coupon_redemptions` | 3,276 | 35x |
| Integration requests | 265,775 | `fct_integration_health` | 4,368 | 61x |
| Loyalty events | 31,891 | `fct_loyalty_events` | 1,092 | 29x |
| **Total** | **2,068,975** | | **49,523** | **42x** |

Coupons are indented because they are not a fourth source. `int_coupon_events`
projects the `acceptCoupon` and `rejectCoupon` rows out of the effects stream, so
those 115,924 rows are counted once, in the Effects row. §3 explains why.

And the published layer:

| `rpt_` model | Rows | Grain |
|---|---|---|
| `rpt_qbr_campaign_performance` | 153 | tenant × quarter × campaign × segment |
| `rpt_anomalies` | 151 | tenant × week × metric × entity (only rows with abs(z) ≥ 2.5) |
| `rpt_feature_adoption` | 120 | 4 tenants × 6 quarters × 5 effect types, full spine |
| `rpt_qbr_overview` | 72 | 4 tenants × 6 quarters × 3 segments |
| **Total** | **496** | |

**Why the two-step collapse and not one.** `stg_` compacts *format*, `fct_`
collapses *grain*. Separating them means the aggregation logic is readable and
individually testable, and a grain bug can be isolated to one layer. `int_`
sits between them holding all the joins, so the layer that aggregates never
also has to join.

**Why `int_` reduces nothing.** That is the point. It is the logic layer:
session → campaign → ruleset → effect lineage, with the shopper segment carried
from the session onto every effect it produced. Materialised as a view, so it
costs no storage. Without it, "the drop is concentrated in returning shoppers"
is not an answerable question.

**Why this is a test, not a slide.** `assert_reduction_ratio.sql` fails the
build if the four `rpt_` models together exceed `max_rpt_rows` (8,000, set in
`dbt_project.yml`). The claim that an LLM can reason over the serving layer is
enforced by CI, not asserted in a document.

---

## 3. The Talon.One domain, and why a CSM cares

The raw streams are the platform's actual objects, not abstract "events".
Terminology below is checked against Talon.One's own documentation; where this
build's names diverge from theirs, §13 says so rather than papering over it.

**Customer session.** Talon.One's documented entity name. A shopper's cart is
sent to the promotion engine via the Integration API's *Update customer session*
call (`updateCustomerSessionV2`), which evaluates every live campaign against it
and returns effects. This is the platform's unit of work and its unit of cost:
1.26M of the 2.18M events. A CSM cares because session volume is the account's
engagement heartbeat, and because latency here is customer-visible at checkout.

A session has four documented states — `open`, `closed`, `cancelled` and
`partially returned` — and **Talon.One counts only `closed` (and partially
returned) toward campaign analytics; `open` and `cancelled` are excluded.** This
build models two of the four and counts both. See §13; it is the one place where
this warehouse would not reconcile against the customer's own screen.

**Effect.** What the engine returns. The five modelled here — `setDiscount`,
`acceptCoupon`, `rejectCoupon`, `addLoyaltyPoints`, `showNotification` — are
real Talon.One effect types, exact to the camelCase, drawn from a documented set
of about 35 that also covers referrals, giveaways, achievements, audiences and
the various `rollback*` counterparts. Effects are where the
platform delivers value, and only three of the five move money — which is why
`is_monetary` is computed at `stg_effects` and `value_weight` is a dimension
(`dim_effect_type`) rather than a constant in a ranker. A CSM cares because
"which effects fired, on which campaigns, for which shoppers" is the whole
value story of the quarter.

**Coupon redemption.** Attempt, then redeemed or rejected with a reason.
Redemption *rate* is the single most-quoted campaign KPI, and the most easily
broken: computed as a stored ratio it cannot be re-aggregated without the
average-of-averages bug. So the components (`redemptions`,
`redemption_attempts`, `rejections`) are stored and the rate is derived at
query time.

**Loyalty.** Talon.One writes *loyalty program* (and the `addLoyaltyPoints`
effect carries a `programId`); this repo's column is `programme_id`, which is a
British-spelling slip rather than their vocabulary. Points issued and burned,
tier transitions. Issued-minus-burned is
an accounting liability, not a vanity metric: points outstanding are money the
account owes its shoppers. A rising balance is a real conversation.

**Integration health.** API request log per application: status, error code,
latency. Not a promotions metric at all, but it is the thing that makes a QBR
credible — the customer already knows their mobile app broke in May, and a pack
that does not mention it is a pack they stop trusting.

**Shopper grouping.** This build calls it `profile_segment` with values `new`,
`returning` and `vip`. Talon.One's documented term for grouping customer
profiles is **audience**, not segment. The concept is right, the word is ours.

**Entitlement vs usage.** `dim_tenant` carries `has_loyalty_entitlement` and
`has_referrals_entitlement`. Paying for a feature and never firing it is not a
usage statistic, it is an expansion conversation. This is why
`rpt_feature_adoption` is built over a full tenant × quarter × feature spine:
a gap has to exist as a row before anyone can see it.

The four mock accounts are deliberately unlike each other: `acme-commerce`
(Enterprise, DE, everything entitled and used), `nordwind-retail` (Enterprise,
DE, loyalty entitled and never used), `fastcart` (Mid-Market, US, loyalty
adopted mid-history), `brightline-grocers` (Mid-Market, GB, no loyalty
entitlement, heavy notifications).

### Where this data would actually come from

The mock generator emits five streams; this DAG now reads four. Neither is
Talon.One's shape. Their real
automated export surface is narrower, and knowing the difference is worth more
in a Q&A than defending the mock.

Talon.One exports **customer sessions, customer profiles and triggered effects**
automatically, via Management API endpoints (*Export customer sessions*, *Export
triggered effects*, and *List Applications events* for the event feed), as CSV,
timestamps in UTC+00:00. **Loyalty data — balances, transaction logs, projected
balances — is manual export only**, out of the Campaign Manager. Coupons are not
a separate export at all. Webhooks exist but are rule-triggered effects: a push
channel for individual rules, not a bulk feed.

| This build's stream | Real source | Fidelity |
|---|---|---|
| `stg_session_evaluations` | Export customer sessions | **Direct match.** |
| `stg_effects` | Export triggered effects | **Direct match.** |
| `int_coupon_events` | None. Coupon lifecycle *is* effects: `acceptCoupon`, `rejectCoupon`, `couponCreated`, `reserveCoupon`, `rollbackCoupon` | Modelled as a projection of the effects lineage, because there is nothing else it could faithfully be. |
| `stg_loyalty_events` | Its own export — manual, out of Campaign Manager: balances, transaction logs, projected balances | **Correct as a separate source.** Kept; see below. |
| `stg_integration_requests` | Not Talon.One data at all — the customer's own API gateway telemetry | Real data, real source, but ours to collect, not theirs to export. |
| *(not modelled)* | Export customer profiles | A real automated export this build ignores; profile fields ride inline on sessions instead. |

**Coupons are a projection, not a source.** `int_coupon_events` selects the
`acceptCoupon` and `rejectCoupon` rows out of `int_session_campaign_lineage`,
and `fct_coupon_redemptions` aggregates that. The shopper segment is already on
the lineage row, so the coupon fact needs no join to recover it — which matters,
because `coupon_code` is not unique across effects (115,924 coupon effects over
84,317 codes) and joining on it multiplies rows. `assert_coupon_facts_do_not_fan_out` asserts that the fact's
`redemption_attempts` equals the count of coupon effects in `stg_effects`, so a
join reintroduced above it fails the build.

**Loyalty is a source, and that is correct.** Talon.One exports loyalty as its
own feed — balances, transaction logs, projected balances — so a separate `stg_`
model is the faithful shape rather than a shortcut. It also could not be a
projection here: this dataset emits no `deductLoyaltyPoints` effect, so every
burn, and with it signal S6, exists only in the loyalty feed. Projecting loyalty
out of effects would mean inventing the burns.

**What the coupon projection does not carry.** A rejection reason. Talon.One's
`rejectCoupon` effect has a `rejectionReason` prop (`CouponNotFound`,
`CouponExpired`, `CouponLimitReached`), so in production the breakdown of *why*
coupons bounce rides on the effect and flows through naturally. This dataset's
generated effects payload has no such field, so the pipeline has no rejection
breakdown. Adding it means carrying the prop through `stg_effects`.

One more mismatch worth owning: the source declares gzipped JSONL, and
Talon.One's exports are CSV. Immaterial to the modelling, but it is the kind of
detail worth conceding before it is pointed out.

---

## 4. From raw files to the 21 models

### From raw files to staging

The step before the first model, and the one most likely to be asked about,
because it is where a pipeline usually breaks.

**What lands.** Gzipped JSONL, hive-partitioned, one directory per stream:

```
data/raw/effects/month=2025-06/tenant=nordwind-retail/part-000.jsonl.gz
                 month=2025-06/tenant=acme-commerce/part-000.jsonl.gz
                 ...
```

288 files across the four streams. One JSON object per line:

```json
{"event_id":"ef-520895","occurred_at":"2025-06-01T12:59:32","tenant":"nordwind-retail",
 "session_id":"sess-nordwind-retail-520894","campaign_id":"nord-seasonal",
 "ruleset_id":"nord-seasonal-rs1","effect_type":"setDiscount","discount_value":15.38,
 "points":0,"currency":"EUR","coupon_code":null}
```

**Nothing is loaded first.** There is no ingestion job and no copy of the raw
data inside the warehouse. `_sources.yml` points DuckDB at the files and it reads
them in place through `read_json`, so `stg_` views query the files directly. The
first time a row is written anywhere is the `fct_` layer.

**Four decisions in the source declaration**, each of which is a way JSONL loads
usually fail:

1. **`format='newline_delimited'` is explicit.** DuckDB's default is `'array'`,
   and auto-detecting format across a glob of gzipped files is exactly where
   these loads break.
2. **Columns are declared, not inferred.** `read_json_auto` samples 20,480
   objects to guess types. Over two million rows with sparse fields — a
   `coupon_code` that is null in most effects, a `reject_reason` present only on
   failures — sampling mistypes them. Declaring every column is faster *and*
   turns the schema into a contract: if the producer changes a type, the build
   fails instead of silently coercing.
3. **`hive_partitioning=true`** yields the `month` column for free from the
   directory name, and lets DuckDB prune whole directories when a query filters
   on it. The `tenant` partition key is shadowed by the `tenant` field inside the
   payload, which is intended, so pruning applies to month only.
4. **`union_by_name=true`** so a stream whose columns arrive in a different order,
   or gain a field mid-history, still unions cleanly.

Two smaller things that are easy to lose an hour to: the source needs
`meta: formatter: oldstyle`, required whenever `external_location` contains
braces — which a `columns={...}` spec always does — and the root path comes from
`env_var('TALON_RAW_ROOT', '../data/raw')`, so the same models resolve whether
dbt is invoked from `dbt/`, from the Makefile, or from a deployed job.

**What each `stg_` model then does.** All four have the same shape, and it is
deliberately narrow:

```sql
with src as (
    select * from {{ source('raw', 'effects') }}
),
deduped as (
    select *, row_number() over (partition by event_id order by occurred_at) as _rn
    from src
)
select
    event_id,
    cast(occurred_at as timestamp)  as fired_at,
    cast(occurred_at as date)       as fired_on,
    coalesce(discount_value, 0.0)   as discount_value,
    effect_type in ('setDiscount', 'acceptCoupon', 'addLoyaltyPoints') as is_monetary,
    ...
from deduped
where _rn = 1
```

Four jobs, and nothing else:

- **Dedupe** on `event_id`, keeping the earliest. At-least-once delivery is the
  normal case for an event pipeline, and a redelivered event would otherwise be
  counted twice in every downstream number. *Honest note: this dataset's
  generator emits no duplicates, so the dedupe currently removes zero rows. It is
  a guard against production behaviour, not something doing visible work here.*
- **Type** — cast the timestamp, and emit a `date` alongside it. Every fact
  aggregates by day and every incremental predicate filters on a date, so
  materialising it once here saves a cast on two million rows repeatedly.
- **Derive the booleans once** — `is_monetary`, `is_redeemed`, `is_server_error`.
  These are definitions, not calculations, and pinning them here means no
  downstream model re-derives one slightly differently.
- **Split signed values** so sums are additive: `points_delta` becomes
  `points_issued` and `points_burned`, because summing a signed column across a
  mixed set of issues and burns answers neither question.

**What staging deliberately does not do:** no joins, no aggregation, no business
logic beyond the above, and no filtering of rows. PII is carried through on
purpose (§3) — the firewall is the `rpt_` boundary, not this one.

**Why views.** The source is files. A staging view is a saved query over them, so
there is no copy to fall out of date and no storage to pay for. It also means
`make build` never has a stale-staging failure mode: the only way to be looking
at old data is if the files themselves are old.

**What is tested here.** 25 of the 67 tests sit on staging: `event_id` unique and
not null on every stream, `accepted_values` on every enum (tenant, effect type,
session state, coupon event, loyalty direction), and the business invariants that
must hold before anything is aggregated — `cart_total >= 0`, `latency_ms > 0`,
`is_server_error = (http_status >= 500)`, and
`not (effect_type = 'rejectCoupon' and discount_value > 0)`, which would
overstate every redemption number downstream if it ever failed.

### Staging (4) — typed, deduped, one row per raw event. Materialised as views.

Every `stg_` model has the same shape: read the source, `row_number()` over
`event_id` ordered by `occurred_at`, keep `_rn = 1`, cast timestamps, and
derive the one or two booleans that downstream logic should not have to
re-derive. Dedupe is at this layer because at-least-once delivery is the normal
case for an event pipeline and every count downstream would otherwise be wrong.

| Model | Grain | Why it exists | Business question |
|---|---|---|---|
| `stg_session_evaluations` | 1 row / cart evaluation | The platform's unit of work. **Carries PII (`profile_email`) on purpose** — the reduction is also a PII firewall, and that claim needs something to firewall. | How much is this account actually using the engine, and how fast is it? |
| `stg_effects` | 1 row / effect returned | Derives `is_monetary` here so materiality is a property of the data, not of a ranker. | What did the engine actually give the shopper? |
| `stg_loyalty_events` | 1 row / points movement | Splits `points_delta` into `points_issued` / `points_burned` so the sums are additive. Also carries PII. | What is the loyalty liability and is it growing? |
| `stg_integration_requests` | 1 row / API request | Derives `is_server_error` (`http_status >= 500`). | Is the integration healthy? |

### Intermediate (3) — joins and business logic. Views. No reduction.

| Model | Grain | Why it exists |
|---|---|---|
| `int_session_campaign_lineage` | 1 row / effect (510,080) | Resolves session → campaign → ruleset → effect and attaches the shopper segment from the session onto the effect. `has_parent_session` is emitted as a column so the orphan test can assert on it. Left join, deliberately: an orphan must survive to be caught, not vanish. |
| `int_coupon_events` | 1 row / coupon effect (115,924) | Projects `acceptCoupon` / `rejectCoupon` out of the lineage model, carrying the shopper segment with them, so the coupon fact never has to join on `coupon_code` to recover it. |
| `int_quarter_calendar` | 1 row / date (546) | Calendar spine over the observed date range, labelling each date with its quarter, quarter start, month start, and **prior quarter label**. Period-over-period is the backbone of a QBR, so it is resolved once instead of re-derived with a self-join in every mart. |

### Marts (10) — the star schema. Tables.

**Dimensions (5), from seeds.** Small, conformed, and the reason the reporting
layer can label an anomaly rather than emit an opaque id.

| Model | Rows | Notes |
|---|---|---|
| `dim_tenant` | 4 | Plan tier, country, currency, entitlement booleans. Entitlements are what make adoption gaps commercially readable. |
| `dim_campaign` | 9 | Name, type, `is_paid_feature`. `is_paid_feature` feeds the salience boost: movement on something the customer pays for outranks movement on something free. |
| `dim_ruleset` | 18 | Ruleset version and activation date, joined to campaign for tenant. Makes "the drop starts at ruleset v2" answerable. |
| `dim_application` | 8 | Channel (web/mobile) and name. Anomalies on an application are otherwise unreadable. |
| `dim_effect_type` | 5 | `is_monetary` and `value_weight` (setDiscount 1.0, acceptCoupon 0.9, addLoyaltyPoints 0.7, rejectCoupon 0.2, showNotification 0.05). **This table is what stops a notification spike outranking a discount collapse.** |

**Facts (5), all daily grain, all incremental.**

All five use `incremental_strategy='delete+insert'` with a three-day lookback
predicate. Not `merge` (needs DuckDB ≥ 1.4.0), not `microbatch` (dbt-duckdb
warns it may not be faster, and it cannot use a `unique_key`). The lookback is
what makes reruns cheap: a nightly full rebuild at this volume is not
affordable, and the brief's 5 GB/month makes that worse, not better.

| Model | Grain | Rows | What it answers |
|---|---|---|---|
| `fct_session_evaluations` | tenant × day × application × segment | 13,104 | Engagement and performance: sessions, distinct profiles, cart value, avg/p95 latency, cancelled sessions. **The 96x collapse — the biggest single reduction in the DAG.** |
| `fct_effects_fired` | tenant × day × campaign × effect type × segment | 27,683 | Value delivered: effects fired, discount value, points awarded, sessions with an effect. |
| `fct_coupon_redemptions` | tenant × day × campaign × segment | 3,276 | Attempts / redemptions / rejections as **components, never a ratio**. Reads `int_coupon_events`, which already carries the segment — no join, and therefore no fan-out. |
| `fct_loyalty_events` | tenant × day | 1,092 | Points issued, burned, net outstanding, distinct members. No segment grain: loyalty events are not attached to a session. |
| `fct_integration_health` | tenant × day × application | 4,368 | Requests, server errors, avg and p95 latency. No segment grain: an API request has no shopper. |

The two facts without a segment grain are the reason `rpt_qbr_overview` needs a
caveat — see §13, Known traps.

### Reporting (4) — QBR-shaped, published as external Parquet.

| Model | Grain | Rows | What it is |
|---|---|---|---|
| `rpt_qbr_overview` | tenant × quarter × segment | 72 | Account-level context: sessions, cart value, latency, API health, loyalty balance, plus prior-quarter sessions and cart value and a `sessions_qoq`. Feeds the wizard's account picker and the usage/health bundles. |
| `rpt_qbr_campaign_performance` | tenant × quarter × campaign × segment | 153 | The campaign story. Effects, discount, points, redemptions and their prior-quarter counterparts, resolved with `lag()` **here, in the warehouse** — so a narrative can never be handed a delta the warehouse did not compute. Rates exposed alongside their components. `full outer join` between effects and coupons so a campaign with coupons but no effects (or vice versa) still produces a row. |
| `rpt_feature_adoption` | tenant × quarter × feature | 120 | Entitlement versus use, over a full cross-join spine so zero-usage is a row. Classifies each cell as `never_used` / `lapsed` / `newly_adopted` / `growing` / `declining` / `steady`, with `is_entitled` derived from `dim_tenant`. |
| `rpt_anomalies` | tenant × week × metric × entity | 154 | Statistically unusual weekly movements. See below. |

#### `rpt_anomalies` in detail

Six metric series are unioned into one long shape (`redemption_rate`,
`discount_value`, `effects_fired`, `sessions_evaluated`, `server_error_rate`,
`net_points_outstanding`), then scored against a **trailing eight-week
baseline, excluding the week under test**, requiring at least six baseline
weeks, and kept where `abs(z_score) >= 2.5`.

Four design decisions worth knowing cold:

1. **Weekly grain, not quarterly.** A one-week incident diluted across thirteen
   weeks disappears. S3 (a 5xx spike lasting one week) is invisible at quarterly
   grain and is z = 92.8 at weekly grain.
2. **The baseline excludes the week under test** (`rows between 8 preceding and
   1 preceding`). Otherwise a spike inflates the baseline it is measured
   against and scores itself down.
3. **Partial weeks at the data boundary are excluded entirely.** A two-day week
   compared against seven-day weeks produces an enormous z-score that is an
   artefact of the cutoff. Left in, these dominate the ranking and bury every
   real finding. `abs(z_score) < 500` is the regression guard.
4. **The model stops at "statistically unusual".** It emits the raw inputs a
   materiality ranker needs — `movement_magnitude` (rate changes scaled by
   volume, so a rate move on 12,000 attempts outranks the same move on 40),
   `affects_revenue`, `is_paid_feature`, `value_weight` — but does not decide
   what is worth discussing. That judgement is business logic, lives in
   `qbr/salience.py`, and can be retuned without a warehouse rebuild.

`quarter_label` is derived from `week_start`, not aggregated from member days:
a week straddling a quarter boundary must land in exactly one quarter, and
`max(quarter_label)` would pick one arbitrarily.

---

## 5. Why `rpt_` materialises as external Parquet

`+materialized: external`, `+format: parquet`, `location` under
`data/serving/`. Everything else is a view or a table inside
`data/warehouse.duckdb`.

**The operational reason.** Cube's DuckDB driver has no read-only mode. If Cube
opened `warehouse.duckdb`, it would hold a write lock, and `dbt build` would
fail while Cube was up. Publishing to Parquet means Cube reads files nothing
else holds, and the warehouse can rebuild while the semantic layer is serving.

**The architectural reason, which is the one to lead with.** Parquet makes the
serving layer a **published contract** rather than a peek into someone else's
database. It is the same boundary you get on Snowflake or BigQuery with a
share or an external table: the consumer sees exactly the four tables you chose
to publish and cannot reach past them into staging, into PII, into anything
unversioned. On this stack it also happens to be 48 KB of columnar files that
anything can read without a warehouse connection.

---

## 6. Could the semantic layer replace `rpt_`?

Worth having a straight answer to, because the honest one is "partly", and
"partly" is more convincing than a blanket defence.

**What Cube could genuinely absorb.** `rpt_qbr_overview` is close to pure
aggregation: sums of sessions, cart value, requests, points, plus two ratios. A
semantic layer defining those measures over `fct_` directly would produce the
same answers, and the pre-aggregation would be a performance choice rather than
a correctness one. Same for most of `rpt_qbr_campaign_performance`'s current-
quarter columns.

**What it could not.** Three things in `rpt_` are not expressible as measures,
and it is worth knowing which:

1. **Window functions.** Every `prior_*` column comes from `lag()` over
   quarter. Cube's measure DSL has no window functions; `compareDateRange`
   works on a time dimension, and `quarter_label` here is a string. Look at
   `cube/model/cubes/campaign_performance.yml`: `prior_redemptions` is declared
   `type: sum` over a column. Cube consumes the prior-quarter value; it cannot
   produce it.
2. **Rows that do not exist in the source.** `rpt_feature_adoption` is a
   deliberate cross join of tenant × quarter × feature so that an entitled,
   never-used feature is a row rather than an absence. A semantic layer
   aggregates rows it is given; it cannot manufacture the missing ones. Signal
   S5 is invisible without this.
3. **The anomaly scoring.** A trailing eight-week z-score that excludes the week
   under test, with partial weeks dropped, is a window over a window. Not a
   measure, at all.

**And two reasons that are not about capability.** First, the boundary is the
security control: `rpt_` is what makes `assert_no_pii_in_rpt` meaningful, and if
Cube read `fct_`/`stg_` directly, the PII firewall has nothing to stand on and
Cube's DuckDB driver takes a write lock on the warehouse file. Second,
testability: `assert_pop_deltas_reconcile` can check a `lag()` that lives in the
warehouse. Computed at query time in Cube, period-over-period is outside dbt's
test surface entirely.

**The line to use.** `rpt_` is not a cache of things Cube could compute. It is
where the logic Cube cannot express lives, and it is the published boundary that
makes the tenant-scoping and PII claims enforceable. The parts that are just
pre-aggregation, mainly the overview model, genuinely are optional, and
collapsing them would be a reasonable simplification on a warehouse with cheap
compute.

---

## 7. How redemption rate is calculated

Worth being exact about, because it is the most-quoted number in the pack and
the easiest to get subtly wrong.

**The definition.** A redemption *attempt* is one coupon effect: the engine
evaluated a code and returned either `acceptCoupon` or `rejectCoupon`. A
*redemption* is an `acceptCoupon`. So:

```
redemption_rate = acceptCoupon / (acceptCoupon + rejectCoupon)
```

It is the share of coupon evaluations the engine accepted. Nothing about baskets
or revenue, which is worth saying plainly before a customer assumes otherwise.

**Where each piece lives.**

1. `int_coupon_events` emits one row per coupon effect with an `is_redeemed`
   boolean (`effect_type = 'acceptCoupon'`).
2. `fct_coupon_redemptions` aggregates to tenant × day × campaign × segment and
   stores the **components**: `redemption_attempts` = `count(*)`,
   `redemptions` = `sum(is_redeemed)`, `rejections` = the complement. A dbt test
   asserts `redemptions + rejections = redemption_attempts`.
3. `rpt_qbr_campaign_performance` rolls those to the quarter and exposes both the
   components and a convenience `redemptions::double / redemption_attempts`.
4. Cube defines the measure over the components, not over the stored column:
   `{redemptions} / NULLIF({redemption_attempts}, 0)`.

**Why the rate is never stored and summed.** Because averaging a rate gives the
wrong answer, and gives it convincingly. Take acme-commerce's Winback campaign
in 2026-Q2 by segment:

| Segment | Redemptions | Attempts | Rate |
|---|---|---|---|
| new | 1,702 | 2,872 | 59.3% |
| returning | 1,668 | 4,226 | 39.5% |
| vip | 813 | 1,413 | 57.5% |
| **Correct total** | **4,183** | **8,511** | **49.1%** |

Averaging the three segment rates gives (59.3 + 39.5 + 57.5) / 3 = **52.1%**.
That is three points too high, because it treats a 1,413-attempt segment as
equal in weight to a 4,226-attempt one. The error is small enough to look
plausible and large enough to change the conversation — 49% and 52% are
different stories about the same quarter. Storing the components and dividing at
the end is what makes any grain, any filter, any segment split come out right
without anyone having to remember this.

The same reasoning drives `api_error_rate` (`server_errors / requests`) and every
other ratio in the pack.

---

## 8. The dbt pipeline: materialisation and the nightly run

The layering is not just naming. Each layer is materialised differently, and the
choices are what make a nightly refresh cheap.

| Layer | Materialisation | Why |
|---|---|---|
| `stg_` | **view** | The source is external files. A staging view is a query over them, so it costs nothing to store and nothing to keep current — there is no copy to go stale. |
| `int_` | **view** | Ephemeral would inline the SQL and save nothing on DuckDB, where storage is free. Views stay inspectable: during a demo you can select from `int_session_campaign_lineage` and show the lineage, which is impossible with ephemeral. |
| `dim_` | **table** | Tiny (44 rows total), joined constantly. Materialise once. |
| `fct_` | **incremental table** | The expensive layer, and the only one where rebuild cost is real. See below. |
| `rpt_` | **external parquet** | The published contract the semantic layer reads (§5). |

### Why the facts are incremental

A full rebuild reads all 2,068,975 events, re-aggregates every day of six
quarters, and rewrites five fact tables. Doing that nightly means paying every
night for history that has not changed since the night before.

All five `fct_` models are therefore configured:

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'occurred_on', 'campaign_id', 'profile_segment']
) }}
```

with a matching predicate in the body:

```sql
{% if is_incremental() %}
where occurred_on >= (
    select coalesce(max(occurred_on), '1900-01-01') - interval 3 day from {{ this }}
)
{% endif %}
```

Three decisions in there worth being able to defend:

**`delete+insert`, not `merge`.** `merge` needs DuckDB ≥ 1.4.0. On a warehouse
that supports it, `merge` is the better choice; the strategy is a one-line
config change, and nothing else in the model moves.

**Not `microbatch`.** dbt-duckdb warns it may not be faster here, and it cannot
use a `unique_key`, which is what makes the reload idempotent.

**A three-day lookback, not one.** Events arrive late — a session closes after
midnight, an integration retries, a batch lands behind schedule. Rebuilding only
"yesterday" silently loses those. Re-deleting and re-inserting the trailing three
days costs almost nothing and makes the pipeline self-healing: any day that was
wrong becomes right the next time the model runs, without an intervention.

Together with `unique_key`, the run is **idempotent**. Running it twice produces
the same table, which is the property that lets you rerun a failed nightly job
without thinking about what it already did.

### What the nightly run actually costs, measured

Both timings are on this laptop, against the local DuckDB file, including all 93
tests:

| Run | Wall clock |
|---|---|
| `dbt build --full-refresh` | **4m 38s** |
| `dbt build` (incremental) | **2m 23s** |

**Be honest about that ratio.** It is 1.9x, not the 50x the funnel might lead
someone to expect, and the reason is specific to this build: `stg_` is a set of
views over gzipped JSON, so *every* run still decompresses and parses all
2,068,975 raw events before the incremental predicate can filter anything. The
lookback saves the aggregation and the writes, not the scan.

On a real warehouse this inverts. Raw events land as partitioned tables, not as
files re-parsed on every read, so the incremental predicate prunes partitions at
the source and the nightly run touches three days of data rather than six
quarters of it. The three-day lookback is written for that world; here it is
demonstrating a pattern rather than showing its full payoff, and claiming
otherwise would be easy to catch.

What is already free is the top of the DAG: `rpt_` rebuilds in full every run
because it is 496 rows, and dimensions because they are 44.

The asymmetry is the point: **the expensive layer is touched incrementally and
the cheap layer is rebuilt from scratch.** Nobody has to reason about
incremental correctness in the reporting models, where the window functions and
the period-over-period logic live and where a partial rebuild would be genuinely
hard to get right. They are small enough to always rebuild, and they are small
enough *because* of the reduction that happens below them.

That is the same argument as the funnel, one layer down: reduce early, and every
decision after it gets cheaper and simpler.

---

## 9. Anomaly detection: the z-score actually applied

`rpt_anomalies` computes a **rolling, trailing, per-series z-score**. Not a
global one. The distinction is the whole design.

### The series

Six metrics are unioned into one long shape, each contributing rows of
`(tenant_id, week_start, metric_name, entity_type, entity_id, metric_value,
volume, affects_revenue)`:

| Metric | Entity | What moves |
|---|---|---|
| `redemption_rate` | campaign | coupons accepted vs evaluated |
| `discount_value` | campaign | money discounted |
| `effects_fired` | effect type | volume of one effect kind |
| `sessions_evaluated` | tenant | engine workload |
| `server_error_rate` | application | 5xx share of requests |
| `net_points_outstanding` | tenant | loyalty liability |

Each series is partitioned by `(tenant_id, metric_name, entity_id)`. A campaign
is only ever compared against its own history, never against another campaign or
another account.

### The window

```sql
avg(metric_value)         over w  as baseline_mean,
stddev_samp(metric_value) over w  as baseline_sd,
count(*)                  over w  as baseline_weeks
window w as (
    partition by tenant_id, metric_name, entity_id
    order by week_start
    rows between 8 preceding and 1 preceding
)
```

Then:

```
z_score         = (metric_value - baseline_mean) / baseline_sd
relative_change = (metric_value - baseline_mean) / |baseline_mean|
```

with `z_score = 0` when `baseline_sd` is null or zero, a `baseline_weeks >= 6`
requirement, and a final `abs(z_score) >= 2.5` filter.

### Four choices, and the business reason for each

**Weekly grain, not quarterly.** A QBR is quarterly, so the instinct is to detect
quarterly. That instinct is wrong: a one-week incident averaged across thirteen
weeks disappears. Nordwind's mobile 5xx rate hit 20.3% for the week of 11 May
against a 0.6% baseline — z = 92.8 weekly, and invisible quarterly. For a CSM
that is the difference between walking into a review already knowing about the
customer's worst week and being told about it.

**`rows between 8 preceding and 1 preceding` — the current week is excluded.**
If the week under test were in its own baseline it would drag the mean toward
itself and shrink its own z-score. The worse the incident, the more it would
hide. Excluding it means the question is always "how does this week compare with
the eight before it", which is the question a human would ask.

**Eight weeks, minimum six.** Two months is long enough to establish a normal
range and short enough to follow a business that changes. Below six weeks there
is not enough history for a standard deviation to mean anything, so those rows
are dropped rather than reported with false confidence. `stddev_samp` (n−1) is
used rather than population sd, because eight weeks is a sample of the account's
behaviour, not the whole of it.

**Partial weeks at the data boundary are excluded entirely.** A two-day week
compared against seven-day weeks produces an enormous z-score that is purely an
artefact of where the data was cut. Left in, these dominate the ranking and bury
every real finding. `abs(z_score) < 500` is the test that keeps this fixed.

### What the model deliberately does not do

It stops at "statistically unusual", and the z-score it computes is an internal
nomination signal: it never reaches the customer-facing pack, which shows the
observed value, the baseline and the salience ranking only. It also emits the raw
inputs a materiality ranker needs — `movement_magnitude` (for rate metrics, `|value − baseline| ×
volume`, so a rate move on 12,000 attempts outranks the same move on 40),
`affects_revenue`, `is_paid_feature`, `value_weight` — but it does not decide
what is worth discussing. That is business judgement, and it lives one layer up.

---

## 10. Salience: turning "unusual" into "worth saying"

`qbr/salience.py`. About forty lines, deliberately outside the warehouse.

### What it is, in one paragraph

Salience is a **triage score**. Every finding that survives anomaly detection
gets one number answering a single question: *how much of a thirty-minute
customer conversation does this deserve?* It is not a statistic, not a
probability, and not a percentage of anything. It is a weighted opinion,
expressed as a number so that findings can be sorted and a line can be drawn.

The z-score and the salience score answer different questions, and the whole
design rests on keeping them apart:

| | Question | Computed | Can it tell you… |
|---|---|---|---|
| **z-score** | Is this unusual for this account? | In SQL, from history | …whether the number moved. Nothing about whether anyone cares. |
| **salience** | Is this worth the customer's time? | In Python, from business weights | …whether to put it on a slide. |

A z-score cannot rank a notification spike against a discount collapse, because
it has no idea one moves money and the other does not. That information is not
in the statistics, so it cannot be recovered from them. It has to be supplied,
by a human, once — which is what this module is.

### The six factors

The score starts at a base worth and is multiplied by factors, each answering
one question:

| Factor | The question it answers | Range | Effect |
|---|---|---|---|
| `METRIC_WEIGHT` | What kind of conversation is this? | 0.35–1.00 | Base. A redemption rate is a revenue conversation (1.00); an effect count is barely one (0.45). |
| `value_weight` | What is this effect type worth? | 0.05–1.00 | From `dim_effect_type`, applied **only** when the thing that moved is an effect type. `setDiscount` 1.0, `showNotification` **0.05**. |
| `relative_move` | How big is it, against its own baseline? | 0–1 | `rel / (rel + 1)`. A doubling scores 0.5, a tenfold 0.91. |
| `volume_confidence` | Is there enough data to believe it? | 0.4–1.0 | `min(1, volume / 200)`. A rate over forty attempts is noise wearing a z-score. |
| `PAID_FEATURE_BOOST` | Do they pay for this? | ×1.35 | Movement on a paid entitlement is a commercial conversation. |
| `REVENUE_BOOST` | Does it touch money? | ×1.20 | |
| `DETERIORATION_BOOST` | Is it getting worse? | ×1.25 | Things going wrong beat things going right. Direction is metric-specific: more errors is bad, more sessions is good. |

**Why multiply rather than add.** Multiplication makes this an AND, not an OR. A
finding has to be about something that matters **and** be large **and** be
trustworthy. Any one factor near zero kills the score no matter how strong the
others are — which is exactly the behaviour you want from `showNotification`'s
0.05 weight. Adding would let a huge, well-evidenced movement on a worthless
metric accumulate its way onto the agenda. It cannot, here.

Two constants finish it:

- `SALIENCE_FLOOR = 0.15` — below this, a movement is not worth a slide however
  unusual it is.
- `DEFAULT_TOP_N = 5` — a QBR that raises fifteen things has raised nothing.

### Read back in words

**Winback Reactivation's redemption rate, acme-commerce, 2026-Q2 → 0.3594.**

Start at 1.00: a redemption rate is the most commercially loaded thing measured.
Keep it at 1.00 for effect weight, because a campaign is not an effect type. The
rate fell 21.6% against its own baseline, which is a real move but not a
catastrophe, so it scales down to 0.18. There were 620 attempts behind it, well
over the 200 needed for full confidence, so no damping. Then three boosts apply:
the customer pays for this campaign, it touches revenue, and it is getting worse.
**0.36.** Above the floor, and it leads the pack.

**`rejectCoupon` volume, same account, same quarter → 0.0240.**

Start at 0.45: a count of effects fired is a weak conversation to begin with.
Multiply by 0.20, because `rejectCoupon` is what the engine returns when it turns
a coupon down, and the platform itself rates it near-worthless. It rose 36.3%,
scaling to 0.27. No boosts: nobody pays for it specifically, and more rejections
is not obviously deterioration in a way the direction map recognises. **0.024.**
Six times below the floor. Dropped.

Two movements of near-identical statistical significance — z = −4.06 and
z = +3.55 — separated by a factor of **fifteen**, entirely because of two numbers
a human chose.

### The shortest way to explain it: it is an ICE score

For anyone who will not read the Python, this is the fastest framing. ICE
(Impact × Confidence × Ease) is a standard product prioritisation score, and
salience is the same shape:

| ICE | Salience |
|---|---|
| **Impact** | `METRIC_WEIGHT` × `value_weight` × `relative_move` — what kind of thing moved, what it is worth, how far it moved |
| **Confidence** | `volume_confidence` — the same idea exactly: enough observations to believe it? |
| **Ease** | *nothing* |

Two differences worth being precise about. ICE scores are assigned by a human per
item; here the factors are computed from each row and the human sets the weights
**once**, which is what lets it run across every finding and every account
without anyone scoring anything. And ICE ranks candidate *actions*, whereas this
ranks *observations*.

**The absent Ease term is deliberate, not an oversight.** Salience answers "what
deserves the customer's attention", not "what should we do about it". For an
agenda those come apart: being hard to fix is not a reason to withhold from a
customer that their error rate tripled — if anything it is a reason to raise it
sooner. But if this ever moves from surfacing findings to recommending actions,
cost has to enter the score, and that is the line where this design stops being
sufficient.

### What the number does and does not mean

- **It is ordinal, not absolute.** 0.36 does not mean 36% of anything. Only the
  ordering and the distance between scores carry meaning. (In the rendered pack
  it is shown ×100 as a 0–100 index, purely so one decimal place stays readable.)
- **It is comparable within a pack, and roughly across packs** for the same
  metrics — but it is not a KPI, and nothing should ever be reported as "our
  average salience improved".
- **It can exceed 1.** Brightline's web error spike scores 1.09: full base
  weight, a 3.2x relative move, revenue and deterioration boosts stacked. The
  scale has no ceiling by design.
- **It is an opinion, and it is meant to be argued with.** That is the point of
  putting it in forty lines of readable Python instead of burying it in SQL or in
  a prompt. If RevOps thinks reliability should outrank discount volume, that is
  a conversation about one constant, changed in one line, with no warehouse
  rebuild and no model retraining.

### Why this matters to Talon.One specifically

Their product is a rules engine that fires effects. Some effects move money and
some are messages, and the cheap ones are always the most numerous —
`showNotification` is the highest-volume effect in this dataset by a wide margin.

Any analytics built on effect volume will therefore keep finding that
notifications moved the most. If the ranking is statistical, **every automated
review leads with notifications, forever.** The fix is not better statistics. It
is one column in a dimension table saying a notification is worth 0.05 of a
discount, and a ranker that reads it.

The pack ships the suppressed list alongside the surfaced one for the same
reason: being able to show a reviewer the significant movement the system
deliberately dropped, and the score that dropped it, is the argument that the
ranking is doing real work rather than quietly hiding things.

---

## 11. The five singular tests, and what each defends

Alongside 62 generic tests (`unique`, `not_null`, `accepted_values`,
`relationships`, and the `expression_is_true` macro), five singular tests carry
the load. 67 data tests total.

| Test | Defends against | Failure means |
|---|---|---|
| `assert_no_pii_in_rpt` | The design doc's PII-firewall claim being decorative. Inspects `information_schema.columns` for `main_reporting` and fails on any column named `profile_id`, `profile_email`, `email`, `coupon_code`, `session_id`, `cart_items`. | Someone added a personal or session-level identifier to a published model. Breaks the build rather than the customer's trust. **It checks column names, not values** — the honest limit, worth stating before it is asked. |
| `assert_reduction_ratio` | The funnel being an assertion. Sums the rows of all four `rpt_` models and fails above `max_rpt_rows`. | The serving layer grew past the point where the LLM payload assumption holds. |
| `assert_pop_deltas_reconcile` | A silently wrong `lag()`. Recomputes the prior quarter by an independent self-join over a deduplicated, row-numbered quarter list and fails on disagreement. | Every "down 22% on last quarter" in the narrative is wrong while still reading plausibly. This is the one whose failure mode is invisible without a test. |
| `assert_coupon_facts_do_not_fan_out` | A join on `coupon_code` reappearing between the effects stream and the coupon fact (§13). Asserts `sum(redemption_attempts)` in `fct_coupon_redemptions` equals the count of `acceptCoupon` + `rejectCoupon` rows in `stg_effects`. | Coupon counts are being multiplied. The failure is quiet without this test, because the rate stays correct while the counts inflate. |
| `assert_no_orphan_effects` | A broken lineage join. Fails on any row in `int_session_campaign_lineage` with `has_parent_session = false`. | Shopper segment travels from session to effect; an orphan silently corrupts every per-segment number in the pack. |

Of the generic tests, the ones that are business rules rather than hygiene:
`redemptions + rejections = redemption_attempts`,
`net_points_outstanding = points_issued - points_burned`,
`not (effect_type = 'rejectCoupon' and discount_value > 0)`,
`is_redeemed = (effect_type = 'acceptCoupon')`,
`distinct_profiles <= sessions_evaluated`,
`redemption_rate between 0 and 1`.

---

## 12. The six planted signals

Documented in [`SIGNALS.md`](SIGNALS.md) at the task 2 root, tagged `S1`..`S6`
in `generate/world.py` at the function that makes each true. Uniformly random
data would make the demo worthless: a tool for finding things worth discussing
cannot be shown to work if nothing is worth discussing.

| id | Account | Story | Surfaces in | Verified |
|----|---------|-------|-------------|----------|
| S1 | acme-commerce | Winback Reactivation redemption rate collapses in 2026-Q2 | `rpt_qbr_campaign_performance` (PoP), ranked #1 in `rpt_anomalies` | 62.0% (2026-Q1) → 49.1% (2026-Q2), a **20.7% relative fall**. Anomaly at week 2026-04-06, z = -4.06. |
| S2 | fastcart | Points Launch ramps `addLoyaltyPoints` from zero | `rpt_feature_adoption` | `never_used` ×3 quarters → `newly_adopted` (452, 2025-Q4) → `growing` (1,885) → `growing` (3,657). |
| S3 | nordwind-retail | Mobile 5xx rate spikes for one week | `rpt_anomalies`, top salience | Week 2026-05-11: 20.25% against a 0.55% baseline, **z = 92.8**. Next-highest server-error z anywhere is 6.6. |
| S4 | brightline-grocers | Aisle Reminder notification volume triples | Detected, then **deliberately suppressed** | Week 2026-03-30, z = 24.6 — genuinely significant, worth nothing. |
| S5 | nordwind-retail | Entitled to loyalty, fires zero loyalty events, ever | `rpt_feature_adoption` as `never_used` across all six quarters with `is_entitled = true` | Confirmed: `addLoyaltyPoints` usage 0 in every quarter. |
| S6 | acme-commerce | Points issued outrun points burned, quarter after quarter | Rising `net_points_outstanding` in `fct_loyalty_events` / `rpt_qbr_overview` | -79,466 (2025-Q1) → +182,373 (2026-Q2). No single quarter alarming; the trend is the finding. |

### The two suppressions, and why they are the strongest argument in the pack

**S4** is the headline. A notification counter triples with z = 24.6. It is
statistically undeniable and commercially worthless. A system that ranks by
z-score leads the QBR with it. This one detects it, scores it at the bottom,
drops it, and can show its reasoning.

The acme-commerce pack makes the same point at closer range. In 2026-Q2:

| Finding | z | Relative change | Paid feature | Outcome |
|---|---|---|---|---|
| Winback redemption rate | **-4.06** | -21.6% | yes | surfaced |
| `rejectCoupon` volume | **+3.55** | +36.3% | no | dropped |

Comparable statistical significance, opposite decisions. That gap is produced
entirely by the ranking layer, which is the argument that it earns its place.
(Salience scores are recomputed per run by `qbr/salience.py`; the pack is the
place to read them, not this table.) Deterministic detection in SQL, business judgement in a tunable Python
module, language in the LLM, and nothing crossing over.

**S5** is the other kind of silence: a signal that only exists as an absence. It
is why `rpt_feature_adoption` is built over a full spine — a gap has to be a row
before anyone can notice it.

---

## 13. Known traps in this DAG

Things worth knowing before someone finds them.

**`rpt_qbr_overview` fans tenant-grain facts across segments.** Its grain is
tenant × quarter × segment, but integration health and loyalty have no segment
grain, so those columns are joined on tenant × quarter and repeated across all
three segments. Summing `points_issued` or `api_requests` from this model
without a segment filter triples them. Verified: `sum(points_issued)` for
acme-commerce 2026-Q2 reads 1,323,036 from `rpt_qbr_overview` against 441,012
from `fct_loyalty_events`, which is the true figure.

The ratio measures are unaffected in different ways: `api_error_rate` is safe
(numerator and denominator scale together), `net_points_outstanding` is not (a
difference, so it scales too).

`account_overview.yml` in Cube declares `points_issued`, `points_burned`,
`api_requests` and `api_server_errors` as `type: sum`, so querying them at
tenant × quarter grain returns 3x the truth. Fixes: query them from a
segment-neutral cube, divide by the segment count, or split the tenant-grain
columns into their own `rpt_` model.
This bites the first usage or health bundle that queries them; the three built
sections (`campaign_performance`, `anomalies`, `feature_adoption`) do not.

**Sessions evaluated includes cancelled sessions; Talon.One's own analytics
excludes them.** The platform documents four customer-session states — `open`,
`closed`, `cancelled`, `partially returned` — and factors only `closed` and
partially returned into campaign analytics. This build models two states
(`stg_session_evaluations` asserts `accepted_values: ['closed', 'cancelled']`)
and `fct_session_evaluations.sessions_evaluated` counts both, with
`cancelled_sessions` broken out alongside it. So the headline session number in
`rpt_qbr_overview`, and the `sessions_evaluated` series feeding `rpt_anomalies`,
will not tie out against what the customer sees on their own Campaign Analytics
screen.

There is a good answer, and it has to be given deliberately rather than
discovered: "sessions evaluated" here is an **engine workload** measure — every
evaluation consumes an API call and costs money whatever the cart does
afterwards — which is a different question from "sessions that counted toward
campaign performance". Both are legitimate; they are not interchangeable, and
the column name does not currently say which one it is. The cheap fix is to
publish both, `sessions_evaluated` and a `sessions_closed` that matches the
platform's definition, and let the QBR quote the one that fits the sentence.
Publishing both — `sessions_evaluated` and a `sessions_closed` matching the
platform's definition — would let a QBR quote whichever fits the sentence.

**`value_weight` on campaign-entity anomalies is the coalesce default.**
`rpt_anomalies` joins `dim_effect_type` on `entity_id`, which only matches when
the entity *is* an effect type. Campaign and application rows fall through to
`coalesce(..., 0.5)`. That is intentional, not a bug, but it means
`value_weight` is not a campaign-level property and should not be read as one.

**`assert_no_pii_in_rpt` checks names, not values.** A column called
`entity_label` holding an email address would pass. Naming discipline is the
control; the test enforces the discipline, not the outcome.

**`coupon_code` is not a join key.** 115,924 coupon effects carry 84,317
distinct codes, so anything joining on it multiplies rows. The coupon fact
avoids the problem by taking its segment from the lineage projection instead of
looking it up, and `assert_coupon_facts_do_not_fan_out` fails the build if a
join is ever reintroduced. Worth knowing because the failure is quiet: counts
inflate while the *rate* stays correct, since numerator and denominator inflate
together.

**The lineage join is a left join by design.** Orphan effects survive so
`assert_no_orphan_effects` can catch them. An inner join would make the test
pass by deleting its own evidence.

**`SIGNALS.md` lives at the task 2 root**, not in `generate/`. The
`generate/world.py` file is where the tags are.

---

## 14. Reproducing every number in this file

```bash
duckdb data/warehouse.duckdb -c "select count(*) from main_staging.stg_session_evaluations"
```

```bash
duckdb -c "select count(*) from read_parquet('data/serving/rpt_anomalies.parquet')"
```

S1, the redemption collapse:

```bash
duckdb -c "select quarter_label, sum(redemptions) red, sum(redemption_attempts) att, round(100.0*sum(redemptions)/sum(redemption_attempts),1) pct from read_parquet('data/serving/rpt_qbr_campaign_performance.parquet') where campaign_id='acme-winback' group by 1 order by 1"
```

S3, the integration spike:

```bash
duckdb -c "select entity_label, week_start, round(z_score,1) z, round(metric_value,4) val, round(baseline_mean,4) baseline from read_parquet('data/serving/rpt_anomalies.parquet') where metric_name='server_error_rate' order by abs(z_score) desc limit 3"
```

The S4 suppression pair:

```bash
duckdb -c "select entity_label, metric_name, round(z_score,2) z, round(relative_change,3) rel, is_paid_feature from read_parquet('data/serving/rpt_anomalies.parquet') where tenant_id='acme-commerce' and quarter_label='2026-Q2' order by abs(z_score) desc limit 2"
```
