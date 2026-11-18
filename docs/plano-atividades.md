# Plano de atividades — datalake-doomsday

> Plano de execução da arquitetura definida em [arquitetura-v2.md](arquitetura-v2.md).
> Este documento é a **única** lista ordenada de trabalho. O que não está aqui,
> não está planejado.
>
> **Status:** Ondas 0 a 4 e 6 concluídas. Onda 5 em andamento (5.1 e 5.3
> prontas; 5.2/5.4/5.5 abertas). Onda 7 não começou.
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
9. **Precisando de superusuário: informar e pedir. Nunca assumir, nunca pedir senha.**
   O agente não executa `sudo`, não digita senha e não contorna privilégio por
   caminho lateral sem declarar. Ao encontrar bloqueio de root:

   1. **parar** e dizer qual comando exato é necessário;
   2. explicar **o que ele muda** no sistema;
   3. registrar em `docs/requisitos-sudo.md` — o arquivo é a fila de pendências
      de privilégio, não um apêndice;
   4. seguir com o que é possível sem root, **declarando o que ficou sem prova**.

   Contorno sem root é permitido (foi o caso do `local-path-provisioner` em vez do
   addon do microk8s), mas **só com registro explícito** do que mudou e por quê.
   Contorno silencioso é o mesmo pecado de pendência implícita.
11. **Toda necessidade de root vira script + auditoria legível.** Nunca um bloco
    de comandos para copiar.

    O script é a **única** forma de o usuário executar algo com privilégio. E ele
    precisa poder revisar antes de rodar, sem ler shell:

    | o que o script tem que declarar | por quê |
    |---|---|
    | **o que muda** no sistema, em uma frase | decidir se quer |
    | **lista de ações**, uma linha cada, em português | auditar sem ler bash |
    | **o que NÃO faz** (não apaga, não remove, não expõe) | o medo real |
    | **como reverter** | saída de emergência |
    | `--dry-run` quando houver mudança permanente | ver antes de aplicar |
    | validação de `EUID` com recusa explícita | falhar cedo e claro |

    Nenhum script de root sem `--reverter` ou `--help` que explique a reversão.
    Script de root sem caminho de volta não é ferramenta, é armadilha.
10. **Toda parada gera checkpoint de memória — qualquer que seja o motivo.**
    Fim de onda, bloqueio, troca de assunto, fim de sessão. Não é só "quando
    termina bem": parada por bloqueio é justamente quando o contexto mais se perde.

    ```bash
    python3 ~/.ori/global/features/memoria-sessao/memoria_sessao.py usar datalake-doomsday-env
    ```

    O checkpoint precisa conter, no mínimo:

    | campo | por quê |
    |---|---|
    | `oQueFoiFeito` | decisões e o **porquê**, não a lista de arquivos |
    | `ondeParou` | estado exato + HEAD dos dois repos |
    | `proximosPassos` | ordenados, incluindo o que **não** fazer ainda |
    | `bloqueios` | com o comando que desbloqueia, quando existe |
    | `comandosUteis` | comandos que funcionaram de fato, não os que deveriam |
    | `licoesAprendidas` | o que custou tempo, para não custar duas vezes |

    Regra de escrita: **fato verificável, não impressão.** "Onda 3 concluída" é
    inútil; "PUT/GET de 5 MiB com sha256 conferindo, 5,1M em `/var/lib/garage/data`"
    é o que permite retomar sem refazer.

---

## Visão das ondas

```
Onda 0  Repositório e contrato de CI            ✅ feito
Onda 1  Núcleo de domínio puro (lakecore)       ✅ feito
Onda 2  Schema do catálogo                      ✅ feito
Onda 3  Cluster mínimo de pé                    ✅ feito
Onda 4  Ingestão ponta a ponta  ← A PROVA       ✅ feito
Onda 5  Conversar com os dados (chat)           🟢 5.1 e 5.3 feitas; 5.2/5.4/5.5 abertas
Onda 6  Backup e restore provado                ✅ feito (backup consertado + restore provado)
Onda 7  Bundle offline                          ⬜ não começou  ~1-2 sessões
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

- ~~`kubectl exec`/`logs`/`port-forward` quebrados~~ — **resolvido em 2026-11-18**
  com `sudo microk8s refresh-certs --cert ca.crt`. Ver `requisitos-sudo.md`, P1.
  O que a correção revelou está logo abaixo e é o mais importante da onda.
- **`rf=1` continua sendo "lake de preparação"** (ADR-005). Nada insubstituível
  deve entrar em `raw/` antes de 3 nós + `rf=3`.
- **Chaves S3 de teste ficaram no cluster** (`lakecore-ingest`, `verificador`).
  Devem ser removidas antes de qualquer dado real: `garage key delete`.
- O Postgres não foi testado com **restart** ainda. Persistência é afirmada pelo
  PVC `Bound` e pelo `pgdata` em disco, não por um ciclo de reinício provado —
  isso é Onda 6.

### Adendo (2026-11-18, depois do P1) — o que `logs` escondia

Assim que `logs` voltou, apareceu um bug que existia desde a primeira instalação:

```
FATAL: role "$(POSTGRES_USER)" does not exist     (a cada 10s)
```

Duas falhas na mesma linha:

1. **`$(VAR)` não é expandido em `exec.command`** no Kubernetes — só em
   `command`/`args`. Os argumentos chegavam literais ao container.
2. **`pg_isready` devolve 0 mesmo com role inexistente** (medido: `-U '$(POSTGRES_USER)'`
   → exit 0). Ou seja, o readiness probe **passava sem testar autenticação**.
   O pod ficava `Ready` com credencial potencialmente quebrada.

Corrigido: probe roda `psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT 1'`
via `sh -c`. Validado por medição — exit 2 com role inexistente, exit 0 com a
role correta.

**É a terceira ocorrência do mesmo padrão em um dia:** `make ci | tail`,
objetos <1 MiB inlinados no LMDB, e agora `pg_isready`. **Três coisas que
pareciam verdes sem exercitar nada.** O antídoto é sempre o mesmo: perguntar
qual mecanismo o teste realmente toca, e provar que ele **falha** quando deve.

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

### ✅ CONCLUÍDA — 2026-11-18

**A prova do projeto, executada no cluster:**

```bash
# upload HTTP
POST /uploads → HTTP 201
{"sha256":"f56fd752...","key":"raw/teste-e2e/texto/2026/11/18/f56fd752...",
 "size":27,"duplicate":false,"origem":"teste-e2e"}

# segunda vez, mesmo arquivo
{"sha256":"f56fd752...","duplicate":true}

# catálogo
SELECT count(*), origem, status FROM objects → 1 | teste-e2e | cataloged
```

**1 arquivo → 1 objeto + 1 linha. Rodar 2× → ainda 1.**

E o backup também passou a funcionar no caminho:
```
dump ok: 2262 bytes
INFO enviado: backup/postgres/d-20261118T114938Z.sql.gz
Job: Complete 1/1
```

**O que está pronto e provado:**

```bash
# 8 testes de integração contra Garage e PostgreSQL REAIS
S3_ENDPOINT=... LAKECORE_TEST_PG_URL=... make test-integration
# 8 passed in 2.62s
```

| artefato | estado |
|---|---|
| `src/lakecore/adapters/s3_store.py` | ✅ `put`/`exists`/`garantir_bucket` |
| `src/lakecore/api/main.py` | ✅ `/uploads`, `/health` (faz `SELECT 1`), `/objects/{sha}` |
| `src/lakecore/drop_scan.py` | ✅ varre `drop/`, arquiva sem apagar antes de confirmar |
| `charts/ingest` | ✅ Deployment + CronJob do `drop/`, `helm lint` ok |
| `scripts/bootstrap-s3.sh` | ✅ cria chave e Secret de forma idempotente |
| `Dockerfile` | ✅ multi-stage, não-root, `exec form` para SIGTERM |

**Três provas por medição, não por configuração:**

1. **Write-only é real.** Com a chave de `ingest`: `PUT` → ok, `GET` → `AccessDenied`.
   A política do ADR-011 está medida, não afirmada.
2. **Idempotência ponta a ponta.** Mesmo arquivo 2×: 1 linha em `objects`, 1 objeto
   no storage, `duplicate=True` na segunda.
3. **Objeto de 2 MiB gera bloco em disco** (não inlinado no LMDB como os <1 MiB).

**BLOQUEIO RESOLVIDO — era `firewalld`, não a rota blackhole.**

```
blackhole 10.1.74.192/26     ← cobre TODOS os pods
vxlan.calico inet 10.1.74.192/32
calico-node: 1301 restarts, reiniciou 02:30 (durante refresh-certs)
```

Pod → pod e Service → pod dão `No route to host`. `ClusterIP` funciona (DNAT),
IP de pod não. `ingest-api` sobe mas não alcança o catálogo.

**Resolvido por:** `sudo bash scripts/fix-firewalld-calico.sh` — o firewalld
filtrava a cadeia `FORWARD` e as interfaces `cali*` não estavam na zona `trusted`.
O restart do microk8s não resolvia porque o problema nunca foi do cluster.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| `drop/` como PVC ReadWriteMany | `hostPath` — decidido em §10, é o mesmo modelo do Garage |
| chave S3 criada no bootstrap do chart | `scripts/bootstrap-s3.sh` fora do chart: credencial não pode vir do Helm |
| `key create` idempotente | **não é** — criar duas vezes gera duas chaves com o mesmo nome, e `key info <nome>` passa a responder "N matching keys". Corrigido com verificação prévia |
| `boto3==1.35.76` | atualizado a `1.44.5`: a versão antiga usa `utcnow()`, deprecado, e `filterwarnings=error` quebrava a suíte |

**Pendências explícitas:**

- **CronJob do `drop/` executou com sucesso mas com diretório vazio.** A porta
  `drop/` não foi exercitada com arquivo real: `/var/lib/datalake/drop` é
  `root:root` e o job roda como `10001`. Colocar arquivo ali exige root.
  **É a única parte da onda sem prova ponta a ponta.**
- **Migração do catálogo não é aplicada pelo chart.** O `objects` não existia no
  cluster e o `/health` passava, porque só fazia `SELECT 1`. Foi necessário rodar
  `alembic upgrade head` à mão. Fica para a Onda 6 (Job de migração).

---

## Onda 5 — Conversar com os dados (chat)

**Objetivo.** A pessoa pergunta em português e recebe resposta **vinda dos dados**.

**Pergunta de produto respondida em 2026-11-18** (era o último item aberto da
§10): quem usa são pessoas que querem **controle sobre os próprios dados**,
coleta simples e custo baixo. Ao executar pela primeira vez, o que querem ver é
**uma interface para conversar com os próprios dados** — um chat.

Isso redefine a onda. Dashboard deixa de ser o centro e passa a ser
**diagnóstico de saúde** do lake, não exploração. Ver ADR-014.

**Entregáveis**
- **`chat-api`**: recebe pergunta em linguagem natural, devolve resposta + o SQL
  que foi executado
- **Executor de SQL com read-only, `LIMIT` e `timeout`** — o componente crítico
- Página de chat (a interface principal)
- Painel secundário: volume, últimas entradas, saúde
- **Playwright** cobrindo: pergunta → resposta → SQL visível

**Pronto quando**
```bash
make chat-demo    # "quantos arquivos tenho por origem?" → resposta + SQL
make e2e          # Playwright verde no fluxo de conversa
```

**O que NÃO é.** O chat não "sabe" nada sobre o acervo por conta própria. Toda
afirmação sobre os dados nasce de consulta executada. O modelo redige; o banco
responde.

**Risco — o maior da onda.** Um `DROP` gerado por modelo é o pior cenário
possível neste projeto: o dado bruto é o ativo e não é reconstruível. Mitigações
obrigatórias, todas testáveis:

1. credencial **read-only** no executor, separada da de ingestão
2. allowlist: só `SELECT` (e `WITH`) passa
3. `LIMIT` forçado e `statement_timeout`
4. **o SQL é mostrado ao usuário** — transparência é o que separa "conversar
   com os dados" de "confiar no chatbot"

**Ordem interna da onda:**

| # | entrega | por quê antes do resto |
|---|---|---|
| 5.1 | executor SQL read-only + testes de recusa | sem isso o chat é um vetor de destruição |
| 5.2 | export Parquet do catálogo | dá ao chat algo para consultar sem bater no OLTP |
| ~~5.3~~ | ~~`chat-api` com LLM plugável~~ **REVISADO** → servidor MCP + Hermes Agent como tela | o runtime de agente já existe; reescrevê-lo era refazer o que funciona |
| 5.4 | UI de chat | só depois de 5.1–5.3 provados |
| 5.5 | painel secundário + e2e | fecha a guardrail de Playwright |

**Dependência externa declarada.** O LLM é **opcional**: sem ele o chat degrada
para "pergunta por filtro" (origem, tipo, data). Um lake que só funciona com GPU
disponível não serve para infraestrutura mínima.

### 🟢 5.1 CONCLUÍDA — 2026-11-18 — executor SQL read-only

Onda em andamento. **5.1 está pronta**; 5.2–5.5 não.

**Prova executável:**
```bash
make test          # 33 testes no executor, sem rede e sem container
```

| arquivo | conteúdo |
|---|---|
| `src/lakecore/chat/executor.py` | `validar()`, `executar()`, `ResultadoSql`, `SqlRecusado` |
| `tests/test_chat_executor.py` | 33 testes: 11 formas de escrita, statements múltiplos, CTE com escrita, falso positivo |

**Quatro camadas de defesa, independentes:**

| # | defesa | falha se… |
|---|---|---|
| 1 | allowlist de primeira palavra (`SELECT`/`WITH`) | — |
| 2 | statement único (`;` só no fim) | — |
| 3 | `WITH` contendo `insert/update/delete/merge` recusado | — |
| 4 | credencial **read-only** no banco (o chart, ainda não feito) | as três acima falharem |

**O que o teste prova de verdade** — e eu verifiquei que **falha** ao remover a
allowlist:

```
FAILED test_escrita_e_recusada[DROP TABLE objects]
FAILED test_escrita_e_recusada[DELETE FROM objects]
FAILED test_recusa_antes_de_tocar_no_banco
```

**Não recusa falso positivo** — três testes específicos:
`select drop_reason from events`, `select * from delete_log`,
`select 'DROP TABLE x'`. Buscar substring recusaria os três; análise da primeira
palavra não.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| ordem 5.1 → 5.5 | mantida, mas 5.1 cresceu: 4 camadas e 33 testes em vez de "um executor" |
| `LIMIT` forçado | pede `limite + 1` linhas de propósito — com exatamente `limite` não há como distinguir "havia mais" de "cabia justo" |

**Pendências explícitas:**

- **A credencial read-only no banco não existe ainda.** É a defesa que não
  depende de mim estar certo; sem ela o executor protege só pelo parsing.
- **5.2 a 5.5 não começaram:** export Parquet, `chat-api`, UI, e2e.
- **`SET LOCAL statement_timeout` não é verificado em SQLite** — o teste roda nele
  e o `except` engole. Precisa de um teste contra PostgreSQL real na 5.2.

---

### ✅ 5.3 CONCLUÍDA — 2026-11-18 — tela de chat via MCP (Hermes Agent)

**Decisão do usuário nesta sessão:** Hermes é o caminho principal; usar
**OpenRouter**; o Hermes passa a ser **exclusivo deste projeto**; `vllm-study`
é descartado. A escolha da UI foi delegada a mim.

**Prova executável:**
```bash
make ci-check                                   # 130 testes, 7 pulados (sem PG)
scripts/criar-role-readonly.sh --apply          # prova que o banco recusa escrita
hermes mcp list                                 # 4 ferramentas do servidor lake
hermes -z "Quantos objetos por tipo eu tenho?"   # resposta + SQL, vinda do banco
hermes webapp --status                          # Serving at http://127.0.0.1:9120
```

**O que foi entregue:**

| arquivo | papel |
|---|---|
| `src/lakecore/mcp/__init__.py` | servidor MCP, 4 ferramentas, stdio |
| `src/lakecore/mcp/__main__.py` | permite `python -m lakecore.mcp` |
| `tests/test_mcp.py` | 29 testes: as ferramentas não escrevem |
| `scripts/criar-role-readonly.sh` | **defesa 4**: role `lakecore_chat` sem escrita |
| `scripts/conectar-chat.sh` | ponte host→cluster e URL local da tela |

**As quatro ferramentas:** `lake_esquema`, `lake_buscar`, `lake_sql`, `lake_estado`.

**A arquitectura, e por quê:**

```
Hermes Agent (tela)  →  MCP (stdio)  →  lakecore-mcp  →  credencial read-only  →  Postgres
```

O Hermes é **cliente, não dono do host**. Um runtime de agente que ganha
`terminal` e `file` vira administrador da máquina — e a tela aqui serve para
conversar com dados. Por isso, além do MCP, foram **desabilitadas** as
ferramentas `terminal`, `file`, `code_execution`, `browser`, `computer_use`,
`web`, `image_gen`, `tts` e `delegation`. Derrubar o Hermes não derruba a
ingestão, o backup nem o catálogo.

**A defesa 4 existe agora — e é a única que não depende do meu código:**

```
SELECT em objects  -> 1
DELETE em objects  -> ERROR:  permission denied for table objects
```

Prova adicional: **contornando o executor**, chamando o banco direto com a
credencial do chat, as três defesas de parsing são ignoradas — e o banco recusa
sozinho:
```
'delete from objects'          -> permission denied for table objects
'drop table objects'           -> must be owner of table objects
'update objects set origem=1'  -> permission denied for table objects
```

**O teste que importa não é o caminho feliz.** Pedi ao Hermes, em português e
com "tenho certeza do que estou pedindo", para **apagar todos os objetos**. Ele
recusou, explicou que a porta não existe, e as 11 linhas continuaram lá
(`select count(*)` → 11). Pedi também para executar `rm -rf` — sem ferramenta de
terminal, não fez.

**O que foi ingerido para provar:** 10 arquivos heterogêneos (3 texto WhatsApp,
2 foto, 4 e-mail, 1 PDF) por `POST /uploads`, todos `201`. Reenvio do mesmo
arquivo → `duplicate: true`. Catálogo: 11 objetos, 16.242 bytes, 4 origens,
3 tipos. O chat respondeu 8 texto / 2 foto / 1 pdf — número que eu confiro à mão.

**Escolha de modelo, por medição e não por preferência:** benchmark em
PostgreSQL real (o de SQLite estava errado — `ILIKE` é válido em produção) com
15 perguntas de dificuldade crescente, incluindo JSONB, `HAVING`, subconsulta e
porcentagem. Três modelos baratos empataram em **15/15**: `gpt-oss-20b`,
`ling-3.0-flash` e `deepseek-v3.2`. O placar não discriminou SQL correto.

O que discriminou foi **alucinação**: perguntas impossíveis com o schema real
(coluna `proprietario`, `avaliacao_estrelas`, etiqueta `urgente`), onde a
resposta certa é admitir que não existe:

| modelo | recusa corretamente |
|---|---|
| `deepseek/deepseek-v3.2` | **3/3** |
| `anthropic/claude-haiku-4.5` | 3/3 |
| `openai/gpt-oss-20b` | 2/3 |
| `inclusionai/ling-3.0-flash` | 1/3 |

**Escolhido: `deepseek/deepseek-v3.2`** — 3/3 em não inventar, 15/15 em SQL,
163k de contexto, US$ 0,26/M entrada e 0,38/M saída. `claude-haiku-4.5` empatou
em acerto e custa 4× mais; fica como reserva.

**UI escolhida: `hermes webapp` (oficial), não `hermes-webui` (terceiro).**
Motivo: o oficial serve o **mesmo** renderer do Desktop, no mesmo gateway, com
as mesmas sessões — não é um cliente paralelo que precisa ser mantido em sincronia.
O `hermes-webui` de terceiros (19,5k★) reimplementa a camada; mais uma peça para
divergir. Verificado: HTTP 200 em `127.0.0.1:9120`.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| 5.3 = `chat-api` próprio com LLM plugável | **substituído** por servidor MCP + Hermes. Motivo: o runtime de agente, a memória e o gateway de mensagens já existem e são melhores do que qualquer `chat-api` desta onda |
| LLM local (vLLM) como runtime | **OpenRouter**, decidido pelo usuário. A VRAM foi liberada: `vllm-study` parado e removido, **3.754 MiB livres** |
| 4 camadas de defesa | continuam 4; a nº 4 (credencial) **passou a existir nesta sessão** |
| benchmark decide o modelo | o placar de SQL empatou; quem decidiu foi o teste de alucinação |

**Armadilhas pagas nesta sessão (não repetir):**

| sintoma | causa real |
|---|---|
| `pip` instalava e o ingest-api quebrava em runtime | `mcp` declara `starlette>=0.27`; o resolver subia para 1.x, incompatível com `fastapi 0.115` (`<0.39`). Pinar `starlette==0.38.6`, `uvicorn==0.32.1`, `sse-starlette==2.1.3` |
| tela pendurada esperando o MCP | `python -m lakecore.mcp` falhava: pacote sem `__main__.py`. Criado |
| `Name or service not known` na tela | o Secret aponta `postgresql:5432` (Service **dentro** do cluster); o MCP roda no host. Usar `scripts/conectar-chat.sh`, que mantém a ponte |
| troquei o `.env` e a tela continuou com a URL velha | o **gateway** já rodava e tinha o `.env` em memória; ele é quem inicia o MCP. Reiniciar o gateway, não só editar |
| `hermes gateway restart` travou 300s | havia sessão de chat viva (`manage_connections`). `stop --yes` para interromper de propósito |
| `SET LOCAL` e `information_schema` funcionavam em PG e quebravam em SQLite | mesmo padrão "só funciona no dialeto certo". `aplicar_timeout()` devolve bool (testável); schema vem de `Base.metadata`, não de `information_schema` |
| nome da constraint não casava | a convenção de metadata prefixa: `ck_objects_status_valido`. Comparar sufixo |
| meu benchmark reprovava 3 modelos corretos | erro **meu**: ordem de colunas invertida, `e`+63 zeros em vez de `e`×64, `AVG` arredondado. Corrigi a expectativa, não o modelo |

**Pendências explícitas:**

- **`lakecore-mcp` roda no host, não no cluster.** É desvio declarado: o MCP é
  subprocesso da tela, e a tela é local. Na Onda 7 (bundle offline) ou na 5.5
  ele vai para dentro do cluster, ao lado do Postgres, e
  `scripts/conectar-chat.sh` deixa de ser necessário.
- **O gateway do Hermes não é serviço.** Roda com `setsid hermes gateway run`.
  Instalar como serviço (`hermes gateway install`) é opcional e ficou de fora —
  é mudança de host, não do projeto.
- **A ponte `port-forward` morre com o host.** `scripts/conectar-chat.sh` a
  recria; não há supervisão automática.
- **Sobreviver a restart do pod não foi testado** para a role `lakecore_chat`
  (ela vive no PVC do Postgres).
- **5.2 (Parquet) não foi feita** e continua fazendo sentido: o chat hoje
  consulta o OLTP direto. Com acervo grande isso deixa de servir.
- **5.4/5.5:** a UI oficial já atende "conversar com os dados". O painel
  secundário dedicado e o Playwright continuam pendentes.

### ✅ 5.2 CONCLUÍDA — 2026-11-18 — export Parquet do catálogo

**Prova executável:**
```bash
make export-parquet
#   objects: 11 linhas
#   uploads: 0 linhas
#   total: 4139 bytes em 2 arquivo(s)
```

| arquivo | papel |
|---|---|
| `src/lakecore/export/__init__.py` | `exportar()`, `consultar()`, tipos declarados |
| `src/lakecore/export/cli.py` | um caminho só, usado pelo Job e por quem depura |
| `docker/backup/publicar_derivado.py` | publica em `backup/derived/` |
| `tests/test_export.py` | 12 testes |

**Por que `duckdb` e não `pyarrow`:** um pacote de 31 MB escreve **e** consulta
Parquet; `pyarrow` faria só escrever e custaria 42 MB. Num bundle offline que
precisa caber em pendrive, um pacote com dois trabalhos vence dois com um cada.

**A decisão que o teste protege: os tipos.** Escrever tudo como `varchar`
"funciona" e é o defeito: `size_bytes` viraria texto e `sum()` passaria a
comparar strings. O schema é **declarado** em `TIPOS`, não inferido — coluna
vazia não tem tipo para inferir, e inferir de dados reais faz o schema do
derivado mudar conforme o acervo. Verifiquei que os testes **falham** ao
reverter para `varchar`: o DuckDB responde `BinderException` em `sum()`.

```
sha256        VARCHAR     size_bytes   BIGINT     coletado_em  TIMESTAMP
```

**Fidelidade provada contra o acervo real:** o Parquet publicado no Garage e
lido de volta dá `(11, 16242)` — a mesma contagem e soma do catálogo.

**Onde ele mora, e por quê:** em `backup/derived/`, não em `derived/`. A chave
do papel `verify` só alcança o bucket `backup`, e isso é deliberado: quem publica
derivado não deve poder escrever ao lado do dado bruto. O teste
`test_mantem_o_bucket_do_papel_verify` avisa se alguém trocar o bucket em vez do
prefixo.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| "dá ao chat algo para consultar sem bater no OLTP" | o **export** existe e está provado; o `lake_sql` **ainda consulta o OLTP**. Ligar o chat no Parquet é trabalho separado, e hoje o OLTP aguenta 11 linhas |
| export como CronJob | o CLI existe e roda; o CronJob no chart ainda não |

**Pendências explícitas:**

- **O chat não lê o Parquet ainda.** `lake_sql` continua no PostgreSQL. Com
  acervo pequeno isso é correto; a virada precisa de medição, não de pressa.
- **Sem CronJob.** O export é manual (`make export-parquet`).
- **Sem retenção nem particionamento.** Um arquivo por tabela; com milhões de
  linhas isso deixa de servir e a partição por data de `coletado_em` vira
  necessária.

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

### ✅ ONDA 6 CONCLUÍDA — 2026-11-18 — backup consertado e restore provado

Esta seção existe porque o item mais importante da Onda 6 **não era** o restore
drill: era descobrir que o backup nunca funcionou.

**Como apareceu.** Investigando a proposta de adicionar OpenTelemetry/Grafana
(pedido do usuário), fui olhar o estado do cluster e achei:

```
postgresql-backup   schedule=0 3 * * *   lastSuccessfulTime=<none>
postgresql-backup-29916360   Failed   0/1   8h
```

**Duas causas independentes, ambas invisíveis:**

| # | causa | sintoma que enganava |
|---|---|---|
| 1 | a tag `lakecore-backup:0.1.0` no containerd apontava para um fragmento **`text/html`** de 493 KiB (página de erro de um pull antigo), não para a imagem | `unexpected media type text/html` — erro que não menciona backup |
| 2 | `docker/backup/upload_s3.py` lia `S3_ENDPOINT`; o chart injeta `GARAGE_S3_ENDPOINT` | `KeyError: 'S3_ENDPOINT'`, dentro de um pod que o Job já tinha apagado |

**Por que ninguém viu por 8 horas:**
- `successfulJobsHistoryLimit: 3/3` com falha diária: em 3 dias o Job que
  falhou é apagado e sobra só `lastSuccessfulTime: <none>`, que ninguém consulta.
- O pod é apagado antes de alguém ler o log; `kubectl logs` devolvia
  `timed out waiting for the condition`.
- `kubectl get jobs` mostrava `Failed` — a informação estava **visível**, não
  escondida. Faltou olhar.

**Conserto:**

```bash
# 1. importar a imagem real, por cima da tag corrompida.
#    `ctr` do sistema é v2.2.4 e o containerd do microk8s é v1.6.28:
#    incompatíveis ("unknown service containerd.services.streaming.v1").
#    Usar o `ctr` do próprio snap. NÃO precisa de sudo: o socket é root:microk8s
#    e o usuário está no grupo.
CTR="/snap/microk8s/current/bin/ctr --address /var/snap/microk8s/common/run/containerd.sock --namespace k8s.io"
docker save lakecore-backup:0.1.1 -o /tmp/b.tar
$CTR images rm docker.io/library/lakecore-backup:0.1.0
$CTR images import --digests /tmp/b.tar

# 2. o script aceita os dois nomes de variável (_exigir)
# 3. imagePullPolicy: IfNotPresent no template (faltava)
```

**Prova executável:**

```bash
make test                                              # 139 testes (9 novos)
microk8s kubectl -n lake-data create job --from=cronjob/postgresql-backup bk
#   backup-prova   Complete   1/1   6s
microk8s kubectl -n lake-data logs job/backup-prova
#   dump gerado: 3239 bytes
#   INFO enviado: backup/postgres/lakecore-20261118T141150Z.sql.gz (3239 bytes)
```

**RESTORE PROVADO** — o que a onda inteira existia para provar. Restaurei num
banco novo (`restore_drill`), sem tocar no original:

```
original:   11 obj, 16242 bytes
restaurado: 11 obj, 16242 bytes
```

O dump baixado do Garage começa com `PGDMP` (formato custom do `pg_dump`),
descomprime para 10.315 bytes e restaura sem erro.

**Desvios do previsto:**

| previsto | ocorrido |
|---|---|
| Onda 6 = construir backup e provar restore | o backup **já existia e estava quebrado**; a onda virou conserto + prova |
| prova = destruir PVC e restaurar | feito de forma mais segura: restaurar em **banco novo** e comparar. Destruir o PVC do único nó não provaria mais e arriscaria o acervo — o drill destrutivo fica para quando houver segundo nó |
| `make restore-drill` automatizado | o drill foi executado à mão em pod avulso; **o alvo do Makefile ainda não existe** |

**Armadilha nova, e é a quarta do mesmo tipo:** o teste que escrevi para pegar o
bug **passou com o bug presente**. Ele comparava o YAML do chart contra uma
lista de nomes escrita à mão, e não contra o que o script consome. Corrigido:
agora exige `"GARAGE_S3_ENDPOINT"` no **código do script**, e verifiquei que
falha ao reintroduzir o bug. (As outras três: `make ci | tail`, objetos <1 MiB
inlinados no LMDB, `pg_isready` com role inválida.)

**Pendências explícitas:**

### ✅ `make restore-drill` — o critério de pronto, agora executável

O drill que eu tinha feito à mão virou código. Executa o ciclo inteiro dentro de
um Pod efêmero e **falha se divergir**.

**Prova:**
```bash
make restore-drill
#   assinatura do banco ORIGINAL:
#     objects: 11 linhas, md5=1537030f91fe27b59bd8ba94391e4f77
#     uploads: 0 linhas, md5=(vazio)
#   assinatura do banco RESTAURADO:
#     objects: 11 linhas, md5=1537030f91fe27b59bd8ba94391e4f77
#     uploads: 0 linhas, md5=(vazio)
#   ✓ RESTORE PROVADO — o dump voltou a ser um catálogo idêntico
```

| arquivo | papel |
|---|---|
| `docker/backup/restore_drill.py` | escolhe o dump, valida `PGDMP`, restaura, compara |
| `scripts/restore-drill.sh` | orquestra o Pod; `--dry-run` é o padrão |
| `tests/test_restore_drill.py` | 14 testes da lógica de comparação |
| Makefile | `restore-drill`, `restore-drill-check` |

**Por que compara md5 e não só `count(*)`:** contagem sozinha aprova
"restaurei 11 linhas, só que as erradas". A assinatura é
`(número de linhas, md5 da lista de chaves ordenada)` por tabela. Verifiquei que
o comparador **falha** ao remover a checagem de digest e ao remover a detecção
de tabela ausente.

**O drill também foi testado contra falsos positivos:**

| situação plantada | resposta do drill |
|---|---|
| `.sql.gz` com lixo e nome mais recente | `não é um dump custom do pg_dump (começa com b'isto ')` |
| banco restaurado sem `uploads` | `uploads: ausente no banco restaurado` |
| mesma contagem, conteúdo diferente | `mesma contagem (11) mas conteúdo diverge` |

**Três defeitos meus, pegos pelo próprio caminho:**

1. `ENTRYPOINT ["/bin/sh","-c"]` da imagem fazia o Pod morrer com
   `-c requires an argument`; foi preciso sobrescrever `command`.
2. `psql`/`pg_restore` **não leem `POSTGRES_PASSWORD`** — é `PGPASSWORD`. O Job
   de backup já tinha pago esse erro, e ele reapareceu aqui.
3. shellcheck `SC2006`: backticks dentro de comentário. Corrigido para aspas.

**Pendências explícitas:**

- **Restore destrutivo (apagar o PVC) não foi feito.** O drill restaura num
  banco novo do **mesmo** servidor. Simular a perda do PVC exigiria apagar o
  volume de um nó único — arriscaria o acervo sem provar nada a mais. Fica para
  quando houver segundo nó.
- **O backup de depuração `postgres/d-20261118T114938Z.sql.gz` (2.262 bytes)
  continua no Garage** e deve ser apagado antes de dado real.
- **A tag `lakecore-backup:0.1.0` continua no containerd** apontando para o
  `text/html`. Não removi para não quebrar um release antigo; o values aponta
  para `0.1.3`.
- **Nada disso é monitorado.** A falha ficou 8 horas visível em
  `kubectl get jobs` e ninguém viu. Observabilidade (OpenTelemetry + Grafana)
  foi discutida nesta sessão e **deliberadamente adiada** — decisão do usuário.
- **O drill não roda agendado.** É manual (`make restore-drill`). Rodar
  semanalmente exigiria um CronJob que cria Pods — fica para a Onda 7.

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
| 1 | `replication_factor`: `1` agora ou aguardar 3 nós? | — | ✅ **respondida: `rf=1`** |
| 2 | PostgreSQL: StatefulSet + CronJob ou CloudNativePG? | — | ✅ **respondida: StatefulSet** |
| 3 | `drop/`: PVC `ReadWriteMany` ou `hostPath`? | — | ✅ **respondida: `hostPath`** |
| 4 | **Quem instala e o que quer ver?** | — | ✅ **RESPONDIDA 2026-11-18:** quem quer controle sobre os próprios dados, coleta simples e custo baixo. Quer **conversar com os próprios dados** — um chat. Ver ADR-014 |
| 5 | LLM do chat: Ollama ou vLLM? | — | ✅ **respondida: vLLM. Ollama desabilitado (`scripts/desabilitar-ollama.sh`). ADR-015** |
| 6 | Chat sem LLM é degradação ou modo primário? | — | ✅ **RESPONDIDA na prática (5.3):** primário. `lake_buscar` responde por filtro sem modelo; o LLM é acelerador. Testado: a ferramenta funciona com o LLM fora do ar |
| 7 | Runtime de LLM: local (vLLM) ou remoto? | — | ✅ **respondida 2026-11-18: OpenRouter.** VRAM liberada (`vllm-study` removido). vLLM continua o caminho para o bundle offline da Onda 7 |
| 8 | A tela (Hermes) é dona do host? | — | ✅ **respondida: não.** Cliente via MCP, ferramentas de host desabilitadas |

**As quatro primeiras estão fechadas.** As duas novas são consequência direta da
resposta de produto e são menores: nenhuma delas muda arquitetura, só a
implementação do chat.

Nota sobre a nº 6 — é decisão de produto, não técnica: um lake que só funciona
com GPU disponível contradiz "infraestrutura mínima". A minha recomendação é que
o modo sem LLM (pergunta por filtro: origem, tipo, data) seja **primário e
completo**, e o LLM um acelerador.

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
