# Imagem do lakecore: ingest-api + CLI.
#
# Multi-stage: o builder instala dependências, a imagem final copia só o
# necessário. `--no-compile` no pip reduz ~40% e elimina `.pyc` que não servem em
# runtime de produção (o pyc é gerado na primeira execução, em cache fora da imagem).
#
# Usuário não-root: um lake que armazena dado heterogêneo não pode rodar como root
# no cluster.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-compile --prefix=/install -r requirements.txt


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

RUN groupadd --gid 10001 lakecore \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin lakecore

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src/ ./src/

USER 10001:10001

EXPOSE 8080

# `exec form` para que SIGTERM chegue ao processo: o uvicorn precisa desligar
# limpo, senão upload em curso vira objeto órfão no storage sem linha no catálogo.
ENTRYPOINT ["python", "-m", "uvicorn", "lakecore.api.main:app"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
