"""Retrieval over the account-context corpus.

A QBR has two halves. The warehouse knows what moved; the account team knows
why. This module is the second half: it pulls the calls, notes, cases and
commitments that bear on the movements the ranking layer has already decided are
worth discussing.

Three properties matter more than the retrieval algorithm.

**Retrieval is anomaly-driven, not free search.** `salience.py` has already cut
the candidate movements down to the handful that are material. Those rows build
the query. Nothing here searches for whatever seems interesting, because there is
no such thing as a correct answer to that.

**Tenant isolation is a filter, not a ranking signal.** A document belonging to
another account cannot be out-ranked into a pack; it is never a candidate. This
mirrors what `query_rewrite` does in the semantic layer.

**`visibility: internal` is removed before the model sees anything.** Renewal
strategy, pricing headroom and opinions about the customer's staff are in the
corpus deliberately, because a retrieval layer that only ever holds safe
documents proves nothing. Filtering after generation would mean the model had
already read them.

The scoring is keyword search (BM25 under the hood) in about fifty lines, with
no embeddings and no vector store. That is a scoping decision, not a shortcut:
the corpus is nine documents, where a dense index buys nothing measurable and
costs determinism, and a demo that retrieves the same evidence every run is
worth more than one that retrieves marginally better evidence sometimes. At real
corpus sizes this becomes a hybrid - keyword search for the entity names, which
are exactly the terms lexical search is good at, and dense retrieval for the
paraphrases it misses - behind the same interface.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
from collections import Counter
from typing import Any

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CONTEXT_DIR = os.path.normpath(os.path.join(HERE, "..", "context"))

# Keyword-search (BM25) constants. Standard values; nothing here is tuned to the mock corpus,
# because tuning nine documents would be fitting noise.
K1 = 1.5
B = 0.75

# A movement has to retrieve something that is actually about it. Below this the
# evidence is dropped rather than shown, so a section can legitimately come back
# with no context at all - which is the honest outcome when the account team
# never wrote anything down.
SCORE_FLOOR = 1.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_QUOTE_LINE_RE = re.compile(r"^>\s?(.*)$")

# Metric column names are not English. Retrieval matches on words a human wrote
# in a call summary, so the machine name has to be expanded into them first.
_METRIC_TERMS = {
    "redemption_rate": "coupon redemption rate redeemed",
    "effects_fired": "effect fired volume",
    "discount_value": "discount value spend",
    "api_error_rate": "api error rate errors 5xx reliability incident",
    "sessions_evaluated": "sessions evaluated volume traffic",
    "points_issued": "loyalty points issued earn",
    "points_burned": "loyalty points burned spent redeemed",
    "net_points_outstanding": "loyalty points outstanding liability balance",
}


class Document:
    """One corpus file: its frontmatter, its body, and the tokens keyword search scores."""

    def __init__(self, meta: dict[str, Any], body: str, path: str):
        self.path = path
        self.source = str(meta.get("source", ""))
        self.source_id = str(meta.get("source_id", ""))
        self.title = str(meta.get("title", ""))
        self.date = _as_date(meta.get("date"))
        self.tenant_id = str(meta.get("tenant_id", ""))
        self.participants = list(meta.get("participants") or [])
        self.entities = [str(e) for e in (meta.get("entities") or [])]
        self.visibility = str(meta.get("visibility", "internal"))
        self.actions = list(meta.get("actions") or [])
        self.body = body

        # Entities are repeated into the indexed text. They are the join key
        # between a document and an anomaly row, so a document that names the
        # campaign should beat one that merely discusses the same topic.
        self.tokens = _tokenise(f"{self.title} {' '.join(self.entities * 3)} {body}")
        self.entity_tokens = {tok for e in self.entities for tok in _tokenise(e)}
        self.counts = Counter(self.tokens)

    def quotes(self) -> list[str]:
        """Verbatim quotes, which are what a CSM actually wants to repeat.

        Consecutive blockquote lines are one quote. Splitting on the line breaks
        Markdown happens to use would hand the model half a sentence, and half a
        sentence cannot be checked back against the source verbatim.
        """
        blocks: list[list[str]] = []
        for line in self.body.splitlines():
            match = _QUOTE_LINE_RE.match(line)
            if not match:
                blocks.append([]) if blocks and blocks[-1] else None
                continue
            text = match.group(1).strip()
            if not text:
                continue
            # The attribution line ("- Priya Raman, 04:12") is provenance, not
            # part of what was said.
            if text.startswith("-"):
                blocks.append([])
                continue
            if not blocks or not blocks[-1]:
                blocks.append([])
            blocks[-1].append(text)
        return [" ".join(b).strip() for b in blocks if b]

    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.body.split("\n\n") if p.strip()]


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _tokenise(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _split_frontmatter(raw: str, path: str) -> tuple[dict[str, Any], str]:
    """Markdown files carry `---` frontmatter; the commitment files are all YAML."""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return yaml.safe_load(parts[1]) or {}, parts[2]
    if path.endswith((".yml", ".yaml")):
        return yaml.safe_load(raw) or {}, raw
    return {}, raw


def load_corpus(tenant_id: str, include_internal: bool = False) -> list[Document]:
    """Every document for one tenant.

    `include_internal` exists for the tests that assert the filter works. No
    caller in the pipeline passes it.
    """
    docs: list[Document] = []
    root = os.path.join(CONTEXT_DIR, tenant_id)
    if not os.path.isdir(root):
        return docs

    for dirpath, _, filenames in os.walk(root):
        for name in sorted(filenames):
            if not name.endswith((".md", ".yml", ".yaml")):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                meta, body = _split_frontmatter(fh.read(), path)
            if not meta.get("source_id"):
                continue
            doc = Document(meta, body, path)

            # Tenant isolation. The directory already implies it, but a document
            # whose frontmatter disagrees with its location is a corpus bug, and
            # the safe reading of an ambiguous document is to drop it.
            if doc.tenant_id != tenant_id:
                continue
            if doc.visibility != "customer_safe" and not include_internal:
                continue
            docs.append(doc)
    return docs


def _keyword_score(query_tokens: list[str], docs: list[Document]) -> list[float]:
    n = len(docs)
    if not n:
        return []
    avg_len = sum(len(d.tokens) for d in docs) / n
    df = Counter()
    for doc in docs:
        for term in set(query_tokens):
            if doc.counts.get(term):
                df[term] += 1

    scores = []
    for doc in docs:
        score = 0.0
        length = len(doc.tokens) or 1
        for term in query_tokens:
            freq = doc.counts.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * length / avg_len))
        scores.append(score)
    return scores


def _query_for(movement: dict[str, Any]) -> tuple[str, list[str]]:
    """Turn one ranked anomaly row into a query and the entity terms it must hit."""
    label = str(movement.get("entity_label") or "")
    metric = str(movement.get("metric_name") or "")
    expanded = _METRIC_TERMS.get(metric, metric.replace("_", " "))
    return f"{label} {expanded}", [label, expanded]


def _snippet(doc: Document, entity_terms: list[str]) -> str:
    """The most quotable passage that mentions the entity.

    Preference order is deliberate: a verbatim quote from the customer is worth
    more in a QBR than a summary sentence written by the account team, because
    the CSM can repeat it back and the customer recognises their own words.
    """
    # Match on the words of the entity, not the whole label. Nobody says
    # "Winback Reactivation" out loud on a call; they say "the winback audience",
    # and matching the full label would skip the quote that is the whole point.
    tiers = [{tok for tok in _tokenise(term) if len(tok) > 3} for term in entity_terms if term]
    for wanted in tiers:
        for quote in doc.quotes():
            if any(w in quote.lower() for w in wanted):
                return quote
    for wanted in tiers:
        for para in doc.paragraphs():
            if any(w in para.lower() for w in wanted):
                return " ".join(para.split())
    quotes = doc.quotes()
    if quotes:
        return quotes[0]
    paras = doc.paragraphs()
    return " ".join(paras[0].split()) if paras else ""


def _evidence(doc: Document, score: float, entity_terms: list[str],
              movement: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "source": doc.source,
        "source_id": doc.source_id,
        "title": doc.title,
        "date": doc.date.isoformat() if doc.date else None,
        "participants": doc.participants,
        "snippet": _snippet(doc, entity_terms),
        "score": round(score, 3),
        "explains": {
            "entity_label": movement.get("entity_label"),
            "metric_name": movement.get("metric_name"),
        } if movement else None,
    }


def retrieve_for_movements(tenant_id: str, movements: list[dict[str, Any]],
                           per_movement: int = 1) -> list[dict[str, Any]]:
    """Evidence for the movements the ranking layer already decided to surface.

    Returns citation-numbered items, `C1` upward, in the order the movements were
    ranked. A movement with nothing above the score floor simply gets no
    evidence: silence is the correct output when nobody wrote anything down, and
    inventing a plausible reason is the exact failure this whole pipeline exists
    to prevent.
    """
    docs = load_corpus(tenant_id)
    if not docs:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for movement in movements:
        query, entity_terms = _query_for(movement)
        scores = _keyword_score(_tokenise(query), docs)
        ranked = sorted(zip(docs, scores), key=lambda p: p[1], reverse=True)

        # The gate: a document qualifies only if the movement's entity appears
        # in its declared `entities`, which is the join key between the corpus
        # and an anomaly row. Matching anywhere in the body is too loose - a
        # call summary titled "Quarterly check-in" would answer a movement on
        # any entity with the word "quarterly" in its name. Without the gate,
        # metric vocabulary alone ("sessions", "volume") clears the score floor
        # and the retriever hands the model an unrelated document to invent a
        # connection from.
        entity_tokens = {tok for tok in _tokenise(entity_terms[0]) if len(tok) > 3}

        taken = 0
        for doc, score in ranked:
            if taken >= per_movement or score < SCORE_FLOOR:
                break
            if entity_tokens and not (entity_tokens & doc.entity_tokens):
                continue
            if doc.source_id in seen:
                continue
            seen.add(doc.source_id)
            out.append(_evidence(doc, score, entity_terms, movement))
            taken += 1

    for i, item in enumerate(out, start=1):
        item["citation_id"] = f"C{i}"
    return out


def retrieve_commitments(tenant_id: str) -> list[dict[str, Any]]:
    """Action items agreed at a previous review, with their current status.

    Not a search. Commitments are enumerated, because "what did we promise last
    time" has one right answer and retrieving an approximation of it would be
    worse than useless.
    """
    out: list[dict[str, Any]] = []
    for doc in load_corpus(tenant_id):
        if doc.source != "commitment":
            continue
        for action in doc.actions:
            out.append({
                "id": action.get("id"),
                "text": action.get("text"),
                "owner": action.get("owner"),
                "status": action.get("status"),
                "closed_on": str(action.get("closed_on")) if action.get("closed_on") else None,
                "note": action.get("note"),
                "source_id": doc.source_id,
                "agreed_on": doc.date.isoformat() if doc.date else None,
            })
    return out


def corpus_summary(tenant_id: str) -> dict[str, Any]:
    """What was available and what was withheld. Rendered into the pack footer.

    Publishing the withheld count rather than hiding it is the point: a reader
    can see that the filter ran and did something, which is not visible from a
    pack that simply never mentions the internal note.
    """
    visible = load_corpus(tenant_id)
    everything = load_corpus(tenant_id, include_internal=True)
    return {
        "documents_available": len(everything),
        "documents_searchable": len(visible),
        "withheld_internal": len(everything) - len(visible),
        "sources": sorted({d.source for d in visible}),
    }
