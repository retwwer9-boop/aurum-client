"""Публикация AurumLauncher.exe в GitHub Releases + переменные Render.

    python publish_launcher.py                       # берёт build/dist/AurumLauncher.exe
    python publish_launcher.py --no-render           # только GitHub
    python publish_launcher.py --tag launcher-v2     # свой тег

Хеш и размер попадают в build/artifacts.env, поэтому deploy_render.py
передаст их в Render даже без RENDER_API_KEY.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import publish_assets as assets
from publish_assets import (
    ARTIFACTS_FILE,
    ROOT,
    PublishError,
    RENDER_API_KEY,
    ensure_assets_repo,
    ensure_release,
    sha256,
    upload_asset,
)

DEFAULT_EXE = ROOT / "build" / "dist" / "AurumLauncher.exe"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Опубликовать лаунчер")
    parser.add_argument("--exe", default=str(DEFAULT_EXE))
    parser.add_argument("--tag", help="тег релиза, по умолчанию launcher-<дата>")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    exe = Path(args.exe)
    if not exe.is_absolute():
        exe = (ROOT / exe).resolve()
    if not exe.is_file():
        print(f"Нет файла {exe}. Сначала: python tools/build_launcher.py", file=sys.stderr)
        return 1

    try:
        tag = args.tag or time.strftime("launcher-%Y.%m.%d")
        size = exe.stat().st_size
        digest = sha256(exe)
        print(f"      AurumLauncher.exe {size / 1024 / 1024:.1f} МБ  sha256 {digest[:16]}…")

        owner, repo = ensure_assets_repo()
        full_repo = f"{owner}/{repo}"
        release = ensure_release(full_repo, tag)
        upload_asset(full_repo, release["id"], exe, "AurumLauncher.exe")

        values = {
            "LAUNCHER_URL": f"https://github.com/{full_repo}/releases/download/{tag}/AurumLauncher.exe",
            "LAUNCHER_SHA256": digest,
            "LAUNCHER_SIZE": str(size),
            "LAUNCHER_VERSION": tag,
        }

        merged = {**read_env(ARTIFACTS_FILE), **values}
        write_env(ARTIFACTS_FILE, merged)

        print("[4/5] Ссылка:")
        for key, value in values.items():
            print(f"      {key}={value}")
        print(f"      сохранено в {ARTIFACTS_FILE.relative_to(ROOT)}")

        if RENDER_API_KEY and not args.no_render:
            service_id = assets.find_render_service()
            assets.set_env(service_id, values)
            assets.trigger_deploy(service_id)
            print("[5/5] Переменные переданы в Render, деплой запущен")
        elif args.no_render:
            print("[5/5] Render пропущен (--no-render)")
        else:
            print("[5/5] RENDER_API_KEY не задан — значения передаст deploy_render.py")
    except PublishError as exc:
        print(f"\nОШИБКА:\n{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
