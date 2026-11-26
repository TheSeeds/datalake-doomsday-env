# Manual de Instalação — datalake-doomsday

Instala o lake por dois caminhos, através do mesmo `install.sh`:

- **Online** (máquina **com** internet): `sudo bash install.sh` (padrão). Usa o
  microk8s do store, as imagens próprias do GHCR (`ghcr.io/theseeds/lakecore-*`)
  e os registries públicos.
- **Offline** (máquina **sem** rede): `sudo bash install.sh --fonte offline`, a
  partir do bundle de `make bundle`. Snaps, imagens e charts vêm do artefato,
  verificados por checksum.

Ambos convergem no mesmo `verify.sh` (12 verificações). Este manual detalha o
**offline** (caminho homologado em VM Ubuntu 24.04 sem rede); o **online** é o
mesmo fluxo sem a etapa do bundle, e ainda não foi homologado numa máquina limpa
com rede (ver `docs/release.md`).

> Build do bundle e publicação das imagens GHCR: [`docs/release.md`](release.md).

## Pré-requisitos

| Requisito | Valor |
|---|---|
| SO | Ubuntu 24.04 (x86_64) |
| RAM | mín. 8 GB (engine `micro`) / 16 GB (engine `standard`) |
| Disco | mín. 30 GB livres |
| Acesso | root (o install.sh confere EUID) |

O bundle é auto-suficiente: contém snaps, imagens OCI, charts, scripts e
checksums. **Não baixa nada da rede.**

## Obter o bundle

Numa máquina COM rede (máquina de desenvolvimento):

```bash
git clone <repo-datalake-doomsday-env>
cd datalake-doomsday-env
scripts/bundle.sh --apply
# cria dist/datalake-bundle-<versão>/ (ex.: 1.0.0)
```

Transfira a pasta `dist/datalake-bundle-<versão>/` para a máquina de destino
(pendrive, disco externo). Preserve permissões (o install.sh roda como root).
A versão do bundle é a do release (ver `docs/release.md`); o caminho `--fonte
online` não usa bundle.

## Instalar na máquina de destino (SEM rede)

```bash
# desligue a rede para provar o offline (opcional, recomendado na homologação)
sudo ip link set <iface> down

cd /caminho/para/datalake-bundle-<versão>
sudo bash install.sh --fonte offline --engine standard
```

Parâmetros:

| Flag | Efeito |
|---|---|
| `--fonte online` (padrão) | instala usando internet (microk8s do store, GHCR, registries públicos) |
| `--fonte offline` | instala a partir do bundle (sem rede) |
| `--engine micro` | postgresql com shared_buffers reduzido (16 GB RAM) |
| `--engine standard` | postgresql padrão (32 GB RAM) |
| `--with-observability` | instala também Prometheus/Grafana/Loki/Alloy |
| `--dry-run` | mostra os passos sem executar |

O install.sh é **idempotente**: rodar de novo não corrompe o instalado.

O que o script faz, na ordem (as etapas 4/6/8 variam com a fonte):

1. **Valida a fonte** — offline: `sha256sum -c SHA256SUMS` antes de tocar no
   sistema (bundle corrompido ⇒ aborta com "não instale"); online: confirma que
   snaps/registries/GHCR estarão disponíveis.
2. **Instala o microk8s** — online: do snap store; offline: snap local
   (`--classic --dangerous`), com o snapd primeiro e espera do restart (correção
   de 2026-11-19: instalar durante o restart fazia o hook do microk8s ser
   ignorado).
3. **Garante o cluster inicializado** — se o hook não rodou, `microk8s start`
   explícito; espera a API responder (teste real, não `snap list`).
4. **Prepara as imagens** — offline: importa `images/*.tar` no containerd (permite
   `imagePullPolicy: Never`); online: nada a importar (o kubelet puxa do GHCR +
   registries).
5. **Habilita addons** — dns, hostpath-storage, helm3.
6. **Instala o chart** — namespace `lake-data`, com `--wait --timeout 10m`; os
   overrides de imagem do lakecore vêm da fonte (curto/`Never` offline,
   GHCR/`IfNotPresent` online).
7. **Aplica o layout do Garage** (assign + apply).
8. **Roda a migração do catálogo (Alembic)** — `scripts/migrar-catalogo.sh`, um
   Job que aplica `upgrade head` (P1 da Onda 7 corrigido; idempotente).

## Verificar

```bash
sudo bash verify.sh
```

12 verificações. Todas verdes ⇒ instalação ok:

```
== 1. Cluster            → nó Ready
== 2. Pods do lake       → garage, postgresql, ingest prontos
== 3. Catálogo           → SELECT 1 autenticado + count(objects)
== 4. Garage             → /var/lib/garage/data com conteúdo
== 5. Ingestão           → POST /health 200; upload duplicate=false; reenvio duplicate=true
== 6. Backup             → tabela saude com último backup bem-sucedido
== 7. Frescor            → rotina(s) com ultimo_sucesso registrado
```

`sudo bash verify.sh --rapido` pula o teste de disco do Garage.

## Acessar

- **Ingestão (HTTP)**: `kubectl -n lake-data port-forward svc/ingest 8080:8080`
  - `POST /uploads` com `-F arquivo=@... -F origem=... -F tipo=...`
  - `GET /health` → 200
  - `GET /objects/{sha256}` → metadados
- **PostgreSQL**: `kubectl -n lake-data exec postgresql-0 -- psql -U lakecore -d lakecore`
- **Chat**: `scripts/conectar-chat.sh` (usa `lakecore.mcp`, MCP no host)

## Reverter

```bash
microk8s helm3 uninstall datalake -n lake-data
sudo snap remove microk8s        # apaga TUDO, inclusive /var/lib/garage
```

## Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| `cannot install system snap snapd: ... context deadline exceeded` | snapd tentou atualizar on-line; sem rede morre | bundle deve conter `snapd.snap`; se faltar, refazer bundle |
| `cluster não ficou Ready em 5 min` | hook do snap foi ignorado (restart do snapd) | rodar install.sh de novo (o passo 2b/7 faz `microk8s start`) |
| pods com `ErrImageNeverPull` | imagens não importadas | `microk8s ctr images import images/*.tar` |
| `certificate ... x509` ao usar `kubectl exec/logs` | CA do apiserver com IP antigo | refresh-certs (não resolve key usage); documentado em `docs/requisitos-sudo.md` |
| PVC `Pending` | hostpath-storage sem default-class | `microk8s enable hostpath-storage` |
