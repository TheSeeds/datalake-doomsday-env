# datalake-doomsday-env

O **ambiente instalável** do [datalake-doomsday](https://github.com/TheSeeds/datalake-doomsday).

Este repositório é o artefato: charts, distro, scripts de instalação, bundle offline
e o núcleo de domínio (`lakecore`). O *modelo conceitual* — visão, arquitetura,
decisões e plano de atividades — vive no repositório de conceito.

> **Separação deliberada:** conceito muda quando o pensamento muda; ambiente muda
> quando o código muda e precisa de tag, digest e release. Misturar os dois faz
> toda edição de texto aparecer como diff ao lado de mudança de chart, e o bundle
> precisa fixar um commit de si mesmo.

| repositório | contém | ciclo |
|---|---|---|
| `datalake-doomsday` | visão, arquitetura, decisões, plano | quando o desenho muda |
| **`datalake-doomsday-env`** (este) | charts, distro, scripts, `lakecore`, bundle | quando o código muda |

## Estado

**Ondas 0 a 4 concluídas.** O lake **ingere** dado de verdade: arquivo entra,
objeto vai para o Garage e a linha aparece no catálogo, idempotente por `sha256`.

| onda | estado | prova |
|---|---|---|
| 0 — estrutura e CI | ✅ | `make ci` verde sem cluster |
| 1 — `lakecore` puro | ✅ | `make ingest-demo`: 4 entradas → 2 objetos |
| 2 — schema do catálogo | ✅ | 59 testes em PostgreSQL real; migração reversível |
| 3 — cluster mínimo | ✅ | PUT/GET de 5 MiB com `sha256` conferindo; blocos em disco |
| 4 — ingestão ponta a ponta | ✅ | `POST /uploads` → 201; 2ª vez → `duplicate:true`; 1 linha |
| 5 — conversar com os dados | 🟢 5.1 e 5.3 feitas | executor read-only + tela de chat via MCP, provada contra o catálogo |
| 6 — backup e restore | ✅ | `make restore-drill`: dump do Garage → catálogo idêntico (contagem + md5) |
| 7 — bundle offline | ⬜ | |

O plano completo, com o bloco de conclusão de cada onda, está em
[`docs/plano-atividades.md`](docs/plano-atividades.md).

### Backup provado, não prometido

`pg_dump` diário rodando não é backup — é esperança. Em 2026-11-18 descobrimos
que o Job falhava em **100% das execuções** e ninguém sabia, porque ninguém
restaurava. O drill agora é código:

```bash
make restore-drill        # --apply explícito; sem ele mostra o que faria
```

Restaura o dump mais recente num banco **novo**, sem tocar no original, e
compara os dois por **contagem e md5 das chaves** — contagem sozinha aprova
"restaurei 11 linhas, só que as erradas". Se divergir, o banco de rascunho é
**mantido** para inspeção; apagá-lo tornaria o incidente irreproduzível.

### `lakecore` — o coração

Recebe um caminho, devolve um `Record`. **Não conhece** HTTP, S3, PostgreSQL ou
Kubernetes — só stdlib. Isso mantém `make test` em milissegundos e permite que
as ondas 0–2 rodem com o cluster desligado.

```python
from lakecore import IngestRequest, ingest

resultado = ingest(
    IngestRequest(path="foto.jpg", origem="pendrive"),
    store=..., catalog=..., clock=...,
)
resultado.duplicate   # True se o sha256 já estava catalogado
resultado.record.key  # raw/pendrive/imagem/2026/11/18/<sha256>
```

Garantias cobertas por teste:

- **idempotência por conteúdo**, não por nome — renomear não duplica
- **write-before-catalog**: o objeto entra no storage antes da linha no catálogo,
  então o catálogo nunca aponta para objeto inexistente
- **fail-closed** na integridade: storage que não confirma a escrita ou arquivo
  alterado entre hash e gravação **não** são catalogados
- proveniência obrigatória: sem `origem`, a ingestão é recusada

Adaptadores reais (Garage, PostgreSQL) entram nas ondas 2 e 3. Até lá os testes
usam implementações em memória das mesmas portas.

O plano completo, com as ondas 0–7 e o critério de pronto de cada uma, está em
[`docs/plano-atividades.md`](docs/plano-atividades.md).

### Catálogo

Duas tabelas: `objects` (o acervo catalogado) e `uploads` (lotes de ingestão).
O schema sustenta os invariantes que o domínio assume:

- `sha256` **UNIQUE** — idempotência é garantida pelo banco, não só pelo código
- `origem` `NOT NULL` — dado sem procedência não entra
- `metadados` JSONB (PostgreSQL) / JSON (SQLite) — dado heterogêneo não exige schema rígido
- `status` com `CHECK` nos sete estados da máquina de estados

## Validação

```bash
make ci         # SQLite + lint — não requer cluster, Docker nem rede
make ci-full    # + PostgreSQL real (requer Docker)
make ingest-demo      # prova o critério da Onda 1
make migrate-up-down  # upgrade → downgrade → upgrade em PostgreSQL
make cluster-verify   # critério da Onda 3: cluster com layout aplicado
```

Nenhum arquivo de configuração tem credencial: a URL do banco vem sempre de
`LAKECORE_DATABASE_URL`.

## Cluster

Instalado no microk8s existente (`zoio`), namespace `lake-data`:

| componente | forma | persistência |
|---|---|---|
| Garage | DaemonSet + `hostPath` | `/var/lib/garage/{meta,data}` no nó |
| PostgreSQL | StatefulSet + PVC | `local-path`, 10 GiB |
| backup | CronJob `pg_dump` | diário, para o bucket `backup/` |

```bash
make secrets    # gera os Secrets fora do Helm (nunca em values.yaml)
make cluster    # helm upgrade --install
make cluster-verify
```

**O Garage não armazena até o layout ser aplicado.** O Helm instala, mas não
configura layout; sem ele os pods ficam `Ready` e a escrita falha. O passo é
`scripts/garage-layout.sh assign --apply` e depois `apply`.

> **Resolvido em 2026-11-18:** `kubectl exec`, `logs` e `port-forward` falhavam
> com `x509` porque o IP da máquina mudou e o certificado do apiserver não
> acompanhou. `sudo microk8s refresh-certs --cert ca.crt` corrigiu, e
> `scripts/cluster-verify.sh` agora reporta `kubectl exec funcional`.
>
> **O que o `refresh-certs` NÃO resolveu:** o CA do microk8s não inclui a
> extensão `key usage`, nem antes nem depois de regenerar. Clientes TLS modernos
> (Python 3.14, usado pelos sidecars) recusam esse CA. Por isso o módulo
> `observability` usa `sidecar.skipTlsVerify: true` — dívida de segurança
> declarada no `modules/observability/values.yaml`, com o motivo e o risco.

`make ci` roda sem Kubernetes, sem Garage e sem PostgreSQL. Isso é intencional:
as ondas 0–2 rodam com o cluster desligado, porque o valor do projeto está no
catálogo, não no orquestrador.

## Conversar com os dados

A tela é o **Hermes Agent**, conectado por **MCP**. Ele é *cliente*, não dono do
host: as ferramentas de `terminal`, `file`, `browser`, `code_execution` e `web`
estão desabilitadas de propósito. Derrubar a tela não derruba a ingestão, o
backup nem o catálogo.

```
Hermes (tela)  →  MCP  →  lakecore.mcp  →  credencial read-only  →  PostgreSQL
```

| ferramenta | o que faz |
|---|---|
| `lake_esquema` | o schema real, para o modelo não inventar coluna |
| `lake_buscar` | filtro por origem/tipo/status/data — **funciona sem LLM** |
| `lake_sql` | `SELECT` com allowlist, `LIMIT` e `timeout`; devolve o SQL junto |
| `lake_estado` | volume, origens, últimos lotes e o que falhou |

```bash
scripts/criar-role-readonly.sh --apply   # cria a role sem permissão de escrita
scripts/conectar-chat.sh                 # ponte host→cluster e URL local
hermes webapp --status                   # tela em http://127.0.0.1:9120
```

**Quatro camadas de defesa contra escrita**, e a quarta não depende do meu código:
mesmo contornando o executor e chamando o banco direto, a credencial do chat
recebe `permission denied for table objects`. O SQL executado é sempre mostrado:
é o que separa "conversar com os dados" de "confiar no chatbot".

Requisitos de desenvolvimento: Python 3.11+, e `microk8s` (o `helm` vem de
`microk8s helm3`). `shellcheck` e `yamllint` são instalados pelo `make setup`.

## Licença

Apache 2.0. Ver [`LICENSE`](LICENSE).
