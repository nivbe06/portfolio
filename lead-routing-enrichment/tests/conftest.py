import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app import db as DB
from app import reconcile as R


@pytest.fixture(autouse=True)
def clean_store(monkeypatch, tmp_path):
    """Every test starts from a cold canonical DB and forces the offline (stub-table)
    LLM path, so results are deterministic regardless of ANTHROPIC_API_KEY.

    The store is redirected to a per-test temp file first. `db.reset()` drops and
    recreates its tables, so without this the suite would wipe the real
    `app/state/terms.db` - including the promoted aliases the demo depends on.
    `db.DB_PATH` is read inside `db._conn()` at call time, so patching it here
    covers every caller.
    """
    monkeypatch.setattr(DB, "DB_PATH", tmp_path / "terms.db")
    monkeypatch.setattr(R, "_client", None)
    R.reset_store()
    yield
    R.reset_store()
