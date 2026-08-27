# Lead Routing Enrichment

Partial account in -> normalised, CRM-ready record out. Deterministic-first, LLM-last.
Every field shows how it was decided (deterministic vs LLM), so LLM over-use is visible.

## Run

```bash
cd lead-routing-enrichment
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
.venv/bin/uvicorn app.api:app --port 8077
```
Open http://localhost:8077

Terminal-only version (no server, pure stdlib):
```bash
python3 run_cli.py            # or: python3 run_cli.py --reset
```

## Behaviour without `ANTHROPIC_API_KEY`

The LLM tail (`reconcile.py`, step 3) resolves the key at import time: env var first,
then the macOS keychain (`security find-generic-password -s ANTHROPIC_API_KEY`). If
neither yields a key, `_client` stays `None` and every LLM-tail lookup falls back to
a small offline stub table covering the known demo values (`_LLM_TABLE` in
`reconcile.py`) - the demo script still runs, no network call, no error surfaced to
the user. A value that is in neither the canonical/seeded map nor that stub table is
left as its raw input value and flagged `"no mapping for '<value>' -> review"` for
the human review queue, rather than blocked or guessed at.

To force this path deliberately (e.g. to demo the offline fallback), set
`USE_REAL_LLM=0`. It short-circuits the LLM tail without touching your environment
or your keychain:
```bash
USE_REAL_LLM=0 .venv/bin/uvicorn app.api:app --port 8077
```

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt   # first time only
.venv/bin/pytest -q
```
53 tests over `gates.py`, `selection.py`, `reconcile.py`, `orchestrator.py`. Deterministic
regardless of `ANTHROPIC_API_KEY` - a fixture forces the offline LLM stub path so results
don't depend on network access or a live key.

## Architecture (hybrid)

Tested Python core; a thin FastAPI layer exposes it and serves the UI. In production
the same core sits behind n8n (deterministic gates + API calls, business-owner legible).

```
app/
  models.py        provenance-carrying data model
  fields.py        field registry + seeded taxonomies (= the quality-rules table)
  providers.py     mock Clearbit / ZoomInfo / Apollo / Crunchbase (seed files)
  gates.py         Gate A (needs enrichment?) + Gate B (is value good?)
  reconcile.py     seed -> learned -> LLM tail, with persisted write-back cache
  selection.py     anti-fire-all: call only providers that own a missing field
  orchestrator.py  gate -> select -> fetch -> quality+waterfall -> reconcile -> assemble
  api.py           FastAPI endpoints + static UI
  web/index.html   account-in -> enriched-out UI
  seeds/           provider seed data + demo_accounts (A) + demo_accounts_b (B)
```

## Demo script (presentation)

1. **Reset learned map** (cold start, admin -> Danger zone).
2. **Enrich the demo list.** LLM THIS RUN = 5 (e.g. industry `Software->SaaS`,
   title `Director of Growth->growth_leader`). Point at DET vs LLM badges: most
   fields deterministic. Note the waterfall (FastCart phone), hard-fail drop
   (BahnPay employee_count), Gate A skip (free email), corp-email harvest (Loyal Nordic).
3. **Write to CRM.** This is the step that matters: confirming the run promotes each
   reconciled mapping to canonical. An LLM proposal is never cached on its own - a
   human has to confirm it before it becomes a rule.
4. **Enrich the second list** (brand-new companies, same messy variants). LLM THIS
   RUN = 1: BrightCart's `Software` / `Director of Growth` now resolve
   deterministically via rules **learned from the first run**. Only the genuinely-new
   `webshop` pays the LLM. This is generalisation, not caching.
5. **Write to CRM, then enrich the second list again.** LLM THIS RUN = 0. The tail
   is promoted too.

Headline: LLM calls fall as the learned map saturates; provider API calls are the
real cost and the gate + anti-fire-all selection bound them.

## Known limitations (deferred, not oversights)

- **Idempotency.** A re-run of the same account against the same providers re-calls
  and re-pays rather than detecting "already done." The design is specified
  (`(account_key, field, provider, date)` cache key, see
  `task1_presentation_plan.md`, "Session decisions - multi-user, fields, audit,
  dedup, idempotency") but not implemented - it protects against a mid-flight
  retry or duplicate upload in production, which this single-session demo build
  never exercises. Out of scope for this take-home; noted here so it reads as a
  scoped decision if raised in Q&A, not a gap discovered under pressure.
- **Provider failure vs. bad data.** A down/rate-limited/timeout provider is not
  distinguished from one that returned nothing; both fall through to the next
  provider in the waterfall. A production system would retry/queue a transient
  failure rather than waterfalling past it.
- **Outcome feedback loop.** Nothing here confirms a provider's value was actually
  *right* (e.g. an email that didn't bounce) - only that it passed Gate B's format
  and plausibility checks. Closing that loop is V2.
