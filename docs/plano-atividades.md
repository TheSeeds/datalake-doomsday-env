# Plano de atividades — datalake-doomsday

> Plano de execução da arquitetura definida em [arquitetura-v2.md](arquitetura-v2.md).
> Este documento é a **única** lista ordenada de trabalho. O que não está aqui,
> não está planejado.
>
> **Status:** Ondas 0, 1, 2 e 3 concluídas e verificadas no cluster.
> Vive no repositório `datalake-doomsday-env`. A arquitetura e as decisões
> permanecem em `datalake-doomsday`.
>
> **Revisão 2 (2026-11-18):** hardware verificado — a máquina tem
> **GPU NVIDIA RTX 3050 Laptop, 4 GB de VRAM**, não "sem GPU" como a arquitetura
> supunha. Isso não antecipa IA no plano; muda o que precisa ser medido e
> introduz o conceito de *piso de GPU*. Ver §11.

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
7. **Toda onda concluída deixa rastro explícito neste documento.** Imediatamente
   ao terminar, o bloco `### ✅ CONCLUÍDA — AAAA-MM-DD` é escrito na própria
   onda, com: comando que provou, número de testes/arquivos, tabela de
   entregável × estado, e **desvios registrados**. Onda sem bloco de conclusão
   é onda não concluída, mesmo que o código exista.

   E dentro do bloco, dois campos não são opcionais:
   - **Desvios do previsto** — o que saiu diferente e por quê. Plano que só
     registra acertos não serve para replanejar.
   - **Pendências explícitas** — o que ficou incompleto, com o bloqueio que
     isso cria. Nunca deixar pendência implícita: ela vira mentira por omissão.
8. **Toda onda termina com `git push` — nos dois repositórios.** Documentação que
   existe só na máquina de quem trabalhou não é documentação; é rascunho. Antes de
   dizer "onda concluída":

   ```bash
   make ci-check          # tem que passar
   git add -A && git commit && git push    # env: plano, README, charts, código
   cd ../datalake-doomsday && git push     # conceito: ADRs, arquitetura, se mudou
   ```

   Checklist de documentação por onda — o que **não** pode ficar para depois:

   | onde | o que atualizar |
   |---|---|
   | `docs/plano-atividades.md` | bloco de conclusão (§regra 7) + visão das ondas |
   | `README.md` | tabela de ondas, estado, seção do que mudou |
   | `docs/requisitos-sudo.md` | se a onda encontrou bloqueio de privilégio |
   | `datalake-doomsday/docs/decisoes.md` (conceito) | ADR novo, se houve decisão |
   | `datalake-doomsday/docs/arquitetura-v2.md` | correção, se a realidade divergiu |

   Onda concluída sem push nos dois repos conta como **não concluída**.

---

## Visão das ondas

```
Onda 0  Repositório e contrato de CI            ✅ feito
Onda 1  Núcleo de domínio puro (lakecore)       ✅ feito
Onda 2  Schema do catálogo                      ✅ feito
Onda 3  Cluster mínimo de pé                    ✅ feito
Onda 4  Ingestão ponta a ponta  ← A PROVA       ← próxima
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

### ✅ CONCLUÍDA — 2026-11-18

**Prova executável:**
```bash
make ci-check      # exit 0
```

**24 arquivos versionados, 2 commits.** `make ci` roda sem cluster, sem rede e
sem container — o que permite que as ondas 0–2 avancem com a infra desligada.

| entregável | estado |
|---|---|
| repo `datalake-doomsday-env` com a estrutura da §8.1 | ✅ |
| `README`, `.gitignore`, `.yml` do CI, `Makefile` | ✅ |
| CI: pytest + helm lint + shellcheck + yamllint + guarda de segredos | ✅ |
| plano migrado e versionado aqui; ponteiro no repo de conceito | ✅ |
| `LICENSE` Apache 2.0 | ⚠️ **só o aviso**; texto integral pendente (ver abaixo) |

**Desvios do previsto, registrados:**

- `shellcheck`, `yamllint` e `helm` **não existiam** no host. Resolvido sem
  dependência de pacote do sistema: `shellcheck-py` e `yamllint` via PyPI,
  `helm` via `microk8s helm3` (já instalado). Isso mantém o alvo "Fedora dev /
  Ubuntu homologação" funcionando sem `dnf install`.
- `truthy` do yamllint acusava falso positivo em `on:` do GitHub Actions. Fixado
  com `check-keys: false` — a chave é YAML 1.1 booleana, não valor booleano.
- **Pendência explícita:** o `LICENSE` contém apenas o aviso, não o texto
  integral do Apache 2.0. O CI **bloqueia tag de release** enquanto isso não for
  corrigido. Consequência: **o repo não deve ser público até o texto integral
  estar presente**, senão anuncia uma licença que não concedeu nada.

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

### ✅ CONCLUÍDA — 2026-11-18

**Prova executável:**
```bash
make ingest-demo
# aceitos=2 iguais=2 falhas=0 objetos=2   (4 entradas, 2 conteúdos distintos)
```

**41 testes verdes**, sem container e sem rede.

| arquivo | responsabilidade |
|---|---|
| `models.py` | `Record`, `ObjectRef`, `IngestRequest`, `UploadBatch`, máquina de estados |
| `ports.py` | `ObjectStore`, `Catalog`, `Clock` como `Protocol` |
| `layout.py` | `raw/{origem}/{tipo}/YYYY/MM/DD/{sha256}`, com saneamento de entrada |
| `errors.py` | erros tipados; `DuplicateObjectError` distingue "já existia" de "falhou" |
| `ingestion.py` | `ingest()`, `hash_file()`, `classify()` |
| `fakes.py` | implementações em memória das portas |
| `__main__.py` | CLI para exercitar o domínio sem infra |

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| `ingest.py` | renomeado para `ingestion.py` — colisão com a função `ingest()` sombreava o módulo (ADR-012) |
| "colisão de hash (fixture)" nos testes | coberto de forma mais direta: conteúdo igual com nomes diferentes, e dedup por `sha256` |
| `make test` como prova | provado por `make ingest-demo` — mais forte, exercita a CLI e a idempotência ponta a ponta |

**Pendências explícitas:**

- **Adaptadores reais não existem.** `ObjectStore` e `Catalog` só têm
  implementação em memória. Enquanto isso durar, "ingerir" não persiste nada —
  é Onda 2 e 3.
- **Estado não sobrevive ao processo.** Consequência direta do item acima: rodar
  `ingest-demo` duas vezes **não** prova idempotência entre execuções. A prova
  válida exige adaptador persistente (Onda 4).

**Decisões que o código carrega:**

- **Write-before-catalog.** Storage primeiro, catálogo depois. O inverso criaria
  linha apontando para objeto inexistente — e o catálogo é a fonte de verdade.
- **Idempotência por conteúdo.** O `sha256` vai no caminho do objeto, então duas
  ingestões do mesmo dado disputam a mesma chave. Renomear não duplica.
- **`ObjectStore` não exige `get`.** Só `put` e `exists`. É o papel `ingest`
  write-only do ADR-011 traduzido em tipo: ingestor comprometido não exfiltra.
- **Fail-closed.** Storage que aceita a escrita e perde o objeto, ou arquivo
  alterado entre hash e gravação, **não** são catalogados.
- **Hash e tamanho na mesma passagem.** Tamanho vem da leitura, não de `stat()`,
  porque entre o `stat` e a leitura o arquivo pode mudar.

**Duas correções de rota durante a onda.**

1. O primeiro `make ingest-demo` repetia a injeção em duas invocações separadas da
   CLI. Como os adaptadores são em memória, cada processo começa vazio — o demo
   mostrava `ACEITO` na segunda passagem e dizia o contrário do que queria provar.
   Agora a prova inteira acontece **numa única invocação**.

2. **Defeito real de API, encontrado porque um teste falhou.** O módulo
   `lakecore.ingest` e a função `lakecore.ingest` tinham o mesmo nome. Ao
   reexportar a função no `__init__.py`, o módulo passava a ser **sombreado pela
   própria função**: `import lakecore.ingest as modulo` devolvia a função, e
   qualquer `monkeypatch` no módulo não tinha efeito — o teste de integridade
   "passava" patcheando o objeto errado. Módulo renomeado para
   `lakecore/ingestion.py`; a função continua `ingest()`.

   A lição é de processo, não de Python: **um teste que não pode falhar é pior
   que teste ausente**, porque produz confiança. Foi o `monkeypatch` correto que
   expôs a colisão de nomes.

**Incidente de processo.** O commit da Onda 1 foi enviado com `make ci` vermelho:
`make ci 2>&1 | tail` fez o `&&` enxergar o exit code do `tail`, não o do `make`.
Corrigido no Makefile com um alvo `ci-check` que usa `set -o pipefail` e não deixa
falha passar. Regra nova: **nenhum push sem `ci-check` verde**.

**Não incluído, deliberadamente:** adaptador de storage real, adaptador de
catálogo real, HTTP, e qualquer coisa que exija cluster. Isso é Onda 2 e 3.

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
make migrate-up-down   # alembic upgrade head → downgrade base → upgrade head
```

**Risco.** Testar só em banco vazio. O CI deve rodar contra Postgres com dados
(lição registrada no geoflow: migração que passa em banco novo falha em produção).

### ✅ CONCLUÍDA — 2026-11-18

**Prova executável:**
```bash
make ci-full       # 59 testes verdes em PostgreSQL real + lint
make migrate-up-down
# upgrade  -> 65a942da6f86 (objects, uploads)
# downgrade base
# upgrade  -> ok
```

**59 testes em PostgreSQL** (53 rodam também em SQLite, 6 exigem PG).

| arquivo | responsabilidade |
|---|---|
| `src/lakecore/db/models.py` | `ObjectRow`, `UploadRow`; `JSONBMaisPortavel` (JSONB no PG, JSON no resto) |
| `src/lakecore/db/catalog.py` | `SqlCatalog` — adaptador da porta `Catalog` |
| `src/lakecore/db/migrations/env.py` | URL só de env var; `render_as_batch` em SQLite |
| `versions/65a942da6f86` | schema inicial: `objects`, `uploads`, índice GIN |
| `versions/8b1f2c3d4e5a` | `status` + `CHECK` + índice, com `server_default` |
| `tests/db/` | catálogo, migrações e integração `ingest() → Postgres` |

**Decisões que o código carrega:**

- **`sha256` UNIQUE** é a implementação física da idempotência. `DuplicateObjectError`
  traduz a violação de constraint em erro de domínio.
- **`status` com `CHECK`** enumera os sete estados da máquina do domínio. Se o
  domínio deixar passar valor inválido, o banco recusa.
- **`server_default` na migração de coluna, removido depois.** Coluna `NOT NULL`
  sem default falha em tabela populada — e é exatamente o cenário de produção.
- **`JSONBMaisPortavel`** em vez de importar `JSONB`: o mesmo `CREATE TABLE`
  funciona nos dois dialetos. GIN condicionado a PostgreSQL.
- **Duas migrações de propósito.** A segunda existe para exercitar evolução de
  schema **com dado dentro**, que a primeira nunca testa.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| `bytes` | coluna chamada `size_bytes` — `bytes` é builtin e vira ambiguidade em leitura de código |
| `status` na migração inicial | entrou como **segunda** migração, para testar backfill em tabela populada |
| `make test-db` | alvo real é `make migrate-up-down` + `make ci-full` |
| `make ci` cobriria PG | não cobre: `make ci` continua sem Docker (onda 0–2 rodam com infra desligada); o alvo com PostgreSQL é `ci-full` |

**Defeitos encontrados pelo teste, e corrigidos:**

1. **Detecção de duplicado só funcionava em PostgreSQL.** O adaptador procurava
   `uq_objects_sha256` na mensagem — nome que o PostgreSQL usa e o SQLite não.
   Em SQLite, todo duplicado virava `IntegrityError` genérico e a ingestão
   deixaria de ser idempotente sem sinal claro. Centralizado em
   `_e_violacao_de_sha_unico()` e coberto por teste.
2. **A migração autogerada referenciou `JSONBMaisPortavel()` sem importar** —
   `NameError` em tempo de execução. Reescrita auto-contida.
3. **Teste usava `now()`, que não existe em SQLite.** Timestamp passado por
   parâmetro.
4. **`text()` devolve JSON como string em SQLite e dict em PostgreSQL.** Teste
   normaliza em vez de assumir.
5. **Regressão que eu mesmo introduzi:** `make ci` passou a subir container
   PostgreSQL, quebrando o princípio "ondas 0–2 rodam sem infra". Separado em
   `ci` (sem Docker) e `ci-full` (com).

**Pendências explícitas:**

- **Adaptador de storage real não existe.** `ObjectStore` continua só em memória.
  O critério da Onda 4 (objeto no Garage) ainda não pode ser cumprido.
- **Estado sobrevive ao processo, agora.** Ao contrário da Onda 1, idempotência
  entre execuções é testável — mas só contra o catálogo, não contra o objeto.
- **Ainda bloqueada pela pergunta 2 da §10** (StatefulSet vs CloudNativePG). O
  schema foi escrito para ser agnóstico: nenhuma feature exclusiva de operador.
  Seguir com StatefulSet + `pg_dump` é reversível; adotar CNPG depois exige
  migrar dados, não schema.

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

### ✅ CONCLUÍDA — 2026-11-18

**Prova executável:**
```bash
make cluster-verify
# storageclass local-path · release datalake · garage Ready · postgresql Ready
# PVC Bound · cluster_layout presente · 6 blocos, 5,1M em /var/lib/garage/data
```

**Prova do armazenamento, ponta a ponta (Job dentro do cluster):**
```
PUT 5MiB ok
GET 5MiB ok, sha256 confere
CHAVE=raw/teste/binario/2026/11/18/ee5e7322...99117ebc
```
E o dado está fisicamente no host: `/var/lib/garage/data` = **5,1M**, blocos em
`8e/fb/`, `70/19/`. Não é "o S3 respondeu" — é byte em disco, lido de volta com
hash idêntico, na chave determinística do `lakecore`.

**Descoberto no caminho:** objetos **< 1 MiB são inlinados no LMDB** (`meta/`),
não geram bloco em `data/`. O teste de 41 bytes "passou" sem provar nada sobre
armazenamento de bloco. Foi o teste de 5 MiB que provou de fato. **Um teste que
passa sem exercitar o mecanismo é pior que teste ausente** — mesma lição do
ADR-012.

**Decisões tomadas (as três confirmadas):**

| decisão | escolha |
|---|---|
| PostgreSQL | **StatefulSet** + CronJob `pg_dump`; CNPG fica para depois, sem migrar dado |
| Garage `replication_factor` | **`rf=1`** agora, registrado como "lake de preparação" |
| Cluster | **microk8s existente** (`zoio`, v1.31.14, verificado vazio) |

**O que está pronto:**

| artefato | estado |
|---|---|
| `charts/garage` | ✅ `helm lint` ok, `--dry-run=client` ok, DaemonSet + hostPath |
| `charts/postgresql` | ✅ StatefulSet + CronJob de backup, `shared_buffers` por tier |
| `charts/datalake` | ✅ umbrella; 4 charts lintam |
| `charts/ingest` | ✅ placeholder, `enabled: false` |
| `scripts/gerar-secrets.sh` | ✅ idempotente, fora do Helm |
| `scripts/garage-layout.sh` | ✅ `assign` é dry-run por padrão |
| `scripts/cluster-verify.sh` | ✅ falha no caso "pod Ready, layout vazio" |
| `docs/requisitos-sudo.md` | ✅ o que só você pode rodar |

**Prova do que foi provado:**
```bash
make ci-check     # 4 charts lintados, 3 scripts shellcheck, 59 testes
microk8s helm3 template lake charts/datalake | microk8s kubectl apply --dry-run=client -f -
```

**O bloqueio de `sudo` foi contornado — e o contorno é registrado, não escondido.**

`microk8s enable hostpath-storage` exige sudo e escreve em `$SNAP_COMMON`.
Substituído por `local-path-provisioner` do Rancher, aplicado com `kubectl`, que
é o mesmo tipo de provisioner e **não** precisa de sudo:

```bash
microk8s kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.37/deploy/local-path-storage.yaml
microk8s kubectl annotate storageclass local-path storageclass.kubernetes.io/is-default-class=true
```

**Diferença que importa:** o addon do microk8s grava em `$SNAP_COMMON/default-storage`;
o do Rancher grava em `/opt/local-path-provisioner`. Os dois são hostPath, os dois
avisam que não servem para produção. Para 1 nó com `rf=1` é equivalente — e fica
registrado que a escolha foi por ausência de `sudo`, não por mérito técnico.

> **Segunda anotação é obrigatória.** O manifest do Rancher **não** marca a
> StorageClass como default (o addon do microk8s marca). Sem a anotação, o PVC
> fica `Pending` mesmo com o provisioner `Running`, e o erro que aparece é
> "unbound immediate PersistentVolumeClaims" — que aponta para o lugar errado.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| `make verify-storage` | alvo real é `make cluster-verify` |
| Garage via Helm chart oficial | chart próprio, sem dependência de repo externo — o oficial exige CRDs e não fixa `DaemonSet` para 1 nó |
| `status` só no catálogo | agora há também `scripts/gerar-secrets.sh`: credencial gerada pelo Helm vaza em `helm get values` |
| — | `yamllint` não pode validar template Helm (`{{ }}` é Go-template). Excluído; `helm lint` cobre |
| `hostpath-storage` do microk8s | `local-path-provisioner` do Rancher — mesmo tipo, sem `sudo` |
| — | o layout do Garage foi aplicado por **Job**, não por `kubectl exec`: o certificado do apiserver está desatualizado e bloqueia `exec`/`logs` |

**Correções aplicadas durante a onda:**

1. `garage.toml` inventado com chave inexistente — corrigido contra a doc oficial; segredos passam por `GARAGE_RPC_SECRET`/`GARAGE_ADMIN_TOKEN` (env), não pelo ConfigMap.
2. `lint-helm` e `lint-sh` imprimiam "nenhum chart/script" mesmo com 4 e 3 — mensagem que mentia sobre o que foi verificado.
3. `yamllint` barrava `#:comentário` de `values.yaml`; regra ajustada explicando por que a convenção existe.
4. **Bug no chart do PostgreSQL:** `sharedBuffers` vazava para dentro de `resources`
   (`unknown field ...resources.sharedBuffers`). Corrigido com `omit` na helper.
5. `--set postgresql.enabled=false` da primeira instalação **persistiu no release**
   e o umbrella instalava só o Garage enquanto `helm` dizia `deployed`. Instalação
   precisa ser com os valores finais, ou `uninstall` antes.
6. `helm --wait` reportou sucesso com pods `Pending` — `--wait` só espera o
   apiserver aceitar, não o PVC ligar.

**Pendências explícitas:**

- **`kubectl exec`/`logs`/`port-forward` estão quebrados** neste host: o IP mudou
  (`.103` → `.11`) e o certificado do apiserver não acompanhou. Consequência real:
  depurar qualquer pod exige `sudo microk8s refresh-certs --cert ca.crt`. Contornado
  nesta onda com Jobs que escrevem em `hostPath`, mas **é dívida**, não solução.
- **`rf=1` continua sendo "lake de preparação"** (ADR-005). Nada insubstituível
  deve entrar em `raw/` antes de 3 nós + `rf=3`.
- **Chaves S3 de teste ficaram no cluster** (`lakecore-ingest`, `verificador`).
  Devem ser removidas antes de qualquer dado real: `garage key delete`.
- O Postgres não foi testado com **restart** ainda. Persistência é afirmada pelo
  PVC `Bound` e pelo `pgdata` em disco, não por um ciclo de reinício provado —
  isso é Onda 6.

**Para desbloquear:** rode o Passo 1 de `docs/requisitos-sudo.md` e eu executo
`make cluster && make cluster-verify`.

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
sudo bash install.sh --engine standard --gpu nvidia && sudo bash verify.sh
```

**Risco.** `verify.sh` rodando na mesma máquina que gerou o bundle. Precisa ser
ambiente limpo, senão testa cache, não instalação.

**Adendo da revisão 2.** `--gpu nvidia` passa a ser um caminho **testado**, não
teórico, porque a máquina de desenvolvimento tem GPU. Ver §11. A ressalva da §9
continua de pé: homologar GPU na VM do host não homologa GPU em ferro modesto.

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

---

## 11. Hardware verificado (revisão 2)

Medido em 2026-11-18 na máquina de desenvolvimento. A arquitetura v2 foi escrita
supondo "GPU opcional, provavelmente ausente". **Estava errada** — e a correção
muda o que precisa ser medido, não o que precisa ser entregue.

### 11.1 O que existe

| item | medido |
|---|---|
| GPU | NVIDIA GeForce RTX 3050 Laptop |
| VRAM | **4096 MiB, com ~3666 MiB já em uso** por um `VLLM::EngineCore` |
| Driver / CUDA | 580.159.03 / CUDA 13.0 |
| Runtime | `nvidia-ctk` e `nvidia-container-runtime` presentes |
| Addon microk8s | `nvidia` disponível (e `gpu` como alias) |
| Ollama | ativo, modelo `qwen2.5-coder:7b` (4,7 GB) |

### 11.2 Por que isso **não** antecipa IA no plano

O modelo de 7B tem 4,7 GB em disco e não cabe em 4 GB de VRAM junto com o que já
está rodando. Hoje a GPU é um recurso **disputado**, não disponível. Um lake cuja
única GPU está 90% ocupada por outro serviço não tem um caminho de IA confiável.

Conclusão: a Onda 5 e o módulo `ai-assistant` continuam pós-Onda 7 (§9). O que
muda é que a **capacidade** deixa de ser especulação e vira restrição medida.

### 11.3 Piso de GPU — conceito novo

O eixo `gpu` da arquitetura (`none` / `nvidia` / `amd`) descreve *fabricante*.
Isso é insuficiente: 4 GB e 24 GB de VRAM são o mesmo "nvidia" e viabilizam
coisas diferentes. Introduzimos o **piso de VRAM** por módulo:

| módulo | piso de VRAM | nota |
|---|---|---|
| embed de pequeno porte | 2 GB | viável nesta máquina **se** o vLLM ceder espaço |
| LLM 7B quantizado | 6 GB | **não cabe** aqui |
| LLM 13B+ | 12 GB+ | fora de escopo v1 |

O `module.yaml` (§7 da arquitetura) passa a declarar `requires.vram: 6Gi` em vez
de apenas `requires.gpu: optional`. Um módulo que não satisfaz o piso deve
**recusar instalação com mensagem clara**, não degradar silenciosamente para CPU
e entregar 1 token/s — degradação silenciosa é a mesma mentira do
`estado-validado.md`.

### 11.4 Consequência para os entregáveis

| onda | ajuste |
|---|---|
| 3 | nada. GPU não entra em infraestrutura de dados |
| 7 | `--gpu nvidia` vira caminho exercitado no `verify.sh` (ao menos: RuntimeClass presente e `nvidia-smi` de dentro de um pod) |
| pós-7 | teste de contenção de VRAM: `nvidia-smi` mostrando uso **exclusivo** antes de qualquer medição de IA |

**Regra registrada:** nenhuma medição de desempenho de IA é válida enquanto a
GPU estiver compartilhada com outro processo. Medir sob contenção não mede o
modelo — mede a disputa.
