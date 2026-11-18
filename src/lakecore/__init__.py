"""Núcleo de domínio do datalake-doomsday.

Este pacote é o coração do projeto e a única parte que precisa estar certa.
Ele **não** sabe o que é HTTP, S3, PostgreSQL ou Kubernetes: recebe um caminho
e devolve um `Record`. Todo o resto (API, Job, chart) é encanamento em volta.

Ver `docs/plano-atividades.md`, Onda 1.
"""

from lakecore.errors import (
    DuplicateObjectError,
    IngestError,
    IntegrityMismatchError,
    UnsupportedObjectError,
)
from lakecore.ingestion import IngestResult, classify, hash_file, ingest
from lakecore.layout import raw_key
from lakecore.models import IngestRequest, ObjectRef, Record, UploadBatch, UploadState
from lakecore.ports import Catalog, Clock, ObjectStore

__all__ = [
    "Catalog",
    "Clock",
    "DuplicateObjectError",
    "IngestError",
    "IngestRequest",
    "IngestResult",
    "IntegrityMismatchError",
    "ObjectRef",
    "ObjectStore",
    "Record",
    "UnsupportedObjectError",
    "UploadBatch",
    "UploadState",
    "classify",
    "hash_file",
    "ingest",
    "raw_key",
]
