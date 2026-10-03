"""Relationship read model for the User / API / Service workspace pages.

One endpoint answers "who reaches this and what does it reach" for any scope
(a user, an API, a Service, or the whole estate). Every list comes from the
worker's five-minute IP rollup (``topology_principal_ip_5m``), so all numbers on
a page share one source. Each row is compared with the equal-length window
just before the selected one to mark it ``new``, ``active`` or ``silent``.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from backend.app.repositories.db_context import get_connection

router = APIRouter(prefix="/api/v1", tags=["relationships"])

ANONYMOUS_SQL = "('', 'unknown', '-anonymous-', 'anonymous')"
FACETS = ("caller", "principal", "service", "api", "ip")
# Facet key expressions over the normalised base rows (aliases differ from the
# raw column names: ClickHouse resolves same-name aliases wrongly in subqueries).
KEY_SQL = {
    "caller": "caller",
    "principal": "p",
    "service": "svc",
    "api": "svc, op",
    "ip": "ip",
}
BUCKET_SECONDS = 300
# Defaults the Services API shows for services with no catalog metadata.
META_DEFAULTS = {"environment": "production", "group": "Core", "module": "Default"}
META_KEYS = ("environment", "group", "module")
MAX_WINDOW_SECONDS = 31 * 86400


def _seconds(value: Optional[int]) -> Optional[int]:
    if not value:
        return None
    return int(value / 1000) if value > 10_000_000_000 else int(value)


def _window(from_t: Optional[int], to_t: Optional[int]) -> Tuple[int, int, int]:
    end = _seconds(to_t) or int(time.time())
    start = _seconds(from_t) or end - 86400
    if end <= start:
        raise HTTPException(status_code=422, detail="'to' must be after 'from'")
    start = max(start, end - MAX_WINDOW_SECONDS)
    return start, end, start - (end - start)


def _base_sql(where: List[str]) -> str:
    return f"""
        SELECT bucket_start AS b,
          if(principal IN {ANONYMOUS_SQL}, '-anonymous-', principal) AS p,
          if(source_ip = '', 'unknown', source_ip) AS ip,
          service AS svc,
          if(startsWith(api, concat(service, '/')), substring(api, length(service) + 2), api) AS op,
          caller_service AS caller,
          request_count AS rc, error_count AS ec, p95_latency_ms AS lat,
          request_bytes AS rb, response_bytes AS sb, first_seen_ms AS fs, last_seen_ms AS ls,
          is_load_balancer AS lb, source_ip_role AS role, role_label AS rl
        FROM topology_principal_ip_5m FINAL
        WHERE {' AND '.join(where)}
    """


def _service_meta(db: Any) -> Dict[str, Dict[str, str]]:
    """Catalog metadata (environment / group / module) per service, with the Services API defaults."""
    rows = db.execute(
        "SELECT name, argMax(environment, last_seen_ms) AS env, argMax(service_group, last_seen_ms) AS grp, "
        "argMax(service_module, last_seen_ms) AS mdl FROM services GROUP BY name"
    ).fetchall()
    return {
        row[0]: {
            "environment": row[1] or META_DEFAULTS["environment"],
            "group": row[2] or META_DEFAULTS["group"],
            "module": row[3] or META_DEFAULTS["module"],
        }
        for row in rows
    }


def meta_of(meta: Dict[str, Dict[str, str]], name: str) -> Dict[str, str]:
    return meta.get(name) or dict(META_DEFAULTS)


def _meta_clause(meta: Dict[str, Dict[str, str]], wanted: Dict[str, Optional[str]]) -> Tuple[List[str], List[Any]]:
    """Restrict ``service`` to the catalog environment / group / module selection.

    Services missing from the catalog carry the defaults, so they match when every
    requested value is a default.
    """
    wanted = {key: value for key, value in wanted.items() if value}
    if not wanted:
        return [], []
    allowed = [name for name, values in meta.items() if all(values[key] == value for key, value in wanted.items())]
    defaults_match = all(META_DEFAULTS[key] == value for key, value in wanted.items())
    return ["(has(?, service) OR (? = 1 AND NOT has(?, service)))"], [allowed, 1 if defaults_match else 0, list(meta)]


def _scope_clauses(filters: Dict[str, Any], skip: str = "") -> Tuple[List[str], List[Any]]:
    """WHERE clauses on raw rollup columns for every filter except ``skip``.

    ``service`` and ``caller`` accept one value or a list (multi-select).
    """
    clauses: List[str] = []
    args: List[Any] = []
    principal = filters.get("principal")
    if principal and skip != "principal":
        if principal in ("-anonymous-", "unknown", "anonymous"):
            clauses.append(f"principal IN {ANONYMOUS_SQL}")
        else:
            clauses.append("principal = ?")
            args.append(principal)
    service = filters.get("service")
    if service and skip != "service":
        if isinstance(service, list):
            clauses.append("has(?, service)")
        else:
            clauses.append("service = ?")
        args.append(service)
    api = filters.get("api")
    if api and skip != "api":
        api_service = filters.get("api_service") or (service if isinstance(service, str) else "")
        bare = api[len(api_service) + 1:] if api_service and api.startswith(f"{api_service}/") else api
        if api_service:
            clauses.append("service = ? AND api IN (?, ?)")
            args.extend([api_service, bare, f"{api_service}/{bare}"])
        else:
            clauses.append("api = ?")
            args.append(bare)
    caller = filters.get("caller")
    if caller and skip != "caller":
        clauses.append("has(?, caller_service)" if isinstance(caller, list) else "caller_service = ?")
        args.append(caller)
    ip = filters.get("ip")
    if ip and skip != "ip":
        clauses.append("source_ip = ?" if ip != "unknown" else "source_ip IN ('', 'unknown')")
        if ip != "unknown":
            args.append(ip)
    return clauses, args


def _state(current: int, previous: int, history: bool) -> str:
    if not history:
        return "active" if current else "silent"
    if current and not previous:
        return "new"
    if not current and previous:
        return "silent"
    return "active"


def _facet(db: Any, facet: str, locked: Dict[str, Any], selected: Dict[str, Any],
           start: int, end: int, prev_start: int, history: bool, limit: int, q: Optional[str],
           anonymous_only: bool = False, meta_filter: Tuple[List[str], List[Any]] = ([], []),
           meta: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Any]:
    clauses, args = _scope_clauses(locked)
    sel_clauses, sel_args = _scope_clauses(selected, skip=facet)
    where = ["bucket_start >= ?", "bucket_start < ?", *clauses, *sel_clauses, *meta_filter[0]]
    where_args: List[Any] = [prev_start, end, *args, *sel_args, *meta_filter[1]]
    if anonymous_only:
        where.append(f"principal IN {ANONYMOUS_SQL}")
    outer: List[str] = []
    outer_args: List[Any] = []
    if facet == "principal" and not anonymous_only:
        outer.append("p != '-anonymous-'")
    if facet == "caller":
        outer.append("caller != ''")
    if q:
        outer.append("positionCaseInsensitive(concat(svc, ' ', op), ?) > 0" if facet == "api" else f"positionCaseInsensitive({KEY_SQL[facet]}, ?) > 0")
        outer_args.append(q)
    cur = f"b >= {int(start)}"
    sql = f"""
        SELECT {KEY_SQL[facet]},
          sumIf(rc, {cur}) AS requests, sumIf(ec, {cur}) AS errors, maxIf(lat, {cur}) AS p95_ms,
          sumIf(rb, {cur}) AS request_bytes, sumIf(sb, {cur}) AS response_bytes,
          minIf(fs, {cur} AND fs > 0) AS first_seen_ms, maxIf(ls, {cur}) AS last_seen_ms,
          sumIf(rc, b < {int(start)}) AS prev_requests, max(ls) AS last_ever_ms,
          uniqExactIf(p, {cur} AND p != '-anonymous-') AS principals,
          sumIf(rc, {cur} AND p = '-anonymous-') AS unknown_requests,
          uniqExactIf(caller, {cur} AND caller != '') AS callers,
          uniqExactIf((svc, op), {cur}) AS apis, uniqExactIf(svc, {cur}) AS services,
          uniqExactIf(ip, {cur}) AS ips,
          max(lb) AS is_load_balancer, any(role) AS ip_role, any(rl) AS ip_role_label,
          count() OVER () AS total_rows
        FROM ({_base_sql(where)})
        {('WHERE ' + ' AND '.join(outer)) if outer else ''}
        GROUP BY {KEY_SQL[facet]}
        HAVING requests > 0 OR prev_requests > 0
        ORDER BY requests DESC, prev_requests DESC, {KEY_SQL[facet]}
        LIMIT ?
    """
    rows = [dict(row) for row in db.execute(sql, [*where_args, *outer_args, limit])]
    duration = max(1, end - start)
    items = []
    for row in rows:
        requests = int(row.get("requests") or 0)
        item = {
            "name": row.get("op") if facet == "api" else row.get(KEY_SQL[facet]),
            "requests": requests,
            "errors": int(row.get("errors") or 0),
            "error_rate": round((row.get("errors") or 0) / requests, 4) if requests else 0.0,
            "tps": round(requests / duration, 6),
            "p95_ms": round(float(row.get("p95_ms") or 0), 2),
            "request_bytes": int(row.get("request_bytes") or 0),
            "response_bytes": int(row.get("response_bytes") or 0),
            "first_seen_ms": int(row.get("first_seen_ms") or 0) or None,
            "last_seen_ms": int(row.get("last_seen_ms") or row.get("last_ever_ms") or 0) or None,
            "prev_requests": int(row.get("prev_requests") or 0),
            "state": _state(requests, int(row.get("prev_requests") or 0), history),
            "principals": int(row.get("principals") or 0),
            "unknown_requests": int(row.get("unknown_requests") or 0),
            "callers": int(row.get("callers") or 0),
            "apis": int(row.get("apis") or 0),
            "services": int(row.get("services") or 0),
            "ips": int(row.get("ips") or 0),
        }
        if facet == "api":
            item["service"] = row.get("svc")
        if facet in ("service", "caller") and meta is not None:
            item.update(meta_of(meta, item["name"]))
        if facet == "ip":
            item.update({
                "is_load_balancer": bool(row.get("is_load_balancer")),
                "role": row.get("ip_role") or "unknown",
                "role_label": row.get("ip_role_label") or "",
            })
        items.append(item)
    total = int(rows[0].get("total_rows") or 0) if rows else 0
    return {"total": total, "items": items, "truncated": total > len(items)}


def _shared_ips(db: Any, principal: str, start: int, end: int, limit: int) -> Dict[str, Any]:
    """Other identities (and unknown traffic) seen on this user's non-infrastructure IPs."""
    sql = f"""
        SELECT p, uniqExact(ip) AS shared_ips, sum(rc) AS requests, max(ls) AS last_seen_ms,
          groupUniqArray(5)(ip) AS sample_ips, count() OVER () AS total_rows
        FROM ({_base_sql(["bucket_start >= ?", "bucket_start < ?"])})
        WHERE p != ? AND lb = 0 AND ip NOT IN ('unknown', '') AND ip IN (
          SELECT source_ip FROM topology_principal_ip_5m FINAL
          WHERE bucket_start >= ? AND bucket_start < ? AND principal = ? AND is_load_balancer = 0
        )
        GROUP BY p ORDER BY shared_ips DESC, requests DESC, p LIMIT ?
    """
    rows = [dict(row) for row in db.execute(sql, [start, end, principal, start, end, principal, limit])]
    items = [{
        "name": row.get("p"),
        "unknown": row.get("p") == "-anonymous-",
        "shared_ips": int(row.get("shared_ips") or 0),
        "requests": int(row.get("requests") or 0),
        "last_seen_ms": int(row.get("last_seen_ms") or 0) or None,
        "sample_ips": list(row.get("sample_ips") or []),
    } for row in rows]
    total = int(rows[0].get("total_rows") or 0) if rows else 0
    return {"total": total, "items": items, "truncated": total > len(items)}


def _summary_and_series(db: Any, locked: Dict[str, Any], selected: Dict[str, Any],
                        start: int, end: int, prev_start: int,
                        meta_filter: Tuple[List[str], List[Any]] = ([], [])) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    clauses, args = _scope_clauses({**locked, **{k: v for k, v in selected.items() if v}})
    clauses, args = [*clauses, *meta_filter[0]], [*args, *meta_filter[1]]
    base = _base_sql(["bucket_start >= ?", "bucket_start < ?", *clauses])
    cur = f"b >= {int(start)}"
    row = db.execute(f"""
        SELECT sumIf(rc, {cur}) AS requests, sumIf(ec, {cur}) AS errors, maxIf(lat, {cur}) AS p95_ms,
          sumIf(rb, {cur}) AS request_bytes, sumIf(sb, {cur}) AS response_bytes,
          sumIf(rc, b < {int(start)}) AS prev_requests,
          sumIf(rc, {cur} AND p = '-anonymous-') AS unknown_requests,
          uniqExactIf(ip, {cur} AND p = '-anonymous-') AS unknown_ips,
          uniqExactIf(p, {cur} AND p != '-anonymous-') AS principals,
          uniqExactIf(caller, {cur} AND caller != '') AS callers,
          uniqExactIf((svc, op), {cur}) AS apis, uniqExactIf(svc, {cur}) AS services,
          uniqExactIf(ip, {cur}) AS ips,
          minIf(fs, {cur} AND fs > 0) AS first_seen_ms, maxIf(ls, {cur}) AS last_seen_ms
        FROM ({base})
    """, [prev_start, end, *args]).fetchone()
    summary = {key: (row[key] if row else 0) for key in (
        "requests", "errors", "p95_ms", "request_bytes", "response_bytes", "prev_requests",
        "unknown_requests", "unknown_ips", "principals", "callers", "apis", "services", "ips",
        "first_seen_ms", "last_seen_ms",
    )}
    summary = {key: (float(value) if key == "p95_ms" else int(value or 0)) for key, value in summary.items()}
    summary["error_rate"] = round(summary["errors"] / summary["requests"], 4) if summary["requests"] else 0.0
    summary["tps"] = round(summary["requests"] / max(1, end - start), 6)
    series_rows = db.execute(f"""
        SELECT b, sum(rc) AS req_total, sum(ec) AS err_total, sum(rb) AS rb_total, sum(sb) AS sb_total,
          countIf(rb > 0) AS rb_samples, countIf(sb > 0) AS sb_samples
        FROM ({base}) WHERE {cur} GROUP BY b ORDER BY b
    """, [prev_start, end, *args]).fetchall()
    series = []
    for point in series_rows:
        point = dict(point)
        series.append({
            "timestamp_ms": int(point["b"]) * 1000,
            "requests": int(point["req_total"] or 0),
            "errors": int(point["err_total"] or 0),
            "request_bytes_per_second": round((point["rb_total"] or 0) / BUCKET_SECONDS, 3),
            "response_bytes_per_second": round((point["sb_total"] or 0) / BUCKET_SECONDS, 3),
            "bandwidth_bytes_per_second": round(((point["rb_total"] or 0) + (point["sb_total"] or 0)) / BUCKET_SECONDS, 3),
            "request_bytes_samples": int(point["rb_samples"] or 0),
            "response_bytes_samples": int(point["sb_samples"] or 0),
            "bandwidth_available": bool(point["rb_samples"] or point["sb_samples"]),
        })
    return summary, series


def _meta_options(db: Any, locked: Dict[str, Any], meta: Dict[str, Dict[str, str]], wanted: Dict[str, Optional[str]],
                  start: int, end: int) -> Dict[str, List[Dict[str, Any]]]:
    """Dropdown values with service counts; each level is counted within the levels above it."""
    clauses, args = _scope_clauses(locked)
    rows = db.execute(
        f"SELECT DISTINCT service FROM topology_principal_ip_5m WHERE {' AND '.join(['bucket_start >= ?', 'bucket_start < ?', *clauses])}",
        [start, end, *args],
    ).fetchall()
    services = [meta_of(meta, row[0]) for row in rows]
    options: Dict[str, List[Dict[str, Any]]] = {}
    for depth, key in enumerate(META_KEYS):
        above = META_KEYS[:depth]
        counts: Dict[str, int] = {}
        for values in services:
            if all(not wanted.get(level) or values[level] == wanted[level] for level in above):
                counts[values[key]] = counts.get(values[key], 0) + 1
        options[key] = [{"value": value, "services": count} for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return options


@router.get("/relationships")
def relationships(
    principal: Optional[str] = Query(None, max_length=200, description="Lock the scope to one user (use -anonymous- for unknown users)"),
    service: Optional[str] = Query(None, max_length=200, description="Lock the scope to one Service"),
    api: Optional[str] = Query(None, max_length=500, description="Lock the scope to one API (needs service)"),
    sel_caller: Optional[List[str]] = Query(None, description="One or more caller services"),
    sel_principal: Optional[str] = Query(None, max_length=200),
    sel_service: Optional[List[str]] = Query(None, description="One or more services"),
    sel_environment: Optional[str] = Query(None, max_length=200),
    sel_group: Optional[str] = Query(None, max_length=200),
    sel_module: Optional[str] = Query(None, max_length=200),
    sel_api: Optional[str] = Query(None, max_length=500),
    sel_api_service: Optional[str] = Query(None, max_length=200),
    sel_ip: Optional[str] = Query(None, max_length=200),
    facets: str = Query(",".join(FACETS), max_length=200),
    q: Optional[str] = Query(None, max_length=200, description="Case-insensitive name search applied to every facet"),
    limit: int = Query(100, ge=1, le=1000),
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
) -> Dict[str, Any]:
    """Neighbour lists of one scope from the five-minute IP rollup.

    Locked filters (``principal``, ``service``, ``api``) define the page; ``sel_*``
    filters are the operator's row selection. A facet ignores the selection on its
    own dimension, so the clicked list keeps its siblings.
    """
    if api and not service:
        raise HTTPException(status_code=422, detail="'api' requires 'service'")
    wanted = [name.strip() for name in facets.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in (*FACETS, "unknown_ip", "shared")]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown facets: {', '.join(unknown)}")
    start, end, prev_start = _window(from_time, to_time)
    locked = {"principal": principal, "service": service, "api": api, "api_service": service if api else None}
    def clean(values: Optional[List[str]]) -> Optional[List[str]]:
        values = [value for value in (values or []) if value][:500]
        return values or None

    selected = {"caller": clean(sel_caller), "principal": sel_principal, "service": clean(sel_service),
                "api": sel_api, "api_service": sel_api_service, "ip": sel_ip}
    wanted_meta = {"environment": sel_environment, "group": sel_group, "module": sel_module}
    with get_connection() as db:
        earliest = db.execute("SELECT min(bucket_start) FROM topology_principal_ip_5m").fetchone()
        history = bool(earliest and earliest[0] and int(earliest[0]) <= prev_start + BUCKET_SECONDS)
        meta = _service_meta(db)
        meta_filter = _meta_clause(meta, wanted_meta)
        summary, series = _summary_and_series(db, locked, selected, start, end, prev_start, meta_filter)
        options = _meta_options(db, locked, meta, wanted_meta, start, end)
        result: Dict[str, Any] = {}
        for name in wanted:
            if name == "shared":
                if principal and principal not in ("-anonymous-", "unknown", "anonymous"):
                    result["shared"] = _shared_ips(db, principal, start, end, limit)
                continue
            if name == "unknown_ip":
                result["unknown_ip"] = _facet(db, "ip", locked, selected, start, end, prev_start, history, limit, q,
                                              anonymous_only=True, meta_filter=meta_filter)
                continue
            result[name] = _facet(db, name, locked, selected, start, end, prev_start, history, limit, q,
                                  meta_filter=meta_filter, meta=meta)
    return {
        "window": {"start_ms": start * 1000, "end_ms": end * 1000, "previous_start_ms": prev_start * 1000,
                   "history_available": history},
        "scope": {key: value for key, value in locked.items() if value and key != "api_service"},
        "selection": {**{key: value for key, value in selected.items() if value},
                      **{key: value for key, value in wanted_meta.items() if value}},
        "service_meta_options": options,
        "summary": summary,
        "series": series,
        "facets": result,
    }





# Link ends for /relationships/links: (kind expression, name expression) over the base aliases.
# "origin" is where a request came from: the caller service, or the source IP when no caller
# service was recorded.
LINK_ENDS = {
    "origin": ("if(caller != '', 'service', 'ip')", "if(caller != '', caller, ip)"),
    "caller": ("'service'", "caller"),
    "principal": ("if(p = '-anonymous-', 'unknown', 'user')", "p"),
    "ip": ("'ip'", "ip"),
    "service": ("'service'", "svc"),
    "api": ("'api'", "concat(svc, char(31), op)"),  # split into service + api below
}


@router.get("/relationships/links")
def relationship_links(
    left: str = Query(..., description="One of origin, caller, principal, ip, service, api"),
    right: str = Query(..., description="One of origin, caller, principal, ip, service, api"),
    principal: Optional[str] = Query(None, max_length=200),
    service: Optional[str] = Query(None, max_length=200),
    api: Optional[str] = Query(None, max_length=500, description="Lock the scope to one API (needs service)"),
    sel_principal: Optional[str] = Query(None, max_length=200),
    limit: int = Query(2000, ge=1, le=5000),
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
) -> Dict[str, Any]:
    """Request counts per (left, right) pair inside one scope, e.g. origin -> user for one API.

    Unknown users are one ``-anonymous-`` row of kind ``unknown``. Origins without a caller
    service are their source IP (kind ``ip``) with its role.
    """
    if left not in LINK_ENDS or right not in LINK_ENDS or left == right:
        raise HTTPException(status_code=422, detail=f"'left' and 'right' must be two different values of {', '.join(LINK_ENDS)}")
    if api and not service:
        raise HTTPException(status_code=422, detail="'api' requires 'service'")
    start, end, prev_start = _window(from_time, to_time)
    scope = {"principal": sel_principal or principal, "service": service, "api": api, "api_service": service if api else None}
    if principal and sel_principal and principal != sel_principal:
        return {"window": {"start_ms": start * 1000, "end_ms": end * 1000, "previous_start_ms": prev_start * 1000,
                           "history_available": False}, "links": [], "truncated": False}
    clauses, args = _scope_clauses(scope)
    (lk, lv), (rk, rv) = LINK_ENDS[left], LINK_ENDS[right]
    cur = f"b >= {int(start)}"
    sql = f"""
        SELECT {lk} AS left_kind, {lv} AS left_name, {rk} AS right_kind, {rv} AS right_name,
          sumIf(rc, {cur}) AS requests, sumIf(rc, b < {int(start)}) AS prev_requests,
          max(lb) AS any_lb, anyIf(role, role != '') AS ip_role, anyIf(rl, rl != '') AS ip_role_label,
          count() OVER () AS total_rows
        FROM ({_base_sql(['bucket_start >= ?', 'bucket_start < ?', *clauses])})
        WHERE ({lv}) != '' AND ({rv}) != ''
        GROUP BY left_kind, left_name, right_kind, right_name
        HAVING requests > 0 OR prev_requests > 0
        ORDER BY requests DESC, prev_requests DESC, left_name, right_name
        LIMIT ?
    """
    with get_connection() as db:
        earliest = db.execute("SELECT min(bucket_start) FROM topology_principal_ip_5m").fetchone()
        history = bool(earliest and earliest[0] and int(earliest[0]) <= prev_start + BUCKET_SECONDS)
        rows = [dict(row) for row in db.execute(sql, [prev_start, end, *args, limit])]
    links = []
    for row in rows:
        requests, previous = int(row.get("requests") or 0), int(row.get("prev_requests") or 0)
        link = {
            "left_kind": row["left_kind"], "left": row["left_name"],
            "right_kind": row["right_kind"], "right": row["right_name"],
            "requests": requests, "prev_requests": previous, "state": _state(requests, previous, history),
        }
        for side in ("left", "right"):
            if link[f"{side}_kind"] == "api":
                link[f"{side}_service"], _, link[side] = link[side].partition("\x1f")
        if "ip" in (row["left_kind"], row["right_kind"]):
            link.update({"is_load_balancer": bool(row.get("any_lb")), "role": row.get("ip_role") or "unknown",
                         "role_label": row.get("ip_role_label") or ""})
        links.append(link)
    total = int(rows[0].get("total_rows") or 0) if rows else 0
    return {
        "window": {"start_ms": start * 1000, "end_ms": end * 1000, "previous_start_ms": prev_start * 1000,
                   "history_available": history},
        "links": links,
        "truncated": total > len(links),
    }
