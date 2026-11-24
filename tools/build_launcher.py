"""Сборка AurumLauncher.exe через PyInstaller.

    pip install pyinstaller pillow
    python tools/build_launcher.py

Результат: build/dist/AurumLauncher.exe и build/launcher.env
(хеш, размер, версия — их читает publish_launcher.py).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = BUILD / "dist"
ICON = BUILD / "aurum.ico"
WORK = BUILD / "pyinstaller"
ENV_FILE = BUILD / "launcher.env"

GOLD = (232, 181, 90, 255)
INK = (18, 16, 10, 255)


def make_icon() -> Path:
    """Рисует простую иконку: золотой квадрат с буквой A."""
    from PIL import Image, ImageDraw

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((12, 12, size - 12, size - 12), radius=58, fill=GOLD)
    draw.rounded_rectangle((26, 26, size - 26, size - 26), radius=46, outline=(255, 255, 255, 70), width=3)

    draw.line([(128, 62), (84, 194)], fill=INK, width=22, joint="curve")
    draw.line([(128, 62), (172, 194)], fill=INK, width=22, joint="curve")
    draw.line([(103, 152), (153, 152)], fill=INK, width=20)

    BUILD.mkdir(parents=True, exist_ok=True)
    image.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ICON


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    try:
        icon = make_icon()
    except ImportError:
        print("Нет Pillow — собираю без иконки (pip install pillow)", file=sys.stderr)
        icon = None

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "AurumLauncher",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT),
    ]
    if icon is not None:
        command += ["--icon", str(icon)]
    command.append(str(ROOT / "launcher_entry.py"))

    print("Сборка:", " ".join(command))
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        print("PyInstaller завершился с ошибкой", file=sys.stderr)
        return result.returncode

    exe = DIST / "AurumLauncher.exe"
    if not exe.is_file():
        print(f"Не найден {exe}", file=sys.stderr)
        return 1

    version = time.strftime("%Y.%m.%d")
    size = exe.stat().st_size
    digest = sha256(exe)

    ENV_FILE.write_text(
        f"LAUNCHER_PATH={exe}\n"
        f"LAUNCHER_SHA256={digest}\n"
        f"LAUNCHER_SIZE={size}\n"
        f"LAUNCHER_VERSION={version}\n",
        encoding="utf-8",
    )

    print(f"\nГотово: {exe}")
    print(f"  размер: {size / 1024 / 1024:.1f} МБ")
    print(f"  sha256: {digest}")
    print(f"  метаданные: {ENV_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
