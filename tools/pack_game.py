"""Упаковка портативной среды Aurum в game.zip для раздачи лаунчеру.

Build-инструмент (запускается разработчиком, не игроком):
    python tools/pack_game.py --source "C:\\Users\\...\\Dimasik Portable" --out build/game.zip

Внутри архива — содержимое папки клиента: RUN-DIMASIK.bat, offline-run/, python/ и т. д.
Исключаются логи, сохранения, кеши и пользовательские файлы.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sys
import time
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {
    "temp",
    "logs",
    "saves",
    "crash-reports",
    "downloads",
    "__pycache__",
    ".git",
    ".gradle",
    ".idea",
    "screenshots",
    # кеш Edge и временный профиль браузера — к игре отношения не имеет
    "profile",
}

# Клиент ставит лаунчер (aurum.jar). Если оставить его в архиве, мод
# загрузится дважды и игра упадёт на дубликате mod id.
CLIENT_JAR_PATTERNS = ("dimasik-offline.jar", "dimasik-*.jar", "aurum*.jar")

EXCLUDE_FILES = {
    "options.txt",
    "usercache.json",
    "command_history.txt",
    "servers.dat_old",
    "launcher_accounts.json",
    "launcher_log.txt",
    "latest.log",
    # личные данные разработчика: аккаунты, друзья, серверы, макросы
    "accounts.conf",
    "friend.conf",
    "servers.conf",
    "macro.conf",
    "bot-macros.json",
}

EXCLUDE_SUFFIXES = (".log", ".tmp", ".part", ".lnk")

CHUNK = 4 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def collect(source: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDE_DIRS]
        for name in names:
            lower = name.lower()
            if lower in EXCLUDE_FILES or lower.endswith(EXCLUDE_SUFFIXES):
                continue
            if any(fnmatch.fnmatch(lower, pattern) for pattern in CLIENT_JAR_PATTERNS):
                continue
            files.append(Path(root) / name)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Собрать game.zip из папки портативного клиента")
    parser.add_argument("--source", required=True, help="папка клиента (где лежит RUN-DIMASIK.bat)")
    parser.add_argument("--out", default="build/game.zip", help="куда положить архив")
    parser.add_argument("--level", type=int, default=6, help="сжатие 0-9")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not (source / "RUN-DIMASIK.bat").is_file():
        print(f"В {source} нет RUN-DIMASIK.bat — это не папка клиента", file=sys.stderr)
        return 1

    output = Path(args.out)
    if not output.is_absolute():
        output = (Path(__file__).resolve().parent.parent / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = collect(source)
    print(f"Файлов: {len(files)} · исходный размер: {sum(f.stat().st_size for f in files) // (1024 * 1024)} МБ")
    print(f"Архив: {output}")

    started = time.time()
    written = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=args.level) as bundle:
        for index, path in enumerate(files, 1):
            bundle.write(path, path.relative_to(source).as_posix())
            written += 1
            if written % 400 == 0 or written == len(files):
                percent = written * 100 // len(files)
                print(f"  {percent:3d}%  {written}/{len(files)}  ({time.time() - started:.0f} c)")

    size = output.stat().st_size
    print(f"\nГотово за {time.time() - started:.0f} c")
    print(f"  файл:   {output}")
    print(f"  размер: {size} байт ({size / 1024 / 1024:.0f} МБ)")
    print(f"  sha256: {sha256(output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
