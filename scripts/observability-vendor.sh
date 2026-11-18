#!/usr/bin/env bash
# Vendoriza os charts e as imagens do módulo `observability` para uso OFFLINE.
#
# POR QUE ESTE SCRIPT EXISTE:
#   o addon `observability` do microk8s executa, dentro do próprio `enable`:
#
#     helm upgrade --install ... --repo https://prometheus-community.github.io/helm-charts
#
#   Ou seja: baixa o chart da INTERNET no momento da instalação. Num lake sem
#   rede — que é a tese do projeto — o addon não sobe. É o mesmo erro de
#   anunciar Apache 2.0 sem colar o texto da licença.
#
#   Este script é rodado UMA VEZ, numa máquina COM rede, e produz:
#     modules/observability/vendor/*.tgz    (charts, ~2 MB)
#     modules/observability/vendor/images.tar (imagens, ~1 GB)
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - NÃO instala nada;
#   - NÃO usa `--repo` (é justamente o que ele elimina);
#   - NÃO usa `sudo`;
#   - NÃO altera o cluster.
#
# O QUE FICA SEM PROVA:
#   - que o bundle resultante instala numa máquina sem rede. Isso só se prova
#     num ambiente limpo (Onda 7).
#
# USO:
#   scripts/observability-vendor.sh              # dry-run: mostra o que faria
#   scripts/observability-vendor.sh --apply      # baixa e empacota

set -euo pipefail

APLICAR=false
MODULO="modules/observability"
HELM="microk8s helm3"

#: Versões pinadas, TIradas de `helm search repo` em 2026-11-18.
#: Chart "latest" numa bundle offline é bundle que não reproduz: a pessoa daqui
#: a seis meses baixa outra coisa. Estes números foram medidos, não supostos —
#: a primeira versão deste script tinha versões que não existiam.
KPS_VERSAO="93.4.0"
LOKI_VERSAO="7.6.0"
ALLOY_VERSAO="1.16.0"
HELM_REPO_PROM="https://prometheus-community.github.io/helm-charts"
HELM_REPO_GRAFANA="https://grafana.github.io/helm-charts"
HELM_REPO_ALLOY="https://grafana.github.io/helm-charts"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APLICAR=true; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

cd "$(dirname "$0")/.."

echo "=================================================================="
echo " Vendorizando módulo: observability"
echo " Modo: $(${APLICAR} && echo 'APLICAR' || echo 'DRY-RUN (padrão)')"
echo "=================================================================="
echo
echo "Charts (pinados):"
echo "  kube-prometheus-stack ${KPS_VERSAO}   (${HELM_REPO_PROM})"
echo "  loki                 ${LOKI_VERSAO}   (${HELM_REPO_GRAFANA})"
echo "  alloy                ${ALLOY_VERSAO}  (${HELM_REPO_ALLOY})"
echo
echo "Imagens (baixadas com docker pull, exportadas com docker save):"
echo "  grafana/grafana, prom/prometheus, grafana/loki, grafana/alloy,"
echo "  quay.io/prometheus-operator/prometheus-operator,"
echo "  quay.io/prometheus/node-exporter,"
echo "  registry.k8s.io/kube-state-metrics/kube-state-metrics"
echo
echo "NÃO faz: instalar nada, usar --repo na instalação, usar sudo, tocar no cluster."
echo

if ! ${APLICAR}; then
  echo "DRY-RUN: nada foi baixado."
  echo "Rode com --apply para vendorizar de fato."
  exit 0
fi

VENDOR="${MODULO}/vendor"
mkdir -p "${VENDOR}"

echo "[1/3] Baixando charts pinados"
${HELM} repo add prometheus-community "${HELM_REPO_PROM}" >/dev/null 2>&1 || true
${HELM} repo add grafana "${HELM_REPO_GRAFANA}" >/dev/null 2>&1 || true
${HELM} repo update >/dev/null 2>&1 || true

${HELM} pull prometheus-community/kube-prometheus-stack --version "${KPS_VERSAO}" \
  -d "${VENDOR}"
${HELM} pull grafana/loki --version "${LOKI_VERSAO}" -d "${VENDOR}"
${HELM} pull grafana/alloy --version "${ALLOY_VERSAO}" -d "${VENDOR}"

echo "  charts em ${VENDOR}:"
find "${VENDOR}" -maxdepth 1 -name "*.tgz" -printf "    %f\n" | sort

echo "[2/3] Descobrindo as imagens REAIS a partir dos charts"
# Derivar em vez de listar à mão: a primeira versão deste script tinha versões
# que eu inventei, e elas não existiam. A fonte de verdade é o chart pinado,
# renderizado com os values deste módulo.
VALORES="${MODULO}/values.yaml"
python3 - "${VALORES}" <<'PYVALORES'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for chave, destino in (
    ("kube-prometheus-stack", "/tmp/obs-kps-values.yaml"),
    ("loki", "/tmp/obs-loki-values.yaml"),
    ("alloy", "/tmp/obs-alloy-values.yaml"),
):
    yaml.safe_dump(d[chave], open(destino, "w"))
PYVALORES

IMAGENS_ARQ="/tmp/obs-imagens.txt"
: > "${IMAGENS_ARQ}"

{
  ${HELM} template obs prometheus-community/kube-prometheus-stack \
    --version "${KPS_VERSAO}" -f /tmp/obs-kps-values.yaml --namespace observability
  ${HELM} template loki grafana/loki \
    --version "${LOKI_VERSAO}" -f /tmp/obs-loki-values.yaml --namespace observability
  ${HELM} template alloy grafana/alloy \
    --version "${ALLOY_VERSAO}" -f /tmp/obs-alloy-values.yaml --namespace observability
} 2>/dev/null \
  | grep -oE 'image: "?[^"[:space:]]+' \
  | sed 's/image: //;s/"//g;s/@sha256.*//' \
  | sort -u > "${IMAGENS_ARQ}.bruto"

# Remove imagens que existem só para o teste do próprio chart (`helm test`) e
# para canary. Elas não rodam no lake, e num bundle offline cada MB conta.
grep -vE 'bats/bats|loki-canary|loki-helm-test|nginx-unprivileged|library/busybox' \
  "${IMAGENS_ARQ}.bruto" > "${IMAGENS_ARQ}" || true

echo "  imagens a empacotar:"
sed 's/^/    /' "${IMAGENS_ARQ}"
echo "  (excluídas por serem só de teste do chart:)"
grep -E 'bats/bats|loki-canary|loki-helm-test|nginx-unprivileged|library/busybox' \
  "${IMAGENS_ARQ}.bruto" | sed 's/^/    /' || true

while read -r img; do
  [[ -n "${img}" ]] || continue
  echo "  pull ${img}"
  docker pull --quiet "${img}"
done < "${IMAGENS_ARQ}"

echo "[3/3] Empacotando para transporte"
mapfile -t LISTA < "${IMAGENS_ARQ}"
docker save -o "${VENDOR}/images.tar" "${LISTA[@]}"

# Checksums: um bundle sem eles não permite detectar corrupção no transporte,
# e corrupção silenciosa de imagem é pior que ausência de imagem.
( cd "${VENDOR}" && sha256sum ./*.tgz images.tar > SHA256SUMS )

echo
echo "Pronto. Conteúdo de ${VENDOR}:"
du -sh "${VENDOR}"/*
echo
echo "No destino (sem rede):"
echo "  /snap/microk8s/current/bin/ctr --address /var/snap/microk8s/common/run/containerd.sock \\"
echo "    --namespace k8s.io images import ${VENDOR}/images.tar"
echo "  microk8s helm3 install obs ${VENDOR}/kube-prometheus-stack-${KPS_VERSAO}.tgz -n observability --create-namespace"
echo
echo "O QUE FICA SEM PROVA: instalar em máquina sem rede. Isso é a Onda 7."
