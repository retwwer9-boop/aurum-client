"""Регистрация и вход."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import LoginIn, RegisterIn, normalize_hwid
from ..security import client_ip, create_token, hash_password, limiter, verify_password
from ..utils import now_ts

router = APIRouter(prefix="/api", tags=["auth"])


def auth_payload(user: User) -> dict:
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "expires_in": settings.token_ttl,
        "user": user.to_public(),
        "subscription": user.subscription(),
    }


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.hit(f"register:{client_ip(request)}")

    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="Регистрация закрыта, обратитесь в поддержку")

    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")

    email = str(body.email).lower() if body.email else None
    if email and db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Этот e-mail уже используется")

    user = User(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
        hwid=normalize_hwid(body.hwid),
        last_login_at=now_ts(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Логин или e-mail уже заняты") from None

    db.refresh(user)
    return auth_payload(user)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.hit(f"login:{client_ip(request)}:{body.username}")

    user = db.scalar(select(User).where(User.username == body.username))
    # Одинаковый ответ на «нет такого» и «неверный пароль» — не подсказываем, какие логины есть.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    hwid = normalize_hwid(body.hwid)
    if hwid:
        if user.hwid and user.hwid != hwid:
            raise HTTPException(
                status_code=403,
                detail="Аккаунт привязан к другому устройству. Напишите в поддержку для сброса",
            )
        if not user.hwid:
            user.hwid = hwid

    user.last_login_at = now_ts()
    db.commit()
    db.refresh(user)
    return auth_payload(user)
