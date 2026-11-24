"""Окно лаунчера Aurum.

Игра ставится только в %APPDATA%\\AurumClient\\game — поиска папок на диске нет.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import game
from .api import DEFAULT_API_URL, ApiError, AurumClient
from .hwid import get_hwid

BG = "#12141c"
PANEL = "#1a1d27"
FIELD = "#232735"
TEXT = "#eef1f7"
MUTED = "#8f97ab"
ACCENT = "#7f94dd"
ACCENT_DARK = "#5f74bd"
DANGER = "#e08a8a"
OK = "#8fd6a8"

SETTINGS_DIR = game.APP_DIR
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Aurum Client")
        self.geometry("600x700")
        self.minsize(560, 640)
        self.configure(bg=BG)

        game.prepare()

        self.settings = load_settings()
        self.client: AurumClient | None = None
        self.profile: dict = {}
        self.manifest: dict | None = None
        self.busy = False
        # Рабочие потоки не трогают Tk напрямую: они кладут задачи в очередь,
        # а главный поток выполняет их в _drain.
        self._events: queue.Queue = queue.Queue()

        self._build_login()
        self._load_saved()
        self.after(30, self._drain)

    # ------------------------------------------------------------------ виджеты

    def _label(self, parent, text, size=10, color=TEXT, bold=False, **kw):
        return tk.Label(
            parent,
            text=text,
            bg=kw.pop("bg", BG),
            fg=color,
            font=("Segoe UI", size, "bold" if bold else "normal"),
            **kw,
        )

    def _entry(self, parent, **kw):
        return tk.Entry(
            parent,
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground="#2f3446",
            highlightcolor=ACCENT,
            **kw,
        )

    def _button(self, parent, text, command, primary=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=ACCENT if primary else FIELD,
            fg="#0e1017" if primary else TEXT,
            activebackground=ACCENT_DARK if primary else "#2c3144",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            padx=12,
            pady=7,
            bd=0,
        )

    def _build_login(self) -> None:
        self.login_frame = tk.Frame(self, bg=BG)
        self.login_frame.pack(fill="both", expand=True, padx=34, pady=(30, 24))

        self._label(self.login_frame, "Aurum", 26, TEXT, True).pack(anchor="w")
        self._label(self.login_frame, "Client · вход в аккаунт", 10, MUTED).pack(anchor="w", pady=(0, 20))

        self.api_entry = self._field("Адрес API", DEFAULT_API_URL)
        self.user_entry = self._field("Логин")
        self.pass_entry = self._field("Пароль", show="•")

        self.login_status = self._label(self.login_frame, "", 9, MUTED, wraplength=480, justify="left")
        self.login_status.pack(anchor="w", pady=(6, 12))

        row = tk.Frame(self.login_frame, bg=BG)
        row.pack(fill="x")
        self.login_button = self._button(row, "Войти", lambda: self._submit(False), primary=True)
        self.login_button.pack(side="left", fill="x", expand=True)
        self.register_button = self._button(row, "Регистрация", lambda: self._submit(True))
        self.register_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self._label(
            self.login_frame,
            "Логин и пароль от сайта. Игра и клиент скачиваются на этот компьютер\n"
            f"и больше никуда не копируются.\nПапка установки: {game.APP_DIR}",
            9,
            "#6f778b",
            justify="left",
        ).pack(anchor="w", pady=(16, 0))

        self.bind_all("<Return>", self._on_return)

    def _on_return(self, _event=None) -> None:
        if self.login_frame.winfo_ismapped() and not self.busy:
            self._submit(False)

    def _field(self, title: str, value: str = "", show: str | None = None) -> tk.Entry:
        self._label(self.login_frame, title, 9, MUTED).pack(anchor="w")
        entry = self._entry(self.login_frame, show=show)
        if value:
            entry.insert(0, value)
        entry.pack(fill="x", ipady=7, pady=(4, 12))
        return entry

    def _build_main(self) -> None:
        self.main_frame = tk.Frame(self, bg=BG)
        self.main_frame.pack(fill="both", expand=True, padx=26, pady=18)

        top = tk.Frame(self.main_frame, bg=PANEL)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=PANEL)
        inner.pack(fill="x", padx=16, pady=12)

        self.user_label = self._label(inner, "", 12, TEXT, True, bg=PANEL)
        self.user_label.pack(anchor="w")
        self.sub_label = self._label(inner, "", 9, MUTED, bg=PANEL)
        self.sub_label.pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(inner, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        self.refresh_button = self._button(actions, "Обновить статус", self._refresh_profile)
        self.refresh_button.pack(side="left")
        self.logout_button = self._button(actions, "Выйти", self._logout)
        self.logout_button.pack(side="left", padx=(8, 0))

        self._label(self.main_frame, "Папка установки", 9, MUTED).pack(anchor="w", pady=(18, 4))
        path_row = tk.Frame(self.main_frame, bg=BG)
        path_row.pack(fill="x")
        self.path_entry = self._entry(path_row)
        self.path_entry.insert(0, str(game.APP_DIR))
        self.path_entry.configure(state="readonly", readonlybackground=FIELD)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self._button(path_row, "Открыть", self._open_folder).pack(side="left", padx=(8, 0))

        action_row = tk.Frame(self.main_frame, bg=BG)
        action_row.pack(fill="x", pady=(16, 6))
        self.install_button = self._button(action_row, "Установить клиент", self._install, primary=True)
        self.install_button.pack(side="left", fill="x", expand=True)
        self.play_button = self._button(action_row, "Играть", self._play)
        self.play_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.progress = ttk.Progressbar(self.main_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(12, 6))

        self.status_label = self._label(self.main_frame, "", 9, MUTED, wraplength=520, justify="left")
        self.status_label.pack(anchor="w")

        self.log_box = tk.Text(
            self.main_frame,
            height=10,
            bg="#0d0f16",
            fg="#a9b3c9",
            insertbackground=TEXT,
            relief="flat",
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
            padx=10,
            pady=8,
        )
        self.log_box.pack(fill="both", expand=True, pady=(10, 0))

    # ------------------------------------------------------------------ утилиты

    def _ui(self, callback, *args) -> None:
        """Из любого потока: задача уходит в очередь главного потока."""
        self._events.put((callback, args))

    def _drain(self) -> None:
        while True:
            try:
                callback, args = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except tk.TclError as exc:  # окно закрыли, пока шла работа
                if "application has been destroyed" not in str(exc):
                    raise
        if self.winfo_exists():
            self.after(30, self._drain)

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _status(self, message: str, color: str = MUTED) -> None:
        self.status_label.configure(text=message, fg=color)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.refresh_button, self.install_button, self.play_button, self.logout_button):
            widget.configure(state=state)

    def _background(self, work, done=None, error=None) -> None:
        def runner() -> None:
            try:
                result = work()
            except (ApiError, game.GameError) as exc:
                message = exc.detail if isinstance(exc, ApiError) else str(exc)
                self._ui(error or self._fail, message)
            except Exception as exc:  # noqa: BLE001 — показываем причину, а не падаем молча
                self._ui(error or self._fail, f"Ошибка: {exc}")
            else:
                if done:
                    self._ui(done, result)

        threading.Thread(target=runner, daemon=True).start()

    def _fail(self, message: str) -> None:
        self._set_busy(False)
        self._status(message, DANGER)
        self._log(f"Ошибка: {message}")

    def _load_saved(self) -> None:
        self.api_entry.delete(0, "end")
        self.api_entry.insert(0, self.settings.get("api_url") or DEFAULT_API_URL)
        if self.settings.get("username"):
            self.user_entry.insert(0, self.settings["username"])
        self.pass_entry.focus_set()

    def _open_folder(self) -> None:
        game.prepare()
        try:
            os.startfile(str(game.APP_DIR))  # type: ignore[attr-defined]
        except OSError as exc:
            self._status(f"Не удалось открыть папку: {exc}", DANGER)

    # ------------------------------------------------------------------ вход

    def _submit(self, register: bool) -> None:
        if self.busy:
            return
        api_url = self.api_entry.get().strip().rstrip("/")
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()

        if not api_url.startswith(("http://", "https://")):
            self.login_status.configure(text="Адрес API должен начинаться с https://", fg=DANGER)
            return
        if len(username) < 3 or len(password) < 8:
            self.login_status.configure(text="Логин от 3 символов, пароль от 8", fg=DANGER)
            return

        self.login_button.configure(state="disabled")
        self.register_button.configure(state="disabled")
        self.login_status.configure(
            text="Регистрирую аккаунт…" if register else "Проверяю логин и пароль…", fg=MUTED
        )

        def work() -> dict:
            client = AurumClient(api_url)
            try:
                hwid = get_hwid()
            except Exception:  # noqa: BLE001 — HWID не критичен для входа
                hwid = None
            payload = (
                client.register(username, password, hwid)
                if register
                else client.login(username, password, hwid)
            )
            return {"client": client, "payload": payload}

        def done(result: dict) -> None:
            self.client = result["client"]
            self.settings.update({"api_url": api_url, "username": username})
            save_settings(self.settings)
            self.profile = result["payload"]
            self.login_status.configure(text="", fg=MUTED)
            self._show_main()

        def fail(message: str) -> None:
            self.login_status.configure(text=message, fg=DANGER)
            self.login_button.configure(state="normal")
            self.register_button.configure(state="normal")

        self._background(work, done, fail)

    def _show_main(self) -> None:
        self.login_frame.pack_forget()
        if not hasattr(self, "main_frame"):
            self._build_main()
        self.main_frame.pack(fill="both", expand=True, padx=26, pady=18)
        self._apply_profile()
        if self.client:
            self._log(f"Подключено к {self.client.base_url}")
        self.after(150, self._check_environment)

    def _apply_profile(self) -> None:
        user = self.profile.get("user", {})
        sub = self.profile.get("subscription", {})
        self.user_label.configure(text=user.get("username", "—"))
        if sub.get("active"):
            self.sub_label.configure(
                text=f"Подписка {sub.get('plan', '')} · до {str(sub.get('expires_at'))[:10]} "
                f"· осталось {sub.get('days_left', 0)} дн.",
                fg=OK,
            )
        else:
            self.sub_label.configure(text="Подписка неактивна", fg=DANGER)
            self._status("Подписка неактивна — клиент скачать нельзя. Напишите в поддержку.", DANGER)

    # ------------------------------------------------------------------ среда

    def _check_environment(self) -> None:
        """Сверяет локальную версию с сервером; при первом входе ставит клиент сам."""
        if not self.client or self.busy:
            return
        self._set_busy(True)
        self._status("Проверяю версию клиента…")

        def work() -> dict:
            return {"manifest": self.client.manifest(), "ready": game.is_ready()}

        def done(result: dict) -> None:
            self._set_busy(False)
            self.manifest = result["manifest"]
            version = self.manifest.get("version", "")
            game_entry = self.manifest.get("game")

            if not game_entry:
                self._status("Среда игры ещё не опубликована на сервере — сообщите администратору.", DANGER)
                return

            if game.is_ready(version):
                self._status(f"Клиент установлен (v{version}) · {game.describe()}", OK)
                self._log(f"Папка игры: {game.GAME_DIR} · версия {version}")
                return

            self._log("Клиент не установлен или устарел — скачиваю автоматически.")
            self._install()

        self._background(work, done, self._fail)

    def _phase(self, start: int, end: int):
        last = [-1]

        def mapper(done: int, total: int) -> None:
            percent = start + (end - start) * (min(done, total) / total if total else 0)
            rounded = int(percent)
            if rounded == last[0]:  # не заваливаем Tk событиями на каждый файл
                return
            last[0] = rounded
            self._ui(self._set_progress, percent)

        return mapper

    def _set_progress(self, percent: float) -> None:
        self.progress.configure(value=max(0.0, min(100.0, percent)))

    def _install(self, then=None) -> None:
        if self.busy or not self.client:
            return
        if not self.manifest:
            self._check_environment()
            return

        game_entry = self.manifest.get("game") or {}
        jar_entry = self.manifest.get("jar") or {}
        if not game_entry:
            self._status("Среда игры не опубликована на сервере", DANGER)
            return

        self._set_busy(True)
        self.progress.configure(value=0)
        self._status("Скачиваю среду игры (первый раз это долго)…")

        def work() -> dict:
            game.GAME_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)

            self._ui(self._log, "Загрузка game.zip…")
            self.client.download(game_entry["url"], game.GAME_ARCHIVE, progress=self._phase(0, 70))

            if jar_entry:
                self._ui(self._log, "Загрузка aurum.jar…")
                self.client.download(jar_entry["url"], game.JAR_FILE, progress=self._phase(70, 82))

            self._ui(self._log, "Распаковка среды и установка модов…")
            game.install_game(
                game.GAME_ARCHIVE,
                expected_sha256=str(game_entry.get("sha256") or ""),
                on_extract=self._phase(82, 98),
            )
            destination = game.install_jar(game.JAR_FILE)
            game.write_state(
                version=str(self.manifest.get("version") or ""),
                installed_at=int(time.time()),
                sha256=str(game_entry.get("sha256") or ""),
            )
            return destination

        def done(destination: Path) -> None:
            self.progress.configure(value=100)
            self._set_busy(False)
            self._status("Клиент установлен", OK)
            self._log(f"Готово: {destination}")
            self._log(f"Среда: {game.GAME_DIR}")
            if then:
                then()

        self._background(work, done, self._fail)

    # ------------------------------------------------------------------ действия

    def _refresh_profile(self) -> None:
        if self.busy or not self.client:
            return
        self._set_busy(True)

        def done(payload: dict) -> None:
            self.profile = payload
            self._apply_profile()
            self._set_busy(False)
            self._status("Статус обновлён", OK)

        self._background(self.client.me, done, self._fail)

    def _logout(self) -> None:
        if self.client:
            self._background(self.client.logout)
        self.client = None
        self.profile = {}
        self.manifest = None
        self.main_frame.pack_forget()
        self.pass_entry.delete(0, "end")
        self.login_frame.pack(fill="both", expand=True, padx=34, pady=(30, 24))
        self.login_button.configure(state="normal")
        self.register_button.configure(state="normal")
        self._set_busy(False)

    def _play(self) -> None:
        if self.busy or not self.client:
            return

        version = str((self.manifest or {}).get("version") or "")
        if not game.is_ready(version):
            self._log("Клиент не установлен — сначала скачиваю.")
            self._install(then=self._play)
            return

        self._set_busy(True)

        def work() -> int:
            return game.launch().pid

        def done(pid: int) -> None:
            self._set_busy(False)
            self._status(f"Игра запущена (PID {pid})", OK)
            self._log(f"Запуск: {game.describe()} из {game.GAME_DIR}")

        self._background(work, done, self._fail)


def main() -> None:
    Launcher().mainloop()


if __name__ == "__main__":
    main()
