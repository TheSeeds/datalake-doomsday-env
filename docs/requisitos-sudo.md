# Pendências de superusuário

Fila de comandos que **só você pode rodar**. O agente não executa `sudo`, não
digita senha e não contorna privilégio sem declarar (regra 9 do plano).

Cada item diz: o comando, o que ele muda, e o que fica bloqueado sem ele.

---

## ✅ P1 — certificado do apiserver — **RESOLVIDO em 2026-11-18**

```bash
sudo microk8s refresh-certs --cert ca.crt   # executado pelo usuário
```

**Resultado:** `kubectl exec`, `logs` e `port-forward` voltaram a funcionar;
cluster e layout do Garage sobreviveram ao restart. O aviso 3 do
`cluster-verify.sh` desapareceu sozinho — a detecção é por teste real, não por
diagnóstico herdado.

**O que a correção revelou de imediato** (nada disso era visível antes, porque
`logs` estava inacessível):

| descoberta | gravidade |
|---|---|
| probe do PostgreSQL usava `$(POSTGRES_USER)` em `exec.command`, que o Kubernetes **não expande** | logs com `role "$(POSTGRES_USER)" does not exist` a cada 10 s |
| `pg_isready` retorna **0 mesmo com role inexistente** — o probe passava sem testar autenticação | falha silenciosa: pod `Ready` com credencial quebrada |

Ambos corrigidos: probe agora roda `psql ... -c 'SELECT 1'` via `sh -c`, que
autentica de fato (medido: exit 2 com role inexistente).

---

## Histórico — P1 original (mantido como registro)

**Sintoma.** `kubectl get` funciona; `kubectl exec`, `kubectl logs` e
`kubectl port-forward` falham:

```
x509: certificate is valid for 192.168.1.103, ..., not 192.168.1.11
```

**Causa.** O IP do host mudou de `192.168.1.103` para `192.168.1.11` depois que o
cluster subiu, e o certificado do apiserver ficou com o IP antigo. `get` usa o
`localhost` do kubeconfig; `exec`/`logs` fazem proxy até o kubelet pelo IP do nó,
e é aí que a verificação falha.

**Comando:**

```bash
sudo microk8s refresh-certs --cert ca.crt
```

**O que muda.** Regenera o certificado da CA com o IP atual e reinicia o
apiserver. O cluster fica indisponível por ~30 s. `kubectl` volta a funcionar
logo depois.

**O que fica bloqueado sem isso.** Depuração de qualquer pod: ler log de
`ingest-api`, executar `psql` dentro do Postgres, abrir shell no Garage para
`garage status`. Na Onda 3 eu contornei com Jobs que escrevem em `hostPath`; isso
funciona, mas gasta tempo e não serve para operação normal.

**Impacto hoje:** a Onda 4 (ingestão) é depurável sem isso, mas com muito mais
rodadas de tentativa e erro.

---

## 🟡 P2 — storage class nativa (opcional, não bloqueia)

---

## 🔴 P4 — `firewalld` bloqueia FORWARD entre pods (BLOQUEIA a Onda 4)

### Diagnóstico correto (2026-11-18, após restart não resolver)

A hipótese inicial era a rota `blackhole`. **Estava errada** — o kernel resolve o
pod corretamente:

```
ip route get 10.1.74.236  →  10.1.74.236 dev cali41ea7915227
```

A rota `blackhole 10.1.74.192/26` é ruído: existe, mas perde para a rota `/32`
por host. O host alcança o pod (`host → pod IP: OK`).

**A causa real é `firewalld`.**

| evidência | valor |
|---|---|
| `firewalld` no host | **`active`** (Fedora), iniciado `2026-11-17 23:00` |
| `vxlan.calico` em alguma zona | **não** |
| interfaces `cali*` em alguma zona | **não** |
| `ip_forward` | `1` (habilitado) |
| política de `FORWARD` | bloqueia (padrão do firewalld) |

O firewalld **filtra a cadeia `FORWARD`**. Tráfego que entra no host é permitido
(`INPUT`), por isso `host → pod` funciona. Tráfego que **atravessa** o host —
exatamente o caso pod → pod — é descartado. O Calico usa a cadeia `FORWARD` para
suas políticas; com firewalld na frente, o pacote morre antes.

### Prova

| caminho | resultado |
|---|---|
| host → pod IP | **OK** |
| pod → pod IP | `No route to host` |
| pod → Service ClusterIP | `Connection timed out` |
| pod → internet (`172.21.0.1:443`) | OK |

**Refinamento (medição posterior, mais precisa):**

| alvo | tipo | resultado |
|---|---|---|
| `garage` `10.152.183.104:3900` | **ClusterIP** | ✅ `open` |
| `postgresql` `10.1.74.236:5432` | **pod IP** | ❌ `No route to host` |
| `10.1.74.236:5432` do host | pod IP | ✅ OK |

ClusterIP funciona; **pod IP não**. E o `postgresql` é o único Service
**headless** (`clusterIP: None`) — logo é o único que expõe IP de pod direto para
os clientes. O Garage funciona porque o cliente resolve para ClusterIP.

Isso **restringe** o diagnóstico: não é `FORWARD` genérico (o ClusterIP é DNAT e
passa pelo mesmo caminho), é o encaminhamento **entre interfaces `cali*`** — que
é exatamente o que a zona `trusted` sem interfaces bloqueia.

As duas primeiras linhas juntas fecham o diagnóstico: o host entrega, o pod não
atravessa.

> **Ação imediata sem root:** trocar o Service do PostgreSQL de headless para
> ClusterIP desvia do problema. Mas isso é paliativo: `pod → pod IP` continua
> quebrado e o `ai-worker`/`query-api` da Onda 5 precisam dele. O fix é o
> firewalld.

### Comando (exige root)

Adicionar as interfaces do Calico à zona `trusted` — **e persistir**:

```bash
sudo firewall-cmd --permanent --zone=trusted --add-interface=vxlan.calico
sudo firewall-cmd --permanent --zone=trusted --add-interface=cali+
sudo firewall-cmd --reload
```

> `cali+` não é wildcard de zona: o firewalld aceita o sufixo para interfaces
> ainda não criadas. Se a versão recusar, use as interfaces existentes:
> `sudo firewall-cmd --permanent --zone=trusted --add-interface=$(ip -br link | awk '/cali/{print $1}' | tr '\n' ' ')`

Alternativa mais ampla (e mais perigosa): permitir todo `FORWARD` na zona do
Calico. Prefira a primeira — ela abre só o necessário.

### Verificar depois

```bash
firewall-cmd --zone=trusted --list-interfaces
# esperado: vxlan.calico cali+

# e o teste que importa:
microk8s kubectl -n lake-data run tv --rm -i --restart=Never \
  --image=busybox:1.36 -- nc -zv -w4 postgresql 5432
# esperado: postgresql (10.152.183.x:5432) open
```

### Por que o restart do microk8s não resolveu

Porque o problema **nunca foi** do microk8s. Reiniciar o cluster não altera
política de firewall do host. Isto é um bom lembrete: o pedido P4 original
apontava para o lugar errado, e a investigação corrigiu o alvo. O pedido
anterior está mantido abaixo como registro do erro.

---

## Histórico — P4 hipótese inicial: rota blackhole (DIAGNÓSTICO ERRADO)

**Sintoma.** Pod → pod e Service → pod falham com `No route to host`. Service
`ClusterIP` funciona (DNAT no kube-proxy), mas qualquer tráfego até o **IP do
pod** é descartado.

**Medido em 2026-11-18.** Host tem:

```
blackhole 10.1.74.192/26                      ← cobre .192 a .255
vxlan.calico  inet 10.1.74.192/32
```

Todos os pods do cluster caem nessa faixa: `.194`, `.201`, `.213`, `.214`,
`.226`, `.249`. **Nenhum** é alcançável por IP.

**Causa provável.** O `calico-node` está com **1301 restarts** e reiniciou às
`02:30` de hoje — durante o `refresh-certs`. A rota `blackhole` para o próprio
podCIDR é o que o Calico instala quando **não sabe** para onde rotear a faixa: em
vez de encaminhar, descarta. É estado inconsistente do dataplane, não
configuração intencional.

**Comando (exige root):**

```bash
sudo systemctl restart snap.microk8s.daemon-containerd
sudo microk8s stop && sudo microk8s start
```

Se a rota voltar após o restart, o dataplane está preso e a alternativa é:

```bash
sudo ip route del blackhole 10.1.74.192/26
```

…mas remover a rota **sem** corrigir a origem faz o Calico recriá-la no próximo
reconcile. O restart é a correção; o `ip route del` é paliativo para confirmar o
diagnóstico.

**O que fica bloqueado.** A Onda 4 está **escrita e testada no host** (8 testes
de integração contra Garage e PostgreSQL reais, todos verdes), mas o chart não
consegue rodar no cluster: `ingest-api` não alcança o catálogo. Sem isso, o
critério "arquivo → objeto **e** linha" não pode ser demonstrado no cluster.

**Por que não contornei.** Contornar exigiria mexer em rotas do host sem root, o
que é exatamente o tipo de ação que a regra 9 manda pedir em vez de assumir.

---

O addon oficial do microk8s grava em `$SNAP_COMMON/default-storage`:

```bash
microk8s enable hostpath-storage
```

**Situação.** Contornado na Onda 3 com `local-path-provisioner` do Rancher, que
grava em `/opt/local-path-provisioner` e é aplicável sem root. Funciona e está em
uso. Habilitar o addon nativo **substituiria** o contorno — mais alinhado ao que a
documentação do microk8s descreve, menos peça de terceiro.

**Não bloqueia nada.** Migrar depois exige recriar o PVC do Postgres (o dado está
em `/opt/local-path-provisioner`), então só vale a pena se houver motivo.

---

## 🟡 P3 — grupo docker (melhora o dia a dia)

Verificado: o usuário **não** está no grupo `docker`. Consequência: `make ci-full`
e `make test-pg` dependem de um container que já esteja autorizado.

```bash
sudo usermod -aG docker "$USER"
```

**O que muda.** Permite rodar `docker` sem `sudo`. Efeito só depois de encerrar a
sessão e entrar de novo.

**Alternativa sem root.** Apontar `LAKECORE_TEST_PG_URL` para um PostgreSQL que
você já tenha, ou usar `make pg-up` (container efêmero na porta 55432).

**Não** use um banco de outro projeto que já esteja rodando na máquina: o teste
derruba e recria tabelas, e destruiria dados que não são seus.

---

## Histórico de contornos sem root

Registrado para que o desvio não vire padrão esquecido.

| data | o que precisava de root | como foi resolvido |
|---|---|---|
| 2026-11-18 | `microk8s enable hostpath-storage` | `local-path-provisioner` do Rancher via `kubectl`; StorageClass anotada como default manualmente |
| 2026-11-18 | `kubectl exec` para aplicar layout do Garage | Job em Alpine com o binário do Garage montado de `hostPath`, saída em arquivo no host |

Ambos funcionam. Ambos são dívida registrada, não solução.

---

## Sessão 2026-11-18 (noite) — Onda 5.3: nenhum novo pedido de superusuário

A 5.3 (tela de chat via MCP) **não precisou de `sudo`**. Tudo o que exigia
privilégio foi feito por `microk8s kubectl`:

| ação | como | precisa de root? |
|---|---|---|
| criar role read-only no PostgreSQL | `scripts/criar-role-readonly.sh --apply` | não (`kubectl exec`) |
| criar Secret com a credencial do chat | mesmo script | não |
| ponte host→cluster | `scripts/conectar-chat.sh` (`port-forward`) | não |
| instalar Hermes Agent | `curl ... install.sh \| bash`, em `~/.hermes` | não |

**Regra 11 respeitada:** o único script que toca o banco
(`criar-role-readonly.sh`) tem `--dry-run` como padrão, `--apply` explícito,
lista de ações em português, o que **não** faz, como reverter, e prova ao final
(`SELECT` funciona, `DELETE` recebe `permission denied`).

**Efeito colateral registrado:** o `vllm-study` (container de **outro projeto**)
foi parado e removido por decisão do usuário nesta sessão — "pode derrubar tudo
que estiver usando a VRAM, [o Hermes] deve ser exclusiva para nosso projeto.
Então vllm-study vai para o lixo". VRAM resultante: **3.754 MiB livres** (era 178).
O repositório `vllm-doomsday` continua intacto em disco: parar o container não
apagou o projeto.

**Pendências de privilégio inalteradas** (continuam opcionais e não bloqueiam):
`microk8s enable hostpath-storage`, `sudo usermod -aG docker $USER`,
`sudo microk8s refresh-certs --cert ca.crt`.

---

## ✅ P1 EXECUTADO — 2026-11-18 — `microk8s refresh-certs`

O usuário executou `sudo microk8s refresh-certs --cert ca.crt`. Resultado medido:

**O que resolveu:** `kubectl exec`, `logs` e `port-forward` voltaram a funcionar.
O `x509` que nos perseguia desde a Onda 3 (IP do host mudou de .103 para .11 e o
certificado não acompanhou) acabou. `scripts/cluster-verify.sh` agora reporta
"kubectl exec funcional" em vez de AVISO de degradação.

**O que NÃO resolveu, e é um achado:** eu tinha juntado dois problemas
diferentes. O CA regenerado **também** não tem a extensão `key usage` — só
`Basic Constraints: critical, CA:TRUE`. Verificado com `openssl x509` no CA do
kubeconfig depois da troca.

Consequência: o `skipTlsVerify: true` do módulo `observability` **continua
necessário**. Testei removê-lo depois do `refresh-certs` e o sidecar voltou a
`CrashLoopBackOff` com `CA cert does not include key usage extension`.

| problema | causa | `refresh-certs` resolve? |
|---|---|---|
| `x509` em exec/logs/port-forward | certificado com IP antigo | ✅ sim |
| sidecar recusa o CA | CA sem extensão `key usage` (como o microk8s gera) | ❌ não |

**O que ficou na fila:** o ideal seria um CA bundle próprio para os sidecars ou
uma imagem cujo cliente TLS não exija a extensão. Nenhum dos dois se paga por um
componente acessório; a dívida está registrada no `values.yaml` do módulo, com o
risco escrito por extenso.

**A disponibilidade continua:** antes de rodar, o usuário precisa saber que
`refresh-certs` reinicia o `kubelite` e o `cluster-agent`, e que nós workers
precisariam ser removidos e re-juntados. Aqui há **um** nó, então não houve
impacto — mas num cluster multi-nó isto é operação de janela.
