# Changelog — datalake-doomsday-env

As releases seguem Semantic Versioning (ver [`docs/release.md`](release.md)).
O formato é [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [1.0.0] — 2026-11-XX (planejado)

Primeira versão estável. Encerra a fase 1 (v0.1-beta) e adota SemVer.

### Adicionado

- **Caminho online de instalação** — `install.sh --fonte online`: o mesmo
  instalador passa a funcionar em máquina com internet (microk8s do store,
  imagens próprias do GHCR `ghcr.io/theseeds/lakecore-*`, registries públicos).
  O offline (bundle) permanece como caminho homologado.
- **`scripts/build-push-ghcr.sh`** — build e publicação das imagens próprias
  (`lakecore-ingest`, `lakecore-backup`) no GHCR, por release.
- **`scripts/migrar-catalogo.sh`** — migração Alembic do catálogo como passo
  próprio do install, resolvendo o P1 da Onda 7 (tabelas não criadas em
  instalação limpa).
- **`docs/release.md` / `docs/CHANGELOG.md`** — processo de versionamento e
  release.

### Corrigido

- Em instalação limpa, as tabelas `objects`/`uploads`/`saude` agora são criadas
  pela migração rodada no install (antes só manualmente no pod).
- `bundle.sh`/`install.sh` passam a gerar e consumir o bundle com versão
  parametrizada (`datalake-bundle-<versão>`).

### Alterado

- Charts (`datalake`, `garage`, `postgresql`, `ingest`), o módulo
  `observability` e as imagens próprias alinhados a `1.0.0`.
- `install.sh` reestruturado nos passos `1..8` (inclui a migração) e com a opção
  `--fonte`.

## Onda 7 — bundle offline homologado (2026-11-25)

Estado em `docs/homologacao/onda7-tentativa4/RELATORIO.md`. `install.sh &&
verify.sh` verdes (12/12) numa VM Ubuntu 24.04 sem rede.