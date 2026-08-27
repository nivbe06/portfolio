"""Cube configuration: the tenant boundary.

The design doc claims the semantic layer is a tenant-scoped access boundary, not
just a metric dictionary. This file is where that claim is enforced. Every query
that reaches Cube gets a tenant filter appended from the caller's signed JWT,
before the query is planned. A caller cannot opt out, because the filter is not
part of the query they submitted.

`query_rewrite` rather than per-cube `access_policy` blocks: one visible place
where the rule lives, which is easier to point at in review and harder to leave
half-applied across nine cubes.
"""

from cube import config


# Every view that carries tenant-scoped data. Anything queryable must appear
# here or the request is refused, so adding a view without deciding how it is
# scoped fails closed rather than leaking.
TENANT_SCOPED_VIEWS = {
    "qbr_campaigns",
    "qbr_adoption",
    "qbr_anomalies",
    "qbr_overview",
}


def _referenced_views(query: dict) -> set:
    """Which views this query touches, read off its member names."""
    members = []
    for key in ("measures", "dimensions"):
        members.extend(query.get(key) or [])
    for f in query.get("filters") or []:
        if isinstance(f, dict) and "member" in f:
            members.append(f["member"])
    for td in query.get("timeDimensions") or []:
        if isinstance(td, dict) and "dimension" in td:
            members.append(td["dimension"])
    for order in query.get("order") or []:
        if isinstance(order, (list, tuple)) and order:
            members.append(order[0])

    return {m.split(".")[0] for m in members if isinstance(m, str) and "." in m}


@config("query_rewrite")
def query_rewrite(query: dict, ctx: dict) -> dict:
    security_context = ctx.get("securityContext") or {}
    tenant_id = security_context.get("tenant_id")

    if not tenant_id:
        raise Exception(
            "tenant_id claim is required. Every query must arrive with a signed "
            "tenant identity; there is no unscoped read path."
        )

    views = _referenced_views(query)
    if not views:
        # No members means nothing to scope. Let Cube reject it on its own terms.
        return query

    unknown = views - TENANT_SCOPED_VIEWS
    if unknown:
        raise Exception(
            f"Refusing to serve un-scoped members: {sorted(unknown)}. "
            "Only tenant-scoped views are queryable."
        )

    # query['filters'] is absent on some query shapes, so guard before appending.
    if not query.get("filters"):
        query["filters"] = []

    for view in sorted(views):
        query["filters"].append({
            "member": f"{view}.tenant_id",
            "operator": "equals",
            "values": [tenant_id],
        })

    return query
