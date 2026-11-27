"""Админ-методы: выдача подписки, блокировка, сброс привязки устройства."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import GrantIn, NoteIn, UsernameIn
from ..security import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _get(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.post("/grant")
def grant(body: GrantIn, db: Session = Depends(get_db)) -> dict:
    user = _get(db, body.username)
    user.grant(body.days, body.plan)
    db.commit()
    return {"status": "ok", "user": user.to_public(), "subscription": user.subscription()}


@router.post("/revoke")
def revoke(body: UsernameIn, db: Session = Depends(get_db)) -> dict:
    user = _get(db, body.username)
    user.revoke()
    db.commit()
    return {"status": "ok", "user": user.to_public(), "subscription": user.subscription()}


@router.post("/reset-hwid")
def reset_hwid(body: UsernameIn, db: Session = Depends(get_db)) -> dict:
    user = _get(db, body.username)
    user.hwid = None
    db.commit()
    return {"status": "ok", "username": user.username}


@router.post("/note")
def set_note(body: NoteIn, db: Session = Depends(get_db)) -> dict:
    """Короткая подпись в кабинете пользователя. Пустая строка убирает её."""
    user = _get(db, body.username)
    user.note = body.note or None
    db.commit()
    return {"status": "ok", "username": user.username, "note": user.note or ""}


@router.get("/users")
def users(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 200))
    rows = db.scalars(select(User).order_by(User.created_at.desc()).limit(limit)).all()
    return {
        "count": len(rows),
        "users": [
            {**u.to_public(), "subscription": u.subscription(), "last_login_at": u.last_login_at}
            for u in rows
        ],
    }
