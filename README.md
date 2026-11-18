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

**Ondas 0, 1 e 2 concluídas.** O núcleo de domínio e o catálogo persistente
funcionam; infraestrutura e cluster ainda **não existem**.

| onda | estado |
|---|---|
| 0 — estrutura e CI | ✅ `make ci` verde sem cluster |
| 1 — `lakecore` puro | ✅ `make ingest-demo`: 4 entradas → 2 objetos |
| 2 — schema do catálogo | ✅ 59 testes em PostgreSQL real; migração reversível |
| 3 — cluster mínimo | ⬜ próxima |
| 4–7 | ⬜ |

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
```

Nenhum arquivo de configuração tem credencial: a URL do banco vem sempre de
`LAKECORE_DATABASE_URL`.

`make ci` roda sem Kubernetes, sem Garage e sem PostgreSQL. Isso é intencional:
as ondas 0–2 rodam com o cluster desligado, porque o valor do projeto está no
catálogo, não no orquestrador.

Requisitos de desenvolvimento: Python 3.11+, e `microk8s` (o `helm` vem de
`microk8s helm3`). `shellcheck` e `yamllint` são instalados pelo `make setup`.

## Licença

Apache 2.0. Ver [`LICENSE`](LICENSE).
