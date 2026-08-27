"""Verify that every number in a generated narrative came from the data.

The model is never asked to compute anything, so in principle it cannot invent a
figure. In practice "in principle" is not a control. This module is the control:
it extracts every numeric token from the generated text and asserts that each
one is derivable from the structured payload the model was given. Anything that
is not, fails, and the section is regenerated.

The hard part is tolerance, not extraction, and it fails in both directions.
Too strict and every section is regenerated over correct rounding: a payload
value of 0.2218 must be accepted when the narrative says "22%", because a model
writing "22.18%" is writing worse prose. Too loose and the check stops being a
control at all.

Two rules keep it honest, and both were learned by getting them wrong:

  1. Derived arithmetic is admitted only *within a record*. Deriving across the
     whole payload admits so many values that almost any three-digit figure
     matches one by coincidence.
  2. The payload is rounded to the claim's stated precision, never the reverse.
     A figure written to one decimal place has to be right to one decimal place.

See test_grounding.py, where the cases marked REGRESSION are figures that
earlier versions of this module accepted.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Matches 1,234.56 / 22% / 0.62 / -3.4 / €1.2k style tokens.
NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*\s*%?")

# Small integers are almost always prose ("three campaigns", "the top 5"), not
# claims about the data. Checking them produces false rejections without
# catching anything real.
TRIVIAL_MAX = 12

# Years and quarters are labels, not measurements.
LABEL_RE = re.compile(r"^(19|20)\d{2}$")


def _clean(token: str) -> tuple[float | None, bool]:
    """Return (value, was_percent)."""
    is_percent = token.strip().endswith("%")
    raw = token.replace(",", "").replace("%", "").strip()
    if raw in ("", "-", "."):
        return None, is_percent
    try:
        return float(raw), is_percent
    except ValueError:
        return None, is_percent


def extract_numbers(text: str) -> list[tuple[str, float, bool]]:
    """Every numeric claim in the narrative, as (token, value, is_percent)."""
    found = []
    for match in NUMBER_RE.finditer(text):
        token = match.group().strip()
        value, is_percent = _clean(token)
        if value is None:
            continue
        if not is_percent and abs(value) <= TRIVIAL_MAX and float(value).is_integer():
            continue
        if LABEL_RE.match(token):
            continue
        found.append((token, value, is_percent))
    return found


def _variants(value: float) -> set[float]:
    """Every scale a payload number could legitimately be written at.

    Values are kept at full precision here. Rounding happens at comparison
    time, against the precision the claim states, so that a figure written to
    one decimal place has to be correct to one decimal place.
    """
    if value is None:
        return set()

    out = {value, abs(value)}
    for base in (value, abs(value)):
        out.add(base * 100)      # ratio written as a percentage
        out.add(base / 100)      # percentage written as a ratio
        if abs(base) >= 1000:
            out.add(base / 1000)  # "18.4k"
    return out


def _payload_values(payload: Any, acc: set[float] | None = None) -> set[float]:
    """Walk the payload and collect every number it contains, at any depth."""
    if acc is None:
        acc = set()

    if isinstance(payload, dict):
        for v in payload.values():
            _payload_values(v, acc)
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            _payload_values(v, acc)
    elif isinstance(payload, bool):
        pass
    elif isinstance(payload, (int, float)):
        acc.add(float(payload))
    elif isinstance(payload, str):
        try:
            acc.add(float(payload))
        except ValueError:
            pass
    return acc


def _records(payload: Any, acc: list[list[float]] | None = None) -> list[list[float]]:
    """Every dict in the payload, reduced to the numbers it contains.

    A record is the unit within which arithmetic is meaningful. One row holds a
    rate, its prior-quarter rate and the change between them, so a narrative
    comparing those is restating the row. Two numbers from unrelated rows have
    no arithmetic relationship worth expressing.
    """
    if acc is None:
        acc = []

    if isinstance(payload, dict):
        own: list[float] = []
        for value in payload.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                own.append(float(value))
            elif isinstance(value, str):
                try:
                    own.append(float(value))
                except ValueError:
                    pass
            else:
                _records(value, acc)
        if own:
            acc.append(own)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _records(value, acc)
    return acc


def admissible_values(payload: Any) -> set[float]:
    """The payload's numbers, plus every legitimate rounding of each.

    Derived quantities are included, but only *within a record*. A narrative may
    legitimately say "fell from 62% to 49%, a drop of 13 points" when all three
    figures describe one row, because that is restating the row rather than
    computing something new.

    Deriving across the whole payload instead, which is what this did first,
    makes the check useless. Sixty payload numbers produce roughly three
    thousand pairs, and once each pair contributes a difference, a ratio and a
    handful of roundings, the admissible set grows large enough that almost any
    three-digit figure lands in it by coincidence. A fabricated redemption rate
    of 44.2% passed against a payload whose real value was 48.7%. The bound on
    what counts as derivable is what gives the check its teeth.
    """
    raw = _payload_values(payload)
    admissible: set[float] = set()

    for value in raw:
        admissible |= _variants(value)

    for record in _records(payload):
        if len(record) > 24:            # keep it cheap on wide rows
            record = record[:24]
        for a in record:
            for b in record:
                if a == b:
                    continue
                admissible |= _variants(a - b)
                if b != 0:
                    admissible |= _variants((a - b) / abs(b))
    return admissible


def _stated_precision(token: str) -> int:
    """How many decimal places the claim actually commits to."""
    body = token.replace(",", "").replace("%", "").strip()
    return len(body.split(".", 1)[1]) if "." in body else 0


def check(text: str, payload: Any) -> dict[str, Any]:
    """Validate a narrative against its payload.

    A claim is accepted when some admissible value, rounded to the precision the
    claim itself states, equals the claim. The direction matters. Rounding the
    *claim* instead, which is what this did first, accepts a whole unit of error:
    "44.2%" would match any payload value near 44, so a fabricated redemption
    rate passed against a real one of 48.7%. Making the payload meet the claim's
    stated precision means a figure written to one decimal place has to be right
    to one decimal place.

    Returns a report rather than raising, so the caller can rewrite the offending
    sections, and so a failure is visible rather than silent.
    """
    allowed = admissible_values(payload)
    claims = extract_numbers(text)
    unverified = []

    for token, value, is_percent in claims:
        places = _stated_precision(token)

        # Each reading carries its own precision. A percentage read back as a
        # ratio needs two more decimal places, because dividing by a hundred
        # shifts the significant digits. Comparing the ratio at the percentage's
        # precision instead collapses "24%" to 0 and matches any near-zero value
        # in the payload, which is how a wholly invented figure gets through.
        readings = [(value, places)]
        if is_percent:
            readings.append((value / 100, places + 2))

        matched = any(
            abs(round(admissible, precision) - round(candidate, precision)) < 1e-9
            for candidate, precision in readings
            for admissible in allowed
        )
        if not matched:
            unverified.append({"token": token, "value": value})

    return {
        "ok": not unverified,
        "checked": len(claims),
        "unverified": unverified,
        "payload_values": len(allowed),
    }


def format_failure(report: dict[str, Any]) -> str:
    """A correction the model can act on, naming the offending figures."""
    tokens = ", ".join(f"'{u['token']}'" for u in report["unverified"])
    return (
        f"These figures do not appear in the data you were given: {tokens}. "
        "Rewrite using only figures present in the payload. Do not calculate "
        "new values, and do not estimate."
    )


# --------------------------------------------------------------------------
# Context grounding
#
# Numbers are checked against the payload above. Prose warranted by a retrieved
# document needs its own controls, because the failure modes are different: a
# fabricated figure is caught by comparing it to the data, but a fabricated
# quotation, a citation pointing at a document that was never retrieved, or a
# sentence lifted from an internal note all pass a numeric check untouched.
#
# The governing rule, and the one to say out loud: **context may explain a
# number, never produce one.** A call summary saying "we did about forty
# thousand redemptions" is not a source for a figure. It is a source for a
# reason. `check()` still validates every figure against the semantic layer and
# nothing here relaxes that.
# --------------------------------------------------------------------------

_CITATION_RE = re.compile(r"\[(C\d+)\]")
_QUOTED_RE = re.compile(r"[“\"]([^“”\"]{12,})[”\"]")


def _normalise(text: str) -> str:
    """Whitespace and quote-mark differences are formatting, not fabrication."""
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("’", "'").replace("‘", "'")
    return " ".join(text.split()).strip(" .,;:-")


def check_context(text: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the qualitative half of a narrative against what was retrieved.

    Three failures, each of which a numeric check would let through:

      unresolved_citations  a `[C3]` when only C1 and C2 were retrieved, which is
                            an invented source and the most dangerous of the
                            three because it looks like diligence
      unverified_quotes     quotation marks around words nobody said
      unused_evidence       retrieved and cited by nothing; not an error, but
                            worth reporting, because a section that ignores its
                            own evidence is usually a section written before the
                            evidence arrived

    Returns a report rather than raising, matching `check()`, so a caller can
    rewrite and retry.
    """
    known = {item.get("citation_id") for item in evidence if item.get("citation_id")}
    snippets = [_normalise(str(item.get("snippet", ""))) for item in evidence]

    cited = set(_CITATION_RE.findall(text))
    unresolved = sorted(cited - known)

    unverified_quotes = []
    for quoted in _QUOTED_RE.findall(text):
        needle = _normalise(quoted)
        if not any(needle in hay for hay in snippets):
            unverified_quotes.append(quoted)

    return {
        "ok": not unresolved and not unverified_quotes,
        "citations_used": sorted(cited),
        "unresolved_citations": unresolved,
        "quotes_checked": len(_QUOTED_RE.findall(text)),
        "unverified_quotes": unverified_quotes,
        "unused_evidence": sorted(known - cited),
    }


def format_context_failure(report: dict[str, Any]) -> str:
    """A correction the model can act on, naming what failed."""
    parts = []
    if report["unresolved_citations"]:
        ids = ", ".join(report["unresolved_citations"])
        parts.append(
            f"These citations do not exist in the evidence you were given: {ids}. "
            "Cite only the citation_id values present in the evidence list."
        )
    if report["unverified_quotes"]:
        quotes = "; ".join(f'"{q}"' for q in report["unverified_quotes"])
        parts.append(
            f"These quotations do not appear verbatim in any retrieved snippet: {quotes}. "
            "Quote only what the snippet actually says, character for character, "
            "or paraphrase without quotation marks."
        )
    return " ".join(parts)
