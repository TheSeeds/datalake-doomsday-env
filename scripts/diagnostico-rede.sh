#!/usr/bin/env bash
# Diagnóstico da rede de pods do microk8s.
#
# NÃO precisa de root. Coleta tudo que importa e imprime num formato que dá para
# copiar inteiro (ou salvar em arquivo com --salvar).
#
# USO:
#   scripts/diagnostico-rede.sh
#   scripts/diagnostico-rede.sh --salvar /tmp/rede.txt
#
# O que ele responde, em ordem:
#   1. o firewalld está filtrando FORWARD?
#   2. o Calico está de pé?
#   3. o host alcança o pod?
#   4. o pod alcança o pod? (a pergunta que importa)

set -uo pipefail

SAIDA=""
if [[ "${1:-}" == "--salvar" ]]; then
  SAIDA="${2:?--salvar exige caminho}"
  exec > >(tee "${SAIDA}") 2>&1
fi

secao() { printf '\n===== %s =====\n' "$*"; }
kc() { microk8s kubectl "$@"; }

echo "diagnóstico de rede — $(date -u +%Y-%m-%dT%H:%M:%SZ)"

secao "1. HOST"
# shellcheck disable=SC1091  # /etc/os-release é lido para obter PRETTY_NAME
echo "sistema : $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-?}")"
echo "kernel  : $(uname -r)"
echo "ip_forward: $(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null)"

secao "2. FIREWALLD (a causa mais provável)"
if command -v firewall-cmd >/dev/null 2>&1; then
  echo "estado: $(systemctl is-active firewalld 2>/dev/null || echo desconhecido)"
  echo
  echo "zonas ativas:"
  firewall-cmd --get-active-zones 2>/dev/null | sed 's/^/  /'
  echo
  echo "vxlan.calico em alguma zona?"
  firewall-cmd --get-active-zones 2>/dev/null | awk '/^[a-z]/{z=$1} /^  interfaces:/{if ($0 ~ /vxlan\.calico|cali/) print "  SIM na zona " z}'
  firewall-cmd --get-active-zones 2>/dev/null | grep -q "cali" \
    && echo "  (encontrado)" || echo "  NÃO — é isto que quebra pod→pod"
  echo
  echo "zona trusted:"
  firewall-cmd --zone=trusted --list-all 2>/dev/null | sed 's/^/  /'
else
  echo "firewall-cmd ausente (firewalld não instalado) — não é a causa"
fi

secao "3. ROTAS DO HOST"
echo "blackhole (ruído, se houver):"
ip route 2>/dev/null | grep blackhole | sed 's/^/  /' || echo "  nenhuma"
echo
echo "vxlan.calico:"
ip -4 addr show vxlan.calico 2>/dev/null | grep inet | sed 's/^/  /' || echo "  ausente"
echo
echo "interfaces cali*:"
ip -br link 2>/dev/null | awk '/^cali/{print "  " $1}' | head -8

secao "4. PODS"
kc -n lake-data get pods -o custom-columns=\
'NOME:.metadata.name,IP:.status.podIP,PRONTO:.status.containerStatuses[0].ready' \
  --no-headers 2>/dev/null | sed 's/^/  /'

secao "5. CALICO"
kc -n kube-system get pods -l k8s-app=calico-node \
  -o custom-columns='NOME:.metadata.name,PRONTO:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount' \
  --no-headers 2>/dev/null | sed 's/^/  /'

secao "6. TESTE HOST -> POD"
PODIP="$(kc -n lake-data get pod postgresql-0 -o jsonpath='{.status.podIP}' 2>/dev/null)"
if [[ -n "${PODIP}" ]]; then
  echo -n "host -> ${PODIP}:5432  "
  timeout 4 bash -c "echo > /dev/tcp/${PODIP}/5432" 2>/dev/null && echo "OK" || echo "falha"
else
  echo "  sem pod do postgres"
fi

secao "7. TESTE POD -> POD (o que importa)"
echo "criando pod temporário..."
kc -n lake-data run diag-net --rm -i --restart=Never --image=busybox:1.36 -- \
  sh -c 'printf "  pod -> postgresql:5432  "; nc -zv -w4 postgresql 5432 2>&1; printf "  pod -> garage:3900      "; nc -zv -w4 garage 3900 2>&1' \
  2>&1 | grep -vE "^If you don|^pod .* deleted" | sed 's/^/  /'

secao "CONCLUSÃO"
if firewall-cmd --get-active-zones 2>/dev/null | grep -q "cali"; then
  echo "  firewalld tem as interfaces do Calico em zona — rede deve funcionar"
else
  echo "  firewalld NÃO tem as interfaces do Calico em zona"
  echo "  → rode: sudo bash scripts/fix-firewalld-calico.sh"
fi

if [[ -n "${SAIDA}" ]]; then
  echo
  echo "(saída também salva em ${SAIDA})"
fi
