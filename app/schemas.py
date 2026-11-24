"""Схемы запросов с валидацией (pydantic v2)."""

from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, field_validator

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
PLAN_RE = re.compile(r"^[a-z]{3,16}$")


def normalize_hwid(raw: str | None) -> str | None:
    if not raw:
        return None
    value = "".join(ch for ch in raw.strip().upper() if ch.isalnum())
    return value if 16 <= len(value) <= 128 else None


class RegisterIn(BaseModel):
    username: str
    password: str
    email: EmailStr | None = None
    hwid: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("3–32 символа: латиница, цифры, точка, дефис, подчёркивание")
        return value

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if not 8 <= len(value) <= 128:
            raise ValueError("Пароль должен быть от 8 до 128 символов")
        return value


class LoginIn(BaseModel):
    username: str
    password: str
    hwid: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return value.strip().lower()


class GrantIn(BaseModel):
    username: str
    days: int = 30
    plan: str = "premium"

    @field_validator("days")
    @classmethod
    def _days(cls, value: int) -> int:
        if not 1 <= value <= 3650:
            raise ValueError("Срок подписки: от 1 до 3650 дней")
        return value

    @field_validator("plan")
    @classmethod
    def _plan(cls, value: str) -> str:
        value = value.strip().lower()
        if not PLAN_RE.fullmatch(value):
            raise ValueError("Название тарифа: 3–16 латинских букв")
        return value


class UsernameIn(BaseModel):
    username: str
