#!/usr/bin/env bash
# Prova que o backup do catálogo volta a ser um catálogo: restore drill.
#
# Este script é o critério de pronto da Onda 6, em forma executável.
#
# POR QUE ELE EXISTE:
#   `pg_dump` diário rodando não é backup — é esperança. Em 2026-11-18 descobrimos
#   que o Job estava falhando em 100% das execuções havia horas, e ninguém viu
#   porque ninguém restaurava. O drill transforma "deve funcionar" em "funcionou,
#   e aqui está a comparação".
#
# O QUE ESTE SCRIPT FAZ:
#   1. sobe um Pod efêmero dentro do cluster, com a imagem do backup;
#   2. escolhe o dump mais recente em `backup/` e confere o cabeçalho PGDMP;
#   3. cria um banco NOVO (`restore_drill`) e restaura nele;
#   4. compara original × restaurado por contagem E md5 das chaves;
#   5. descarta o banco de rascunho se bater; MANTÉM se divergir (material de
#      depuração — apagar tornaria o incidente irreproduzível).
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - NÃO toca no banco original (só faz SELECT nele);
#   - NÃO apaga nenhum backup;
#   - NÃO usa `sudo`;
#   - NÃO reinicia nada.
#
# O QUE FICA SEM PROVA (dito explicitamente, como manda a regra 7):
#   - apagar o PVC do PostgreSQL e restaurar do zero. Isso exige segundo nó para
#     ser seguro; o drill restaura num banco novo do mesmo servidor.
#
# USO:
#   scripts/restore-drill.sh              # dry-run: mostra o que faria
#   scripts/restore-drill.sh --apply      # executa o drill

set -euo pipefail

APLICAR=false
NAMESPACE="lake-data"
IMAGEM="lakecore-backup:0.1.3"
POD="restore-drill"
TIMEOUT_SEGUNDOS=180

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APLICAR=true; shift ;;
    --namespace) NAMESPACE="${2:?--namespace exige valor}"; shift 2 ;;
    --imagem) IMAGEM="${2:?--imagem exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

kc() { microk8s kubectl "$@"; }

echo "=================================================================="
echo " Restore drill do catálogo"
echo " Namespace: ${NAMESPACE}   Imagem: ${IMAGEM}"
echo " Modo: $(${APLICAR} && echo 'APLICAR' || echo 'DRY-RUN (padrão)')"
echo "=================================================================="
echo

echo "[1/5] Verificando que o catálogo responde de verdade"
# `pg_isready` NÃO serve: devolve 0 mesmo com role inexistente (medido em
# 2026-11-18). O teste tem que autenticar.
if ! kc -n "${NAMESPACE}" exec postgresql-0 -- \
      psql -U lakecore -d lakecore -tAc 'select 1' >/dev/null 2>&1; then
  echo "  FALHOU: o catálogo não respondeu a um SELECT real."
  exit 1
fi
echo "  ok: SELECT 1 respondeu"

echo "[2/5] Procurando backup disponível"
DUMPS="$(kc -n "${NAMESPACE}" get cronjob postgresql-backup \
  -o jsonpath='{.status.lastSuccessfulTime}' 2>/dev/null || true)"
if [[ -z "${DUMPS}" ]]; then
  echo "  AVISO: o CronJob nunca registrou sucesso."
  echo "         O drill ainda pode passar se houver dump em backup/ — mas isso"
  echo "         significa que o agendamento diário não está provado."
else
  echo "  ok: último sucesso do CronJob em ${DUMPS}"
fi

echo "[3/5] Ações que SERÃO executadas (dentro de um Pod efêmero)"
cat <<'COMO'
  a) baixar o dump .sql.gz mais recente de backup/postgres/ no Garage
  b) conferir o cabeçalho PGDMP (recusa arquivo que não seja dump do pg_dump)
  c) ler a assinatura do banco ORIGINAL (SELECT, somente leitura)
  d) criar o banco descartável `restore_drill` e restaurar nele
  e) comparar original × restaurado: contagem E md5 das chaves por tabela
  f) se bater, descartar `restore_drill`; se divergir, MANTÊ-LO para inspeção
COMO
echo
echo "  NÃO faz: nenhuma escrita no banco original; nenhuma remoção de backup;"
echo "           nenhum sudo; nenhum restart."
echo

if ! ${APLICAR}; then
  echo "[4/5] DRY-RUN: nada foi executado."
  echo "      Rode com --apply para executar o drill."
  exit 0
fi

echo "[4/5] Executando o drill"

# O ConfigMap leva o script para dentro do Pod. Montar como arquivo (e não
# embutir no `args`) evita o inferno de escapes de YAML que já custou uma
# tentativa nesta sessão.
DIR_TMP="$(mktemp -d)"
trap 'rm -rf "${DIR_TMP}"; kc -n "${NAMESPACE}" delete pod "${POD}" --ignore-not-found >/dev/null 2>&1 || true; kc -n "${NAMESPACE}" delete configmap restore-drill-scripts --ignore-not-found >/dev/null 2>&1 || true' EXIT

kc -n "${NAMESPACE}" create configmap restore-drill-scripts \
  --from-file=restore_drill.py="$(dirname "$0")/../docker/backup/restore_drill.py" \
  --dry-run=client -o yaml > "${DIR_TMP}/cm.yaml"
kc -n "${NAMESPACE}" apply -f "${DIR_TMP}/cm.yaml" >/dev/null

kc -n "${NAMESPACE}" delete pod "${POD}" --ignore-not-found >/dev/null 2>&1 || true

cat > "${DIR_TMP}/pod.yaml" <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${POD}
  namespace: ${NAMESPACE}
spec:
  restartPolicy: Never
  containers:
    - name: drill
      image: ${IMAGEM}
      # "Never" e não "IfNotPresent": a imagem é construída localmente e
      # importada no containerd. Com "IfNotPresent", uma tag que existe mas
      # aponta para um fragmento inválido (página HTML de 404 de um pull
      # anterior) é aceita sem validação — e o pod falha com
      # "unexpected media type text/html". Com "Never", ou a imagem local é
      # boa, ou o erro diz exatamente que ela não está lá.
      imagePullPolicy: Never
      # A imagem tem ENTRYPOINT ["/bin/sh", "-c"], herdado do Job de backup.
      # Sem sobrescrever, o Kubernetes entrega o "command" como argumento do
      # "sh -c" e o pod morre com "-c requires an argument".
      command: ["python3", "/scripts/restore_drill.py"]
      envFrom:
        - secretRef:
            name: lakecore-db-secret
      env:
        - name: GARAGE_S3_ENDPOINT
          value: "http://garage:3900"
        - name: S3_ACCESS_KEY
          valueFrom:
            secretKeyRef: {name: lakecore-s3-verify, key: S3_ACCESS_KEY}
        - name: S3_SECRET_KEY
          valueFrom:
            secretKeyRef: {name: lakecore-s3-verify, key: S3_SECRET_KEY}
      volumeMounts:
        - name: scripts
          mountPath: /scripts
  volumes:
    - name: scripts
      configMap:
        name: restore-drill-scripts
        defaultMode: 0755
YAML

kc -n "${NAMESPACE}" apply -f "${DIR_TMP}/pod.yaml" >/dev/null
echo "  pod criado; aguardando (até ${TIMEOUT_SEGUNDOS}s)"

FASE=""
for _ in $(seq 1 "${TIMEOUT_SEGUNDOS}"); do
  FASE="$(kc -n "${NAMESPACE}" get pod "${POD}" -o jsonpath='{.status.phase}' 2>/dev/null || echo '')"
  case "${FASE}" in
    Succeeded|Failed) break ;;
  esac
  sleep 1
done

echo
echo "---------------- saída do drill ----------------"
kc -n "${NAMESPACE}" logs "${POD}" 2>&1 || true
echo "-----------------------------------------------"
echo

CFG="$(kc -n "${NAMESPACE}" get pod "${POD}" -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}' 2>/dev/null || echo '')"

echo "[5/5] Veredito"
if [[ "${FASE}" == "Succeeded" && "${CFG}" == "0" ]]; then
  echo "  ✓ RESTORE PROVADO — o dump voltou a ser um catálogo idêntico"
  echo
  echo "  Isso é o que a Onda 6 existia para provar."
  exit 0
fi

echo "  ✗ DRILL FALHOU (fase=${FASE:-desconhecida}, exit=${CFG:-desconhecido})"
echo
echo "  O banco 'restore_drill' foi PRESERVADO para inspeção, se chegou a ser"
echo "  criado. Investigue com:"
echo "    microk8s kubectl -n ${NAMESPACE} exec postgresql-0 -- \\"
echo "      psql -U lakecore -d restore_drill -c '\\dt'"
echo "  Depois descarte:"
echo "    microk8s kubectl -n ${NAMESPACE} exec postgresql-0 -- \\"
echo "      psql -U lakecore -d postgres -c 'DROP DATABASE restore_drill'"
exit 1
