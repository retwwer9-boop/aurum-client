"""Aurum Auth — точка входа FastAPI для Render.

Локальный запуск:
    uvicorn app.main:app --reload

Render:
    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .database import engine, init_db
from .routes import account, admin, auth, billing, download, launcher, site

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aurum")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for problem in settings.warnings():
        log.warning("КОНФИГУРАЦИЯ: %s", problem)
    init_db()
    log.info("БД готова: %s", engine.dialect.name)
    yield


app = FastAPI(
    title="Aurum Auth",
    version="2.0.0",
    lifespan=lifespan,
    # Публичная документация не нужна: клиент знает свои эндпоинты.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
)


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанная ошибка", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


app.mount("/static", StaticFiles(directory=str(site.WEB_DIR / "static")), name="static")


@app.get("/api/info")
def info() -> dict:
    return {
        "service": "Aurum Auth",
        "status": "ok",
        "version": "2.1.0",
        "payments": "yookassa" if settings.payments_enabled else "off",
        "game_version": settings.game_version,
    }


@app.get("/api/health")
def health() -> JSONResponse:
    """Render опрашивает этот путь; проверяем и БД."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.error("health: БД недоступна: %s", exc)
        return JSONResponse(status_code=503, content={"status": "error", "database": "down"})
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "database": "ok", "engine": engine.dialect.name},
    )


app.include_router(auth.router)
app.include_router(account.router)
app.include_router(admin.router)
app.include_router(download.router)
app.include_router(launcher.router)
app.include_router(billing.router)
app.include_router(site.router)
