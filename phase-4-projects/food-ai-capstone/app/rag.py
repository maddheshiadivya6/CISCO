import hashlib
import logging
import math
import zipfile
from io import BytesIO
from pathlib import Path

import pymupdf
from docx import Document as DocxDocument
from fastapi import HTTPException
from google import genai
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk

logger = logging.getLogger(__name__)
MAX_BYTES = 5 * 1024 * 1024


def client():
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(503, "Gemini is not configured; set GEMINI_API_KEY on the server")
    return genai.Client(api_key=settings.gemini_api_key, http_options={"timeout": 30000})


def embed(texts: list[str], task_type: str) -> list[list[float]]:
    try:
        result = client().models.embed_content(
            model=get_settings().gemini_embedding_model,
            contents=texts,
            config={"task_type": task_type, "output_dimensionality": 768},
        )
        return [embedding.values for embedding in result.embeddings]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Gemini embedding request failed")
        raise HTTPException(503, "Gemini embeddings are temporarily unavailable") from exc


def extract(filename: str, data: bytes) -> list[tuple[str, str]]:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".txt":
            return [("section 1", data.decode("utf-8"))]
        if suffix == ".pdf":
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if len(doc) > 200:
                    raise HTTPException(413, "Document has too many pages")
                return [(f"page {i + 1}", page.get_text()) for i, page in enumerate(doc)]
        if suffix == ".docx":
            with zipfile.ZipFile(BytesIO(data)) as archive:
                if sum(member.file_size for member in archive.infolist()) > 20 * 1024 * 1024:
                    raise HTTPException(413, "Document expands beyond the allowed size")
            doc = DocxDocument(BytesIO(data))
            return [("section 1", "\n".join(p.text for p in doc.paragraphs))]
    except (ValueError, UnicodeError, RuntimeError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(422, "Could not read document") from exc
    raise HTTPException(415, "Only PDF, DOCX and UTF-8 TXT documents are supported")


def index_document(db: Session, filename: str, data: bytes, user_id: int):
    filename = Path(filename).name
    if not filename or len(filename) > 255 or len(data) > MAX_BYTES:
        raise HTTPException(413, "Document is too large or its filename is invalid")
    pieces = []
    for page, content in extract(filename, data):
        content = content.strip()
        for start in range(0, len(content), 600):
            chunk = content[start:start + 700].strip()
            if chunk:
                pieces.append((page, chunk))
    if not pieces:
        raise HTTPException(422, "Document contains no extractable text")
    if len(pieces) > 200:
        raise HTTPException(413, "Document has too many text chunks")
    vectors = embed([chunk for _, chunk in pieces], "RETRIEVAL_DOCUMENT")
    if len(vectors) != len(pieces):
        raise HTTPException(503, "Gemini returned an incomplete embedding response")
    versions = list(db.scalars(select(Document).where(Document.filename == filename)))
    for old in versions:
        old.active = False
    doc = Document(filename=filename, sha256=hashlib.sha256(data).hexdigest(),
                   version=max((d.version for d in versions), default=0) + 1, uploaded_by=user_id)
    db.add(doc)
    db.flush()
    for (page, content), vector in zip(pieces, vectors):
        db.add(DocumentChunk(document_id=doc.id, page=page, content=content, embedding=vector))
    db.commit()
    return {"id": doc.id, "filename": doc.filename, "version": doc.version, "chunks": len(pieces)}


def retrieve(db: Session, question: str) -> list[dict]:
    query = embed([question], "RETRIEVAL_QUERY")[0]
    qnorm = math.sqrt(sum(x * x for x in query))
    results = []
    chunks = db.execute(select(DocumentChunk, Document).join(Document).where(Document.active.is_(True))).all()
    for chunk, document in chunks:
        v = chunk.embedding
        if len(v) != len(query):
            continue
        norm = math.sqrt(sum(x * x for x in v))
        similarity = sum(a * b for a, b in zip(query, v)) / (qnorm * norm) if qnorm and norm else 0
        if similarity >= 0.55:
            results.append((similarity, {
                "filename": document.filename, "page": chunk.page, "chunk_id": chunk.id,
                "version": document.version, "text": chunk.content,
            }))
    return [result for _, result in sorted(results, key=lambda x: x[0], reverse=True)[:4]]
