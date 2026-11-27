# Homologação do caminho ONLINE — datalake-doomsday-env

> **Status: pendente (critério de pronto aberto da v1.0.0).**
> O caminho **offline** está homologado (VM Ubuntu 24.04 sem rede, 12/12,
> 2026-11-25 — ver `onda7-tentativa4/RELATORIO.md`). Este documento é o roteiro
> para fechar a **segunda** garantia: instalar o lake por `--fonte online` numa
> máquina **limpa com internet** e provar com `verify.sh`.

## O que a homologação online precisa provar

Que `install.sh --fonte online` sobe o lake numa máquina que **tem** internet,
usando:

- microk8s do **snap store** (não do bundle);
- imagens próprias de **`ghcr.io/theseeds/lakecore-{ingest,backup}:1.0.0`**
  (não importadas no containerd, mas puxadas do registry);
- imagens de infra dos **registries públicos** (postgres, garage, etc.);
- o mesmo `verify.sh` de 12 verificações verde.

**NÃO é** a mesma prova do offline: aqui a máquina **tem** rede, e o valor é
confirmar que o instalador usa essa rede corretamente (não depende do bundle).

## Pré-requisitos (você executa — credencial/maquina)

| item | detalhe |
|---|---|
| Máquina limpa com rede | Ubuntu 24.04 (Tier 1) ou uma VM na rede |
| Microk8s não instalado | idealmente uma máquina onde `snap list microk8s` não retorna nada |
| `sudo` | o install exige root |
| Acesso ao GHCR | **`docker login ghcr.io`** com um PAT com escopo `write:packages` — que você roda, nunca eu peço senha |

## Passo 0 — publicar as imagens próprias no GHCR (PRIMEIRO)

O caminho online **não funciona** enquanto as imagens não estiverem no GHCR.
Já estão buildadas localmente com os nomes certos:

```bash
docker images | grep theseeds
# ghcr.io/theseeds/lakecore-ingest:1.0.0
# ghcr.io/theseeds/lakecore-backup:1.0.0
```

Para publicar (exige login seu):

```bash
docker login ghcr.io          # você, com PAT write:packages
cd datalake-doomsday-env
scripts/build-push-ghcr.sh --push --tag 1.0.0
```

> Confira que o push usa os nomes `lakecore-ingest`/`lakecore-backup` (o script
> foi corrigido para isso — antes gerava `ingest`/`backup`, o que quebraria o
> caminho online).

## Passo 1 — instalar na máquina limpa (com rede)

No repo (clonado ou pelo tar do release):

```bash
# máquina TEM internet
sudo bash install.sh                          # fonte online (padrão)
# ou explícito:
sudo bash install.sh --fonte online --engine standard
```

Espere os 8 passos:

```
1/8 Validando a fonte          → online
2/8 Instalando o snap microk8s → do store
3/8 Cluster Ready
4/8 Preparando as imagens      → "serão puxadas dos registries (online)"
5/8 Habilitando addons
6/8 Instalando o chart         → puxa lakecore do GHCR + infra dos registries
7/8 Layout do Garage
8/8 Migração do catálogo (Alembic)
```

Se o passo 6 falhar por **`ErrImagePull`/`ImagePullBackOff` em
`ghcr.io/theseeds/lakecore-*`**, causa mais provável: imagens não publicadas no
GHCR (volte ao Passo 0) ou PAT sem acesso ao pacote.

## Passo 2 — verificar

```bash
sudo bash verify.sh            # 12 verificações, o mesmo dos dois caminhos
```

Esperado: `12 verificação(ões) ok, 0 falha(s) → RESULTADO: instalação verificada.`

## Passo 3 — registrar o resultado

Ao fechar, registre aqui (substituindo o status do topo) e em
`docs/release.md` (desmarcar a pendência):

```markdown
**Concluído:** 2026-11-XX. Máquina: ____ . `verify.sh` ___/12.
Log anexado quando disponível.
```

## O que NÃO é necessário provar no online

- que a máquina fica **sem** rede — isso é especificidade do offline (já provado);
- idempotência de reinstalar sobre os mesmos dados — não é foco desta rodada;
- hardware físico de 16 GB — é item separado (§14 da arquitetura v2).

## Checklist de encerramento da v1.0.0

- [ ] `docker login ghcr.io` + `scripts/build-push-ghcr.sh --push --tag 1.0.0`
- [ ] instalar online em máquina limpa com rede (**`verify.sh` 12/12**)
- [ ] registrar status acima + desmarcar pendência em `docs/release.md`
- [ ] commit + push (main e dev) do roteiro e da correção de nome do build-push