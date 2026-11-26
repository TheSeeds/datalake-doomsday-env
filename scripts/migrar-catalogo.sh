#!/usr/bin/env bash
# Roda a migração do catálogo (Alembic) como um Job efêmero no cluster.
#
# POR QUE EXISTE (P1 da Onda 7, corrigido para a v1.0.0):
#   até a v0.1.x, a migração do catálogo NÃO estava no install.sh — o comentário
#   na linha 15 dizia que rodava, mas o passo não existia. Em instalação limpa
#   as tabelas `objects`/`uploads`/`saude` não eram criadas, e o verify falhava
#   com `relation objects does not exist`. Só rodava manualmente no pod, com o
#   `alembic.ini` copiado em `/tmp`.
#
#   Este script resolve isso: gera um Job único (restartPolicy: Never) que
#   executa `alembic upgrade head` dentro da imagem do ingest, com o
#   `LAKECORE_DATABASE_URL` montado a partir do Secret do banco. É idempotente:
#   `upgrade head` não refaz o que já está aplicado (verifica `alembic_version`).
#
# POR QUE JOB e não `kubectl run --restart=Never`:
#   o Job dá condição `complete` observável via `kubectl wait`. O YAML é gerado
#   num arquivo e aplicado com `apply` — recurso idempotente.
#
# IMAGEM:
#   o install.sh passa a ref da imagem do ingest (a mesma do Deployment). Offline
#   = `lakecore-ingest:1.0.0` (importada no containerd); online = `ghcr.io/...`.
#   A imagem agora carrega `alembic.ini` e as versões de migração (ver Dockerfile);
#   imagens v0.1.x (sem o ini) são atendidas por um fallback que o escreve em /tmp.
#
# USO:
#   scripts/migrar-catalogo.sh <imagem> [--namespace lake-data]
#   scripts/migrar-catalogo.sh lakecore-ingest:1.0.0
#   scripts/migrar-catalogo.sh ghcr.io/theseeds/lakecore-ingest:1.0.0

set -euo pipefail

IMAGEM="${1:?uso: migrar-catalogo.sh <imagem> [--namespace ns]}"
[[ $# -ge 1 ]] && shift

NAMESPACE="lake-data"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="${2:?--namespace exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,44p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

kc() { microk8s kubectl "$@"; }
JOB="migracao-catalogo"
TMP_YAML="$(mktemp --suffix=.yaml)"

kc -n "${NAMESPACE}" get secret lakecore-db-secret >/dev/null 2>&1 \
  || { echo "FALHA: secret lakecore-db-secret não existe em ${NAMESPACE}" >&2; exit 1; }

# Heredoc QUOTED ('YAML'): o shell não expande nada aqui; o `$(...)` da URL fica
# literal e o KUBERNETES o interpola no env (referência a outro env var do mesmo
# container). A interpolação de IMAGEM/JOB/NAMESPACE usa `sed` com delimitador
# `#` — refs GHCR contêm `/` e `@`, então `#` (ausente) é seguro.
{
cat <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: __JOB__
  labels:
    app.kubernetes.io/part-of: datalake
    app.kubernetes.io/component: migracao-catalogo
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/part-of: datalake
        app.kubernetes.io/component: migracao-catalogo
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: migrar
          image: "__IMAGEM__"
          imagePullPolicy: IfNotPresent
          command: ["/bin/sh", "-c"]
          args:
            - |
              # /app/alembic.ini existe na imagem a partir da v1.0.0 (Dockerfile).
              # Imagens v0.1.x não o trazem; escreve um completo e segue.
              # env.py chama fileConfig(): um ini só com [alembic] quebra em
              # KeyError: 'formatters'.
              INI=/app/alembic.ini
              if [ ! -f "$INI" ]; then
                INI=/tmp/alembic.ini
                printf '%s\n' \
                  '[alembic]' \
                  'script_location = /app/src/lakecore/db/migrations' \
                  'prepend_sys_path = /app/src' \
                  'sqlalchemy.url =' \
                  '' \
                  '[loggers]' \
                  'keys = root,sqlalchemy,alembic' \
                  '' \
                  '[handlers]' \
                  'keys = console' \
                  '' \
                  '[formatters]' \
                  'keys = generic' \
                  '' \
                  '[logger_root]' \
                  'level = WARNING' \
                  'handlers = console' \
                  'qualname =' \
                  '' \
                  '[logger_sqlalchemy]' \
                  'level = WARNING' \
                  'handlers =' \
                  'qualname = sqlalchemy.engine' \
                  '' \
                  '[logger_alembic]' \
                  'level = INFO' \
                  'handlers =' \
                  'qualname = alembic' \
                  '' \
                  '[handler_console]' \
                  'class = StreamHandler' \
                  'args = (sys.stderr,)' \
                  'level = NOTSET' \
                  'formatter = generic' \
                  '' \
                  '[formatter_generic]' \
                  'format = %(levelname)-5.5s [%(name)s] %(message)s' \
                  'datefmt = %H:%M:%S' > "$INI"
              fi
              exec python -m alembic -c "$INI" upgrade head
          env:
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef: {name: lakecore-db-secret, key: POSTGRES_USER}
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: {name: lakecore-db-secret, key: POSTGRES_PASSWORD}
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef: {name: lakecore-db-secret, key: POSTGRES_DB}
            - name: LAKECORE_DATABASE_URL
              value: "postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgresql:5432/$(POSTGRES_DB)"
YAML
} \
  | sed -e 's#__IMAGEM__#'"${IMAGEM}"'#g' \
        -e 's#__JOB__#'"${JOB}"'#g' \
        -e 's#__NAMESPACE__#'"${NAMESPACE}"'#g' \
  > "${TMP_YAML}"

# Re-aplicação: Job é imutável; se o anterior existir, apaga e recria.
kc -n "${NAMESPACE}" delete job/${JOB} --ignore-not-found >/dev/null 2>&1 || true

kc -n "${NAMESPACE}" apply -f "${TMP_YAML}" >/dev/null
rm -f "${TMP_YAML}"

echo "  Job '${JOB}' criado — aguardando conclusão"
if ! kc -n "${NAMESPACE}" wait --for=condition=complete --timeout=180s job/${JOB} >/dev/null 2>&1; then
  echo
  echo "FALHA: job de migração não completou em 180s. Logs:"
  kc -n "${NAMESPACE}" logs job/${JOB} --tail=50 2>&1 || true
  kc -n "${NAMESPACE}" get job/${JOB} -o wide 2>&1 || true
  exit 1
fi

# Version real aplicada, para o verify não precisar inferir.
echo "  ok: migração aplicada"
kc -n "${NAMESPACE}" exec postgresql-0 -- psql -U lakecore -d lakecore -tAc \
  "select version_num from alembic_version" 2>/dev/null | sed 's/^/      alembic_version: /' || true