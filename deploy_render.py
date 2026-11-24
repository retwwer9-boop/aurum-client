"""Полностью автономный деплой Aurum Client.

Что делает без единой ручной команды:
  1. читает токены из окружения или deploy.env;
  2. создаёт приватный репозиторий aurum-client через GitHub API;
  3. делает git init / commit / push сам;
  4. создаёт Postgres и Web Service на Render через API;
  5. прописывает переменные окружения и ждёт статус live.

Запуск (токены — в переменных окружения или в deploy.env рядом со скриптом):
    python deploy_render.py --check    # проверить токены, ничего не создавая
    python deploy_render.py            # полный деплой
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / "deploy.env"
ARTIFACTS_FILE = ROOT / "build" / "artifacts.env"
CREDENTIALS_FILE = ROOT / "build" / "credentials.env"

REPO_NAME = os.environ.get("GITHUB_REPO", "aurum-client")
SERVICE_NAME = os.environ.get("RENDER_SERVICE_NAME", "aurum-auth")
DB_NAME = os.environ.get("RENDER_DB_NAME", "aurum-db")
BRANCH = "main"
REGION = os.environ.get("RENDER_REGION", "frankfurt")
PLAN = "free"
PYTHON_VERSION = "3.12.7"
BUILD_COMMAND = "pip install -r requirements.txt"
START_COMMAND = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
HEALTH_PATH = "/api/health"

RENDER_API = "https://api.render.com/v1"
GITHUB_API = "https://api.github.com"

PASSTHROUGH_ENV = (
    "GAME_URL",
    "GAME_SHA256",
    "GAME_SIZE",
    "GAME_VERSION",
    "JAR_URL",
    "JAR_SHA256",
    "JAR_SIZE",
    "LAUNCHER_URL",
    "LAUNCHER_SHA256",
    "LAUNCHER_SIZE",
    "LAUNCHER_VERSION",
    "PUBLIC_BASE_URL",
    "SUPPORT_TELEGRAM",
    "SUPPORT_EMAIL",
    "YOOKASSA_SHOP_ID",
    "YOOKASSA_SECRET_KEY",
    "ALLOW_REGISTRATION",
    "CORS_ORIGINS",
)

CHECK_ONLY = "--check" in sys.argv
NO_DB = "--no-db" in sys.argv
PUBLIC_REPO = "--public" in sys.argv

REQUIRED_FILES = (
    "requirements.txt",
    "render.yaml",
    "app/main.py",
    "app/config.py",
    "launcher/__main__.py",
)


class DeployError(RuntimeError):
    pass


# ------------------------------------------------------------------ конфигурация


def load_env_file(path: Path) -> None:
    """Подхватывает KEY=VALUE, не перетирая уже заданные переменные."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


load_env_file(ENV_FILE)
# Ссылки на game.zip/aurum.jar, сохранённые publish_assets.py
load_env_file(ARTIFACTS_FILE)

RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# Некоторые провайдеры блокируют штатные адреса Render (216.24.57.x).
# RENDER_EDGE_IP позволяет ходить через другой edge Cloudflare с тем же SNI.
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


def mask(value: str) -> str:
    return f"{value[:7]}…{value[-4:]}" if len(value) > 12 else "—"


# ------------------------------------------------------------------------- HTTP


def _http(url: str, method: str = "GET", body: dict | None = None, token: str | None = None,
          headers: dict | None = None, timeout: float = 180.0, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "aurum-deploy/2.0")
    if data is not None and raw is None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise DeployError(f"{method} {url} → HTTP {exc.code}\n{detail[:1500]}") from None
    except urllib.error.URLError as exc:
        raise DeployError(f"Нет связи с {url}: {exc.reason}") from None

    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8", "replace")


def github(method: str, path: str, body: dict | None = None):
    if not GITHUB_TOKEN:
        raise DeployError("GITHUB_TOKEN не задан")
    return _http(GITHUB_API + path, method, body, GITHUB_TOKEN,
                 headers={"X-GitHub-Api-Version": "2022-11-28"})


def render(method: str, path: str, body: dict | None = None):
    if not RENDER_API_KEY:
        raise DeployError("RENDER_API_KEY не задан")
    return _http(RENDER_API + path, method, body, RENDER_API_KEY)


def unwrap(payload, key: str):
    if isinstance(payload, dict) and key in payload:
        return payload[key]
    return payload


# ------------------------------------------------------------------------- git


def sh(args: list[str], check: bool = True) -> str:
    result = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise DeployError(f"{' '.join(args)} → код {result.returncode}\n{result.stderr.strip()[:1000]}")
    return ((result.stdout or "") + (result.stderr or "")).strip()


def git(*args: str, check: bool = True) -> str:
    return sh(["git", *args], check=check)


def ensure_repo() -> tuple[str, str, str]:
    """Создаёт приватный репозиторий, возвращает (owner, repo, clone_url)."""
    account = github("GET", "/user")
    owner = account["login"]

    exists = True
    try:
        github("GET", f"/repos/{owner}/{REPO_NAME}")
    except DeployError as exc:
        if "HTTP 404" in str(exc):
            exists = False
        else:
            raise

    if not exists:
        try:
            github("POST", "/user/repos", {
                "name": REPO_NAME,
                "private": not PUBLIC_REPO,
                "auto_init": False,
            })
            print(f"[2/6] Репозиторий создан: {owner}/{REPO_NAME} ({'public' if PUBLIC_REPO else 'private'})")
        except DeployError as exc:
            if "already exists" not in str(exc):
                raise
    else:
        print(f"[2/6] Репозиторий уже существует: {owner}/{REPO_NAME}")

    return owner, REPO_NAME, f"https://github.com/{owner}/{REPO_NAME}"


def push_code(clone_url: str, owner: str) -> str:
    if not (ROOT / ".git").is_dir():
        git("init", "-b", BRANCH)
    git("config", "user.name", owner)
    git("config", "user.email", f"{owner}@users.noreply.github.com")
    git("add", "-A")
    git("commit", "-m", "Aurum Client: backend, launcher, deploy", check=False)

    auth_url = clone_url.replace("https://", f"https://x-access-token:{GITHUB_TOKEN}@")
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", auth_url)
    try:
        git("push", "-u", "origin", f"{BRANCH}:{BRANCH}", "--force")
    finally:
        git("remote", "set-url", "origin", clone_url, check=False)

    head = git("rev-parse", "--short", "HEAD")
    print(f"[3/6] Код отправлен в GitHub (commit {head})")
    return head


# ---------------------------------------------------------------------- Render


def owner_id() -> str:
    owners = render("GET", "/owners?limit=1") or []
    if not owners:
        raise DeployError("Render: workspace не найден")
    return unwrap(owners[0], "owner")["id"]


def find_service() -> dict | None:
    for item in render("GET", f"/services?name={SERVICE_NAME}&limit=50") or []:
        service = unwrap(item, "service")
        if service.get("name") == SERVICE_NAME:
            return service
    return None


def ensure_postgres(owner: str) -> str | None:
    if os.environ.get("DATABASE_URL", "").strip():
        print("[4/6] Использую DATABASE_URL из окружения (внешняя база)")
        return os.environ["DATABASE_URL"].strip()

    if NO_DB:
        print("[4/6] Postgres пропущен (--no-db)")
        return None

    for item in render("GET", "/postgres?limit=100") or []:
        candidate = unwrap(item, "postgres")
        if candidate.get("name") == DB_NAME:
            print(f"[4/6] Postgres уже существует: {DB_NAME}")
            return _wait_database(candidate["id"])

    try:
        created = render("POST", "/postgres", {
            "name": DB_NAME,
            "ownerId": owner,
            "plan": "free",
            "region": REGION,
            "version": "16",
            "databaseName": "aurum",
            "user": "aurum",
        })
    except DeployError as exc:
        print(f"[4/6] Postgres создать не удалось: {exc}")
        print("      Аккаунты останутся в SQLite и сотрутся при рестарте Render.")
        return None

    database = unwrap(created, "postgres")
    print(f"[4/6] Postgres создаётся: {database.get('id')}")
    return _wait_database(database["id"])


def _wait_database(database_id: str, timeout: float = 600.0) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        database = unwrap(render("GET", f"/postgres/{database_id}"), "postgres") or {}
        status = str(database.get("status", ""))
        if status in {"available", "ready"}:
            # Строка подключения лежит в отдельном endpoint: в объекте базы её нет.
            info = render("GET", f"/postgres/{database_id}/connection-info") or {}
            url = info.get("internalConnectionString") or info.get("externalConnectionString")
            if url:
                print("[4/6] Postgres готов")
                expires = database.get("expiresAt")
                if expires:
                    print(f"      бесплатный Postgres действует до {str(expires)[:10]}")
                return url
        if status in {"creation_failed", "unavailable"}:
            print(f"[4/6] Postgres в статусе {status}")
            return None
        time.sleep(5)
    print("[4/6] Postgres не стал доступен за 10 минут")
    return None


def ensure_service(owner: str, clone_url: str) -> dict:
    service = find_service()
    if service:
        print(f"[5/6] Сервис {SERVICE_NAME} уже существует")
        return service

    secret_key = secrets.token_urlsafe(48)
    admin_token = secrets.token_urlsafe(32)

    payload = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner,
        "repo": clone_url,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "python",
            "plan": PLAN,
            "region": REGION,
            "healthCheckPath": HEALTH_PATH,
            "envSpecificDetails": {
                "buildCommand": BUILD_COMMAND,
                "startCommand": START_COMMAND,
            },
        },
        "envVars": [
            {"key": "PYTHON_VERSION", "value": PYTHON_VERSION},
            {"key": "SECRET_KEY", "value": secret_key},
            {"key": "ADMIN_TOKEN", "value": admin_token},
        ],
    }
    try:
        created = render("POST", "/services", payload)
    except DeployError as exc:
        text = str(exc)
        if "repo" in text.lower() or "not found" in text.lower() or "github" in text.lower():
            raise DeployError(
                f"{text}\n\n"
                "Похоже, Render не видит приватный репозиторий.\n"
                "Один раз в браузере: Render Dashboard → Account Settings → GitHub →\n"
                "Configure → дать доступ к репозиторию aurum-client → Save.\n"
                "После этого просто запустите скрипт снова — он продолжит с этого шага.\n"
                "Либо запустите `python deploy_render.py --public`, если приватность не нужна."
            ) from None
        raise

    service = unwrap(created, "service")
    print(f"[5/6] Сервис создан: {service.get('id')}")
    save_credentials(admin_token, secret_key)
    return service


def save_credentials(admin_token: str, secret_key: str) -> None:
    """Кладёт админ-токен рядом с проектом: он нужен для выдачи подписок."""
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(
        f"SERVICE_URL=https://{SERVICE_NAME}.onrender.com\n"
        f"ADMIN_TOKEN={admin_token}\n"
        f"SECRET_KEY={secret_key}\n",
        encoding="utf-8",
    )
    print(f"[5/6] ADMIN_TOKEN сохранён в {CREDENTIALS_FILE.relative_to(ROOT)}")


def read_credentials() -> dict[str, str]:
    try:
        lines = CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    return dict(line.split("=", 1) for line in lines if "=" in line)


def set_env(service_id: str, key: str, value: str) -> None:
    render("PUT", f"/services/{service_id}/env-vars/{key}", {"value": value})


def trigger_deploy(service_id: str) -> str:
    payload = render("POST", f"/services/{service_id}/deploys", {"clearCache": "do_not_clear"})
    if isinstance(payload, dict):
        if payload.get("id"):
            return str(payload["id"])
        deploy = unwrap(payload, "deploy") or {}
        if deploy.get("id"):
            return str(deploy["id"])

    # API может вернуть объект без вложенности — берём самый свежий деплой.
    for item in render("GET", f"/services/{service_id}/deploys?limit=1") or []:
        return str(unwrap(item, "deploy").get("id") or "")
    return ""


def wait_deploy(service_id: str, deploy_id: str, timeout: float = 900.0) -> bool:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if deploy_id:
            deploy = unwrap(render("GET", f"/services/{service_id}/deploys/{deploy_id}"), "deploy") or {}
        else:
            items = render("GET", f"/services/{service_id}/deploys?limit=1") or []
            deploy = unwrap(items[0], "deploy") if items else {}
        status = str(deploy.get("status", ""))
        if status != last:
            print(f"      деплой: {status}")
            last = status
        if status in {"live", "deactivated"}:
            return status == "live"
        if status in {"build_failed", "update_failed", "canceled"}:
            print(f"      деплой остановлен: {status} (логи в Render Dashboard)")
            return False
        time.sleep(10)
    return False


# ------------------------------------------------------------------------- main


def preflight() -> None:
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).exists()]
    if missing:
        raise DeployError("В папке проекта нет файлов: " + ", ".join(missing))

    problems = []
    if not GITHUB_TOKEN:
        problems.append("GITHUB_TOKEN не задан")
    if not RENDER_API_KEY:
        problems.append("RENDER_API_KEY не задан")
    if problems:
        raise DeployError(
            "Не хватает токенов:\n  - " + "\n  - ".join(problems) +
            f"\n\nВпишите их в {ENV_FILE.name} (две строки) или в переменные окружения."
        )
    if not sh(["git", "--version"], check=False).startswith("git version"):
        raise DeployError("git не найден в PATH")


def main() -> int:
    try:
        preflight()
        print(f"[1/6] Токены: GitHub {mask(GITHUB_TOKEN)}, Render {mask(RENDER_API_KEY)}")

        owner = owner_id()
        print(f"[1/6] Render workspace: {owner}")

        if CHECK_ONLY:
            github_user = github("GET", "/user")["login"]
            print(f"      GitHub: {github_user}")
            print("Проверка пройдена. Запустите без --check для деплоя.")
            return 0

        owner_login, _, clone_url = ensure_repo()
        push_code(clone_url, owner_login)

        database_url = ensure_postgres(owner)
        service = ensure_service(owner, clone_url)
        service_id = service["id"]

        if database_url:
            set_env(service_id, "DATABASE_URL", database_url)

        pushed = {key: os.environ[key] for key in PASSTHROUGH_ENV if os.environ.get(key)}
        for key, value in pushed.items():
            set_env(service_id, key, value)
        if pushed:
            print(f"[5/6] Передано переменных: {', '.join(pushed)}")

        deploy_id = trigger_deploy(service_id)
        print(f"[6/6] Деплой запущен: {deploy_id}")
        ok = wait_deploy(service_id, deploy_id)
    except DeployError as exc:
        print(f"\nОШИБКА:\n{exc}", file=sys.stderr)
        return 1

    url = f"https://{SERVICE_NAME}.onrender.com"
    print("\nГотово." if ok else "\nДеплой не завершился успехом.")
    print(f"  Проверка: {url}/api/health")
    print(f"  Лаунчер:  укажите адрес API {url}")
    credentials = read_credentials()
    if credentials.get("ADMIN_TOKEN"):
        print(f"  ADMIN_TOKEN: {credentials['ADMIN_TOKEN']}")
        print(f"  (сохранён в {CREDENTIALS_FILE.relative_to(ROOT)})")
    else:
        print("  ADMIN_TOKEN: Render Dashboard → сервис → Environment")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
