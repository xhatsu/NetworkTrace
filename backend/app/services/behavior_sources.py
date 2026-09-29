"""Source-isolated inputs. No cross-source summing or inferred environments."""
from __future__ import annotations
from backend.app.services.learned_behavior import BUCKET, UNKNOWN, eligible_identity
from backend.config import settings


def normalize(source, row):
    result = {k: str(row.get(k) or 'unknown').strip() or 'unknown'
              for k in ('environment','caller','principal','target','operation')}
    result.update(source=source, bucket_ms=int(row['bucket_ms']), requests=int(row['requests']),
                  errors=int(row.get('errors') or 0), auth_failures=int(row.get('auth_failures') or 0),
                  auth_successes=int(row.get('auth_successes') or 0),
                  p95_ms=float(row.get('p95_ms') or 0),
                  request_bytes=int(row.get('request_bytes') or 0), response_bytes=int(row.get('response_bytes') or 0),
                  byte_samples=int(row.get('byte_samples') or 0), trace_ids=row.get('trace_ids',[])[:3],
                  observed_ips=[{'address':str(ip),'role':'infrastructure' if ip in (*settings.known_f5,*settings.known_lb,*settings.known_reverse_proxy,*settings.known_nat) else 'unverified_peer'} for ip in row.get('observed_ips',[]) if ip][:10])
    result['caller_observed']=result['caller'].lower() not in UNKNOWN
    result['reference_eligible']=all(result[k].lower() not in UNKNOWN for k in ('target','operation'))
    # Missing caller attribution does not invalidate measured credential/API TPS.
    # Its unknown-caller scope stays separate; no caller edge is fabricated.
    return result


def sql_day(repo, source, start, end):
    if source != 'legacy_metrics':
        raise ValueError('behavior learning only accepts metric_buckets')
    if source=='legacy_metrics':
        sql='''SELECT bucket_start*1000 AS bucket_ms, 'unknown' AS environment,
        caller_service AS caller,principal_name AS principal,target_service AS target,operation,
        request_count AS requests,error_count AS errors,latency_p95 AS p95_ms,
        request_bytes,response_bytes,request_bytes_samples AS byte_samples
        FROM metric_buckets FINAL WHERE bucket_size=300 AND bucket_start>={start:Int64}/1000
        AND bucket_start<{end:Int64}/1000 LIMIT 100001'''
    rows=repo.query(sql,{'start':start,'end':end})
    if len(rows)>100000:
        raise ValueError('behavior input exceeds 100000 windows/day')
    return [normalize(source,r) for r in rows]


def _raw_sources_removed(start, end, after=None):
    """Raw Elasticsearch learning was intentionally removed.

    Kept as a private compatibility marker so callers fail explicitly rather
    than silently switching the learner back to span documents.
    """
    raise ValueError('raw trace learning is disabled; use metric_buckets')


'''DISABLED_RAW_SOURCE_IMPLEMENTATION

def es_query(start,end,after=None):
    body=ElasticsearchMetricRepository._query(start,end,300,after)
    runtime=body['runtime_mappings']
    # Explicit caller evidence only. Peer service may describe a destination.
    runtime['topology.caller']['script']['source']=(
        "def s=params['_source']; def v=s['caller_service']; if(v==null)v=s['caller.service']; "
        "if(v==null && s['caller'] instanceof Map){def c=s['caller']['service'];v=c instanceof Map?c['name']:c;} "
        "if(v==null && s['labels'] instanceof Map){v=s['labels']['caller_service'];if(v==null)v=s['labels']['caller.service'];} "
        "if(v!=null)emit(v.toString());")
    runtime['behavior.environment']={'type':'keyword','script':{'source':
        "def s=params['_source'];def v=s['service_environment'];if(v==null)v=s['service.environment'];"
        "if(v==null && s['service'] instanceof Map)v=s['service']['environment'];if(v==null)v=s['environment'];"
        "if(v!=null)emit(v.toString());"}}
    comp=body['aggs']['buckets']['composite']
    # Keep the recorded operation rather than the legacy compressed metric operation.
    comp['sources'][-1]={'operation':{'terms':{'field':'topology.api','missing_bucket':True}}}
    comp['sources'].append({'environment':{'terms':{'field':'behavior.environment','missing_bucket':True}}})
    runtime['behavior.peer_ip']={'type':'keyword','script':{'source':
        "def s=params['_source'];def v=s['caller_ip'];if(v==null)v=s['source_ip'];"
        "if(v==null && s['source'] instanceof Map)v=s['source']['ip'];if(v==null && s['client'] instanceof Map)v=s['client']['ip'];"
        "if(v!=null)emit(v.toString());"}}
    aggs=body['aggs']['buckets']['aggs']
    aggs['observed_ips']={'terms':{'field':'behavior.peer_ip','size':10}}
    for value in ('failure','success'):
        aggs['auth_'+value]={'filter':{'term':{'auth_result':value}}}
    aggs['evidence']={'top_hits':{'size':1,'_source':['trace.id','trace_id'],'sort':[{'@timestamp':'desc'}]}}
    return body


def es_page(start,end,after=None):
    adapter=ElasticsearchMetricRepository()
    with adapter._client() as client:
        response=client.post(f'/{adapter.source_index}/_search',json=es_query(start,end,after))
        response.raise_for_status()
        body=response.json()
    if body.get('timed_out') or body.get('_shards',{}).get('failed',0):
        raise ValueError('partial Elasticsearch behavior response')
    if 'aggregations' not in body:
        raise ValueError('missing Elasticsearch behavior aggregation')
    aggregation=body['aggregations']['buckets']
    rows=[]
    for b in aggregation['buckets']:
        key=b['key']; values=b.get('latency_percentiles',{}).get('values',{})
        traces=[]
        for hit in b.get('evidence',{}).get('hits',{}).get('hits',[]):
            source=hit.get('_source',{}); trace=source.get('trace',{})
            tid=source.get('trace_id') or source.get('trace.id') or (trace.get('id') if isinstance(trace,dict) else None)
            if tid: traces.append(str(tid))
        rows.append(normalize('elasticsearch',dict(environment=key.get('environment'),caller=key.get('caller'),
            principal=key.get('principal'),target=key.get('service'),operation=key.get('operation'),
            bucket_ms=key['bucket_start_ms'],requests=b['doc_count'],errors=b['errors']['doc_count'],
            p95_ms=values.get('95.0'), auth_failures=b['auth_failure']['doc_count'],auth_successes=b['auth_success']['doc_count'],
            request_bytes=b['request_bytes']['value'],response_bytes=b['response_bytes']['value'],
            byte_samples=b['request_bytes_samples']['value'],trace_ids=traces,
            observed_ips=[r['key'] for r in b['observed_ips']['buckets']])))
    return rows, aggregation.get('after_key') if len(rows)>=250 else None


'''


def apply_quality(repo, rows, start, end):
    incidents=repo.query('''SELECT target_service,first_seen,last_seen FROM anomaly_events FINAL
        WHERE last_seen>={start:Int64} AND first_seen<{end:Int64}
        AND anomaly_type IN ('traffic_spike','traffic_drop','latency','error_rate') LIMIT 10001''',{'start':start,'end':end})
    gaps=repo.query('''SELECT window_start_sec,window_end_sec FROM telemetry_quality_windows FINAL
        WHERE window_end_sec>={start:Int64}/1000 AND window_start_sec<{end:Int64}/1000 AND is_collection_gap=1 LIMIT 10001''',{'start':start,'end':end})
    if len(incidents)>10000 or len(gaps)>10000:
        raise ValueError('behavior quality evidence exceeds bound')
    for row in rows:
        blocked=any(i['target_service']==row['target'] and i['first_seen']<row['bucket_ms']+BUCKET and i['last_seen']>=row['bucket_ms'] for i in incidents)
        gap=any(i['window_start_sec']*1000<row['bucket_ms']+BUCKET and i['window_end_sec']*1000>row['bucket_ms'] for i in gaps)
        row['reference_eligible']=row['reference_eligible'] and not blocked and not gap
        row['quality_reason']='collection_gap' if gap else 'incident_window' if blocked else 'limited_attribution' if not row['reference_eligible'] else 'no_known_quality_block'
    return rows


def coverage(rows, end):
    return {'through_ms':end,'requests':sum(r['requests'] for r in rows),
            'identified_requests':sum(r['requests'] for r in rows if eligible_identity(r)),
            'caller_observed_requests':sum(r['requests'] for r in rows if r['caller_observed']),
            'known_environment_requests':sum(r['requests'] for r in rows if r['environment']!='unknown'),
            'collection_coverage':'unknown','sampling_ratio':None}
