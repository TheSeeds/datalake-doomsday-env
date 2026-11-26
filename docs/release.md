# Release e versionamento — datalake-doomsday-env

Como promover uma versão, montar o bundle e publicar as imagens próprias.
Aplica-se a partir da **v1.0.0**, que adota **Semantic Versioning**.

## Modelo de versão

`MAJOR.MINOR.PATCH` (SemVer):

- **MAJOR** — quebra de compatibilidade; exigir migração ou re-instalação;
- **MINOR** — nova capacidade, compatível com a anterior;
- **PATCH** — correção, compatível.

Uma release fixa **a mesma versão em todo o sistema**:

| artefato | onde vive |
|---|---|
| tag git | `vM.m.p` |
| `## Estado` + `## Versão` | `README.md` |
| charts `version` / `appVersion` | `charts/*/Chart.yaml` + `Chart.lock` |
| bundle | `dist/datalake-bundle-<M.m.p>/` |
| imagens próprias GHCR | `ghcr.io/theseeds/lakecore-{ingest,backup}:<M.m.p>` |
| imagem default do chart | `charts/**/values.yaml` (`tag`) |

O `install.sh` lê esses caminhos por etapa; o objetivo é que **não exista mais
de uma versão apontada de lugares diferentes** (a fonte de verdade é este
conjunto, promovido junto).

## Passos de uma release

1. **Bump de versão** — atualize `M.m.p` nos `Chart.yaml`/`Chart.lock` de
   `charts/*`, no `module.yaml` do módulo, e no `VERSAO=` de `scripts/bundle.sh`.
   Sincronize a tag da imagem do lakecore em `charts/**/values.yaml`.
2. **Atualize `docs/CHANGELOG.md`** — mova "Unreleased" para a versão nova.
3. **Valide** — `make ci` (e `make ci-full` se possível). Alinhe com o
   repositório de conceito se a arquitetura mudou.
4. **Publique as imagens próprias (GHCR)**:
   ```bash
   docker login ghcr.io              # PAT com write:packages (você executa)
   scripts/build-push-ghcr.sh --push --tag <M.m.p>
   ```
   `lakecore-ingest` e `lakecore-backup` — apenas imagem de build, **sem segredo
   de negócio** no artefato.
5. **Monte o bundle (para o caminho offline)**:
   ```bash
   scripts/bundle.sh --apply --versao <M.m.p>
   # dist/datalake-bundle-<M.m.p>/  (snaps, imagens, charts, scripts, SHA256SUMS)
   ```
6. **Commit + tag + push**:
   ```bash
   make ci-check
   git add -A && git commit
   git tag v<M.m.p>
   git push && git push --tags
   ```

## Publicar imagens no GHCR

Só as duas imagens **próprias** são publicadas — o resto da infra já vem de
registries públicos. `scripts/build-push-ghcr.sh`:

```bash
scripts/build-push-ghcr.sh                    # build local (sem push) — dry-run
scripts/build-push-ghcr.sh --push --tag 1.0.0 # build + push em ghcr.io/theseeds
```

> Push exige autenticação. Este repositório não guarda credencial; o comando
> `docker login ghcr.io` é executado por você (regra de privilégio/segredo).

## Caminho online — pendência do release v1.0.0

O caminho **offline** está homologado (VM Ubuntu 24.04 sem rede, 12/12). O
caminho **online** (o mesmo `install.sh` com `--fonte online`) **ainda não foi
homologado** numa máquina limpa com internet. Antes de declarar v1.0.0 "fechada":

- [ ] subir uma VM/máquina limpa com rede;
- [ ] `sudo bash install.sh && sudo bash verify.sh` (fonte online);
- [ ] registrar o resultado em `docs/homologacao/`.

Este é o único critério de pronto do release que permanece aberto.

## Build do bundle (detalhe)

```bash
scripts/bundle.sh            # dry-run: mostra conteúdo e tamanho estimado
scripts/bundle.sh --apply    # monta dist/datalake-bundle-<versão>/
```

O bundle **não leva o acervo** (`raw/` é do usuário) nem credenciais. Cada
tarball de imagem é gerado amd64-only (um por imagem) para que o import offline
não falhe em manifest multi-plataforma — lições embutidas do `bundle.sh`.