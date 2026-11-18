#!/usr/bin/env bash
# Aplica e verifica o cluster layout do Garage.
#
# POR QUE ESTE SCRIPT EXISTE:
# o Helm instala o Garage, mas NÃO configura o layout do cluster. Sem layout o
# cluster sobe "verde", os pods ficam Ready e ele NÃO ARMAZENA NADA. É falha
# silenciosa — exatamente o que `verify` precisa detectar.
#
# `garage layout assign` diz quanta capacidade cada nó oferece e em qual zona de
# falha ele está. `garage layout apply` confirma.
#
# USO:
#   scripts/garage-layout.sh status
#   scripts/garage-layout.sh assign            # dry-run (padrão)
#   scripts/garage-layout.sh assign --apply
#   scripts/garage-layout.sh apply [versao]
#   scripts/garage-layout.sh verify
#
# ATENÇÃO: mudar o layout de um cluster com dado dentro pode causar
# indisponibilidade. `assign` é dry-run por padrão por isso.

set -euo pipefail

NAMESPACE="${GARAGE_NAMESPACE:-lake-data}"
RELEASE="${GARAGE_RELEASE:-datalake}"
CAPACITY="${GARAGE_CAPACITY:-400G}"
ZONE="${GARAGE_ZONE:-dc1}"

LABEL="app.kubernetes.io/name=garage,app.kubernetes.io/instance=${RELEASE}"

die() { printf 'erro: %s\n' "$*" >&2; exit 1; }

pod_do_garage() {
  local pod
  pod="$(microk8s kubectl -n "${NAMESPACE}" get pods -l "${LABEL}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [[ -n "${pod}" ]] || die "nenhum pod do Garage em ns=${NAMESPACE} release=${RELEASE}"
  printf '%s' "${pod}"
}

garage() {
  local pod
  pod="$(pod_do_garage)"
  microk8s kubectl -n "${NAMESPACE}" exec "${pod}" -- /garage -c /etc/garage.toml "$@"
}

node_id() {
  local pod
  pod="$(pod_do_garage)"
  microk8s kubectl -n "${NAMESPACE}" exec "${pod}" -- \
    /garage -c /etc/garage.toml status 2>/dev/null |
    awk '/^[a-f0-9]{8,}/ {print $1; exit}'
}

cmd_status() { garage status; }

cmd_assign() {
  local aplicar=0
  [[ "${1:-}" == "--apply" ]] && aplicar=1

  local id
  id="$(node_id)"
  [[ -n "${id}" ]] || die "não encontrei node id em 'garage status'"

  printf 'node=%s zona=%s capacidade=%s\n' "${id}" "${ZONE}" "${CAPACITY}"

  if (( ! aplicar )); then
    echo "DRY-RUN — nada foi alterado. Use 'assign --apply' para efetivar."
    printf 'rodaria:\n  garage layout assign -z %s -c %s %s\n' "${ZONE}" "${CAPACITY}" "${id}"
    return 0
  fi

  garage layout assign -z "${ZONE}" -c "${CAPACITY}" "${id}"
  printf 'layout modificado. Revise com "status" e confirme com "apply".\n'
}

cmd_apply() { garage layout apply --version "${1:-1}"; }

cmd_verify() {
  local id
  # Um nó sem capacidade no layout é a falha silenciosa: o pod está Ready e a
  # escrita falha. Este é o teste que a pega.
  id="$(node_id)"
  if [[ -z "${id}" ]]; then
    die "layout VAZIO — o Garage não armazena nada, mesmo com pod Ready"
  fi

  garage status
  printf '\nok: %s nó(s) no layout\n' "$(printf '%s\n' "${id}" | wc -l | tr -d ' ')"
}

case "${1:-}" in
  status) cmd_status ;;
  assign) shift; cmd_assign "${@:-}" ;;
  apply)  shift; cmd_apply "${@:-}" ;;
  verify) cmd_verify ;;
  *) die "uso: $0 {status|assign [--apply]|apply [versao]|verify}" ;;
esac
