"""Per-client research kept in the Knowledge library, shared by every agent.

Docs are ordinary knowledge documents titled "<Client> · <Kind>" or "<Client> · <Kind> ·
<Subject>", e.g. "VAIO · Reader Profile · IT Director" or "VAIO · Proof Bank". Any agent with
the client library tools can find them by client name, whether or not they are attached to it.
Saving is a write tool, so a person approves each save first.
"""

from typing import Any

from sqlmodel import select

from app import knowledge
from app.db import KnowledgeDoc, audit, session
from app.events.schema import utcnow

SEP = " · "
KINDS = ("Reader Profile", "Moment Library", "Proof Bank", "Messaging Framework")
MAX_DOC_CHARS = 12_000  # per document returned to an agent
MAX_DOCS = 10


class LibraryError(ValueError):
    pass


def _clean(part: str) -> str:
    return " ".join(part.replace("·", "-").split())


def title_for(client: str, kind: str, subject: str = "") -> str:
    client, subject = _clean(client), _clean(subject)
    if not client:
        raise LibraryError("Say which client this is for.")
    match = next((k for k in KINDS if k.lower() == kind.strip().lower()), None)
    if match is None:
        raise LibraryError(f"kind must be one of: {', '.join(KINDS)}.")
    return SEP.join(p for p in (client, match, subject) if p)


async def upsert_doc(spec: dict[str, str]) -> str:
    """Create or replace a knowledge document by title, then index it. Returns its id."""
    with session() as s:
        doc = s.exec(select(KnowledgeDoc).where(KnowledgeDoc.title == spec["title"])).first()
        if doc is None:
            doc = KnowledgeDoc(**spec)
        else:
            doc.content, doc.updated_at = spec["content"], utcnow()
        s.add(doc)
        s.commit()
        doc_id = doc.id
    await knowledge.index_doc(doc_id)
    return doc_id


def client_docs(client: str) -> list[KnowledgeDoc]:
    prefix = (_clean(client) + SEP).lower()
    if prefix == SEP.lower():
        return []
    with session() as s:
        docs = s.exec(select(KnowledgeDoc)).all()
    return sorted((d for d in docs if d.title.lower().startswith(prefix)),
                  key=lambda d: d.title)


async def find(client: str, query: str = "") -> dict[str, Any]:
    """A client's docs: their full text, or with a query the best-matching passages."""
    docs = client_docs(client)
    if not docs:
        return {"client": client, "documents": [],
                "note": "Nothing saved for this client yet."}
    if query.strip():
        found = await knowledge.search(query, [d.id for d in docs], k=8)
        return {"client": client, "matches": found["results"],
                "documents": [d.title for d in docs]}
    return {"client": client, "documents": [
        {"title": d.title, "updated": d.updated_at.date().isoformat(),
         "content": d.content[:MAX_DOC_CHARS],
         **({"truncated": True} if len(d.content) > MAX_DOC_CHARS else {})}
        for d in docs[:MAX_DOCS]],
        **({"more": [d.title for d in docs[MAX_DOCS:]]} if len(docs) > MAX_DOCS else {})}


async def save(client: str, kind: str, subject: str, content: str,
               agent_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    title = title_for(client, kind, subject)
    if not content.strip():
        raise LibraryError("The document is empty.")
    # "vaio" and "VAIO" are the same client: keep the title the doc was first saved under
    same = next((d for d in client_docs(client) if d.title.lower() == title.lower()), None)
    existed = same is not None
    title = same.title if same else title
    doc_id = await upsert_doc({"title": title, "content": content.strip(),
                               "source": "agent"})
    audit("knowledge_saved", f"{'Updated' if existed else 'Saved'} {title}",
          agent_id=agent_id, task_id=task_id, data={"doc_id": doc_id})
    return {"saved": title, "doc_id": doc_id, "replaced_existing": existed}
