"""Adiciona `saude`: o sinal de frescor do lake.

POR QUE ESTA TABELA EXISTE, E POR QUE ELA VEM ANTES DO GRAFANA:

em 2026-11-18 descobrimos que o CronJob de backup falhava em 100% das execuções
havia horas. A informação estava **visível** — `kubectl get jobs` mostrava
`Failed` — e ninguém olhou. O problema não era falta de métrica: era falta de
uma resposta pronta para a única pergunta que alguém faz de verdade, que é
"meu backup está funcionando?".

Um painel de Grafana responde tendência, e tendência exige alguém olhando. Esta
tabela responde o **estado**: quando foi a última vez que algo deu certo, e
quando foi a última vez que deu errado. Ela funciona com a stack de
observabilidade inteira desligada, e é consultável pelo `lake_estado` que já
existe.

DECISÕES DE SCHEMA:

- **Uma linha por tipo de sinal**, chaveada por `sinal`, não uma estrutura
  genérica. "last_success do backup" é uma pergunta concreta; um schema de
  chave-valor arbitrário evita a decisão hoje e a cobra depois.
- **`ultimo_sucesso` e `ultima_falha` separados, e não só um `status`.** Um
  backup que falhou ontem e funcionou hoje é diferente de um que nunca
  funcionou; o booleano achata os dois e o primeiro é o caso normal.
- **`detalhe` em texto livre**, porque a mensagem de erro é o que faz alguém
  agir. Guardar só "failed" obriga a caçar o log de um pod que já foi apagado.
- **Sem FK e sem histórico.** O histórico é o que o Prometheus vai guardar; aqui
  só o retrato do agora. Duas fontes de verdade para tendência divergiriam.

`server_default` nos instantes porque a tabela pode já estar populada no dia em
que a migração rodar num lake em uso — a lição da migração `8b1f2c3d4e5a`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d9e1a7b203"
down_revision = "8b1f2c3d4e5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saude",
        sa.Column("sinal", sa.String(length=64), primary_key=True),
        sa.Column("ultimo_sucesso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_falha", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_ok", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_falha", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("detalhe", sa.Text(), nullable=True),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("total_ok >= 0", name="ck_saude_total_ok_nao_negativo"),
        sa.CheckConstraint("total_falha >= 0", name="ck_saude_total_falha_nao_negativo"),
    )


def downgrade() -> None:
    op.drop_table("saude")
