"""Страницы сайта: лендинг, вход, кабинет, покупка подписки."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..plans import PLANS

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIR = ROOT / "web"

templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

router = APIRouter(tags=["site"])


def _context(request: Request, **extra) -> dict:
    return {
        "request": request,
        "plans": [plan.to_public() for plan in PLANS],
        "payments_enabled": settings.payments_enabled,
        "launcher_url": settings.launcher_url,
        "launcher_size": settings.launcher_size,
        "launcher_version": settings.launcher_version,
        "support_telegram": settings.support_telegram,
        "support_email": settings.support_email,
        "game_version": settings.game_version,
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", _context(request, page="home"))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", _context(request, page="login"))


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "register.html", _context(request, page="register"))


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "account.html", _context(request, page="account"))


@router.get("/buy", response_class=HTMLResponse)
def buy_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "buy.html", _context(request, page="buy"))


@router.get("/buy/success", response_class=HTMLResponse)
def buy_success(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "success.html", _context(request, page="buy"))


@router.get("/legal", response_class=HTMLResponse)
def legal_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "legal.html", _context(request, page="legal"))


@router.get("/download/launcher")
def download_launcher() -> RedirectResponse:
    if settings.launcher_url:
        return RedirectResponse(settings.launcher_url, status_code=302)
    return RedirectResponse("/account#launcher", status_code=302)
