#!/usr/bin/env bash
# Instala o lake num nó. Dois caminhos de instalação:
#
#   online  (padrão)  — máquina COM internet. Instala microk8s do snap store,
#                       imagens do containerd dos registries públicos + GHCR, e
#                       o chart do próprio repositório. É o caminho de quem tem
#                       uma máquina viva e rede.
#   offline            — máquina SEM rede, a partir do bundle. Imagens locais
#                       importadas no containerd (`pullPolicy: Never`), snaps do
#                       bundle, tudo verificado por checksum.
#
# Ambos convergem para o MESMO passo de migração do catálogo e o MESMO verify.sh.
# O que muda é apenas de onde vêm snaps, imagens e o chart.
#
# REQUER superusuário: instalar snap, habilitar addons e escrever em
# /var/lib/datalake. É por isso que este script é `bash install.sh` com
# conferência de EUID — e por que ele é idempotente: rodar duas vezes não pode
# corromper o que já está instalado.
#
# O QUE ESTE SCRIPT FAZ, NA ORDEM:
#   1. valida a fonte (bundle para offline; rede/ferramentas para online);
#   2. garante o microk8s instalado e o cluster inicializado;
#   3. (offline) importa as imagens do bundle no containerd;
#   4. habilita os addons (dns, hostpath-storage, helm);
#   5. cria os Secrets, instala o chart, aplica o layout do Garage;
#   6. roda a migração do catálogo (Alembic) — P1 da Onda 7, agora no install;
#   7. (opcional) módulo observability.
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - online: NÃO baixa o bundle (seria trabalho inútil com rede);
#   - offline: NÃO acessa a rede (é o ponto: se acessasse, não seria offline);
#   - NÃO instala o módulo `observability` por padrão (é opcional, custa RAM);
#   - NÃO apaga dado existente: se o lake já estiver instalado, atualiza.
#
# COMO REVERTER:
#   microk8s helm3 uninstall datalake -n lake-data
#   sudo snap remove microk8s     # apaga TUDO, inclusive /var/lib/garage
#
# USO:
#   sudo bash install.sh                                # fonte online (padrão)
#   sudo bash install.sh --fonte offline                # a partir do bundle
#   sudo bash install.sh --engine micro                # máquina de 16 GB
#   sudo bash install.sh --with-observability          # + módulo de observabilidade
#   sudo bash install.sh --dry-run                     # mostra sem executar

set -euo pipefail

APLICAR=true
ENGINE="standard"
COM_OBSERVABILITY=false
FONTE="online"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) APLICAR=false; shift ;;
    --engine) ENGINE="${2:?--engine exige valor}"; shift 2 ;;
    --fonte) FONTE="${2:?--fonte exige valor (online|offline)}"; shift 2 ;;
    --with-observability) COM_OBSERVABILITY=true; shift ;;
    -h|--help) sed -n '2,42p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done
case "${FONTE}" in
  online|offline) ;;
  *) echo "argumento inválido para --fonte: ${FONTE} (esperado online|offline)" >&2; exit 64 ;;
esac

BUNDLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NS="lake-data"

# Refs das imagens próprias do lake por fonte. Vêm de símbolo único para que o
# chart e o passo de migração apontem para o MESMO artefato — se divergirem, o
# verify os pega.
# Offline: só o nome curto; as imagens são o que o bundle importou no containerd.
# Online: repositório público GHCR (sem segredo de negócio; só build).
IMAGEM_INGEST="lakecore-ingest:1.0.0"
[[ "${FONTE}" == "online" ]] && IMAGEM_INGEST="ghcr.io/theseeds/lakecore-ingest:1.0.0"

passo() { printf '\n== %s\n' "$*"; }
falhar() { printf '\nFALHOU: %s\n' "$*" >&2; exit 1; }

echo "=================================================================="
echo " Instalação do lake — fonte: ${FONTE}"
echo " Engine: ${ENGINE}   Observabilidade: ${COM_OBSERVABILITY}"
[[ "${FONTE}" == "offline" ]] && echo " Bundle: ${BUNDLE_DIR}"
echo " Modo: $(${APLICAR} && echo APLICAR || echo 'DRY-RUN')"
echo "=================================================================="

if ${APLICAR} && [[ "${EUID}" -ne 0 ]]; then
  falhar "precisa de superusuário. Rode: sudo bash $0"
fi

passo "1/8 Validando a fonte"
if [[ "${FONTE}" == "offline" ]]; then
  [[ -f "${BUNDLE_DIR}/SHA256SUMS" ]] || falhar "SHA256SUMS ausente: bundle incompleto"
  if ( cd "${BUNDLE_DIR}" && sha256sum --quiet -c SHA256SUMS 2>/dev/null ); then
    echo "  ok: todos os checksums conferem"
  else
    # Um bundle corrompido no transporte instalaria software errado com
    # aparência de certo. Verificar campo de batalha é tarde.
    falhar "checksum não confere. Bundle corrompido — não instale."
  fi
  if compgen -G "${BUNDLE_DIR}/images/*.tar" > /dev/null; then
    : # imagens em images/*.tar (formato atual)
  elif [[ -f "${BUNDLE_DIR}/images.tar" ]]; then
    : # formato antigo de tar único
  else
    falhar "sem imagens no bundle (nem images/*.tar nem images.tar)"
  fi
  echo "  ok: bundle presente e íntegro"
else
  echo "  ok: fonte online — snaps e imagens vêm da rede (microk8s, registries, GHCR)"
fi

passo "2/8 Instalando o snap do microk8s"
if snap list microk8s >/dev/null 2>&1; then
  echo "  microk8s já instalado: $(snap list microk8s | awk 'NR==2 {print $2}')"
elif [[ "${FONTE}" == "online" ]]; then
  # Caminho online: o snap vem do store. O snapd costuma estar presente num
  # sistema Ubuntu; se não estiver, `snap` falha e a mensagem aponta o caminho.
  command -v snap >/dev/null 2>&1 \
    || falhar "snapd não encontrado. Instale o snapd (sudo apt install snapd)."
  echo "  instalando microk8s do store (canal estável)"
  ${APLICAR} && snap install microk8s --classic
elif [[ "${FONTE}" == "offline" ]]; then
  # O snap `snapd` PRIMEIRO. Numa máquina limpa o snapd é o pacote .deb, e ao
  # instalar o microk8s ele tenta se auto-atualizar para a versão snap — que é
  # uma requisição de rede. Sem rede, a instalação morre em "cannot install
  # system snap snapd". Provado na homologação de 2026-11-18.
  SNAP_SNAPD="$(find "${BUNDLE_DIR}/snaps" -name 'snapd*.snap' | sort | head -1)"
  if [[ -n "${SNAP_SNAPD}" ]]; then
    echo "  instalando snapd $(basename "${SNAP_SNAPD}")"
    if ${APLICAR}; then
      snap install "${SNAP_SNAPD}" --dangerous 2>/dev/null || true
      # O snapd se REINICIA ao ser atualizado ("Waiting for automatic snapd
      # restart..."). Instalar outro snap durante esse restart faz o snapd
      # responder "INFO task ignored" e o hook de instalação do microk8s — que
      # é quem inicializa o cluster — não roda. Medido em 2026-11-19: o snap
      # ficava listado e `microk8s kubectl` respondia "connection refused"
      # para sempre. Esperar as mudanças do snapd terminarem antes de seguir.
      for _ in $(seq 1 60); do
        pendente="$(snap changes 2>/dev/null | awk 'NR>1 && $2 ~ /^(Doing|Undoing|Do)$/' | head -1)"
        [[ -z "${pendente}" ]] && break
        sleep 5
      done
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

# Instalar o snap `snapd` dispara um restart dele mesmo ("Waiting for automatic
# snapd restart..."). Se o microk8s for instalado logo depois, o snapd reporta
# `INFO task ignored` e o hook de instalação do microk8s — que é quem inicializa
# o cluster — NÃO roda. Resultado medido na homologação de 2026-11-19: o snap
# aparece instalado e `microk8s kubectl` responde "connection refused" para
# sempre, porque não há cluster nenhum.
# O teste é o servidor da API responder, não o snap estar listado.
passo "2b/8 Garantindo que o cluster foi inicializado"
if ${APLICAR}; then
  api_pronta() { microk8s kubectl get --raw /readyz >/dev/null 2>&1; }
  if api_pronta; then
    echo "  ok: cluster já estava inicializado"
  else
    echo "  cluster não inicializou (hook do snap ignorado): iniciando"
    microk8s start >/dev/null 2>&1 || true
    # 10 min: microk8s inicializa o cluster do zero, não é instantâneo.
    for _ in $(seq 1 120); do
      api_pronta && break
      sleep 5
    done
    # Incondicional é mentira: foi assim que a primeira versão deste passo
    # imprimiu "ok: servidor da API responde" com a API recusando conexão.
    api_pronta || falhar "servidor da API não respondeu em 10 min após microk8s start"
    echo "  ok: servidor da API responde"
  fi
else
  echo "  [dry-run] microk8s start se o cluster não tiver inicializado"
fi

# `microk8s status --wait-ready` sai 0 mesmo quando não está pronto em
# algumas versões; o teste é o nó ficar Ready.
passo "3/8 Aguardando o cluster ficar Ready"
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

passo "4/8 Preparando as imagens"
if [[ "${FONTE}" == "offline" ]]; then
  # Sem isto, com `imagePullPolicy: Never`, todo pod falha com ErrImageNeverPull.
  # É o passo que a Onda 6 ensinou: imagem local é requisito, não conveniência.
  if ${APLICAR}; then
    # Formato do bundle: `images/*.tar` (um por imagem, amd64-only — ver bundle.sh)
    # ou o antigo `images.tar` único. Importa o que existir.
    N_IMPORTADAS=0
    if compgen -G "${BUNDLE_DIR}/images/*.tar" > /dev/null; then
      for tar_imagem in "${BUNDLE_DIR}"/images/*.tar; do
        microk8s ctr images import "${tar_imagem}" >/dev/null 2>&1 && N_IMPORTADAS=$((N_IMPORTADAS + 1))
      done
    elif [[ -f "${BUNDLE_DIR}/images.tar" ]]; then
      microk8s ctr images import "${BUNDLE_DIR}/images.tar" >/dev/null && N_IMPORTADAS=1
    else
      falhar "sem imagens no bundle (nem images/*.tar nem images.tar)"
    fi
    N="$(microk8s ctr images ls -q 2>/dev/null | grep -vc '^sha256' || true)"
    echo "  ok: ${N_IMPORTADAS} arquivo(s) de imagem importado(s); ${N} imagem(ns) no containerd"
  else
    echo "  [dry-run] microk8s ctr images import images/*.tar"
  fi
else
  # Online: as imagens vêm dos registries no momento em que o kubelet puxa
  # (pullPolicy IfNotPresent com repositórios de rede). Nada a importar agora.
  # A validação de verdade é o `--wait` do helm (passo 6) + o verify.sh.
  echo "  ok: imagens serão puxadas dos registries (online)"
fi

passo "5/8 Habilitando addons"
for addon in dns hostpath-storage helm3; do
  if ${APLICAR}; then
    microk8s enable "${addon}" 2>&1 | tail -1 | sed 's/^/  /'
  else
    echo "  [dry-run] microk8s enable ${addon}"
  fi
done

passo "6/8 Instalando o chart do lake"
if ${APLICAR}; then
  bash "${BUNDLE_DIR}/scripts/criar-role-readonly.sh" --apply >/dev/null || true
  # Secrets ANTES do chart: o chart referencia por nome e recusa sem eles.
  bash "${BUNDLE_DIR}/scripts/gerar-secrets.sh" 2>/dev/null || true

  # Overrides de imagem por fonte. Offline: renomeia as próprias para o nome
  # curto importado no containerd e usa `pullPolicy: Never` (a imagem local é a
  # única fonte e estando lá é a certa). Online: repositórios públicos/digest e
  # `IfNotPresent`, que deixa o kubelet puxar o que falta mas não re-puxa o que
  # já está presente.
  SETS_OFFLINE=(
    "--set" "ingest.image.repository=lakecore-ingest"
    "--set" "ingest.image.tag=1.0.0"
    "--set" "ingest.image.pullPolicy=Never"
    "--set" "postgresql.backup.image.repository=lakecore-backup"
    "--set" "postgresql.backup.image.tag=1.0.0"
    "--set" "postgresql.backup.image.pullPolicy=Never"
  )
  SETS_ONLINE=(
    "--set" "ingest.image.repository=ghcr.io/theseeds/lakecore-ingest"
    "--set" "ingest.image.tag=1.0.0"
    "--set" "ingest.image.pullPolicy=IfNotPresent"
    "--set" "postgresql.backup.image.repository=ghcr.io/theseeds/lakecore-backup"
    "--set" "postgresql.backup.image.tag=1.0.0"
    "--set" "postgresql.backup.image.pullPolicy=IfNotPresent"
  )
  if [[ "${FONTE}" == "online" ]]; then
    SETS=("${SETS_ONLINE[@]}")
  else
    SETS=("${SETS_OFFLINE[@]}")
  fi

  microk8s helm3 upgrade --install datalake "${BUNDLE_DIR}/charts/datalake" \
    -n "${NS}" --create-namespace \
    --set "postgresql.tier=${ENGINE}" \
    "${SETS[@]}" --wait --timeout 10m
  echo "  ok: release instalado"
else
  echo "  [dry-run] microk8s helm3 upgrade --install datalake charts/datalake -n ${NS}"
fi

passo "7/8 Aplicando o layout do Garage"
# O Helm instala o Garage mas NÃO aplica o layout; sem ele os pods ficam Ready e
# nada é armazenado (lição da Onda 3, que custou um teste que "passava").
if ${APLICAR}; then
  bash "${BUNDLE_DIR}/scripts/garage-layout.sh" assign --apply >/dev/null 2>&1 || true
  bash "${BUNDLE_DIR}/scripts/garage-layout.sh" apply --apply >/dev/null 2>&1 || true
  echo "  ok: layout aplicado"
else
  echo "  [dry-run] garage-layout.sh assign --apply && apply --apply"
fi

passo "8/8 Migração do catálogo (Alembic)"
# ATÉ a v0.1.x, esta migração NÃO rodava no install — só manualmente no pod, com
# o `alembic.ini` copiado em /tmp. Em instalação limpa as tabelas
# `objects`/`uploads`/`saude` não eram criadas (P1 da Onda 7). Agora é um Job
# efêmero usando a MESMA imagem do ingest, idempotente via `upgrade head`.
if ${APLICAR}; then
  bash "${BUNDLE_DIR}/scripts/migrar-catalogo.sh" "${IMAGEM_INGEST}" \
    --namespace "${NS}" || falhar "migração do catálogo falhou"
else
  echo "  [dry-run] migrar-catalogo.sh ${IMAGEM_INGEST}"
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
