"""ЮKassa: создание счёта и проверка его статуса.

Документация: https://yookassa.ru/developers/api
Авторизация — Basic (shopId:secretKey), каждая запись требует Idempotence-Key.
Суммы в API — строкой с двумя знаками: "199.00".
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
import uuid

from ..config import settings

log = logging.getLogger("aurum.yookassa")

API_URL = "https://api.yookassa.ru/v3"


class PaymentError(RuntimeError):
    """Ошибка провайдера с человекочитаемым текстом для сайта."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def _auth_header() -> str:
    raw = f"{settings.yookassa_shop_id}:{settings.yookassa_secret_key}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    if not settings.payments_enabled:
        raise PaymentError("Оплата не настроена: нет YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY", 503)

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(API_URL + path, data=data, method=method)
    request.add_header("Authorization", _auth_header())
    request.add_header("Content-Type", "application/json")
    request.add_header("Idempotence-Key", str(uuid.uuid4()))

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        log.error("ЮKassa %s %s → HTTP %s: %s", method, path, exc.code, raw[:500])
        detail = raw[:300]
        try:
            body = json.loads(raw)
            detail = body.get("description") or body.get("type") or detail
        except json.JSONDecodeError:
            pass
        raise PaymentError(f"ЮKassa отклонила запрос: {detail}", 502) from None
    except (urllib.error.URLError, OSError) as exc:
        log.error("ЮKassa недоступна: %s", exc)
        raise PaymentError("Платёжный сервис недоступен, попробуйте позже", 502) from None


def amount_value(kopecks: int) -> str:
    return f"{kopecks // 100}.{kopecks % 100:02d}"


def create_payment(
    *,
    amount: int,
    description: str,
    return_url: str,
    metadata: dict[str, str],
) -> dict:
    payload = {
        "amount": {"value": amount_value(amount), "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:128],
        "metadata": metadata,
    }
    return _request("POST", "/payments", payload)


def get_payment(payment_id: str) -> dict:
    return _request("GET", f"/payments/{payment_id}")
