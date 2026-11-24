# Aurum Client — бэкенд на Render + изолированный лаунчер

Аккаунты и подписки на FastAPI, база в Postgres (Render) или SQLite (локально),
лаунчер на Tkinter. Лаунчер ничего не ищет на диске: игра ставится в
`%APPDATA%\AurumClient\game`, клиент — в её `mods`. Деплой и публикация файлов —
скриптами, без ручных команд git.

```
aurum-client/
├─ app/                        бэкенд FastAPI
│  ├─ main.py                  точка входа, CORS, /api/health
│  ├─ config.py                настройки из переменных окружения
│  ├─ database.py              SQLAlchemy: Postgres / SQLite
│  ├─ models.py                пользователь + подписка
│  ├─ schemas.py               валидация запросов
│  ├─ security.py              PBKDF2, JWT, лимит попыток
│  ├─ utils.py                 время, дни
│  └─ routes/
│     ├─ auth.py               /api/register, /api/login
│     ├─ account.py            /api/me, /api/subscription, /api/logout
│     ├─ admin.py              /api/admin/grant | revoke | reset-hwid | users
│     ├─ download.py           /api/download, /api/download/info
│     └─ launcher.py           /api/launcher/manifest, /api/launcher/game
├─ launcher/                   лаунчер (Tkinter, без зависимостей)
│  ├─ __main__.py              python -m launcher
│  ├─ ui.py                    окно входа и главное окно
│  ├─ api.py                   HTTP-клиент сервера
│  ├─ game.py                  папка %APPDATA%, установка архива, запуск
│  └─ hwid.py                  HWID (SHA-256 от железа)
├─ tools/pack_game.py          сборка game.zip из портативного клиента
├─ publish_assets.py           загрузка game.zip/aurum.jar в GitHub Releases
├─ deploy_render.py            создание репозитория, Postgres и сервиса на Render
├─ deploy.env.example          шаблон для токенов (сам deploy.env в .gitignore)
├─ render.yaml                 Blueprint для Render
├─ requirements.txt
└─ run_launcher.bat            запуск лаунчера без консоли
```

## 1. Как работает лаунчер

1. Создаёт `%APPDATA%\AurumClient\{game,cache}`.
2. После входа запрашивает `/api/launcher/manifest` — версию среды, ссылки, SHA-256.
3. Если версия не совпадает или среды нет — качает `game.zip`, проверяет SHA-256,
   распаковывает в `%APPDATA%\AurumClient\game` (с защитой от zip-slip).
4. Качает `aurum.jar`, кладёт его в `offline-run\game\mods` (или `game\mods`/`mods`,
   смотря что есть в сборке).
5. «Играть» запускает `RUN-DIMASIK.bat` из `%APPDATA%\AurumClient\game`.
6. Никаких копирований на рабочий стол и поиска папок по диску нет.

Скачивание и распаковка идут в фоновом потоке; Tk обновляется через очередь,
поэтому окно не зависает и не падает на «main thread is not in main loop».

## 2. Локальный запуск

```powershell
cd aurum-client
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:SECRET_KEY="local-secret-0123456789abcdef"
$env:ADMIN_TOKEN="local-admin"
.venv\Scripts\uvicorn app.main:app --port 8000
```

Проверка: `http://127.0.0.1:8000/api/health` → `{"status":"ok",...}`.
Локальная БД — `aurum.db`. Лаунчер: `python -m launcher` (или `run_launcher.bat`),
адрес API — `http://127.0.0.1:8000`.

## 3. API

| Метод | Путь | Тело / заголовок | Ответ |
|---|---|---|---|
| POST | `/api/register` | `{username, password, email?, hwid?}` | 201 + `access_token`, `user`, `subscription` |
| POST | `/api/login` | `{username, password, hwid?}` | 200 + токен, либо 401/403 |
| GET | `/api/me` | `Authorization: Bearer` | профиль + подписка |
| GET | `/api/subscription` | `Authorization: Bearer` | `{active, plan, expires_at, days_left}` |
| POST | `/api/logout` | `Authorization: Bearer` | инвалидирует все токены |
| GET | `/api/download` | `Authorization: Bearer` | `aurum.jar`, 403 без подписки |
| GET | `/api/launcher/manifest` | `Authorization: Bearer` | версия, ссылки, размеры, SHA-256 |
| GET | `/api/launcher/game` | `Authorization: Bearer` | `game.zip` или редирект на GitHub |
| POST | `/api/admin/grant` | `{username, days, plan}` + `X-Admin-Token` | продлевает подписку |
| POST | `/api/admin/revoke` | `{username}` + `X-Admin-Token` | отключает подписку |
| POST | `/api/admin/reset-hwid` | `{username}` + `X-Admin-Token` | разрешает вход с нового ПК |
| GET | `/api/admin/users` | `X-Admin-Token` | последние аккаунты |

Правила сервера:

- логин приводится к нижнему регистру, 3–32 символа, `[a-z0-9_.-]`;
- пароль 8–128 символов, PBKDF2-SHA256 (210 000 итераций, своя соль);
- JWT HS256 на 12 часов, привязан к `token_version` (выход = отзыв всех сессий);
- первый вход с `hwid` привязывает аккаунт к устройству, другой ПК → 403;
- подписка продлевается от даты окончания, а не от «сейчас»;
- 10 попыток входа в минуту с одного IP+логина.

## 4. Публикация клиента (один раз и при обновлениях)

Нужен `GITHUB_TOKEN` (classic, права `repo`). Токены читаются из `deploy.env`
или переменных окружения.

```powershell
Copy-Item deploy.env.example deploy.env   # вписать токены
```

Собрать архив и залить вместе с JAR:

```powershell
python publish_assets.py `
  --source "C:\Users\NEXUS\Desktop\Dimasik-26.2-Portable-Windows-x64\Dimasik Portable" `
  --jar    "C:\Users\NEXUS\Desktop\Dimasik-26.2-Portable-Windows-x64\Dimasik Portable\offline-run\game\mods\dimasik-offline.jar"
```

Если сервиса на Render ещё нет, добавьте `--no-render` — скрипт зальёт файлы
и сохранит ссылки в `build/artifacts.env`, откуда их возьмёт `deploy_render.py`.

Что произойдёт:

1. `tools/pack_game.py` соберёт `build/game.zip` (без `saves`, `logs`, `temp`,
   кеша Edge, личных конфигов аккаунтов/друзей/серверов и без клиентского JAR —
   иначе мод загрузится дважды).
2. Создастся публичный репозиторий `aurum-client-downloads` (файлы должны
   скачиваться без токена) и релиз с тегом-датой.
3. `game.zip` и `aurum.jar` загрузятся в релиз, посчитаются SHA-256 и размеры.
4. В Render уйдут `GAME_URL`, `GAME_SHA256`, `GAME_SIZE`, `GAME_VERSION`,
   `JAR_URL`, `JAR_SHA256`, `JAR_SIZE`; сервис перезапустится.
5. Ссылки дублируются в `build/artifacts.env` — их подхватывает деплой.

Текущая сборка: `game.zip` — 584 МБ, 5717 файлов, SHA-256
`eb3cc2c87c9b222283d94941ea1307027a1c164f3bee008b48d1421a5149322c`.

Только собрать архив, без публикации:

```powershell
python tools/pack_game.py --source "...\Dimasik Portable" --out build\game.zip --level 1
```

Архив и JAR в git не попадают (`.gitignore`), они живут в GitHub Releases.

## 5. Деплой на Render

1. `deploy.env` должен содержать `GITHUB_TOKEN` и `RENDER_API_KEY`
   (Render → Account Settings → API Keys).
2. Проверка токенов, без создания ресурсов:

```powershell
python deploy_render.py --check
```

3. Полный деплой:

```powershell
python deploy_render.py
```

Если провайдер блокирует адреса Render (таймауты/TLS reset на `api.render.com`),
в `deploy.env` можно указать доступный edge Cloudflare — сертификат и SNI
останутся `render.com`:

```ini
RENDER_EDGE_IP=104.18.0.1
```

Скрипт сам:

1. создаёт **приватный** репозиторий `aurum-client` (если его нет);
2. делает `git init`, commit и push (remote с токеном подставляется только на время push);
3. создаёт Postgres `aurum-db` и берёт internal connection string;
4. создаёт Web Service `aurum-auth` (Python 3.12, free, frankfurt) с health-check
   `/api/health`;
5. прописывает `DATABASE_URL`, `SECRET_KEY`, `ADMIN_TOKEN` и ждёт статус `live`.

Ожидаемый адрес: `https://aurum-auth.onrender.com`.

**Единственный ручной шаг для приватного репозитория:** Render видит приватные
репозитории только после установки GitHub App. Один раз в браузере:
Dashboard → Account Settings → GitHub → Configure → дать доступ к `aurum-client`.
Скрипт напишет это же сообщение, если сервис не создастся. Полностью без браузера:
`python deploy_render.py --public` (репозиторий станет публичным).

## 6. После деплоя

1. Render → сервис `aurum-auth` → Environment → скопировать `ADMIN_TOKEN`.
2. Зарегистрироваться в лаунчере и выдать себе подписку:

```powershell
curl -X POST https://aurum-auth.onrender.com/api/admin/grant `
  -H "X-Admin-Token: ВАШ_ADMIN_TOKEN" -H "Content-Type: application/json" `
  -d '{\"username\":\"ваш_логин\",\"days\":30,\"plan\":\"premium\"}'
```

3. В лаунчере указать `https://aurum-auth.onrender.com`, войти — среда скачается
   автоматически, затем «Играть».

## 7. Переменные окружения Render

| Переменная | Обязательна | Назначение |
|---|---|---|
| `DATABASE_URL` | да (иначе SQLite) | Postgres; `postgres://` нормализуется автоматически |
| `SECRET_KEY` | да | подпись JWT, генерируется скриптом |
| `ADMIN_TOKEN` | для админки | заголовок `X-Admin-Token` |
| `ALLOW_REGISTRATION` | нет | `0` закрывает регистрацию |
| `TOKEN_TTL_SECONDS` | нет | срок жизни токена, по умолчанию 43200 |
| `GAME_URL` / `GAME_SHA256` / `GAME_SIZE` / `GAME_VERSION` | да | среда игры для лаунчера |
| `JAR_URL` / `JAR_SHA256` / `JAR_SIZE` | желательно | клиент в GitHub Releases |
| `JAR_PATH` / `GAME_PATH` | нет | локальные файлы вместо URL |
| `CORS_ORIGINS` | нет | по умолчанию `*` |

## 8. Ограничения и безопасность

- Free web service Render засыпает после 15 минут простоя: первый запрос —
  холодный старт 30–60 секунд. Лаунчер это переживает (таймаут 25 с на запрос,
  120 с на скачивание).
- Диск на free-тарифе эфемерный, поэтому аккаунты — в Postgres. Если Postgres
  создать не удалось, скрипт предупредит: данные будут теряться при рестарте.
- Файлы игры лежат в публичном репозитории релизов: ссылку можно передать, но
  манифест выдаётся только по токену с активной подпиской. Для жёсткой защиты
  нужны подписанные URL (S3/Cloudflare R2).
- HWID присылает клиент: это защита от «поделиться аккаунтом», а не от реверса.
  Лаунчер стоит обфусцировать перед релизом.
- Токены (`GITHUB_TOKEN`, `RENDER_API_KEY`) лежат только в `deploy.env`, он в
  `.gitignore`. `deploy_render.py` больше не содержит ключей.
- Пароли не логируются, ответ на неверный логин и пароль одинаковый,
  `/docs` FastAPI отключена.

## 9. Что проверено на этой машине

- 17/17 сквозных проверок: манифест без подписки → 403, выдача подписки,
  скачивание архива байт в байт, распаковка, JAR в `offline-run/game/mods`,
  запуск `.bat`, отказ при неверном SHA-256, запрет zip-slip, отсутствие
  `Authorization` при загрузке с чужого домена.
- Окно лаунчера: вход → автоматическая установка → прогресс 100% → «Играть»
  запускает игру из `%APPDATA%\AurumClient\game`.
- `python deploy_render.py --check` проверяет ключ Render и токен GitHub.
