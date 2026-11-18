#!/usr/bin/env bash
# Cria a role READ-ONLY do catálogo, que é a defesa 4 do executor de SQL.
#
# POR QUE ESTE SCRIPT EXISTE (regra 11 do plano):
# as defesas 1-3 do executor (allowlist, statement único, CTE com escrita) são
# análise de texto — dependem de eu estar certo. Esta não: mesmo que todo o
# parsing falhe e um `DELETE` chegue ao banco, o PostgreSQL recusa porque a role
# não tem o privilégio. É a única defesa cuja garantia não passa por mim.
#
# O QUE ESTE SCRIPT NÃO FAZ:
#   - não apaga nem recria a role se ela já existir (isso trocaria a senha e
#     derrubaria o chat no meio de uma consulta)
#   - não dá permissão de escrita em `objects` nem em `uploads`
#   - não roda fora do cluster, e não usa `sudo`
#
# COMO REVERTER:
#   microk8s kubectl -n lake-data exec postgresql-0 -- \
#     psql -U lakecore -d lakecore -c 'DROP OWNED BY lakecore_chat; DROP ROLE lakecore_chat;'
#   microk8s kubectl -n lake-data delete secret lakecore-db-chat
#
# USO:
#   scripts/criar-role-readonly.sh              # dry-run: mostra o que faria
#   scripts/criar-role-readonly.sh --apply      # aplica
#
# A saída é escrita para ser lida por gente: cada ação em português, e o que
# fica sem prova é dito no final.

set -euo pipefail

APLICAR=false
NAMESPACE="lake-data"
ROLE="lakecore_chat"
POD="postgresql-0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APLICAR=true; shift ;;
    --namespace) NAMESPACE="${2:?--namespace exige valor}"; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

kc() { microk8s kubectl "$@"; }

# Executa SQL como superusuário do catálogo e devolve a saída crua.
psql_admin() {
  kc -n "${NAMESPACE}" exec "${POD}" -- psql -U lakecore -d lakecore -tAc "$1"
}

echo "=================================================================="
echo " Role READ-ONLY do chat: ${ROLE}"
echo " Namespace: ${NAMESPACE}   Pod: ${POD}"
echo " Modo: $(${APLICAR} && echo 'APLICAR' || echo 'DRY-RUN (padrão)')"
echo "=================================================================="
echo

echo "[1/4] Verificando que o PostgreSQL responde de verdade"
if ! psql_admin 'select 1' >/dev/null 2>&1; then
  echo "  FALHOU: o catálogo não respondeu. Sem isso não há o que fazer."
  echo "  (lembre: 'pg_isready' devolve 0 mesmo com role inexistente — por isso"
  echo "   o teste aqui é um SELECT real)"
  exit 1
fi
echo "  ok: SELECT 1 respondeu"
echo

echo "[2/4] Conferindo se a role já existe"
if psql_admin "select 1 from pg_roles where rolname = '${ROLE}'" | grep -q 1; then
  echo "  já existe — não vou recriar (isso trocaria a senha e derrubaria o chat)."
  echo
  echo "  Porém: toda tabela NOVA nasce sem SELECT para esta role. Isso já"
  echo "  aconteceu com a tabela 'saude' (migração c4d9e1a7b203), e o sintoma foi"
  echo "  'Saúde das rotinas: (indisponível)' no lake_estado — silencioso."
  echo "  Por isso reaplico APENAS os grants, que são idempotentes."
  if ${APLICAR}; then
    psql_admin "grant select on all tables in schema public to ${ROLE}" >/dev/null
    psql_admin "alter default privileges in schema public grant select on tables to ${ROLE}" >/dev/null
    echo "  grants reaplicados (tabelas atuais + futuras)"
  else
    echo "  [dry-run] aplicaria: GRANT SELECT nas tabelas atuais e nas futuras"
  fi
  exit 0
fi
echo "  não existe; será criada"
echo

echo "[3/4] Ações que SERÃO executadas"
cat <<SQL
  a) criar a role '${ROLE}' com LOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE
  b) dar CONNECT no banco lakecore e USAGE no schema public
  c) dar SELECT em objects e uploads
  d) REVOGAR qualquer escrita (ALL) em vez de só não conceder, para que
     privilégio herdado de PUBLIC/go anônimo não passe por baixo
  e) gerar senha aleatória e gravar no Secret 'lakecore-db-chat'
SQL
echo
echo "  NÃO faz: nenhum INSERT/UPDATE/DELETE; não toca em dados; não muda a role de ingestão."
echo

if ! ${APLICAR}; then
  echo "[4/4] DRY-RUN: nada foi executado."
  echo "      Rode com --apply para criar de fato."
  exit 0
fi

echo "[4/4] Aplicando"

SENHA="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"

psql_admin "create role ${ROLE} with login noinherit nosuperuser nocreatedb nocreaterole password '${SENHA}'" >/dev/null
echo "  a) role criada"

psql_admin "grant connect on database lakecore to ${ROLE}" >/dev/null
psql_admin "grant usage on schema public to ${ROLE}" >/dev/null
echo "  b) conexão e schema liberados"

psql_admin "grant select on objects, uploads to ${ROLE}" >/dev/null
echo "  c) SELECT concedido em objects e uploads"

# Revogar explicitamente é diferente de não conceder: o PostgreSQL não concede
# escrita a PUBLIC por padrão, mas tabelas criadas por ferramentas externas
# podem ter. Revogar torna o estado explícito e auditável.
psql_admin "revoke insert, update, delete, truncate on objects, uploads from ${ROLE}" >/dev/null
psql_admin "revoke create on schema public from ${ROLE}" >/dev/null
echo "  d) escrita revogada explicitamente"

# A senha vai para um Secret, nunca para o values do Helm nem para o log.
if kc -n "${NAMESPACE}" get secret lakecore-db-chat >/dev/null 2>&1; then
  kc -n "${NAMESPACE}" delete secret lakecore-db-chat >/dev/null
fi
kc -n "${NAMESPACE}" create secret generic lakecore-db-chat \
  --from-literal=LAKECORE_DATABASE_URL="postgresql+psycopg://${ROLE}:${SENHA}@postgresql:5432/lakecore" \
  >/dev/null
echo "  e) Secret 'lakecore-db-chat' criado"
echo

echo "=================================================================="
echo " PROVA: a role consegue ler e NÃO consegue escrever"
echo "=================================================================="
# A prova é feita com a própria credencial nova, não com a de admin: testar
# com a role de superusuário provaria nada sobre a role que o chat vai usar.
PROVA_LEITURA="$(kc -n "${NAMESPACE}" exec "${POD}" -- env PGPASSWORD="${SENHA}" \
  psql -h 127.0.0.1 -U "${ROLE}" -d lakecore -tAc 'select count(*) from objects' 2>&1 || true)"
echo "  SELECT em objects  -> ${PROVA_LEITURA}"

PROVA_ESCRITA="$(kc -n "${NAMESPACE}" exec "${POD}" -- env PGPASSWORD="${SENHA}" \
  psql -h 127.0.0.1 -U "${ROLE}" -d lakecore -tAc \
  "delete from objects where 1=0" 2>&1 || true)"
echo "  DELETE em objects  -> ${PROVA_ESCRITA}"

if echo "${PROVA_ESCRITA}" | grep -qi 'permission denied\|negada'; then
  echo
  echo "  ✓ escrita RECUSADA pelo banco — a defesa 4 existe de fato"
else
  echo
  echo "  ✗ ATENÇÃO: a escrita NÃO foi recusada. A defesa 4 não está valendo."
  exit 1
fi

echo
echo " O QUE FICA SEM PROVA:"
echo "   - o chat ainda não está conectado com esta credencial (5.3 em diante)"
echo "   - sobreviver a restart do pod não foi testado (a role vive no PVC)"
