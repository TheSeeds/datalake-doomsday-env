# Pendências de superusuário

Fila de comandos que **só você pode rodar**. O agente não executa `sudo`, não
digita senha e não contorna privilégio sem declarar (regra 9 do plano).

Cada item diz: o comando, o que ele muda, e o que fica bloqueado sem ele.

---

## 🔴 P1 — certificado do apiserver (bloqueia depuração)

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
você já tenha. **Não** usar o `pramimfez-postgres-1` — é de outro projeto.

---

## Histórico de contornos sem root

Registrado para que o desvio não vire padrão esquecido.

| data | o que precisava de root | como foi resolvido |
|---|---|---|
| 2026-11-18 | `microk8s enable hostpath-storage` | `local-path-provisioner` do Rancher via `kubectl`; StorageClass anotada como default manualmente |
| 2026-11-18 | `kubectl exec` para aplicar layout do Garage | Job em Alpine com o binário do Garage montado de `hostPath`, saída em arquivo no host |

Ambos funcionam. Ambos são dívida registrada, não solução.
