"""CIP RAG microservice. Схема БД: rag."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="CIP RAG",
    description="Микросервис RAG: PDF → markdown (docling). Команды: RAG_LIST_DOCUMENTS, RAG_GET_DOCUMENT, RAG_SEARCH.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cip-rag"}
