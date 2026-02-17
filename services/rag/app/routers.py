"""
API RAG. Документы: загрузка PDF → docling → markdown в БД.
Команды для чат-бота: RAG_LIST_DOCUMENTS, RAG_GET_DOCUMENT, RAG_SEARCH.
"""
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document
from app.pdf_service import pdf_to_markdown
from app.schemas import DocumentListItem, DocumentResponse

router = APIRouter(prefix="/api/v1", tags=["rag"])


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Document)
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc())
    )
    return [DocumentListItem.model_validate(d) for d in r.scalars().all()]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Document).where(Document.id == document_id))
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.get("/documents/search", response_model=list[DocumentListItem])
async def search_documents(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{q.strip()}%"
    r = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.content_md.ilike(pattern),
        )
        .order_by(Document.created_at.desc())
    )
    return [DocumentListItem.model_validate(d) for d in r.scalars().all()]


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    tenant_id: UUID = Query(..., description="ID тенанта"),
    name: str = Query(..., min_length=1, max_length=512),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename).suffix or ".pdf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir=settings.upload_dir
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
        md = pdf_to_markdown(tmp_path)
    except Exception as e:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"PDF conversion failed: {e}")
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    doc = Document(
        tenant_id=tenant_id,
        name=name.strip(),
        content_md=md,
        source_file_name=file.filename,
    )
    db.add(doc)
    await db.flush()
    return DocumentResponse.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Document).where(Document.id == document_id))
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.flush()
