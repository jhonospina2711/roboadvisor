import os
import re
import threading
from datetime import datetime, timezone
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from davivienda_chat_qa import Document, USER_AGENT, answer_question, build_corpus


DEFAULT_MODEL = os.getenv("LOCAL_MODEL", "gemma4-financiero")
DEFAULT_MAX_PAGES = int(os.getenv("QA_MAX_PAGES", "20"))
DEFAULT_TOP_K = int(os.getenv("QA_TOP_K", "4"))


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Pregunta del cliente")
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=10)
    model: str = Field(DEFAULT_MODEL)


class AskResponse(BaseModel):
    answer: str
    sources: List[str]
    model: str
    indexed_pages: int


class ReindexRequest(BaseModel):
    max_pages: int = Field(DEFAULT_MAX_PAGES, ge=1, le=100)


class ReindexResponse(BaseModel):
    indexed_pages: int
    indexed_at: str


class ServiceState:
    def __init__(self) -> None:
        self.docs: List[Document] = []
        self.indexed_at: Optional[datetime] = None
        self.lock = threading.Lock()


state = ServiceState()
app = FastAPI(
    title="Davivienda Corredores Q&A API",
    version="1.0.0",
    description="API de preguntas y respuestas basada en scraping + Gemma local",
)


def _build_docs(max_pages: int) -> List[Document]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return build_corpus(session=session, max_pages=max_pages)


def _extract_sources(answer: str) -> List[str]:
    sources = re.findall(r"https?://[^\s)]+", answer)
    return list(dict.fromkeys(sources))


def _refresh_index(max_pages: int) -> int:
    docs = _build_docs(max_pages=max_pages)
    if not docs:
        return 0

    with state.lock:
        state.docs = docs
        state.indexed_at = datetime.now(timezone.utc)
    return len(docs)


@app.on_event("startup")
def startup_event() -> None:
    _refresh_index(max_pages=DEFAULT_MAX_PAGES)


@app.get("/health")
def health() -> dict:
    with state.lock:
        indexed_pages = len(state.docs)
        indexed_at = state.indexed_at.isoformat() if state.indexed_at else None

    return {
        "status": "ok",
        "indexed_pages": indexed_pages,
        "indexed_at": indexed_at,
        "default_model": DEFAULT_MODEL,
    }


@app.get("/debug/index")
def debug_index(limit: int = 20) -> dict:
    with state.lock:
        docs = list(state.docs)

    safe_limit = max(1, min(limit, 200))
    items = [{"url": d.url, "title": d.title} for d in docs[:safe_limit]]

    return {
        "indexed_pages": len(docs),
        "items": items,
    }


@app.post("/reindex", response_model=ReindexResponse)
def reindex(payload: ReindexRequest) -> ReindexResponse:
    indexed_pages = _refresh_index(max_pages=payload.max_pages)
    if not indexed_pages:
        raise HTTPException(status_code=502, detail="No se pudo indexar contenido del sitio")

    with state.lock:
        indexed_at = state.indexed_at.isoformat()

    return ReindexResponse(indexed_pages=indexed_pages, indexed_at=indexed_at)


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    with state.lock:
        docs = list(state.docs)

    # Autorecupera el índice si quedó demasiado corto por fallas temporales del sitemap.
    if len(docs) < 3:
        refreshed = _refresh_index(max_pages=DEFAULT_MAX_PAGES)
        if refreshed:
            with state.lock:
                docs = list(state.docs)

    if not docs:
        return AskResponse(
            answer=(
                "No fue posible responder en este momento porque el indice esta vacio. "
                "El sitio objetivo esta devolviendo una pagina de proteccion anti-bot. "
                "Intenta ejecutar /reindex de nuevo en unos minutos."
            ),
            sources=[],
            model=payload.model,
            indexed_pages=0,
        )

    answer = answer_question(
        question=payload.question,
        docs=docs,
        model=payload.model,
        top_k=payload.top_k,
    )

    sources = _extract_sources(answer)

    return AskResponse(
        answer=answer,
        sources=sources,
        model=payload.model,
        indexed_pages=len(docs),
    )
