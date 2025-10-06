# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.routers.extract import router as extract_router
from app.db import init_db_pool, close_db_pool  # uses your asyncpg pool helpers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db_pool()
    yield
    # Shutdown
    await close_db_pool()

app = FastAPI(
    title="ERP-AI Document Intelligence API",
    version="1.0",
    lifespan=lifespan,
)

# Routes
app.include_router(extract_router)

# Health
@app.get("/health")
async def health():
    return {"status": "ok"}
