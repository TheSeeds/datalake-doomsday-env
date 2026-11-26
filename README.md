# datalake-doomsday-env

**O ambiente instalável do [datalake-doomsday](https://github.com/TheSeeds/datalake-doomsday)**.

O **lake** é um armazém de dados de preservação: ingere arquivos, guarda-os com
proveniência obrigatória, cataloga-os de forma idempotente por `sha256` e expõe
consultas e exportação. Instala-se num nó **sem internet** (a partir de um bundle
offline) **ou numa máquina viva com internet** — o mesmo `install.sh` cobre os
dois caminhos.

Este repositório é o artefato: charts, distro, scripts de instalação, bundle
offline, e o núcleo de domínio (`lakecore`). O *modelo conceitual* — visão,
arquitetura, decisões e plano de atividades — vive no repositório de conceito.

> **Separação deliberada:** conceito muda quando o pensamento muda; ambiente muda
> quando o código muda e precisa de tag, digest e release. Misturar os dois faz
> toda edição de texto aparecer como diff ao lado de mudança de chart, e o bundle
> precisa fixar um commit de si mesmo.

| repositório | contém | ciclo |
|---|---|---|
| `datalake-doomsday` | visão, arquitetura, decisões, plano | quando o desenho muda |
| **`datalake-doomsday-env`** (este) | charts, distro, scripts, `lakecore`, bundle | quando o código muda |

## Versão

**v1.0.0** — fim da fase 1 (v0.1-beta). A partir daqui o projeto adota
**Semantic Versioning**: `MAJOR.MINOR.PATCH`, com tag git por release e changelog
em `docs/CHANGELOG.md`. O processo de release (bump, build do bundle, publicação
das imagens próprias no GHCR) está em [`docs/release.md`](docs/release.md).

## Estado

**Ondas 0 a 7 concluídas.** O lake **ingere** dado de verdade: o arquivo entra,
o objeto vai para o Garage e a linha aparece no catálogo, idempotente por
`sha256` — em instalação **offline homologada** (VM sem rede) e disponível
**online**.

| onda | estado | prova |
|---|---|---|
| 0 — estrutura e CI | ✅ | `make ci` verde sem cluster |
| 1 — `lakecore` puro | ✅ | `make ingest-demo`: 4 entradas → 2 objetos |
| 2 — schema do catálogo | ✅ | 59 testes em PostgreSQL real; migração reversível |
| 3 — cluster mínimo | ✅ | PUT/GET de 5 MiB com `sha256` conferindo; blocos em disco |
| 4 — ingestão ponta a ponta | ✅ | `POST /uploads` → 201; 2ª vez → `duplicate:true`; 1 linha |
| 5 — conversar com os dados | 🟢 5.1/5.2/5.3/5.6 | executor read-only, export Parquet, chat via MCP, frescor |
| 6 — backup e restore | ✅ | `make restore-drill`: dump do Garage → catálogo idêntico |
| 7 — bundle offline | ✅ | `install.sh && verify.sh` (12/12) numa VM Ubuntu 24.04 SEM rede (2026-11-25) |

O plano completo, com o bloco de conclusão de cada onda, está em
[`docs/plano-atividades.md`](docs/plano-atividades.md).

## Instalação (offline e online)

O mesmo `install.sh` instala pelos dois caminhos. O que muda é só de onde vêm
snaps, imagens e o chart; a verificação final (`verify.sh`) é a mesma.

| caminho | quem usa | fonte |
|---|---|---|
| `--fonte online` (padrão) | máquina **com** internet | microk8s do store; imagens do GHCR (`ghcr.io/theseeds/lakecore-*`) + registries públicos; charts do repo |
| `--fonte offline` | máquina **sem** internet | bundle de `make bundle` (snaps + imagens + charts, verificados por checksum) |

```bash
# 1) online — máquina viva com rede
sudo bash install.sh                 # padrão: fonte online (usa microk8s + GHCR)

# 2) offline — monte o bundle primeiro, numa máquina com rede
make bundle                          # dist/datalake-bundle-<versão>/
# ... copie a pasta para a máquina de destino ...
sudo bash install.sh --fonte offline

# em qualquer um dos dois:
sudo bash verify.sh                  # 12 verificações que exercitam o caminho real
```

> **Homologado (offline):** `install.sh && verify.sh` verdes (12/12) numa VM
> Ubuntu 24.04 **sem internet** em 2026-11-25. O caminho **online** ainda não foi
> homologado numa máquina limpa com rede — é o primeiro item do release v1.0.0
> (ver `docs/release.md`).

O `install.sh` agora **roda a migração do catálogo** (`scripts/migrar-catalogo.sh`)
como passo próprio — corrige o P1 da Onda 7, em que em instalação limpa as
tabelas `objects`/`uploads`/`saude` não eram criadas.

Manuais: [`docs/instalacao.md`](docs/instalacao.md) (instalar),
[`docs/operacao.md`](docs/operacao.md) (operar),
[`docs/release.md`](docs/release.md) (build bundle, GHCR, versionamento).

## Backup provado, não prometido

`pg_dump` diário rodando não é backup — é esperança. Em 2026-11-18 descobrimos
que o Job falhava em **100% das execuções** e ninguém sabia, porque ninguém
restaurava. O drill agora é código:

```bash
make restore-drill        # --apply explícito; sem ele mostra o que faria
```

Restaura o dump mais recente num banco **novo**, sem tocar no original, e
compara os dois por **contagem e md5 das chaves**. Se divergir, o banco de
rascunho é **mantido** para inspeção.

## `lakecore` — o coração

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

**Garantias cobertas por teste:**

- **idempotência por conteúdo**, não por nome — renomear não duplica;
- **write-before-catalog**: o objeto entra no storage antes da linha no catálogo;
- **fail-closed** na integridade: storage que não confirma a escrita ou arquivo
  alterado entre hash e gravação **não** são catalogados;
- proveniência obrigatória: sem `origem`, a ingestão é recusada.

## Catálogo

Duas tabelas: `objects` e `uploads`. O schema sustenta os invariantes:

- `sha256` **UNIQUE** — idempotência garantida pelo banco;
- `origem` `NOT NULL` — dado sem procedência não entra;
- `metadados` JSONB (PostgreSQL) / JSON (SQLite);
- `status` com `CHECK` nos sete estados da máquina.

## Validação

```bash
make ci                     # SQLite + lint — sem cluster, Docker ou rede
make ci-full                # + PostgreSQL real (requer Docker)
make ingest-demo            # critério da Onda 1
make migrate-up-down        # upgrade → downgrade → upgrade
make cluster-verify         # critério da Onda 3
make verify                 # verificação de uma instalação real
```

Nenhum arquivo de configuração tem credencial: a URL do banco vem sempre de
`LAKECORE_DATABASE_URL`.

## Cluster

Instalado no microk8s existente, namespace `lake-data`:

| componente | forma | persistência |
|---|---|---|
| Garage | DaemonSet + `hostPath` | `/var/lib/garage/{meta,data}` no nó |
| PostgreSQL | StatefulSet + PVC | `local-path`, 10 GiB |
| backup | CronJob `pg_dump` | diário, bucket `backup/` |

**O Garage não armazena até o layout ser aplicado** — passo explícito no
`install.sh` e em `scripts/garage-layout.sh`.

Dívida declarada: o CA do microk8s não inclui `key usage`, e o módulo
`observability` usa `sidecar.skipTlsVerify: true` (ver
`modules/observability/values.yaml`).

## Conversar com os dados

A tela é o **Hermes Agent** via **MCP** — *cliente*, não dono do host. As
ferramentas de `terminal`, `file`, `browser`, `code_execution` e `web` estão
desabilitadas. Ferramentas: `lake_esquema`, `lake_buscar`, `lake_sql` (allowlist
`SELECT`/`WITH` read-only) e `lake_estado`.

**Quatro camadas de defesa contra escrita**, sendo a última no PostgreSQL — mesmo
contornando o executor, a credencial do chat recebe `permission denied`.

## Versionamento

- **Semantic Versioning** a partir da v1.0.0.
- Tag git por release (`v1.0.0`, ...), imagem GHCR e charts todos alinhados à
  mesma versão (é o que `docs/release.md` centraliza).
- Changelog em [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## Licença

Apache 2.0. Ver [`LICENSE`](LICENSE).