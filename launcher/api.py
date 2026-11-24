"""Клиент HTTP к серверу Aurum (только стандартная библиотека)."""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_API_URL = "https://aurum-auth.onrender.com"
CHUNK = 128 * 1024

# Некоторые провайдеры блокируют адреса, куда резолвится *.onrender.com
# (216.24.57.0/24): TCP-соединение сбрасывается. Render живёт за Cloudflare,
# поэтому тот же сервис доступен через любой её edge: SNI и сертификат
# остаются прежними, меняется только IP, к которому подключаемся.
EDGE_FALLBACK_IPS = (
    "104.18.0.1",
    "104.17.0.1",
    "162.159.0.1",
    "104.18.32.1",
    "172.64.0.1",
)

_edge_ip: str | None = None


class _EdgeConnection(http.client.HTTPSConnection):
    """HTTPS-соединение к конкретному IP с SNI/host исходного домена."""

    def __init__(self, host: str, ip: str, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self._ip = ip

    def connect(self) -> None:  # type: ignore[override]
        self.sock = socket.create_connection((self._ip, self.port or 443), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _EdgeHandler(urllib.request.HTTPSHandler):
    def __init__(self, ip: str) -> None:
        super().__init__()
        self._ip = ip

    def https_open(self, req):
        return self.do_open(lambda host, **kwargs: _EdgeConnection(host, self._ip, **kwargs), req)


def _edge_host(host: str) -> bool:
    return host == "onrender.com" or host.endswith(".onrender.com")


def _urlopen(request: urllib.request.Request, timeout: float):
    """urlopen с запасным маршрутом через edge Cloudflare для *.onrender.com."""
    global _edge_ip
    host = urllib.parse.urlsplit(request.full_url).hostname or ""

    def via_edge(ip: str):
        opener = urllib.request.build_opener(_EdgeHandler(ip))
        return opener.open(request, timeout=timeout)

    if _edge_ip and _edge_host(host):
        return via_edge(_edge_ip)

    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError):
        if not _edge_host(host):
            raise

    last: Exception | None = None
    for ip in EDGE_FALLBACK_IPS:
        try:
            response = via_edge(ip)
            _edge_ip = ip
            return response
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as exc:
            last = exc
    raise urllib.error.URLError(f"нет маршрута к {host}: {last}")


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
            with _urlopen(request, self.timeout) as response:
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

    def download(
        self,
        url: str,
        destination: Path,
        progress: Callable[[int, int], None] | None = None,
        attempts: int = 6,
    ) -> Path:
        """Скачивает файл во временный .part, продолжая с места обрыва.

        GitHub Releases и мобильные сети регулярно рвут длинную загрузку,
        поэтому файл докачивается через Range, а 5xx/сетевые ошибки повторяются.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        absolute = url if url.startswith(("http://", "https://")) else self.base_url + url
        temporary = destination.with_suffix(destination.suffix + ".part")

        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._fetch(absolute, temporary, progress)
                break
            except _Retryable as exc:
                last = exc.cause
                if attempt == attempts:
                    raise ApiError(0, f"Загрузка прервалась: {exc}") from None
                time.sleep(min(2 * attempt, 10))
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 or exc.code == 429:
                    last = exc
                    if attempt == attempts:
                        raise ApiError(exc.code, _error_detail(exc)) from None
                    time.sleep(min(2 * attempt, 10))
                    continue
                temporary.unlink(missing_ok=True)
                raise ApiError(exc.code, _error_detail(exc)) from None
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                last = exc
                if attempt == attempts:
                    reason = getattr(exc, "reason", exc)
                    raise ApiError(0, f"Загрузка не удалась: {reason}") from None
                time.sleep(min(2 * attempt, 10))

        if not temporary.exists() or temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise ApiError(0, "Сервер вернул пустой файл")

        os.replace(temporary, destination)
        return destination

    def _fetch(self, absolute: str, temporary: Path, progress: Callable[[int, int], None] | None) -> None:
        have = temporary.stat().st_size if temporary.exists() else 0

        request = urllib.request.Request(absolute)
        # Токен — только нашему серверу. На GitHub Releases он не нужен и его нельзя светить.
        if self.token and absolute.startswith(self.base_url + "/"):
            request.add_header("Authorization", f"Bearer {self.token}")
        if have:
            request.add_header("Range", f"bytes={have}-")

        with _urlopen(request, 120) as response:
            status = getattr(response, "status", 200)
            if have and status == 200:
                have = 0  # сервер проигнорировал Range — начинаем заново
            mode = "ab" if have else "wb"

            length = int(response.headers.get("Content-Length") or 0)
            total = have + length if length else 0
            received = 0
            with open(temporary, mode) as handle:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(have + received, total)

        size = temporary.stat().st_size if temporary.exists() else 0
        if total and size < total:
            raise _Retryable(f"получено {size} из {total} байт")


class _Retryable(Exception):
    def __init__(self, cause: object) -> None:
        super().__init__(str(cause))
        self.cause = cause


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
