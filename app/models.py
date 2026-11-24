"""Модели: аккаунт + подписка одного пользователя + платежи."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .utils import days_left, iso, now_ts


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Одна привязка к устройству: защита от передачи аккаунта друзьям.
    hwid: Mapped[str | None] = mapped_column(String(128))

    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    # Смена значения инвалидирует все выданные токены (выход со всех устройств).
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ts, nullable=False)
    last_login_at: Mapped[int | None] = mapped_column(BigInteger)

    plan: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    sub_started_at: Mapped[int | None] = mapped_column(BigInteger)
    sub_expires_at: Mapped[int | None] = mapped_column(BigInteger)

    # ------------------------------------------------------------------ helpers

    @property
    def subscription_active(self) -> bool:
        return bool(self.sub_expires_at and self.sub_expires_at > now_ts())

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": iso(self.created_at),
            "hwid_bound": bool(self.hwid),
        }

    def subscription(self) -> dict:
        return {
            "active": self.subscription_active,
            "plan": self.plan,
            "started_at": iso(self.sub_started_at),
            "expires_at": iso(self.sub_expires_at),
            "days_left": days_left(self.sub_expires_at) if self.subscription_active else 0,
        }

    def grant(self, days: int, plan: str) -> None:
        """Продлевает подписку от текущей даты окончания, а не от «сейчас»."""
        if days <= 0:
            return
        start = now_ts()
        base = max(self.sub_expires_at or 0, start)
        self.sub_started_at = self.sub_started_at or start
        self.sub_expires_at = base + days * 86400
        self.plan = plan

    def revoke(self) -> None:
        self.sub_expires_at = now_ts()
        self.plan = "none"


class Payment(Base):
    """Счёт на подписку. Один платёж = один тариф, оплата подтверждается провайдером."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # копейки
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)

    provider: Mapped[str] = mapped_column(String(16), default="yookassa", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    confirmation_url: Mapped[str | None] = mapped_column(String(1024))

    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ts, nullable=False)
    paid_at: Mapped[int | None] = mapped_column(BigInteger)

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "days": self.days,
            "amount": self.amount,
            "amount_label": f"{self.amount // 100} ₽",
            "currency": self.currency,
            "status": self.status,
            "created_at": iso(self.created_at),
            "paid_at": iso(self.paid_at),
        }

