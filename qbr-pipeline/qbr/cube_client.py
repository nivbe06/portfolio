"""Talk to Cube.

Two things matter here.

First, queries are built from bundle manifests, never composed by a model. The
build_query function below is the entire translation layer: YAML in, Cube JSON
out, deterministically. A model chooses which manifest to run and nothing else.

Second, every request carries a signed JWT naming one tenant. The token is the
only thing that decides which account's data comes back, and cube.py appends the
matching filter server-side. A caller cannot widen its own scope.
"""

from __future__ import annotations

import os
import time
from typing import Any

import jwt
import requests

CUBE_URL = os.environ.get("CUBE_URL", "http://localhost:4000")
CUBE_API_SECRET = os.environ.get("CUBEJS_API_SECRET", "dev-secret-not-for-production")
LOAD_ENDPOINT = f"{CUBE_URL}/cubejs-api/v1/load"
META_ENDPOINT = f"{CUBE_URL}/cubejs-api/v1/meta"


class CubeError(RuntimeError):
    pass


def token_for(tenant_id: str) -> str:
    """Sign a tenant claim. This is the whole access decision."""
    return jwt.encode({"tenant_id": tenant_id}, CUBE_API_SECRET, algorithm="HS256")


def _headers(tenant_id: str) -> dict[str, str]:
    # Cube expects the raw token on Authorization, with no Bearer prefix.
    return {
        "Authorization": token_for(tenant_id),
        "Content-Type": "application/json",
    }


def meta(tenant_id: str = "acme-commerce") -> dict:
    r = requests.get(META_ENDPOINT, headers=_headers(tenant_id), timeout=30)
    r.raise_for_status()
    return r.json()


def run_query(query: dict, tenant_id: str, timeout: int = 60) -> list[dict]:
    """Execute one Cube query and return flat rows with short column names.

    Cube can answer HTTP 200 with {"error": "Continue wait"} while it warms a
    query, which is a poll instruction rather than a failure.
    """
    deadline = time.time() + timeout
    attempt = 0

    while True:
        attempt += 1
        r = requests.post(
            LOAD_ENDPOINT,
            headers=_headers(tenant_id),
            json={"query": query},
            timeout=timeout,
        )

        if r.status_code >= 400:
            raise CubeError(f"Cube returned {r.status_code}: {r.text[:500]}")

        body = r.json()
        err = body.get("error")

        if err == "Continue wait":
            if time.time() > deadline:
                raise CubeError("Cube kept asking to wait past the timeout")
            time.sleep(min(1.0 * attempt, 4.0))
            continue

        if err:
            raise CubeError(str(err))

        # compareDateRange responses arrive as results[]; everything else as data.
        if "results" in body:
            rows: list[dict] = []
            for result in body["results"]:
                rows.extend(result.get("data", []))
        else:
            rows = body.get("data", [])

        return [_strip_view_prefix(row) for row in rows]


def _strip_view_prefix(row: dict) -> dict:
    """Cube returns members as 'view.member'. Bundles refer to plain names."""
    out = {}
    for key, value in row.items():
        out[key.split(".", 1)[-1] if "." in key else key] = value
    return out


def build_query(spec: dict, params: dict[str, Any]) -> dict:
    """Turn a bundle manifest query block into a Cube query.

    This is the deterministic boundary. Everything a model contributes has
    already happened by the time this runs: it picked a bundle id. The measures,
    dimensions, filters and ordering all come from YAML written by a human.
    """
    view = spec["view"]

    def qualify(member: str) -> str:
        return member if "." in member else f"{view}.{member}"

    query: dict[str, Any] = {}

    if spec.get("measures"):
        query["measures"] = [qualify(m) for m in spec["measures"]]
    if spec.get("dimensions"):
        query["dimensions"] = [qualify(d) for d in spec["dimensions"]]

    filters = []
    for f in spec.get("filters") or []:
        values = [_substitute(v, params) for v in f.get("values", [])]
        filters.append({
            "member": qualify(f["member"]),
            "operator": f.get("operator", "equals"),
            "values": values,
        })
    if filters:
        query["filters"] = filters

    if spec.get("order"):
        query["order"] = [[qualify(member), direction]
                          for member, direction in spec["order"]]

    query["limit"] = spec.get("limit", 500)
    return query


def _substitute(value: Any, params: dict[str, Any]) -> Any:
    """Fill {quarter} style placeholders from wizard parameters.

    Only whole-token substitution, and only from the wizard's own deterministic
    parameters. There is no path from free text into a query here.
    """
    if not isinstance(value, str):
        return value
    if value.startswith("{") and value.endswith("}"):
        key = value[1:-1]
        if key not in params:
            raise KeyError(f"Bundle referenced unknown parameter '{key}'")
        return params[key]
    return value
