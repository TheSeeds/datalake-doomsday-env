#!/usr/bin/env bash
# Constrói e publica as imagens próprias do lake (ingest e backup) no GHCR.
#
# POR QUE SÓ ESTAS DUAS:
#   a ingest (`Dockerfile`) e a backup (`docker/backup/Dockerfile`) são as únicas
#   imagens buildadas neste repositório. Toda a infra (postgres, garage, microk8s,
#   observability) já vem de registries públicos. Publicar no GHCR o que é nosso
#   deixa o caminho de instalação ONLINE usar o repositório público sem segredo
#   de negócio no artefato — só imagem de build, como combinado.
#
# NAMESPACE GHCR:
#   `ghcr.io/theseeds/*` (org GitHub `TheSeeds`). O push exige autenticação com
#   um PAT com escopo `write:packages` — que você roda, nunca este script pede
#   senha (regra 9). O CI pode reutilizar `GITHUB_TOKEN` num workflow devidamente
#   autorizado.
#
# USO:
#   scripts/build-push-ghcr.sh                # build local, SÓ build (sem push)
#   scripts/build-push-ghcr.sh --push --tag 1.0.0   # build + push no GHCR
#
# TAG:
#   padrão: a versão de release (ver scripts/bundle.sh) — mantém bundies e
#   imagens GHCR alinhados por semver. Bump de versão = nova tag nos dois lados.

set -euo pipefail

PUSH=false
TAG="1.0.0"
ORG="theseeds"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push) PUSH=true; shift ;;
    --tag) TAG="${2:?--tag exige valor}"; shift 2 ;;
    --org) ORG="${2:?--org exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

cd "$(dirname "$0")/.."

precisa_docker() {
  command -v docker >/dev/null 2>&1 || { echo "FALHOU: docker não encontrado" >&2; exit 1; }
}

build() {
  local nome="$1"; local caminho="$2"; local ctx="$3"; local tag="$4"
  local ref="ghcr.io/${ORG}/${nome}:${tag}"
  echo "  build ${nome} → ${ref}"
  docker build -t "${ref}" -f "${caminho}" "${ctx}"
}

echo "=================================================================="
echo " Build das imagens próprias do lake → GHCR (org ${ORG})"
echo " Tag: ${TAG}   Push: ${PUSH}"
echo "=================================================================="

precisa_docker

build "ingest" Dockerfile . "${TAG}"
build "backup" docker/backup/Dockerfile docker/backup "${TAG}"

if ! ${PUSH}; then
  echo
  echo "DRY-RUN: imagens buildadas localmente (não publicado)."
  echo "Rode com --push para publicar em ghcr.io/${ORG}/"
  echo "  docker login ghcr.io   # com PAT write:packages (você executa)"
  echo "  scripts/build-push-ghcr.sh --push"
  exit 0
fi

echo
echo "[push] publicando em ghcr.io/${ORG}/"
for nome in lakecore-ingest lakecore-backup; do
  ref="ghcr.io/${ORG}/${nome}:${TAG}"
  echo "  push ${ref}"
  docker push "${ref}"
done

echo
echo "OK. Imagens publicadas com tag ${TAG}."
echo "Caminho online usará:"
echo "  ghcr.io/${ORG}/lakecore-ingest:${TAG}"
echo "  ghcr.io/${ORG}/lakecore-backup:${TAG}"