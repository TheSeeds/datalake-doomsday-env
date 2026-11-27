#!/usr/bin/env bash
# Build LOCAL das imagens próprias do lake (ingest e backup).
#
# PUBLICAÇÃO OFICIAL = CI (GitHub Actions), não este script:
#   o workflow `.github/workflows/publish-images.yml` sobe as imagens para o GHCR
#   automaticamente em toda TAG `v*` (buildx + GITHUB_TOKEN, sem login manual).
#   Este script serve para BUILD LOCAL / iteração de desenvolvimento e como
#   fallback declarado (ex.: homologar o artefato antes do release).
#
# POR QUE SÓ ESTAS DUAS:
#   a ingest (`Dockerfile`) e a backup (`docker/backup/Dockerfile`) são as únicas
#   imagens buildadas neste repositório. Toda infra (postgres, garage, microk8s,
#   observability) vem de registries públicos. As nossas vão para
#   `ghcr.io/theseeds/lakecore-{ingest,backup}:<tag>`.
#
# NOMES (alinhados ao install.sh):
#   `lakecore-ingest` / `lakecore-backup` — NUNCA `ingest`/`backup`, senão o
#   caminho online falha com ErrImagePull. (Bug corrigido 2026-11-27.)
#
# USO:
#   scripts/build-push-ghcr.sh                        # build local (padrão)
#   scripts/build-push-ghcr.sh --push --tag 1.0.0     # build + push (fallback manual)
#
# TAG: a versão de release (sem `v`), alinhada ao semver dos charts e do bundle.

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
echo " (Publicação oficial: CI em tag v* — ver publish-images.yml)"
echo "=================================================================="

precisa_docker

build "lakecore-ingest" Dockerfile . "${TAG}"
build "lakecore-backup" docker/backup/Dockerfile docker/backup "${TAG}"

if ! ${PUSH}; then
  echo
  echo "DRY-RUN: imagens buildadas localmente (não publicado)."
  echo "Publicação oficial: CI (tag v*). Fallback manual:"
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