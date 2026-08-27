# Planted signals

Uniformly random mock data makes a demo worthless: nothing is ever worth
discussing, so a tool for finding things worth discussing cannot be shown to
work. `generate/world.py` plants six specific stories. Each is tagged `S1`..`S6`
in that file, at the function that makes it true.

This file exists so the presenter can point at each one and say what the
pipeline should do with it, including the two cases where the correct behaviour
is to say nothing.

| id | Account | Story | Where it should surface |
|----|---------|-------|-------------------------|
| S1 | acme-commerce | Winback Reactivation coupon redemption rate falls ~21% in 2026-Q2, concentrated in `returning` shoppers | `campaign_performance` PoP, and ranked #1 in `anomalies` |
| S2 | fastcart | Points Launch ramps `addLoyaltyPoints` from zero in 2025-Q4 to material volume by 2026-Q2 | `feature_adoption` as `newly_adopted` then `growing` |
| S3 | nordwind-retail | Mobile app 5xx error rate jumps from 0.6% to 20% for the week of 2026-05-11 | Ranked #1 in `anomalies`, top salience |
| S4 | brightline-grocers | Aisle Reminder notification volume triples in 2026-Q2 | Detected, then **deliberately suppressed** |
| S5 | nordwind-retail | Entitled to loyalty, fires zero loyalty events, ever | `expansion_signals`, and a zeroed loyalty KPI |
| S6 | acme-commerce | Loyalty points issued outrun points burned, quarter after quarter | Rising `net_points_outstanding` |

## What each one is for

**S1 is the accuracy check.** The design document and the published architecture
artifact both quote the sentence "coupon redemption on the winback campaign fell
22% against the previous quarter". That sentence was written before the data
existed. It is now measurably true: 62.0% in 2026-Q1 against 49.1% in 2026-Q2, a
relative fall of 20.7%. The claim in the document and the number in the
warehouse agree because the data was built to make them agree, which is worth
saying out loud rather than implying.

(These figures moved slightly when `stg_coupon_events` was replaced by
`int_coupon_events`, a projection of the effects stream. The old coupon fact
joined lineage on `coupon_code`, which is not unique, and inflated every
absolute coupon count by about half while leaving the rate intact. 62.0 → 49.1
are the un-inflated numbers. See `DAG_GUIDE.md` §3.)

**S2 is the adoption story.** A feature that did not exist, then did. It gives
`rpt_feature_adoption` a real state transition to classify rather than a static
list.

**S3 is the high-salience incident.** A short, sharp, customer-visible
reliability failure. It is the reason anomaly detection runs at weekly grain: at
quarterly grain one bad week is diluted across thirteen and disappears entirely.

**S4 is the most important one.** A notification counter triples. It is
genuinely statistically significant, and it is worth nothing to anybody. A
system that ranks by z-score leads the QBR with it. This system detects it, scores
it at the bottom of the list, and drops it, and can show you why. In the
acme-commerce pack the same point lands even harder: `rejectCoupon` volume moves
with z = +3.55 and is dropped, while the winback redemption collapse moves with
z = -4.06 and surfaces. **Comparable statistical significance, opposite
decisions.** That is the argument that the ranking layer
earns its place.

**S5 is the commercial opening.** An entitlement with no usage is not a usage
statistic, it is a conversation. It is also why `rpt_feature_adoption` is built
against a full spine of tenant × quarter × feature: a gap has to be a row before
anyone can notice it.

**S6 is the slow one.** No single quarter looks alarming; the trend is the
finding. It is there so the pack has something that only period-over-period
comparison can see.

## Verifying them

```bash
make generate && make build
```

Then, for the two that a reviewer is most likely to want to see for themselves:

```bash
duckdb data/warehouse.duckdb -c "select quarter_label, sum(redemptions) as red, sum(redemption_attempts) as att, round(100.0*sum(redemptions)/sum(redemption_attempts),1) as pct from main_reporting.rpt_qbr_campaign_performance where campaign_id='acme-winback' group by 1 order by 1"
```

```bash
duckdb -c "select entity_label, week_start, round(z_score,1) as z, round(metric_value,4) as val, round(baseline_mean,4) as baseline from read_parquet('data/serving/rpt_anomalies.parquet') where metric_name='server_error_rate' order by abs(z_score) desc limit 3"
```
