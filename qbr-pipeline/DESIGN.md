# QBR Pipeline - Design

**Design principle:** the warehouse does the reduction, the LLM does the language. Every number a CSM sees is computed deterministically in SQL. The LLM never counts, never aggregates, never detects. It selects, ranks context, and writes.

---

## 1. The reduction funnel

The task is a volume problem before it is an AI problem. These are **measured**, not estimated — counts from an actual build in `task2/`, which generates 2.18M events across four accounts and six quarters. The DAG reads 2.07M of them: the generator also emits a coupon feed, which the pipeline no longer consumes because Talon.One does not export one (a coupon's outcome is an effect).

| Stage | Format | Volume | Cumulative reduction |
|---|---|---|---|
| Raw logs landed | gzipped JSONL | 2,068,975 events, 53 MB gz (~380 MB raw) | 1x |
| `stg_` typed + deduped | views over Parquet | same rows | 1x |
| `int_` lineage + joins | views | no reduction, by design | 1x |
| `dim_` / `fct_` daily grain | incremental tables | 49,523 rows | 42x |
| `rpt_` QBR-shaped, published | Parquet | **496 rows, 48 KB** | **4,171x** |
| Payload sent to LLM | JSON, top-N ranked | **~2,153 tokens** | **~46,000x** on tokens |

At the 5 GB monthly volume the brief describes, the ratio is larger still.

`int_` reduces nothing, deliberately: it's the logic layer (session → campaign → ruleset → effect lineage), materialised as views so it adds no storage or volume. `stg_` compacts the format, `fct_`/`rpt_` collapse the grain — separating the two keeps the aggregation logic readable and testable.

At Sonnet 5 pricing ($3 / $15 per million tokens in/out), a QBR pack costs a few cents; 200 accounts a quarter, a handful of dollars. The LLM is a rounding error, warehouse compute is the real cost line — which is why the funnel is enforced by a dbt test (`assert_reduction_ratio.sql`), not left as an assumption.

---

## 2. Pipeline stages and tools

**Ingest.** Session and integration logs land append-only in object storage (S3/GCS), partitioned by `date` / `tenant`. Compaction from raw JSON to Parquet at landing is the cheapest volume win available: columnar layout plus column pruning cuts scan cost before any modelling happens. Retention: hot 90 days in the warehouse, colder history as external Parquet.

**Transform: dbt DAG in the warehouse (Snowflake/BigQuery).** Standard medallion layering, mapped to Talon.One's actual domain objects rather than abstract "events":

- `stg_` (4 models) — typed, deduped, one row per raw event: `stg_session_evaluations`, `stg_effects`, `stg_loyalty_events`, `stg_integration_requests`. There is deliberately no `stg_coupon_events`: Talon.One has no coupon export, and a coupon's outcome is an effect.
- `int_` (3 models) — joins and business logic. Sessions are already first-class objects in the platform, so `int_session_campaign_lineage` resolves session → campaign → ruleset → effect lineage rather than reconstructing sessions from clickstream. `int_coupon_events` projects the coupon lifecycle (`acceptCoupon` / `rejectCoupon`) out of that lineage.
- `dim_` / `fct_` (10 models) — `dim_tenant`, `dim_campaign`, `dim_ruleset`, `dim_application`, `dim_effect_type`; `fct_session_evaluations`, `fct_effects_fired`, `fct_coupon_redemptions`, `fct_loyalty_events`, `fct_integration_health`. `fct_` models are **incremental**, not full-refresh — a nightly full rebuild is not affordable at this volume.
- `rpt_` (4 models) — QBR-shaped: `rpt_qbr_overview`, `rpt_qbr_campaign_performance`, `rpt_feature_adoption`, `rpt_anomalies`. Pre-aggregated by account / segment / quarter, with period-over-period deltas and anomaly flags.

**Cadence: nightly batch. No streaming.** A QBR is quarterly. Building real-time infra for a quarterly artefact is spending money to solve a problem nobody has.

**Semantic layer: Cube.dev, self-hosted.** Every metric is defined once — name, calculation, grain, valid dimensions — as the contract between the data platform and the AI layer. Base cubes are `public: false`; only views are queryable, and a `query_rewrite` hook appends server-side tenant scoping the caller cannot opt out of. `rpt_` publishes as Parquet, which Cube reads directly (see appendix for why, and for the Cube-vs-MetricFlow reasoning).

---

## 3. Where the LLM sits, and where it does not

**Does not: anomaly detection.** Anomalies are computed in `rpt_` with deterministic statistics (rolling z-score, threshold rules, dbt tests). This is cheap, auditable, reproducible, and scales to 20M events. An LLM scanning data hunting for anomalies is the expensive, non-deterministic, unverifiable version of a solved problem.

**Does not: aggregation, parsing, or computing any figure.** SQL's job.

**Does not: writing free SQL against production tables.** It queries the semantic layer only, read-only credentials, row-level tenant scoping so a query cannot cross accounts.

**Does: select what to show.** The QBR wizard is *deterministic by default*. The CSM picks account, period and segment as parameters; the LLM selects from a small registry of pre-defined QBR section bundles (adoption, campaign performance, anomalies, integration health). Free-form natural-language query is the escape hatch, not the primary path. Text-to-SQL is the least reliable component in any system of this shape, so it gets the smallest possible surface area.

**Does: turn structured results into narrative.** "Coupon redemption on the Winback Reactivation campaign fell 22% against last quarter, concentrated in returning shoppers" is what a CSM can present. A table of numbers is not.

**Does: explain a movement using what the account team already knows.** A QBR is a conversation, not a numbers dump. Why coupon redemption fell is in a Gong call or a Salesforce note, never in a fact table. A retrieval layer (`qbr/retrieval.py`, keyword search over a mock corpus of calls, CSM notes, support cases and last quarter's action items) pulls the passages bearing on the movements the ranking step already surfaced, and the narrative cites them. Retrieval is anomaly-driven rather than free search: salience has decided what is material, and "search for whatever seems interesting" has no correct answer to check against.

**Does not: derive a figure from that context.** The governing rule is that **context explains a number, never produces one**. A call summary saying "about forty thousand redemptions" is a source for a reason, not for a figure. Every number still validates against the semantic-layer payload alone.

### Three controls that make this defensible

**Salience ranking, between `rpt_` and the LLM.** The task asks for anomalies *worth discussing with the customer*. A z-score gives 40 flags, most of them noise. A ranking step weights each flagged anomaly by business materiality: revenue impact, tie to a contracted goal, adoption of a paid feature, direction of travel. Only the top 3 to 5 reach the LLM. Statistical significance is not the same thing as being worth 90 seconds of a QBR.

In the working implementation this is measurable. For one account the ranker was handed eight flagged movements: a `rejectCoupon` volume change at z = +3.6 was dropped, and a coupon redemption collapse at z = -3.6 surfaced. Identical statistical significance, opposite decisions, because only one of them costs the customer money.

**Grounding check.** Every figure in the generated narrative must exist in the input payload. A deterministic post-check validates the numbers in the output against the structured input and rejects any that do not match. The LLM cannot invent a number because it is never asked to produce one, and the check enforces it.

**Retrieval boundary.** Free text introduces failure modes a numeric check cannot see: a fabricated quotation, a citation pointing at a document that was never retrieved, or a sentence lifted from an internal note. Three controls answer them. Documents marked `visibility: internal` (renewal strategy, pricing headroom) are filtered *before* the model is given anything, because filtering afterwards means it has already read them. Every `[C1]` citation must resolve to something actually retrieved. Every quotation must appear verbatim in its snippet. The rendered pack publishes what was withheld, so a reader can see the filter ran.

---

## 4. PII, and CSM-facing output

**Two data planes, two governance regimes.** The warehouse plane is aggregate by construction. The account-context plane is free text written by humans and is governed by classification instead: every document declares `customer_safe` or `internal`, tenant isolation is a filter rather than a ranking signal, and both properties are enforced by tests rather than by prompt instructions.

**PII firewall.** Raw logs carry customer profile attributes, identifiers and cart contents. By `rpt_` the data is aggregate and carries no individual identity — a governance property that falls out of the architecture for free, enforced by `assert_no_pii_in_rpt`. Combined with tenant-scoped access at the semantic layer, no cross-account leakage path exists.

**Generated on demand**, when a CSM asks, not pre-built on a schedule — most accounts don't have a review in a given window, and a pre-built pack is stale by the meeting. A human reviews every pack before a customer sees it, at generation time rather than in a batch queue. Flow: CSM opens the pack → reviews narrative plus charts → adjusts scope or asks a follow-up (re-queries the semantic layer) → exports to deck or PDF. (Export tooling and a CSM-edit feedback loop are scoped but not built — see appendix.)

---

## 5. How the layers interact

| Layer | Component | Role |
|---|---|---|
| Storage | Object store | Raw log landing, append-only, Parquet compaction, cold tier |
| Storage | Warehouse | `stg_` → `rpt_`, dbt-managed, incremental |
| Processing | dbt | Reduction, lineage, aggregation, anomaly flags, tests |
| Processing | Salience ranker | Anomaly materiality ranking, top-N selection |
| Contract | Semantic layer | Metric definitions, query compilation, tenant-scoped access boundary |
| AI | LLM | Section selection, narrative generation, follow-up interpretation |
| Guardrail | Grounding check | Validates every figure in output against structured input |
| Output | QBR wizard | Scoping, review, edit, follow-up |
| Output | Export | Narrative plus charts to deck or PDF |

---

## AI tool usage disclosure

I used Claude (via Claude Code) as a critic, not an author. I brought the architecture, medallion dbt DAG, semantic layer as the AI/data contract, LLM confined to language, from prior hands-on dbt and warehouse work. Claude's contribution was adversarial review: it pushed me to quantify the reduction funnel rather than assert it, flagged that my first draft let the LLM compose queries too freely, and prompted the salience-ranking and grounding-check additions. I also used it to draft this document from my notes. Every design decision here I can defend and would make again without it.

---

## Appendix: implementation detail (not required by the 1-2 page brief, kept for Q&A prep)

**Why Cube over the dbt Semantic Layer / MetricFlow.** In order of weight: its `query_rewrite` hook makes row-level tenant scoping a first-class server-side control rather than something the caller is trusted to apply; marking every base cube `public: false` makes "the LLM queries metrics, never tables" a structural property of the deployment rather than a line in a prompt; and it self-hosts with no dbt Cloud dependency, where the dbt Semantic Layer's serving API is a Cloud feature. Rate measures are defined over their component measures, so re-aggregating across segments cannot produce an average of averages.

**Why Cube reads Parquet, not the DuckDB warehouse file.** Cube's DuckDB driver opens its database file read-write with no read-only option, and DuckDB's lock is exclusive to a single writer. So the semantic layer does not read the warehouse: `rpt_` publishes as Parquet into a serving directory and Cube reads that, which means the warehouse can rebuild while the semantic layer keeps serving. The boundary is a published contract, not a shared file. (Full walkthrough of this and the rest of the pipeline: `task2/PIPELINE.md`.)

**Export and feedback loop (scoped, not built).** Export is templated: narrative plus chart images into a slide deck or PDF via a deck API or a Jinja template, matching the existing QBR format. CSM edits to the narrative would be captured as the cheapest available quality signal and as few-shot material for improving generation over time.
