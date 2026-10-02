#!/bin/sh
# Generate matching values for the tracescope and tracescope-obi charts (and optionally
# the rendered manifests) for one pipeline mode, so both sides always agree.
#
#   elk        : OBI -> collector -> Elastic APM -> Elasticsearch -> TraceScope worker
#                tracescope: pipelineMode=elk_to_clickhouse, ES sync on, ingest off
#   clickhouse : OBI -> collector -> TraceScope ingest (/v1/traces) -> ClickHouse
#                tracescope: pipelineMode=clickhouse, ES off, ingest on (APM skipped)
#
# Output (in --out DIR):
#   tracescope-values.yaml  tracescope-obi-values.yaml           always
#   tracescope.yaml         tracescope-obi.yaml                  with --render (helm template)
#
# Install:
#   helm upgrade --install tracescope deploy/helm/tracescope -n tracescope \
#     -f deploy/helm/tracescope/values-secrets.yaml -f OUT/tracescope-values.yaml
#   helm upgrade --install tracescope-obi deploy/helm/tracescope-obi -n tracescope \
#     -f OUT/tracescope-obi-values.yaml
set -eu

usage() {
    cat <<'EOF'
Usage: render-stack.sh --mode elk|clickhouse [options]

  --mode MODE            elk | clickhouse (required)
  --obi VARIANT          standard | custom (default: standard; custom = XML/SOAP bodies)
  --body on|off          capture HTTP bodies (default: on)
  --target NS[/GLOB]     instrument namespace, optionally a deployment-name glob;
                         repeatable (default: default)
  --exclude NS           exclude namespace from instrumentation; repeatable
  --ts-release NAME      tracescope release name (default: tracescope)
  -n, --namespace NS     custom namespace for all components (shorthand for
                         --ts-namespace and --obi-namespace; default: tracescope)
  --ts-namespace NS      tracescope namespace (default: tracescope)
  --obi-release NAME     tracescope-obi release name (default: <ts-release>-obi)
  --obi-namespace NS     tracescope-obi namespace (default: tracescope, same as the app)
  --apm-endpoint H:P     Elastic APM OTLP endpoint (elk mode)
                         (default: apm-server.tmp-elk.svc.cluster.local:8200)
  --es-url URL           Elasticsearch URL for the TraceScope worker (elk mode)
                         (default: http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200)
  --out DIR              output directory (default: ./stack-out)
  --tag TAG              custom image tag for tracescope workloads (e.g. 0.4.6-amd64)
  --pull-policy POLICY   image pull policy (e.g. Always, IfNotPresent)
  --nodeport             skip Ingress and expose API (30102) and Ingest (30103) as NodePort
  --no-pvc               run ClickHouse as ephemeral pod with emptyDir (no PVC required)
  --no-collector         disable OTel collector (deploy OBI daemonset agent only)
  --export-endpoint URL  OTLP trace endpoint for OBI (required if --no-collector)
  --render               also run helm template for both charts
  --no-cluster-rbac      use namespace-scoped Role & RoleBinding instead of ClusterRole
                         (for restricted environments where ClusterRole is forbidden)
  --no-rbac              omit all RBAC (Role/ClusterRole) and disable K8s metadata
  --single-yaml [FILE]   bundle all manifests (tracescope + OBI) into one single YAML file
                         (default: <out>/tracescope-all.yaml; implies --render)
  --all-in-one [FILE]    alias for --single-yaml
  -h, --help             show this help
EOF
}

die() { echo "render-stack: $*" >&2; exit 2; }

MODE=""
OBI_VARIANT=standard
BODY=on
TARGETS=""
EXCLUDES=""
TS_RELEASE=tracescope
TS_NS=tracescope
OBI_NS=tracescope
OBI_RELEASE=
IMAGE_TAG=""
PULL_POLICY=""
APM_ENDPOINT=apm-server.tmp-elk.svc.cluster.local:8200
ES_URL=http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200
OUT=./stack-out
RENDER=0
SINGLE_YAML_FILE=""
NODEPORT=0
NO_PVC=0
NO_COLLECTOR=0
EXPORT_ENDPOINT=""
CLUSTER_RBAC=1
CREATE_RBAC=1
NL='
'

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) [ $# -ge 2 ] || die "--mode needs a value"; MODE=$2; shift 2 ;;
        --obi) [ $# -ge 2 ] || die "--obi needs a value"; OBI_VARIANT=$2; shift 2 ;;
        --body) [ $# -ge 2 ] || die "--body needs a value"; BODY=$2; shift 2 ;;
        --target) [ $# -ge 2 ] || die "--target needs a value"; TARGETS="$TARGETS$2$NL"; shift 2 ;;
        --exclude) [ $# -ge 2 ] || die "--exclude needs a value"; EXCLUDES="$EXCLUDES$2$NL"; shift 2 ;;
        --ts-release) [ $# -ge 2 ] || die "--ts-release needs a value"; TS_RELEASE=$2; shift 2 ;;
        -n|--namespace) [ $# -ge 2 ] || die "$1 needs a value"; TS_NS=$2; OBI_NS=$2; shift 2 ;;
        --ts-namespace) [ $# -ge 2 ] || die "--ts-namespace needs a value"; TS_NS=$2; shift 2 ;;
        --obi-release) [ $# -ge 2 ] || die "--obi-release needs a value"; OBI_RELEASE=$2; shift 2 ;;
        --obi-namespace) [ $# -ge 2 ] || die "--obi-namespace needs a value"; OBI_NS=$2; shift 2 ;;
        --tag) [ $# -ge 2 ] || die "--tag needs a value"; IMAGE_TAG=$2; shift 2 ;;
        --pull-policy) [ $# -ge 2 ] || die "--pull-policy needs a value"; PULL_POLICY=$2; shift 2 ;;
        --apm-endpoint) [ $# -ge 2 ] || die "--apm-endpoint needs a value"; APM_ENDPOINT=$2; shift 2 ;;
        --es-url) [ $# -ge 2 ] || die "--es-url needs a value"; ES_URL=$2; shift 2 ;;
        --out) [ $# -ge 2 ] || die "--out needs a value"; OUT=$2; shift 2 ;;
        --nodeport) NODEPORT=1; shift ;;
        --no-pvc) NO_PVC=1; shift ;;
        --no-collector) NO_COLLECTOR=1; shift ;;
        --export-endpoint) [ $# -ge 2 ] || die "--export-endpoint needs a value"; EXPORT_ENDPOINT=$2; shift 2 ;;
        --render) RENDER=1; shift ;;
        --no-cluster-rbac) CLUSTER_RBAC=0; shift ;;
        --no-rbac) CREATE_RBAC=0; shift ;;
        --single-yaml|--all-in-one|--combined)
            RENDER=1
            if [ $# -ge 2 ] && ! echo "$2" | grep -q '^-'; then
                SINGLE_YAML_FILE=$2
                shift 2
            else
                SINGLE_YAML_FILE=""
                shift 1
            fi
            ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown option: $1" ;;
    esac
done

case "$MODE" in elk|clickhouse) ;; "") usage >&2; die "--mode is required" ;; *) die "--mode must be elk or clickhouse" ;; esac
case "$OBI_VARIANT" in standard|custom) ;; *) die "--obi must be standard or custom" ;; esac
case "$BODY" in on|off) ;; *) die "--body must be on or off" ;; esac
[ -n "$TARGETS" ] || TARGETS="default$NL"

if [ "$NO_COLLECTOR" = 1 ] && [ -z "$EXPORT_ENDPOINT" ]; then
    die "--no-collector requires --export-endpoint <URL> (e.g. --export-endpoint http://otel-collector.monitoring.svc.cluster.local:4317)"
fi

if [ "$OBI_VARIANT" = custom ] && [ "$BODY" = off ]; then
    echo "render-stack: warning: --obi custom only adds XML body capture; it has no effect with --body off" >&2
fi

[ -n "$OBI_RELEASE" ] || OBI_RELEASE="$TS_RELEASE-obi"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Same rule as the tracescope chart's "tracescope.fullname" helper.
case "$TS_RELEASE" in
    *tracescope*) TS_FULLNAME=$TS_RELEASE ;;
    *) TS_FULLNAME="$TS_RELEASE-tracescope" ;;
esac
TS_INGEST_URL="http://$TS_FULLNAME-ingest.$TS_NS.svc.cluster.local:30103"

# YAML double-quoted scalar.
q() { printf '"%s"' "$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"; }

mkdir -p "$OUT"
TS_VALUES="$OUT/tracescope-values.yaml"
OBI_VALUES="$OUT/tracescope-obi-values.yaml"
BODY_BOOL=true
[ "$BODY" = on ] || BODY_BOOL=false

# --------------------------------------------------------------------------
# tracescope values
# --------------------------------------------------------------------------
{
    echo "# Generated by render-stack.sh --mode $MODE. Layer after values-secrets.yaml."
    if [ -n "$IMAGE_TAG" ]; then
        cat <<EOF
global:
  image:
    tag: $(q "$IMAGE_TAG")
EOF
    fi

    if [ "$MODE" = elk ]; then
        cat <<EOF
storage:
  pipelineMode: elk_to_clickhouse
  traceBackend: clickhouse
  clickhouseOnlyAgentTraces: false
elasticsearch:
  enabled: true
  syncEnabled: true
  url: $(q "$ES_URL")
EOF
    else
        cat <<EOF
storage:
  # Worker processes the ClickHouse traces written by the ingest pods.
  pipelineMode: clickhouse
  traceBackend: clickhouse
  # Must stay false: true makes /v1/traces accept and silently drop spans.
  clickhouseOnlyAgentTraces: false
elasticsearch:
  # APM/Elasticsearch is skipped entirely.
  enabled: false
  syncEnabled: false
behavior:
  enabled: true
EOF
    fi

    if [ "$NO_PVC" = 1 ]; then
        cat <<EOF
clickhouse:
  persistence:
    enabled: false
EOF
    fi

    if [ "$NODEPORT" = 1 ]; then
        cat <<EOF
ingress:
  enabled: false
EOF
    fi

    if [ -n "$PULL_POLICY" ] || [ "$NODEPORT" = 1 ]; then
        echo "app:"
        if [ -n "$PULL_POLICY" ]; then
            cat <<EOF
  image:
    pullPolicy: $PULL_POLICY
EOF
        fi
        if [ "$NODEPORT" = 1 ]; then
            cat <<EOF
  service:
    type: NodePort
    port: 30102
    nodePort: 30102
EOF
        fi
    fi

    echo "ingest:"
    if [ "$MODE" = clickhouse ]; then
        echo "  enabled: true"
    else
        echo "  enabled: false"
    fi
    if [ -n "$PULL_POLICY" ]; then
        cat <<EOF
  image:
    pullPolicy: $PULL_POLICY
EOF
    fi
    if [ "$NODEPORT" = 1 ] && [ "$MODE" = clickhouse ]; then
        cat <<EOF
  service:
    type: NodePort
    port: 30103
    nodePort: 30103
EOF
    fi
} > "$TS_VALUES"

# --------------------------------------------------------------------------
# tracescope-obi values
# --------------------------------------------------------------------------
{
    echo "# Generated by render-stack.sh --mode $MODE."
    cat <<EOF
obi:
  variant: $OBI_VARIANT
  discovery:
    instrument:
EOF
    printf '%s' "$TARGETS" | while IFS= read -r t; do
        [ -n "$t" ] || continue
        case "$t" in
            */*)
                echo "      - k8s_namespace: $(q "${t%%/*}")"
                echo "        k8s_deployment_name: $(q "${t#*/}")"
                ;;
            *) echo "      - k8s_namespace: $(q "$t")" ;;
        esac
    done
    if [ -n "$EXCLUDES" ]; then
        echo "    excludeInstrument:"
        printf '%s' "$EXCLUDES" | while IFS= read -r e; do
            [ -n "$e" ] && echo "      - k8s_namespace: $(q "$e")"
        done
    fi
    cat <<EOF
  bodyCapture:
    enabled: $BODY_BOOL
EOF
    if [ -n "$EXPORT_ENDPOINT" ]; then
        cat <<EOF
  export:
    endpoint: $(q "$EXPORT_ENDPOINT")
EOF
    fi
    if [ "$CLUSTER_RBAC" = 0 ]; then
        cat <<EOF
  rbac:
    create: true
    clusterScoped: false
EOF
    fi
    if [ "$CREATE_RBAC" = 0 ]; then
        cat <<EOF
  kubernetesMetadata: false
  rbac:
    create: false
EOF
    fi
    cat <<EOF
collector:
EOF
    if [ "$NO_COLLECTOR" = 1 ]; then
        cat <<EOF
  enabled: false
EOF
    elif [ "$MODE" = elk ]; then
        cat <<EOF
  exporter:
    mode: elk
    elk:
      endpoint: $(q "$APM_ENDPOINT")
EOF
    else
        cat <<EOF
  exporter:
    mode: tracescope
    tracescope:
      endpoint: $(q "$TS_INGEST_URL")
  # TraceScope rejects >10000 spans / >10 MiB per request (non-retryable 413).
  batch:
    sendBatchSize: 2000
    sendBatchMaxSize: 5000
  redaction:
    # TraceScope does not persist bodies; drop them after WSSE extraction.
    dropBodies: true
EOF
    fi
} > "$OBI_VALUES"

echo "wrote $TS_VALUES"
echo "wrote $OBI_VALUES"

if [ "$RENDER" = 1 ]; then
    command -v helm >/dev/null 2>&1 || die "helm not found (needed for --render)"
    TS_SECRETS="$SCRIPT_DIR/tracescope/values-secrets.yaml"
    set -- -f "$TS_VALUES"
    [ -f "$TS_SECRETS" ] && set -- -f "$TS_SECRETS" "$@"
    helm template "$TS_RELEASE" "$SCRIPT_DIR/tracescope" -n "$TS_NS" "$@" > "$OUT/tracescope.yaml"
    helm template "$OBI_RELEASE" "$SCRIPT_DIR/tracescope-obi" -n "$OBI_NS" -f "$OBI_VALUES" > "$OUT/tracescope-obi.yaml"
    if [ "$MODE" = clickhouse ] && [ "$NO_COLLECTOR" = 0 ] && ! grep -q "name: $TS_FULLNAME-ingest\$" "$OUT/tracescope.yaml"; then
        die "rendered tracescope has no $TS_FULLNAME-ingest Service; collector endpoint would not resolve"
    fi
    echo "wrote $OUT/tracescope.yaml"
    echo "wrote $OUT/tracescope-obi.yaml"

    ALL_YAML="$OUT/tracescope-all.yaml"
    [ -n "$SINGLE_YAML_FILE" ] && ALL_YAML="$SINGLE_YAML_FILE"
    {
        cat "$OUT/tracescope.yaml"
        printf '\n'
        cat "$OUT/tracescope-obi.yaml"
    } > "$ALL_YAML"
    echo "wrote $ALL_YAML"
fi
