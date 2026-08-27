# AI usage disclosure - Task 1

## Building this submission

Built with Claude Code (Anthropic) as a pair-programming tool across an iterative
session series. I made the architecture and product calls - two-gate design, the
seed -> learned -> LLM reconciliation order, anti-fire-all provider selection, the
promotion mechanic - and directed each iteration; Claude Code wrote and revised code,
docs, and tests to that direction, and I reviewed and corrected as it went.

## Inside the running app

The app itself uses a real LLM call at one specific, bounded point: `reconcile.py`,
step 3 of reconciliation. When a provider's value is a valid-but-foreign vocabulary
term (e.g. industry `"Software"`, not yet in the canonical `industry` list), and no
deterministic rule matches, Claude Haiku is asked to map it to exactly one term from
an explicit allowed list, or decline.

Everywhere else in the pipeline is deterministic:
- Gate A (does this need enrichment?) and Gate B (is the value good?) - no LLM.
- Provider selection (anti-fire-all) - no LLM.
- Waterfall fallback between providers - no LLM.
- Any value already in the canonical vocabulary, or matched by a seeded or
  user-promoted alias - no LLM.

The LLM's output is a *proposal*, never auto-cached. It becomes a permanent
deterministic rule only after a human confirms it via "Write to CRM" enough times
to cross the promotion threshold (`db.PROMOTE_AT`, see `db.py`). This is why the
demo shows LLM call counts falling to zero across repeated runs: the learned map
grows, the LLM tail shrinks, not because outputs are cached blindly but because
humans confirm them into rules.

If `ANTHROPIC_API_KEY` is not resolvable (env var or macOS keychain), the app does
not fail: reconciliation falls back to a small offline stub table covering the
known demo values, and any value neither seeded nor in that stub table is left as
raw input, flagged `"no mapping for '<value>' -> review"` for the human review
queue. See `README.md` for the exact fallback behaviour and how to force it.
