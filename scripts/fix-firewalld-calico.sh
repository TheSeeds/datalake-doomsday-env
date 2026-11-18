#!/usr/bin/env bash
# Libera o FORWARD do firewalld para as interfaces do Calico.
#
# PROBLEMA: firewalld filtra a cadeia FORWARD. INPUT passa (host→pod OK) e
# FORWARD morre (pod→pod falha). O Calico depende de FORWARD; o pacote morre
# antes de ele ver.
#
# Este script:
#   1. mostra o estado atual (antes)
#   2. adiciona vxlan.calico e as interfaces cali* à zona trusted, de forma
#      PERMANENTE
#   3. recarrega o firewalld
#   4. verifica o resultado (depois)
#
# É IDEMPOTENTE: rodar duas vezes não causa erro nem duplica regra.
#
# USO:
#   sudo bash scripts/fix-firewalld-calico.sh
#   sudo bash scripts/fix-firewalld-calico.sh --reverter   # desfaz
#
# Depois dele, o teste que importa:
#   microk8s kubectl -n lake-data run tv --rm -i --restart=Never \
#     --image=busybox:1.36 -- nc -zv -w4 postgresql 5432

set -euo pipefail

ZONA="trusted"
REVERTER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reverter|--revert) REVERTER=1; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "erro: precisa de root. Rode com sudo:" >&2
  echo "  sudo bash $0 ${*:-}" >&2
  exit 77
fi

if ! command -v firewall-cmd >/dev/null 2>&1; then
  echo "erro: firewall-cmd não encontrado (firewalld não está instalado)" >&2
  exit 1
fi

if ! systemctl is-active --quiet firewalld; then
  echo "aviso: firewalld NÃO está ativo."
  echo "       Se a rede de pods funciona, nada a fazer."
  systemctl is-active firewalld || true
  exit 0
fi

# Interfaces do Calico presentes AGORA. `vxlan.calico` é a principal; as `cali*`
# são por pod e mudam de nome quando pods são recriados — por isso adicionamos o
# sufixo `cali+`, que cobre as futuras.
mapfile -t CALI_IFACES < <(ip -br link 2>/dev/null | awk '/^(cali|vxlan\.calico)/{sub(/@.*/,"",$1); print $1}')

echo "=============================================================="
echo " ANTES"
echo "=============================================================="
echo "firewalld: $(systemctl is-active firewalld)"
echo "vxlan.calico presente: $(ip -br link show vxlan.calico >/dev/null 2>&1 && echo sim || echo nao)"
echo "interfaces cali*: ${#CALI_IFACES[@]}"
echo "zona ${ZONA} hoje:"
firewall-cmd --zone="${ZONA}" --list-all 2>/dev/null | sed 's/^/  /'
echo

if (( REVERTER )); then
  echo "=============================================================="
  echo " REVERTENDO"
  echo "=============================================================="
  firewall-cmd --permanent --zone="${ZONA}" --remove-interface=vxlan.calico 2>/dev/null || true
  firewall-cmd --permanent --zone="${ZONA}" --remove-interface=cali+ 2>/dev/null || true
  for iface in "${CALI_IFACES[@]}"; do
    firewall-cmd --permanent --zone="${ZONA}" --remove-interface="${iface}" 2>/dev/null || true
  done
  firewall-cmd --reload >/dev/null
  echo "revertido. A rede de pods volta a falhar, se era isso que você queria."
  exit 0
fi

echo "=============================================================="
echo " APLICANDO"
echo "=============================================================="

# `vxlan.calico` existe sempre que o Calico está de pé. Se não existir, o Calico
# não subiu — avisar é melhor que adicionar regra para interface fantasma.
if ip -br link show vxlan.calico >/dev/null 2>&1; then
  if firewall-cmd --permanent --zone="${ZONA}" --add-interface=vxlan.calico 2>/dev/null; then
    echo "  + vxlan.calico"
  else
    echo "  = vxlan.calico (já estava)"
  fi
else
  echo "  ! vxlan.calico ausente — o Calico não está de pé. Verifique:"
  echo "      microk8s kubectl -n kube-system get pods -l k8s-app=calico-node"
fi

# `cali+` cobre as interfaces que ainda vão nascer. Firewalld aceita o sufixo
# mesmo sem a interface existir.
if firewall-cmd --permanent --zone="${ZONA}" --add-interface='cali+' 2>/dev/null; then
  echo "  + cali+  (cobre pods futuros)"
else
  echo "  = cali+  (já estava, ou versão do firewalld não suporta sufixo)"
  # Fallback: adicionar as interfaces existentes uma por uma.
  for iface in "${CALI_IFACES[@]}"; do
    [[ "${iface}" == "vxlan.calico" ]] && continue
    if firewall-cmd --permanent --zone="${ZONA}" --add-interface="${iface}" 2>/dev/null; then
      echo "  + ${iface}"
    fi
  done
fi

echo
echo "recarregando firewalld..."
firewall-cmd --reload >/dev/null
echo "ok"

echo
echo "=============================================================="
echo " DEPOIS"
echo "=============================================================="
firewall-cmd --zone="${ZONA}" --list-all 2>/dev/null | sed 's/^/  /'

echo
echo "=============================================================="
echo " PRÓXIMO PASSO — teste que importa"
echo "=============================================================="
cat <<'FIM'
  microk8s kubectl -n lake-data run tv --rm -i --restart=Never \
    --image=busybox:1.36 -- nc -zv -w4 postgresql 5432

  Esperado: "postgresql (10.152.183.x:5432) open"

  Se ainda falhar, rode e me mostre a saída:

    scripts/diagnostico-rede.sh

  Para desfazer tudo:

    sudo bash scripts/fix-firewalld-calico.sh --reverter
FIM
