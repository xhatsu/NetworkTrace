# ClickHouse CPU diagnosis (production, read-only)

Observed on 2026-09-14 UTC in namespace `tracescope`. No fix, mutation, restart, or query cancellation was performed. All ClickHouse statements used for evidence were `SELECT`/system-table reads with bounded time ranges and/or limits. No secret values were read or printed.

## Executive conclusion

The dominant measured cause is the analytics worker's `process_principal_intelligence` stage, not web traffic. After the fresh deployment, its persisted checkpoint leaves **250,001 of 250,004 traces** to process. It fetches up to 10,000 full trace rows, then processes each row with many individual readiness scans, `FINAL` lookups, inserts, and synchronous `ALTER ... UPDATE` mutations. It does not save the principal checkpoint until the entire backlog finishes.

In the fixed 15-minute window `08:58:40`–`09:13:40`, statements directly matching that worker/derived-write pattern executed **80,966 queries**, read **1,630,724,788 rows**, wrote **77,868 rows**, accumulated **423.37 query-wall-seconds**, and used **295.142 CPU-seconds**. That is an average of **0.328 ClickHouse CPU cores** in logged worker-shaped queries alone (`295.142 / 900`). The same window created **25,671 new parts**, **7,851 mutations**, and **5,133 regular merges**. Background merge/mutation work is therefore a secondary, worker-induced cause rather than an independent ingestion or TTL cause.

The previously suspected once-per-minute code-241 retry is real, but its attribution was misstated and its measured CPU contribution was smaller. The failing SQL was the principal-intelligence cursor query `SELECT * FROM traces ... ORDER BY ingest_order,row_uid LIMIT 10000`, not the bucket aggregation query. In the rolling one-hour capture it made **36 attempts: 29 failures and 7 successes**, read **6,890,832 rows**, and used **12.909 CPU-seconds**. The exceptions were `MEMORY_LIMIT_EXCEEDED` while executing `MergeTreeSelect`, not `MergeSortingTransform` in the captured rows.

Continuous fleet ingestion and TTL merge churn were both refuted for this observation window. There were no trace INSERT query-log rows in the last two hours, no `traces` `NewPart` events, the restarted ingest writer reported zero accepted/committed requests, and the part log contained no `TTLDeleteMerge` or `TTLRecompressMerge` entries.

One important premise in the task was stale at observation time: the live app and ingest pods were **0.2.2**, not 0.2.0, and had started only minutes before collection.

## 1. CPU quantification and timeline

### Kubernetes resource visibility

Four requested `kubectl top pods` samples were attempted one minute apart. All failed identically, so Kubernetes supplied no pod-level CPU number:

```text
SAMPLE 2026-09-14T09:05:49Z
error: Metrics API not available
SAMPLE 2026-09-14T09:06:49Z
error: Metrics API not available
SAMPLE 2026-09-14T09:07:49Z
error: Metrics API not available
SAMPLE 2026-09-14T09:08:49Z
error: Metrics API not available
```

Command:

```sh
kubectl -n tracescope top pods
```

The ClickHouse container resource envelope was:

```text
clickhouse requests.cpu=300m limits.cpu=2 requests.memory=2Gi limits.memory=4Gi
```

At `09:06:31`, ClickHouse reported version `24.8.14.39` and only **515 seconds** uptime. Pod inventory at `09:06:00` likewise showed ClickHouse age **8m6s**, app age **6m39s**, and ingest pod ages **6m18s–8m10s**. This was a fresh rollout/restart, not a long steady-state sample.

### ClickHouse-native CPU accounting

Because Metrics API was unavailable, the most specific CPU measure available was ClickHouse's cumulative `OSCPUVirtualTimeMicroseconds` event:

```text
uptime_seconds  total_cpu_s  logged_query_cpu_s  logged_query_cpu_pct  non_query_or_unlogged_cpu_s  non_query_or_unlogged_avg_cores
989             544.041      338.463             62.2                  205.578                      0.208
```

Command (read-only; diagnostic queries had `log_queries=0`):

```sql
WITH
  (SELECT value/1000000 FROM system.events
   WHERE event='OSCPUVirtualTimeMicroseconds') AS t_cpu,
  (SELECT sum(ProfileEvents['OSCPUVirtualTimeMicroseconds'])/1000000
   FROM system.query_log
   WHERE event_time >= now()-toIntervalSecond(uptime())
     AND type IN ('QueryFinish','ExceptionWhileProcessing')) AS q_cpu
SELECT uptime(), t_cpu, q_cpu, 100*q_cpu/t_cpu,
       t_cpu-q_cpu, (t_cpu-q_cpu)/uptime();
```

An earlier direct snapshot gave the same order of magnitude:

```text
uptime_seconds  cpu_microseconds  avg_cpu_cores_since_start  wait_microseconds  avg_waiting_threads_since_start
949             519811600         0.548                      166504310           0.175
```

Thus ClickHouse itself averaged **0.548 CPU cores** over those 949 seconds. Logged completed/failed queries accounted for **62.2%** of ClickHouse CPU at the later snapshot. The residual **0.208 average cores** includes background merges/mutations, startup, and other internal/unlogged work; it must not be attributed wholly to merges.

Three `system.asynchronous_metrics` samples provide only a node-visible/cgroup-context proxy, not pod attribution. `CGroupMaxCPU` was 2; summing user plus system time across CPU0 and CPU1 gives **0.89**, **1.13**, and **1.58** busy cores at these instants:

```text
CH_CPU_PROXY_SAMPLE 2026-09-14T09:12:22Z
CGroupMaxCPU 2; LoadAverage1 3.33
OSUserTimeCPU0 0.34; OSUserTimeCPU1 0.34; OSSystemTimeCPU0 0.11; OSSystemTimeCPU1 0.10

CH_CPU_PROXY_SAMPLE 2026-09-14T09:12:52Z
CGroupMaxCPU 2; LoadAverage1 4.24
OSUserTimeCPU0 0.43; OSUserTimeCPU1 0.40; OSSystemTimeCPU0 0.14; OSSystemTimeCPU1 0.16

CH_CPU_PROXY_SAMPLE 2026-09-14T09:13:23Z
CGroupMaxCPU 2; LoadAverage1 3.43
OSUserTimeCPU0 0.72; OSUserTimeCPU1 0.59; OSSystemTimeCPU0 0.10; OSSystemTimeCPU1 0.17
```

These proxy figures include other work visible to the container and are retained only because pod metrics were unavailable.

### Live samples

At `09:06:54`, ClickHouse had one active merge and one background merge/mutation task:

```text
BackgroundMergesAndMutationsPoolTask  1
MemoryTracking                        1881546437
Merge                                 1
Query                                 1
```

The only non-diagnostic process caught in that sample was a short per-principal lookup (`elapsed=0.00049`, `read_rows=0`). At `09:10:05`, no merge was active and the only non-diagnostic process was another short principal lookup (`elapsed=0.001`). This is not one continuously running query; it is a high-rate stream of small queries interleaved with merges and mutations. No `KILL QUERY` was warranted or issued.

## 2. Ranked attributed causes

### 1. Principal-intelligence row-at-a-time/N+1 processing — dominant

Fixed-window query-log attribution (`08:58:40` inclusive to `09:13:40` exclusive):

```text
attribution                    queries  read_rows    written_rows  wall_seconds  cpu_seconds
worker_principal_and_derived   80966    1630724788   77868         423.37        295.142
other_or_ambiguous             15882    12340161     0             28.664        23.147
```

The worker group included the exact cursor/readiness/principal statement shapes, non-trace derived INSERTs, and ALTER mutations. The API log tail showed health/readiness probes and the requested ingestion-status read, but no dashboard/user traffic. Therefore the classification is well supported for this bounded window; `other_or_ambiguous` was deliberately not attributed.

The most expensive individual shapes in the same fixed window were:

```text
workload                   queries  read_rows    written_rows  wall_seconds  cpu_seconds  max_memory_bytes
principal_full_trace_scan  6399     1599775596   0             101.183       117.503      2514614
other_principal_select     41002    20139916     0             124.669       110.215      5667509
derived_insert             25737    5180860      77868         46.175        46.373       30601415
other_select               15859    12339862     0             28.63         23.132       1873260
alter_mutation             7754     0            0             149.715       19.386       0
incremental_cursor_scan    2        500008       0             0.934         1.022        215732230
bucket_rollup              72       5128408      0             0.694         0.644        18660164
```

The `principal_full_trace_scan` sample was:

```sql
SELECT MIN(timestamp_ms), MAX(timestamp_ms),
       COUNT(DISTINCT timestamp_ms / 86400000), COUNT(*)
FROM traces
WHERE principal_id = '…'
   OR (principal_id IS NULL AND principal_name = '…')
```

It is called by `evaluate_readiness()` for row-level novelty checks. The fixed-window average was **6.93 such full-trace scans per second** (`6,399 / 900`), each scanning approximately the whole 250,004-row trace table: the query-log aggregate read **1,599,775,596 rows**.

Worker logs establish stage timing and the currently stuck stage verbatim:

```text
{"event": "worker_stage_complete", "stage": "aggregate_traces", "elapsed_seconds": 4.389, ... "budget_seconds": 55.0, "budget_exceeded": false}
{"event": "worker_stage_complete", "stage": "rebuild_baselines", "elapsed_seconds": 0.212, ...}
{"event": "worker_stage_complete", "stage": "detect_anomalies", "elapsed_seconds": 1.658, ...}
{"event": "worker_stage_start", "stage": "process_principal_intelligence", ...}
```

No principal-stage completion appeared in another bounded tail captured at `09:10:28`, more than eleven minutes after pod startup.

The persistent state explains the backlog:

```text
source                  cursor_value                                                                                                                       updated_max
aggregation_cursor      {"mode":"incremental","ingest_order":1789232711539274208,"row_uid":"8b08b43a-bc68-4ad7-bfd7-9f705d5fb70a",...}  1789376375777
principal_intelligence  {"ingest_order": 1789232583599453148, "row_uid": "fc570409-24b4-4ddc-b60e-00233b1a3e6c", ...}                    1789232585689
```

```text
min_ingest_order       max_ingest_order       trace_rows
1789229747761653154    1789232711539274208    250004

rows_after_principal_checkpoint
250001
```

Repository correlation:

- `backend/app/services/principal_relationships.py:432-458` loops over batches but saves the checkpoint only after the loop ends.
- Lines 444-447 select `*` and sort by `(ingest_order,row_uid)` for every batch.
- Lines 450-453 call `_process_incremental_row()` for every trace.
- Lines 268 onward record multiple historical/candidate dimensions per row; lines 294, 309, 317, 324, 331, 338, 347, and 356 can invoke detector readiness.
- `backend/app/services/behavioral_engine.py:160-164` implements readiness as the full trace-table aggregate shown above.
- `principal_relationships.py:377-428` performs many per-row point reads and writes and refreshes four `FINAL` counts.

### 2. Worker-created small parts, regular merges, and mutations — major secondary amplifier

The same fixed 15-minute window produced:

```text
event_type  merge_reason  events  rows     bytes       wall_seconds
NewPart     NotAMerge     25671   77868    38.12 MiB   12.303
RemovePart  NotAMerge     18535   3902706  460.02 MiB  0
MutatePart  NotAMerge     7851    388075   478.26 MiB  73.686
MergeParts  RegularMerge  5133    3714102  252.64 MiB  35.377
```

Per-minute evidence shows this was sustained, not a single burst. Representative complete minutes:

```text
minute                new_parts  merges  mutations  merge_wall_seconds  mutation_wall_seconds
2026-09-14 09:01:00   1888       379     564        2.355               4.547
2026-09-14 09:02:00   1906       381     573        2.179               4.665
2026-09-14 09:03:00   1930       385     579        2.290               4.645
2026-09-14 09:04:00   1912       382     576        2.305               4.687
```

The table-level 20-minute capture attributed the largest churn directly to worker-derived tables:

```text
historical_registry     NewPart     4930 events
incidents               MutatePart  4911 events, 41.629 wall-seconds
candidate_behaviors     NewPart     2460 events
principal_change_events NewPart     2456 events
historical_registry     MergeParts   986 events, 5.479 wall-seconds
principal_change_events MergeParts   491 events, 7.669 wall-seconds
candidate_behaviors     MergeParts   492 events, 2.653 wall-seconds
```

Active-part counts remained low (mostly one to five parts per table) because ClickHouse was continually merging the tiny parts. Low active counts therefore do not mean low merge cost. The worker's per-row derived inserts and `ALTER TABLE incidents UPDATE ... SETTINGS mutations_sync = 1` statements are the source of this write amplification.

`system.part_log.ProfileEvents` contained no CPU values on this ClickHouse build, so merge CPU cannot be isolated exactly. It lies within the **205.578 non-query/unlogged CPU-seconds** over the 989-second since-start snapshot, together with startup and other internals; the report does not claim all of that residual as merge CPU.

### 3. Historical once-per-minute code-241 retry — confirmed, smaller, and currently superseded

Rolling one-hour aggregate:

```text
attempts  failures  successes  first_seen           last_seen            avg_ms  avg_read_rows  total_read_rows  cpu_seconds  max_memory_bytes
36        29        7          2026-09-14 08:13:23  2026-09-14 08:59:38  319.6   191412         6890832          12.909       254070126
```

The minute series showed one attempt in each populated minute, including consecutive failures from `08:45` through `08:56`. A representative exception was:

```text
2026-09-14 08:56:50  query_duration_ms=546  read_rows=188388
memory_usage=200689612  cpu_seconds=0.342  exception_code=241
Memory limit (total) exceeded: would use 1.83 GiB ... maximum: 1.80 GiB.
OvercommitTracker decision: Query was selected to stop ... While executing MergeTreeSelect...
```

Failing SQL:

```sql
SELECT * FROM traces
WHERE (ingest_order,row_uid)>(1789232583599453148,toUUID('fc570409-24b4-4ddc-b60e-00233b1a3e6c'))
ORDER BY ingest_order,row_uid LIMIT 10000
```

This proves the 60-second doomed retry behavior and code 241. It refutes the narrower hypothesis that the captured failure was the timestamp-range bucket aggregation ending in `MergeSortingTransform`. The query belongs to `process_principal_intelligence`; captured exceptions ended in `MergeTreeSelect`. The fresh 0.2.2 worker then succeeded in fetching the backlog and moved into the much more expensive N+1 processing described above.

### 4. Continuous ingestion through the fleet path — refuted in the window

Public status at `09:08:14`:

```json
{"events":250004,"traces":250004,"latest_ingested_ms":null,
 "jobs":[{"name":"behavioral-observability","status":"running","processed_count":0}],
 "ingest_writer":{"accepted_requests":0,"rejected_requests":0,"committed_requests":0,
 "committed_records":0,"duplicate_requests":0,"write_transactions":0,
 "failed_requests":0,"writer_alive":true,"queue_depth":0,"queue_capacity":256}}
```

The bounded ingest log contained startup and liveness/readiness probes only. The bounded two-hour query-log query for `INSERT INTO traces%` returned no rows. The bounded two-hour `system.part_log` query for `traces` showed only five migration mutations at `08:59` and their later removal; it showed no `NewPart` entries:

```text
minute                event_type  part_events  rows
2026-09-14 08:59:00   MutatePart  5            250004
2026-09-14 09:09:00   RemovePart  5            250004
```

Therefore fleet ingestion did not explain the measured CPU. It could contribute at other times, but not during this capture.

### 5. TTL-driven merge churn — refuted in the window

Production TTLs were present:

```text
agent_stats_history  TTL toDateTime(observed_at) + toIntervalDay(1)
ingest_batches       TTL toDateTime(intDiv(received_at_ms, 1000)) + toIntervalDay(7)
metric_buckets       TTL toDateTime(bucket_start) + toIntervalDay(90)
metric_buckets_agg   TTL bucket_time + toIntervalDay(90)
traces               TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(30)
```

But the two-hour part-log grouping was:

```text
merge_reason  event_type  events  output_rows  read_rows  read_bytes  wall_seconds
RegularMerge  MergeParts  9641    6832068      6881451    3.16 GiB    71.208
NotAMerge     MutatePart  14694   506586       506686     1.82 GiB    144.558
```

No `TTLDeleteMerge` or `TTLRecompressMerge` row appeared. The observed churn was regular merge and explicit mutation work, not TTL work.

## 3. Causal chain in plain words

1. A fresh app/ClickHouse rollout came up with the principal-intelligence checkpoint far behind the physical ingest ordering: **250,001 rows** remained.
2. The worker successfully fetched a 10,000-row full-record batch. Before the rollout, the same cursor query often retried once per minute and failed with code 241 because server memory was already near its 1.80 GiB query/overcommit ceiling.
3. For every fetched trace, the worker runs numerous point/`FINAL` queries. Novelty checks repeatedly call a full-table readiness aggregate. In 15 minutes that one aggregate ran **6,399 times** and read **1,599,775,596 rows**.
4. The row loop also emits individual derived-table INSERTs and synchronous incident mutations. In 15 minutes it created **25,671 new parts** and **7,851 mutations**.
5. ClickHouse continuously merged those parts: **5,133 regular merges** in the same window. This adds background work even though the web UI is idle and even though no new traces are entering the system.
6. The checkpoint is written only after the complete backlog loop. A worker restart before completion can replay the backlog, regenerating the same read/write/merge pressure.

## 4. Recommended fixes, ranked (not applied)

1. **Make principal intelligence set-based and bounded.** Process a small explicit batch, use only required trace columns, persist its checkpoint after each durably completed batch, enforce a stage/time budget, and yield between batches. Expected impact: removes multi-hour monopolization and prevents full replay after restart.
2. **Eliminate readiness full scans from the row loop.** Precompute/cache readiness once per principal and observation window from maintained summary tables, or evaluate all affected principals in one grouped query. Expected impact: removes the measured 6,399 full scans/15 minutes and its 117.503 CPU-seconds.
3. **Batch derived writes.** Aggregate relationship/candidate/principal changes in memory or staging blocks and issue batch INSERTs rather than individual row inserts. Expected impact: collapses the measured 25,671 new parts/15 minutes by orders of magnitude and correspondingly reduces regular merges.
4. **Remove synchronous per-event mutations.** Model incidents/jobs/checkpoints as versioned ReplacingMergeTree inserts or coalesce updates once per incident/batch. Expected impact: removes the 7,851 mutations/15 minutes and their 73.686 wall-seconds of part work.
5. **Align the cursor query with storage order/projection and select narrow columns.** `ORDER BY ingest_order,row_uid` against the current trace table requires reading broadly, and `SELECT *` raises memory. Add a suitable projection/materialized processing queue or change the cursor design after validating correctness. Expected impact: prevents the captured code-241 retries and reduces the 215–254 MB peak query memory.
6. **Keep memory limits as guardrails, not as the primary fix.** Raising the 1.80 GiB effective query/overcommit ceiling alone would allow the inefficient query to run harder and may increase CPU. Only retune after bounding the workload and reconciling it with the 4 GiB container limit.
7. **Restore Metrics API / pod CPU telemetry.** This is observability work, not the application fix. It will permit direct pod CPU time-series and node-pressure correlation instead of ClickHouse-native and node-visible proxies.
8. **Do not tune TTLs based on this incident.** There were zero TTL merge events in the measured two hours. Revisit TTL staggering/settings only if future `part_log.merge_reason` data shows TTL work.
9. **Verify deployed image provenance by digest.** The task expected 0.2.0, but the live pods reported `xhatsu101/tracescope:app-0.2.2` and `xhatsu101/tracescope:ingest-0.2.2`. Pinning/recording digests will prevent diagnosis against the wrong source version.

## 5. What could not be determined

- Exact pod CPU at the requested four timestamps and node pressure could not be determined because Kubernetes returned `Metrics API not available` for every `kubectl top pods` sample. No broader, non-authorized node inspection was performed.
- Background merge CPU could not be separated exactly because `system.part_log.ProfileEvents` had no CPU values. Merge count, bytes, rows, and durations are exact; the non-query CPU residual is only an upper envelope, not merge-only CPU.
- The bounded API log tail supports the operator's “zero web requests” statement but cannot prove that no request occurred outside the retained tail. Query-log attribution intentionally leaves `other_or_ambiguous` unassigned.
- The query log retained evidence from before the fresh pods but the previous worker pod/log stream was no longer available. The code-241 cadence is therefore correlated by query timestamps, SQL text, and exception details rather than matching old worker log lines.
- The cause of the apparent deployment immediately before diagnosis was not investigated because rollout history/change provenance was outside the allowed read-only command set.

## Deployment identity and safety record

Live images at `09:09:01`:

```text
api image=xhatsu101/tracescope:app-0.2.2
analytics-worker image=xhatsu101/tracescope:app-0.2.2 args=["--interval","60"]
three ingest pods image=xhatsu101/tracescope:ingest-0.2.2
```

No `KILL QUERY` was issued: live `system.processes` samples contained no long-running runaway query. No INSERT, ALTER, OPTIMIZE, DELETE, restart, rollout, or other production mutation was performed.
