from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from .repository import StorageRepository


INSERT = """INSERT INTO anomalies(fingerprint,entity_type,entity_id,anomaly_type,first_detected_ms,last_detected_ms,window_start_ms,window_end_ms,current_value,baseline_value,normal_low,normal_high,absolute_difference,percent_change,current_samples,baseline_samples,persistence_buckets,severity,status,unit,explanation,rule,training_start_ms,training_end_ms,limitations_json,contributors_json,trace_ids_json,updated_at_ms)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def save(repo: StorageRepository, *, fingerprint: str, entity_type: str, entity_id: str, kind: str,
         start: int, end: int, value: float, baseline: float | None, samples: int, baseline_samples: int,
         unit: str, explanation: str, rule: str, training_start: int, training_end: int,
         contributors: list[dict[str,Any]], limitations: list[str], severity: str="medium") -> None:
    now=int(time.time()*1000);delta=value-(baseline or 0);percent=delta/baseline*100 if baseline else None
    values=(fingerprint,entity_type,entity_id,kind,now,now,start,end,value,baseline,None,None,delta,percent,samples,baseline_samples,1,severity,"open",unit,explanation,rule,training_start,training_end,json.dumps(limitations),json.dumps(contributors),json.dumps([]),now)
    with repo.transaction() as db:
        prior = db.execute("SELECT status FROM anomalies FINAL WHERE fingerprint=?", (fingerprint,)).fetchone()
        values = (*values[:18], "open" if prior and prior[0] == "resolved" else (prior[0] if prior else "open"), *values[19:])
        db.execute(INSERT, values)


def detect_structural(repo: StorageRepository) -> int:
    """Novelty, mix, dormancy, and operation-matched instance detectors."""
    with repo.connect() as db:
        bounds=db.execute("SELECT MIN(timestamp_ms),MAX(timestamp_ms) FROM events").fetchone()
    if not bounds or bounds[0] is None or bounds[1]-bounds[0] < 3_600_000: return 0
    first,last=bounds;window_start=last-10*60_000;training_end=window_start;found=0
    limitations=["Sampling coverage is unknown.","Presented account identity does not prove the originating service."]
    with repo.connect() as db:
        relationships=db.execute("""SELECT account_username,service_name,operation,MIN(timestamp_ms) first_seen,COUNT(*) samples
          FROM events WHERE account_username IS NOT NULL GROUP BY account_username,service_name,operation
          HAVING first_seen>=? AND samples>=3""",(window_start,)).fetchall()
    for row in relationships:
        for kind,target in (("new_account_to_service",row["service_name"]),("new_account_to_operation",f"{row['service_name']} / {row['operation']}")):
            save(repo,fingerprint=f"account:{row['account_username']}:{kind}:{target}",entity_type="account",entity_id=row["account_username"],kind=kind,start=row["first_seen"],end=last+1,value=row["samples"],baseline=0,samples=row["samples"],baseline_samples=0,unit="observed requests",explanation=f"Account {row['account_username']} was newly observed accessing {target}, with {row['samples']:,} requests in the current window.",rule="Relationship was absent before the training cutoff and persisted for at least three observations.",training_start=first,training_end=training_end,contributors=[{"destination":target,"requests":row["samples"]}],limitations=limitations)
            found+=1
    with repo.connect() as db:
        edges=db.execute("SELECT source_service,target_service,evidence,MIN(bucket_ms) first_seen,SUM(request_count) samples FROM topology_edges GROUP BY source_service,target_service,evidence HAVING first_seen>=? AND samples>=3",(window_start,)).fetchall()
    for row in edges:
        entity=f"{row['source_service']} → {row['target_service']}"
        save(repo,fingerprint=f"edge:{entity}:{row['evidence']}",entity_type="dependency",entity_id=entity,kind="new_service_dependency_edge",start=row["first_seen"],end=last+1,value=row["samples"],baseline=0,samples=row["samples"],baseline_samples=0,unit="observed calls",explanation=f"A new {row['evidence']} dependency {entity} appeared with {row['samples']:,} observed calls.",rule="Directed relationship was absent from the training window and exceeded the minimum traffic threshold.",training_start=first,training_end=training_end,contributors=[{"edge":entity,"evidence":row["evidence"]}],limitations=["Shared trace IDs alone are not accepted as edge evidence."],severity="high" if row["evidence"]=="confirmed" else "medium")
        found+=1
    # Dormancy requires a full 14-day silent period, so short-history datasets cannot trigger it.
    if last-first>=15*86_400_000:
        with repo.connect() as db:
            active=db.execute("SELECT account_username,COUNT(*) samples FROM events WHERE account_username IS NOT NULL AND timestamp_ms>=? GROUP BY account_username HAVING samples>=5",(window_start,)).fetchall()
            for row in active:
                previous=db.execute("SELECT MAX(timestamp_ms),COUNT(*) FROM events WHERE account_username=? AND timestamp_ms<?",(row["account_username"],window_start)).fetchone()
                if previous[0] and previous[0]<window_start-14*86_400_000:
                    save(repo,fingerprint=f"account:{row['account_username']}:dormant_return",entity_type="account",entity_id=row["account_username"],kind="dormant_account_return",start=window_start,end=last+1,value=row["samples"],baseline=0,samples=row["samples"],baseline_samples=previous[1],unit="observed requests",explanation=f"Dormant account {row['account_username']} returned with {row['samples']:,} requests after at least 14 days without observed activity.",rule="Previously known identity, no observations for 14 days, then at least five renewed requests.",training_start=first,training_end=window_start,contributors=[],limitations=limitations,severity="high");found+=1
        with repo.connect() as db:
            unusual_hours=db.execute("""SELECT c.account_username,c.hour,c.samples,COALESCE(b.samples,0) baseline_samples FROM
              (SELECT account_username,strftime('%w-%H',timestamp_ms/1000,'unixepoch') hour,COUNT(*) samples FROM events WHERE account_username IS NOT NULL AND timestamp_ms>=? GROUP BY account_username,hour) c
              LEFT JOIN (SELECT account_username,strftime('%w-%H',timestamp_ms/1000,'unixepoch') hour,COUNT(*) samples FROM events WHERE account_username IS NOT NULL AND timestamp_ms<? GROUP BY account_username,hour) b
              ON b.account_username=c.account_username AND b.hour=c.hour WHERE c.samples>=10 AND COALESCE(b.samples,0)=0""",(window_start,window_start)).fetchall()
        for row in unusual_hours:
            save(repo,fingerprint=f"account:{row['account_username']}:usage_hour:{row['hour']}",entity_type="account",entity_id=row["account_username"],kind="changed_account_usage_hours",start=window_start,end=last+1,value=row["samples"],baseline=0,samples=row["samples"],baseline_samples=0,unit="observed requests",explanation=f"Account {row['account_username']} was active in weekday/hour bucket {row['hour']}, which was absent from the historical training window.",rule="At least ten current requests in a weekday/hour bucket not observed during at least 15 days of history.",training_start=first,training_end=window_start,contributors=[{"weekday_hour":row["hour"],"requests":row["samples"]}],limitations=limitations);found+=1
    # Total-variation distance detects operation-mix shifts without assigning cause.
    current_start=last-30*60_000;baseline_start=current_start-2*60*60_000
    with repo.connect() as db:
        mix_rows=db.execute("SELECT account_username,operation,SUM(timestamp_ms>=?) current_count,SUM(timestamp_ms<?) baseline_count FROM events WHERE account_username IS NOT NULL AND timestamp_ms>=? GROUP BY account_username,operation",(current_start,current_start,baseline_start)).fetchall()
    mixes: dict[str,list[Any]]=defaultdict(list)
    for row in mix_rows: mixes[row["account_username"]].append(row)
    for account,rows in mixes.items():
        cur=sum(r["current_count"] for r in rows);base=sum(r["baseline_count"] for r in rows)
        if cur<50 or base<100: continue
        tvd=.5*sum(abs(r["current_count"]/cur-r["baseline_count"]/base) for r in rows)
        if tvd>=.35:
            contributors=sorted(({"operation":r["operation"],"current_share":r["current_count"]/cur,"baseline_share":r["baseline_count"]/base} for r in rows),key=lambda x:abs(x["current_share"]-x["baseline_share"]),reverse=True)[:5]
            save(repo,fingerprint=f"account:{account}:operation_mix",entity_type="account",entity_id=account,kind="changed_account_operation_mix",start=current_start,end=last+1,value=tvd,baseline=0,samples=cur,baseline_samples=base,unit="total variation",explanation=f"Account {account}'s operation mix changed by {tvd*100:.1f}% total-variation distance, based on {cur:,} current requests.",rule="Current 30-minute operation shares differ from the preceding two-hour distribution by at least 35% TVD.",training_start=baseline_start,training_end=current_start,contributors=contributors,limitations=limitations);found+=1
    # Compare instances only within the same service and operation.
    with repo.connect() as db:
        instance_rows=db.execute("SELECT service_name,operation,node_name,COUNT(*) samples,AVG(duration_us)/1000.0 avg_ms FROM events WHERE node_name IS NOT NULL AND timestamp_ms>=? GROUP BY service_name,operation,node_name HAVING samples>=30",(current_start,)).fetchall()
    comparable: dict[tuple[str,str],list[Any]]=defaultdict(list)
    for row in instance_rows: comparable[(row["service_name"],row["operation"])].append(row)
    for (service,operation),rows in comparable.items():
        if len(rows)<2: continue
        fastest=min(rows,key=lambda r:r["avg_ms"]);slowest=max(rows,key=lambda r:r["avg_ms"])
        if slowest["avg_ms"]>=fastest["avg_ms"]*2 and slowest["avg_ms"]-fastest["avg_ms"]>=75:
            entity=f"{service} / {operation}"
            save(repo,fingerprint=f"instance:{entity}",entity_type="operation",entity_id=entity,kind="instance_imbalance",start=current_start,end=last+1,value=slowest["avg_ms"],baseline=fastest["avg_ms"],samples=slowest["samples"],baseline_samples=fastest["samples"],unit="average ms",explanation=f"For operation-matched traffic, instance {slowest['node_name']} averaged {slowest['avg_ms']:.0f} ms versus {fastest['avg_ms']:.0f} ms on {fastest['node_name']}.",rule="Compare only the same service/operation; require 30 samples per instance, at least 2× and 75 ms separation.",training_start=current_start,training_end=last,contributors=[dict(r) for r in rows],limitations=["Average is used for instance screening; inspect operation percentiles before acting.","No causal claim is made."],severity="high");found+=1
    return found
