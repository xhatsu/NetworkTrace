# Interactive Service Topology Plan

## 1. Goal

Build a lightweight, interactive topology view from OpenTelemetry trace data plus HTTP/network data collected by the custom tracer.

The topology has three drill-down levels:

1. **Service**
2. **API / operation**
3. **Username / principal**

Only the currently expanded branch is rendered. High-cardinality details such as source IPs are shown in a side panel instead of as topology nodes.

---

## 2. User Experience

### Level 1 — Service topology

Initial view shows only services and their observed call relationships.

Example:

```text
API Gateway ─────> Payment ─────> Billing
      │                │
      └────> Account   └────> Customer
```

Each service node shows a small operational summary:

- TPS/RPS
- p95 latency
- error rate
- warning/change indicator

Each service-to-service edge shows:

- call direction
- TPS
- optional p95 latency
- edge thickness based on request rate
- solid/dashed style for direct vs inferred relationships

### Level 2 — API

Expanding a service shows only that service's APIs/operations.

Example:

```text
Payment
├── POST /payment
├── POST /refund
├── GET /balance
└── GET /customer/{id}
```

API names should be normalized to avoid high-cardinality raw URLs.

### Level 3 — Username / Principal

Expanding an API shows usernames/principals observed using that API.

Example:

```text
POST /payment
├── payment_batch
├── partner_a
├── checkout_user
├── billing_system
└── -anonymous-
```

Internally, use `principal` as the canonical concept because many usernames are service/system accounts rather than human users.

---

## 3. Click vs Expand Behavior

Keep inspection and expansion separate.

### Single click

Opens the right-side detail panel for the selected:

- service
- API
- username/principal
- relationship edge

### Expand control or double click

Loads and displays child nodes.

### Collapse

Removes the expanded children from the visible graph.

This keeps the topology small and avoids accidental graph expansion.

---

## 4. Frontend Stack

Recommended frontend:

- **Vite**
- **React**
- **Sigma.js**
- **Graphology**

### Why

Sigma.js gives lightweight WebGL rendering with good headroom for large graphs.

Graphology stores the currently loaded graph structure and supports dynamic add/remove operations.

The frontend should never load the entire topology.

Typical visible set should remain approximately:

- 100–500 services
- selected service APIs
- selected API users

Even if the backend knows about millions of historical relationships.

---

## 5. Backend Stack

Recommended:

- **FastAPI**
- **ClickHouse**

The browser renders data only.

Topology relationships and metrics are computed server-side.

```text
OTel traces
     +
HTTP tracer data
     ↓
normalization
     ↓
ClickHouse
     ↓
5-minute relationship aggregation
     ↓
FastAPI topology API
     ↓
Sigma.js
```

---

## 6. Relationship Storage

Keep separate tables for each cardinality level.

### Service relationships

`topology_service_edges_5m`

Suggested dimensions:

- bucket_start
- caller_service
- target_service
- request_count
- error_count
- p50_latency_ms
- p95_latency_ms
- p99_latency_ms
- request_bytes
- response_bytes
- unique_principals
- unique_source_ips
- first_seen
- last_seen
- evidence_type
- confidence

### API relationships

`topology_api_edges_5m`

Suggested dimensions:

- bucket_start
- caller_service
- caller_api
- target_service
- target_api
- metrics as above

### Principal relationships

`topology_principal_edges_5m`

Suggested dimensions:

- bucket_start
- principal
- source_service
- source_api
- target_service
- target_api
- request_count
- error_count
- latency metrics
- request/response bytes
- source IP count
- first_seen
- last_seen

### Principal/IP relationship data

`topology_principal_ip_5m`

Suggested dimensions:

- bucket_start
- principal
- source_ip
- service
- api
- request_count
- error_count
- p95_latency_ms
- request_bytes
- response_bytes
- first_seen
- last_seen
- is_load_balancer

---

## 7. Current Topology Tables

In addition to historical 5-minute buckets, maintain current relationship tables for fast topology loading.

Examples:

- `topology_service_current`
- `topology_api_current`
- `topology_principal_current`

These contain the latest known state and are optimized for graph loading.

Historical `_5m` tables remain available for trends, comparison, and topology history.

---

## 8. Aggregation Strategy

Run aggregation every 5 minutes.

Only process the new time window.

```text
10:00–10:05 traces
      ↓
aggregate
      ↓
insert 10:00 bucket

10:05–10:10 traces
      ↓
aggregate
      ↓
insert 10:05 bucket
```

Do not repeatedly scan all historical raw traces.

The aggregation layer should derive:

- service edges
- API edges
- principal edges
- principal/IP relationships
- operational metrics
- first/last seen
- topology changes
- evidence/confidence

---

## 9. Evidence and Confidence

Because relationships come from multiple sources, track how every edge was derived.

Suggested evidence types:

- `OTEL_PARENT_CHILD`
- `OTEL_CLIENT_SERVER`
- `HTTP_NETWORK_OBSERVED`
- `TCP_CORRELATED`
- `IP_SERVICE_INFERRED`

Example:

```text
payment-service → billing-service

Evidence:
- OTel client span
- OTel server span
- HTTP tuple observed

confidence = HIGH
```

Inferred relationships should be visually distinguishable from directly observed relationships.

---

## 10. Service Detail Panel

When a service is selected, show five operational groups.

### Traffic

- TPS/RPS
- request count
- request bandwidth
- response bandwidth
- average request size
- average response size

### Performance

- p50 latency
- p95 latency
- p99 latency

### Reliability

- error rate
- HTTP 4xx rate
- HTTP 5xx rate
- timeout count if available
- TCP reset count if available
- incomplete transaction count if available

### Dependencies

- caller service count
- target service count
- API count
- active principal count
- new caller relationships
- new target relationships

### Change

- current 5m vs previous 5m
- current vs baseline
- TPS change
- latency change
- error change
- bandwidth change
- new/disappeared dependency

---

## 11. API Detail Panel

For a selected API show:

- TPS
- request count
- p50/p95/p99 latency
- error rate
- 4xx/5xx rate
- request bandwidth
- response bandwidth
- average request size
- average response size
- unique principals
- unique source IPs
- caller services
- target services
- top callers
- recent changes
- first seen
- last seen

---

## 12. Principal/User Detail Panel

Use multiple side-panel tabs/pages.

### Overview

- TPS
- request count
- p95/p99
- error rate
- request/response bandwidth
- services used
- APIs used
- source IP count
- first seen
- last seen

### Traffic

Time series for:

- TPS
- latency
- errors
- request bandwidth
- response bandwidth

### IPs

Server-side paginated IP list.

Suggested columns:

- IP
- TPS
- requests/5m
- error rate
- p95
- first seen
- last seen
- service count
- API count
- LB/direct flag
- new-IP flag

Filters:

- All
- Direct
- Load balancer
- New IP
- High error
- Inactive

Known F5/load-balancer addresses should be marked explicitly so they are not treated as meaningful new client origins.

### Paths

Show principal relationships across:

```text
principal → API → service
```

Useful for answering:

- Which APIs does this principal use?
- Which services does it reach?
- Which new path appeared?

### Changes

Show:

- new IP
- new API
- new service
- new caller
- dormant/reactivated principal
- TPS anomaly
- latency anomaly
- error anomaly
- bandwidth anomaly

---

## 13. Anonymous Traffic

Track anonymous attribution quality explicitly.

Important metrics:

- identified request percentage
- anonymous request percentage
- anonymous TPS
- anonymous top services
- anonymous top APIs

Example:

```text
Identified requests   93.4%
Anonymous              6.6%
```

This indicates how reliable the principal-level topology is.

---

## 14. Suggested API Endpoints

### Service graph

```http
GET /topology/services?window=5m
```

### Expand service

```http
GET /topology/services/{service}/apis?window=5m
```

### Expand API

```http
GET /topology/services/{service}/apis/{api}/principals?window=5m
```

### Principal IPs

```http
GET /topology/principals/{principal}/ips
    ?service=...
    &api=...
    &window=1h
    &page_size=50
    &cursor=...
```

### Detail endpoints

```http
GET /topology/services/{service}/metrics
GET /topology/apis/{api}/metrics
GET /topology/principals/{principal}/metrics
```

Use cursor/keyset pagination for high-cardinality IP lists rather than large OFFSET queries.

---

## 15. Rendering Rules

### Service view

Render:

- all currently relevant services
- aggregated service-to-service edges

### API view

Only render APIs for explicitly expanded services.

### Principal view

Only render principals for explicitly expanded APIs.

For extremely high-cardinality API users:

- return top N principals by selected metric
- provide search/filter
- optionally aggregate the remainder as `Other principals`

### Layout

Do not run a complete graph layout after every expansion.

Position newly expanded child nodes around their parent.

Only run a global layout:

- on initial graph load
- after major topology changes
- when the user presses Re-layout

Metrics can refresh without moving node positions.

---

## 16. Operational Change Detection

Annotate topology changes instead of making users discover them manually.

Examples:

- new service edge
- disappeared service edge
- new API relationship
- new principal/API relationship
- new source IP
- TPS surge/drop
- p95/p99 latency degradation
- 4xx/5xx increase
- bandwidth increase
- anonymous percentage increase

Example:

```text
NEW EDGE
payment → fraud

first seen: 8 minutes ago
TPS: 42
p95: 71 ms
```

---

## 17. What the DevOps Lead Should Be Able to Answer

The topology should make these questions fast to answer:

1. What service is busiest?
2. What service is slow?
3. What service is failing?
4. Which dependencies are affected?
5. What changed in the last 5 minutes?
6. Which API caused the problem?
7. Which principal/account is generating the traffic?
8. Which IPs are associated with that principal?
9. Is the IP a real source or a known load balancer?
10. Is this a new dependency, API, user path, or IP?
11. Is bandwidth changing unusually?
12. Is anonymous traffic increasing?
13. Is the relationship directly observed or inferred?

---

## 18. Implementation Order

### Phase 1 — Service topology

- normalize service names
- aggregate service edges every 5 minutes
- create current service topology table
- expose `/topology/services`
- implement Sigma.js service graph
- node/edge selection
- service metric panel

### Phase 2 — API drill-down

- normalize API/operation names
- aggregate API relationships
- lazy-load APIs when a service expands
- API metrics panel
- collapse support

### Phase 3 — Principal drill-down

- build principal relationship aggregation
- lazy-load principals per API
- principal overview
- traffic page
- path page

### Phase 4 — IP analysis

- aggregate principal/IP relationships
- maintain configured F5/LB IP list
- paginated IP page
- IP detail view
- new-IP detection

### Phase 5 — Change intelligence

- previous-5m comparisons
- baseline comparisons
- new/disappeared relationships
- principal/IP changes
- topology warning annotations

---

## 19. Final Architecture

```text
               OpenTelemetry traces
                        +
               Custom HTTP tracer
                        │
                        ▼
                Normalization layer
                        │
                        ▼
                   ClickHouse
                        │
          ┌─────────────┴─────────────┐
          │       5m aggregation      │
          ▼                           ▼
 historical relationship      current topology
       tables                    tables
          │                           │
          └─────────────┬─────────────┘
                        ▼
                     FastAPI
                        │
                        ▼
                React + Vite
                        │
                        ▼
             Sigma.js + Graphology
                        │
      ┌─────────────────┼─────────────────┐
      ▼                 ▼                 ▼
   Service             API            Principal
                                           │
                                           ▼
                                    paginated IPs
```

The key design principle is:

> **Render only what the operator expands; compute and store the full relationship history in ClickHouse.**
