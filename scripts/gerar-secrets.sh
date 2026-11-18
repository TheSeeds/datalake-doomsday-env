#!/usr/bin/env bash
# Gera os Secrets que os charts exigem e NÃO podem vir do Helm.
#
# POR QUE FORA DO CHART:
# valor gerado pelo Helm fica registrado em `helm get values` e no histórico do
# release. Credencial ali é credencial vazada. Este script gera uma vez e a
# cria como Secret; o chart apenas referencia por nome.
#
# IDEMPOTENTE: se o Secret já existe, não sobrescreve — sobrescrever trocaria a
# chave do Garage e o cluster pararia de enxergar os próprios nós.
#
# USO:
#   scripts/gerar-secrets.sh [--namespace lake-data]
#
# Pré-requisito: microk8s (o kubectl vem de `microk8s kubectl`).

set -euo pipefail

NAMESPACE="lake-data"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="${2:?--namespace exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

kc() { microk8s kubectl "$@"; }

kc get namespace "${NAMESPACE}" >/dev/null 2>&1 || kc create namespace "${NAMESPACE}"

criar_se_ausente() {
  local nome="$1"; shift
  if kc -n "${NAMESPACE}" get secret "${nome}" >/dev/null 2>&1; then
    printf '%-28s já existe (mantido)\n' "${nome}"
    return 0
  fi
  kc -n "${NAMESPACE}" create secret generic "${nome}" "$@" >/dev/null
  printf '%-28s criado\n' "${nome}"
}

# --- Garage: segredo de RPC e token de admin ---------------------------------
# RPC secret precisa ser 32 bytes em hex (64 caracteres).
criar_se_ausente garage-rpc-secret \
  --from-literal=GARAGE_RPC_SECRET="$(openssl rand -hex 32)" \
  --from-literal=GARAGE_ADMIN_TOKEN="$(openssl rand -base64 32)"

# --- PostgreSQL: credenciais do catálogo -------------------------------------
criar_se_ausente lakecore-db-secret \
  --from-literal=POSTGRES_USER=lakecore \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)" \
  --from-literal=POSTGRES_DB=lakecore

echo
echo "segredos prontos em ns=${NAMESPACE}."
echo "NÃO os commite, nem os coloque em values.yaml."
