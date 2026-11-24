"""Профиль, статус подписки, выход."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user.to_public(), "subscription": user.subscription()}


@router.get("/subscription")
def subscription(user: User = Depends(current_user)) -> dict:
    return user.subscription()


@router.post("/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Инвалидирует все токены аккаунта (выход на всех устройствах)."""
    user.token_version += 1
    db.commit()
    return {"status": "ok"}
