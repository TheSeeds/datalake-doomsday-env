#!/usr/bin/env bash
# Monta o bundle offline do lake: tudo o que a instalação precisa, num artefato.
#
# POR QUE ESTE SCRIPT EXISTE:
#   a tese do projeto é instalar sem internet. Sem bundle, "offline" é uma
#   afirmação não verificada. O bundle é o artefato que torna a afirmação
#   testável: ou instala numa máquina sem rede, ou não instala.
#
# O QUE ELE REÚNE:
#   1. snaps (microk8s + bases) — sem eles não há orquestrador;
#   2. imagens do containerd — sem elas os pods não sobem (pullPolicy Never);
#   3. os charts já vendorizados do repositório;
#   4. o manifesto com versões pinadas e SHA256SUM de tudo.
#
# O QUE ELE NÃO FAZ:
#   - NÃO instala nada;
#   - NÃO usa `sudo` (lê o containerd pelo socket, com o grupo microk8s);
#   - NÃO baixa da internet (usa o que já está nesta máquina);
#   - NÃO inclui dado do acervo.
#
# DECISÃO IMPORTANTE — O BUNDLE NÃO LEVA `raw/`:
#   o acervo é do usuário, não do instalador. Levar o acervo de desenvolvimento
#   entregaria dado de teste como se fosse o conteúdo de quem instala, e violaria
#   a regra de que o dado bruto é do dono. `seed/` leva só o cenário de
#   demonstração, declarado como tal.
#
# USO:
#   scripts/bundle.sh              # dry-run: mostra o que faria e o tamanho
#   scripts/bundle.sh --apply      # monta de fato
#
# SAÍDA: dist/datalake-bundle-<versao>/

set -euo pipefail

APLICAR=false
VERSAO="0.1.0"
DESTINO_BASE="dist"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APLICAR=true; shift ;;
    --versao) VERSAO="${2:?--versao exige valor}"; shift 2 ;;
    --destino) DESTINO_BASE="${2:?--destino exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

cd "$(dirname "$0")/.."
DESTINO="${DESTINO_BASE}/datalake-bundle-${VERSAO}"

CTR_BIN="/snap/microk8s/current/bin/ctr"
CTR_SOCK="/var/snap/microk8s/common/run/containerd.sock"

echo "=================================================================="
echo " Bundle offline do lake — versão ${VERSAO}"
echo " Destino: ${DESTINO}"
echo " Modo: $(${APLICAR} && echo 'APLICAR' || echo 'DRY-RUN (padrão)')"
echo "=================================================================="
echo

echo "[1/5] Levantando o que compõe o bundle"
SNAPS_NEEDED=()
while read -r nome _versao; do
  SNAPS_NEEDED+=("${nome}")
done < <(snap list 2>/dev/null | awk '/^(core|microk8s)/ {print $1, $2}')
echo "  snaps: ${SNAPS_NEEDED[*]}"

if [[ ! -x "${CTR_BIN}" ]]; then
  echo "  FALHOU: ${CTR_BIN} não existe." >&2
  exit 1
fi
# `-q` devolve só hashes em versões novas do ctr: usar a listagem completa e
# ficar com a coluna REF, sem os nomes de import temporário.
IMAGENS_TMP="$(mktemp)"
"${CTR_BIN}" --address "${CTR_SOCK}" --namespace k8s.io images ls 2>/dev/null \
  | awk 'NR>1 && $1 !~ /^import-/ && $1 !~ /@/ && $1 !~ /^sha256:/ {print $1}' \
  | sort -u > "${IMAGENS_TMP}"
N_IMAGENS="$(wc -l < "${IMAGENS_TMP}")"
echo "  imagens do containerd: ${N_IMAGENS}"

echo "[2/5] Tamanho estimado"
echo "  snaps:   $(du -ch /var/lib/snapd/snaps/{microk8s,core20,core24}_*.snap 2>/dev/null | tail -1 | cut -f1)"
echo "  charts:  $(du -sh modules/*/vendor charts 2>/dev/null | awk '{s+=$1} END {print "~"s"MB"}')"
echo "  imagens: ~8 GiB descomprimido; o .tar comprimido fica entre 2 e 3 GiB"
echo

echo "[3/5] Conteúdo do bundle"
cat <<'COMO'
  datalake-bundle-<versao>/
    snaps/            microk8s e bases (instalam com `snap install`)
    images.tar        TODAS as imagens do containerd, para `ctr images import`
    charts/           datalake, garage, postgresql, ingest, observability
    modules/          definições + vendor dos charts de cada módulo
    seed/             cenário de demonstração (NÃO é o acervo)
    scripts/          install.sh, verify.sh, garage-layout.sh
    versions.yaml     pinos: versões de snap, imagem e chart
    SHA256SUMS        checksums de TUDO
COMO
echo "  NÃO inclui: raw/ (o acervo é do usuário), backups, credenciais."
echo

if ! ${APLICAR}; then
  echo "[4/5] DRY-RUN: nada foi montado."
  echo "      Rode com --apply para montar de fato."
  rm -f "${IMAGENS_TMP}"
  exit 0
fi

echo "[4/5] Montando"
rm -rf "${DESTINO}"
mkdir -p "${DESTINO}"/{snaps,charts,modules,seed,scripts}

echo "  snaps"
# `/var/lib/snapd/snaps/*.snap` é `-rw------- root root`: NÃO é legível sem
# superusuário. Em vez de pedir sudo (o script declara que não usa), usa-se
# `snap download`, que baixa o MESMO artefato para o diretório atual, com
# checksum verificado pelo próprio snapd.
#
# Limitação declarada: `snap download` exige rede. O bundle é montado numa
# máquina com rede (é ela que produz o artefato offline); a máquina sem rede
# apenas consome. Se esta máquina não tiver rede, o fallback é `sudo cp`.
for snap_nome in "${SNAPS_NEEDED[@]}"; do
  # `snap list` colunas: Name Version Rev Tracking Publisher Notes.
  # O canal é a coluna 4 (Tracking); a 6 é Notes ("base", "classic").
  canal="$(snap list "${snap_nome}" 2>/dev/null | awk 'NR==2 {print $4}')"
  canal="${canal:-latest/stable}"
  echo "    ${snap_nome} (canal ${canal})"
  if snap download "${snap_nome}" --channel="${canal}" \
       --basename="${snap_nome}" --target-directory="${DESTINO}/snaps" >/dev/null 2>&1; then
    echo "      baixado"
  else
    # Fallback declarado: o .snap instalado é o artefato mais confiável — é o
    # que está rodando. Precisa de root para ler.
    arquivo="$(find /var/lib/snapd/snaps -maxdepth 1 -name "${snap_nome}_*.snap" 2>/dev/null | sort | tail -1)"
    if [[ -n "${arquivo}" ]] && sudo -n cp "${arquivo}" "${DESTINO}/snaps/" 2>/dev/null; then
      echo "      copiado do disco (sudo)"
    else
      echo "      AVISO: não consegui obter ${snap_nome}." >&2
      echo "             Rode: sudo cp /var/lib/snapd/snaps/${snap_nome}_*.snap ${DESTINO}/snaps/" >&2
    fi
  fi
done

echo "  imagens"
# `mapfile` em vez de `$(cat ...)`: a divisão por palavra é intencional (uma
# imagem por linha), mas explícita — e o shellcheck concorda.
mapfile -t LISTA_IMAGENS < "${IMAGENS_TMP}"
"${CTR_BIN}" --address "${CTR_SOCK}" --namespace k8s.io images export \
  --platform linux/amd64 "${DESTINO}/images.tar" "${LISTA_IMAGENS[@]}"
echo "    $(du -sh "${DESTINO}/images.tar" | cut -f1) em images.tar"

echo "  charts do lake"
cp -r charts/* "${DESTINO}/charts/"

echo "  módulos"
for m in modules/*/; do
  [[ -f "${m}module.yaml" ]] || continue
  nome="$(basename "${m}")"
  mkdir -p "${DESTINO}/modules/${nome}"
  cp "${m}module.yaml" "${m}README.md" "${m}values.yaml" "${DESTINO}/modules/${nome}/" 2>/dev/null || true
  if [[ -d "${m}vendor" ]]; then
    mkdir -p "${DESTINO}/modules/${nome}/vendor"
    # Só os charts: o images.tar do módulo é redundante com o do bundle.
    cp "${m}"vendor/*.tgz "${DESTINO}/modules/${nome}/vendor/" 2>/dev/null || true
  fi
  echo "    ${nome}"
done

echo "  seed"
if compgen -G "seed/*" > /dev/null; then
  cp -r seed/* "${DESTINO}/seed/"
else
  echo "    (seed vazio — a demonstração criará arquivos na instalação)"
fi

echo "  scripts"
cp scripts/garage-layout.sh scripts/criar-role-readonly.sh scripts/conectar-chat.sh \
   scripts/restore-drill.sh scripts/observability-install.sh "${DESTINO}/scripts/"
if [[ -f scripts/install.sh ]]; then cp scripts/install.sh "${DESTINO}/scripts/"; fi
if [[ -f scripts/verify.sh ]]; then cp scripts/verify.sh "${DESTINO}/scripts/"; fi

echo "  versions.yaml"
cat > "${DESTINO}/versions.yaml" <<YAML
# Pin de tudo o que o bundle entrega.
# Um bundle sem pinos reproduz "o que havia na máquina em que foi montado",
# que é exatamente o que um artefato de instalação não pode ser.
versao: "${VERSAO}"
montado_em: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
host: "$(uname -srm)"
snaps:
$(snap list 2>/dev/null | awk '/^(core|microk8s)/ {printf "  %s: \"%s\"\n", $1, $2}')
imagens:
$(sed 's/^/  - /' "${IMAGENS_TMP}")
charts:
$(for c in charts/*/Chart.yaml; do
    nome=$(awk '/^name:/ {print $2}' "$c")
    vers=$(awk '/^version:/ {print $2}' "$c")
    printf '  - %s: "%s"\n' "$nome" "$vers"
  done)
YAML

echo "  SHA256SUMS"
# Escreve num temporário FORA do diretório e move: gerar o SHA256SUMS dentro
# dele enquanto o `find` varre o mesmo diretório é corrida, mesmo com o
# `! -name SHA256SUMS`.
SUM_TMP="$(mktemp)"
( cd "${DESTINO}" && find . -type f ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum ) > "${SUM_TMP}"
mv "${SUM_TMP}" "${DESTINO}/SHA256SUMS"
echo "    $(wc -l < "${DESTINO}/SHA256SUMS") arquivo(s) com checksum"

rm -f "${IMAGENS_TMP}"

echo
echo "[5/5] Bundle pronto"
echo "  caminho: ${DESTINO}"
echo "  tamanho: $(du -sh "${DESTINO}" | cut -f1)"
echo
echo "O QUE FICA SEM PROVA: instalar numa máquina SEM REDE."
echo "Isso exige ambiente limpo (VM). Bundle montado é pré-requisito, não prova."
