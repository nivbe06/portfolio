# Task 1 — Code Map

Purpose: know this codebase well enough to answer a hostile Q&A question without opening a file. Traces one request end to end, states what each module owns, and answers the five questions a panel is most likely to ask.

## The request path

`POST /api/enrich` (`app/api.py`) is the only entry point that runs the pipeline. Everything else (`/api/plan`, `/api/refetch`, `/api/terms`, `/api/costs`, ...) is a view onto the same core or a variant of one step.

```
api.py:enrich()
  -> orchestrator.py:enrich_account()      one call per account, per run
       -> gates.py:account_eligible()      Gate A (account level)
       -> gates.py:resolve_company_key()   domain, or name -> domain
       -> selection.py:primary_plan()      anti-fire-all: which providers to call at all
       -> orchestrator.py:_enrich_one()    per field, one call per field to enrich
            -> providers.py:fetch()        mock provider call + normalise
            -> gates.py:gate_b()           Gate B (field level, quality check)
            -> reconcile.py:reconcile()    canonical DB -> already-canonical -> LLM
                 -> db.py:get_canonical()  SQLite lookup, no LLM if it hits
                 -> anthropic API call     only on a genuine miss
  -> api.py:_serialize()                   attach kept (untouched) fields, cost, low_conf flag
  -> db.py:record_field_enrichment()       stats ledger (#3)
  -> db.py:record_enrichment_log()         per-field audit row (#9)
  -> COSTS.append(...)                     in-memory cost ledger (#6)
```

`models.py` defines the shapes that flow through every arrow above (`Candidate`, `ResolvedField`, `AccountResult`, and the `SourceType` / `Method` / `Verdict` enums). No logic lives there — it's the contract every module agrees to.

`fields.py` is data, not flow: `FIELD_REGISTRY` (which providers own which field, in priority order, and whether the field is in the default set), plus every seeded taxonomy (`COUNTRY_MAP`, `VERTICALS`, `PLATFORM_VOCAB`, `SENIORITY_SEED`, `FREE_DOMAINS`, `KNOWN_MX`, `NAME_TO_DOMAIN`). Both `gates.py` and `reconcile.py` read it; nothing writes it at runtime.

## What each module owns

| Module | Owns | Does not own |
|---|---|---|
| `api.py` | HTTP surface, request/response shaping, in-memory audit/cost ledgers, CSV ingest, demo batch loading, per-user permission gate | any enrichment decision — it calls into the core, never judges a value itself |
| `orchestrator.py` | the pipeline shape: which fields need enriching, calling selection then the per-field loop, assembling `AccountResult` | provider mechanics, quality rules, reconciliation |
| `gates.py` | Gate A (account eligibility, field-needs-enrichment) and Gate B (per-field format/plausibility checks) — pure deterministic, no LLM | fetching data, deciding what to do after a verdict (that's the orchestrator's waterfall loop) |
| `selection.py` | `primary_plan`: which providers get called at all, based on which fields are actually missing (the anti-fire-all cost lever) | quality judgement, fallback ordering beyond returning the ordered list |
| `providers.py` | mock transport (`_load`) + per-provider normalisers turning provider-native JSON into internal `Candidate` objects, filtered by declared coverage | any decision about whether a candidate is good enough (that's Gate B) |
| `reconcile.py` | canonical-vocabulary mapping: DB lookup -> already-canonical check -> real Claude call -> stub fallback; owns the Anthropic client and key resolution | fetching provider data, quality gating |
| `db.py` | SQLite persistence: `canonical_terms`, `suggestions` (with promotion), `field_stats`, `enrichment_log` | any business logic about what should be promoted — it just counts unique users and applies the threshold it's given |
| `models.py` | dataclasses/enums shared across every module | behaviour |
| `fields.py` | static registry + seed taxonomies | behaviour |

## Where the two gates sit and what each rejects

**Gate A** (`gates.py:account_eligible`, `field_needs_enrichment`) runs before any provider is touched.
- `account_eligible`: does this account have *any* enrichable identifier — a business domain, a company name, or a person's name? A free personal email alone doesn't disqualify (a company name still gives something to resolve against). Rejects: no domain, no company, no person → account skipped entirely, `needs_review = False` (there's nothing to review, it's a data problem, not a quality problem).
- `field_needs_enrichment`: is this specific field missing (null/placeholder/empty), or present-but-useless (a personal email where a corporate one is needed)? Drives which fields even enter the pipeline for that account.

**Gate B** (`gates.py:gate_b`) runs once per candidate value, after a provider returns something, before it's accepted.
- Format/plausibility checks per field: email needs RFC shape *and* a seeded MX record; phone needs E.164; `employee_count` must be a positive int under 5M or it's a **hard fail** (implausible headcount never gets waterfalled — a wrong number is worse than no number); country/industry/platform/seniority get checked against the seeded vocabulary — a valid-but-foreign value returns `RECONCILE`, not `PASS` or `FAIL`, because it's a vocabulary mismatch, not a quality problem.
- Verdict meanings: `PASS` (accept as-is), `RECONCILE` (accept, but map to canonical vocabulary next), `RECOVERABLE` (try the next provider), `HARD_FAIL` (drop, do not waterfall — implausible data should never leak through via a second guess).

## The learned reconciliation map: write and read paths

**Read** (`reconcile.py:reconcile`, called once per categorical field per account): four-step order —
1. `db.get_canonical(field, raw)` — SQLite lookup against `canonical_terms.aliases` (JSON array per agreed term). Deterministic, no LLM, no cost.
2. Is the raw value already an exact canonical term? (covers providers that already return the right vocabulary)
3. Real Claude call (`_llm_reconcile`, `claude-haiku-4-5` by default) — only reached on a genuine miss. Falls back to a small deterministic stub table (`_LLM_TABLE`) if no API key is resolvable, so the app still runs offline.
4. Genuinely unknown → left raw, flagged for review. No LLM call, no crash.

**Write** happens on a separate path, not automatically. An LLM proposal is *never* auto-cached — it's shown to the user as unconfirmed. Only when the CRM-write flow calls `POST /api/suggest` (`api.py:suggest` → `db.py:add_suggestion`) does a suggestion get recorded. `add_suggestion` counts *unique users* who've suggested the same `from -> to` mapping; at `db.PROMOTE_AT` unique users it's written into `canonical_terms.aliases`, and from then on step 1 catches it deterministically — zero LLM calls for that value, for every account, forever. `PROMOTE_AT` is 1 in this demo build so a single reviewer sees promotion happen in one pass (production value is 3; see the docstring in `db.py`). This is the mechanism behind the 5 → 1 → 0 LLM-call sequence in the demo script.

## How the LLM tail is bounded

Several independent limits, stacked:
- **Reconciliation only.** The LLM is never called to fetch data, only to map an already-fetched, already-gate-B-passed value onto a fixed vocabulary. Numbers, emails, phones, URLs, revenue bands are never reconciled at all (`reconcile.RECONCILABLE` — five categorical fields only).
- **Deterministic-first.** Every call checks the canonical DB and the exact-match case before ever considering the LLM. Seeded aliases and previously-promoted terms never reach the model.
- **One-shot per candidate, no retry loop.** `_llm_reconcile` is a single request with a strict system prompt requiring one allowed term or `NONE`; a bad or failed response is treated as "no mapping," not retried.
- **Bounded output space.** The prompt hands the model the exact allowed-term set (`_canonical_targets`) for that field — it cannot invent a new canonical term, only pick from what's given or decline.
- **Structural cap via selection + waterfall.** `selection.primary_plan` only calls providers that own a field actually missing (`WATERFALL_CAP = 3` in `orchestrator.py` bounds providers tried per field), so the LLM only ever sees values that made it through the funnel — never a blind sweep.
- **Promotion shrinks the tail over time.** Every promoted term removes that value from ever reaching the LLM again, for any future account. This is why repeat runs converge toward zero LLM calls (the demo's 5 → 1 → 0).

## Five likely Q&A questions, answered

**1. "What happens if two users suggest conflicting reconciliations for the same raw term?"**
`add_suggestion` keys on `(field, reconcile_from, reconcile_to)` — a different `to` for the same `from` is a *different* row with its own unique-user count. Nothing promotes until one specific mapping independently reaches the threshold; the store doesn't arbitrate conflicts, it just requires more agreement per candidate answer. Two competing mappings can both accumulate votes; whichever reaches `PROMOTE_AT` first wins, but the other keeps its own count and could still promote later — there's no explicit reconciliation of the conflict itself.

**2. "Is the account-eligibility skip (Gate A) different from a field being dropped by Gate B, and why does that distinction matter?"**
Yes, and it maps directly to `needs_review`. A Gate A skip (`someone@gmail.com`, no company, no name) means there's *nothing to enrich against* — that's a data-collection problem, not a quality problem, so `needs_review = False`; showing it in a review queue would be noise. A Gate B hard-fail or unresolved field means real data existed and was actively judged low-quality or implausible — that *does* belong in front of a human, hence `needs_review = True` by default on `AccountResult`.

**3. "Why does `employee_count` hard-fail instead of waterfalling to the next provider?"**
Deliberate: a `RECOVERABLE` verdict waterfalls because the field might just be missing from this provider. But an implausible number (negative, or over 5M) isn't a missing-data problem — it's evidence the value is *wrong*, and a second provider guessing a different wrong number doesn't fix that. Waterfalling on implausible data risks silently accepting whichever wrong number a later provider returns. Hard-fail stops and drops, or keeps the existing value if there was one (see `_enrich_one`'s `chosen is None` branch).

**4. "The cost dashboard shows LLM cost as 'the remainder.' Why not compute it directly?"**
`api.py:costs()` deliberately computes `ai_cost = total - sum(by_provider.values())` so provider-line-items plus AI reconcile to the ledgered total *exactly*, by construction — no rounding drift between two independently-summed numbers. The actual LLM call count and per-field LLM cost are tracked precisely elsewhere (`reconcile.llm_call_count`, `_field_costs` in `api.py`); the dashboard's "remainder" framing is specifically for the top-level admin summary where exact reconciliation matters more than a second independent sum.

**5. "What happens when the same field is both `overwrite_fields`-selected and has an existing value that no provider can beat?"**
`_enrich_one` in `orchestrator.py`: if every provider in the waterfall returns nothing usable (`chosen is None`) and the field `has_existing`, the function returns the *original* value with `method=UNCHANGED, source="first_party"` and a note `"no newer value found - kept existing"`. Overwrite is a permission to *try* replacing a value, never a guarantee it will be replaced, and the pipeline never blanks a field that already had something — data can only get better or stay the same, never regress to empty.

**6. "Does the `linkedin_url` Gate B check handle every real LinkedIn URL shape?"**
Not originally — a review of `_LINKEDIN_RE` found it rejected valid profile URLs on three real shapes: country subdomains (`de.linkedin.com/in/...`), a query string after the slug (`?originalSubdomain=de`), and no-scheme input (`linkedin.com/in/...`). Since `linkedin_url` is not in the default field set and is never reconciled, the blast radius was contained to `RECOVERABLE` false negatives (a real profile URL bouncing to the next provider or the review queue) — no LLM path, no demo-script impact. Fixed in `gates.py`:
```python
# before
_LINKEDIN_RE = re.compile(r"^https?://(www\.)?linkedin\.com/in/[\w\-]+/?$", re.I)
# after
_LINKEDIN_RE = re.compile(r"^(https?://)?([\w-]+\.)?linkedin\.com/in/[\w\-]+/?(\?.*)?$", re.I)
```
Scheme and subdomain now both optional (any subdomain, not just `www.`), and a trailing query string no longer fails the anchor. Company-page URLs (`/company/...`) and non-LinkedIn input still correctly reject. Verified against 6 cases (valid: `www.` with trailing slash, country-subdomain with query string, bare no-scheme, `m.` mobile subdomain; invalid: company page, garbage string) and the full 53-test suite still passes. Good example to have ready: a real gap found by reading the code critically, not by running the demo, closed in one line, verified before claiming it.
