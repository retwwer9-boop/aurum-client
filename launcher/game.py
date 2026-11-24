"""Среда игры внутри %APPDATA%\\AurumClient.

Лаунчер ничего не ищет на рабочем столе: игра живёт только здесь.

    %APPDATA%\\AurumClient\\
        game\\            распакованная среда (RUN-DIMASIK.bat, offline-run, python…)
        cache\\           скачанные архивы
        state.json       версия установленной среды, дата, хеши
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "AurumClient"
GAME_DIR = APP_DIR / "game"
CACHE_DIR = APP_DIR / "cache"
STATE_FILE = APP_DIR / "state.json"

GAME_ARCHIVE = CACHE_DIR / "game.zip"
JAR_FILE = CACHE_DIR / "aurum.jar"
JAR_NAME = "aurum.jar"

# В сборке клиента моды лежат в offline-run/game/mods; в других сборках — в mods.
MODS_CANDIDATES = (
    Path("offline-run") / "game" / "mods",
    Path("game") / "mods",
    Path("mods"),
)

CHUNK = 1024 * 1024


class GameError(RuntimeError):
    pass


# ------------------------------------------------------------------- состояние


def prepare() -> None:
    """Создаёт каталоги лаунчера. Вызывается при старте."""
    for path in (APP_DIR, GAME_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(**values) -> None:
    state = {**read_state(), **values}
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def installed_version() -> str:
    return str(read_state().get("version") or "")


def game_dir() -> Path:
    return GAME_DIR


def launcher_bat() -> Path | None:
    for name in ("RUN-DIMASIK.bat", "run-dimasik.bat", "run.bat", "start.bat"):
        candidate = GAME_DIR / name
        if candidate.is_file():
            return candidate
    bats = sorted(p for p in GAME_DIR.glob("*.bat") if "uninstall" not in p.name.lower())
    return bats[0] if bats else None


def is_ready(version: str | None = None) -> bool:
    """Среда распакована, JAR на месте, версия совпадает."""
    if launcher_bat() is None or not jar_path().is_file():
        return False
    if version and installed_version() and installed_version() != version:
        return False
    return True


# ----------------------------------------------------------------- контрольные суммы


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    digest = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, size)
    return digest.hexdigest()


# ------------------------------------------------------------------- распаковка


def _strip_prefix(names: list[str]) -> str:
    """Если архив собран из папки (все пути с общим корнем) — отрезаем этот корень."""
    first = {name.split("/", 1)[0] for name in names if "/" in name}
    loose = any("/" not in name for name in names)
    if len(first) == 1 and not loose:
        return first.pop() + "/"
    return ""


def _unsafe(name: str) -> bool:
    """Абсолютные пути, диски и «..» — запрещены (zip-slip и запись вне папки игры)."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return True
    return any(part == ".." for part in normalized.split("/"))


def install_game(archive: Path, expected_sha256: str = "", on_extract: Callable[[int, int], None] | None = None) -> None:
    if not archive.is_file():
        raise GameError(f"Архив среды не найден: {archive}")

    if expected_sha256:
        actual = sha256_file(archive)
        if actual.lower() != expected_sha256.lower():
            archive.unlink(missing_ok=True)
            raise GameError("Контрольная сумма архива не совпала — скачайте клиент заново")

    GAME_DIR.mkdir(parents=True, exist_ok=True)
    root = GAME_DIR.resolve()

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [m for m in bundle.infolist() if not m.is_dir()]
            for member in members:
                if _unsafe(member.filename):
                    raise GameError(f"Небезопасный путь в архиве: {member.filename}")
            prefix = _strip_prefix([m.filename for m in members])
            total = sum(m.file_size for m in members) or 1
            done = 0

            for member in members:
                name = member.filename[len(prefix):] if prefix and member.filename.startswith(prefix) else member.filename
                if not name or name.endswith("/"):
                    continue
                target = (GAME_DIR / name).resolve()
                # zip-slip: путь обязан остаться внутри папки игры
                if not target.is_relative_to(root):
                    raise GameError(f"Небезопасный путь в архиве: {member.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination, CHUNK)
                done += member.file_size
                if on_extract:
                    on_extract(done, total)
    except zipfile.BadZipFile as exc:
        raise GameError("Архив повреждён, скачайте клиент заново") from exc

    if launcher_bat() is None:
        raise GameError("В архиве нет .bat-файла запуска — проверьте сборку на сервере")


def mods_dir() -> Path:
    """Куда игра реально смотрит моды: offline-run/game/mods в штатной сборке."""
    for relative in MODS_CANDIDATES:
        candidate = GAME_DIR / relative
        if candidate.is_dir():
            return candidate
    return GAME_DIR / MODS_CANDIDATES[0]


def jar_path() -> Path:
    return mods_dir() / JAR_NAME


def install_jar(jar: Path = JAR_FILE) -> Path:
    """Кладёт aurum.jar в папку модов распакованной среды."""
    if not jar.is_file():
        raise GameError("JAR клиента не скачан")
    destination = jar_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(jar, destination)
    return destination


# ----------------------------------------------------------------------- запуск


def launch() -> subprocess.Popen:
    bat = launcher_bat()
    if bat is None:
        raise GameError("Среда не установлена — нажмите «Установить клиент»")

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
    return subprocess.Popen(
        ["cmd", "/c", str(bat)],
        cwd=str(GAME_DIR),
        creationflags=flags,
        close_fds=True,
    )


def describe() -> str:
    bat = launcher_bat()
    return f"запуск через {bat.name}" if bat else "среда не установлена"
