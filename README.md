# Telegram Manager

Локальная веб-панель для работы с Telegram-группами. На текущем этапе доступны каркас интерфейса, проверка состояния backend и единый локальный запуск.

## Требования

- Python 3.11 или новее;
- Node.js 20 или новее;
- npm.

## Установка

Команды ниже выполняются из корня проекта.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm --prefix frontend ci
Copy-Item .env.example .env
```

Файл `.env` необязателен: приложение по умолчанию слушает только `127.0.0.1:8000`.

## Обычный запуск

Соберите интерфейс и запустите приложение:

```powershell
npm --prefix frontend run build
python launcher.py
```

Launcher дождётся ответа backend и откроет `http://127.0.0.1:8000`. Для запуска без браузера используйте `python launcher.py --no-browser`. Остановка — `Ctrl+C`.

## Режим разработки

Backend и Vite запускаются в разных терминалах:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix frontend run dev
```

Панель будет доступна по адресу `http://127.0.0.1:5173`; запросы `/api` Vite направляет на FastAPI.

## Проверка

```powershell
python -m pytest
npm --prefix frontend run build
```

Проверить backend вручную можно командой:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## Настройки

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `TELEGRAM_MANAGER_HOST` | `127.0.0.1` | Адрес backend |
| `TELEGRAM_MANAGER_PORT` | `8000` | Порт backend |
| `TELEGRAM_MANAGER_CORS_ORIGINS` | адреса Vite на порту `5173` | Разрешённые источники frontend |
| `TELEGRAM_MANAGER_DATA_DIR` | `data` в корне проекта | Каталог локальных данных |
| `TELEGRAM_MANAGER_DEBUG` | `false` | Включает `/api/docs` и OpenAPI |
| `TELEGRAM_MANAGER_LOG_LEVEL` | `INFO` | Уровень журналирования |

Секреты, Telegram-сессии и каталог `data` не должны попадать в систему контроля версий. Приложение рассчитано на локальный запуск; не меняйте адрес на публичный без отдельной настройки безопасности.
