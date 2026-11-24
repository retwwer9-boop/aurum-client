"""Клиент HTTP к серверу Aurum (только стандартная библиотека)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_API_URL = "https://aurum-auth.onrender.com"
CHUNK = 128 * 1024


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class AurumClient:
    def __init__(self, base_url: str = DEFAULT_API_URL, token: str | None = None, timeout: float = 25.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------ служебное

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            raise ApiError(exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise ApiError(0, f"Нет связи с сервером: {exc.reason}") from None

        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(0, "Сервер вернул не JSON — проверьте адрес API") from None

    # ------------------------------------------------------------------ аккаунт

    def register(self, username: str, password: str, hwid: str | None = None) -> dict:
        data = self._request("POST", "/api/register", {"username": username, "password": password, "hwid": hwid})
        self.token = data.get("access_token", self.token)
        return data

    def login(self, username: str, password: str, hwid: str | None = None) -> dict:
        data = self._request("POST", "/api/login", {"username": username, "password": password, "hwid": hwid})
        self.token = data.get("access_token", self.token)
        return data

    def me(self) -> dict:
        return self._request("GET", "/api/me")

    def subscription(self) -> dict:
        return self._request("GET", "/api/subscription")

    def logout(self) -> None:
        self._request("POST", "/api/logout")

    def manifest(self) -> dict:
        """Что и по каким ссылкам качать: версия среды, игра, JAR."""
        return self._request("GET", "/api/launcher/manifest")

    # ------------------------------------------------------------------ загрузка

    def download(self, url: str, destination: Path, progress: Callable[[int, int], None] | None = None) -> Path:
        """Скачивает файл с сервера (относительный путь допустим) во временный .part."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        absolute = url if url.startswith(("http://", "https://")) else self.base_url + url

        request = urllib.request.Request(absolute)
        # Токен — только нашему серверу. На GitHub Releases он не нужен и его нельзя светить.
        if self.token and absolute.startswith(self.base_url + "/"):
            request.add_header("Authorization", f"Bearer {self.token}")

        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                with open(temporary, "wb") as handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        if progress:
                            progress(received, total)
        except urllib.error.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise ApiError(exc.code, _error_detail(exc)) from None
        except urllib.error.URLError as exc:
            temporary.unlink(missing_ok=True)
            raise ApiError(0, f"Загрузка не удалась: {exc.reason}") from None

        if temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise ApiError(0, "Сервер вернул пустой файл")

        os.replace(temporary, destination)
        return destination


def _error_detail(exc: urllib.error.HTTPError) -> str:
    raw = exc.read().decode("utf-8", "replace").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw or f"HTTP {exc.code}"
    detail = payload.get("detail", payload)
    if isinstance(detail, list) and detail:  # ошибки валидации pydantic
        first = detail[0]
        return first.get("msg", str(first)) if isinstance(first, dict) else str(first)
    return str(detail)
