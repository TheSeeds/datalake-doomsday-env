# datalake-doomsday-env

O **ambiente instalável** do [datalake-doomsday](https://github.com/TheSeeds/datalake-doomsday).

Este repositório é o artefato: charts, distro, scripts de instalação, bundle offline
e o núcleo de domínio (`lakecore`). O *modelo conceitual* — visão, arquitetura,
decisões e plano de atividades — vive no repositório de conceito.

> **Separação deliberada:** conceito muda quando o pensamento muda; ambiente muda
> quando o código muda e precisa de tag, digest e release. Misturar os dois faz
> toda edição de texto aparecer como diff ao lado de mudança de chart, e o bundle
> precisa fixar um commit de si mesmo.

| repositório | contém | ciclo |
|---|---|---|
| `datalake-doomsday` | visão, arquitetura, decisões, plano | quando o desenho muda |
| **`datalake-doomsday-env`** (este) | charts, distro, scripts, `lakecore`, bundle | quando o código muda |

## Estado

**Onda 0 — estrutura e contrato de CI.** Não há infraestrutura, cluster ou
ingestão funcional aqui ainda. O que existe:

- `src/lakecore/` — contrato do núcleo de domínio (tipos + portas). Sem I/O.
- `profiles/`, `charts/`, `modules/`, `scripts/`, `seed/`, `deploy/` — vazios, aguardando as ondas seguintes.
- `.github/workflows/ci.yml` — CI que precisa ficar verde **antes** de existir código.

O plano completo, com as ondas 0–7 e o critério de pronto de cada uma, está em
[`docs/plano-atividades.md`](docs/plano-atividades.md).

## Validação

```bash
make ci        # não requer cluster, não requer rede
```

`make ci` roda sem Kubernetes, sem Garage e sem PostgreSQL. Isso é intencional:
as ondas 0–2 rodam com o cluster desligado, porque o valor do projeto está no
catálogo, não no orquestrador.

Requisitos de desenvolvimento: Python 3.11+, e `microk8s` (o `helm` vem de
`microk8s helm3`). `shellcheck` e `yamllint` são instalados pelo `make setup`.

## Licença

Apache 2.0. Ver [`LICENSE`](LICENSE).
