"""CIP Gallery microservice. Схема БД: gallery."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="CIP Gallery",
    description="Микросервис галереи изображений. Команды: LIST_GALLERIES, SHOW_GALLERY, CREATE_GALLERY_GROUP, ADD_IMAGE_TO_GALLERY, REMOVE_IMAGE_FROM_GALLERY, DELETE_GALLERY_GROUP.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cip-gallery"}
