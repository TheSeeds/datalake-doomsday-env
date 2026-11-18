# Módulo: observability

O primeiro módulo real do lake. Ele existe para provar o **conceito** de módulo
tanto quanto para servir: o `modules/` estava vazio desde a Onda 0, e a §9 do
plano dizia "módulos instaláveis: só depois de haver 1 módulo real". Este é ele.

## O que ele faz

Mostra tendência do lake ao longo do tempo: métricas do PostgreSQL e do Garage,
logs de todos os pods, e — quando o `lakecore` começar a emitir spans — traces do
caminho de ingestão.

**O que ele NÃO faz, e é importante:** ele não responde "meu backup está
funcionando?". Essa pergunta é respondida pela tabela `saude` e por `make
frescor`, que funcionam com este módulo **desligado**. Painel exige alguém
olhando; o frescor não.

## Componentes, e por que são estes quatro

| componente | papel | imagem |
|---|---|---|
| **Grafana** | o painel | 315 MB |
| **Prometheus** | métricas | 116 MB |
| **Loki** | logs | 47 MB |
| **Alloy** | **coleta** (logs + métricas + OTLP) | 225 MB |

**Por que Alloy e não Promtail + OTel Collector:**

`Promtail` chegou a **EOL em 2 de março de 2026** — a doc do Loki diz
literalmente *"No future support or updates will be provided"*. E `Alloy` é a
distribuição do OpenTelemetry Collector mantida pela Grafana: ela faz o que o
Promtail fazia (`loki.source.kubernetes`), o que o OTel Collector fazia
(`otelcol.receiver.otlp`) e o que o Prometheus Agent faria (`prometheus.scrape`).

Ou seja: **dois componentes em um**. A stack que seria de cinco peças é de
quatro, com ~96 MB e ~150 MB de RAM a menos.

## Requisitos

```yaml
requires:
  gpu: none
  ram: 1.5Gi      # soma dos limites, não do uso ocioso (~1,05 GB)
  disk: 12Gi      # métricas e logs com retenção curta
```

No piso do projeto (16 GB RAM) isso é ~9%. Cabe, mas é o maior módulo em RAM —
e por isso ele é **opcional** e desligado por padrão.

## Retenção: o padrão é curto, de propósito

```yaml
prometheus.retention: 15d
prometheus.size: 5Gi
loki.retention: 7d
loki.size: 5Gi
```

Um lake que existe para durar não pode ter um painel que come o disco. Os
números são curtos porque observabilidade serve para **agir agora**, não para
arqueologia. Quem precisar de mais tempo muda aqui, conscientemente.

## Airgap: por que não usamos o addon do microk8s

O addon `observability` do microk8s executa, dentro do `enable`:

```bash
$HELM upgrade --install kube-prom-stack kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts
```

Isso baixa o chart **da internet no momento da instalação**. Num lake sem rede,
o addon não sobe. É o mesmo erro da licença Apache anunciada sem o texto.

Por isso este módulo é vendorizado: os charts vão como `.tgz` no bundle e as
imagens são importadas no containerd (`ctr images import`). O `install.sh` do
módulo usa `--repo` **nunca**.

## Desinstalar não apaga dado do usuário

```yaml
uninstall:
  keeps: [dashboards]
```

Remover o módulo apaga métricas e logs (são derivados do funcionamento, não do
acervo), mas **preserva os dashboards** que o usuário escreveu. A regra vem do
NOMAD e está na §7 da arquitetura: desinstalar módulo não apaga dado do usuário.

O acervo (`raw/`), o catálogo e a tabela `saude` não são tocados em nenhum
momento.
