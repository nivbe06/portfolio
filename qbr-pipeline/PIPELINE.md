# Pipeline: from a Makefile target to a QBR on someone's screen

Companion to [`DAG_GUIDE.md`](DAG_GUIDE.md). That file owns the warehouse half
(raw → staging → intermediate → marts → reporting, materialisation, the
incremental config, measured build timings). This file owns everything after
`dbt build` finishes: how the `rpt_` output — plain data files on disk, not a
database — becomes a rendered HTML pack, and what
each Makefile target actually does. It does not repeat §8 of `DAG_GUIDE.md`;
read that first if the question is about the warehouse build itself.

## 1. The runtime path, end to end

```
dbt build
  → data/serving/*.parquet          (rpt_ models, written out as plain data files)
  → Cube reads those files          (cube/model/*.py, 4 public views)
  → qbr/cube_client.py              (signs a per-tenant JWT, sends a Cube query)
  → qbr/salience.py                 (ranks anomaly rows by materiality, not by z)
  → qbr/retrieval.py                (account context for each surfaced movement)
  → the agent writes prose          (/create-qbr, reading payload + writing_rules)
  → qbr/grounding.py                (figures checked against payload;
                                     citations and quotations checked against
                                     the retrieved snippets)
  → qbr/render.py + qbr/charts.py   (self-contained HTML, inline SVG, no CDN)
```

There are two inputs, not one. The warehouse says **what** moved. The account
record - Gong calls, Salesforce notes and cases - says **why**, and it is the
half that turns a report into a review.

Two processes own this, cleanly split. `qbr/build_qbr.py` runs everything
deterministic: querying, ranking, checking, rendering. The agent owns exactly
one step, writing the prose, and touches nothing else — it never composes a
query and never computes a figure.

## 1a. The retrieval half

`qbr/retrieval.py` reads a mock corpus under `context/<tenant>/`. Four sources,
hand-written, no external service and no network: call summaries with verbatim
quotes, CSM notes, support cases, and the action items agreed at the previous
review. `context/README.md` documents the frontmatter every document carries.

**Retrieval is anomaly-driven, not free search.** `salience.py` has already
decided which movements are material; those rows build the queries. Nothing
searches for whatever seems interesting, because there is no correct answer to
that question and no way to check one.

**The scoring is keyword search in about fifty lines.** No embeddings, no vector
store. That is a scoping decision and worth defending rather than apologising for:
the corpus is nine documents, a dense index buys nothing measurable at that size,
and a demo that retrieves the same evidence every run is worth more than one
that retrieves marginally better evidence sometimes. At real corpus sizes this
becomes hybrid - keyword search for entity names, which are exactly what lexical
search is good at, and dense retrieval for the paraphrases it misses - behind the
same interface.

**Three controls sit around it**, and each defends against a failure a numeric
grounding check cannot see:

| Control | Defends against | Where |
|---|---|---|
| `visibility: internal` documents are filtered **before** the model is given anything | Renewal strategy, pricing headroom and opinions about the customer's staff reaching a customer-facing pack. Filtering afterwards is not a control: the model has already read it, and a model cannot unread something. | `retrieval.load_corpus` |
| Tenant isolation is a filter, never a ranking signal | Another account's call summary being out-ranked into this pack. Mirrors `query_rewrite` in the semantic layer. | `retrieval.load_corpus` |
| A document qualifies only if the movement's entity is in its declared `entities` | The retriever handing the model its best-scoring but unrelated document, and the model inventing the connection. A movement nobody wrote about gets **no** evidence, which is the honest output. | `retrieve_for_movements` |

**The rule that makes the whole thing safe: context may explain a number, never
produce one.** A call summary saying "we did about forty thousand redemptions"
is a source for a reason, not for a figure. `grounding.check()` reads the Cube
payload and nothing else, and `test_retrieval.py` fixes that separation so a
later refactor cannot quietly merge them.

`grounding.check_context()` adds two checks on the prose itself: every `[C1]`
citation must resolve to something actually retrieved, and every quotation must
appear verbatim in a snippet. An invented citation is the most dangerous of the
failure modes, because it looks like diligence.

The rendered pack carries the provenance: each cited passage with its source,
date and participants, and a footer line stating how many documents were
searchable and how many were **withheld as internal**. Publishing the withheld
count rather than hiding it is deliberate - it is the only way a reader can see
that the filter ran and removed something.

## 2. Why Cube reads plain data files, not the database directly

`rpt_` output is written as Parquet, a compact data file format (think a
faster, more compact CSV) — separate from the live `warehouse.duckdb`
database. Covered in full in `DAG_GUIDE.md` §5. The one-line version: Cube's
database driver has no read-only mode, so if Cube held `warehouse.duckdb`
open, `dbt build` would fail on the write lock the moment Cube was up.
Publishing `rpt_` as plain data files means Cube reads files nothing else
holds, and the warehouse can rebuild while the shared data layer keeps
serving. `make build` therefore restarts Cube automatically once the publish
finishes (see §6 below) — not because Cube would error on stale files, but
because it holds file handles open and needs to reopen them to see the new
rows.

## 3. Why there is no `make qbr`

A QBR needs prose, and the thing that writes the prose is the agent running
`/create-qbr`, not the Makefile. A `make` target can only shell out to
something deterministic; it cannot write the narrative paragraph, which is the
one non-deterministic step in the whole pipeline. So the pack is built in two
separate CLI calls instead, with the model in between:

```bash
make payloads TENANT=acme-commerce QUARTER=2026-Q2   # phase 1: query + rank, stop
# → agent reads the payload, writes qbr/created-qbrs/narratives-<tenant>-<quarter>.json
make render TENANT=acme-commerce QUARTER=2026-Q2 \
  NARRATIVES=qbr/created-qbrs/narratives-acme-commerce-2026-Q2.json  # phase 2: check + render
```

This split is not a convenience, it is the control. Putting the grounding
check (phase 2) on the other side of a process boundary from whatever wrote
the text means the check holds regardless of which model, agent, or human
produced the prose — nothing about `grounding.py` trusts its caller.

`/create-qbr` (`.claude/skills/create-qbr/SKILL.md` in the vault root) runs
both phases and writes the narrative in between. Running `qbr/build_qbr.py`
by hand, as this document does to verify the Makefile, skips only the prose
step; a human can supply `narratives-*.json` directly, as done below, and the
grounding check applies identically to a human's prose as to the model's.

## 4. `qbr/cube_client.py` — turning a bundle into a Cube request

Two guarantees live here, not upstream:

- **A model chooses a bundle id and nothing else.** `build_query()` is the
  entire translation layer: it reads a bundle's `query`/`breakdown`/`trend`
  block from `qbr/bundles/*.yml`, qualifies bare member names against the
  bundle's declared `view`, substitutes `{quarter}`/`{prior_quarter}`
  placeholders from the wizard's own deterministic parameters, and emits a
  Cube JSON query. There is no code path from free text into a query — the
  substitution function only fills whole-token placeholders it already knows
  about, or raises.
- **Every request carries a signed JWT naming one tenant.** `token_for()`
  signs `{"tenant_id": ...}`; `cube.py`'s `query_rewrite` appends the matching
  filter server-side. A caller cannot widen its own scope by asking for a
  different tenant — `qbr/test_boundary.py` (`make check`) proves this against
  a live Cube, not just in the design doc.

`run_query()` also absorbs Cube's `{"error": "Continue wait"}` response, which
is a poll instruction while Cube warms a query rather than a failure, and
strips the `view.member` prefix Cube returns so bundles can refer to plain
member names.

## 5. `qbr/salience.py` — ranking anomalies by materiality, not by z

A z-score answers "is this unusual"; it has no opinion on "does anyone care".
`salience.py` is the module that answers the second question, and it is
deliberately outside the warehouse — a 40-line file a non-SQL reader can
tune and audit, versus business judgement buried in a query or a prompt.

Score = `METRIC_WEIGHT[metric] × value_weight × relative_move × volume_confidence`,
then multiplied by boosts for paid-feature movements, revenue-touching
movements, and deteriorating movements. Full derivation and the ICE framing
(Impact × Confidence, deliberately no Ease term — a QBR agenda is about what
deserves the customer's attention, not what is cheap to fix) are in
`DAG_GUIDE.md` §10; this file only needs the interface: `rank()` takes the
`anomalies` bundle's rows and returns `{ranked, suppressed, candidate_count,
salience_floor}`. `ranked` is what surfaces in the pack; `suppressed` is the
five highest-|z| rows that did not clear `SALIENCE_FLOOR` (0.15) — kept and
shown so a reviewer can see what a naive z-ordered system would have led with
instead.

## 6. The agent step — the only non-deterministic one

`/create-qbr` reads the phase-1 payload (account context, the bundle
registry, and per chosen section: `payload` plus that bundle's
`writing_rules` from `qbr/bundles/*.yml`: `must_cover`, `must_not`, `tone`,
`max_words`). It writes continuous prose per section, restating figures from
the payload only — no new arithmetic, no recall from elsewhere, no
z-scores or statistical language in customer-facing text. Output is a flat
JSON `{section_id: text}` written to
`qbr/created-qbrs/narratives-<tenant>-<quarter>.json`. Nothing in this step
calls an API or touches a credential; the only artefact that matters is the
JSON file, which is why phase 2 can validate it identically whether a model
or a human wrote it.

## 7. `qbr/grounding.py` — the control that makes step 6 safe to trust

Full rationale, including both hard-won tolerance rules, is in the module's
own docstring and `DAG_GUIDE.md` references it; the two rules worth carrying
into this document because they shape what "verified" means in every pack:

1. **Derived arithmetic is admitted only within a record.** A narrative may
   say "fell from 62% to 49%, a drop of 13 points" when all three numbers
   describe one payload row — that is restating the row. Deriving across the
   *whole* payload was tried first and rejected: sixty payload numbers produce
   roughly three thousand cross-row pairs, dense enough that a fabricated
   44.2% redemption rate passed against a real 48.7%, purely by coincidence.
2. **The payload is rounded to the claim's stated precision, never the
   reverse.** A figure written to one decimal place has to be right to one
   decimal place. Rounding the *claim* instead (tried first) let "44.2%"
   match any payload value near 44 — a whole percentage point of slack, wide
   enough for the same fabricated figure above to pass a second way.

`grounding.check(text, payload)` extracts every numeric token from the prose
(skipping small trivial integers like "the top 5" and year/quarter labels),
builds the set of admissible values from the payload (every legitimate
rounding/scaling of a raw value, plus within-record derived differences and
ratios), and reports `{ok, checked, unverified, payload_values}`. It returns
a report rather than raising, so `build_qbr.py`'s phase 2 can name the exact
offending tokens and exit non-zero, and the caller (agent or human) rewrites
only the failing section and reruns. `qbr/test_grounding.py` (`make test`)
pins 16 cases, several marked `REGRESSION` for figures earlier versions of
this module wrongly accepted — including both bugs above.

## 8. `qbr/render.py` + `qbr/charts.py` — the HTML

`render.py` assembles one self-contained HTML file: header with account
context, KPI tiles, one `<section>` per chosen bundle (narrative paragraphs
plus that section's charts), and a provenance panel reporting which sections
passed grounding, the anomaly funnel (candidates considered vs. surfaced),
and that no query in the document was composed by a language model. A
section that failed grounding after a retry still renders, wrapped in a
visible "Held for review" flag, rather than being silently dropped — the
failure is meant to be seen, not hidden.

`charts.py` hand-draws inline SVG (bar, line, table) from the same rows the
narrative was checked against — no chart library, no CDN, so the pack stays a
single file that opens anywhere. Design tokens (colour variables, type,
spacing) deliberately match `qbr-pipeline.html`, the architecture artefact,
so the diagram and the thing it describes read as one system. `charts.fmt()`
is the one place display precision is decided: percentages and money to one
decimal or whole units — Cube returns every measure as a string, so `_num()`
coerces before any arithmetic or comparison (this was the S5 bug that broke
KPI up/down arrows until fixed — see the Progress table entry for S5).

## 9. Makefile targets

Verified live on 2026-08-22, `TENANT=acme-commerce QUARTER=2026-Q2` unless
noted. `ROOT`, `TALON_RAW_ROOT`, `TALON_SERVING_ROOT` are exported once at the
top of the Makefile from `pwd`, so every target resolves the same absolute
paths regardless of the caller's working directory — relative paths in a
database view break the moment someone opens the warehouse from elsewhere.

| Target | What it runs | When to use it | Verified |
|---|---|---|---|
| `all` | `generate build serve` in sequence | Full rebuild from nothing — first run on a new machine, or after `make clean` | Ran clean → generate → build → serve end to end; see below |
| `generate` | `generate/gen_logs.py` then `generate/dump_seeds.py`, writing ~2.18M raw events to `data/raw/` at `--scale 1.0` (default; `--scale 0.05` for a quick smoke run) | Only needed once, or after `make clean` — the seed (`20260821`) is fixed, so reruns are deterministic and reproduce identical raw events | Ran to completion in the full cycle below |
| `build` | `cd dbt && dbt build`, then — only if Cube is already running — restarts it and polls `localhost:4000/cubejs-api/v1/meta` until it answers 200 (up to 60s) | After any change to `data/raw/` or to a model. Safe to run whether or not Cube is up: dbt never blocks on Cube (they touch different files, the whole point of publishing `rpt_` as plain data files), and the restart-and-poll only fires when there is something running to refresh | Ran to completion in the full cycle below; 67 dbt tests pass |
| `serve` | `docker compose -f cube/docker-compose.yml up -d` | Start the semantic layer on `localhost:4000` when it is not already running | Verified via `meta` returning 200 after the full cycle |
| `stop` | `docker compose -f cube/docker-compose.yml down` | Tear down Cube, e.g. before a `dbt build` you want to run without the auto-restart firing | Ran and confirmed `docker compose ps` shows no `cube` service, then `make serve` brought it back |
| `payloads` | `qbr/build_qbr.py --emit-payloads` — phase 1 only. Writes `qbr/created-qbrs/payloads-<tenant>-<quarter>.json`. `FOCUS="..."` optional | Start of a QBR — gather and rank before anyone writes prose | Ran for `acme-commerce`/`2026-Q2`: 3 built sections queried, wrote the payload file |
| `render` | `qbr/build_qbr.py --json --with-narratives $(NARRATIVES)` — phase 2. `NARRATIVES=<path>` is required (no default; the Makefile does not guess which draft to check) | After the prose exists, to check every figure and render the HTML | Ran against an existing `narratives-acme-commerce-2026-Q2.json`: 3 sections, all `verified`, anomalies 8 considered / 1 surfaced |
| `test` | `qbr/test_grounding.py` — Python-side unit tests for the grounding checker. (dbt's own tests run inside `make build`, not here) | After touching `grounding.py`, or as a fast sanity check with no Cube dependency | Ran: 16/16 grounding cases behaved as intended |
| `check` | `qbr/test_boundary.py` — the two access-control claims (an account can read only its own metrics; a base cube cannot be queried directly; a token naming another tenant returns zero rows; a token with no tenant claim is refused), run against a **live** Cube | After touching `cube/cube.py`'s `query_rewrite`, or as evidence for "how do you know an agent cannot read the whole warehouse" | Ran: 4/4 boundary checks passed |
| `clean` | `rm -rf data/raw data/serving data/warehouse.duckdb dbt/target` | Full reset before an `all` rerun, or to confirm the build is reproducible from nothing | Ran: completed in ~2s |

**`make all` full-cycle verification (this session).** `make clean` (2s) →
`make generate` (3m53s) → `make build` failed the first time, fixed, reran
(2m25s) → `make serve` (already up from the restart in `build`). Then
`make payloads` and `make render` re-run for both tenants against the
freshly rebuilt warehouse, and `make test`/`make check` both rerun, to
confirm the regenerated data files round-trip through Cube and the grounding
check end to end.

**A real bug found running this.** `make clean` deletes `data/serving/`
entirely (`rm -rf data/serving`), but dbt's step that writes the `rpt_` data
files does not create the destination directory — it only writes files into one
that already exists. The very first `make build` after `make clean` fails on
all four `rpt_` models with `IO Error: Cannot open file
".../data/serving/rpt_*.parquet": No such file or directory`, while every
staging/intermediate/marts model and test still passes (`PASS=78 ERROR=4
SKIP=11` — the four external-model errors cascade into skipped tests that
depend on them). `mkdir -p data/serving` before the rebuild and `make build`
succeeds cleanly (`PASS=93 ERROR=0`). This has never surfaced before because
`data/serving/` has existed continuously since it was first created; `make
clean` followed immediately by `make build` (rather than `make all`, which
also fails the same way since `build` runs after `generate` with `serving/`
already gone) is the only way to hit it. **Whoever runs S9's fresh-clone
verification (`make clean && make all` from a stranger's checkout, where
`data/serving/` has never existed) needs `mkdir -p data/serving` before
`make build`, or add it to the `build` target directly.** Flagging this for
S9/S10 rather than fixing the Makefile myself — out of scope for S6, which
documents the pipeline rather than changes it.

**Row counts after the rebuild, checked directly against the warehouse and
the published data files, confirming the rebuild is exactly reproducible from
the fixed seed (`20260821`):**

| | Rows |
|---|---|
| `fct_coupon_redemptions` | 3,276 |
| `fct_effects_fired` | 27,683 |
| `fct_integration_health` | 4,368 |
| `fct_loyalty_events` | 1,092 |
| `fct_session_evaluations` | 13,104 |
| **`fct_` total** | **49,523** — matches `DAG_GUIDE.md` exactly |
| `rpt_anomalies` | 151 |
| `rpt_feature_adoption` | 120 |
| `rpt_qbr_campaign_performance` | 153 |
| `rpt_qbr_overview` | 72 |
| **`rpt_` total** | **496** — matches `DAG_GUIDE.md` exactly |

`make test` (16/16) and `make check` (4/4) both pass against the rebuilt
warehouse. `make payloads` + `make render` re-run for both `acme-commerce`
and `brightline-grocers`, `2026-Q2`, reusing the narrative JSON already on
disk from an earlier run today (deterministic figures round-trip
identically): acme 3 sections / 10+12+4 = 26 figures, all verified,
8 anomaly candidates / 1 surfaced; brightline 3 sections / 5+2+6 = 13
figures, all verified, 5 candidates / 2 surfaced. Same section and figure
counts S5 reported for both packs — the rebuild changed nothing a customer
would see.
