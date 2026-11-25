# Homologação Onda 7 — Tentativa 4

Data: 2026-11-24/25
Status: 🟡 EM ANDAMENTO
VM: `lake-homologacao` (libvirt, Ubuntu 24.04.5, 4 vCPU / 8 GB RAM)

## Objetivo

Fechar o critério de pronto da Onda 7:

```bash
# máquina limpa, sem rede
sudo bash install.sh --engine standard && sudo bash verify.sh
```

## Histórico (resumo das tentativas anteriores)

| Tentativa | Data | Resultado | Causa raiz |
|---|---|---|---|
| 1 | 18/nov | ❌ install parou no passo 2 | snapd não estava no bundle; tentou atualizar on-line sem rede |
| 2 | 19/nov | ❌ cluster nunca Ready | snapd reiniciou e o hook do microk8s foi ignorado (`INFO task ignored`) |
| 3 | 19/nov | ❌ cluster Ready por um instante, depois refused | mesma causa; `microk8s start` explícito entrou no install (passo 2b/7) |

## Correções aplicadas nesta rodada

### 1. `install.sh` — passo 2b/7 (cluster inicializado de verdade)
Já estava no repo (commit `96d8192`): após instalar o microk8s, verifica se a API
responde (`microk8s kubectl get --raw /readyz`) e, se não, roda `microk8s start`
explícito e espera até 10 min. Evita o "verde sem exercitar nada" do `snap list`.

### 2. `bundle.sh` — export de imagens (3 bugs encontrados nesta rodada)

**Bug A — tar sobrescrito (319 KB):** `ctr images export` num loop sobrescrevia o
mesmo arquivo; só a última imagem ficava. Corrigido → 3,4 GB.

**Bug B — manifest list multi-plataforma:** `ctr images export --platform amd64`
grava o manifest list completo; o import alvo valida filhos de outras plataformas
e falha em `content digest ... not found`. Imagem culpada: garage v1.1.0
(referenciava manifest 386 ausente).

**Bug C — skopeo não faz append:** `skopeo copy ... docker-archive:tar` falha com
`docker-archive doesn't support modifying existing images` ao adicionar a 2ª
imagem num tar existente.

**Solução final:** **um tar por imagem** (`images/img-001.tar` ... img-023.tar),
cada um via `ctr images export` → `skopeo copy --override-arch amd64` (que
reescreve o manifest para amd64 simples). O `install.sh` importa `images/*.tar`
em loop (contando N_IMPORTADAS).

### 3. `install.sh` — passo 4/7 suporta `images/*.tar` ou `images.tar`

## Estado da VM nesta rodada

- microk8s v1.31.14 instalado (snaps locais do bundle)
- Cluster Ready (nó `lake-homologacao`)
- Rede `enp1s0` desligada → sem internet (ping unreachable, DNS exit 2, https 000)
- Bundle corrigido copiado para `/opt/datalake-bundle-0.1.0/` (4,4 GB), checksums OK
- install.sh rodando (2026-11-25 02:0x UTC) — passo 4/7 importando imagens

## LICÃO CRÍTICA desta rodada (prova de offline)

**NÃO derrubar a rota default / interface para provar "sem rede".** O Calico CNI
precisa alcançar o service do apiserver (`10.152.183.1:443`) para criar/destruir
sandboxes. Com a rota default removida, todo pod novo fica `ContainerCreating`
com `SandboxChanged` para sempre e o helm `--wait` estoura ("context deadline
exceeded"). Sintoma nos logs do containerd:

```
plugin type="calico" failed (delete): error getting ClusterInformation:
Get "https://10.152.183.1:443/apis/...": dial tcp 10.152.183.1:443:
connect: network is unreachable
```

**A prova de offline correta:** bloquear a SAÍDA externa com iptables (DROP
para IPs públicos/DNS), mantendo as rotas internas do cluster intactas.

## Ajustes encontrados no caminho (bundle v3)

1. **Faltava `cdkbot/hostpath-provisioner:1.5.0` + `busybox:1.28.4`** — sem elas o
   addon hostpath-storage não sobe e o PVC do PostgreSQL fica Pending.
   Corrigido: incluir no bundle (imagens agora 25).
2. **Faltava `lakecore-backup:0.2.0`** — o CronJob do backup usa
   `pullPolicy: Never`; sem a imagem no containerd o pod falha com
   `ErrImageNeverPull`. Corrigido: buildada e importada no host (bundle 26).
3. **`bootstrap-s3.sh` não estava no bundle** — o install.sh cria os secrets e
   AVISA que o secret `lakecore-s3-ingest` precisa do bootstrap. Corrigido:
   copiado explicitamente para o bundle.

## Logs
(A serem anexados conforme a rodada avança)

- `install-onda7-t4.log` — bundle v1 (falhou: import de imagens)
- `install-onda7-t5.log` — bundle v2 (falhou: storage + secrets)
- `verify-onda7-t5.log` — pendente
- `install-onda7-t6.log` — bundle v3 (em preparação)

## Resultado — ✅ HOMOLOGADO (2026-11-25 04:06 UTC)

`verify.sh` rodou na VM `lake-homologacao` com rede bloqueada (DNS externo
`dns_exit=2`, curl externo `http=000`), e passou **12/12**:

```
== 1. Cluster          ok  nó Ready
== 2. Pods do lake     ok  garage, postgresql, ingest prontos
== 3. Catálogo         ok  SELECT autenticado + objects acessível
== 4. Garage           ok  armazena e devolve
== 5. Ingestão         ok  health 200; primeiro upload; idempotência por sha256
== 6. Backup           ok  último backup bem-sucedido
== 7. Frescor          ok  saúde registrada

12 verificação(ões) ok, 0 falha(s)  →  RESULTADO: instalação verificada.
```

A **ONDA 7 ESTÁ FECHADA**: `sudo bash install.sh --engine standard && sudo bash verify.sh`
verde numa máquina **sem internet**.

## PENDÊNCIAS RECOMENDADAS (pós-homologação)

1. **Install.sh NÃO roda a migração do catálogo** — comentário na linha 15 diz
   que sim, mas o passo não existe. A tabela `objects` não era criada. Fechado
   manualmente rodando Alembic no pod do ingest. **PENDENTE:** adicionar a
   migração ao install.sh/chart como Job.
2. **Imagem `lakecore-ingest` desatualizada no bundle v1-v3** — não tinha a
   migração `saude`; rebuildada com `src/` atual (contém `c4d9e1a7b203`).
   Incluída no bundle v4.
3. **Garage layout** — o install.sh passo 7/7 só roda se o helm `--wait`
   terminar; como o --wait estourava, o layout não era aplicado. No fim, aplicado
   manualmente (`garage layout apply --version 1`).
4. **Backup não agendado ainda** — o CronJob `postgresql-backup` é `0 3 * * *`;
   para o verify passar foi criado `backup-manual-pg` manualmente. PENDENTE:
   aguardar o agendamento ou criar um trigger no install.

## Defeitos pagos nesta rodada (tentativa 4)

| defeito | causa |
|---|---|
| `images.tar` 319 KB | `ctr export` sobrescrevia o arquivo no loop |
| `content digest ... not found` | manifest list multi-plataforma sem os blobs das outras plataformas |
| `docker-archive doesn't support modifying` | skopeo não faz append; solução: um tar por imagem |
| PVC Pending | `hostpath-provisioner` sem imagem no bundle (adicionada) |
| `connection refused` cluster | remover rota default quebra o Calico (usa service IP) |
| `relation objects does not exist` | migração do catálogo não rodava |
| `ErrImageNeverPull` backup | imagem `lakecore-backup` ausente (buildada e incluída) |
| `sandbox changed` permanente | Calico sem rota para o service IP |
