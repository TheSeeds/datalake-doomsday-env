{{- define "ingest.fullname" -}}
{{- printf "%s" .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ingest.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: datalake
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "ingest.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- /* Ambiente comum aos dois gatilhos (API e Job). Uma fonte só: se a API e o
       Job recebessem configuração diferente, "mesma implementação" seria mentira. */ -}}
{{- define "ingest.env" -}}
- name: S3_ENDPOINT
  value: "http://garage:3900"
- name: S3_REGION
  value: "garage"
- name: S3_BUCKET
  value: {{ .Values.s3.bucket | quote }}
- name: LAKECORE_TAMANHO_MAXIMO
  value: {{ .Values.tamanhoMaximoUpload | quote }}
- name: DROP_DIR
  value: {{ .Values.drop.hostPath | quote }}
- name: S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.s3.existingSecret }}
      key: S3_ACCESS_KEY
- name: S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.s3.existingSecret }}
      key: S3_SECRET_KEY
- name: POSTGRES_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.db.existingSecret }}
      key: POSTGRES_USER
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.db.existingSecret }}
      key: POSTGRES_PASSWORD
- name: POSTGRES_DB
  valueFrom:
    secretKeyRef:
      name: {{ .Values.db.existingSecret }}
      key: POSTGRES_DB
- name: LAKECORE_DATABASE_URL
  value: "postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgresql:5432/$(POSTGRES_DB)"
{{- end -}}
