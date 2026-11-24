"""Выдача клиента только активным подписчикам."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from ..config import settings
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api", tags=["download"])


@router.get("/download")
def download(user: User = Depends(current_user)):
    if not user.subscription_active:
        raise HTTPException(status_code=403, detail="Подписка неактивна — оформите или продлите её")

    if settings.jar_url:
        return RedirectResponse(settings.jar_url, status_code=307)

    if not settings.jar_path.is_file():
        raise HTTPException(status_code=503, detail="Файл клиента ещё не загружен на сервер")

    return FileResponse(
        settings.jar_path,
        media_type="application/java-archive",
        filename="aurum.jar",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/download/info")
def info(user: User = Depends(current_user)) -> dict:
    return {
        "subscription": user.subscription(),
        "jar_available": bool(settings.jar_url) or settings.jar_path.is_file(),
    }
