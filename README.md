# Portfolio - Niv Belleli

Systems that turn messy operational reality into something a non-technical team
can act on, with the guardrails built into the system rather than into people's
habits.

The first two were built as take-home work for a GTM AI Engineer process. The
task briefs are not reproduced here; each project states the problem in my own
words and then shows the implementation. The last two are patterns I ran in
production and rebuilt clean, with no employer data, code, or content.

---

## [Lead Routing Enrichment](lead-routing-enrichment/)

**Problem.** New accounts arrive from many sources with partial information. A
service has to enrich each record against an external provider, normalise the
response into one internal model, and decide which incoming values are allowed
to overwrite what the CRM already holds.

**What it does.** Deterministic first, language model last. Every field records
how it was decided, so over-use of the LLM is visible rather than hidden. Phone
numbers parse to E.164 with the region inferred from headquarters. A field-level
merge policy decides what wins. Runs as a web service or as a pure-stdlib CLI,
and degrades to an offline stub when no API key is present.

**53 tests.** FastAPI, Python.

---

## [QBR Pipeline](qbr-pipeline/)

**Problem.** Millions of raw session and integration events, and a customer
success manager who needs a quarterly business review a customer can be shown.

**What it does.** 2.18M mock events reduced through a dbt DAG to a published
serving layer, exposed through a Cube semantic layer that doubles as the tenant
access boundary, and rendered into a customer-facing review document.

The rule the whole system is built around: **the warehouse does the reduction,
the language model does the language.** It selects sections and writes prose. It
computes nothing, detects nothing, and composes no queries. Every figure is
calculated in SQL and validated against source before it reaches the page.
Internal-only documents are filtered before retrieval, not after, and the
rendered pack publishes what was withheld so a reader can see the filter ran.

**21 models, 67 tests, 4 live access-boundary tests.** dbt, DuckDB, Cube,
Python.

See [`DESIGN.md`](qbr-pipeline/DESIGN.md) for the architecture and the reasoning
behind each boundary.

---

## Running these

Each project has its own README with setup steps. The QBR pipeline generates its
own dataset (`make generate`); no data is committed to this repository.

---

## [Skill Shop](skill-shop/) *(in progress)*

Turning scattered individual AI hacks into repeatable practice. A browsable
catalogue generated from a registry, a contribution path, and a three-state
graduation gate (sandbox, reviewed, published) that puts the quality standard in
version control instead of in a policy document.

## [Brain Onboarding](brain-onboarding/) *(in progress)*

The path from zero to a working context layer for a non-technical person. Guided
setup, typed frontmatter so retrieval narrows before it reads, and an update
process that rides on work people already do rather than a review nobody runs.
