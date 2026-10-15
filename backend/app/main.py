"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(
    title="Smart Warranty Intelligence & Failure Prediction API",
    version="1.0.0",
    description="Warranty, service-request, inventory, analytics and failure-risk prediction API. "
                "Authenticate via POST /api/v1/auth/login and send `Authorization: Bearer <token>`.",
    docs_url="/docs" if not settings.is_production else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.include_router(api_router)


@app.get("/health", tags=["health"])
def health():
    from sqlalchemy import text

    from app.core.database import engine

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
