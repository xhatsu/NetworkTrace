from __future__ import annotations

import base64
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator


def synthetic_documents(count: int = 24_000, services: int = 36, anchor: datetime | None = None, seed: int = 42) -> Iterator[dict[str, Any]]:
    """Deterministic patterns: duplicates can be replayed, callers may be unknown, and the final bucket is anomalous."""
    rng=random.Random(seed)
    anchor=(anchor or datetime.now(timezone.utc)).replace(second=0,microsecond=0)
    start=anchor-timedelta(hours=3)
    service_names=[f"{['edge','orders','payments','identity','catalog','platform'][i%6]}-{i:03d}" for i in range(services)]
    accounts=["svc-checkout","svc-billing","batch-recon","shared-legacy",None]
    operations=["GET /v1/items","POST /v1/orders","POST /v1/payments","GET /health","GET /v1/profile"]
    for i in range(count):
        minute=i % 180
        # A deliberate five-minute estate-wide telemetry gap must not become a drop incident.
        if 80 <= minute <= 84: minute=85
        service_index=(i*17+i//services)%services; service=service_names[service_index]
        timestamp=start+timedelta(minutes=minute,seconds=(i*13)%60,microseconds=(i%1000)*1000)
        is_final=minute==179 and service_index in (1,7)
        duration=max(2_000,int(rng.lognormvariate(11.0,0.45))) * (7 if is_final else 1)
        status=503 if (is_final and i%3==0) or i%211==0 else 403 if i%307==0 else 200
        account=accounts[i%len(accounts)]
        auth="Basic "+base64.b64encode(f"{account}:never-store-this".encode()).decode() if account else None
        trace=f"{i//2:032x}"; transaction=f"{i*2:016x}"
        operation="POST /rare-maintenance" if i%997==0 else operations[i%len(operations)]
        transaction_doc={"id":transaction,"name":operation,"duration":{"us":duration}}
        if i%17: transaction_doc["sampled"]=True
        source={"@timestamp":timestamp.isoformat(),"event":{"ingested":(timestamp+timedelta(seconds=2)).isoformat(),"outcome":"failure" if status>=500 else "success"},
            "trace":{"id":trace},"transaction":transaction_doc,
            "service":{"name":service,"environment":"production","node":{"name":f"{service}-pod-{i%3}"}},
            "labels":{"service_group_id":service.split('-')[0],"service_module_id":f"module-{service_index%8}","http_request_header_authorization":auth},
            "http":{"request":{"method":"POST" if "POST" in operation else "GET"},"response":{"status_code":status}},
            "url":{"domain":f"{service}.internal","port":443,"path":"/v1"},"span":{"kind":"server"},"processor":{"event":"transaction"}}
        yield {"_id":f"fixture-server-{i}","_source":source,"fields":{"service.name":["must-not-be-second-event"]}}
        # Roughly one client span per 12 server events. Some have no parent (inferred evidence).
        if i%12==0:
            target=service_names[(service_index+1+(i%5))%services]
            child={"@timestamp":timestamp.isoformat(),"trace":{"id":trace},"parent":{"id":transaction if i%24==0 else f"missing-{i}"},
                "span":{"id":f"{i*2+1:016x}","kind":"client"},"name":f"HTTP {target}","duration_us":max(1000,duration//3),
                "service":{"name":service,"environment":"production"},"peer":{"service":target},"event":{"outcome":"success"},
                "labels":{"service_group_id":service.split('-')[0],"service_module_id":f"module-{service_index%8}"}}
            yield {"_id":f"fixture-client-{i}","_source":child}
    # A concentrated, explainable final-minute regression with enough samples to pass guardrails.
    target=service_names[1 if len(service_names)>1 else 0]
    for j in range(420):
        timestamp=anchor-timedelta(seconds=1+(j%110))
        yield {"_id":f"fixture-regression-{count}-{j}","_source":{
            "@timestamp":timestamp.isoformat(),"event":{"ingested":(timestamp+timedelta(seconds=3)).isoformat(),"outcome":"failure" if j%4==0 else "success"},
            "trace":{"id":f"{count+j:032x}"},"transaction":{"id":f"a{j:015x}","name":"POST /v1/orders","duration":{"us":620_000+j*113},"sampled":True},
            "service":{"name":target,"environment":"production","node":{"name":f"{target}-pod-2"}},
            "labels":{"service_group_id":target.split('-')[0],"service_module_id":"module-1","http_request_header_authorization":"Basic "+base64.b64encode(b"svc-checkout:not-persisted").decode()},
            "http":{"request":{"method":"POST"},"response":{"status_code":503 if j%4==0 else 200}},"span":{"kind":"server"},"processor":{"event":"transaction"}}}


def malformed_security_documents(anchor: datetime) -> list[dict[str, Any]]:
    base={"@timestamp":anchor.isoformat(),"transaction":{"id":"bad-1","name":"GET /safe","duration":{"us":1000}},"trace":{"id":"bad-trace"},"service":{"name":"security-fixture"},"http":{"request":{"method":"GET"}}}
    return [{"_source":{**base,"labels":{"http_request_header_authorization":"Basic !!!not-base64!!!"}}},{"_source":{**base,"transaction":{**base["transaction"],"id":"missing-header"}}}]
