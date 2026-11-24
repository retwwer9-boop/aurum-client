"""Тарифы подписки. Цена хранится в копейках, чтобы не ловить округления."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    id: str
    days: int
    price: int  # копейки
    title: str
    note: str
    badge: str = ""

    @property
    def rubles(self) -> int:
        return self.price // 100

    @property
    def price_label(self) -> str:
        return f"{self.rubles:,}".replace(",", " ") + " ₽"

    @property
    def per_month(self) -> str:
        if self.days >= 30:
            months = max(self.days / 30, 1)
            return f"{round(self.rubles / months)} ₽/мес"
        return ""

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "days": self.days,
            "price": self.price,
            "price_label": self.price_label,
            "per_month": self.per_month,
            "title": self.title,
            "note": self.note,
            "badge": self.badge,
        }


PLANS: tuple[Plan, ...] = (
    Plan(
        id="month",
        days=30,
        price=19900,
        title="30 дней",
        note="Попробовать: весь функционал, одно устройство",
    ),
    Plan(
        id="quarter",
        days=90,
        price=49900,
        title="90 дней",
        note="Выгоднее на 16%",
        badge="Популярный",
    ),
    Plan(
        id="year",
        days=365,
        price=149000,
        title="365 дней",
        note="Лучшая цена: 124 ₽ в месяц",
        badge="Выгодно",
    ),
)

PLANS_BY_ID: dict[str, Plan] = {plan.id: plan for plan in PLANS}


def get_plan(plan_id: str) -> Plan | None:
    return PLANS_BY_ID.get(plan_id)
