{{- define "jobsifty.storageClass" -}}
{{- if .Values.storageClass }}
storageClassName: {{ .Values.storageClass | quote }}
{{- end }}
{{- end }}

{{- define "jobsifty.nodeAffinity" -}}
{{- $poolName := .pool -}}
{{- $pool := index .root.Values.nodePools $poolName -}}
{{- if and $poolName $pool }}
nodeAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    nodeSelectorTerms:
    - matchExpressions:
      - key: {{ $pool.labelKey | quote }}
        operator: In
        values:
        - {{ $pool.labelValue | quote }}
{{- end }}
{{- end }}
