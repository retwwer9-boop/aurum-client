"""Публикация среды игры и JAR в GitHub Releases + прокидывание ссылок в Render.

Запуск (нужны GITHUB_TOKEN и, для привязки к Render, RENDER_API_KEY):
    python publish_assets.py --source "C:\\путь\\Dimasik Portable" --jar build/aurum.jar

Что делает:
  1. пакует папку клиента в build/game.zip (если передан --source);
  2. создаёт/использует публичный репозиторий aurum-client-downloads;
  3. создаёт релиз и загружает game.zip и aurum.jar ассетами;
  4. считает SHA-256 и размеры;
  5. прописывает GAME_URL / GAME_SHA256 / JAR_URL / JAR_SHA256 в Render и запускает деплой.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / "deploy.env"
ARTIFACTS_FILE = ROOT / "build" / "artifacts.env"
ASSETS_REPO = os.environ.get("ASSETS_REPO", "aurum-client-downloads")
SERVICE_NAME = os.environ.get("RENDER_SERVICE_NAME", "aurum-auth")
GITHUB_API = "https://api.github.com"
RENDER_API = "https://api.render.com/v1"


class PublishError(RuntimeError):
    pass


def load_env_file() -> None:
    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


load_env_file()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()

RENDER_EDGE_IP = os.environ.get("RENDER_EDGE_IP", "").strip()


def _force_edge(ip: str) -> None:
    import socket

    original = socket.getaddrinfo

    def patched(host, port, *args, **kwargs):
        if isinstance(host, str) and (host == "api.render.com" or host.endswith(".onrender.com")):
            return original(ip, port, *args, **kwargs)
        return original(host, port, *args, **kwargs)

    socket.getaddrinfo = patched


if RENDER_EDGE_IP:
    _force_edge(RENDER_EDGE_IP)


def http(url: str, method: str = "GET", body: dict | None = None, token: str | None = None,
         headers: dict | None = None, timeout: float = 300.0, data_file: Path | None = None,
         content_type: str | None = None):
    if data_file is not None:
        data = open(data_file, "rb")  # noqa: SIM115 — закрывается в finally ниже
        length = data_file.stat().st_size
    else:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        length = len(data) if data else 0

    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "aurum-publish/1.0")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None and data_file is None:
        request.add_header("Content-Type", "application/json")
    if data_file is not None:
        request.add_header("Content-Type", content_type or "application/octet-stream")
        request.add_header("Content-Length", str(length))
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise PublishError(f"{method} {url} → HTTP {exc.code}\n{detail[:1200]}") from None
    except urllib.error.URLError as exc:
        raise PublishError(f"Нет связи с {url}: {exc.reason}") from None
    finally:
        if data_file is not None:
            data.close()

    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8", "replace")


def github(method: str, path: str, body: dict | None = None, **kwargs):
    return http(GITHUB_API + path, method, body, GITHUB_TOKEN, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def pack(source: Path, output: Path, level: int = 1) -> Path:
    print(f"[1/5] Упаковка {source} → {output}")
    script = ROOT / "tools" / "pack_game.py"
    subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--out", str(output), "--level", str(level)],
        check=True,
    )
    return output


def ensure_assets_repo() -> tuple[str, str]:
    if not GITHUB_TOKEN:
        raise PublishError("GITHUB_TOKEN не задан (переменная окружения или deploy.env)")
    owner = github("GET", "/user")["login"]

    try:
        github("GET", f"/repos/{owner}/{ASSETS_REPO}")
        print(f"[2/5] Репозиторий ассетов: {owner}/{ASSETS_REPO}")
    except PublishError as exc:
        if "HTTP 404" not in str(exc):
            raise
        github("POST", "/user/repos", {
            "name": ASSETS_REPO,
            "private": False,
            "auto_init": True,
            "description": "Aurum Client — файлы среды и клиента (только релизы)",
        })
        print(f"[2/5] Создан публичный репозиторий ассетов: {owner}/{ASSETS_REPO}")
    return owner, ASSETS_REPO


def ensure_release(full_repo: str, tag: str) -> dict:
    try:
        return github("GET", f"/repos/{full_repo}/releases/tags/{tag}")
    except PublishError as exc:
        if "HTTP 404" not in str(exc):
            raise
    release = github("POST", f"/repos/{full_repo}/releases", {
        "tag_name": tag,
        "name": f"Aurum Client {tag}",
        "body": "Среда игры и клиент для лаунчера Aurum.",
    })
    print(f"[3/5] Создан релиз {tag}")
    return release


def upload_asset(full_repo: str, release_id: int, path: Path, name: str) -> None:
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"      загрузка {name} ({size_mb:.0f} МБ)…")
    query = urllib.parse.urlencode({"name": name})
    url = f"https://uploads.github.com/repos/{full_repo}/releases/{release_id}/assets?{query}"

    if name.endswith(".zip"):
        content_type = "application/zip"
    elif name.endswith(".jar"):
        content_type = "application/java-archive"
    else:
        content_type = "application/octet-stream"

    def send() -> None:
        http(
            url,
            "POST",
            token=GITHUB_TOKEN,
            data_file=path,
            content_type=content_type,
            timeout=3600,
        )

    try:
        send()
    except PublishError as exc:
        # Тот же тег и имя файла уже загружали: заменяем старый ассет.
        if "HTTP 422" not in str(exc):
            raise
        for asset in github("GET", f"/repos/{full_repo}/releases/{release_id}/assets") or []:
            if asset.get("name") == name:
                github("DELETE", f"/repos/{full_repo}/releases/assets/{asset['id']}")
        send()
    print(f"      {name} загружен")


def find_render_service() -> str:
    services = http(f"{RENDER_API}/services?name={SERVICE_NAME}&limit=50", token=RENDER_API_KEY)
    for item in services or []:
        service = item.get("service", item)
        if service.get("name") == SERVICE_NAME:
            return service["id"]
    raise PublishError(f"На Render нет сервиса {SERVICE_NAME}. Сначала запустите deploy_render.py")


def set_env(service_id: str, values: dict[str, str]) -> None:
    for key, value in values.items():
        http(f"{RENDER_API}/services/{service_id}/env-vars/{key}", "PUT", {"value": value},
             token=RENDER_API_KEY)


def trigger_deploy(service_id: str) -> None:
    http(f"{RENDER_API}/services/{service_id}/deploys", "POST", {"clearCache": "do_not_clear"},
         token=RENDER_API_KEY)


def wait_healthy(url: str, timeout: float = 900.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=20) as response:
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Опубликовать клиент и среду игры")
    parser.add_argument("--source", help="папка портативного клиента (упакуется в game.zip)")
    parser.add_argument("--game", default="build/game.zip", help="готовый game.zip")
    parser.add_argument("--jar", default="build/aurum.jar", help="файл aurum.jar")
    parser.add_argument("--version", help="версия/тег, по умолчанию дата")
    parser.add_argument("--level", type=int, default=1, help="сжатие zip 0-9 (1 быстрее всего)")
    parser.add_argument("--no-render", action="store_true", help="не трогать Render, только GitHub")
    args = parser.parse_args()

    try:
        tag = args.version or time.strftime("v%Y.%m.%d-%H%M%S")

        game_zip = Path(args.game)
        if args.source:
            game_zip = pack(Path(args.source), (ROOT / args.game).resolve(), level=args.level)
        elif not game_zip.is_absolute():
            game_zip = (ROOT / args.game).resolve()
        if not game_zip.is_file():
            raise PublishError(f"Нет {game_zip}: укажите --source или --game")

        jar = Path(args.jar)
        if not jar.is_absolute():
            jar = (ROOT / args.jar).resolve()

        game_sha = sha256(game_zip)
        game_size = game_zip.stat().st_size
        jar_sha = sha256(jar) if jar.is_file() else ""
        jar_size = jar.stat().st_size if jar.is_file() else 0
        print(f"      game.zip  {game_size / 1024 / 1024:.0f} МБ  sha256 {game_sha[:16]}…")
        if jar_sha:
            print(f"      aurum.jar {jar_size / 1024 / 1024:.0f} МБ  sha256 {jar_sha[:16]}…")
        else:
            print("      aurum.jar не найден — JAR останется прежним (JAR_URL не меняем)")

        owner, repo = ensure_assets_repo()
        full_repo = f"{owner}/{repo}"
        release = ensure_release(full_repo, tag)

        upload_asset(full_repo, release["id"], game_zip, "game.zip")
        if jar_sha:
            upload_asset(full_repo, release["id"], jar, "aurum.jar")

        base = f"https://github.com/{full_repo}/releases/download/{tag}"
        game_url = f"{base}/game.zip"
        jar_url = f"{base}/aurum.jar"

        values = {
            "GAME_URL": game_url,
            "GAME_SHA256": game_sha,
            "GAME_SIZE": str(game_size),
            "GAME_VERSION": tag,
        }
        if jar_sha:
            values.update({"JAR_URL": jar_url, "JAR_SHA256": jar_sha, "JAR_SIZE": str(jar_size)})

        print("[4/5] Ссылки:")
        for key, value in values.items():
            print(f"      {key}={value}")

        # Сохраняем для deploy_render.py: он подхватит и передаст в Render,
        # даже если сервиса ещё нет.
        ARTIFACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_FILE.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8"
        )
        print(f"      сохранено в {ARTIFACTS_FILE.relative_to(ROOT)}")

        if RENDER_API_KEY and not args.no_render:
            service_id = find_render_service()
            set_env(service_id, values)
            trigger_deploy(service_id)
            print("[5/5] Переменные переданы в Render, деплой запущен")
            url = f"https://{SERVICE_NAME}.onrender.com"
            print("      ждём /api/health…")
            print("      сервер готов" if wait_healthy(url) else "      сервер пока не отвечает — смотрите логи Render")
        elif args.no_render:
            print("[5/5] Render пропущен (--no-render): значения передаст deploy_render.py")
        else:
            print("[5/5] RENDER_API_KEY не задан: значения передаст deploy_render.py позже")

        print("\nМанифест для лаунчера обновлён.")
    except PublishError as exc:
        print(f"\nОШИБКА:\n{exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nОШИБКА упаковки: код {exc.returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
