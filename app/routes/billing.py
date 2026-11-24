"""Оплата подписки через ЮKassa: счёт, статус, вебхук."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Payment, User
from ..payments import yookassa
from ..payments.yookassa import PaymentError
from ..plans import PLANS, get_plan
from ..schemas import CheckoutIn
from ..security import client_ip, current_user, limiter
from ..utils import now_ts

log = logging.getLogger("aurum.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/plans")
def plans() -> dict:
    return {
        "plans": [plan.to_public() for plan in PLANS],
        "payments_enabled": settings.payments_enabled,
        "provider": "ЮKassa",
        "support_telegram": settings.support_telegram,
        "support_email": settings.support_email,
    }


@router.post("/checkout")
def checkout(
    body: CheckoutIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    limiter.hit(f"checkout:{user.id}:{client_ip(request)}")

    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Такого тарифа нет")

    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        days=plan.days,
        amount=plan.price,
        currency="RUB",
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    try:
        remote = yookassa.create_payment(
            amount=plan.price,
            description=f"Aurum — подписка на {plan.days} дней",
            return_url=f"{settings.yookassa_return_url}?payment={payment.id}",
            metadata={
                "payment_id": str(payment.id),
                "user_id": str(user.id),
                "plan_id": plan.id,
                "days": str(plan.days),
            },
        )
    except PaymentError as exc:
        # Счёт не создан у провайдера — не оставляем мусорную запись в истории.
        db.delete(payment)
        db.commit()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    payment.provider_id = str(remote.get("id") or "")
    payment.confirmation_url = (remote.get("confirmation") or {}).get("confirmation_url")
    db.commit()

    if not payment.confirmation_url:
        log.error("ЮKassa не вернула confirmation_url: %s", remote)
        payment.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail="Платёжный сервис не выдал ссылку на оплату")

    return {
        "payment": payment.to_public(),
        "confirmation_url": payment.confirmation_url,
    }


@router.get("/payments/{payment_id}")
def payment_status(
    payment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    payment = db.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="Платёж не найден")

    # Сайт опрашивает этот метод, пока человек оплачивает: вебхук может прийти позже.
    if payment.status == "pending" and payment.provider_id and settings.payments_enabled:
        try:
            remote = yookassa.get_payment(payment.provider_id)
        except PaymentError:
            remote = None
        if remote:
            payment = _apply(db, payment.id, remote)

    db.refresh(user)
    return {"payment": payment.to_public(), "subscription": user.subscription()}


@router.get("/history")
def history(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc())
        .limit(20)
    ).all()
    return {"payments": [payment.to_public() for payment in rows]}


@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Уведомление от ЮKassa. Телу не доверяем: перепроверяем платёж через API."""
    try:
        event = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": False}

    obj = (event or {}).get("object") or {}
    provider_id = str(obj.get("id") or "")
    if not provider_id or not settings.payments_enabled:
        return {"ok": False}

    try:
        remote = yookassa.get_payment(provider_id)
    except PaymentError as exc:
        log.warning("вебхук: не удалось проверить платёж %s: %s", provider_id, exc)
        return {"ok": False}

    payment = db.scalar(select(Payment).where(Payment.provider_id == provider_id))
    if payment is None:
        log.warning("вебхук: платёж %s не найден в базе", provider_id)
        return {"ok": False}

    _apply(db, payment.id, remote)
    return {"ok": True}


def _apply(db: Session, payment_id: int, remote: dict) -> Payment:
    """Начисляет подписку ровно один раз, даже если пришли и вебхук, и опрос."""
    payment = db.execute(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Платёж не найден")

    if payment.status == "succeeded":
        return payment

    status = str(remote.get("status") or "")
    if status == "succeeded":
        try:
            paid = int(round(float((remote.get("amount") or {}).get("value", "0")) * 100))
        except (TypeError, ValueError):
            paid = 0
        if paid and paid < payment.amount:
            log.error(
                "платёж %s: оплачено %s коп., ожидалось %s — подписка не начислена",
                payment.id,
                paid,
                payment.amount,
            )
            return payment

        payment.status = "succeeded"
        payment.paid_at = now_ts()
        user = db.get(User, payment.user_id)
        if user is not None:
            user.grant(payment.days, "premium")
        db.commit()
        log.info("подписка +%s дней пользователю %s (платёж %s)", payment.days, payment.user_id, payment.id)
    elif status == "canceled":
        payment.status = "canceled"
        db.commit()

    return payment
