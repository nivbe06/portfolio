"""Core data model. A field value never travels without its provenance."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    FIRST_PARTY = "first_party"   # a human at our company observed it (BDR call, form)
    THIRD_PARTY = "third_party"   # an enrichment provider gave it to us
    SEED = "seed"                 # reference data we control


class Method(str, Enum):
    """How a value was decided. Surfaced in the UI so the user sees LLM vs not."""
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    UNCHANGED = "unchanged"       # value already present, we did not touch it


class Verdict(str, Enum):
    PASS = "pass"                 # good, accept
    RECOVERABLE = "recoverable"   # incomplete / low-conf / empty -> waterfall
    HARD_FAIL = "hard_fail"       # implausible -> drop, never write
    RECONCILE = "reconcile"       # valid but different vocabulary -> normalise, not a fail


@dataclass
class Candidate:
    """One provider's answer for one field, before resolution."""
    field: str
    value: Any
    source: str                  # provider name, or "input"
    source_type: SourceType
    confidence: float = 0.5
    observed_at: str = ""        # ISO date


@dataclass
class ResolvedField:
    """The final value for a field plus the audit trail behind it."""
    field: str
    value: Any                    # final canonical value (the "after")
    source: str
    source_type: SourceType
    method: Method
    confidence: float
    verdict: Verdict
    before: Any = None            # value in the input record ("was")
    raw_value: Any = None         # what the provider returned, pre-reconcile
    llm_confidence: float | None = None   # the AI's own mapping confidence (LLM rows only)
    observed_at: str = ""         # when the source observed the value (provenance)
    notes: list[str] = field(default_factory=list)
    providers_called: list[str] = field(default_factory=list)


@dataclass
class AccountResult:
    key: str                     # company domain, the enrichment key
    key_source: str = "input_domain"   # how we got the key (input / resolved from name)
    enriched: dict[str, ResolvedField] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""
    providers_called: list[str] = field(default_factory=list)
    llm_calls: int = 0
    needs_review: bool = True    # V1: everything goes through the human review queue
    notes: list[str] = field(default_factory=list)
