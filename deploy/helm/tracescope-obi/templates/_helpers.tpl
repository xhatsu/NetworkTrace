{{- define "tracescope-obi.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else if contains "tracescope" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-tracescope-obi" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "tracescope-obi.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: tracescope
{{- end -}}

{{- define "tracescope-obi.collectorName" -}}
{{- printf "%s-collector" (include "tracescope-obi.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tracescope-obi.obiName" -}}
{{- include "tracescope-obi.fullname" . -}}
{{- end -}}

{{/* OBI image for the selected variant: standard (upstream) or custom (XML body). */}}
{{- define "tracescope-obi.obiImage" -}}
{{- $variant := .Values.obi.variant -}}
{{- if not (has $variant (list "standard" "custom")) -}}
{{- fail (printf "obi.variant must be standard or custom, got %q" $variant) -}}
{{- end -}}
{{- $img := index .Values.obi.image $variant -}}
{{- printf "%s:%s" $img.repository $img.tag -}}
{{- end -}}

{{/* OTLP endpoint OBI exports to: explicit override, else the in-chart collector. */}}
{{- define "tracescope-obi.obiExportEndpoint" -}}
{{- if .Values.obi.export.endpoint -}}
{{- .Values.obi.export.endpoint -}}
{{- else if .Values.collector.enabled -}}
{{- printf "http://%s.%s.svc.cluster.local:4317" (include "tracescope-obi.collectorName" .) .Release.Namespace -}}
{{- else -}}
{{- fail "obi.export.endpoint is required when collector.enabled=false" -}}
{{- end -}}
{{- end -}}
