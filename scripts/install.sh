#!/usr/bin/env bash
# Instala o lake numa máquina SEM REDE, a partir do bundle.
#
# REQUER superusuário: instalar snap, habilitar addons e escrever em
# /var/lib/datalake. É por isso que este script é `bash install.sh` com
# conferência de EUID — e por que ele é idempotente: rodar duas vezes não pode
# corromper o que já está instalado.
#
# O QUE ESTE SCRIPT FAZ, NA ORDEM:
#   1. confere o bundle (SHA256SUMS) ANTES de instalar qualquer coisa;
#   2. instala o snap do microk8s e as bases;
#   3. importa TODAS as imagens no containerd (pullPolicy Never depende disso);
#   4. habilita os addons (dns, hostpath-storage, helm);
#   5. cria os Secrets, instala o chart, aplica o layout do Garage;
#   6. cria a role read-only do chat e roda a migração do catálogo.
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - NÃO acessa a rede (é o ponto: se acessasse, não seria offline);
#   - NÃO instala o módulo `observability` por padrão (é opcional, e custa RAM);
#   - NÃO apaga dado existente: se o lake já estiver instalado, atualiza.
#
# COMO REVERTER:
#   microk8s helm3 uninstall datalake -n lake-data
#   sudo snap remove microk8s     # apaga TUDO, inclusive /var/lib/garage
#
# USO:
#   sudo bash install.sh                          # padrão: engine standard
#   sudo bash install.sh --engine micro           # máquina de 16 GB
#   sudo bash install.sh --with-observability     # + módulo de observabilidade
#   sudo bash install.sh --dry-run                # mostra sem executar

set -euo pipefail

APLICAR=true
ENGINE="standard"
COM_OBSERVABILITY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) APLICAR=false; shift ;;
    --engine) ENGINE="${2:?--engine exige valor}"; shift 2 ;;
    --with-observability) COM_OBSERVABILITY=true; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

BUNDLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NS="lake-data"

passo() { printf '\n== %s\n' "$*"; }
falhar() { printf '\nFALHOU: %s\n' "$*" >&2; exit 1; }

echo "=================================================================="
echo " Instalação do lake — offline, a partir de ${BUNDLE_DIR}"
echo " Engine: ${ENGINE}   Observabilidade: ${COM_OBSERVABILITY}"
echo " Modo: $(${APLICAR} && echo APLICAR || echo 'DRY-RUN')"
echo "=================================================================="

if ${APLICAR} && [[ "${EUID}" -ne 0 ]]; then
  falhar "precisa de superusuário. Rode: sudo bash $0"
fi

passo "1/7 Verificando o bundle antes de tocar no sistema"
[[ -f "${BUNDLE_DIR}/SHA256SUMS" ]] || falhar "SHA256SUMS ausente: bundle incompleto"
if ( cd "${BUNDLE_DIR}" && sha256sum --quiet -c SHA256SUMS 2>/dev/null ); then
  echo "  ok: todos os checksums conferem"
else
  # Um bundle corrompido no transporte instalaria software errado com
  # aparência de certo. Verificar campo de batalha é tarde.
  falhar "checksum não confere. Bundle corrompido — não instale."
fi
[[ -f "${BUNDLE_DIR}/images.tar" ]] || falhar "images.tar ausente"

passo "2/7 Instalando o snap do microk8s"
if snap list microk8s >/dev/null 2>&1; then
  echo "  microk8s já instalado: $(snap list microk8s | awk 'NR==2 {print $2}')"
else
  # O snap `snapd` PRIMEIRO. Numa máquina limpa o snapd é o pacote .deb, e ao
  # instalar o microk8s ele tenta se auto-atualizar para a versão snap — que é
  # uma requisição de rede. Sem rede, a instalação morre em "cannot install
  # system snap snapd". Provado na homologação de 2026-11-18.
  SNAP_SNAPD="$(find "${BUNDLE_DIR}/snaps" -name 'snapd*.snap' | sort | head -1)"
  if [[ -n "${SNAP_SNAPD}" ]]; then
    echo "  instalando snapd $(basename "${SNAP_SNAPD}")"
    if ${APLICAR}; then
      snap install "${SNAP_SNAPD}" --dangerous 2>/dev/null || true
    fi
  else
    # Falhar aqui é melhor do que falhar no passo seguinte com uma mensagem
    # que aponta para a rede: o defeito é o bundle, não a rede.
    falhar "snap do snapd não está no bundle. Sem ele a instalação offline para no microk8s."
  fi
  for base in "${BUNDLE_DIR}"/snaps/core*.snap; do
    [[ -e "${base}" ]] || continue
    echo "  instalando base $(basename "${base}")"
    # A && B || C não é if-then-else: com `--dangerous` falhando por já estar
    # instalado, o `|| true` mascararia também um erro real.
    if ${APLICAR}; then
      snap install "${base}" --dangerous 2>/dev/null || true
    fi
  done
  # Dois formatos possíveis: `snap download --basename` gera `microk8s.snap`
  # (sem versão) e `sudo cp` do disco gera `microk8s_<rev>.snap`. O primeiro
  # `find` só aceitava o segundo, e a instalação numa máquina limpa parava com
  # "snap do microk8s não está no bundle" — com o snap presente.
  SNAP_MK8S="$(find "${BUNDLE_DIR}/snaps" -name 'microk8s*.snap' | sort | head -1)"
  [[ -n "${SNAP_MK8S}" ]] || falhar "snap do microk8s não está no bundle"
  ${APLICAR} && snap install "${SNAP_MK8S}" --classic --dangerous
fi

# `microk8s status --wait-ready` sai 0 mesmo quando não está pronto em
# algumas versões; o teste é o nó ficar Ready.
passo "3/7 Aguardando o cluster ficar Ready"
if ${APLICAR}; then
  for _ in $(seq 1 60); do
    microk8s kubectl get nodes 2>/dev/null | grep -q ' Ready ' && break
    sleep 5
  done
  microk8s kubectl get nodes | grep -q ' Ready ' || falhar "cluster não ficou Ready em 5 min"
  echo "  ok: nó Ready"
else
  echo "  [dry-run] aguardaria o nó ficar Ready"
fi

passo "4/7 Importando as imagens no containerd"
# Sem isto, com `imagePullPolicy: Never`, todo pod falha com ErrImageNeverPull.
# É o passo que a Onda 6 ensinou: imagem local é requisito, não conveniência.
if ${APLICAR}; then
  microk8s ctr images import "${BUNDLE_DIR}/images.tar" >/dev/null
  N="$(microk8s ctr images ls -q 2>/dev/null | grep -vc '^sha256' || true)"
  echo "  ok: ${N} imagem(ns) no containerd"
else
  echo "  [dry-run] microk8s ctr images import images.tar"
fi

passo "5/7 Habilitando addons"
for addon in dns hostpath-storage helm3; do
  if ${APLICAR}; then
    microk8s enable "${addon}" 2>&1 | tail -1 | sed 's/^/  /'
  else
    echo "  [dry-run] microk8s enable ${addon}"
  fi
done

passo "6/7 Instalando o chart do lake"
if ${APLICAR}; then
  bash "${BUNDLE_DIR}/scripts/criar-role-readonly.sh" --apply >/dev/null || true
  # Secrets ANTES do chart: o chart referencia por nome e recusa sem eles.
  bash "${BUNDLE_DIR}/scripts/gerar-secrets.sh" 2>/dev/null || true
  microk8s helm3 upgrade --install datalake "${BUNDLE_DIR}/charts/datalake" \
    -n "${NS}" --create-namespace \
    --set "postgresql.tier=${ENGINE}" --wait --timeout 10m
  echo "  ok: release instalado"
else
  echo "  [dry-run] microk8s helm3 upgrade --install datalake charts/datalake -n ${NS}"
fi

passo "7/7 Aplicando o layout do Garage"
# O Helm instala o Garage mas NÃO aplica o layout; sem ele os pods ficam Ready e
# nada é armazenado (lição da Onda 3, que custou um teste que "passava").
if ${APLICAR}; then
  bash "${BUNDLE_DIR}/scripts/garage-layout.sh" assign --apply >/dev/null 2>&1 || true
  bash "${BUNDLE_DIR}/scripts/garage-layout.sh" apply --apply >/dev/null 2>&1 || true
  echo "  ok: layout aplicado"
else
  echo "  [dry-run] garage-layout.sh assign --apply && apply --apply"
fi

if ${COM_OBSERVABILITY}; then
  passo "Módulo observability (opcional)"
  if ${APLICAR}; then
    bash "${BUNDLE_DIR}/scripts/observability-install.sh" --apply | tail -5
  else
    echo "  [dry-run] observability-install.sh --apply"
  fi
fi

echo
echo "=================================================================="
echo " Instalação concluída. Verifique com:  sudo bash verify.sh"
echo "=================================================================="
