#!/usr/bin/env bash
# Mantém a ponte entre o servidor MCP (que roda no HOST) e o catálogo (que roda
# no cluster) e grava a URL local onde a tela a encontra.
#
# POR QUE ISTO EXISTE:
# o Secret `lakecore-db-chat` aponta para `postgresql:5432`, que é o nome do
# Service DENTRO do cluster. O servidor MCP é um subprocesso da tela e roda no
# host — ali esse nome não resolve. O erro aparece como
# "Name or service not known", que parece senha errada e não é.
#
# DESVIO DECLARADO: na instalação final (Onda 7) o MCP roda DENTRO do cluster,
# ao lado do Postgres, e este script deixa de ser necessário. Ele existe agora
# porque a tela ainda é local.
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - não abre porta para a rede: `port-forward` escuta só em 127.0.0.1
#   - não altera o Secret do cluster
#   - não expõe a senha na saída
#
# USO:
#   scripts/conectar-chat.sh            # sobe a ponte e grava a URL
#   scripts/conectar-chat.sh --status   # só informa se está de pé
#   scripts/conectar-chat.sh --down     # derruba a ponte

set -euo pipefail

NAMESPACE="lake-data"
PORTA_LOCAL=15432
ARQUIVO_URL="${HOME}/.hermes/lake-url.local"
LOG="/tmp/lake-chat-portforward.log"

kc() { microk8s kubectl "$@"; }

viva() { ss -ltn 2>/dev/null | grep -q ":${PORTA_LOCAL} "; }

case "${1:-}" in
  --status)
    if viva; then echo "ponte de pé em 127.0.0.1:${PORTA_LOCAL}"; else echo "ponte NÃO está de pé"; exit 1; fi
    exit 0 ;;
  --down)
    pkill -f "port-forward.*postgresql.*${PORTA_LOCAL}" 2>/dev/null && echo "ponte derrubada" || echo "nada a derrubar"
    exit 0 ;;
  -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
esac

if viva; then
  echo "ponte já estava de pé em 127.0.0.1:${PORTA_LOCAL}"
else
  # `setsid` desliga o processo do terminal: sem isso o port-forward morre
  # junto com o shell que o criou, e a tela perde o banco no meio de uma sessão.
  setsid microk8s kubectl -n "${NAMESPACE}" port-forward "svc/postgresql" \
    "${PORTA_LOCAL}:5432" >"${LOG}" 2>&1 &
  for _ in $(seq 1 20); do viva && break; sleep 0.5; done
  if ! viva; then
    echo "FALHOU: a ponte não subiu em 10s. Log em ${LOG}:" >&2
    tail -5 "${LOG}" >&2
    exit 1
  fi
  echo "ponte criada em 127.0.0.1:${PORTA_LOCAL}"
fi

# A URL é derivada do Secret a cada execução: assim uma troca de senha no
# cluster não fica sem efeito na tela.
if ! kc -n "${NAMESPACE}" get secret lakecore-db-chat >/dev/null 2>&1; then
  echo "FALHOU: Secret lakecore-db-chat não existe." >&2
  echo "  Crie com: scripts/criar-role-readonly.sh --apply" >&2
  exit 1
fi

URL_CLUSTER="$(kc -n "${NAMESPACE}" get secret lakecore-db-chat \
  -o jsonpath='{.data.LAKECORE_DATABASE_URL}' | base64 -d)"
URL_LOCAL="${URL_CLUSTER/@postgresql:5432\//@127.0.0.1:${PORTA_LOCAL}/}"

if [[ "${URL_LOCAL}" == "${URL_CLUSTER}" ]]; then
  echo "AVISO: não reconheci o host no Secret; gravando a URL sem alteração." >&2
fi

install -d -m 700 "$(dirname "${ARQUIVO_URL}")"
( umask 077; printf '%s\n' "${URL_LOCAL}" > "${ARQUIVO_URL}" )

echo "URL local gravada em ${ARQUIVO_URL} (modo 600)"
echo
echo "Aponte a tela para ela:"
echo "  hermes config set LAKECORE_DATABASE_URL \"\$(cat ${ARQUIVO_URL})\""
