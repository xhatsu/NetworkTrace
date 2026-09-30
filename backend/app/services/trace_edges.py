"""Trace-scoped caller resolution for server transactions.

Service edges are derived per server transaction in this order:

1. ``trace_parent``: ``parent.id`` points at a document in the same trace
   (standard APM/OTel SDK agents). When the parent is an exit span whose peer
   names a different service than the callee, the request crossed an
   uninstrumented hop, and that hop is the direct caller
   (``trace_intermediary``).
2. ``trace_peer_match``: the parent chain is not exported (for example OBI eBPF
   instrumentation propagates ``trace.id`` but not a resolvable parent span).
   A client document in the same trace whose peer names the callee, and whose
   time range contains the callee within the clock-skew tolerance, is the caller.
3. Explicit caller evidence (headers/attributes) is left to the aggregation's
   runtime field and is not overridden here.
4. A request whose caller propagated no trace context (no SDK/agent, or eBPF
   instrumentation that could not inject headers) starts a new trace:
   ``network_ip`` attributes it by socket peer IP, from an operator-configured
   map first, then from IPs that resolved to exactly one caller service through
   steps 1-2 in the same slice. Load balancer, proxy, and NAT IPs are never
   attributed. Otherwise, for a root transaction, ``time_correlated`` pairs it
   with a leftover client call from any trace whose peer names the callee and
   whose time range contains it.
5. Otherwise the transaction keeps an empty caller. No caller is fabricated.

A root transaction that is really a client call (a service with no incoming
trace, such as a load generator or a UI backend) describes the caller side of a
request. If it was paired with the callee's server transaction it is skipped to
avoid double counting, otherwise it is re-targeted to the observed peer so a call
into an uninstrumented service stays visible as ``caller -> peer``. Peers that
are not observed services (external hosts) keep their full host name.
"""
from __future__ import annotations

import bisect
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.app.services.normalization import classify_source_ip_role


INFRASTRUCTURE_ROLES = {"load_balancer", "reverse_proxy", "nat_gateway"}
DEFAULT_SKEW_US = 250_000
# Longest client call considered when pairing requests across traces.
MAX_CORRELATED_CALL_US = 60_000_000


@dataclass
class TraceDoc:
    doc_id: str
    trace_id: str
    kind: str  # server | client | internal
    service: str
    parent_id: Optional[str] = None
    peer: str = ""
    peer_host: str = ""
    start_us: int = 0
    end_us: int = 0
    client_ip: str = ""
    explicit_caller: str = ""
    root_client: bool = False


@dataclass
class Resolution:
    caller: Optional[str] = None  # None: keep explicit evidence; "": no caller
    method: str = "none"
    target: Optional[str] = None
    skip: bool = False


@dataclass
class ResolvedSlice:
    resolutions: Dict[str, Resolution] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=dict)

    def callers(self) -> Dict[str, str]:
        return {doc_id: r.caller for doc_id, r in self.resolutions.items()
                if r.caller is not None and not r.skip and r.target is None}

    def targets(self) -> Dict[str, str]:
        return {doc_id: r.target for doc_id, r in self.resolutions.items() if r.target and not r.skip}

    def target_callers(self) -> Dict[str, str]:
        return {doc_id: r.caller or "" for doc_id, r in self.resolutions.items() if r.target and not r.skip}

    def skipped(self) -> Dict[str, bool]:
        return {doc_id: True for doc_id, r in self.resolutions.items() if r.skip}


def peer_host(value: Any) -> str:
    """Return the lower-case host of a peer name, host:port, or URL."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text).split("/", 1)[0]
    if text.startswith("["):
        return text.split("]", 1)[0].lstrip("[")
    if text.count(":") == 1:
        text = text.split(":", 1)[0]
    return text


def normalize_peer(value: Any) -> str:
    """Reduce a peer name, host:port, URL, or cluster DNS name to a service key."""
    text = peer_host(value)
    try:
        ipaddress.ip_address(text)
        return text
    except ValueError:
        pass
    return text.split(".", 1)[0]


def _first(source: Dict[str, Any], *paths: str) -> Any:
    for path in paths:
        if path in source and source[path] not in (None, ""):
            return source[path]
        value: Any = source
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                break
        if isinstance(value, list):
            value = value[0] if value else None
        if value not in (None, ""):
            return value
    return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def doc_from_source(source: Dict[str, Any], explicit_caller: Any = None) -> Optional[TraceDoc]:
    """Build a TraceDoc from an Elastic APM or flattened OTel document."""
    trace_id = str(_first(source, "trace.id", "trace_id", "traceId") or "").strip().lower()
    service = str(_first(source, "service.name", "service_name") or "").strip()
    event = str(_first(source, "processor.event") or "").strip().lower()
    doc_id = _first(source, "transaction.id", "span.id", "span_id", "spanId")
    if not trace_id or not service or not doc_id:
        return None
    parent_id = _first(source, "parent.id", "parent_span_id", "parentSpanId")
    raw_peer = _first(
        source, "labels.service_peer_name", "peer.service", "labels.net_peer_service",
        "span.destination.service.resource", "labels.server_address", "labels.url_full",
    )
    peer = normalize_peer(raw_peer)
    span_kind = str(_first(source, "span_kind", "span.kind", "kind") or "").strip().lower()
    own = normalize_peer(service)
    root_client = False
    if event == "transaction":
        kind = "server"
        # Only client-side documents carry a peer service name; a root one is a
        # call made by a service that received no trace context.
        if span_kind == "client" or (not parent_id and peer and peer != own
                                     and _first(source, "labels.service_peer_name", "peer.service")):
            kind, root_client = "client", True
    elif event == "span":
        kind = "client" if (peer or span_kind == "client") else "internal"
    elif span_kind in ("server", "consumer"):
        kind = "server"
    elif span_kind in ("client", "producer"):
        kind = "client"
    else:
        kind = "internal"
    if kind == "server":
        # The server-side address names the callee itself; it is not a peer.
        peer = raw_peer = ""
    start_us = _int(_first(source, "timestamp.us"))
    if not start_us:
        start_us = _int(_first(source, "timestamp_ms")) * 1000
    duration_us = _int(_first(source, "transaction.duration.us", "span.duration.us"))
    if not duration_us:
        duration_us = int(float(_first(source, "duration_ms") or 0) * 1000)
    client_ip = str(_first(
        source, "labels.net_sock_peer_addr", "labels.network_peer_address", "labels.client_address",
        "client.ip", "source.ip",
    ) or "").strip()
    caller = explicit_caller[0] if isinstance(explicit_caller, list) and explicit_caller else explicit_caller
    return TraceDoc(
        doc_id=str(doc_id), trace_id=trace_id, kind=kind, service=service,
        parent_id=str(parent_id) if parent_id else None, peer=peer, peer_host=peer_host(raw_peer),
        start_us=start_us, end_us=start_us + max(0, duration_us), client_ip=client_ip,
        explicit_caller=str(caller or "").strip(), root_client=root_client,
    )


def parse_ip_map(spec: str) -> List[Tuple[Any, str]]:
    """Parse ``ip_or_cidr=service`` pairs separated by commas or whitespace."""
    entries: List[Tuple[Any, str]] = []
    for item in re.split(r"[,\s]+", spec or ""):
        if "=" not in item:
            continue
        network, service = item.split("=", 1)
        try:
            entries.append((ipaddress.ip_network(network.strip(), strict=False), service.strip()))
        except ValueError:
            continue
    return [entry for entry in entries if entry[1]]


def _lookup_ip(ip: str, entries: List[Tuple[Any, str]]) -> Optional[str]:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    matches = [(net.prefixlen, svc) for net, svc in entries if address.version == net.version and address in net]
    return max(matches)[1] if matches else None


def _attributable_ip(ip: str) -> bool:
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    return classify_source_ip_role(ip)[0] not in INFRASTRUCTURE_ROLES


def resolve(
    docs: Iterable[TraceDoc],
    targets: Optional[Iterable[str]] = None,
    ip_map: Optional[List[Tuple[Any, str]]] = None,
    skew_us: int = DEFAULT_SKEW_US,
) -> ResolvedSlice:
    """Resolve callers for server transactions and root client documents.

    ``targets`` limits which document IDs receive resolutions; other documents
    only provide context (for example spans just before the slice).
    """
    by_trace: Dict[str, List[TraceDoc]] = {}
    for doc in docs:
        by_trace.setdefault(doc.trace_id, []).append(doc)
    wanted = set(targets) if targets is not None else None
    result = ResolvedSlice()
    stats = {key: 0 for key in (
        "trace_parent", "trace_intermediary", "trace_peer_match", "network_ip", "time_correlated",
        "explicit", "unresolved", "client_skipped", "client_retargeted",
    )}
    pending: List[TraceDoc] = []
    learned: Dict[str, set] = {}
    used: set = set()
    # Peers are normalized keys; display them with an observed service's spelling,
    # or the full host for peers that are not observed services (external hosts).
    known = {normalize_peer(doc.service): doc.service for docs_ in by_trace.values() for doc in docs_}

    def display(doc: TraceDoc) -> str:
        return known.get(doc.peer) or doc.peer_host or doc.peer

    def contains(client: TraceDoc, server: TraceDoc) -> bool:
        return client.start_us - skew_us <= server.start_us and server.end_us <= client.end_us + skew_us

    def tightest(candidates: Iterable[TraceDoc], server: TraceDoc) -> Optional[TraceDoc]:
        own = normalize_peer(server.service)
        best: Optional[TraceDoc] = None
        for client in candidates:
            if client.doc_id in used or client.peer != own or client.service == server.service:
                continue
            if contains(client, server) and (
                    best is None or (client.end_us - client.start_us) < (best.end_us - best.start_us)):
                best = client
        return best

    for trace_docs in by_trace.values():
        index = {doc.doc_id: doc for doc in trace_docs}
        servers = sorted((d for d in trace_docs if d.kind == "server"), key=lambda d: d.start_us)
        clients = [d for d in trace_docs if d.kind == "client" and d.peer]
        for server in servers:
            resolution: Optional[Resolution] = None
            own = normalize_peer(server.service)
            parent = index.get(server.parent_id or "")
            if parent is not None:
                if parent.kind == "client" and parent.peer and parent.peer != own:
                    resolution = Resolution(display(parent), "trace_intermediary")
                elif parent.service != server.service:
                    if parent.kind == "server" and server.explicit_caller \
                            and server.explicit_caller != parent.service:
                        # The context crossed a hop that exported no client span and
                        # the callee names its direct caller explicitly.
                        resolution = None
                    else:
                        resolution = Resolution(parent.service, "trace_parent")
                else:
                    resolution = Resolution("", "trace_parent")
                if parent.kind == "client":
                    used.add(parent.doc_id)
            if resolution is None:
                best = tightest(clients, server)
                if best is not None:
                    used.add(best.doc_id)
                    resolution = Resolution(best.service, "trace_peer_match")
            in_scope = wanted is None or server.doc_id in wanted
            if resolution is not None:
                stats[resolution.method] += in_scope
                if resolution.caller and resolution.method != "trace_intermediary" and _attributable_ip(server.client_ip):
                    learned.setdefault(server.client_ip, set()).add(resolution.caller)
                if in_scope:
                    result.resolutions[server.doc_id] = resolution
            elif server.explicit_caller:
                stats["explicit"] += in_scope
            elif in_scope:
                pending.append(server)

    # Requests without usable trace context: the caller propagated none (no SDK
    # or agent), or its context was dropped on the way.
    leftovers: Dict[str, List[TraceDoc]] = {}
    for docs_ in by_trace.values():
        for doc in docs_:
            if doc.kind == "client" and doc.peer and doc.doc_id not in used:
                leftovers.setdefault(doc.peer, []).append(doc)
    starts: Dict[str, List[int]] = {}
    for peer, calls in leftovers.items():
        calls.sort(key=lambda d: d.start_us)
        starts[peer] = [d.start_us for d in calls]

    def overlapping(server: TraceDoc) -> List[TraceDoc]:
        peer = normalize_peer(server.service)
        calls = leftovers.get(peer, [])
        lo = bisect.bisect_left(starts.get(peer, []), server.start_us - MAX_CORRELATED_CALL_US)
        hi = bisect.bisect_right(starts.get(peer, []), server.start_us + skew_us)
        return calls[lo:hi]
    for server in sorted(pending, key=lambda d: d.start_us):
        caller, method = None, "network_ip"
        if _attributable_ip(server.client_ip):
            caller = _lookup_ip(server.client_ip, ip_map or [])
            if caller is None and len(learned.get(server.client_ip, ())) == 1:
                caller = next(iter(learned[server.client_ip]))
        if not caller and not server.parent_id:
            # A root request: a client call from another trace spanning it is the
            # caller that propagated no context.
            best = tightest(overlapping(server), server)
            if best is not None:
                used.add(best.doc_id)
                caller, method = best.service, "time_correlated"
        if caller and caller != server.service:
            stats[method] += 1
            result.resolutions[server.doc_id] = Resolution(caller, method)
        else:
            stats["unresolved"] += 1

    for docs_ in by_trace.values():
        for client in docs_:
            if not client.root_client or not client.peer or (wanted is not None and client.doc_id not in wanted):
                continue
            if client.doc_id in used:
                # The callee's server transaction already counts this request.
                result.resolutions[client.doc_id] = Resolution(skip=True, method="client_skipped")
                stats["client_skipped"] += 1
            else:
                # Only record of a call into an uninstrumented service.
                result.resolutions[client.doc_id] = Resolution(
                    client.service, "client_retargeted", target=display(client),
                )
                stats["client_retargeted"] += 1
    result.stats = stats
    return result
