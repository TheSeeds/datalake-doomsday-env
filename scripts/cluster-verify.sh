#!/usr/bin/env bash
# Valida o cluster do lake: addons, Garage (layout!) e PostgreSQL.
#
# Este script é o critério de pronto da Onda 3, em forma executável.
# Ele FALHA quando algo está "verde mas quebrado" — o caso do Garage sem layout,
# em que os pods estão Ready e nada é armazenado.
#
# USO: scripts/cluster-verify.sh

set -euo pipefail

NAMESPACE_DATA="lake-data"
RELEASE="datalake"
FALHAS=0

ok()   { printf '  ok    %s\n' "$*"; }
falha(){ printf '  FALHA %s\n' "$*"; FALHAS=$((FALHAS + 1)); }

kc() { microk8s kubectl "$@"; }

echo "== addons do microk8s =="
if microk8s kubectl get storageclass >/dev/null 2>&1 &&
   [[ -n "$(microk8s kubectl get storageclass -o name 2>/dev/null)" ]]; then
  ok "storageclass presente"
else
  falha "nenhum storageclass — rode 'microk8s enable hostpath-storage' (precisa sudo)"
fi

echo
echo "== namespace e release =="
if kc get namespace "${NAMESPACE_DATA}" >/dev/null 2>&1; then
  ok "namespace ${NAMESPACE_DATA}"
else
  falha "namespace ${NAMESPACE_DATA} ausente"
fi

if microk8s helm3 list -n "${NAMESPACE_DATA}" 2>/dev/null | grep -q "^${RELEASE}\b"; then
  ok "release ${RELEASE} instalado"
else
  falha "release ${RELEASE} não instalado"
fi

echo
echo "== pods =="
for componente in garage postgresql; do
  pods="$(kc -n "${NAMESPACE_DATA}" get pods -l "app.kubernetes.io/name=${componente}" \
    -o jsonpath='{.items[*].status.phase}' 2>/dev/null || true)"
  if [[ -z "${pods}" ]]; then
    falha "${componente}: nenhum pod encontrado"
  elif grep -qvw "Running" <<<"${pods}"; then
    falha "${componente}: pod( s) não Running: ${pods}"
  else
    ok "${componente}: Running"
  fi
done

echo
echo "== Garage: layout do cluster =="
# A falha silenciosa da Onda 3: DaemonSet Running sem layout = não armazena.
if scripts/garage-layout.sh verify >/dev/null 2>&1; then
  ok "layout aplicado"
else
  falha "layout AUSENTE — o Garage não armazena nada (rode 'scripts/garage-layout.sh assign --apply' e depois 'apply')"
fi

echo
echo "== PostgreSQL: aceita conexão =="
if kc -n "${NAMESPACE_DATA}" exec "statefulset/postgresql" -- \
     pg_isready -U lakecore -d lakecore >/dev/null 2>&1; then
  ok "pg_isready responde"
else
  falha "pg_isready não respondeu"
fi

echo
if (( FALHAS > 0 )); then
  echo "RESULTADO: ${FALHAS} falha(s). Onda 3 NÃO concluída."
  exit 1
fi
echo "RESULTADO: tudo verificável está ok."
echo "Pendente de prova: escrita real de objeto (exige chave S3 criada)."
