"""Манифест среды для лаунчера: версия игры, ссылки и контрольные суммы.

Лаунчер ничего не ищет на диске: он ставит игру в %APPDATA%\\AurumClient\\game
именно по этому манифесту.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from ..config import settings
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api/launcher", tags=["launcher"])


def _require_subscription(user: User) -> None:
    if not user.subscription_active:
        raise HTTPException(status_code=403, detail="Подписка неактивна — оформите или продлите её")


@router.get("/manifest")
def manifest(user: User = Depends(current_user)) -> dict:
    _require_subscription(user)

    game = None
    if settings.game_url or settings.game_path.is_file():
        game = {
            # Если архив лежит в GitHub Releases — отдаём прямую ссылку: трафик
            # не идёт через Render, а токен не покидает наш домен.
            "url": settings.game_url or "/api/launcher/game",
            "size": settings.game_size or (settings.game_path.stat().st_size if settings.game_path.is_file() else 0),
            "sha256": settings.game_sha256,
        }

    jar = None
    if settings.jar_url or settings.jar_path.is_file():
        jar = {
            "url": settings.jar_url or "/api/download",
            "size": settings.jar_size or (settings.jar_path.stat().st_size if settings.jar_path.is_file() else 0),
            "sha256": settings.jar_sha256,
        }

    return {
        "version": settings.game_version,
        "game": game,
        "jar": jar,
        "install_path_hint": "%APPDATA%\\AurumClient",
    }


@router.get("/game")
def game_archive(user: User = Depends(current_user)):
    _require_subscription(user)

    if settings.game_url:
        return RedirectResponse(settings.game_url, status_code=307)
    if not settings.game_path.is_file():
        raise HTTPException(status_code=503, detail="Архив среды ещё не опубликован на сервере")
    return FileResponse(
        settings.game_path,
        media_type="application/zip",
        filename="aurum-game.zip",
        headers={"Cache-Control": "no-store"},
    )
