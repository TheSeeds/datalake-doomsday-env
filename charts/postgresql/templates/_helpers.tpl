{{- define "postgresql.fullname" -}}
{{- printf "%s" .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "postgresql.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: datalake
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "postgresql.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- /* Recursos do tier, SEM o sharedBuffers.

O `sharedBuffers` mora no mesmo mapa por conveniência de leitura, mas NÃO é
campo de `resources` do Kubernetes — vazar ele para o manifest gera
"unknown field spec.template.spec.containers[0].resources.sharedBuffers".
`omit` remove antes de serializar. */ -}}
{{- define "postgresql.recursos" -}}
{{- $t := index .Values.resources .Values.tier -}}
{{- omit $t "sharedBuffers" | toYaml -}}
{{- end -}}

{{- /* Valor de `shared_buffers` do tier, como flag do postgres. */ -}}
{{- define "postgresql.sharedBuffers" -}}
{{- (index .Values.resources .Values.tier).sharedBuffers -}}
{{- end -}}
