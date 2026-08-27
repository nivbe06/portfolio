# QBR Pipeline - session logs to a customer-facing review

A working implementation of the design in
[`DESIGN.md`](DESIGN.md).

2.18 million mock Talon.One session and integration events, reduced through a
dbt DAG to a published serving layer, served through a Cube semantic layer, and
turned into a customer-facing Quarterly Business Review by a `/create-qbr`
skill. Every figure in the output is computed in SQL and validated against its
source before it reaches the document.

**The rule the whole thing is built around: the warehouse does the reduction,
the language model does the language.** It selects which sections to include and
writes the prose. It computes nothing, detects nothing, and composes no queries.

## Run

```bash
cd qbr-pipeline
pip3 install -r requirements.txt
make generate       # ~2.18M events into data/raw, about 90 seconds
make build          # dbt: 21 models, 67 tests, about 35 seconds
make serve          # Cube on localhost:4000
make check          # 4 access-boundary tests against the live semantic layer
```

Then, in Claude Code:

```
/create-qbr
```

**No API key, anywhere.** The skill asks for account, quarter and focus, gathers
the data, writes the prose itself, checks every figure back against source, and
renders the pack into `qbr/created-qbrs/`.

That split is deliberate rather than a convenience. Python does the querying,
ranking, checking and rendering; the agent asking for the QBR writes the
language. Because the grounding check sits on the other side of a process
boundary from whatever produced the text, the control holds regardless of which
model, agent or human wrote it. The two halves are also runnable by hand:

```bash
make payloads TENANT=acme-commerce QUARTER=2026-Q2
make render   TENANT=acme-commerce NARRATIVES=qbr/created-qbrs/narratives-acme-commerce-2026-Q2.json
```

## The measured funnel

Not estimates. These are counts from an actual `make build`.

| Stage | Volume | Cumulative reduction |
|---|---|---|
| Raw events, gzipped JSONL | 2,068,975 events, 53 MB gz (~380 MB raw) | 1x |
| `stg_` typed and deduped | same rows, views over parquet | 1x |
| `int_` lineage and joins | no reduction, by design | 1x |
| `fct_` daily grain, incremental | 49,523 rows | 42x |
| `rpt_` published as parquet | **496 rows, 48 KB** | **4,171x** |
| Payload actually sent to the model | **~2,153 tokens** | **~46,000x** on token count |

The last row is the one that matters: roughly 100 million tokens of raw log
becomes a 2,153-token payload for a complete three-section QBR. At the 5 GB
monthly volume described in the brief the ratio is larger still.

## Why Cube reads parquet and not the warehouse

The obvious design is to point Cube at `data/warehouse.duckdb`. It does not
work, and the reason is worth knowing before you try it.

Cube's DuckDB driver opens the database file read-write and exposes no read-only
option (`DuckDBDriver.readOnly()` returns `false`; there is no `access_mode`
environment variable). DuckDB's file lock is exclusive to one writer, and
`read_only=True` does not get a reader past a writer's lock. So with Cube
running, the next `dbt build` fails with a lock error, and you have to stop the
semantic layer every time you rebuild the warehouse.

So dbt owns the warehouse, and the `rpt_` models are materialised as `external`
parquet into `data/serving/`. Cube runs an in-memory DuckDB and reads those
files per query. Nothing is ever shared, and `make build` succeeds while Cube is
serving. That is a test, not a hope: rebuilding with the container up is step 4
of the verification below.

One honest caveat. Removing the lock is not the same as making the swap
invisible. Replacing the parquet underneath a running Cube leaves it holding
stale file handles, and the next query fails with a protocol error until it is
restarted. So `make build` restarts the container when it finds one running.
The distinction matters: the build is never *blocked*, it just publishes and
then refreshes the reader. With a shared database file the build would have
failed outright and there would be nothing to refresh.

It is also the better architecture. The semantic layer consumes a published,
versioned serving contract rather than reaching into the warehouse, which is the
same boundary argument the design document already makes. And it avoids a second
trap: DuckDB's storage format is version-coupled, so a file written by
dbt-duckdb 1.10 may not open in whatever DuckDB the Cube image ships. Parquet is
stable across versions.

The cost: `external` models cannot be incremental. Incrementality stays in
`fct_`, and `rpt_` rebuilds fully. At 496 rows that is free.

## Layout

```
generate/     world.py defines the cast and plants six signals; gen_logs.py writes them
dbt/          stg_ -> int_ -> dim_/fct_ -> rpt_, 21 models and 67 tests
cube/         docker-compose, the cube models, and cube.py where tenant scoping lives
qbr/          bundles/, the Cube client, salience ranking, retrieval, grounding, render
context/      mock account record: Gong calls, Salesforce notes and cases, commitments
data/         generated, gitignored: raw/, warehouse.duckdb, serving/*.parquet
qbr/created-qbrs/  generated QBR packs (payloads, narratives, rendered HTML)
```

The skill lives at `.claude/skills/create-qbr/SKILL.md` in the repo root.

## The qualitative half

A QBR is a conversation, not a numbers dump. Why redemption fell lives in a Gong
call, never in a fact table. `qbr/retrieval.py` searches a mock account record
under `context/` for the passages bearing on the movements the ranking layer
already surfaced, and the narrative cites them with their source, date and
participants.

The rule that keeps it safe: **context explains a number, it never produces
one.** Every figure still validates against the semantic-layer payload alone.
Three further controls sit around retrieval, each defending something a numeric
check cannot see: documents marked `visibility: internal` are filtered out
*before* the model is given anything, every `[C1]` citation must resolve to
something actually retrieved, and every quotation must match its source
character for character. `qbr/test_retrieval.py` covers all of it.

See `context/README.md` for the corpus and `PIPELINE.md` §1a for the design.

## Design decisions worth defending

**`int_` reduces nothing, deliberately.** It resolves session to campaign to
ruleset to effect and carries shopper segment from the session onto the effect.
Format compaction happens above it in `stg_`, grain collapse below it in
`fct_`. Keeping those separate is what makes the aggregation readable.

**`int_` models are views, not ephemeral.** On DuckDB the storage cost is
identical, and an inspectable intermediate layer is worth a great deal when
something looks wrong in front of an audience.

**Anomaly detection is SQL, at weekly grain.** A rolling z-score against an
eight-week trailing baseline. At quarterly grain, S3's one-week outage is
diluted across thirteen weeks and vanishes. `rpt_anomalies` deliberately stops
at "statistically unusual" and emits the raw inputs a ranker needs; it does not
decide what matters.

**Materiality ranking is Python, outside the warehouse.** Because it is business
judgement, it changes more often than the schema, and a CSM lead should be able
to read it. It scores on relative change rather than absolute magnitude, since
euros and failed requests are not commensurable and ranking them against a
shared ceiling silently decides that a few hundred euros of discount outranks a
thirty-sevenfold increase in customer-visible errors.

**Rate measures are defined over their components in Cube**, never stored and
summed, so re-aggregating across segments cannot produce an average of averages.

**Narrative is written by the agent that asked for the QBR**, not by an API
call from Python. Claude Code is already a model; paying for a second one to do
the same job needs a reason, and with QBRs generated on demand there is no
headless caller to justify it. What survives the split is the part that matters:
`qbr/grounding.py` runs in a separate process from whatever wrote the prose, so
it checks the text on its merits rather than trusting its author.

**Two design-document claims are dbt tests.** `assert_no_pii_in_rpt.sql` fails
the build if any personal identifier reaches the published layer, so the PII
firewall is enforced rather than asserted. `assert_reduction_ratio.sql` fails if
`rpt_` outgrows its row budget, so the funnel is an invariant rather than a
slide.

**Tenant isolation is `query_rewrite` in `cube/cube.py`.** Every base cube is
`public: false`, so only views are queryable, and every query gets a tenant
filter appended from the caller's signed JWT before planning. A caller cannot
opt out, because the filter is not part of the query they submitted. `make
check` proves it.

## Verification

1. `make generate` — row counts per stream, hive partition layout under `data/raw`.
2. `make build` — 21 models, 67 tests, zero failures, zero dbt 1.11 deprecation warnings.
3. `make serve` then `curl localhost:4000/cubejs-api/v1/meta` — four private cubes, four public views.
4. **`make build` again, with Cube still running.** Must pass. This is the regression test for the parquet decision.
5. `make check` — 4/4 boundary tests.
6. `make test` — 16 grounding cases, including that a stored 0.4866 is accepted as "48.7%" or "49%" but rejected as "48.9%".
7. `/create-qbr` — pack in `qbr/created-qbrs/`, every section reporting a non-zero figure count.
8. `SIGNALS.md` — all six planted stories surface, and the two that should be suppressed are.

## Demo script

1. **Show the problem.** `du -sh data/raw`, then the funnel table above.
2. **Run the DAG.** `make build`. Point at the 67 tests, and specifically at
   `assert_no_pii_in_rpt` and `assert_reduction_ratio`: two claims from the
   design document, enforced.
3. **Rebuild with Cube up**, to show the serving-layer decision was load-bearing.
4. **Break the boundary on purpose.** `make check`. A base cube refused, a
   cross-tenant query returning zero rows, an unsigned token rejected.
5. **Build a QBR.** `/create-qbr`, pick acme-commerce. Then the headline: the
   anomaly ranker was handed eight candidates. `rejectCoupon` moved at z = +3.6
   and was dropped. The winback redemption collapse moved at z = -3.6 and
   surfaced. Same significance, opposite decisions, because one of them costs
   the customer money.
6. **Open the pack**, and read the provenance panel at the bottom: which
   sections were verified, how many candidates were considered, what it cost.

## AI usage disclosure

Claude, via Claude Code, wrote most of this code from a design I specified and
reviewed. Its most useful contribution was adversarial: it found that Cube's
DuckDB driver has no read-only mode before I built on the assumption that it
did, which would have surfaced as a lock error mid-demo. I found three
correctness bugs in its output during review: partial weeks at the data boundary
producing artefact z-scores that buried every real finding, a
`select distinct x, row_number() over ...` in a test that shifted the comparison
by one quarter, and a salience score that ranked incommensurable units against a
shared ceiling. All three are fixed, and the fixes are commented where they
matter. The architecture, the domain model, and the decisions in the section
above are mine.
