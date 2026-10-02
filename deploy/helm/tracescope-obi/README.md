# tracescope-obi

OBI (OpenTelemetry eBPF Instrumentation) DaemonSet plus an OpenTelemetry Collector
that feeds TraceScope. Install it separately from the `tracescope` chart because OBI
needs privileged, cluster-scoped access (hostPID, hostNetwork, ClusterRole).

```sh
helm upgrade --install tracescope-obi deploy/helm/tracescope-obi -n tracescope \
  -f my-values.yaml
```

## Modes

| Setting | Values | Meaning |
|---|---|---|
| `obi.variant` | `standard` (default) | Upstream `otel/ebpf-instrument`: headers + JSON bodies. |
| | `custom` | `xhatsu101/ebpf-instrument` fork with XML body extraction. Only for SOAP/XML workloads (WSSE username in the body). Current build is arm64 only. |
| `obi.bodyCapture.enabled` | `true` / `false` | Capture request/response bodies (`request`/`response` sub-switches and `methods`). Off means no payloads leave the node. |
| `collector.exporter.mode` | `elk` (default) | Collector → Elastic APM Server → Elasticsearch. TraceScope: `storage.pipelineMode=elk_to_clickhouse`. |
| | `tracescope` | Collector → TraceScope `/v1/traces` (OTLP/HTTP) → ClickHouse. TraceScope: `storage.pipelineMode=clickhouse`, `elasticsearch.syncEnabled=false`, `storage.clickhouseOnlyAgentTraces=false`. |

`tracescope` mode needs no custom ingestion: TraceScope's own OTLP receiver accepts
protobuf or JSON with gzip. The collector's ClickHouse exporter is not used because it
writes its own `otel_traces` schema, which TraceScope does not read.

## Instrumentation targets

`obi.discovery.instrument` / `obi.discovery.excludeInstrument` are rendered verbatim
into OBI `discovery`; `obi.discovery.extra` adds other discovery keys, and
`obi.extraConfig` deep-merges any raw OBI config.

```yaml
obi:
  discovery:
    instrument:
      - k8s_namespace: default
      - k8s_namespace: shop
        k8s_deployment_name: "order-*"
      - open_ports: "8080-8089"
    excludeInstrument:
      - k8s_namespace: kube-system
```

## Credential handling

After WSSE usernames are extracted, the collector removes
`http.request.header.authorization` and `http.request.header.x-wsse` by default
(`collector.redaction.*`). `<wsse:Password>` in bodies is always masked.
`collector.redaction.dropBodies=true` removes the bodies after extraction.

Removing `authorization` also removes HTTP Basic usernames, which TraceScope would
otherwise derive. Set `collector.redaction.authorizationHeader=false` if you rely on Basic
auth attribution and accept the credential reaching the backend.

## Generating matching values for both charts

`deploy/helm/render-stack.sh` (POSIX sh) writes values for `tracescope` and `tracescope-obi`
that agree with each other, and with `--render` also writes the `helm template` output.

```sh
deploy/helm/render-stack.sh --mode clickhouse --obi custom --body on \
  --target default --target 'shop/order-*' --exclude kube-system --out ./stack-out --render
```

`--mode clickhouse` turns TraceScope `ingest.enabled` on, sets `pipelineMode=clickhouse` and
disables Elasticsearch, then points the collector at `<release>-ingest:30103` with batches
capped at 5000 spans and bodies dropped. `--mode elk` keeps ingest off and ES sync on.

### How clickhouse mode attributes callers

The direct OTLP path has no APM server to resolve callers, so TraceScope does it before
aggregating each slice (`backend/app/services/trace_edge_resolution.py`, same rules as the
ELK path's `trace_edges.py`): a server span takes its caller from the matching client span in
the same trace (or its parent span), then from `OTEL_SERVICE_IP_MAP`, then from an
overlapping client call in another trace. Client and internal spans are not counted as
requests. A root client call with no matching server span becomes `caller -> peer`
(external hosts keep their host name). Operations are canonical (`POST /api/v1/orders/{id}`)
and request/response bytes come from `http.*.body.size`.

Limits: resolution feeds the metric buckets, service edges and topology rollups. Readers that
query raw `traces` directly (user behavior and principal relationships) still see the
ingest-time caller. Non-root client spans are not turned into dependency edges.
Tunables: `storage.traceEdge.*` in the `tracescope` chart (`OTEL_TRACE_EDGE_RESOLUTION`,
`OTEL_TRACE_EDGE_SKEW_MS`, `OTEL_SERVICE_IP_MAP`).
