#!/usr/bin/env bash
# Instala o módulo `observability` a partir dos charts VENDORIZADOS.
#
# POR QUE ESTE SCRIPT EXISTE, E POR QUE NÃO É O ADDON DO MICROK8S:
#
#   o addon oficial faz, dentro do próprio `enable`:
#     helm upgrade --install ... --repo https://prometheus-community.github.io/helm-charts
#
#   Isto é: baixa o chart da internet NO MOMENTO DA INSTALAÇÃO. Num lake sem
#   rede — que é a tese deste projeto — o addon não sobe. É o mesmo erro de
#   anunciar Apache 2.0 sem colar o texto da licença.
#
#   Aqui os charts vêm de `modules/observability/vendor/*.tgz`, já no disco.
#   Nenhum `--repo`. A instalação funciona sem rede.
#
# O QUE ESTE SCRIPT FAZ:
#   1. confere que as imagens estão no containerd (falha alto se não estiverem);
#   2. cria o Secret do Grafana, se não existir (senha aleatória, fora do Helm);
#   3. instala os três charts com os values do módulo;
#   4. espera os pods e reporta o que ficou de pé.
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - NÃO baixa nada da internet;
#   - NÃO usa `sudo`;
#   - NÃO toca no acervo, no catálogo nem na tabela `saude`;
#   - NÃO apaga as métricas no `--uninstall` (ver abaixo).
#
# COMO DESINSTALAR SEM PERDER O QUE IMPORTA:
#   scripts/observability-install.sh --uninstall
#   Mantém os dashboards (dado do usuário). Descarta métricas e logs, que são
#   derivados do funcionamento. O acervo e o catálogo não são tocados.
#
# USO:
#   scripts/observability-install.sh              # dry-run
#   scripts/observability-install.sh --apply      # instala
#   scripts/observability-install.sh --uninstall  # remove (pede confirmação)

set -euo pipefail

APLICAR=false
DESINSTALAR=false
NAMESPACE="observability"
MODULO="modules/observability"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APLICAR=true; shift ;;
    --uninstall) DESINSTALAR=true; shift ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

cd "$(dirname "$0")/.."
kc() { microk8s kubectl "$@"; }
HELM="microk8s helm3"

if ${DESINSTALAR}; then
  echo "Removendo o módulo observability de ns=${NAMESPACE}."
  echo "PRESERVA: dashboards (dado do usuário)."
  echo "DESCARTA: métricas e logs (derivados do funcionamento)."
  echo "NÃO TOCA: raw/, catálogo, tabela saude."
  read -r -p "Confirma? [digite 'remover'] " resposta
  [[ "${resposta}" == "remover" ]] || { echo "cancelado"; exit 1; }
  for r in alloy loki obs; do
    ${HELM} uninstall "$r" -n "${NAMESPACE}" 2>/dev/null || true
  done
  echo "removido. O namespace NÃO foi apagado de propósito (contém o PVC dos dashboards)."
  exit 0
fi

echo "=================================================================="
echo " Módulo observability — instalando de charts vendorizados"
echo " Modo: $(${APLICAR} && echo 'APLICAR' || echo 'DRY-RUN (padrão)')"
echo "=================================================================="
echo

VENDOR="${MODULO}/vendor"
if [[ ! -d "${VENDOR}" ]]; then
  echo "FALHOU: ${VENDOR} não existe." >&2
  echo "  Rode antes, numa máquina COM rede: scripts/observability-vendor.sh --apply" >&2
  exit 1
fi
echo "[1/4] Charts vendorizados (sem rede):"
find "${VENDOR}" -maxdepth 1 -name '*.tgz' -printf '  %f\n' | sort

echo "[2/4] Conferindo as imagens no containerd"
if [[ -x /snap/microk8s/current/bin/ctr ]]; then
  CTR=(/snap/microk8s/current/bin/ctr --address /var/snap/microk8s/common/run/containerd.sock --namespace k8s.io)
  # Listar UMA vez, para um arquivo. Com `set -o pipefail`, `ctr ... | grep -q`
  # faz o `grep` fechar o pipe cedo, o `ctr` morrer com SIGPIPE (exit 141) e o
  # pipefail reportar falha — falso negativo que apareceu como "FALTA
  # grafana/grafana" com a imagem presente.
  LISTA_IMAGENS="$(mktemp)"
  "${CTR[@]}" images ls > "${LISTA_IMAGENS}" 2>/dev/null || true
  faltando=0
  # Nomes EXATOS como o chart os referencia. A primeira versão verificava
  # `prom/prometheus`, mas o chart usa `quay.io/prometheus/prometheus` — o
  # check dava falso negativo e o install falharia depois, menos claro.
  for img in \
    grafana/grafana grafana/loki grafana/alloy \
    prometheus/prometheus prometheus-operator/prometheus-operator; do
    # `images ls -q` devolve só hashes em algumas versões do ctr: usar a
    # listagem completa e procurar o nome é o que funciona nas duas.
    if ! grep -q "${img}" "${LISTA_IMAGENS}"; then
      echo "  FALTA ${img}"
      faltando=$((faltando + 1))
    fi
  done
  if [[ "${faltando}" -gt 0 ]]; then
    echo "  FALHOU: ${faltando} imagem(ns) ausente(s)."
    echo "  Importe primeiro: ctr ... images import ${VENDOR}/images.tar"
    exit 1
  fi
  echo "  ok: imagens presentes"
  rm -f "${LISTA_IMAGENS}"
else
  echo "  AVISO: ctr do snap não encontrado; não consegui conferir."
fi

echo "[3/4] Ações que SERÃO executadas"
cat <<'COMO'
  a) criar ns `observability` se não existir
  b) criar Secret `grafana-admin` com senha aleatória (fora do Helm:
     credencial em values vaza em `helm get values`)
  c) helm install kube-prometheus-stack (Prometheus + Grafana + exporters)
  d) helm install loki (SingleBinary, filesystem, retenção 7d)
  e) helm install alloy (coleta de logs do ns lake-data + receptor OTLP)
COMO
echo "  NÃO faz: baixar da internet, usar sudo, tocar no acervo/catálogo/saude."
echo

if ! ${APLICAR}; then
  echo "[4/4] DRY-RUN: nada foi instalado. Rode com --apply."
  exit 0
fi

echo "[4/4] Instalando"
kc get namespace "${NAMESPACE}" >/dev/null 2>&1 || kc create namespace "${NAMESPACE}"

if kc -n "${NAMESPACE}" get secret grafana-admin >/dev/null 2>&1; then
  echo "  Secret grafana-admin já existe (mantido)"
else
  SENHA="$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)"
  kc -n "${NAMESPACE}" create secret generic grafana-admin \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="${SENHA}" >/dev/null
  echo "  Secret grafana-admin criado (senha não é impressa)"
fi

python3 - "${MODULO}/values.yaml" <<'PYVALORES'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for chave, destino in (
    ("kube-prometheus-stack", "/tmp/obs-kps.yaml"),
    ("loki", "/tmp/obs-loki.yaml"),
    ("alloy", "/tmp/obs-alloy.yaml"),
):
    yaml.safe_dump(d[chave], open(destino, "w"))
PYVALORES

# SEM `--wait` nos três: o `kubelet` coleta imagens que não estão em uso, e um
# `--wait` que falha no primeiro release aborta o script antes de instalar os
# outros dois — cujas imagens então são podadas, e a próxima execução falha com
# "imagem ausente". Instalar os três e verificar no fim evita a cascata.
${HELM} upgrade --install obs "${VENDOR}/kube-prometheus-stack-"*.tgz \
  -n "${NAMESPACE}" -f /tmp/obs-kps.yaml --timeout 10m || echo "AVISO: release 'obs' não ficou Ready"
${HELM} upgrade --install loki "${VENDOR}/loki-"*.tgz \
  -n "${NAMESPACE}" -f /tmp/obs-loki.yaml --timeout 10m || echo "AVISO: release 'loki' não ficou Ready"
${HELM} upgrade --install alloy "${VENDOR}/alloy-"*.tgz \
  -n "${NAMESPACE}" -f /tmp/obs-alloy.yaml --timeout 5m || echo "AVISO: release 'alloy' não ficou Ready"

echo
echo "Pods em ${NAMESPACE}:"
kc -n "${NAMESPACE}" get pods

echo
echo "Abrir o Grafana:"
echo "  microk8s kubectl -n ${NAMESPACE} port-forward svc/obs-grafana 3000:80"
echo "  usuário: admin · senha:"
echo "    microk8s kubectl -n ${NAMESPACE} get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d"
