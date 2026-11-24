"""Настройки приложения из переменных окружения Render."""

from __future__ import annotations

import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("aurum.config")


def _fix_db_url(url: str) -> str:
    """Render отдаёт postgres://..., SQLAlchemy требует явный драйвер."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings:
    def __init__(self) -> None:
        raw_db = os.environ.get("DATABASE_URL", "").strip()
        self.database_url = (
            _fix_db_url(raw_db) if raw_db else f"sqlite:///{(BASE_DIR / 'aurum.db').as_posix()}"
        )

        self.secret_key = os.environ.get("SECRET_KEY", "").strip() or "dev-insecure-secret"
        self.admin_token = os.environ.get("ADMIN_TOKEN", "").strip()
        self.token_ttl = int(os.environ.get("TOKEN_TTL_SECONDS", "43200"))  # 12 часов
        self.allow_registration = os.environ.get("ALLOW_REGISTRATION", "1").lower() not in {
            "0",
            "false",
            "no",
        }

        # Клиент можно держать в репозитории (static/aurum.jar) или отдавать редиректом
        # на GitHub Releases / S3 — тогда JAR_URL.
        self.jar_path = Path(os.environ.get("JAR_PATH") or (BASE_DIR / "static" / "aurum.jar"))
        self.jar_url = os.environ.get("JAR_URL", "").strip()
        self.jar_sha256 = os.environ.get("JAR_SHA256", "").strip().lower()
        self.jar_size = int(os.environ.get("JAR_SIZE", "0") or 0)

        # Среда игры (портативный Minecraft) отдаётся архивом: либо файл на сервере,
        # либо внешний URL (GitHub Releases). Render не хранит большие файлы.
        self.game_path = Path(os.environ.get("GAME_PATH") or (BASE_DIR / "static" / "game.zip"))
        self.game_url = os.environ.get("GAME_URL", "").strip()
        self.game_sha256 = os.environ.get("GAME_SHA256", "").strip().lower()
        self.game_size = int(os.environ.get("GAME_SIZE", "0") or 0)
        self.game_version = os.environ.get("GAME_VERSION", "").strip() or "dev"

        self.cors_origins = [
            origin.strip()
            for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ]
        self.port = int(os.environ.get("PORT", "8000"))
        self.is_render = bool(os.environ.get("RENDER"))

        # ---------------------------------------------------------------- сайт
        self.public_base_url = (
            os.environ.get("PUBLIC_BASE_URL", "").strip() or "https://aurum-auth.onrender.com"
        ).rstrip("/")
        self.support_telegram = os.environ.get("SUPPORT_TELEGRAM", "").strip().lstrip("@")
        self.support_email = os.environ.get("SUPPORT_EMAIL", "").strip()

        # ------------------------------------------------------------- лаунчер
        self.launcher_url = os.environ.get("LAUNCHER_URL", "").strip()
        self.launcher_sha256 = os.environ.get("LAUNCHER_SHA256", "").strip().lower()
        self.launcher_size = int(os.environ.get("LAUNCHER_SIZE", "0") or 0)
        self.launcher_version = os.environ.get("LAUNCHER_VERSION", "").strip()

        # ------------------------------------------------------------- платежи
        self.yookassa_shop_id = os.environ.get("YOOKASSA_SHOP_ID", "").strip()
        self.yookassa_secret_key = os.environ.get("YOOKASSA_SECRET_KEY", "").strip()
        # Куда ЮKassa вернёт покупателя после оплаты.
        self.yookassa_return_url = (
            os.environ.get("YOOKASSA_RETURN_URL", "").strip()
            or f"{self.public_base_url}/buy/success"
        )

    @property
    def payments_enabled(self) -> bool:
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    def warnings(self) -> list[str]:
        problems: list[str] = []
        if self.secret_key == "dev-insecure-secret":
            problems.append("SECRET_KEY не задан — токены подписаны публично известным ключом")
        if self.is_render and not self.database_url.startswith("postgresql"):
            problems.append(
                "DATABASE_URL не задан — SQLite на Render стирается при каждом деплое и рестарте"
            )
        if self.is_render and not self.admin_token:
            problems.append("ADMIN_TOKEN не задан — админ-методы выключены")
        return problems


settings = Settings()
