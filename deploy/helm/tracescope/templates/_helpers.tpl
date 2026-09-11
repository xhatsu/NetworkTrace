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
