"""Включает оплату ЮKassa: читает yookassa.env, пишет ключи в Render, деплоит.

    python tools/enable_payments.py

Секреты в консоль не выводятся. Файл yookassa.env в .gitignore.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "yookassa.env"
DEFAULT_SERVICE_ID = "srv-dc2ome17lnhs73f2s970"

CARRY_KEYS = (
    "YOOKASSA_SHOP_ID",
    "YOOKASSA_SECRET_KEY",
    "SUPPORT_TELEGRAM",
    "SUPPORT_EMAIL",
)


def read_lines(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def render(method: str, path: str, payload: dict | None = None) -> dict:
    api_key = os.environ.get("RENDER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Нет RENDER_API_KEY")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request("https://api.render.com/v1" + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + api_key)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        print(f"Render HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        raise SystemExit(1) from None
    except (urllib.error.URLError, OSError) as exc:
        print(f"Render недоступен: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def main() -> int:
    values = read_lines(ENV_FILE)
    shop_id = values.get("YOOKASSA_SHOP_ID", "")
    secret = values.get("YOOKASSA_SECRET_KEY", "")
    if not shop_id or not secret:
        print(f"Заполните YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в {ENV_FILE.name}", file=sys.stderr)
        return 1
    if not shop_id.isdigit():
        print("YOOKASSA_SHOP_ID должен быть числом из личного кабинета ЮKassa", file=sys.stderr)
        return 1

    deploy_env = read_lines(ROOT / "deploy.env")
    os.environ.setdefault("RENDER_API_KEY", deploy_env.get("RENDER_API_KEY", ""))
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip() or DEFAULT_SERVICE_ID

    for key in CARRY_KEYS:
        value = values.get(key, "")
        if not value:
            continue
        render("PUT", f"/services/{service_id}/env-vars/{key}", {"value": value})
        visible = value if key.startswith("SUPPORT_") else "<скрыто>"
        print(f"{key} = {visible}")

    deploy = render("POST", f"/services/{service_id}/deploys", {"clearCache": "do_not_clear"})
    print(f"деплой {deploy.get('id')} — {deploy.get('status')}")
    print("после деплоя проверьте: /api/info → payments: yookassa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
