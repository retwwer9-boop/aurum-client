"""Запуск деплоя Render через API.

Render не получает вебхуки GitHub для сервиса, созданного через API,
поэтому после push деплой нужно запускать явно:

    python tools/deploy.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "deploy.env"
DEFAULT_SERVICE_ID = "srv-dc2ome17lnhs73f2s970"


def read_env(name: str) -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    api_key = os.environ.get("RENDER_API_KEY", "").strip() or read_env("RENDER_API_KEY")
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip() or read_env("RENDER_SERVICE_ID") or DEFAULT_SERVICE_ID
    if not api_key:
        print("Нет RENDER_API_KEY (deploy.env)", file=sys.stderr)
        return 1

    body = json.dumps({"clearCache": "do_not_clear"}).encode()
    request = urllib.request.Request(
        f"https://api.render.com/v1/services/{service_id}/deploys",
        data=body,
        method="POST",
    )
    request.add_header("Authorization", "Bearer " + api_key)
    request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            deploy = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        print(f"Render вернул HTTP {exc.code}: {raw[:300]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"Render недоступен: {exc}", file=sys.stderr)
        return 1

    print(f"деплой {deploy.get('id')} — {deploy.get('status')}")
    print("следить: https://dashboard.render.com/web/" + service_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
