#!/usr/bin/env bash
# Valida o cluster do lake: storage, componentes, Garage (layout!) e PostgreSQL.
#
# Este script é o critério de pronto da Onda 3 em forma executável. Ele FALHA
# quando algo está "verde mas quebrado" — o caso do Garage sem layout, em que os
# pods estão Ready e nada é armazenado.
#
# IMPORTANTE — POR QUE NÃO USA `kubectl exec`/`logs`:
# neste host o IP mudou (192.168.1.103 → .11) e o certificado do microk8s não
# acompanhou. Consequência: `get` funciona; `exec`, `logs` e `port-forward` falham
# com x509. O script detecta isso e degrada com AVISO EXPLÍCITO em vez de
# reportar falha do cluster. Rodar `sudo microk8s refresh-certs --cert ca.crt`
# resolve — e é passo de sudo (ver docs/requisitos-sudo.md).
#
# USO: scripts/cluster-verify.sh

set -euo pipefail

NAMESPACE="lake-data"
RELEASE="datalake"
FALHAS=0
AVISOS=0

ok()    { printf '  ok    %s\n' "$*"; }
aviso() { printf '  AVISO %s\n' "$*"; AVISOS=$((AVISOS + 1)); }
falha() { printf '  FALHA %s\n' "$*"; FALHAS=$((FALHAS + 1)); }

kc() { microk8s kubectl "$@"; }

# Detecta se `exec` está funcional. Sem isso, verificação interna do Garage e
# `pg_isready` via exec são impossíveis — e o script precisa dizer isso, não
# transformar limitação de ferramenta em falha de infraestrutura.
exec_funciona() {
  local pod
  pod="$(kc -n "${NAMESPACE}" get pods -l app.kubernetes.io/name=garage \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [[ -n "${pod}" ]] || return 1
  kc -n "${NAMESPACE}" exec "${pod}" -- true >/dev/null 2>&1
}

echo "== storage =="
if [[ -n "$(kc get storageclass -o name 2>/dev/null)" ]]; then
  ok "storageclass: $(kc get storageclass -o jsonpath='{.items[0].metadata.name}')"
else
  falha "nenhum storageclass — PVC ficará Pending (ver docs/requisitos-sudo.md)"
fi

echo
echo "== release =="
if microk8s helm3 list -n "${NAMESPACE}" 2>/dev/null | grep -q "^${RELEASE}"; then
  ok "release ${RELEASE} instalado"
else
  falha "release ${RELEASE} não instalado"
fi

echo
echo "== pods =="
for componente in garage postgresql; do
  ready="$(kc -n "${NAMESPACE}" get pods -l "app.kubernetes.io/name=${componente}" \
    -o jsonpath='{.items[*].status.containerStatuses[*].ready}' 2>/dev/null || true)"
  if [[ -z "${ready}" ]]; then
    falha "${componente}: nenhum pod"
  elif grep -qv "true" <<<"${ready}"; then
    falha "${componente}: nem todos Ready (${ready})"
  else
    ok "${componente}: Ready"
  fi
done

echo
echo "== PVC =="
fase_pvc="$(kc -n "${NAMESPACE}" get pvc -o jsonpath='{.items[*].status.phase}' 2>/dev/null || true)"
if [[ -z "${fase_pvc}" ]]; then
  aviso "nenhum PVC encontrado"
elif grep -qv "Bound" <<<"${fase_pvc}"; then
  falha "PVC não Bound (${fase_pvc}) — Postgres não persiste"
else
  ok "PVC Bound"
fi

echo
echo "== Garage: layout do cluster =="
# A falha silenciosa da Onda 3: DaemonSet Running sem layout = não armazena.
# O layout é verificável de fora, pelo estado em disco no host.
LAYOUT="/var/lib/garage/meta/cluster_layout"
if [[ -f "${LAYOUT}" ]]; then
  if [[ -s "${LAYOUT}" ]]; then
    ok "cluster_layout presente e não vazio"
  else
    falha "cluster_layout vazio — Garage NÃO armazena (rode scripts/garage-layout.sh)"
  fi
else
  falha "cluster_layout ausente — Garage NÃO armazena (rode scripts/garage-layout.sh)"
fi

echo
echo "== dados do Garage em disco =="
if [[ -d /var/lib/garage/data ]]; then
  blocos="$(find /var/lib/garage/data -type f ! -name garage-marker 2>/dev/null | wc -l)"
  tamanho="$(du -sh /var/lib/garage/data 2>/dev/null | cut -f1)"
  if (( blocos > 0 )); then
    ok "${blocos} bloco(s) de objeto, ${tamanho} em /var/lib/garage/data"
  else
    aviso "sem blocos ainda — objetos <1MiB ficam inlinados no LMDB (meta), não em data/"
  fi
fi

echo
echo "== certificado do apiserver (exec/logs) =="
if exec_funciona; then
  ok "kubectl exec funcional"
else
  aviso "kubectl exec/logs bloqueados por x509 (IP do host mudou)."
  aviso "  → sudo microk8s refresh-certs --cert ca.crt"
  aviso "  → verificação interna via exec ficou de fora deste relatório"
fi

echo
if (( FALHAS > 0 )); then
  echo "RESULTADO: ${FALHAS} falha(s), ${AVISOS} aviso(s). Onda 3 NÃO concluída."
  exit 1
fi
if (( AVISOS > 0 )); then
  echo "RESULTADO: verificável ok, ${AVISOS} aviso(s) — leia acima antes de chamar de pronta."
  exit 0
fi
echo "RESULTADO: tudo verificável está ok."
