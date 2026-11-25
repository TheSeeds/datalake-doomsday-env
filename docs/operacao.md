# Manual de Operação — datalake-doomsday

Como operar o lake no dia a dia: estado, ingestão, consulta, backup, restore,
observabilidade e manutenção.

## Estado e saúde

```bash
# cluster
microk8s status
microk8s kubectl get nodes

# pods do lake
microk8s kubectl -n lake-data get pods

# o lake sabe dizer se está bem? (frescor)
microk8s kubectl -n lake-data exec postgresql-0 -- \
  psql -U lakecore -d lakecore -tAc \
  "select sinal, ultimo_sucesso, detalhe from saude order by sinal"
```

A tabela `saude` guarda o último sucesso de cada rotina (`backup` hoje;
`ingestao`/`export` em versões futuras). `verify.sh` exige essa tabela populada.

## Ingestão

O caminho real do usuário é HTTP:

```bash
# expõe o serviço localmente
microk8s kubectl -n lake-data port-forward svc/ingest 8080:8080 &

# verificação de vida
curl -s http://127.0.0.1:8080/health

# enviar um arquivo (origem e tipo qualificam o layout raw/{origem}/{tipo}/...)
curl -s -X POST http://127.0.0.1:8080/uploads \
  -F arquivo=@/caminho/arquivo.txt -F origem=minha-fonte -F tipo=texto
# resposta: {"sha256": "...", "duplicate": false}

# reenviar o MESMO arquivo ⇒ duplicate=true (idempotência por sha256)
```

### `drop_scan` — ingestão de diretório (a porta que funciona sem o serviço)

```bash
# le cada arquivo de /caminho/drop, ingere, arquiva em /caminho/arquivado
# falha em 1 arquivo não interrompe o lote
PYTHONPATH=src .venv/bin/python -m lakecore.drop_scan /caminho/drop
```

NUNCA apaga o arquivo de origem antes de confirmar a ingestão.

## Consultar o catálogo

```bash
microk8s kubectl -n lake-data exec postgresql-0 -- \
  psql -U lakecore -d lakecore -tAc \
  "select sha256, origem, tamanho, criado_em from objects order by criado_em desc limit 10"
```

### Chat com os dados

```bash
scripts/conectar-chat.sh        # conecta o `lakecore.mcp` (roda no host)
```

O executor de SQL é **read-only por construção**: allowlist por primeiro token
(`select`/`with`), statement único, recusa DML dentro de WITH, e o usuário vê
o SQL executado. Deve-se adicionar a role read-only no PostgreSQL (ver
`criar-role-readonly.sh`).

## Backup

O backup é um CronJob no Postgres (diário), que:
1. roda `pg_dump` do catálogo;
2. envia para o Garage em `backup/` (nunca no mesmo disco do banco — o PVC);
3. registra `ultimo_sucesso` na tabela `saude`.

```bash
# forçar um backup agora
microk8s kubectl -n lake-data create job --from=cronjob/postgresql-backup backup-manual
microk8s kubectl -n lake-data logs job/backup-manual -f

# ver o último backup registrado
microk8s kubectl -n lake-data exec postgresql-0 -- psql -U lakecore -d lakecore -tAc \
  "select ultimo_sucesso from saude where sinal='backup'"
```

Os artefatos ficam no Garage, bucket `backup/` (img do backup: `postgres:16` +
boto3, **não** é a imagem do Garage — que é shell-less e não tem `pg_dump`).

## Restore (drill)

```bash
scripts/restore-drill.sh         # cria namespace temporário, restaura o dump, confere
```

O critério de pronto da Onda 6 é `make restore-drill` verde. Restore
**destrutivo** (apagar o PVC atual e recriar do dump) ainda não é provado em
produção; exige 2º nó. Ver `docs/plano-atividades.md` §6.

## Observabilidade (opcional)

Se instalado com `--with-observability`:

```bash
# Prometheus / Grafana / Loki / Alloy no namespace observability
microk8s kubectl -n observability get pods
microk8s kubectl -n observability port-forward svc/prometheus 9090:9090
```

Limitação conhecida: o PostgreSQL do lake ainda **não tem exporter** — as
métricas de infra aparecem, as do catálogo não (`pg_up=0`). Está no backlog.

## Manutenção

### Atualizar o lake

```bash
# no host COM rede: refazer o bundle, copiar para a máquina
scripts/bundle.sh --apply

# na máquina: re-rodar o install (idempotente) aponta o chart para a nova tag
sudo bash install.sh --engine standard
```

O chart referencia imagem por tag fixa (`newTag`) — nunca `latest`. Se um apply
de overlay trocar o secret/namespace de produção, é armadilha (ver M2.2 no
plano). Aplicar o **base**, nunca o overlay dev em produção.

### Diagnosticar rede

```bash
scripts/diagnostico-rede.sh                  # sem root
sudo scripts/fix-firewalld-calico.sh         # libera FORWARD para cali* (firewalld)
```

### Limitações conhecidas (dividas declaradas)

| Limit | Impacto | Status |
|---|---|---|
| CA do microk8s sem `key usage` | sidecars exigem `skipTlsVerify`; `refresh-certs` não resolve | documentado em `docs/requisitos-sudo.md` |
| `rf=1` no Garage | nada insubstituível em `raw/` antes de 3 nós + `rf=3` | decisão declarada no plano |
| `lake_sql` consulta o OLTP | não lê o Parquet exportado | backlog |
| PostgreSQL sem exporter | métricas do catálogo ausentes do Prometheus | backlog |
| `lakecore.mcp` no host | depende de `scripts/conectar-chat.sh` | backlog (mover p/ cluster) |

## Segurança

- Secrets do lake são criados pelo `scripts/gerar-secrets.sh` **fora do Helm**
  (não vão para o git; o chart falha se o secret não existir).
- Role read-only do chat: `scripts/criar-role-readonly.sh` — nunca credencial
  de escrita num cliente de chat.
- Checar segredos versionados: `sh scripts/checar_segredos.sh` (roda no CI).
