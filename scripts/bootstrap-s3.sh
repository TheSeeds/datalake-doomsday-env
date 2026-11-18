#!/usr/bin/env bash
# Provisiona a chave S3 do papel `ingest` e o Secret correspondente.
#
# Por que existe: a chave nasce DENTRO do Garage (que é quem sabe gerá-la) e
# precisa chegar ao Kubernetes como Secret. Fazer isso à mão toda vez é onde
# alguém cola credencial no lugar errado.
#
# Política do papel (ADR-011): write-only no prefixo `raw/`. O ingestor grava
# mas não lê o acervo — comprometer o ingestor não exfiltra dado.
#
# IDEMPOTENTE: se a chave já existe no Garage, reaproveita; se o Secret já existe,
# não sobrescreve.
#
# USO: scripts/bootstrap-s3.sh [--namespace lake-data] [--chave lakecore-ingest]

set -euo pipefail

NAMESPACE="lake-data"
NOME_CHAVE="lakecore-ingest"
BUCKET="raw"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="${2:?}"; shift 2 ;;
    --chave) NOME_CHAVE="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

kc() { microk8s kubectl "$@"; }

die() { printf 'erro: %s\n' "$*" >&2; exit 1; }

pod_garage() {
  local pod
  pod="$(kc -n "${NAMESPACE}" get pods -l app.kubernetes.io/name=garage \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [[ -n "${pod}" ]] || die "nenhum pod do Garage em ns=${NAMESPACE}"
  printf '%s' "${pod}"
}

garage() {
  local pod
  pod="$(pod_garage)"
  kc -n "${NAMESPACE}" exec "${pod}" -- /garage -c /etc/garage.toml "$@"
}

echo "== buckets =="
# `raw` guarda o dado bruto; `backup` guarda dump do catálogo. São separados
# porque a política é oposta: `raw` nunca expira, `backup` tem retenção.
for b in "${BUCKET}" backup; do
  garage bucket create "${b}" 2>/dev/null && echo "bucket ${b} criado" \
    || echo "bucket ${b} já existe"
done

echo "== chave =="
# `key create` NÃO é idempotente: criar duas vezes gera duas chaves com o mesmo
# nome, e `key info <nome>` passa a responder "N matching keys" — erro obscuro
# que aconteceu na primeira execução deste script. Verificar antes é obrigatório.
existente="$(garage key list 2>/dev/null | awk -v n="${NOME_CHAVE}" '$2 == n {print $1}')"

if [[ -z "${existente}" ]]; then
  garage key create "${NOME_CHAVE}" >/dev/null
  echo "chave ${NOME_CHAVE} criada"
elif [[ "$(wc -w <<<"${existente}")" -gt 1 ]]; then
  # Duplicata de nome é estado inconsistente: não dá para saber qual é a boa.
  # Falhar aqui é melhor que escolher uma ao acaso e gravar Secret errado.
  die "existem várias chaves '${NOME_CHAVE}' no Garage: $(tr '\n' ' ' <<<"${existente}"). Remova as sobras com 'garage key delete <id>' e rode de novo."
else
  echo "chave ${NOME_CHAVE} já existe (reaproveitando)"
fi

ID="$(garage key list 2>/dev/null | awk -v n="${NOME_CHAVE}" '$2 == n {print $1}')"
[[ -n "${ID}" ]] || die "não consegui obter o Key ID de ${NOME_CHAVE}"

echo "== permissões: write-only em ${BUCKET}/ =="
# Sem `--read`: é a política, não descuido. `--owner` também não: quem ingere não
# administra o bucket.
garage bucket allow --write "${BUCKET}" --key "${NOME_CHAVE}" >/dev/null

SECRET="$(garage key info "${ID}" --show-secret | awk '/Secret key:/ {print $3}')"
[[ -n "${SECRET}" ]] || die "não consegui obter o Secret"

echo "== Secret do Kubernetes =="
if kc -n "${NAMESPACE}" get secret lakecore-s3-ingest >/dev/null 2>&1; then
  echo "lakecore-s3-ingest já existe (mantido — sobrescrever trocaria a chave em uso)"
else
  kc -n "${NAMESPACE}" create secret generic lakecore-s3-ingest \
    --from-literal=S3_ACCESS_KEY="${ID}" \
    --from-literal=S3_SECRET_KEY="${SECRET}" >/dev/null
  echo "lakecore-s3-ingest criado"
fi

echo
echo "papel ingest pronto:"
garage bucket info "${BUCKET}" 2>/dev/null | sed 's/^/  /' || true
echo
echo "atenção: a chave é write-only. Verificar leitura com ela DEVE falhar —"
echo "é o que prova que o papel está correto."

# --- Chave de VERIFICAÇÃO (com leitura) --------------------------------------
#
# Por que duas chaves: a de `ingest` é write-only por política (ADR-011), e por
# isso não consegue responder "o objeto está lá?" — `HeadObject` recebe 403 e 403
# não distingue "ausente" de "sem permissão" (ADR-013).
#
# Separar as chaves resolve sem afrouxar a política: quem ingere não lê, quem
# verifica não escreve. Uma credencial que faz as duas coisas é a que ninguém
# consegue auditar.
NOME_VERIF="lakecore-verify"

echo
echo "== chave de verificação (leitura) =="
existentes_v="$(garage key list 2>/dev/null | awk -v n="${NOME_VERIF}" '$2 == n {print $1}')"

if [[ -z "${existentes_v}" ]]; then
  garage key create "${NOME_VERIF}" >/dev/null
  echo "chave ${NOME_VERIF} criada"
elif [[ "$(wc -w <<<"${existentes_v}")" -gt 1 ]]; then
  die "existem várias chaves '${NOME_VERIF}': $(tr '\n' ' ' <<<"${existentes_v}"). Remova as sobras e rode de novo."
else
  echo "chave ${NOME_VERIF} já existe"
fi

ID_V="$(garage key list 2>/dev/null | awk -v n="${NOME_VERIF}" '$2 == n {print $1}')"
garage bucket allow --read "${BUCKET}" --key "${ID_V}" >/dev/null
# A chave de verificação também precisa ESCREVER em `backup/`: é ela que o Job
# de backup usa para enviar o dump. Ler o acervo e escrever backup são papéis
# compatíveis (nenhum dos dois altera `raw/`).
garage bucket allow --read --write backup --key "${ID_V}" >/dev/null

SECRET_V="$(garage key info "${ID_V}" --show-secret | awk '/Secret key:/ {print $3}')"

if kc -n "${NAMESPACE}" get secret lakecore-s3-verify >/dev/null 2>&1; then
  echo "lakecore-s3-verify já existe (mantido)"
else
  kc -n "${NAMESPACE}" create secret generic lakecore-s3-verify \
    --from-literal=S3_ACCESS_KEY="${ID_V}" \
    --from-literal=S3_SECRET_KEY="${SECRET_V}" >/dev/null
  echo "lakecore-s3-verify criado"
fi
