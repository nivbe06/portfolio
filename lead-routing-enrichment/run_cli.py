#!/usr/bin/env python3
"""Prove the slice: partial account in -> enriched record out, on the terminal.

    python run_cli.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import fields as F
from app import reconcile as R
from app.gates import field_needs_enrichment, is_missing
from app.models import Method, Verdict
from app.orchestrator import enrich_account, needed_fields

SEEDS = Path(__file__).parent / "app" / "seeds" / "demo_accounts.json"

TAG = {Method.LLM: "LLM", Method.DETERMINISTIC: "det", Method.UNCHANGED: "--"}


def show(v) -> str:
    """Compact display: missing -> the empty marker, lists unwrapped, no str-quoting ints."""
    from app.gates import is_missing
    if is_missing(v):
        return "∅"                 # empty set = was missing
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def main() -> None:
    if "--reset" in sys.argv:
        R.reset_store()
        print(">> learned reconciliation map cleared (cold start)\n")
    R.reset_counters()
    cached_before = R.overlay_size()
    accounts = json.loads(SEEDS.read_text())
    total_provider_calls = 0

    for acc in accounts:
        print("=" * 72)
        label = acc.get("domain") or acc.get("email") or "?"
        print(f"{acc['company_name']}  <{label}>")
        print(f"  note: {acc.get('_demo_note','')}")
        res = enrich_account(acc)

        if res.skipped:
            print(f"  SKIPPED (Gate A): {res.skip_reason}  -> provider calls: 0")
            continue

        if res.key_source != "input_domain":
            print(f"  key resolved: {res.key}  ({res.key_source})")

        print(f"  {'FIELD':<20}   {'WAS':<12} -> {'NOW':<26} HOW")
        print(f"  {'-'*20}   {'-'*12}    {'-'*26} {'-'*3}")

        # first-party fields kept untouched
        kept = [f for f in needed_fields(None)
                if f not in res.enriched and not field_needs_enrichment(f, acc["existing"].get(f))]
        for f in kept:
            v = show(acc["existing"][f])
            print(f"  {f:<20}   {v:<12} == {v:<26} kept · first-party")

        for f, rf in res.enriched.items():
            mark = TAG[rf.method]
            before = show(rf.before)
            if rf.value is None:
                now = "(dropped -> review)"
            else:
                now = show(rf.value)
                # show the raw->canonical hop when reconciliation changed the value
                if str(rf.raw_value) != str(rf.value):
                    now = f"{show(rf.raw_value)} -> {now}"
            wf = f"{'>'.join(rf.providers_called)}" if len(rf.providers_called) > 1 else rf.source
            print(f"  {f:<20}   {before:<10} -> {now:<26} [{mark}] {rf.verdict.value} · {wf}")

        total_provider_calls += len(res.providers_called)
        print(f"  --> providers called: {res.providers_called or '[]'} | "
              f"LLM reconciliations: {res.llm_calls}")

    print("=" * 72)
    print(f"TOTAL provider calls across batch:   {total_provider_calls}")
    print(f"LLM reconciliation calls THIS run:   {R.llm_call_count}")
    print(f"Cached aliases (start -> end):       {cached_before} -> {R.overlay_size()}")
    if R.llm_call_count == 0 and cached_before > 0:
        print("=> 0 LLM calls: every semantic conflict was served from the learned map.")
    else:
        print("=> Run again (no --reset) to watch LLM calls drop to 0 - verdicts now cached.")


if __name__ == "__main__":
    main()
