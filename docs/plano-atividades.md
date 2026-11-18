# Plano de atividades — datalake-doomsday

> Plano de execução da arquitetura definida em [arquitetura-v2.md](arquitetura-v2.md).
> Este documento é a **única** lista ordenada de trabalho. O que não está aqui,
> não está planejado.
>
> **Status:** aprovado como plano. Nenhuma onda iniciada.
> Migra para o repositório `datalake-doomsday-env` na Onda 0, onde passa a viver.

---

## Regras de condução

1. **Uma onda por vez.** Nenhuma onda começa com a anterior vermelha.
2. **"Pronto" é verificável por comando**, não por opinião. Cada onda declara o
   comando que prova a conclusão.
3. **Nada entra sem teste.** A guardrail do projeto vale: sem teste automatizado,
   a mudança não está concluída.
4. **Operação destrutiva nunca é default.** `--dry-run` é padrão; `--apply` é explícito.
5. **O dado bruto é irreversível.** Enquanto o `replication_factor` não estiver
   decidido e o número de nós não justificar, `raw/` só recebe dado de teste.
6. **Escopo travado.** Ideia nova vira linha na §9 ("Não fazer ainda"), não
   vira trabalho.

---

## Visão das ondas

```
Onda 0  Repositório e contrato de CI            ~1 sessão
Onda 1  Núcleo de domínio puro (lakecore)       ~1-2 sessões
Onda 2  Schema do catálogo                      ~1 sessão
Onda 3  Cluster mínimo de pé                    ~1 sessão
Onda 4  Ingestão ponta a ponta  ← A PROVA       ~1-2 sessões
Onda 5  Consulta e dashboard                    ~2 sessões
Onda 6  Backup e restore provado                ~1 sessão
Onda 7  Bundle offline                          ~1-2 sessões
────────────────────────────────────────────────────────────
Total                              ~9-11 sessões de trabalho
```

Ondas 0–2 não dependem de infraestrutura nenhuma. Rodam mesmo com o cluster
parado. Isso é deliberado: o valor do projeto está no catálogo, não no Kubernetes.

---

## Onda 0 — Repositório e contrato de CI

**Objetivo.** Existir um lugar onde o ambiente instalável mora, com CI verde
antes de existir código.

**Por quê primeiro.** Sem CI verde, todo commit posterior é ambíguo: não se sabe
se quebrou agora ou já estava quebrado. O CI atual do `datalake-doomsday` está
vermelho (passo sem `run:` e script inexistente) — não repetir.

**Entregáveis**
- Repositório `datalake-doomsday-env` com estrutura da §8.1 da arquitetura
- `LICENSE` (Apache 2.0), `README.md`, `.gitignore`, `Makefile`
- Workflow de CI: lint + shellcheck + `helm lint` + testes Python
- Este documento migrado e versionado lá; no repo antigo fica só o link

**Pronto quando**
```bash
git clone <repo> && cd datalake-doomsday-env && make ci   # exit 0, sem infra
```

**Risco.** Nenhum. É a onda mais barata e a que mais paga.

---

## Onda 1 — Núcleo de domínio puro (`lakecore`)

**Objetivo.** `ingest(path) -> Record`, idempotente por `sha256`, sem HTTP, sem
k8s, sem rede.

**Por quê.** É o coração do produto e a única parte que precisa estar certa.
Testável em milissegundos, sem container. Todo o resto (API, Job, chart) é
encanamento em volta disto.

**Entregáveis**
- `src/lakecore/`: `ingest()`, `hash()`, `classify()`, máquina de estados
- Interfaces (Protocols) para `ObjectStore` e `Catalog`, com fakes em memória
- Layout determinístico do `raw/`: `{origem}/{tipo}/{YYYY}/{MM}/{DD}/{sha256}`
- Testes unitários cobrindo: deduplicação, arquivo vazio, arquivo grande,
  nome sem extensão, colisão de hash (fixture), falha de storage

**Pronto quando**
```bash
make test        # ingere o mesmo arquivo 2x → 1 Record; 100% verde
```

**Risco.** Escopo inflado. Regra: `lakecore` **não** sabe o que é HTTP, S3,
PostgreSQL ou Kubernetes. Só `path` → `Record`.

---

## Onda 2 — Schema do catálogo

**Objetivo.** Migração Alembic com as tabelas do catálogo, exercitada contra
PostgreSQL real.

**Por quê.** O schema é o contrato entre ingestão e consulta. Errar aqui custa
migração de dado irreversível depois.

**Entregáveis**
- `objects`: `id`, `bucket`, `key`, `sha256` (**UNIQUE**), `bytes`,
  `content_type`, `origem`, `tipo`, `coletado_em`, `metadados JSONB`, `status`
- `uploads`: lote, origem, quantidade, estado agregado
- Migração `upgrade` **e** `downgrade` funcionais
- Teste de idempotência no banco: mesmo `sha256` duas vezes → 1 linha

**Pronto quando**
```bash
make test-db     # alembic upgrade head → downgrade base → upgrade head
```

**Risco.** Testar só em banco vazio. O CI deve rodar contra Postgres com dados
(lição registrada no geoflow: migração que passa em banco novo falha em produção).

---

## Onda 3 — Cluster mínimo de pé

**Objetivo.** microk8s com addons, Garage com layout aplicado, PostgreSQL
persistindo.

**Por quê.** Agora sim o primeiro contato com infra — e depois do núcleo já
existir, o cluster serve a um propósito, não é exercício.

**Entregáveis**
- Script de addons idempotente (`dns`, `hostpath-storage`, `helm`, `rbac`,
  `ingress`, `cert-manager`)
- Chart do Garage; `layout.sh` com `assign` + `apply`
- Chart do PostgreSQL com PVC e `shared_buffers` por tier
- Policies mínimas: NetworkPolicy default-deny em `lake-data`
- **`replication_factor` decidido e registrado** (ver risco)

**Pronto quando**
```bash
make cluster && make verify-storage
# bucket de teste criado, objeto escrito e lido de volta
```

**Risco crítico.** O Garage sobe "verde" sem `layout apply` e **não armazena
nada**. Falha silenciosa. Por isso `verify-storage` falha se o layout estiver
vazio, e existe um teste que simula o layout ausente.

**Decisão obrigatória antes da Onda 4:** `rf=1` (single-node, sem redundância)
ou aguardar 3 nós. Ver §4.1 da arquitetura.

---

## Onda 4 — Ingestão ponta a ponta ← **a prova**

**Objetivo.** Um arquivo em `drop/` termina como objeto no Garage **e** linha no
catálogo, e reprocessar não duplica.

**Por quê.** É a única coisa que o projeto nunca entregou. Tudo antes é preparação;
tudo depois é consequência.

**Entregáveis**
- `ingest-api` (porta HTTP) **e** `Job` de varredura do `drop/`
- Ambas as portas usam `lakecore` — uma implementação, dois gatilhos
- Papel `ingest` com chave S3 **write-only** no prefixo `raw/`
- Job idempotente: 2 execuções → 1 objeto, 1 linha
- Teste de integração com Garage + Postgres reais

**Pronto quando**
```bash
make ingest-demo
# 1 arquivo → 1 objeto em raw/ + 1 linha em objects; rodar 2x → ainda 1
```

**Risco.** Acoplar regra de negócio ao Job. Se a lógica não estiver em `lakecore`,
da Onda 1, a Onda 4 está errada — voltar, não contornar.

---

## Onda 5 — Consulta e dashboard

**Objetivo.** Perguntar "o que tem no lake?" e receber resposta.

**Entregáveis**
- CronJob que exporta catálogo → Parquet em `derived/`
- `query-api` com DuckDB sobre Parquet + agregações por origem/tipo/mês
- Página com volume, últimas entradas, saúde da ingestão
- **Playwright** cobrindo o fluxo (fecha a guardrail hoje inexequível)

**Pronto quando**
```bash
make demo && make e2e     # Playwright verde no fluxo de consulta
```

**Risco.** Métrica bonita sem pergunta. Ver §9 — o `seed` depende da pergunta
de produto, que ainda não foi respondida.

---

## Onda 6 — Backup e restore provado

**Objetivo.** Perder o cluster e recuperar — demonstrado, não prometido.

**Entregáveis**
- CronJob `pg_dump` → `backup/`; snapshot do layout Garage
- `restore` com máquina de decisão (`--dry-run` default, `--apply` explícito)
- Drill: destruir PVC, restaurar, comparar contagem de objetos e linhas

**Pronto quando**
```bash
make restore-drill      # cluster limpo → 100% dos objetos e linhas de volta
```

**Risco.** Chamar `pg_dump` de "backup" sem nunca ter restaurado. Restore não
testado é esperança, não backup.

---

## Onda 7 — Bundle offline

**Objetivo.** Instalar o lake em máquina sem internet, em dois comandos.

**Entregáveis**
- `bundle.sh`: snaps + `images export-local` + distro + seed + `SHA256SUMS`
- `install.sh` idempotente, com `--engine` e `--gpu`
- `verify.sh` verde em máquina limpa **sem rede**
- Homologação: VM Ubuntu 24.04 (Tier 1 da §8.4)

**Pronto quando**
```bash
# máquina limpa, sem rede
sudo bash install.sh --engine standard --gpu none && sudo bash verify.sh
```

**Risco.** `verify.sh` rodando na mesma máquina que gerou o bundle. Precisa ser
ambiente limpo, senão testa cache, não instalação.

---

## 8. Sequenciamento e dependências

| Onda | Depende de | Bloqueia |
|---|---|---|
| 0 | — | 1–7 |
| 1 | 0 | 4 |
| 2 | 0, 1 (tipos) | 4 |
| 3 | 0 | 4, 5 |
| 4 | 1, 2, 3 + **decisão de rf** | 5, 6 |
| 5 | 4 | 7 (seed) |
| 6 | 4 | — |
| 7 | 5, 6 | release |

Ondas 1 e 2 são paralelizáveis com 3 (não dependem de infra).

---

## 9. Não fazer ainda

Registrado para não contaminar o escopo. Nenhum destes entra antes da Onda 7:

- **IA / busca semântica** — precisa de catálogo populado para ter o que buscar
- **Multi-nó / HA** — exige 3 máquinas; hoje há uma
- **Módulos instaláveis (Supply Depot)** — só depois de haver 1 módulo real
- **Mapas, cursos, acervo curado** — o NOMAD já faz isso; não é nosso diferencial
- **Multi-tenant** — sem segundo usuário, é abstração sem demanda
- **TLS público com domínio** — v1 é LAN
- **Replicação entre clusters** — geodistribuição sem segundo cluster é teoria
- **Interface de escrita para usuário final** — o público da v1 opera por `drop/` e API

---

## 10. Perguntas em aberto que bloqueiam trabalho

| # | Pergunta | Bloqueia | Prazo |
|---|---|---|---|
| 1 | `replication_factor`: `1` agora ou aguardar 3 nós? | Onda 4 | antes da Onda 4 |
| 2 | PostgreSQL: StatefulSet + CronJob ou CloudNativePG? | Onda 3 | antes da Onda 3 |
| 3 | `drop/`: PVC `ReadWriteMany` ou `hostPath`? | Onda 4 | antes da Onda 4 |
| 4 | **Quem instala isto e qual pergunta quer responder?** | Onda 5 (`seed`) | antes da Onda 5 |

As três primeiras são técnicas e têm recomendação registrada na §13 da
arquitetura. A quarta é de produto e **não tem recomendação** — sem ela, o
dashboard mostra métrica que ninguém pediu.
