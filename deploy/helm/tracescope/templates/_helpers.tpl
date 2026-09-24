{{/*
Expand the name of the chart.
*/}}
{{- define "tracescope.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "tracescope.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "tracescope.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "tracescope.labels" -}}
helm.sh/chart: {{ include "tracescope.chart" . }}
app.kubernetes.io/name: {{ include "tracescope.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: tracescope
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Base selector labels
*/}}
{{- define "tracescope.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tracescope.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ClickHouse Host resolution
*/}}
{{- define "tracescope.clickhouseHost" -}}
{{- if .Values.clickhouse.host -}}
{{- .Values.clickhouse.host -}}
{{- else if .Values.clickhouse.enabled -}}
{{- printf "%s-clickhouse" (include "tracescope.fullname" .) -}}
{{- else -}}
127.0.0.1
{{- end -}}
{{- end }}

{{/*
Secret Name resolution
*/}}
{{- define "tracescope.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "tracescope.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Ingress path routing rules
*/}}
{{- define "tracescope.ingressPaths" -}}
{{- if .Values.ingest.enabled }}
- path: /api/v1/ingest
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
- path: /api/ingest
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
{{- end }}
- path: /api/v1/ingestion/status
  pathType: Prefix
  backend:
    service:
      {{- if .Values.ingest.enabled }}
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
      {{- else }}
      name: {{ include "tracescope.fullname" . }}-api
      port:
        number: 30102
      {{- end }}
{{- if .Values.ingest.enabled }}
- path: /v1/traces
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
- path: /v1/metrics
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
- path: /v1/logs
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-ingest
      port:
        number: 30103
{{- end }}
- path: /api/agent/stats
  pathType: Prefix
  backend:
    service:
      {{- if .Values.agentStats.enabled }}
      name: {{ include "tracescope.fullname" . }}-agent-stats
      port:
        number: 30104
      {{- else }}
      name: {{ include "tracescope.fullname" . }}-api
      port:
        number: 30102
      {{- end }}
- path: /api
  pathType: Prefix
  backend:
    service:
      name: {{ include "tracescope.fullname" . }}-api
      port:
        number: 30102
- path: /assets
  pathType: Prefix
  backend:
    service:
      {{- if .Values.ui.enabled }}
      name: {{ include "tracescope.fullname" . }}-ui
      port:
        number: 80
      {{- else }}
      name: {{ include "tracescope.fullname" . }}-api
      port:
        number: 30102
      {{- end }}
- path: /
  pathType: Prefix
  backend:
    service:
      {{- if .Values.ui.enabled }}
      name: {{ include "tracescope.fullname" . }}-ui
      port:
        number: 80
      {{- else }}
      name: {{ include "tracescope.fullname" . }}-api
      port:
        number: 30102
      {{- end }}
{{- end }}

{{- define "tracescope.elasticsearchUrl" -}}
{{- $es := default (dict) .Values.elasticsearch -}}
{{- if and $es.enabled $es.url -}}
{{- $es.url -}}
{{- end -}}
{{- end -}}

{{/*
Resolve global image tag for TraceScope components.
Precedence:
1. .Values.global.image.tag
2. .Values.global.imageTag
3. .Chart.AppVersion
*/}}
{{- define "tracescope.globalImageTag" -}}
{{- $tag := "" -}}
{{- if .Values.global -}}
  {{- if .Values.global.imageTag -}}
    {{- $tag = .Values.global.imageTag -}}
  {{- else if and .Values.global.image .Values.global.image.tag -}}
    {{- $tag = .Values.global.image.tag -}}
  {{- end -}}
{{- end -}}
{{- default .Chart.AppVersion $tag -}}
{{- end -}}
