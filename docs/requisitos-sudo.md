# Requisitos de infraestrutura da Onda 3 — o que só `sudo` resolve

Este arquivo existe porque a Onda 3 tem uma fronteira que o agente não cruza:
**habilitar addons do microk8s exige `sudo` com senha.**

Não é limitação de código — é decisão de segurança. Um agente que pede a senha do
`sudo` do usuário para "só rodar um comando" abre um precedente que não deve
existir. Os comandos abaixo são para **você** rodar.

## Passo 1 — addons do microk8s

Cluster: `zoio`, v1.31.14, verificado em 2026-11-18 como **vazio** (nenhum
workload fora de `kube-system`). Habilitar é seguro.

```bash
microk8s enable hostpath-storage
```

Por que só este primeiro: é o único que **persiste dado**. Os outros podem entrar
depois, quando o chart precisar (Fase 3.2). `ingress` e `cert-manager` só fazem
sentido quando houver serviço para expor.

Verificação:

```bash
microk8s kubectl get storageclass
# esperado: microk8s-hostpath (default)
```

> **Ressalva registrada:** o próprio microk8s avisa que hostpath "não é adequado
> para produção" e que o volume pode crescer além do limite do PVC. Para o
> `micro`/`standard` de um nó isso é aceitável e está documentado como limite
> consciente, não como descuido.

## Passo 2 — grupo docker (para os testes)

Verificado: o usuário **não** está no grupo `docker`, então `make ci-full` e
`make test-pg` só funcionam enquanto houver container já autorizado. Para rodar
sem depender disso:

```bash
sudo usermod -aG docker "$USER"
# depois: encerrar sessão e entrar novamente
```

Alternativa sem `sudo`: use `podman`, ou aponte `LAKECORE_TEST_PG_URL` para um
PostgreSQL que você já tenha (o `pramimfez-postgres-1` não é candidato — não é
seu banco de testes, e usá-lo seria misturar projeto).

## O que o agente faz depois

Com o `storageclass` presente, a Onda 3 continua sozinha:

```bash
make cluster-verify   # valida addons, garage e postgres
```

## Estado até lá

A Onda 3 está **escrita e validada estaticamente**:

- charts com `helm lint` verde
- manifests com `kubectl --dry-run=client` verde
- scripts com `shellcheck` verde

O que **não** está provado: que os charts sobem de verdade, e que o Garage
armazena com o layout aplicado. Isso é o critério de pronto da onda e exige o
Passo 1 acima.
