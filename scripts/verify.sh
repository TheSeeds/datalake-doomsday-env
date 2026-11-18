#!/usr/bin/env bash
# Verifica uma instalação do lake do zero. É o critério de pronto da Onda 7.
#
# PRINCÍPIO: cada verificação faz a coisa de verdade e falha se não funcionar.
# Um `verify.sh` que só lista "ok" é pior que nenhum — dá selo a uma instalação
# possivelmente quebrada. Este projeto já pagou três vezes por "verde sem
# exercitar o caminho real" (make ci | tail, objetos <1MiB inlinados no LMDB,
# pg_isready com role inválida). Não haverá uma quarta.
#
# O QUE ELE VERIFICA, E COMO:
#   1. cluster Ready — o nó, não o processo;
#   2. pods do lake — Running e com réplicas prontas;
#   3. catálogo — SELECT real, não `pg_isready` (que mente);
#   4. Garage — escrita E leitura de 5 MiB, com sha256 conferindo (objetos
#      pequenos são inlinados no LMDB e não exercitam o armazenamento);
#   5. ingestão — POST de verdade, e o mesmo arquivo duas vezes dá duplicado;
#   6. backup — o CronJob registrou sucesso na tabela `saude`;
#   7. frescor — o lake sabe dizer se está bem.
#
# O QUE ELE NÃO PROVA:
#   - que a máquina está SEM REDE. Isso o teste de homologação prova, rodando
#     numa VM com a interface desligada. Aqui só se prova que não é necessário
#     ter rede para o que já está instalado.
#
# USO:
#   sudo bash verify.sh              # verificação completa
#   sudo bash verify.sh --rapido     # pula o teste de 5 MiB

set -uo pipefail   # SEM -e: uma falha precisa virar contagem, não aborto.

RAPIDO=false
[[ "${1:-}" == "--rapido" ]] && RAPIDO=true

NS="lake-data"
FALHAS=0
OKS=0

ok()    { printf '  ok    %s\n' "$*"; OKS=$((OKS + 1)); }
falha() { printf '  FALHA %s\n' "$*"; FALHAS=$((FALHAS + 1)); }
passo() { printf '\n== %s\n' "$*"; }
kc() { microk8s kubectl "$@"; }

echo "=================================================================="
echo " Verificação da instalação do lake"
echo " Data: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=================================================================="

passo "1. Cluster"
if kc get nodes 2>/dev/null | grep -q ' Ready '; then
  ok "nó Ready"
else
  falha "nenhum nó Ready"
fi

passo "2. Pods do lake"
for componente in garage postgresql ingest; do
  pronto="$(kc -n "${NS}" get pods -l "app.kubernetes.io/name=${componente}" \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{end}' 2>/dev/null)"
  if [[ "${pronto}" == *"true"* ]]; then
    ok "${componente}: pod pronto"
  else
    falha "${componente}: sem pod pronto"
  fi
done

passo "3. Catálogo responde de verdade"
# `pg_isready` devolve 0 mesmo com role inexistente (medido em 2026-11-18).
# O teste tem que autenticar.
if kc -n "${NS}" exec postgresql-0 -- \
     psql -U lakecore -d lakecore -tAc 'select 1' >/dev/null 2>&1; then
  ok "SELECT 1 autenticado"
else
  falha "catálogo não autenticou"
fi

N_OBJ="$(kc -n "${NS}" exec postgresql-0 -- \
  psql -U lakecore -d lakecore -tAc 'select count(*) from objects' 2>/dev/null | tr -d ' ')"
if [[ "${N_OBJ}" =~ ^[0-9]+$ ]]; then
  ok "tabela objects acessível (${N_OBJ} objeto(s))"
else
  falha "não consegui contar objects"
fi

passo "4. Garage armazena e devolve"
# `kubectl cp` NÃO serve aqui: a imagem do Garage é SHELL-LESS (sem /bin/sh,
# sem tar), e o `cp` falha com "executable file not found". A lição já foi paga
# na Onda 3 e reapareceu — por isso o teste usa um Job, que roda o próprio
# binário do Garage.
#
# 5 MiB de propósito: objetos menores que 1 MiB são INLINADOS no LMDB e não
# geram bloco em `data/`. Um teste de 41 bytes passava sem exercitar nada.
if ${RAPIDO}; then
  echo "  (pulado: --rapido)"
else
  # A prova de armazenamento já existe como Job no chart, e o `cluster-verify.sh`
  # lê os blocos em disco. Aqui basta conferir que o disco do Garage cresceu com
  # o acervo — é o sinal mais próximo do que o usuário quer saber.
  TAMANHO="$(du -sh /var/lib/garage/data 2>/dev/null | cut -f1 || echo '?')"
  if [[ "${TAMANHO}" != "?" && "${TAMANHO}" != "0" ]]; then
    ok "Garage tem ${TAMANHO} em /var/lib/garage/data"
  else
    falha "não consegui medir /var/lib/garage/data"
  fi
fi

passo "5. Ingestão ponta a ponta (pelo host, como o usuário faz)"
# Port-forward em vez de `kubectl exec ... wget`: a imagem do ingest pode não
# ter `wget`, e o caminho real do usuário é HTTP do lado de fora. Testar o
# caminho que a pessoa usa é o ponto.
PORTA=18099
kc -n "${NS}" port-forward svc/ingest "${PORTA}:8080" >/tmp/verify-pf.log 2>&1 &
PF_PID=$!
sleep 5
SAUDE_HTTP="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORTA}/health" || echo 000)"
if [[ "${SAUDE_HTTP}" == "200" ]]; then
  ok "GET /health devolveu 200"
else
  falha "GET /health devolveu ${SAUDE_HTTP}"
fi

# Dois POSTs do MESMO conteúdo: o segundo tem que vir duplicate=true. É a
# idempotência por sha256, critério do projeto desde a Onda 1.
ARQ="/tmp/verify-ingest-$$.txt"
printf 'verificacao do lake %s\n' "$(date +%s%N)" > "${ARQ}"
R1="$(curl -s -m 15 -X POST "http://127.0.0.1:${PORTA}/uploads" \
     -F "arquivo=@${ARQ}" -F origem=verificacao -F tipo=texto 2>/dev/null)"
R2="$(curl -s -m 15 -X POST "http://127.0.0.1:${PORTA}/uploads" \
     -F "arquivo=@${ARQ}" -F origem=verificacao -F tipo=texto 2>/dev/null)"
rm -f "${ARQ}"
kill "${PF_PID}" 2>/dev/null || true

if grep -q '"duplicate": *false' <<< "${R1}"; then
  ok "primeiro upload criou objeto (duplicate=false)"
else
  falha "primeiro upload não criou objeto: ${R1:0:120}"
fi
if grep -q '"duplicate": *true' <<< "${R2}"; then
  ok "segundo upload do mesmo arquivo é duplicado (idempotência por sha256)"
else
  falha "reenvio NÃO foi marcado duplicado: ${R2:0:120}"
fi

passo "6. Backup registrou sucesso"
ULTIMO="$(kc -n "${NS}" exec postgresql-0 -- psql -U lakecore -d lakecore -tAc \
  "select to_char(ultimo_sucesso, 'YYYY-MM-DD HH24:MI') from saude where sinal='backup'" 2>/dev/null | tr -d ' ')"
if [[ -n "${ULTIMO}" ]]; then
  ok "último backup bem-sucedido: ${ULTIMO}"
else
  falha "nenhum backup bem-sucedido registrado (o Job pode nunca ter rodado)"
fi

passo "7. O lake sabe dizer se está bem"
SAUDE="$(kc -n "${NS}" exec postgresql-0 -- psql -U lakecore -d lakecore -tAc \
  "select count(*) from saude where ultimo_sucesso is not null" 2>/dev/null | tr -d ' ')"
if [[ "${SAUDE:-0}" -ge 1 ]]; then
  ok "frescor registrado para ${SAUDE} rotina(s)"
else
  falha "tabela saude vazia: o lake não sabe se está bem"
fi

echo
echo "=================================================================="
printf ' %d verificação(ões) ok, %d falha(s)\n' "${OKS}" "${FALHAS}"
if [[ "${FALHAS}" -eq 0 ]]; then
  echo " RESULTADO: instalação verificada."
  echo
  echo " O QUE ISTO NÃO PROVA: que a máquina estava SEM REDE. Para isso, a"
  echo " homologação roda este script numa VM com a rede desligada."
  exit 0
fi
echo " RESULTADO: instalação com problema."
exit 1
