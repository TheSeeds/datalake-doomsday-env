"""`ingest-api` — porta HTTP de entrada do lake.

Um único primitivo (`upload`) com dois gatilhos: HTTP (este serviço) e varredura
de `drop/` (Job). Ambos chamam `lakecore.ingest()` — uma implementação, dois
caminhos. Se a lógica estiver duplicada aqui, o desenho está errado.

Decisões que não são de estilo:

- **`ingest` não lê `raw/`.** O cliente S3 é construído com credencial
  write-only; a porta do domínio nem oferece `get`.
- **`/health` não expõe segredo.** Reporta endpoint e região, nunca chave.
- **Upload tem limite explícito.** Um endpoint que aceita qualquer tamanho é um
  vetor de esgotamento de disco.
- **Idempotência é por `sha256`, não por nome.** Reenviar o mesmo arquivo é
  sucesso com `duplicate=true`, não erro.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lakecore.adapters.s3_store import config_extra, from_env
from lakecore.db.catalog import SqlCatalog
from lakecore.db.models import Base
from lakecore.fakes import FixedClock
from lakecore.ingestion import ingest
from lakecore.layout import raw_key
from lakecore.models import IngestRequest, ObjectRef, Record
from lakecore.ports import Clock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

log = logging.getLogger(__name__)

#: Limite por upload. 64 MiB cabe num corpo HTTP sem buffer em disco e é ordem de
#: grandeza suficiente para documento/log/foto. Arquivo maior vai por `drop/`.
TAMANHO_MAXIMO_UPLOAD = 64 * 1024 * 1024

app = FastAPI(title="lakecore ingest-api", version="0.1.0")

_state: dict[str, object] = {}


class UploadResponse(BaseModel):
    sha256: str
    key: str
    size: int
    duplicate: bool
    origem: str


class ClockSistema:
    """Relógio real. Nos testes usa-se `FixedClock`."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _montar() -> None:
    """Inicializa dependências. Chamado no startup, não no import.

    Import não deve abrir conexão: isso torna o módulo inutilizável em teste e
    faz o pod falhar no `import` em vez de falhar no `startup` com log claro.
    """
    url = os.environ.get("LAKECORE_DATABASE_URL")
    if not url:
        raise RuntimeError("LAKECORE_DATABASE_URL não definida")

    engine = create_engine(url, future=True, pool_pre_ping=True)
    _state["engine"] = engine
    _state["catalog"] = SqlCatalog(sessionmaker(bind=engine, expire_on_commit=False))
    _state["store"] = from_env(dict(os.environ))
    _state["clock"] = ClockSistema()
    log.info("ingest-api pronta", extra=config_extra(dict(os.environ)))


@app.on_event("startup")
def startup() -> None:
    _montar()


@app.on_event("shutdown")
def shutdown() -> None:
    engine = _state.get("engine")
    if engine is not None:
        engine.dispose()  # type: ignore[attr-defined]


@app.get("/health")
def health() -> dict[str, object]:
    """Verifica as duas dependências de verdade.

    Não devolve "ok" só porque o processo subiu: se o banco não responder, isto
    falha. Foi o erro do `pg_isready` na Onda 3 — probe que passa sem testar nada.

    `frescor` é o que a Onda 6 provou faltar: saber que o processo está de pé não
    diz que o backup rodou. O campo é informativo neste endpoint (liveness do
    serviço); quem decide se o lake está saudável é `saude.resumo`, e ele está
    exposto em `/frescor` com o código HTTP correspondente.
    """
    saude: dict[str, object] = {
        "service": "ingest-api",
        "s3": config_extra(dict(os.environ)),
    }

    engine = _state.get("engine")
    if engine is None:
        raise HTTPException(status_code=503, detail="não inicializado")

    from sqlalchemy import text

    with engine.connect() as conn:  # type: ignore[attr-defined]
        conn.execute(text("SELECT 1"))

    saude["catalogo"] = "ok"

    # Frescor entra como Informação, não como gate: um backup atrasado não deve
    # reiniciar o pod de ingestão. `/frescor` é o endpoint de gate.
    try:
        from lakecore.saude import resumo

        _, sinais = resumo(engine)  # type: ignore[arg-type]
        saude["frescor"] = {s.sinal: s.estado for s in sinais}
    except Exception as e:  # noqa: BLE001 - não derruba o health por isso
        log.warning("não consegui ler o frescor: %s", e)
        saude["frescor"] = {"_erro": "tabela saude indisponível"}

    return saude


@app.get("/frescor", status_code=200)
def frescor() -> JSONResponse:
    """Gate de frescor: 200 se tudo fresco, 503 se algo está velho ou quebrado.

    POR QUE 503 E NÃO 200 COM `ok: false`: um endpoint que devolve 200 para um
    lake quebrado não é monitorável — Prometheus, curl e kubelet leem o código.
    A resposta confortável de `200` é o mesmo defeito do `pg_isready`.
    """
    engine = _state.get("engine")
    if engine is None:
        return JSONResponse(status_code=503, content={"erro": "não inicializado"})

    from lakecore.saude import resumo

    tudo_ok, sinais = resumo(engine)  # type: ignore[arg-type]
    corpo = {
        "ok": tudo_ok,
        "sinais": [
            {
                "sinal": s.sinal,
                "estado": s.estado,
                "ultimo_sucesso": s.ultimo_sucesso.isoformat() if s.ultimo_sucesso else None,
                "ultima_falha": s.ultima_falha.isoformat() if s.ultima_falha else None,
                "detalhe": s.detalhe,
            }
            for s in sinais
        ],
    }
    return JSONResponse(status_code=200 if tudo_ok else 503, content=corpo)


@app.post("/uploads", response_model=UploadResponse, status_code=201)
async def upload(
    arquivo: UploadFile = File(...),
    origem: str = Form(...),
    tipo: str | None = Form(default=None),
) -> UploadResponse | JSONResponse:
    """Ingere um arquivo.

    Duplicado **não** é erro: devolve 201 com `duplicate=true` e a chave do
    objeto que já estava lá. A porta HTTP não deve punir quem reenvia.
    """
    if not origem.strip():
        raise HTTPException(status_code=422, detail="origem é obrigatória")

    dados = await arquivo.read()
    if len(dados) > TAMANHO_MAXIMO_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"arquivo excede {TAMANHO_MAXIMO_UPLOAD} bytes; use drop/",
        )

    # `ingest()` espera caminho em disco, porque o domínio resolve arquivo local
    # (o caso do `drop/`). Para HTTP o conteúdo já está em memória: grava em
    # temporário e reusa a MESMA função — duplicar a lógica aqui seria o erro que
    # a Onda 4 existe para evitar.
    import tempfile
    from pathlib import Path

    sufixo = Path(arquivo.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(suffix=sufixo) as tmp:
        tmp.write(dados)
        tmp.flush()

        resultado = ingest(
            IngestRequest(
                path=tmp.name,
                origem=origem,
                tipo=tipo,
                metadados={"nome_original": arquivo.filename or "upload.bin"},
            ),
            store=_state["store"],  # type: ignore[arg-type]
            catalog=_state["catalog"],  # type: ignore[arg-type]
            clock=_state["clock"],  # type: ignore[arg-type]
            tamanho_maximo=TAMANHO_MAXIMO_UPLOAD,
        )

    return UploadResponse(
        sha256=resultado.record.sha256,
        key=resultado.record.key,
        size=resultado.record.size,
        duplicate=resultado.duplicate,
        origem=resultado.record.origem,
    )


@app.get("/objects/{sha256}")
def obter_metadados(sha256: str) -> dict[str, object]:
    """Metadados do catálogo por hash. **Não** devolve o conteúdo.

    Ler o byte é o que a chave de `ingest` não permite — e é o ponto do ADR-011.
    """
    catalog: SqlCatalog = _state["catalog"]  # type: ignore[assignment]
    registro = catalog.by_sha256(sha256)
    if registro is None:
        raise HTTPException(status_code=404, detail="objeto não catalogado")
    return _serializar(registro)


def _serializar(registro: Record) -> dict[str, object]:
    return {
        "sha256": registro.sha256,
        "bucket": registro.bucket,
        "key": registro.key,
        "size": registro.size,
        "content_type": registro.content_type,
        "origem": registro.origem,
        "tipo": registro.tipo,
        "coletado_em": registro.coletado_em.isoformat(),
        "metadados": registro.metadados,
    }
