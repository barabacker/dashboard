# Dashboard

Django-проект с админкой на [Unfold](https://unfoldadmin.com/). Стартовый каркас:
настроенная тема и оформленные пользователи с группами. Доменных моделей пока
нет — они добавляются в приложение `core`.

## Стек

| | |
|---|---|
| Django | 5.2 |
| django-unfold | 0.91 |
| БД | SQLite (файл `db.sqlite3`) |
| Очередь и расписания | Celery + Redis, django-celery-beat |
| Пакеты и venv | [uv](https://docs.astral.sh/uv/) — `pyproject.toml` + `uv.lock` |

Системных зависимостей нет. Нужен только `uv` — нужный Python он поставит сам.

## Запуск

```bash
make install     # uv sync: создаст .venv и поставит зависимости по локу
make migrate
make superuser
make run
```

Админка: http://127.0.0.1:8000/admin/

Без Makefile — то же самое напрямую:

```bash
uv sync
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

`uv run` сам поднимает окружение — активировать venv не нужно.
Если uv ещё не стоит:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                  # macOS / Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"        # Windows
```

## Команды

`make help` покажет список. Основное:

| Команда | Что делает |
|---|---|
| `make install` / `make sync` | зависимости: по локу / строго по локу, без перерешения |
| `make lock` / `make upgrade` | пересобрать лок / поднять версии в пределах ограничений |
| `make run` | сервер разработки, порт меняется через `PORT=8080` |
| `make worker` / `make beat` | celery-воркер / планировщик (нужен Redis) |
| `make migrate` / `make migrations` | применить / создать миграции |
| `make test` | тесты |
| `make lint` / `make fmt` | проверить / отформатировать код (ruff) |
| `make check` | `manage.py check` + проверка несозданных миграций |
| `make ci` | всё, что гоняет CI: lint + check + test |
| `make clean` / `make distclean` | убрать кэши / ещё и venv с базой |

## Структура

```
config/settings.py   настройки проекта и словарь UNFOLD (сайдбар, цвета, тема)
config/urls.py       / → редирект на /admin/
config/celery.py     приложение Celery, автопоиск задач по INSTALLED_APPS
core/admin.py        оформленные UserAdmin и GroupAdmin, модели beat под Unfold
core/models.py       место для доменных моделей
core/tasks.py        задачи Celery
core/management/commands/run_task.py   поставить задачу в очередь из консоли
core/migrations/0001_hourly_session_cleanup.py   заводит периодическую задачу
core/tests.py        тесты доступа и рендера страниц админки
core/tests_tasks.py  тесты задач и расписания
templates/           переопределения шаблонов админки, если понадобятся
```

## Как это настроено

**Unfold идёт первым в `INSTALLED_APPS`** — до `django.contrib.admin`, иначе его шаблоны не подхватятся.

**Своя админ-модель наследует ModelAdmin из Unfold:**

```python
from unfold.admin import ModelAdmin

@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("title", "created_at")
```

Для моделей, у которых уже есть готовый ModelAdmin (User, Group), миксуются оба —
см. `core/admin.py`.

**Сайдбар** задаётся вручную в `UNFOLD["SIDEBAR"]["navigation"]` — новые разделы
нужно дописывать туда, автоматически они не появляются.

## Фоновые задачи

Три процесса: Django, celery-воркер и планировщик beat. Брокер — Redis.

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine   # или локальный redis-server
make worker    # в отдельном терминале
make beat      # в третьем
```

Адрес брокера меняется переменной `CELERY_BROKER_URL` (по умолчанию `redis://127.0.0.1:6379/0`).

**Одноразовая задача** — `core.tasks.say_hello`. Ставится в очередь по требованию:

```python
from core.tasks import say_hello
say_hello.delay("Пётр")
```

```bash
make run-task ARGS="say_hello --name Пётр"      # или напрямую:
uv run manage.py run_task say_hello --name Пётр
uv run manage.py run_task say_hello --now       # выполнить тут же, без очереди
```

Разовый запуск в заданное время делается без кода: в админке создать
Clocked-расписание, задачу с ним и галочкой «одноразовая задача».

**Задача по расписанию** — `core.tasks.cleanup_expired_sessions`, чистит протухшие
сессии каждый час в :30. Расписание заводит миграция `core/0001`, дальше оно живёт
в БД и правится в админке (раздел «Задачи» → «Периодические задачи»): можно менять
cron, выключать и включать — перезапуск beat не нужен, изменения подхватываются сами.

Новые задачи кладутся в `core/tasks.py` с декоратором `@shared_task` — Celery
находит их сам.

Оговорка по интерфейсу: список периодических задач выглядит как остальная админка,
а вот **форма редактирования рендерится стандартными виджетами Django** — у
django-celery-beat своя форма, Unfold её не стилизует. Лечится только своей формой.

## CI

GitHub Actions (`.github/workflows/ci.yml`) на каждый push в `main` и на каждый PR:

| Job | Что делает |
|---|---|
| Линтер | `uv sync --locked`, затем `ruff check` + `ruff format --check` |
| Тесты | `manage.py check`, проверка несозданных миграций, `manage.py test`, `collectstatic` на Python 3.11 / 3.12 / 3.13 |

Оба job'а ставят зависимости через `uv sync --locked`: версии берутся из `uv.lock`,
CI падает, если лок разошёлся с `pyproject.toml`. После правки зависимостей нужно
закоммитить обновлённый `uv.lock` (`make lock`).

Локально то же самое — `make ci`.

## Настройки окружения

| Переменная | По умолчанию |
|---|---|
| `DJANGO_SECRET_KEY` | небезопасный ключ для разработки |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `*` |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` |

Перед деплоем задать все три.

## Зависимости

Добавить пакет: `uv add <пакет>` (в dev-группу: `uv add --dev <пакет>`) — uv сам
обновит `pyproject.toml`, `uv.lock` и окружение. Удалить: `uv remove <пакет>`.
`uv.lock` коммитится, `.venv/` — нет.

## Что дальше

- Доменные модели в `core` (или отдельными приложениями) + их `ModelAdmin`.
- Свой дашборд на главной, когда будет что показывать: шаблон
  `templates/admin/index.html` плюс `UNFOLD["DASHBOARD_CALLBACK"]`.
- Русская локаль для Unfold: часть строк интерфейса («Type to search», «Filters»)
  остаётся английской, лечится собственным `.po`-файлом.
- Гео-слой (SpatiaLite + GDAL + карты в формах) — рабочий вариант лежит в истории,
  коммит `d5efad7`: `git show d5efad7 --stat`.
