"""Agent knowledge: documents split into chunks, embedded, and searched.

With an embedding model configured (Settings > Knowledge search), search is semantic: on
Postgres with the pgvector extension it runs in the database, otherwise cosine similarity is
computed here over the stored vectors. Without one, or for documents not yet embedded with
the current model, search falls back to keywords (Postgres full-text, or term overlap on
SQLite).
"""

import asyncio
import logging
import math
import re
from typing import Any

from sqlalchemy import bindparam, text
from sqlmodel import delete, select

from app.config import get_settings
from app.db import KnowledgeChunk, KnowledgeDoc, get_engine, session
from app.events.schema import utcnow
from app.llm.router import provider_kwargs, provider_of

log = logging.getLogger(__name__)

CHUNK_CHARS = 1200
OVERLAP_CHARS = 150
EMBED_BATCH = 64

_vector_ready = False


# --- chunking ---------------------------------------------------------------------------------


def chunk_text(content: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Pack paragraphs into chunks of about `size` characters; split oversized paragraphs
    with a little overlap so a sentence cut at a boundary still appears whole once."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            chunks.append(para[:cut].strip())
            para = para[max(cut - overlap, 0):].strip()
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


# --- embeddings -------------------------------------------------------------------------------


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed with the configured model through LiteLLM. Raises if none is configured."""
    import litellm

    settings = get_settings()
    model = settings.embedding_model.strip()
    if not model:
        raise RuntimeError("no embedding model configured")
    provider, _ = provider_of(model)
    litellm.telemetry = False
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        response = await litellm.aembedding(model=model, input=texts[i:i + EMBED_BATCH],
                                            timeout=120, **provider_kwargs(settings, provider))
        vectors += [list(map(float, d["embedding"])) for d in response.data]
    return vectors


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --- pgvector (optional) ----------------------------------------------------------------------


def ensure_vector() -> bool:
    """Enable pgvector when the Postgres server has it; add and backfill the vector column.

    Safe to call at every startup. Returns whether in-database vector search is available.
    """
    global _vector_ready
    _vector_ready = False
    if not get_settings().is_postgres:
        return False
    try:
        with get_engine().begin() as conn:
            available = conn.execute(text(
                "select 1 from pg_available_extensions where name = 'vector'")).first()
            if not available:
                log.info("pgvector is not installed on this Postgres server; knowledge "
                         "similarity is computed in the app (use the pgvector/pgvector image "
                         "to search in the database)")
                return False
            conn.execute(text("create extension if not exists vector"))
            conn.execute(text("alter table knowledge_chunk "
                              "add column if not exists embedding_vec vector"))
            conn.execute(text("update knowledge_chunk set embedding_vec = "
                              "cast(embedding::text as vector) "
                              "where embedding is not null and embedding_vec is null"))
    except Exception:
        log.exception("could not enable pgvector; falling back to in-app similarity")
        return False
    _vector_ready = True
    return True


def vector_ready() -> bool:
    return _vector_ready


# --- indexing ---------------------------------------------------------------------------------


async def index_doc(doc_id: str) -> KnowledgeDoc | None:
    """(Re)build a document's chunks, embedding them when a model is configured. Keyword
    search works even if embedding fails; the error is kept on the document."""
    with session() as s:
        doc = s.get(KnowledgeDoc, doc_id)
    if doc is None:
        return None
    chunks = chunk_text(doc.content)
    model = get_settings().embedding_model.strip()
    vectors: list[list[float]] | None = None
    error = ""
    if model and chunks:
        try:
            vectors = await embed(chunks)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:500]
            log.warning("embedding %s failed: %s", doc_id, error)
    await asyncio.to_thread(_store_chunks, doc_id, chunks, vectors,
                            model if vectors else "", error)
    with session() as s:
        return s.get(KnowledgeDoc, doc_id)


def _store_chunks(doc_id: str, chunks: list[str], vectors: list[list[float]] | None,
                  model: str, error: str) -> None:
    with session() as s:
        s.exec(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
        for i, chunk in enumerate(chunks):
            s.add(KnowledgeChunk(doc_id=doc_id, ord=i, content=chunk,
                                 embedding=vectors[i] if vectors else None))
        doc = s.get(KnowledgeDoc, doc_id)
        if doc:
            doc.embedding_model, doc.index_error, doc.indexed_at = model, error, utcnow()
            s.add(doc)
        s.commit()
    if _vector_ready and vectors:
        with get_engine().begin() as conn:
            conn.execute(text("update knowledge_chunk set embedding_vec = "
                              "cast(embedding::text as vector) where doc_id = :d"), {"d": doc_id})


async def reindex_all(only_stale: bool = True) -> int:
    """Re-embed documents whose index doesn't match the current embedding model."""
    model = get_settings().embedding_model.strip()
    with session() as s:
        docs = s.exec(select(KnowledgeDoc)).all()
    stale = [d.id for d in docs
             if not only_stale or d.embedding_model != model or d.indexed_at is None]
    for doc_id in stale:
        await index_doc(doc_id)
    if stale:
        log.info("re-indexed %d knowledge documents", len(stale))
    return len(stale)


# --- search -----------------------------------------------------------------------------------


async def search(query: str, doc_ids: list[str], k: int = 5) -> dict[str, Any]:
    """Best-matching chunks from the given documents: {"mode", "results": [...]}."""
    if not doc_ids or not query.strip():
        return {"mode": "none", "results": []}
    model = get_settings().embedding_model.strip()
    if model:
        try:
            qv = (await embed([query]))[0]
            hits = await asyncio.to_thread(_semantic, qv, model, doc_ids, k)
            if hits:
                return {"mode": "semantic", "results": hits}
        except Exception as e:
            log.warning("semantic search failed, using keywords: %s", e)
    return {"mode": "keyword", "results": await asyncio.to_thread(_keyword, query, doc_ids, k)}


def _titles(doc_ids: list[str]) -> dict[str, str]:
    with session() as s:
        return {d.id: d.title for d in s.exec(select(KnowledgeDoc)
                                               .where(KnowledgeDoc.id.in_(doc_ids)))}


def _hit(doc_id: str, titles: dict[str, str], content: str, score: float) -> dict[str, Any]:
    return {"doc_id": doc_id, "title": titles.get(doc_id, doc_id), "content": content,
            "score": round(float(score), 4)}


def _semantic(qv: list[float], model: str, doc_ids: list[str], k: int) -> list[dict]:
    titles = _titles(doc_ids)
    if _vector_ready:
        sql = text(
            "select c.doc_id, c.content, 1 - (c.embedding_vec <=> cast(:q as vector)) as score "
            "from knowledge_chunk c join knowledge_doc d on d.id = c.doc_id "
            "where c.doc_id in :ids and d.embedding_model = :m and c.embedding_vec is not null "
            "and vector_dims(c.embedding_vec) = :dims "
            "order by c.embedding_vec <=> cast(:q as vector) limit :k"
        ).bindparams(bindparam("ids", expanding=True))
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"q": str(qv), "ids": doc_ids, "m": model,
                                      "dims": len(qv), "k": k}).all()
        return [_hit(r.doc_id, titles, r.content, r.score) for r in rows]
    with session() as s:
        chunks = s.exec(
            select(KnowledgeChunk).join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
            .where(KnowledgeChunk.doc_id.in_(doc_ids), KnowledgeDoc.embedding_model == model)
        ).all()
    scored = sorted(((cosine(qv, c.embedding), c) for c in chunks if c.embedding),
                    key=lambda x: x[0], reverse=True)[:k]
    return [_hit(c.doc_id, titles, c.content, score) for score, c in scored]


_WORD = re.compile(r"[a-z0-9]{2,}")


def _keyword(query: str, doc_ids: list[str], k: int) -> list[dict]:
    titles = _titles(doc_ids)
    if get_settings().is_postgres:
        sql = text(
            "select doc_id, content, ts_rank(to_tsvector('english', content), q) as score "
            "from knowledge_chunk, websearch_to_tsquery('english', :query) q "
            "where doc_id in :ids and to_tsvector('english', content) @@ q "
            "order by score desc limit :k"
        ).bindparams(bindparam("ids", expanding=True))
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"query": query, "ids": doc_ids, "k": k}).all()
        if rows:
            return [_hit(r.doc_id, titles, r.content, r.score) for r in rows]
    # Term overlap: SQLite, or Postgres when full-text found nothing (e.g. all stop words).
    terms = set(_WORD.findall(query.lower()))
    with session() as s:
        chunks = s.exec(select(KnowledgeChunk).where(KnowledgeChunk.doc_id.in_(doc_ids))).all()
    scored = []
    for c in chunks:
        words = _WORD.findall(c.content.lower())
        if hits := sum(w in terms for w in words):
            scored.append((hits / math.sqrt(len(words)), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_hit(c.doc_id, titles, c.content, score) for score, c in scored[:k]]
