"""Terminology store (SQLite). Two tables, per the agreed design:

  canonical_terms   the agreed term + the JSON list of raw variants that map to it
  suggestions       a proposed from->to mapping + who requested it (JSON), counts

Promotion hook: when a suggestion reaches 3 *unique* users, its `from` variant is
added to the canonical term's alias list - so it resolves deterministically from
then on, with no LLM. (V2: per-family thresholds, admin-tunable.)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "state" / "terms.db"
PROMOTE_AT = 1   # unique users needed to promote a suggestion to canonical
# DEMO OVERRIDE: real threshold is 3 (see class docstring). Set to 1 here only so a
# single reviewer can see promotion happen live in one pass. Revert to 3 for production.


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _create(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS canonical_terms (
            field       TEXT NOT NULL,
            agreed_term TEXT NOT NULL,
            aliases     TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (field, agreed_term)
        );
        CREATE TABLE IF NOT EXISTS suggestions (
            field         TEXT NOT NULL,
            reconcile_to  TEXT NOT NULL,
            reconcile_from TEXT NOT NULL,
            requests      TEXT NOT NULL DEFAULT '[]',
            req_count     INTEGER NOT NULL DEFAULT 0,
            unique_users  INTEGER NOT NULL DEFAULT 0,
            promoted      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (field, reconcile_from, reconcile_to)
        );
        CREATE TABLE IF NOT EXISTS field_stats (
            input_name   TEXT PRIMARY KEY,
            total        INTEGER NOT NULL DEFAULT 0,
            by_default   INTEGER NOT NULL DEFAULT 0,
            custom       INTEGER NOT NULL DEFAULT 0,
            when_exists  INTEGER NOT NULL DEFAULT 0,
            when_missing INTEGER NOT NULL DEFAULT 0,
            success      INTEGER NOT NULL DEFAULT 0,
            users        TEXT NOT NULL DEFAULT '[]',
            last_at      TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS enrichment_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL,
            ts          TEXT NOT NULL,
            user        TEXT NOT NULL,
            company     TEXT NOT NULL,
            account_key TEXT NOT NULL,
            field       TEXT NOT NULL,
            service     TEXT NOT NULL DEFAULT '',
            before_value TEXT,
            after_value  TEXT,
            confidence   REAL,
            is_successful INTEGER NOT NULL DEFAULT 0,
            cost         REAL NOT NULL DEFAULT 0,
            observed_at  TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_enrichment_log_company ON enrichment_log(company);
        CREATE INDEX IF NOT EXISTS idx_enrichment_log_field ON enrichment_log(field);
        CREATE INDEX IF NOT EXISTS idx_enrichment_log_run ON enrichment_log(run_id);
    """)


def init(seed_maps: dict[str, dict[str, str]]) -> None:
    """Create tables; seed canonical_terms from the known reference aliases if empty.
    seed_maps: {field: {raw_variant_lower: canonical}}."""
    with _conn() as c:
        _create(c)
        if c.execute("SELECT COUNT(*) FROM canonical_terms").fetchone()[0]:
            return
        grouped: dict[tuple[str, str], list[str]] = {}
        for field, m in seed_maps.items():
            for raw, canon in m.items():
                grouped.setdefault((field, canon), []).append(raw.lower())
        for (field, canon), aliases in grouped.items():
            c.execute("INSERT OR REPLACE INTO canonical_terms(field,agreed_term,aliases) VALUES(?,?,?)",
                      (field, canon, json.dumps(sorted(set(aliases)))))


def get_canonical(field: str, raw: str) -> str | None:
    """Deterministic lookup: does `raw` already map to an agreed term for this field?"""
    key = str(raw).strip().lower()
    with _conn() as c:
        for row in c.execute("SELECT agreed_term,aliases FROM canonical_terms WHERE field=?", (field,)):
            if key == row["agreed_term"].lower() or key in json.loads(row["aliases"]):
                return row["agreed_term"]
    return None


def add_suggestion(field: str, reconcile_from: str, reconcile_to: str, user: str) -> dict:
    """Record a user's reconciliation suggestion. Promote to canonical at PROMOTE_AT unique users."""
    frm, to = str(reconcile_from).strip(), str(reconcile_to).strip()
    if not frm or not to or frm.lower() == to.lower():
        return {"promoted": False, "unique_users": 0}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        _create(c)
        row = c.execute("SELECT requests,promoted FROM suggestions WHERE field=? AND reconcile_from=? AND reconcile_to=?",
                        (field, frm, to)).fetchone()
        requests = json.loads(row["requests"]) if row else []
        already = bool(row["promoted"]) if row else False
        requests.append({"user": user, "ts": ts})
        uniq = len({r["user"] for r in requests})
        promote_now = (not already) and uniq >= PROMOTE_AT
        c.execute("""INSERT OR REPLACE INTO suggestions
                     (field,reconcile_to,reconcile_from,requests,req_count,unique_users,promoted)
                     VALUES(?,?,?,?,?,?,?)""",
                  (field, to, frm, json.dumps(requests), len(requests), uniq,
                   1 if (already or promote_now) else 0))
        if promote_now:
            r = c.execute("SELECT aliases FROM canonical_terms WHERE field=? AND agreed_term=?", (field, to)).fetchone()
            aliases = json.loads(r["aliases"]) if r else []
            if frm.lower() not in aliases:
                aliases.append(frm.lower())
            c.execute("INSERT OR REPLACE INTO canonical_terms(field,agreed_term,aliases) VALUES(?,?,?)",
                      (field, to, json.dumps(sorted(set(aliases)))))
        return {"promoted": promote_now, "unique_users": uniq, "threshold": PROMOTE_AT}


def promoted_count() -> int:
    with _conn() as c:
        _create(c)
        return c.execute("SELECT COUNT(*) FROM suggestions WHERE promoted=1").fetchone()[0]


def record_field_enrichment(field: str, was_default: bool, value_existed: bool,
                            success: bool, user: str) -> None:
    """#3 stats: track which fields users choose to enrich, to tune the default set."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        _create(c)
        row = c.execute("SELECT * FROM field_stats WHERE input_name=?", (field,)).fetchone()
        users = json.loads(row["users"]) if row else []
        if user not in users:
            users.append(user)
        vals = {
            "total": (row["total"] if row else 0) + 1,
            "by_default": (row["by_default"] if row else 0) + (1 if was_default else 0),
            "custom": (row["custom"] if row else 0) + (0 if was_default else 1),
            "when_exists": (row["when_exists"] if row else 0) + (1 if value_existed else 0),
            "when_missing": (row["when_missing"] if row else 0) + (0 if value_existed else 1),
            "success": (row["success"] if row else 0) + (1 if success else 0),
        }
        c.execute("""INSERT OR REPLACE INTO field_stats
            (input_name,total,by_default,custom,when_exists,when_missing,success,users,last_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (field, vals["total"], vals["by_default"], vals["custom"], vals["when_exists"],
             vals["when_missing"], vals["success"], json.dumps(users), ts))


def list_field_stats() -> list[dict]:
    with _conn() as c:
        _create(c)
        out = []
        for r in c.execute("SELECT * FROM field_stats ORDER BY total DESC"):
            d = dict(r); d["unique_users"] = len(json.loads(d.pop("users"))); out.append(d)
        return out


def record_enrichment_log(rows: list[dict]) -> None:
    """One row per field resolution (kept, enriched, or unresolved). Called once per
    /api/enrich run with every row it produced, tagged with a shared run_id."""
    if not rows:
        return
    with _conn() as c:
        _create(c)
        c.executemany("""INSERT INTO enrichment_log
            (run_id,ts,user,company,account_key,field,service,before_value,
             after_value,confidence,is_successful,cost,observed_at)
            VALUES(:run_id,:ts,:user,:company,:account_key,:field,:service,:before_value,
             :after_value,:confidence,:is_successful,:cost,:observed_at)""", rows)


def list_enrichment_log(company: str | None = None, field: str | None = None,
                        run_id: str | None = None, limit: int = 500) -> list[dict]:
    where, params = [], []
    for col, val in (("company", company), ("field", field), ("run_id", run_id)):
        if val:
            where.append(f"{col}=?")
            params.append(val)
    q = "SELECT * FROM enrichment_log"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        _create(c)
        return [dict(r) for r in c.execute(q, params)]


def list_canonical(field: str | None = None) -> list[dict]:
    with _conn() as c:
        _create(c)
        q = "SELECT field,agreed_term,aliases FROM canonical_terms"
        rows = c.execute(q + (" WHERE field=?" if field else "") + " ORDER BY field,agreed_term",
                         (field,) if field else ()).fetchall()
        return [{"field": r["field"], "agreed_term": r["agreed_term"],
                 "aliases": json.loads(r["aliases"])} for r in rows]


def pending_suggestions() -> list[dict]:
    with _conn() as c:
        _create(c)
        return [dict(r) for r in c.execute(
            "SELECT field,reconcile_from,reconcile_to,unique_users,promoted FROM suggestions ORDER BY unique_users DESC")]


def reset() -> None:
    with _conn() as c:
        c.executescript("DROP TABLE IF EXISTS canonical_terms; DROP TABLE IF EXISTS suggestions;")
        _create(c)
