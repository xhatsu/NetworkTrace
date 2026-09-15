# Standalone lightweight Elasticsearch + APM Server testbed

This file is intentionally separate from the TraceScope Helm chart. It replaces the
Docker testbed in this directory with single-node, ephemeral Kubernetes workloads:

```sh
helm rollback tracescope 11 -n tracescope
# Apply this file with your normal Kubernetes deployment workflow.
```

Resources:

- `tracescope-elasticsearch` Service and single-replica Deployment on port 9200
- `tracescope-apm-server` Service and single-replica Deployment on port 8200
- APM Server ConfigMap pointing to `http://tracescope-elasticsearch:9200`
- No Kibana, authentication, or persistence; `emptyDir` is deliberate test-only state
- Elasticsearch JVM heap: 256 MiB initial / 512 MiB maximum

In-cluster endpoints:

```text
http://tracescope-elasticsearch.tracescope.svc.cluster.local:9200
http://tracescope-apm-server.tracescope.svc.cluster.local:8200
```

For TraceScope application pods, configure the existing Helm integration separately:

```sh
--set storage.backend=elasticsearch \
--set elasticsearch.url=http://tracescope-elasticsearch:9200 \
--set elasticsearch.verifyTls=false
```

The workspace automation intentionally does not execute `kubectl`; therefore this
manifest is rendered and statically checked here but must be applied by the operator's
normal cluster deployment path.
